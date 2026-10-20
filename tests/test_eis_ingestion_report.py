"""Protect the distinction between planned, empty, transported and searchable data."""

import importlib.util
import sys
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "eis_ingestion_report", ROOT / "scripts/server-eis-ingestion-report.py"
)
reporter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reporter
spec.loader.exec_module(reporter)
NOW = datetime(2026, 10, 5, 7, tzinfo=UTC)
DAY = date(2026, 10, 4)
SHA = "a" * 64


def window(key, **changes):
    values = dict(
        window_key=key,
        planned_at=NOW - timedelta(hours=10),
        attempt_id=None,
        attempted_at=None,
        outcome=None,
        reason_code=None,
        source_response_sha256=None,
        canonical_at=None,
        canonical_response_sha256=None,
        transport_present=False,
        notice_versions=0,
        indexed_versions=0,
        procedure_events=0,
    )
    values.update(changes)
    return reporter.Window(**values)


def attempted(**changes):
    return (
        dict(
            attempt_id="synthetic-attempt",
            attempted_at=NOW - timedelta(hours=1),
            outcome="NO_DATA",
            source_response_sha256=SHA,
        )
        | changes
    )


def report(now=NOW, first=DAY, last=DAY, changes=None):
    scope = reporter.make_scope(first, last, now)
    coordinates = reporter.scope_coordinates(scope)
    windows = tuple(window(key, **(changes or {}).get(key, {})) for key in sorted(coordinates))
    return reporter.Report(
        checked_at=now,
        snapshot="synthetic-snapshot",
        first_day=first,
        last_day=last,
        scope_sha256=scope.sha256,
        expected_windows=scope.expected_windows,
        windows=windows,
        cohorts=reporter.summarize(windows, coordinates, now),
    )


def test_default_ef_uses_legacy_domain_key():
    coordinates = reporter.scope_coordinates(reporter.make_scope(DAY, DAY, NOW))
    assert len(coordinates) == 495
    assert coordinates["getDocsIP/PRIZ/01/2026-10-04+03:00"] == (DAY, "epNotificationEF2020")
    assert not any(key.endswith("/epNotificationEF2020") for key in coordinates)


@pytest.mark.parametrize(
    "first,last",
    [
        (date(2026, 10, 1), DAY),
        (date(2026, 10, 5), date(2026, 10, 5)),
        (DAY, date(2026, 10, 3)),
    ],
)
def test_scope_rejects_oversize_current_day_or_reversed_dates(first, last):
    with pytest.raises(ValueError):
        reporter.make_scope(first, last, NOW)


@pytest.mark.parametrize(
    "changes,state",
    [
        ({"planned_at": None}, "MISSING_PLAN"),
        ({}, "UNATTEMPTED"),
        (attempted(), "NO_DATA"),
        (attempted(outcome="FAILED", reason_code="SOURCE_TRANSPORT_FAILED"), "SOURCE_RETRY"),
        (attempted(outcome="FAILED", reason_code="MEMBER_UNSUPPORTED"), "PARSER_REVIEW"),
        (attempted(outcome="SYNCED"), "UNKNOWN"),
        ({"transport_present": True}, "UNATTEMPTED"),
        (
            attempted()
            | {"canonical_at": NOW - timedelta(minutes=10), "canonical_response_sha256": SHA},
            "CANONICAL",
        ),
    ],
)
def test_disjoint_states_do_not_infer_canonical_from_outcome_or_transport(changes, state):
    assert window("synthetic-key", **changes).state == state


@pytest.mark.parametrize(
    "changes",
    [
        {"notice_versions": 1, "indexed_versions": 2},
        {"attempt_id": "id"},
        attempted(source_response_sha256=None),
        {"canonical_at": NOW},
        {"planned_at": NOW.replace(tzinfo=None)},
        {"reason_code": "https://secret.invalid"},
    ],
)
def test_evidence_validation_rejects_incomplete_or_unsafe_facts(changes):
    with pytest.raises(ValidationError):
        window("synthetic-key", **changes)


def test_scope_and_cohort_counts_cannot_be_forged():
    original = report()
    for change in (
        {"windows": original.windows[:-1]},
        {"scope_sha256": "b" * 64},
        {"windows": (*original.windows[:-1], original.windows[0])},
        {"cohorts": ()},
        {"company_id": "other-tenant"},
    ):
        with pytest.raises(ValidationError):
            reporter.Report.model_validate(original.model_dump() | change)


def test_future_evidence_is_not_clamped_to_current():
    key = report().windows[0].window_key
    with pytest.raises(ValidationError):
        report(changes={key: {"planned_at": NOW + timedelta(seconds=1)}})


def test_ages_and_index_deficit_remain_independent_of_canonical():
    key = report().windows[0].window_key
    result = report(
        changes={
            key: {
                "canonical_at": NOW - timedelta(hours=1),
                "canonical_response_sha256": SHA,
                "notice_versions": 3,
                "indexed_versions": 2,
                "procedure_events": 1,
            }
        }
    )
    cohort = next(c for c in result.cohorts if c.notice_versions)
    assert sum(cohort.states.values()) == 99
    assert cohort.states == {"CANONICAL": 1, "UNATTEMPTED": 98}
    assert cohort.oldest_pending_plan_age_seconds == 36000
    assert cohort.oldest_pending_attempt_age_seconds is None
    assert cohort.max_canonical_completed_day_lag_seconds == 32400
    assert result.coverage == result.freshness == result.document_coverage == "UNKNOWN"


def test_progress_reports_actual_transitions_and_does_not_claim_call_counts():
    before = report()
    a, b = [w.window_key for w in before.windows[:2]]
    after = report(
        now=NOW + timedelta(minutes=5),
        changes={
            a: attempted(),
            b: attempted(outcome="SYNCED")
            | {
                "canonical_at": NOW,
                "canonical_response_sha256": SHA,
                "notice_versions": 5,
                "indexed_versions": 5,
            },
        },
    )
    progress = reporter.compare(before, after)
    assert progress.elapsed_seconds == 300
    assert progress.first_attempt_observed == progress.latest_attempt_changed == 2
    assert progress.newly_canonical == 1 and progress.canonical_regressions == 0
    assert progress.notice_version_delta == progress.indexed_version_delta == 5
    assert progress.state_transitions == {"UNATTEMPTED->CANONICAL": 1, "UNATTEMPTED->NO_DATA": 1}
    assert progress.capacity == progress.source_call_count == "UNKNOWN"


def test_progress_exposes_regression_and_rejects_incomparable_reports():
    key = report().windows[0].window_key
    before = report(changes={key: {"canonical_at": NOW, "canonical_response_sha256": SHA}})
    after = report(now=NOW + timedelta(minutes=1))
    assert reporter.compare(before, after).canonical_regressions == 1
    with pytest.raises(ValueError):
        reporter.compare(after, before)
    with pytest.raises(ValueError):
        reporter.compare(before, report(now=NOW + timedelta(minutes=1), first=date(2026, 10, 3)))


class EmptyResult:
    def all(self):
        return []

    def mappings(self):
        return []

    def scalars(self):
        return []

    def __iter__(self):
        return iter(())


class QueryRecorder:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return EmptyResult()


def test_queries_are_scope_and_tenant_bounded_and_never_select_source_payloads():
    conn = QueryRecorder()
    key = "getDocsIP/PRIZ/01/2026-10-04+03:00"
    result = reporter.read_windows(conn, (key,))
    assert len(result) == 1 and result[0].state == "MISSING_PLAN"
    assert len(conn.statements) == 6
    sql = []
    for statement in conn.statements:
        compiled = statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        value = str(compiled)
        assert "local-eis-supplier" in value and key in value
        assert "SELECT" in value and "source_url" not in value and "content" not in value
        sql.append(value)
    assert "DISTINCT ON" in sql[1] and "attempt_id DESC" in sql[1]
    assert "LEGACY_CANONICAL" in sql[2] and "response_sha256" in sql[2]
    assert "company_id = eis_notice_versions.company_id" in sql[4]
    assert "version_number = eis_notice_versions.version_number" in sql[4]


@pytest.mark.parametrize(
    "readonly,isolation", [("off", "repeatable read"), ("on", "read committed")]
)
def test_main_refuses_unproven_snapshot_modes(monkeypatch, readonly, isolation):
    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = Engine()

    class Connection:
        def scalar(self, statement):
            return readonly if str(statement) == "SHOW transaction_read_only" else isolation

    class Storage:
        def __init__(self, _engine):
            pass

        @contextmanager
        def transaction(self, company, *, consistent_read):
            assert company == reporter.COMPANY and consistent_read is True
            yield Connection()

    monkeypatch.setenv("DATABASE_URL", "synthetic://hidden")
    monkeypatch.setattr(reporter, "create_engine", lambda _: engine)
    monkeypatch.setattr(reporter, "PostgresStorage", Storage)
    with pytest.raises(ValueError, match="REPORT_TRANSACTION"):
        reporter.main(["--first-day", "2026-10-02", "--last-day", "2026-10-04"])
    assert engine.disposed


def test_main_writes_only_metadata_in_private_proof(monkeypatch, tmp_path, capsys):
    fixture = report()

    class Engine:
        def dispose(self):
            pass

    class Connection:
        def scalar(self, statement):
            return {
                "SHOW transaction_read_only": "on",
                "SHOW transaction_isolation": "repeatable read",
                "SELECT pg_current_snapshot()::text": "synthetic-snapshot",
                "SELECT clock_timestamp()": NOW,
            }[str(statement)]

        def execute(self, statement):
            assert str(statement) == "SET LOCAL statement_timeout = '30s'"

    class Storage:
        def __init__(self, engine):
            pass

        @contextmanager
        def transaction(self, company, *, consistent_read):
            assert company == reporter.COMPANY and consistent_read is True
            yield Connection()

    monkeypatch.setenv("DATABASE_URL", "synthetic://secret-not-for-output")
    monkeypatch.setattr(reporter, "ROOT", tmp_path)
    monkeypatch.setattr(reporter, "create_engine", lambda _: Engine())
    monkeypatch.setattr(reporter, "PostgresStorage", Storage)
    monkeypatch.setattr(reporter, "read_windows", lambda conn, keys: fixture.windows)
    assert reporter.main(["--first-day", "2026-10-04", "--last-day", "2026-10-04"]) == 0
    import json

    summary = json.loads(capsys.readouterr().out)
    proof = Path(summary["proof"])
    restored = reporter.Report.model_validate_json(proof.read_text())
    assert restored == fixture
    assert "secret-not-for-output" not in proof.read_text()
    assert "windows" not in summary and len(summary["cohorts"]) == 5
    if sys.platform != "win32":
        assert proof.stat().st_mode & 0o777 == 0o600
