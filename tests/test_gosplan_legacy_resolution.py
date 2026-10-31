"""Legacy hold reconciliation uses synthetic independent evidence and is fail closed."""

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from procurement.sources.gosplan_queue import GosplanQueue, QueueError

path = Path(__file__).parents[1] / "scripts/server-gosplan-resolve-legacy-hold.py"
spec = importlib.util.spec_from_file_location("legacy_resolution", path)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def fixture():
    now = datetime(2026, 10, 30, tzinfo=UTC)
    start = (now - timedelta(days=1)).isoformat()
    end = now.isoformat()
    diag = {
        "status": "UNKNOWN",
        "http_status": 200,
        "parser": "TYPE_INVALID",
        "invalid_type": {"json_type": "NoneType", "row": 81},
        "law": "44",
        "limit": 100,
        "offset": 300,
        "hold_unchanged": True,
        "cursor_unchanged": True,
        "response_sha256": "b" * 64,
        "requested_at": end,
        "start": start,
        "end": end,
    }
    raw = json.dumps(diag).encode()
    cursor = ["44", end, start, end, 300]
    plan = {
        "company_id": subject.COMPANY,
        "authorization": "USER_STANDING_AUTHORIZATION",
        "diagnostic_file_sha256": hashlib.sha256(raw).hexdigest(),
        "diagnostic_response_sha256": "b" * 64,
        "expected_cursors": [cursor],
        "resolved_at": end,
        "old_response": "UNAVAILABLE",
        "old_cause": "UNKNOWN",
        "coverage": "UNKNOWN",
    }
    return plan, raw, cursor


def test_independent_diagnostic_preserves_old_cause_unknown_and_exact_cursor(tmp_path):
    plan, raw, cursor = fixture()
    q = GosplanQueue(tmp_path / "queue.sqlite")
    with q.conn:
        q.conn.execute(
            "INSERT INTO provider_holds VALUES (?,?,NULL)", (subject.COMPANY, "TYPE_INVALID")
        )
        q.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", (subject.COMPANY, *cursor))
    assert subject.resolve(q, plan, raw, "a" * 64) is True
    assert subject.resolve(q, plan, raw, "a" * 64) is False
    assert q.conn.execute(
        "SELECT original_reason_evidence FROM legacy_hold_resolutions"
    ).fetchone() == ("UNKNOWN",)
    assert q.conn.execute("SELECT offset FROM legacy_scan_resumptions").fetchone() == (300,)
    q.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("old_cause", "TYPE_INVALID"),
        ("coverage", "PASS"),
        ("diagnostic_response_sha256", "c" * 64),
        ("diagnostic_file_sha256", "d" * 64),
    ],
)
def test_altered_plan_cannot_release_hold(tmp_path, field, value):
    plan, raw, _ = fixture()
    plan[field] = value
    q = GosplanQueue(tmp_path / "queue.sqlite")
    with q.conn:
        q.conn.execute(
            "INSERT INTO provider_holds VALUES (?,?,NULL)", (subject.COMPANY, "TYPE_INVALID")
        )
    with pytest.raises(QueueError):
        subject.resolve(q, plan, raw, "a" * 64)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("TYPE_INVALID",)
    q.close()


def test_mismatched_cursor_cannot_release_hold(tmp_path):
    plan, raw, cursor = fixture()
    cursor[-1] = 400
    q = GosplanQueue(tmp_path / "queue.sqlite")
    with q.conn:
        q.conn.execute(
            "INSERT INTO provider_holds VALUES (?,?,NULL)", (subject.COMPANY, "TYPE_INVALID")
        )
    with pytest.raises(QueueError):
        subject.resolve(q, plan, raw, "a" * 64)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("TYPE_INVALID",)
    q.close()


def test_null_gap_executor_replays_after_binding_or_commit_and_refuses_changed_evidence(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    plan, diag, cursor = fixture()
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    with q.conn:
        q.conn.execute(
            'INSERT INTO provider_holds VALUES (?,?,NULL)', (subject.COMPANY, 'TYPE_INVALID')
        )
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', (subject.COMPANY, *cursor))
    subject.resolve(q, plan, diag, 'a' * 64)
    end = datetime.fromisoformat(cursor[1])
    scope = Scope(subject.COMPANY, '44', datetime.fromisoformat(cursor[2]), end, 300, 100)
    observed = end + timedelta(seconds=1)
    raw = json.dumps([{'purchase_number': '0' * 19, 'purchase_type': None}]).encode()
    q.quarantine_and_hold(scope, raw, observed, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    with q.conn:
        q.conn.execute('DELETE FROM provider_hold_evidence')
    when = end + timedelta(seconds=2)
    p = {'company_id': subject.COMPANY, 'authorization': 'USER_STANDING_AUTHORIZATION',
         'observation_id': oid, 'response_sha256': hashlib.sha256(raw).hexdigest(),
         'legacy_resolution_id': 'a' * 64, 'binding_mode': 'POST_LEGACY',
         'actor_id': 'owner', 'resolved_at': when.isoformat(),
         'coverage': 'UNKNOWN'}
    with pytest.raises(QueueError, match='NULL_GAP_SOURCE_CHANGED'):
        subject.resolve_null_gap(q, {**p, 'response_sha256': 'f' * 64})
    assert q.bind_post_legacy_hold(subject.COMPANY, oid, 'a' * 64, 'owner', when)
    assert subject.resolve_null_gap(q, p) == 1
    assert subject.resolve_null_gap(q, p) == 1
    with pytest.raises(QueueError, match='NULL_GAP_BINDING_CHANGED'):
        subject.resolve_null_gap(q, {**p, 'legacy_resolution_id': 'c' * 64})
    assert q.conn.execute('SELECT count(*) FROM partial_page_gaps').fetchone() == (1,)
    q.close()


def test_null_gap_executor_accepts_exact_automatically_bound_new_hold(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    now = datetime(2026, 10, 30, tzinfo=UTC)
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope = Scope(subject.COMPANY, '44', now - timedelta(days=1), now, 0, 100)
    raw = json.dumps([{'purchase_number': '0' * 19, 'purchase_type': None}]).encode()
    q.quarantine_and_hold(scope, raw, now, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    p = {'company_id': subject.COMPANY, 'authorization': 'USER_STANDING_AUTHORIZATION',
         'observation_id': oid, 'response_sha256': hashlib.sha256(raw).hexdigest(),
         'legacy_resolution_id': None, 'binding_mode': 'AUTO_BOUND', 'actor_id': 'owner',
         'resolved_at': (now + timedelta(seconds=1)).isoformat(), 'coverage': 'UNKNOWN'}
    assert subject.resolve_null_gap(q, p) == 1
    assert subject.resolve_null_gap(q, p) == 1
    q.close()
