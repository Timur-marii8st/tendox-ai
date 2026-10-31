import json
import runpy
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from procurement.sources.gosplan_discovery import parse_page
from procurement.sources.gosplan_queue import GosplanQueue, Scope

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/server-gosplan-discovery.py"
NOW = datetime(2026, 10, 28, tzinfo=UTC)


class Storage:
    def __init__(self, present=()):
        self.present = present

    @contextmanager
    def transaction(self, company, *, consistent_read):
        assert company == "local-eis-supplier" and consistent_read
        yield self

    def execute(self, statement):
        assert "SET LOCAL" in str(statement)

    def scalars(self, statement):
        return iter(self.present)


def record(queue, law, rows):
    raw = json.dumps(rows).encode()
    scope = Scope("local-eis-supplier", law, NOW - timedelta(days=1), NOW, 0, 100)
    queue.record(scope, parse_page(raw, law, NOW, 100), NOW)


def row(number, family):
    return {"purchase_number": number, "purchase_type": family, "updated_at": None}


def test_secret_requires_owner_private_regular_file(tmp_path):
    read_secret = runpy.run_path(str(SCRIPT))["read_secret"]
    file = tmp_path / "key"
    file.write_text("private-key\n")
    file.chmod(0o600)
    assert read_secret(file) == "private-key"
    file.chmod(0o644)
    with pytest.raises(ValueError, match="SECRET_PERMISSIONS_INVALID"):
        read_secret(file)
    link = tmp_path / "link"
    link.symlink_to(file)
    with pytest.raises(OSError):
        read_secret(link)


def test_select_only_missing_never_retry_any_attempt(tmp_path):
    choose = runpy.run_path(str(SCRIPT))["choose_candidate"]
    queue = GosplanQueue(tmp_path / "q.sqlite")
    nums = ("0122100003226000061", "0122100003226000062", "0122100003226000063")
    record(queue, "44", [row(num, "epNotificationEF2020") for num in nums])
    attempt = queue.claim("local-eis-supplier", "44", nums[1], NOW)
    queue.finish("local-eis-supplier", attempt, "UNKNOWN", None)
    assert choose(queue, Storage((nums[0],)), "44") == nums[2]
    queue.close()


def test_select_only_supported_223_family(tmp_path):
    choose = runpy.run_path(str(SCRIPT))["choose_candidate"]
    queue = GosplanQueue(tmp_path / "q.sqlite")
    record(
        queue,
        "223",
        [row("32616349721", "purchaseNotice"), row("32616349722", "purchaseNoticeKESMBO")],
    )
    assert choose(queue, Storage(), "223") == "32616349722"
    queue.close()


def test_existing_identity_cleanup_keeps_source_and_active_claim(tmp_path):
    choose = runpy.run_path(str(SCRIPT))["choose_candidate"]
    queue = GosplanQueue(tmp_path / "q.sqlite")
    nums = ("0122100003226000061", "0122100003226000062", "0122100003226000063")
    record(queue, "44", [row(num, "epNotificationEF2020") for num in nums])
    queue.claim("local-eis-supplier", "44", nums[1], NOW)
    assert choose(queue, Storage((nums[0], nums[1])), "44") == nums[2]
    assert {r[1] for r in queue.pending("local-eis-supplier")} == {nums[1], nums[2]}
    assert queue.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
    assert (
        queue.conn.execute(
            "SELECT count(*) FROM audit WHERE event LIKE 'IDENTITY_PRESENT/%'"
        ).fetchone()[0]
        == 1
    )
    queue.close()


def test_preflight_requires_all_three_idle():
    from types import SimpleNamespace

    code = runpy.run_path(str(SCRIPT))
    namespace = code["preflight_recovery"].__globals__
    namespace["urgent44_status"] = lambda *args: "IDLE"
    namespace["joint_mandatory_status"] = lambda *args: "IDLE"
    namespace["read_history_demand"] = lambda *args, **kwargs: SimpleNamespace(
        classification=SimpleNamespace(status="BLOCKED")
    )
    assert code["preflight_recovery"](object()) is False
    namespace["read_history_demand"] = lambda *args, **kwargs: SimpleNamespace(
        classification=SimpleNamespace(status="IDLE")
    )
    assert code["preflight_recovery"](object()) is True
    namespace["urgent44_status"] = lambda *args: "READY"
    namespace["read_history_demand"] = lambda *args, **kwargs: SimpleNamespace(
        classification=SimpleNamespace(status="READY")
    )
    assert code["preflight_recovery"](object()) is True
    namespace["urgent44_status"] = lambda *args: "UNKNOWN"
    assert code["preflight_recovery"](object()) is False


def test_select_only_supported_44_family_without_consuming_unsupported(tmp_path):
    choose = runpy.run_path(str(SCRIPT))["choose_candidate"]
    queue = GosplanQueue(tmp_path / "q.sqlite")
    record(queue, "44", [row("0103300000426000007", "epNotificationEZT2020"),
                         row("0164100007326000018", "epNotificationEF2020")])
    assert choose(queue, Storage(), "44") == "0164100007326000018"
    assert {row[1] for row in queue.pending("local-eis-supplier")} == {
        "0103300000426000007", "0164100007326000018"
    }
    assert queue.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    queue.close()


def test_candidate_type_projection_parses_each_observation_once(tmp_path, monkeypatch):
    import procurement.sources.gosplan_queue as module

    queue = GosplanQueue(tmp_path / "q.sqlite")
    rows = [row(str(index).zfill(19), "epNotificationEF2020") for index in range(1, 101)]
    record(queue, "44", rows)
    original = module.parse_page
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(module, "parse_page", counted)
    projection = queue.pending_with_types("local-eis-supplier")
    assert len(projection) == 100 and len(calls) == 1
    assert all(item[3] == "epNotificationEF2020" for item in projection)
    queue.close()


def test_projection_does_not_duplicate_large_source_blob_for_each_candidate(tmp_path):
    import tracemalloc

    queue = GosplanQueue(tmp_path / "q.sqlite")
    rows = [row(str(index).zfill(19), "epNotificationEF2020") for index in range(1, 101)]
    rows[0]["extra_untrusted_content"] = "x" * (1024 * 1024)
    record(queue, "44", rows)
    tracemalloc.start()
    try:
        projection = queue.pending_with_types("local-eis-supplier")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(projection) == 100
    assert peak < 15 * 1024 * 1024
    queue.close()
