import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from procurement.sources.gosplan_discovery import parse_page
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope

NOW = datetime(2026, 10, 28, tzinfo=UTC)
RAW = json.dumps(
    [
        {
            "purchase_number": "32616349722",
            "purchase_type": "purchaseNotice",
            "updated_at": "2026-10-21T12:00:00",
        }
    ]
).encode()


def scope(company="one"):
    return Scope(company, "223", NOW - timedelta(days=1), NOW, 0, 100)


def test_atomic_repeat_and_tenant_separation(tmp_path: Path):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    page = parse_page(RAW, "223", NOW, 100)
    oid = queue.record(scope(), page, NOW)
    assert queue.record(scope(), page, NOW) == oid
    assert queue.pending("one") == [("223", "32616349722", oid)]
    assert queue.pending("other") == []
    assert queue.conn.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
    queue.close()
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    assert queue.pending("one") == [("223", "32616349722", oid)]
    queue.close()


def test_modified_source_is_rejected(tmp_path: Path):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    queue.record(scope(), parse_page(RAW, "223", NOW, 100), NOW)
    with queue.conn:
        queue.conn.execute("UPDATE observations SET raw=?", (b"[]",))
    with pytest.raises(QueueError, match="SOURCE_HASH_MISMATCH"):
        queue.pending("one")
    queue.close()


def test_mismatched_page_is_not_recorded(tmp_path: Path):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with pytest.raises(QueueError, match="SOURCE_BINDING_INVALID"):
        queue.record(scope(), parse_page(RAW, "223", NOW, 100), NOW + timedelta(seconds=1))
    assert queue.pending("one") == []
    assert queue.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
    queue.close()


def test_refuses_symlink_or_insecure_store(tmp_path: Path):
    other = tmp_path / "other"
    other.write_bytes(b"")
    link = tmp_path / "link"
    link.symlink_to(other)
    with pytest.raises(QueueError, match="STORE_PATH_INVALID"):
        GosplanQueue(link)
    other.chmod(0o644)
    with pytest.raises(QueueError, match="STORE_PERMISSIONS_INVALID"):
        GosplanQueue(other)


def test_claim_survives_restart_and_wrong_tenant_cannot_finish(tmp_path: Path):
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    queue.record(scope(), parse_page(RAW, "223", NOW, 100), NOW)
    attempt = queue.claim("one", "223", "32616349722", NOW)
    queue.close()
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with pytest.raises(QueueError, match="ATTEMPT_IN_PROGRESS"):
        queue.claim("one", "223", "32616349722", NOW)
    with pytest.raises(QueueError, match="ATTEMPT_NOT_ACTIVE"):
        queue.finish("other", attempt, "UNKNOWN", None)
    with pytest.raises(QueueError, match="OFFICIAL_SHA_REQUIRED"):
        queue.finish("one", attempt, "SYNCED", None)
    queue.finish("one", attempt, "UNKNOWN", None)
    with pytest.raises(QueueError, match="ATTEMPT_NOT_ACTIVE"):
        queue.finish("one", attempt, "UNKNOWN", None)
    queue.close()


def test_refuses_unprotected_or_symlink_directory(tmp_path: Path):
    exposed = tmp_path / "exposed"
    exposed.mkdir(mode=0o755)
    exposed.chmod(0o755)
    with pytest.raises(QueueError, match="STORE_DIRECTORY_INVALID"):
        GosplanQueue(exposed / "q.sqlite")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    with pytest.raises(QueueError, match="STORE_DIRECTORY_INVALID"):
        GosplanQueue(alias / "q.sqlite")


def test_claim_rechecks_observation_after_another_connection_changes_it(tmp_path):
    import sqlite3
    import threading

    queue = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "223", NOW - timedelta(days=1), NOW, 0, 100)
    raw = json.dumps(
        [{"purchase_number": "32616349722", "purchase_type": "purchaseNotice"}]
    ).encode()
    old = queue.record(scope, parse_page(raw, "223", NOW, 100), NOW)
    later = NOW + timedelta(seconds=1)
    new = queue.record(scope, parse_page(raw, "223", later, 100), later)
    with queue.conn:
        queue.conn.execute("UPDATE candidates SET observation_id=?", (old,))
    locked = threading.Event()
    release = threading.Event()

    def replace_observation():
        conn = sqlite3.connect(tmp_path / "queue.sqlite", timeout=5)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE candidates SET observation_id=?", (new,))
        locked.set()
        assert release.wait(2)
        conn.commit()
        conn.close()

    writer = threading.Thread(target=replace_observation)
    writer.start()
    assert locked.wait(2)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    with pytest.raises(QueueError, match="CANDIDATE_CHANGED"):
        queue.claim("one", "223", "32616349722", NOW, old)
    writer.join(2)
    timer.join(2)
    assert not writer.is_alive()
    assert queue.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    assert queue.conn.execute("SELECT observation_id FROM candidates").fetchone()[0] == new
    queue.close()


def test_legacy_type_hold_resolution_records_unknown_without_advancing_cursor(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    q = GosplanQueue(tmp_path / "queue.sqlite")
    now = datetime(2026, 10, 30, tzinfo=UTC)
    scope = Scope("one", "44", now - timedelta(days=1), now, 300, 100)
    cursor = ("44", now.isoformat(), (now - timedelta(days=1)).isoformat(), now.isoformat(), 300)
    with q.conn:
        q.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        q.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("two", "TYPE_INVALID"))
        q.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
    args = dict(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=now,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(cursor,),
    )
    assert q.resolve_legacy_type_hold(**args) is True
    assert q.resolve_legacy_type_hold(**args) is False
    assert (
        q.conn.execute("SELECT reason FROM provider_holds WHERE company='one'").fetchone() is None
    )
    assert q.conn.execute("SELECT reason FROM provider_holds WHERE company='two'").fetchone() == (
        "TYPE_INVALID",
    )
    assert (
        q.conn.execute(
            "SELECT law,started_at,start_at,end_at,offset FROM scan_cursors WHERE company='one'"
        ).fetchone()
        == cursor
    )
    row = q.conn.execute(
        "SELECT original_reason_evidence, diagnostic_response_sha, event "
        "FROM legacy_hold_resolutions WHERE company='one'"
    ).fetchone()
    assert row == ("UNKNOWN", "b" * 64, "LEGACY_HOLD_RESOLVED_UNKNOWN")
    assert q.pending("one") == []
    q.close()


def test_legacy_hold_resolution_refuses_changed_cursor_or_inflight(tmp_path):
    from procurement.sources.gosplan_queue import Scope

    q = GosplanQueue(tmp_path / "queue.sqlite")
    now = datetime(2026, 10, 30, tzinfo=UTC)
    scope = Scope("one", "44", now - timedelta(days=1), now, 300, 100)
    with q.conn:
        q.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        q.conn.execute(
            "INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)",
            (
                "one",
                "44",
                now.isoformat(),
                (now - timedelta(days=1)).isoformat(),
                now.isoformat(),
                300,
            ),
        )
    args = dict(
        company="one",
        actor_id="codex-owner",
        resolution_id="a" * 64,
        resolved_at=now,
        diagnostic_response_sha="b" * 64,
        diagnostic_scope=scope,
        expected_cursors=(),
    )
    with pytest.raises(QueueError, match="SCAN_CURSOR_CHANGED"):
        q.resolve_legacy_type_hold(**args)
    with q.conn:
        q.conn.execute(
            "INSERT INTO inflight_scans VALUES (?,?,?,?)",
            ("one", "id", scope.json(), now.isoformat()),
        )
    with pytest.raises(QueueError, match="INFLIGHT_SCAN_UNRESOLVED"):
        q.resolve_legacy_type_hold(**args)
    assert q.conn.execute("SELECT reason FROM provider_holds WHERE company='one'").fetchone() == (
        "TYPE_INVALID",
    )
    assert q.conn.execute("SELECT count(*) FROM legacy_hold_resolutions").fetchone() == (0,)
    q.close()


def test_hold_resolution_rolls_back_audit_and_hold_if_resume_marker_insert_fails(tmp_path):
    now = datetime(2026, 10, 30, tzinfo=UTC)
    q = GosplanQueue(tmp_path / "queue.sqlite")
    scope = Scope("one", "44", now - timedelta(days=1), now, 300, 100)
    cursor = ("44", now.isoformat(), (now - timedelta(days=1)).isoformat(), now.isoformat(), 300)
    with q.conn:
        q.conn.execute("INSERT INTO provider_holds VALUES (?,?,NULL)", ("one", "TYPE_INVALID"))
        q.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", *cursor))
        q.conn.execute(
            "CREATE TRIGGER stop_marker BEFORE INSERT ON legacy_scan_resumptions "
            "BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
    with pytest.raises(Exception, match="synthetic failure"):
        q.resolve_legacy_type_hold(
            company="one",
            actor_id="codex-owner",
            resolution_id="a" * 64,
            resolved_at=now,
            diagnostic_response_sha="b" * 64,
            diagnostic_scope=scope,
            expected_cursors=(cursor,),
        )
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("TYPE_INVALID",)
    assert q.conn.execute("SELECT count(*) FROM legacy_hold_resolutions").fetchone() == (0,)
    assert q.conn.execute("SELECT count(*) FROM legacy_scan_resumptions").fetchone() == (0,)
    q.close()


def test_quarantined_null_type_reconciles_with_durable_gap_and_original_provenance(tmp_path):
    from procurement.sources.gosplan_discovery import GosplanError, inspect_null_type_page

    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 300, 100)
    rows = [
        {'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
        for i in range(100)
    ]
    rows[81]['purchase_type'] = None
    raw = json.dumps(rows).encode()
    with pytest.raises(GosplanError, match='TYPE_INVALID'):
        parse_page(raw, '44', NOW, 100)
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', (
            'one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 300
        ))
    assert q.quarantine_and_hold(scope44, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    assert q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1)) == 1
    page, gaps = inspect_null_type_page(raw, '44', NOW, 100)
    assert gaps == ((81, f'{81:019d}'),)
    assert len(page.candidates) == 99
    assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (400,)
    assert q.conn.execute('SELECT * FROM provider_holds').fetchall() == []
    assert q.conn.execute('SELECT raw FROM observations').fetchone()[0] == raw
    assert q.conn.execute('SELECT event FROM audit').fetchone() == ('PARTIAL_OBSERVED_UNKNOWN',)
    assert len(q.pending('one')) == 99 and q.pending('other') == []
    assert q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1)) == 1
    with pytest.raises(QueueError, match='PARTIAL_REPLAY_MISMATCH'):
        q.reconcile_null_type_page('one', oid, 'other', NOW + timedelta(seconds=1))
    with q.conn:
        q.conn.execute('DELETE FROM partial_page_gaps')
    with pytest.raises(QueueError, match='PARTIAL_GAPS_CHANGED'):
        q.pending('one')
    q.close()


@pytest.mark.parametrize('corruption', ['missing_type', 'bad_type', 'duplicate', 'bad_number'])
def test_quarantined_null_type_does_not_mask_other_validation_errors(tmp_path, corruption):
    from procurement.sources.gosplan_discovery import GosplanError

    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 300, 100)
    rows = [
        {'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
        for i in range(3)
    ]
    rows[0]['purchase_type'] = None
    if corruption == 'missing_type':
        del rows[1]['purchase_type']
    elif corruption == 'bad_type':
        rows[1]['purchase_type'] = 5
    elif corruption == 'duplicate':
        rows[1]['purchase_number'] = rows[0]['purchase_number']
    else:
        rows[1]['purchase_number'] = 'invalid'
    raw = json.dumps(rows).encode()
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', (
            'one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 300
        ))
    q.quarantine_and_hold(scope44, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    with pytest.raises(GosplanError):
        q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1))
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('TYPE_INVALID',)
    assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (300,)
    assert q.conn.execute('SELECT count(*) FROM observations').fetchone() == (0,)
    q.close()


def test_partial_resolution_refuses_old_page_for_new_hold(tmp_path):
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 300, 100)
    rows = [{'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
            for i in range(2)]
    rows[0]['purchase_type'] = None
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', (
            'one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 300
        ))
    q.quarantine_and_hold(scope44, json.dumps(rows).encode(), NOW, 'TYPE_INVALID', None)
    older = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    with q.conn:
        q.conn.execute('DELETE FROM provider_holds')
    rows[1]['purchase_number'] = f'{99:019d}'
    q.quarantine_and_hold(scope44, json.dumps(rows).encode(), NOW + timedelta(seconds=1),
                          'TYPE_INVALID', None)
    with pytest.raises(QueueError, match='PARTIAL_HOLD_CHANGED'):
        q.reconcile_null_type_page('one', older, 'owner', NOW + timedelta(seconds=2))
    assert q.conn.execute('SELECT count(*) FROM observations').fetchone() == (0,)
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('TYPE_INVALID',)
    q.close()


def test_partial_resolution_rolls_back_every_write_on_gap_error(tmp_path):
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 300, 100)
    raw = json.dumps([{'purchase_number': '0' * 19, 'purchase_type': None}]).encode()
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', (
            'one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 300
        ))
    q.quarantine_and_hold(scope44, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    q.conn.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON partial_page_gaps "
                   "BEGIN SELECT RAISE(ABORT, 'test interruption'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1))
    for table in ('observations', 'partial_page_resolutions', 'partial_page_gaps', 'candidates'):
        assert q.conn.execute('SELECT count(*) FROM ' + table).fetchone() == (0,)
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('TYPE_INVALID',)
    assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (300,)
    q.close()


def test_partial_page_preserves_resume_at_offset_limit(tmp_path):
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 1000, 100)
    rows = [{'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
            for i in range(100)]
    rows[0]['purchase_type'] = None
    raw = json.dumps(rows).encode()
    cursor = ('one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 1000)
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', cursor)
        q.conn.execute('INSERT INTO legacy_hold_resolutions VALUES (?,?,?,?,?,?,?,?,?,?)', (
            'one', 'a' * 64, NOW.isoformat(), 'owner', 'TYPE_INVALID', 'UNKNOWN', 'b' * 64,
            scope44.json(), '[]', 'LEGACY_HOLD_RESOLVED_UNKNOWN'
        ))
        q.conn.execute('INSERT INTO legacy_scan_resumptions VALUES (?,?,?,?,?,?,?)', (
            'one', '44', 'a' * 64, *cursor[2:]
        ))
    q.quarantine_and_hold(scope44, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    assert q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1)) == 1
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('OFFSET_LIMIT',)
    assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (1000,)
    assert q.conn.execute('SELECT offset FROM legacy_scan_resumptions').fetchone() == (1000,)
    assert len(q.pending('one')) == 99
    q.close()


def test_concurrent_partial_reconciliation_is_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / 'queue.sqlite'
    q = GosplanQueue(path)
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 300, 100)
    raw = json.dumps([{'purchase_number': '0' * 19, 'purchase_type': None}]).encode()
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', (
            'one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 300
        ))
    q.quarantine_and_hold(scope44, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    q.close()

    def reconcile(_):
        own = GosplanQueue(path)
        try:
            return own.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1))
        finally:
            own.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(reconcile, range(2))) == [1, 1]
    q = GosplanQueue(path)
    assert q.conn.execute('SELECT count(*) FROM partial_page_resolutions').fetchone() == (1,)
    assert q.conn.execute('SELECT count(*) FROM partial_page_gaps').fetchone() == (1,)
    assert q.conn.execute('SELECT count(*) FROM audit').fetchone() == (1,)
    q.close()


def test_partial_first_page_creates_resume_cursor(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 0, 100)
    rows = [{'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
            for i in range(100)]
    rows[0]['purchase_type'] = None
    q.quarantine_and_hold(scope44, json.dumps(rows).encode(), NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    assert q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1)) == 1
    assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (100,)
    assert len(q.pending('one')) == 99
    requests = []

    def reply(request):
        requests.append(dict(request.url.params))
        return httpx.Response(200, json=[{
            'purchase_number': f'{100:019d}', 'purchase_type': 'epNotificationEF2020'
        }])

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = scan_page(client, 'synthetic', q, 'one', '44', NOW + timedelta(hours=7))
    assert result.reason == 'SHORT_PAGE'
    assert requests[0]['skip'] == '100'
    assert requests[0]['updated_after'] == scope44.start.isoformat()
    assert requests[0]['updated_before'] == scope44.end.isoformat()
    assert q.conn.execute('SELECT count(*) FROM partial_scan_resumptions').fetchone() == (0,)
    assert q.conn.execute('SELECT count(*) FROM partial_page_gaps').fetchone() == (1,)
    q.close()


def test_bind_post_legacy_hold_requires_unique_later_rejection_and_exact_resume(tmp_path):
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 300, 100)
    cursor = ('one', '44', NOW.isoformat(), scope44.start.isoformat(), NOW.isoformat(), 300)
    resolution = 'a' * 64
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', cursor)
        q.conn.execute('INSERT INTO legacy_hold_resolutions VALUES (?,?,?,?,?,?,?,?,?,?)', (
            'one', resolution, (NOW - timedelta(seconds=1)).isoformat(), 'owner', 'TYPE_INVALID',
            'UNKNOWN', 'b' * 64, scope44.json(), '[]', 'LEGACY_HOLD_RESOLVED_UNKNOWN'
        ))
        q.conn.execute('INSERT INTO legacy_scan_resumptions VALUES (?,?,?,?,?,?,?)', (
            'one', '44', resolution, *cursor[2:]
        ))
    raw = json.dumps([{'purchase_number': '0' * 19, 'purchase_type': None}]).encode()
    q.quarantine_and_hold(scope44, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    with q.conn:
        q.conn.execute('DELETE FROM provider_hold_evidence')  # installed older worker had no table
    with pytest.raises(QueueError, match='HOLD_BINDING_EVIDENCE_INVALID'):
        q.bind_post_legacy_hold('one', oid, 'c' * 64, 'owner', NOW + timedelta(seconds=1))
    assert q.bind_post_legacy_hold('one', oid, resolution, 'owner', NOW + timedelta(seconds=1))
    assert not q.bind_post_legacy_hold('one', oid, resolution, 'owner', NOW + timedelta(seconds=1))
    assert q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=2)) == 1
    q.close()


def test_two_partial_pages_preserve_both_gaps_and_resume_same_window(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope44 = Scope('one', '44', NOW - timedelta(days=1), NOW, 0, 100)
    rows = [{'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
            for i in range(100)]
    rows[0]['purchase_type'] = None
    q.quarantine_and_hold(scope44, json.dumps(rows).encode(), NOW, 'TYPE_INVALID', None)
    first = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    q.reconcile_null_type_page('one', first, 'owner', NOW + timedelta(seconds=1))
    rows2 = [{'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
             for i in range(100, 200)]
    rows2[81]['purchase_type'] = None
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=rows2))
    with httpx.Client(transport=transport) as c:
        result = scan_page(c, 'synthetic', q, 'one', '44', NOW + timedelta(hours=7))
    assert result.reason == 'TYPE_INVALID'
    second = q.conn.execute('SELECT observation_id FROM provider_hold_evidence').fetchone()[0]
    assert second != first
    q.reconcile_null_type_page('one', second, 'owner', NOW + timedelta(hours=7, seconds=1))
    assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (200,)
    marker = q.conn.execute('SELECT observation_id,offset FROM partial_scan_resumptions').fetchone()
    assert marker == (second, 200)
    assert q.conn.execute('SELECT count(*) FROM partial_page_gaps').fetchone() == (2,)
    assert len(q.pending('one')) == 198
    q.close()


def test_scan_racing_reconciliation_never_skips_old_window(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    from procurement.sources.gosplan_scan import scan_page

    path = tmp_path / 'queue.sqlite'
    q = GosplanQueue(path)
    scope = Scope('one', '44', NOW - timedelta(days=1), NOW, 0, 100)
    rows = [{'purchase_number': f'{i:019d}', 'purchase_type': 'epNotificationEF2020'}
            for i in range(100)]
    rows[0]['purchase_type'] = None
    q.quarantine_and_hold(scope, json.dumps(rows).encode(), NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    q.close()
    barrier = threading.Barrier(2)
    requests = []

    def resolve():
        own = GosplanQueue(path)
        try:
            barrier.wait()
            return own.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1))
        finally:
            own.close()

    def scan():
        own = GosplanQueue(path)
        def reply(request):
            requests.append(dict(request.url.params))
            return httpx.Response(200, json=[])
        try:
            with httpx.Client(transport=httpx.MockTransport(reply)) as client:
                barrier.wait()
                try:
                    return scan_page(
                        client, 'synthetic', own, 'one', '44', NOW + timedelta(hours=7)
                    )
                except QueueError as error:
                    assert str(error) in {'SCAN_SCOPE_CHANGED', 'LEGACY_RESUME_CURSOR_CHANGED'}
                    return None
        finally:
            own.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(resolve), pool.submit(scan)
        assert a.result() == 1
        result = b.result()
    if requests:
        assert requests[0]['skip'] == '100'
        assert requests[0]['updated_after'] == scope.start.isoformat()
        assert requests[0]['updated_before'] == scope.end.isoformat()
        assert result.reason == 'SHORT_PAGE'
    else:
        assert result is None or result.reason == 'PROVIDER_HOLD'
    q = GosplanQueue(path)
    assert q.conn.execute('SELECT count(*) FROM partial_page_gaps').fetchone() == (1,)
    if not requests:
        assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (100,)
    q.close()


@pytest.mark.parametrize('law', ['44', '223'])
@pytest.mark.parametrize('count', [2, 100])
def test_null_reconciliation_at_provider_limit(tmp_path, law, count):
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope = Scope('one', law, NOW - timedelta(days=1), NOW, 1000, 100)
    cursor = ('one', law, NOW.isoformat(), scope.start.isoformat(), NOW.isoformat(), 1000)
    width = 19 if law == '44' else 11
    kind = 'epNotificationEF2020' if law == '44' else 'purchaseNotice'
    rows = [{'purchase_number': f'{i + 1:0{width}d}', 'purchase_type': kind}
            for i in range(count)]
    rows[0]['purchase_type'] = None
    raw = json.dumps(rows).encode()
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', cursor)
    assert q.quarantine_and_hold(scope, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    assert q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1)) == 1
    assert q.conn.execute('SELECT raw FROM observations').fetchone() == (raw,)
    assert q.conn.execute('SELECT reason FROM partial_page_gaps').fetchone() == (
        'NULL_TYPE_UNKNOWN',
    )
    assert q.conn.execute('SELECT event FROM audit').fetchone() == ('PARTIAL_OBSERVED_UNKNOWN',)
    assert len(q.pending('one')) == count - 1
    if count == 100:
        assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('OFFSET_LIMIT',)
        assert q.conn.execute('SELECT offset FROM scan_cursors').fetchone() == (1000,)
        assert q.conn.execute('SELECT observation_id FROM provider_hold_evidence').fetchone() == (
            oid,
        )
    else:
        assert q.conn.execute('SELECT count(*) FROM provider_holds').fetchone() == (0,)
        assert q.conn.execute('SELECT count(*) FROM scan_cursors').fetchone() == (0,)
    q.close()


@pytest.mark.parametrize('law', ['44', '223'])
def test_null_reconciliation_beyond_limit_preserves_hold_and_cursor(tmp_path, law):
    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope = Scope('one', law, NOW - timedelta(days=1), NOW, 1100, 100)
    cursor = ('one', law, NOW.isoformat(), scope.start.isoformat(), NOW.isoformat(), 1100)
    width = 19 if law == '44' else 11
    raw = json.dumps([{'purchase_number': f'{1:0{width}d}', 'purchase_type': None}]).encode()
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', cursor)
    q.quarantine_and_hold(scope, raw, NOW, 'TYPE_INVALID', None)
    oid = q.conn.execute('SELECT id FROM rejected_pages').fetchone()[0]
    with pytest.raises(QueueError, match='OFFSET_LIMIT'):
        q.reconcile_null_type_page('one', oid, 'owner', NOW + timedelta(seconds=1))
    assert q.conn.execute('SELECT * FROM scan_cursors').fetchone() == cursor
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('TYPE_INVALID',)
    assert q.conn.execute('SELECT count(*) FROM observations').fetchone() == (0,)
    assert q.conn.execute('SELECT count(*) FROM partial_page_resolutions').fetchone() == (0,)
    q.close()
