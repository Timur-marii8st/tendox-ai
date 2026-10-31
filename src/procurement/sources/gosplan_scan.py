"""Bounded rolling scan cursor; coverage remains unknown on mutable provider pages."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import httpx

from procurement.sources.gosplan_discovery import (
    MAX_BYTES,
    MAX_OFFSET,
    GosplanError,
    Law,
    fetch_page,
)
from procurement.sources.gosplan_pagination import BatchResult
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope


def scan_page(
    client: httpx.Client, key: str, queue: GosplanQueue, company: str, law: Law, now: datetime
) -> BatchResult:
    """Commit bytes before moving offset; replay after a crash is safe, never complete."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise QueueError("SCAN_TIME_INVALID")
    hold = queue.conn.execute(
        "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
    ).fetchone()
    if hold == ("OFFSET_RECOVERY", None):
        return _scan_offset_recovery(client, key, queue, company, law, now)
    if hold is not None:
        if hold[1] is None:
            return BatchResult("UNKNOWN", "PROVIDER_HOLD", 0, None, ())
        try:
            until = datetime.fromisoformat(hold[1])
            if until.tzinfo is None or until.utcoffset() is None:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise QueueError("PROVIDER_HOLD_INVALID") from exc
        if now < until:
            return BatchResult("UNKNOWN", "PROVIDER_COOLDOWN", 0, None, ())
    previous = queue.conn.execute(
        "SELECT started_at,start_at,end_at,offset FROM scan_cursors WHERE company=? AND law=?",
        (company, law),
    ).fetchone()
    resume = queue.conn.execute(
        "SELECT started_at,start_at,end_at,offset FROM legacy_scan_resumptions "
        "WHERE company=? AND law=?", (company, law)
    ).fetchone()
    partial_resume = queue.conn.execute(
        "SELECT started_at,start_at,end_at,offset FROM partial_scan_resumptions "
        "WHERE company=? AND law=?", (company, law)
    ).fetchone()
    if (resume is not None and resume != previous) or (
        partial_resume is not None and partial_resume != previous
    ):
        raise QueueError("LEGACY_RESUME_CURSOR_CHANGED")
    if previous:
        try:
            started, start, end = (datetime.fromisoformat(v) for v in previous[:3])
            offset = previous[3]
            if (
                any(t.tzinfo is None or t.utcoffset() is None for t in (started, start, end))
                or start >= end
                or end != started
                or end - start != timedelta(hours=24)
                or started > now
                or type(offset) is not int
                or offset < 0
                or offset > 10000
                or offset % 100
            ):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise QueueError("SCAN_CURSOR_INVALID") from exc
        # Old persisted cursors can exceed the provider's current limit. Keep
        # their evidence intact and refuse a request or an automatic reset.
        if offset > MAX_OFFSET:
            return BatchResult("UNKNOWN", "OFFSET_LIMIT", 0, offset, ())
        if now - started >= timedelta(hours=6) and resume is None and partial_resume is None:
            started, start, end, offset = now, now - timedelta(hours=24), now, 0
    else:
        started, start, end, offset = now, now - timedelta(hours=24), now, 0
    scope = Scope(company, law, start, end, offset, 100)
    # Reserve the request durably before network I/O. A crash or failed write
    # leaves a persistent hold requiring explicit reconciliation, never a retry.
    inflight_hold = ("REQUEST_IN_FLIGHT", None)
    attempt_id = str(uuid4())
    with queue.conn:
        queue.conn.execute("BEGIN IMMEDIATE")
        current_hold = queue.conn.execute(
            "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
        ).fetchone()
        current_cursor = queue.conn.execute(
            "SELECT started_at,start_at,end_at,offset FROM scan_cursors WHERE company=? AND law=?",
            (company, law),
        ).fetchone()
        current_resume = queue.conn.execute(
            "SELECT started_at,start_at,end_at,offset FROM legacy_scan_resumptions "
            "WHERE company=? AND law=?", (company, law)
        ).fetchone()
        current_partial_resume = queue.conn.execute(
            "SELECT started_at,start_at,end_at,offset FROM partial_scan_resumptions "
            "WHERE company=? AND law=?", (company, law)
        ).fetchone()
        if (current_hold != hold or current_cursor != previous or current_resume != resume
                or current_partial_resume != partial_resume):
            raise QueueError("SCAN_SCOPE_CHANGED")
        queue.conn.execute(
            "INSERT INTO provider_holds VALUES (?,?,NULL) ON CONFLICT(company) "
            "DO UPDATE SET reason=excluded.reason,until_at=NULL", (company, inflight_hold[0])
        )
        queue.conn.execute(
            "INSERT INTO inflight_scans VALUES (?,?,?,?)",
            (company, attempt_id, scope.json(), now.isoformat()),
        )
    try:
        page = fetch_page(client, key, law, start=start, end=end, offset=offset, limit=100, now=now)
        observation = queue.record(scope, page, now, inflight_id=attempt_id)
    except GosplanError as exc:
        reason = str(exc)
        if exc.source_raw is not None:
            stored = queue.quarantine_and_hold(
                scope, exc.source_raw, now, reason, inflight_hold, attempt_id
            )
            return BatchResult(
                "UNKNOWN", reason if stored else "QUARANTINE_CAP_REACHED", 0, offset, ()
            )
        temporary = reason == "TRANSPORT_ERROR" or reason in {
            "HTTP_500",
            "HTTP_502",
            "HTTP_503",
            "HTTP_504",
        }
        until = (now + timedelta(hours=1)).isoformat() if temporary else None
        with queue.conn:
            queue.conn.execute("BEGIN IMMEDIATE")
            current_hold = queue.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
            ).fetchone()
            if current_hold != inflight_hold:
                raise QueueError("PROVIDER_HOLD_CHANGED") from exc
            queue.check_inflight(scope, now, attempt_id)
            queue.conn.execute(
                "INSERT INTO provider_holds VALUES (?,?,?) "
                "ON CONFLICT(company) DO UPDATE SET reason=excluded.reason,"
                "until_at=excluded.until_at",
                (company, reason, until),
            )
            queue.conn.execute("DELETE FROM inflight_scans WHERE company=?", (company,))
        return BatchResult("UNKNOWN", reason, 0, offset, ())
    except QueueError as exc:
        return BatchResult("UNKNOWN", str(exc), 0, offset, ())
    next_offset = offset + 100 if page.may_have_more and offset < MAX_OFFSET else None
    with queue.conn:
        queue.conn.execute("BEGIN IMMEDIATE")
        current = queue.conn.execute(
            "SELECT started_at,start_at,end_at,offset FROM scan_cursors WHERE company=? AND law=?",
            (company, law),
        ).fetchone()
        if current != previous:
            raise QueueError("SCAN_CURSOR_CHANGED")
        current_resume = queue.conn.execute(
            "SELECT started_at,start_at,end_at,offset FROM legacy_scan_resumptions "
            "WHERE company=? AND law=?", (company, law)
        ).fetchone()
        current_partial_resume = queue.conn.execute(
            "SELECT started_at,start_at,end_at,offset FROM partial_scan_resumptions "
            "WHERE company=? AND law=?", (company, law)
        ).fetchone()
        if current_resume != resume or current_partial_resume != partial_resume:
            raise QueueError("LEGACY_RESUME_CURSOR_CHANGED")
        current_hold = queue.conn.execute(
            "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
        ).fetchone()
        if current_hold != inflight_hold:
            raise QueueError("PROVIDER_HOLD_CHANGED")
        queue.check_inflight(scope, now, attempt_id)
        exhausted = page.may_have_more and offset == MAX_OFFSET
        if exhausted:
            queue.conn.execute(
                "UPDATE provider_holds SET reason='OFFSET_LIMIT',until_at=NULL WHERE company=?",
                (company,),
            )
        else:
            queue.conn.execute("DELETE FROM provider_holds WHERE company=?", (company,))
        queue.conn.execute("DELETE FROM inflight_scans WHERE company=?", (company,))
        if exhausted:
            pass  # Preserve both the cursor and resume marker for explicit reconciliation.
        elif next_offset is None:
            queue.conn.execute("DELETE FROM scan_cursors WHERE company=? AND law=?", (company, law))
            if resume is not None:
                queue.conn.execute(
                    "DELETE FROM legacy_scan_resumptions WHERE company=? AND law=?", (company, law)
                )
            if partial_resume is not None:
                queue.conn.execute(
                    "DELETE FROM partial_scan_resumptions WHERE company=? AND law=?", (company, law)
                )
        else:
            queue.conn.execute(
                "INSERT INTO scan_cursors VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(company,law) DO UPDATE SET started_at=excluded.started_at, "
                "start_at=excluded.start_at,end_at=excluded.end_at,offset=excluded.offset",
                (
                    company,
                    law,
                    started.isoformat(),
                    start.isoformat(),
                    end.isoformat(),
                    next_offset,
                ),
            )
            if resume is not None:
                queue.conn.execute(
                    "UPDATE legacy_scan_resumptions SET offset=? WHERE company=? AND law=?",
                    (next_offset, company, law),
                )
            if partial_resume is not None:
                queue.conn.execute(
                    "UPDATE partial_scan_resumptions SET offset=? WHERE company=? AND law=?",
                    (next_offset, company, law),
                )
    if exhausted:
        return BatchResult("UNKNOWN", "OFFSET_LIMIT", 1, offset, (observation,))
    reason = (
        "PAGE_BUDGET"
        if next_offset is not None
        else ("OFFSET_LIMIT" if page.may_have_more else "SHORT_PAGE")
    )
    return BatchResult("STOPPED", reason, 1, next_offset, (observation,))


def _finish_offset_page(queue, company, law, plan_id, scope, now, attempt_id, observation):
    """Advance only after validating the bound durable page; caller holds cycle lease."""
    from procurement.sources.gosplan_discovery import parse_page

    with queue.conn:
        queue.conn.execute("BEGIN IMMEDIATE")
        if queue.conn.execute(
            "SELECT 1 FROM attempts WHERE company=? AND outcome IS NULL", (company,)
        ).fetchone():
            raise QueueError('OFFSET_RECOVERY_ATTEMPT_OPEN')
        queue.check_inflight(scope, now, attempt_id)
        if queue.conn.execute(
            "SELECT attempt_id,scope,observed_at FROM offset_recovery_reservations "
            "WHERE company=?", (company,),
        ).fetchone() != (attempt_id, scope.json(), now.isoformat()):
            raise QueueError('OFFSET_RECOVERY_RESERVATION_CHANGED')
        child = queue.conn.execute(
            "SELECT c.ordinal,c.start_at,c.end_at,c.offset FROM offset_recovery_children c "
            "JOIN offset_recovery_plans p ON p.company=c.company AND p.plan_id=c.plan_id "
            "WHERE c.company=? AND c.plan_id=? AND p.law=? AND c.status='ACTIVE'",
            (company, plan_id, law),
        ).fetchall()
        if len(child) != 1 or child[0][1:] != (scope.start.isoformat(), scope.end.isoformat(),
                                                scope.offset):
            raise QueueError("OFFSET_RECOVERY_CHILD_CHANGED")
        row = queue.conn.execute(
            "SELECT scope,observed_at,response_sha,raw FROM observations "
            "WHERE company=? AND id=?", (company, observation),
        ).fetchone()
        import hashlib
        if (row is None or row[0] != scope.json() or row[1] != now.isoformat()
                or hashlib.sha256(row[3]).hexdigest() != row[2]
                or hashlib.sha256((row[0] + '\n' + row[1] + '\n' + row[2]).encode())
                .hexdigest() != observation or queue.conn.execute(
                    "SELECT 1 FROM audit WHERE company=? AND observation_id=? "
                    "AND event='OBSERVED'", (company, observation),
                ).fetchone() is None):
            raise QueueError("OFFSET_RECOVERY_PAGE_INVALID")
        page = parse_page(row[3], law, now, scope.limit)
        ordinal = child[0][0]
        if page.may_have_more and scope.offset == MAX_OFFSET:
            queue.conn.execute("UPDATE offset_recovery_children SET status='EXHAUSTED' "
                               "WHERE company=? AND plan_id=? AND ordinal=?",
                               (company, plan_id, ordinal))
            reason = 'OFFSET_RECOVERY_CHILD_LIMIT'
        elif page.may_have_more:
            queue.conn.execute("UPDATE offset_recovery_children SET offset=? "
                               "WHERE company=? AND plan_id=? AND ordinal=?",
                               (scope.offset + 100, company, plan_id, ordinal))
            reason = 'OFFSET_RECOVERY'
        else:
            queue.conn.execute("UPDATE offset_recovery_children SET status='DONE' "
                               "WHERE company=? AND plan_id=? AND ordinal=?",
                               (company, plan_id, ordinal))
            remaining = queue.conn.execute(
                "SELECT ordinal FROM offset_recovery_children WHERE company=? AND plan_id=? "
                "AND status='PREPARED' ORDER BY ordinal", (company, plan_id),
            ).fetchall()
            if remaining:
                queue.conn.execute("UPDATE offset_recovery_children SET status='ACTIVE' "
                                   "WHERE company=? AND plan_id=? AND ordinal=?",
                                   (company, plan_id, remaining[0][0]))
                reason = 'OFFSET_RECOVERY'
            else:
                reason = 'OFFSET_RECOVERY_UNKNOWN'
        queue.conn.execute("UPDATE provider_holds SET reason=? WHERE company=?", (reason, company))
        queue.conn.execute("DELETE FROM inflight_scans WHERE company=?", (company,))
        queue.conn.execute(
            "DELETE FROM offset_recovery_reservations WHERE company=? AND attempt_id=?",
            (company, attempt_id),
        )
        queue.conn.execute("INSERT INTO offset_recovery_events VALUES (?,?,?)",
                           (company, plan_id, f'PAGE/{ordinal}/{scope.offset}/{observation}'))
    return BatchResult('UNKNOWN', reason, 1, None, (observation,))


def _scan_offset_recovery(client, key, queue, company, law, now):
    """One page within an activated child; source quota is unchanged."""
    rows = queue.conn.execute(
        "SELECT p.plan_id,c.start_at,c.end_at,c.offset FROM offset_recovery_plans p "
        "JOIN offset_recovery_children c ON c.company=p.company AND c.plan_id=p.plan_id "
        "WHERE p.company=? AND p.law=? AND c.status='ACTIVE'", (company, law),
    ).fetchall()
    if len(rows) != 1:
        active = queue.conn.execute(
            "SELECT p.law FROM offset_recovery_plans p JOIN offset_recovery_children c "
            "ON c.company=p.company AND c.plan_id=p.plan_id "
            "WHERE p.company=? AND c.status='ACTIVE'", (company,),
        ).fetchall()
        if law == '44' and active == [('223',)]:
            return BatchResult('UNKNOWN', 'OFFSET_RECOVERY_NEXT_223', 0, None, ())
        return BatchResult('UNKNOWN', 'OFFSET_RECOVERY_OTHER_LAW_OR_INVALID', 0, None, ())
    plan_id, start, end, offset = rows[0]
    scope = Scope(company, law, datetime.fromisoformat(start), datetime.fromisoformat(end),
                  offset, 100)
    attempt_id = str(uuid4())
    with queue.conn:
        queue.conn.execute('BEGIN IMMEDIATE')
        current = queue.conn.execute(
            "SELECT start_at,end_at,offset FROM offset_recovery_children "
            "WHERE company=? AND plan_id=? AND status='ACTIVE'", (company, plan_id),
        ).fetchall()
        if (current != [(start, end, offset)] or queue.conn.execute(
            "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
        ).fetchone() != ('OFFSET_RECOVERY', None) or queue.conn.execute(
            "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
        ).fetchone() or queue.conn.execute(
            "SELECT 1 FROM attempts WHERE company=? AND outcome IS NULL", (company,)
        ).fetchone()):
            raise QueueError('OFFSET_RECOVERY_SCOPE_CHANGED')
        observations, observation_bytes = queue.conn.execute(
            "SELECT count(*),coalesce(sum(length(raw)),0) FROM observations WHERE company=?",
            (company,),
        ).fetchone()
        candidates = queue.conn.execute(
            "SELECT count(*) FROM candidates WHERE company=?", (company,),
        ).fetchone()[0]
        rejected, rejected_bytes = queue.conn.execute(
            "SELECT count(*),coalesce(sum(length(raw)),0) FROM rejected_pages WHERE company=?",
            (company,),
        ).fetchone()
        if (observations >= 2000 or observation_bytes + MAX_BYTES > 256 * 1024**2
                or candidates + 100 > 2000 or rejected >= 100
                or rejected_bytes + MAX_BYTES > 32 * 1024**2):
            return BatchResult('UNKNOWN', 'OFFSET_RECOVERY_CAPACITY', 0, offset, ())
        queue.conn.execute(
            "INSERT INTO offset_recovery_reservations VALUES (?,?,?,?)",
            (company, attempt_id, scope.json(), now.isoformat()),
        )
        queue.conn.execute("UPDATE provider_holds SET reason='REQUEST_IN_FLIGHT' WHERE company=?",
                           (company,))
        queue.conn.execute("INSERT INTO inflight_scans VALUES (?,?,?,?)",
                           (company, attempt_id, scope.json(), now.isoformat()))
    try:
        page = fetch_page(client, key, law, start=scope.start, end=scope.end,
                          offset=offset, limit=100, now=now)
        observation = queue.record(scope, page, now, inflight_id=attempt_id)
    except GosplanError as exc:
        if exc.source_raw is not None:
            queue.quarantine_and_hold(scope, exc.source_raw, now, str(exc),
                                      ('REQUEST_IN_FLIGHT', None), attempt_id)
        # An unretained failure remains in flight: no unreviewed retries or hold clearing.
        return BatchResult('UNKNOWN', str(exc), 0, offset, ())
    return _finish_offset_page(queue, company, law, plan_id, scope, now, attempt_id, observation)


def reconcile_offset_page(queue, company, law, plan_id, observation):
    """Finish an interrupted child only from its exact retained page, without source I/O."""
    import json
    import re

    if (not re.fullmatch(r'[a-f0-9]{64}', plan_id)
            or not re.fullmatch(r'[a-f0-9]{64}', observation)):
        raise QueueError('OFFSET_RECOVERY_ID_INVALID')

    row = queue.conn.execute(
        "SELECT attempt_id,scope,observed_at FROM inflight_scans WHERE company=?", (company,),
    ).fetchone()
    if row is None:
        import hashlib

        saved = queue.conn.execute(
            "SELECT o.scope,o.observed_at,o.response_sha,o.raw FROM observations o "
            "JOIN offset_recovery_events e ON e.company=o.company "
            "JOIN offset_recovery_plans p ON p.company=e.company AND p.plan_id=e.plan_id "
            "WHERE o.company=? AND o.id=? AND e.plan_id=? AND p.law=? AND e.event LIKE ?",
            (company, observation, plan_id, law, f'PAGE/%/{observation}'),
        ).fetchall()
        if len(saved) != 1:
            raise QueueError('OFFSET_RECOVERY_INFLIGHT_MISSING')
        scope_json, observed_at, digest, raw = saved[0]
        if (json.loads(scope_json)['law'] != law or hashlib.sha256(raw).hexdigest() != digest
                or hashlib.sha256((scope_json + '\n' + observed_at + '\n' + digest).encode())
                .hexdigest() != observation):
            raise QueueError('OFFSET_RECOVERY_PAGE_INVALID')
        return BatchResult('UNKNOWN', 'OFFSET_RECOVERY_ALREADY_RECONCILED', 0, None,
                           (observation,))
    attempt_id, raw_scope, observed = row
    data = json.loads(raw_scope)
    scope = Scope(data['company'], data['law'], datetime.fromisoformat(data['start']),
                  datetime.fromisoformat(data['end']), data['offset'], data['limit'])
    if scope.company != company or scope.law != law or scope.json() != raw_scope:
        raise QueueError('OFFSET_RECOVERY_SCOPE_INVALID')
    return _finish_offset_page(queue, company, law, plan_id, scope,
                               datetime.fromisoformat(observed), attempt_id, observation)
