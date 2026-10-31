"""Bounded preparation never turns an unresolved provider failure into coverage."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from procurement.sources.gosplan_discovery import parse_page
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def setup_queue(tmp_path):
    q = GosplanQueue(tmp_path / "queue.sqlite")
    start = NOW - timedelta(days=1)
    scope = Scope("one", "44", start, NOW, 1000, 100)
    raw = json.dumps(
        [
            {"purchase_number": f"{n:019}", "purchase_type": "epNotificationEF2020"}
            for n in range(100)
        ]
    ).encode()
    oid = q.record(scope, parse_page(raw, "44", NOW, 100), NOW)
    cursor = (NOW.isoformat(), start.isoformat(), NOW.isoformat(), 1100)
    with q.conn:
        q.conn.execute("INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", ("one", "44", *cursor))
        q.conn.execute("INSERT INTO provider_holds VALUES (?,?,?)", ("one", "HTTP_422", None))
    args = dict(
        company="one",
        law="44",
        actor_id="owner",
        prepared_at=NOW,
        expected_cursor=cursor,
        source_observation_id=oid,
    )
    return q, args


def test_plan_is_replayable_and_preserves_original_hold(tmp_path):
    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    assert q.prepare_offset_recovery(**args) == plan
    parent = q.conn.execute("SELECT cause,coverage,event FROM offset_recovery_plans").fetchone()
    assert parent == ("UNKNOWN", "UNKNOWN", "OFFSET_SPLIT_PREPARED_UNKNOWN")
    children = q.conn.execute(
        "SELECT start_at,end_at,status FROM offset_recovery_children ORDER BY ordinal"
    ).fetchall()
    assert len(children) == 2 and all(x[2] == "PREPARED" for x in children)
    assert datetime.fromisoformat(children[0][1]) > datetime.fromisoformat(children[1][0])
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("HTTP_422",)
    assert q.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (1100,)
    assert q.conn.execute(
        "SELECT count(*) FROM offset_recovery_plans WHERE company=?", ("other",)
    ).fetchone() == (0,)
    q.close()
    q = GosplanQueue(tmp_path / "queue.sqlite")
    assert q.prepare_offset_recovery(**args) == plan
    q.close()


def test_child_insert_failure_rolls_back_all(tmp_path):
    q, args = setup_queue(tmp_path)
    with q.conn:
        q.conn.execute(
            "CREATE TRIGGER reject_child BEFORE INSERT ON offset_recovery_children "
            "BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    with pytest.raises(Exception, match="injected"):
        q.prepare_offset_recovery(**args)
    assert q.conn.execute("SELECT count(*) FROM offset_recovery_plans").fetchone() == (0,)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("HTTP_422",)
    q.close()


def test_tampered_source_or_cursor_fails_closed(tmp_path):
    q, args = setup_queue(tmp_path)
    with q.conn:
        q.conn.execute("UPDATE observations SET raw=?", (b"[]",))
    with pytest.raises(QueueError, match="SOURCE_INVALID"):
        q.prepare_offset_recovery(**args)
    assert q.conn.execute("SELECT count(*) FROM offset_recovery_plans").fetchone() == (0,)
    q.close()


def test_replay_rejects_changed_children_and_hold(tmp_path):
    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    with q.conn:
        q.conn.execute(
            "UPDATE offset_recovery_children SET ordinal=ordinal+10 WHERE plan_id=?", (plan,)
        )
    with pytest.raises(QueueError, match="REPLAY_CONFLICT"):
        q.prepare_offset_recovery(**args)
    with q.conn:
        q.conn.execute("UPDATE provider_holds SET reason='OTHER' WHERE company='one'")
    with pytest.raises(QueueError, match="HOLD_CHANGED"):
        q.prepare_offset_recovery(**args)
    q.close()


def test_activated_children_scan_and_keep_unknown(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    calls = []

    def response(request):
        calls.append(
            (
                request.url.params["skip"],
                request.url.params["updated_after"],
                request.url.params["updated_before"],
            )
        )
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert scan_page(client, "secret", q, "one", "223", NOW).reason == (
            "OFFSET_RECOVERY_OTHER_LAW_OR_INVALID"
        )
        assert scan_page(client, "secret", q, "one", "44", NOW).reason == "OFFSET_RECOVERY"
        assert scan_page(client, "secret", q, "one", "44", NOW).reason == "OFFSET_RECOVERY_UNKNOWN"
    assert len(calls) == 2 and all(c[0] == "0" for c in calls)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == (
        "OFFSET_RECOVERY_UNKNOWN",
    )
    assert q.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (1100,)
    assert q.conn.execute(
        "SELECT status FROM offset_recovery_children ORDER BY ordinal"
    ).fetchall() == [("DONE",), ("DONE",)]
    q.close()


def test_crash_after_page_reconciles_without_source(tmp_path, monkeypatch):
    import httpx

    from procurement.sources import gosplan_scan

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    original = q.record

    def interrupted(*a, **kw):
        original(*a, **kw)
        raise RuntimeError("crash")

    with monkeypatch.context() as m:
        m.setattr(q, "record", interrupted)
        with (
            httpx.Client(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
            ) as c,
            pytest.raises(RuntimeError, match="crash"),
        ):
            gosplan_scan.scan_page(c, "secret", q, "one", "44", NOW)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("REQUEST_IN_FLIGHT",)
    oid = q.conn.execute(
        "SELECT id FROM observations WHERE company='one' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()[0]
    result = gosplan_scan.reconcile_offset_page(q, "one", "44", plan, oid)
    assert result.reason == "OFFSET_RECOVERY"
    assert q.conn.execute("SELECT count(*) FROM inflight_scans").fetchone() == (0,)
    assert gosplan_scan.reconcile_offset_page(q, "one", "44", plan, oid).reason == (
        "OFFSET_RECOVERY_ALREADY_RECONCILED"
    )
    q.close()


def test_failure_without_retained_page_remains_held(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import reconcile_offset_page, scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    calls = []

    def fail(request):
        calls.append(1)
        return httpx.Response(422)

    with httpx.Client(transport=httpx.MockTransport(fail)) as c:
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "HTTP_422"
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "PROVIDER_HOLD"
    assert calls == [1]
    with pytest.raises(QueueError, match="PAGE_INVALID"):
        reconcile_offset_page(q, "one", "44", plan, args["source_observation_id"])
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("REQUEST_IN_FLIGHT",)
    q.close()


def test_child_full_at_limit_never_requests_next_page(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    with q.conn:
        q.conn.execute(
            "UPDATE offset_recovery_children SET offset=1000 WHERE company='one' "
            "AND status='ACTIVE'"
        )
    offsets = []

    def full(request):
        offsets.append(request.url.params["skip"])
        return httpx.Response(
            200,
            json=[
                {"purchase_number": f"{n:019}", "purchase_type": "epNotificationEF2020"}
                for n in range(100)
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(full)) as c:
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "OFFSET_RECOVERY_CHILD_LIMIT"
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "PROVIDER_HOLD"
    assert offsets == ["1000"]
    q.close()


def test_finish_transaction_rolls_back_and_reconciles(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import reconcile_offset_page, scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    with q.conn:
        q.conn.execute(
            "CREATE TRIGGER reject_page_event BEFORE INSERT ON offset_recovery_events "
            "WHEN new.event LIKE 'PAGE/%' BEGIN SELECT RAISE(ABORT,'finish-failed'); END"
        )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))) as c,
        pytest.raises(Exception, match="finish-failed"),
    ):
        scan_page(c, "secret", q, "one", "44", NOW)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("REQUEST_IN_FLIGHT",)
    assert q.conn.execute(
        "SELECT status FROM offset_recovery_children ORDER BY ordinal"
    ).fetchall() == [("ACTIVE",), ("PREPARED",)]
    oid = q.conn.execute("SELECT id FROM observations ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    with q.conn:
        q.conn.execute("DROP TRIGGER reject_page_event")
    assert reconcile_offset_page(q, "one", "44", plan, oid).reason == "OFFSET_RECOVERY"
    q.close()


def test_null_child_exact_reconcile_and_replay(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    rows = [
        {"purchase_number": "0000000000000000150", "purchase_type": None},
        {"purchase_number": "0000000000000000151", "purchase_type": "epNotificationEF2020"},
    ]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as c:
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "TYPE_INVALID"
    oid = q.conn.execute("SELECT observation_id FROM provider_hold_evidence").fetchone()[0]
    assert q.conn.execute("SELECT count(*) FROM offset_recovery_reservations").fetchone() == (0,)
    with pytest.raises(QueueError, match="SOURCE_MISSING"):
        q.reconcile_offset_null_page("other", plan, oid, "owner", NOW)
    with pytest.raises(QueueError, match="SCOPE_CHANGED"):
        q.reconcile_offset_null_page("one", "a" * 64, oid, "owner", NOW)
    assert q.reconcile_offset_null_page("one", plan, oid, "owner", NOW) == 1
    assert q.reconcile_offset_null_page("one", plan, oid, "owner", NOW) == 1
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("OFFSET_RECOVERY",)
    assert q.conn.execute("SELECT reason FROM partial_page_gaps").fetchone() == (
        "NULL_TYPE_UNKNOWN",
    )
    assert q.conn.execute("SELECT offset FROM scan_cursors").fetchone() == (1100,)
    assert q.conn.execute("SELECT event FROM audit WHERE observation_id=?", (oid,)).fetchone() == (
        "PARTIAL_OBSERVED_UNKNOWN",
    )
    assert ("44", "0000000000000000151", oid, "epNotificationEF2020") in q.pending_with_types(
        "one"
    )
    assert all(row[1] != "0000000000000000150" for row in q.pending_with_types("one"))
    assert q.pending_with_types("other") == []
    q.close()


def test_capacity_before_source_and_existing_writer_reservation(tmp_path, monkeypatch):
    import sqlite3

    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    with q.conn:
        q.conn.executemany(
            "INSERT INTO candidates VALUES (?,?,?,?,?)",
            [
                ("one", "44", f"{n:019}", args["source_observation_id"], "PENDING")
                for n in range(100, 1901)
            ],
        )
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda _: calls.append(1))) as c:
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "OFFSET_RECOVERY_CAPACITY"
    assert calls == []
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("OFFSET_RECOVERY",)
    with q.conn:
        q.conn.execute("DELETE FROM candidates WHERE company='one' AND number>=?", (f"{100:019}",))

    def fail(_request):
        raise RuntimeError("lost process")

    with httpx.Client(transport=httpx.MockTransport(fail)) as c, pytest.raises(RuntimeError):
        scan_page(c, "secret", q, "one", "44", NOW)
    other_scope = Scope("one", "44", NOW - timedelta(days=2), NOW - timedelta(days=1), 0, 100)
    raw = json.dumps(
        [{"purchase_number": "0000000000000000001", "purchase_type": "epNotificationEF2020"}]
    ).encode()
    with pytest.raises(sqlite3.IntegrityError, match="OFFSET_RECOVERY_RESERVED"):
        q.record(other_scope, parse_page(raw, "44", NOW, 100), NOW)
    old_writer = sqlite3.connect(tmp_path / "queue.sqlite")
    with pytest.raises(sqlite3.IntegrityError, match="OFFSET_RECOVERY_RESERVED"):
        old_writer.execute(
            "INSERT INTO rejected_pages VALUES (?,?,?,?,?,?,?)",
            ("one", "x", other_scope.json(), NOW.isoformat(), "x", "TYPE_INVALID", raw),
        )
    old_writer.close()
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("REQUEST_IN_FLIGHT",)
    q.close()


def test_null_child_transaction_rollback(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, args = setup_queue(tmp_path)
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company="one", law="44", plan_id=plan)
    rows = [{"purchase_number": "0000000000000000150", "purchase_type": None}]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as c:
        assert scan_page(c, "secret", q, "one", "44", NOW).reason == "TYPE_INVALID"
    oid = q.conn.execute("SELECT observation_id FROM provider_hold_evidence").fetchone()[0]
    with q.conn:
        q.conn.execute(
            "CREATE TRIGGER reject_null_gap BEFORE INSERT ON partial_page_gaps "
            "BEGIN SELECT RAISE(ABORT,'fail-gap'); END"
        )
    with pytest.raises(Exception, match="fail-gap"):
        q.reconcile_offset_null_page("one", plan, oid, "owner", NOW)
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("TYPE_INVALID",)
    assert q.conn.execute("SELECT count(*) FROM partial_page_resolutions").fetchone() == (0,)
    with q.conn:
        q.conn.execute("DROP TRIGGER reject_null_gap")
    assert q.reconcile_offset_null_page("one", plan, oid, "owner", NOW) == 1
    q.close()


def test_open_official_attempt_blocks_prepare_and_activate(tmp_path):
    q, args = setup_queue(tmp_path)
    number = q.pending('one')[0][1]
    attempt = q.claim('one', '44', number, NOW)
    with pytest.raises(QueueError, match='OFFSET_RECOVERY_HOLD_CHANGED'):
        q.prepare_offset_recovery(**args)
    q.finish('one', attempt, 'UNKNOWN', None)
    plan = q.prepare_offset_recovery(**args)
    q.claim('one', '44', number, NOW)
    with pytest.raises(QueueError, match='OFFSET_RECOVERY_ATTEMPT_OPEN'):
        q.activate_offset_recovery(company='one', law='44', plan_id=plan)
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('HTTP_422',)
    q.close()


def test_claim_blocked_while_split_request_reserved(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, args = setup_queue(tmp_path)
    number = q.pending('one')[0][1]
    plan = q.prepare_offset_recovery(**args)
    q.activate_offset_recovery(company='one', law='44', plan_id=plan)

    def response(_):
        with pytest.raises(QueueError, match='OFFSET_RECOVERY_RESERVED'):
            q.claim('one', '44', number, NOW)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(response)) as c:
        assert scan_page(c, 'secret', q, 'one', '44', NOW).reason == 'OFFSET_RECOVERY'
    assert q.conn.execute('SELECT count(*) FROM attempts').fetchone() == (0,)
    q.close()


def test_active_223_split_routes_through_first_44_without_network(tmp_path):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q = GosplanQueue(tmp_path / 'queue.sqlite')
    scope = Scope('one', '223', NOW - timedelta(days=1), NOW, 1000, 100)
    raw = json.dumps([{'purchase_number': f'{i:011d}', 'purchase_type': 'purchaseNotice'}
                      for i in range(100)]).encode()
    oid = q.record(scope, parse_page(raw, '223', NOW, 100), NOW)
    cursor = (NOW.isoformat(), scope.start.isoformat(), NOW.isoformat(), 1100)
    with q.conn:
        q.conn.execute('INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)', ('one', '223', *cursor))
        q.conn.execute('INSERT INTO provider_holds VALUES (?,?,NULL)', ('one', 'HTTP_422'))
    plan = q.prepare_offset_recovery(company='one', law='223', actor_id='owner', prepared_at=NOW,
                                     expected_cursor=cursor, source_observation_id=oid)
    q.activate_offset_recovery(company='one', law='223', plan_id=plan)
    seen = []
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: seen.append(request) or httpx.Response(200, json=[])
    )) as client:
        result = scan_page(client, 'key', q, 'one', '44', NOW)
        assert result.reason == 'OFFSET_RECOVERY_NEXT_223' and not seen
        assert scan_page(client, 'key', q, 'one', '223', NOW).reason == 'OFFSET_RECOVERY'
    assert len(seen) == 1 and '/fz223/purchases' in str(seen[0].url)
    q.close()
