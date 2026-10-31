from datetime import UTC, datetime, timedelta

import httpx
import pytest

from procurement.sources.gosplan_queue import GosplanQueue, QueueError
from procurement.sources.gosplan_scan import scan_page

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def client(offsets, *, second_fails=False):
    def handler(request):
        offset = int(request.url.params["skip"])
        offsets.append(offset)
        if second_fails and offset == 100:
            return httpx.Response(429)
        rows = [
            {
                "purchase_number": str(32600000000 + offset + i),
                "purchase_type": "purchaseNotice",
                "updated_at": None,
            }
            for i in range(100 if offset == 0 else 1)
        ]
        return httpx.Response(200, json=rows)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_restart_continues_only_after_durable_page(tmp_path):
    path = tmp_path / "queue.sqlite"
    offsets = []
    queue = GosplanQueue(path)
    with client(offsets) as c:
        result = scan_page(c, "secret", queue, "one", "223", NOW)
    assert result.next_offset == 100 and result.coverage == "UNKNOWN"
    queue.close()
    queue = GosplanQueue(path)
    with client(offsets) as c:
        result = scan_page(c, "secret", queue, "one", "223", NOW + timedelta(hours=1))
    assert offsets == [0, 100] and result.reason == "SHORT_PAGE"
    assert len(queue.pending("one")) == 101
    assert queue.conn.execute("SELECT count(*) FROM scan_cursors").fetchone()[0] == 0
    queue.close()


def test_failure_never_advances_and_expired_window_restarts(tmp_path):
    offsets = []
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with client(offsets, second_fails=True) as c:
        scan_page(c, "secret", queue, "one", "223", NOW)
        failed = scan_page(c, "secret", queue, "one", "223", NOW + timedelta(hours=1))
        assert failed.status == "UNKNOWN" and failed.next_offset == 100
        held = scan_page(c, "secret", queue, "one", "223", NOW + timedelta(hours=6))
        assert held.reason == "PROVIDER_HOLD"
    assert offsets == [0, 100]
    queue.close()


def test_corrupt_cursor_fails_before_network(tmp_path):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with queue.conn:
        queue.conn.execute(
            "INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)",
            (
                "one",
                "223",
                NOW.isoformat(),
                (NOW - timedelta(days=1)).isoformat(),
                NOW.isoformat(),
                7,
            ),
        )
    offsets = []
    with client(offsets) as c, pytest.raises(QueueError, match="SCAN_CURSOR_INVALID"):
        scan_page(c, "secret", queue, "one", "223", NOW)
    assert offsets == []
    queue.close()


def test_crash_between_page_and_cursor_replays_without_skipping(tmp_path, monkeypatch):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    offsets = []
    original = queue.record

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated crash after durable page")

    with monkeypatch.context() as patch, client(offsets) as c:
        patch.setattr(queue, "record", interrupted)
        with pytest.raises(RuntimeError, match="simulated crash"):
            scan_page(c, "secret", queue, "one", "223", NOW)
    assert len(queue.pending("one")) == 100
    assert queue.conn.execute("SELECT count(*) FROM scan_cursors").fetchone()[0] == 0
    with client(offsets) as c:
        held = scan_page(c, "secret", queue, "one", "223", NOW + timedelta(minutes=1))
    assert held.reason == "PROVIDER_HOLD" and offsets == [0]
    hold = queue.conn.execute("SELECT reason FROM provider_holds").fetchone()[0]
    assert hold == "REQUEST_IN_FLIGHT"
    # Simulate explicit reconciliation after inspecting the retained page and cursor.
    with queue.conn:
        queue.conn.execute("DELETE FROM provider_holds WHERE company='one'")
        queue.conn.execute("DELETE FROM inflight_scans WHERE company='one'")
    with client(offsets) as c:
        result = scan_page(c, "secret", queue, "one", "223", NOW + timedelta(minutes=1))
    assert offsets == [0, 0] and result.next_offset == 100
    queue.close()


def test_429_blocks_other_law_and_persists_across_restart(tmp_path):
    path = tmp_path / "queue.sqlite"
    queue = GosplanQueue(path)
    calls = []

    def denied(request):
        calls.append(request.url.path)
        return httpx.Response(429)

    with httpx.Client(transport=httpx.MockTransport(denied)) as c:
        assert scan_page(c, "secret", queue, "one", "223", NOW).reason == "HTTP_429"
    queue.close()
    queue = GosplanQueue(path)
    with httpx.Client(transport=httpx.MockTransport(denied)) as c:
        assert (
            scan_page(c, "secret", queue, "one", "44", NOW + timedelta(days=10)).reason
            == "PROVIDER_HOLD"
        )
    assert len(calls) == 1
    queue.close()


@pytest.mark.parametrize(("law", "number"), [("44", "0000000000000000001"), ("223", "00000000001")])
def test_null_type_retains_complete_page_and_audit_without_admission(tmp_path, law, number):
    import hashlib
    import json

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    payload = json.dumps([{"purchase_number": number, "purchase_type": None}]).encode()
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    with httpx.Client(transport=transport) as c:
        result = scan_page(c, "secret", queue, "one", law, NOW)
        assert result.status == "UNKNOWN" and result.reason == "TYPE_INVALID"
        assert scan_page(c, "secret", queue, "one", law, NOW).reason == "PROVIDER_HOLD"
    assert queue.pending("one") == []
    assert queue.conn.execute("SELECT count(*) FROM scan_cursors").fetchone()[0] == 0
    stored = queue.conn.execute(
        "SELECT company,response_sha,reason,raw FROM rejected_pages"
    ).fetchone()
    assert stored == ("one", hashlib.sha256(payload).hexdigest(), "TYPE_INVALID", payload)
    assert queue.conn.execute("SELECT event FROM rejected_page_audit").fetchone()[0] == (
        "QUARANTINED_UNKNOWN"
    )
    count_other = queue.conn.execute(
        "SELECT count(*) FROM rejected_pages WHERE company='other'"
    ).fetchone()[0]
    assert count_other == 0
    assert queue.conn.execute("SELECT reason,until_at FROM provider_holds").fetchone() == (
        "TYPE_INVALID",
        None,
    )
    queue.close()


def test_null_at_observed_page_position_quarantines_whole_page_without_cursor_advance(tmp_path):
    """Synthetic replay of the independent 44-FZ diagnostic, not the lost old response."""
    import hashlib
    import json

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    cursor = (
        "one",
        "44",
        NOW.isoformat(),
        (NOW - timedelta(days=1)).isoformat(),
        NOW.isoformat(),
        300,
    )
    with queue.conn:
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", cursor)
    rows = [
        {"purchase_number": f"{index + 1:019d}", "purchase_type": "epNotificationEF2020"}
        for index in range(100)
    ]
    rows[81]["purchase_type"] = None
    payload = json.dumps(rows).encode()
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    with httpx.Client(transport=transport) as c:
        result = scan_page(c, "secret", queue, "one", "44", NOW)
    assert (result.status, result.reason, result.next_offset) == ("UNKNOWN", "TYPE_INVALID", 300)
    assert queue.pending("one") == []
    assert queue.conn.execute("SELECT * FROM scan_cursors").fetchone() == cursor
    assert queue.conn.execute("SELECT response_sha, raw FROM rejected_pages").fetchone() == (
        hashlib.sha256(payload).hexdigest(),
        payload,
    )
    assert queue.conn.execute("SELECT event FROM rejected_page_audit").fetchone() == (
        "QUARANTINED_UNKNOWN",
    )
    queue.close()


def test_quarantine_does_not_replace_existing_429_hold(tmp_path):
    import json

    from procurement.sources.gosplan_queue import Scope

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with queue.conn:
        queue.conn.execute("INSERT INTO provider_holds VALUES ('one','HTTP_429',NULL)")
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 0, 100)
    raw = json.dumps([{"purchase_number": "0000000000000000001", "purchase_type": None}]).encode()
    with pytest.raises(QueueError, match="PROVIDER_HOLD_CHANGED"):
        queue.quarantine_and_hold(scope, raw, NOW, "TYPE_INVALID", None)
    assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone()[0] == "HTTP_429"
    assert queue.conn.execute("SELECT count(*) FROM rejected_pages").fetchone()[0] == 0
    queue.close()


def test_rejected_page_write_failure_leaves_inflight_hold_after_restart(tmp_path, monkeypatch):
    path = tmp_path / "queue.sqlite"
    queue = GosplanQueue(path)
    calls = []

    def response(request):
        calls.append(request.url.path)
        return httpx.Response(
            200, json=[{"purchase_number": "0000000000000000001", "purchase_type": None}]
        )

    def fail(*_args):
        raise OSError("synthetic storage failure")

    with monkeypatch.context() as patch, httpx.Client(transport=httpx.MockTransport(response)) as c:
        patch.setattr(queue, "quarantine_and_hold", fail)
        with pytest.raises(OSError):
            scan_page(c, "secret", queue, "one", "44", NOW)
    queue.close()
    queue = GosplanQueue(path)
    with httpx.Client(transport=httpx.MockTransport(response)) as c:
        result = scan_page(c, "secret", queue, "one", "223", NOW + timedelta(hours=1))
    assert result.reason == "PROVIDER_HOLD" and len(calls) == 1
    hold = queue.conn.execute("SELECT reason FROM provider_holds").fetchone()[0]
    assert hold == "REQUEST_IN_FLIGHT"
    assert queue.conn.execute("SELECT count(*) FROM inflight_scans").fetchone()[0] == 1
    assert queue.conn.execute("SELECT count(*) FROM rejected_pages").fetchone()[0] == 0
    queue.close()


def test_quarantine_replay_is_idempotent_and_conflicting_payload_does_not_change_hold(tmp_path):
    import json

    from procurement.sources.gosplan_queue import Scope

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 0, 100)
    raw = json.dumps([{"purchase_number": "0000000000000000001", "purchase_type": None}]).encode()
    assert queue.quarantine_and_hold(scope, raw, NOW, "TYPE_INVALID", None)
    assert queue.quarantine_and_hold(scope, raw, NOW, "TYPE_INVALID", None)
    other = json.dumps([{"purchase_number": "0000000000000000002", "purchase_type": None}]).encode()
    with pytest.raises(QueueError, match="PROVIDER_HOLD_CHANGED"):
        queue.quarantine_and_hold(scope, other, NOW, "TYPE_INVALID", None)
    assert queue.conn.execute("SELECT count(*) FROM rejected_pages").fetchone()[0] == 1
    assert queue.conn.execute("SELECT count(*) FROM rejected_page_audit").fetchone()[0] == 1
    queue.close()


def test_quarantine_and_new_provider_hold_are_serialized_across_connections(tmp_path):
    import json
    import sqlite3
    import threading

    from procurement.sources.gosplan_queue import Scope

    path = tmp_path / "queue.sqlite"
    queue = GosplanQueue(path)
    locked = threading.Event()
    release = threading.Event()

    def set_rate_limit():
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO provider_holds VALUES ('one','HTTP_429',NULL)")
        locked.set()
        assert release.wait(2)
        conn.commit()
        conn.close()

    worker = threading.Thread(target=set_rate_limit)
    worker.start()
    assert locked.wait(2)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 0, 100)
    raw = json.dumps([{"purchase_number": "0000000000000000001", "purchase_type": None}]).encode()
    with pytest.raises(QueueError, match="PROVIDER_HOLD_CHANGED"):
        queue.quarantine_and_hold(scope, raw, NOW, "TYPE_INVALID", None)
    worker.join(2)
    timer.join(2)
    assert not worker.is_alive()
    assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone()[0] == "HTTP_429"
    assert queue.conn.execute("SELECT count(*) FROM rejected_pages").fetchone()[0] == 0
    queue.close()


@pytest.mark.parametrize("response_kind", ["valid", "null", "rate_limit"])
def test_late_response_cannot_modify_a_replaced_inflight_request(tmp_path, response_kind):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    replacement = "new-request-after-explicit-reconciliation"

    def handler(_request):
        with queue.conn:
            queue.conn.execute(
                "UPDATE inflight_scans SET attempt_id=? WHERE company='one'", (replacement,)
            )
        if response_kind == "rate_limit":
            return httpx.Response(429)
        kind = None if response_kind == "null" else "epNotificationEZT2020"
        return httpx.Response(
            200, json=[{"purchase_number": "0000000000000000001", "purchase_type": kind}]
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        if response_kind == "valid":
            result = scan_page(c, "secret", queue, "one", "44", NOW)
            assert result.reason == "INFLIGHT_BINDING_CHANGED"
        else:
            with pytest.raises(QueueError, match="INFLIGHT_BINDING_CHANGED"):
                scan_page(c, "secret", queue, "one", "44", NOW)
    assert queue.conn.execute("SELECT attempt_id FROM inflight_scans").fetchone()[0] == replacement
    hold = queue.conn.execute("SELECT reason FROM provider_holds").fetchone()[0]
    assert hold == "REQUEST_IN_FLIGHT"
    assert queue.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
    assert queue.conn.execute("SELECT count(*) FROM rejected_pages").fetchone()[0] == 0
    assert queue.conn.execute("SELECT count(*) FROM scan_cursors").fetchone()[0] == 0
    queue.close()


def test_token_reflection_is_never_saved_in_quarantine(tmp_path):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    raw = b'[{"purchase_number":"0000000000000000001","purchase_type":"secret"}]'
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=raw))
    with httpx.Client(transport=transport) as c:
        result = scan_page(c, "secret", queue, "one", "44", NOW)
    assert result.reason == "TOKEN_REFLECTION_REJECTED"
    assert queue.conn.execute("SELECT count(*) FROM rejected_pages").fetchone()[0] == 0
    assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone()[0] == (
        "TOKEN_REFLECTION_REJECTED"
    )
    queue.close()


def test_legacy_cursor_replays_old_window_and_closes_only_after_short_page(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 300, 100)
    cursor = ("44", NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(), NOW.isoformat(), 300)
    with queue.conn:
        queue.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
    queue.resolve_legacy_type_hold(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=NOW,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(cursor,),
    )
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        offset = int(request.url.params["skip"])
        rows = [
            {"purchase_number": f"{offset + i + 1:019d}", "purchase_type": "epNotificationEF2020"}
            for i in range(100 if offset == 300 else 1)
        ]
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        first = scan_page(c, "secret", queue, "one", "44", NOW + timedelta(hours=8))
        assert first.next_offset == 400
        assert queue.conn.execute("SELECT offset FROM legacy_scan_resumptions").fetchone() == (400,)
        second = scan_page(c, "secret", queue, "one", "44", NOW + timedelta(hours=8, minutes=1))
    assert second.reason == "SHORT_PAGE" and second.coverage == "UNKNOWN"
    assert [s["skip"] for s in seen] == ["300", "400"]
    assert queue.conn.execute("SELECT count(*) FROM scan_cursors").fetchone() == (0,)
    assert queue.conn.execute("SELECT count(*) FROM legacy_scan_resumptions").fetchone() == (0,)
    queue.close()


def test_legacy_resume_offset_limit_retains_cursor_and_hold(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 1000, 100)
    cursor = ("44", NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(), NOW.isoformat(), 1000)
    with queue.conn:
        queue.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
    queue.resolve_legacy_type_hold(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=NOW,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(cursor,),
    )
    rows = [
        {"purchase_number": f"{i + 1:019d}", "purchase_type": "epNotificationEF2020"}
        for i in range(100)
    ]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as c:
        result = scan_page(c, "secret", queue, "one", "44", NOW + timedelta(hours=8))
    assert (result.status, result.reason, result.next_offset) == ("UNKNOWN", "OFFSET_LIMIT", 1000)
    assert queue.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (1000,)
    assert queue.conn.execute("SELECT offset FROM legacy_scan_resumptions").fetchone() == (1000,)
    assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("OFFSET_LIMIT",)
    queue.close()


def test_legacy_resume_null_keeps_scope_cursor_and_unknown_quarantine(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 300, 100)
    cursor = ("44", NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(), NOW.isoformat(), 300)
    with queue.conn:
        queue.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
    queue.resolve_legacy_type_hold(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=NOW,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(cursor,),
    )
    payload = [{"purchase_number": "0" * 18 + "1", "purchase_type": None}]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as c:
        result = scan_page(c, "secret", queue, "one", "44", NOW + timedelta(hours=8))
    assert (result.status, result.reason) == ("UNKNOWN", "TYPE_INVALID")
    assert queue.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (300,)
    assert queue.conn.execute("SELECT offset FROM legacy_scan_resumptions").fetchone() == (300,)
    assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("TYPE_INVALID",)
    assert queue.conn.execute("SELECT event FROM rejected_page_audit").fetchone() == (
        "QUARANTINED_UNKNOWN",
    )
    assert queue.pending("one") == []
    queue.close()


def test_legacy_resume_crash_after_record_keeps_inflight_hold_and_marker(tmp_path, monkeypatch):
    from procurement.sources.gosplan_queue import Scope

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 300, 100)
    cursor = ("44", NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(), NOW.isoformat(), 300)
    with queue.conn:
        queue.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
    queue.resolve_legacy_type_hold(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=NOW,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(cursor,),
    )
    original = queue.record

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic crash")

    monkeypatch.setattr(queue, "record", crash)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json=[
                        {"purchase_number": "0" * 18 + "1", "purchase_type": "epNotificationEF2020"}
                    ],
                )
            )
        ) as c,
        pytest.raises(RuntimeError, match="synthetic crash"),
    ):
        scan_page(c, "secret", queue, "one", "44", NOW + timedelta(hours=8))
    assert queue.conn.execute("SELECT offset FROM legacy_scan_resumptions").fetchone() == (300,)
    assert queue.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (300,)
    assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone() == (
        "REQUEST_IN_FLIGHT",
    )
    queue.close()


def test_legacy_resume_concurrent_scanners_allow_only_one_source_request(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from procurement.sources.gosplan_queue import Scope

    path = tmp_path / "queue.sqlite"
    q = GosplanQueue(path)
    scope = Scope("one", "44", NOW - timedelta(days=1), NOW, 300, 100)
    cursor = ("44", NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(), NOW.isoformat(), 300)
    with q.conn:
        q.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        q.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
    q.resolve_legacy_type_hold(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=NOW,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(cursor,),
    )
    q.close()
    entered = Event()
    release = Event()
    requests = []

    def handler(_):
        requests.append(1)
        entered.set()
        assert release.wait(5)
        return httpx.Response(
            200, json=[{"purchase_number": "0" * 18 + "1", "purchase_type": "epNotificationEF2020"}]
        )

    def scan():
        queue = GosplanQueue(path)
        try:
            with httpx.Client(transport=httpx.MockTransport(handler)) as c:
                return scan_page(c, "secret", queue, "one", "44", NOW + timedelta(hours=8))
        finally:
            queue.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(scan)
        assert entered.wait(5)
        second = pool.submit(scan).result(timeout=5)
        release.set()
        successful = first.result(timeout=5)
    assert (
        requests == [1] and second.reason == "PROVIDER_HOLD" and successful.reason == "SHORT_PAGE"
    )


@pytest.mark.parametrize("law", ["44", "223"])
@pytest.mark.parametrize("count", [1, 100])
def test_provider_limit_page_preserves_unknown_and_cursor(tmp_path, law, count):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    cursor = ("one", law, NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(),
              NOW.isoformat(), 1000)
    with queue.conn:
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", cursor)
    seen = []

    def handler(request):
        seen.append(int(request.url.params["skip"]))
        rows = [{"purchase_number": f"{i + 1:0{19 if law == '44' else 11}d}",
                 "purchase_type": "epNotificationEF2020" if law == "44" else "purchaseNotice"}
                for i in range(count)]
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        result = scan_page(c, "secret", queue, "one", law, NOW + timedelta(minutes=1))
    assert seen == [1000] and result.coverage == "UNKNOWN"
    assert queue.conn.execute("SELECT count(*) FROM observations").fetchone() == (1,)
    assert len(queue.pending("one")) == count
    if count == 100:
        assert (result.status, result.reason, result.next_offset) == (
            "UNKNOWN", "OFFSET_LIMIT", 1000
        )
        assert queue.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (1000,)
        assert queue.conn.execute("SELECT reason FROM provider_holds").fetchone() == (
            "OFFSET_LIMIT",
        )
    else:
        assert (result.status, result.reason) == ("STOPPED", "SHORT_PAGE")
        assert queue.conn.execute("SELECT count(*) FROM scan_cursors").fetchone() == (0,)
        assert queue.conn.execute("SELECT count(*) FROM provider_holds").fetchone() == (0,)
    queue.close()


@pytest.mark.parametrize("law", ["44", "223"])
def test_existing_out_of_range_cursor_no_network_or_state_change(tmp_path, law):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    cursor = ("one", law, NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(),
              NOW.isoformat(), 1100)
    with queue.conn:
        queue.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", cursor)
    seen = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r))) as c:
        result = scan_page(c, "secret", queue, "one", law, NOW + timedelta(hours=8))
    assert (result.status, result.reason, result.next_offset) == ("UNKNOWN", "OFFSET_LIMIT", 1100)
    assert not seen and queue.conn.execute("SELECT * FROM scan_cursors").fetchone() == cursor
    assert queue.conn.execute("SELECT count(*) FROM provider_holds").fetchone() == (0,)
    assert queue.conn.execute("SELECT count(*) FROM inflight_scans").fetchone() == (0,)
    queue.close()
