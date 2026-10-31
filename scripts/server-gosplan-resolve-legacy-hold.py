"""Resolve a legacy hold without a network request, preserving unknown evidence and cursors."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope, release_guard_active

COMPANY = "local-eis-supplier"
QUEUE = Path("/var/lib/eis-browser/gosplan/local-eis-supplier/queue.sqlite")
PLAN = Path("/run/gosplan/legacy-resolution-plan.json")
DIAGNOSTIC = Path("/run/gosplan/legacy-diagnostic.json")
OFFSET_PLAN = Path("/run/gosplan/offset-recovery-plan.json")
CYCLE_LOCK = Path("/run/gosplan/cycle.lock")
IMPORT_LOCK = Path("/run/gosplan/eis-import.lock")


def read_bounded(path: Path, expected_sha: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
        raise QueueError("RESOLUTION_DIGEST_INVALID")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise QueueError("RESOLUTION_FILE_INVALID")
        raw = stream.read(65537)
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise QueueError("RESOLUTION_FILE_CHANGED")
    return raw


def resolve(queue: GosplanQueue, plan: dict, diagnostic_raw: bytes, plan_sha: str) -> bool:
    """Check independent evidence; the old response and old cause remain UNKNOWN."""
    if set(plan) != {
        "company_id", "authorization", "diagnostic_file_sha256", "diagnostic_response_sha256",
        "expected_cursors", "resolved_at", "old_response", "old_cause", "coverage",
    }:
        raise QueueError("RESOLUTION_PLAN_INVALID")
    if (
        plan["company_id"] != COMPANY
        or plan["authorization"] != "USER_STANDING_AUTHORIZATION"
        or plan["old_response"] != "UNAVAILABLE"
        or plan["old_cause"] != "UNKNOWN"
        or plan["coverage"] != "UNKNOWN"
        or hashlib.sha256(diagnostic_raw).hexdigest() != plan["diagnostic_file_sha256"]
    ):
        raise QueueError("RESOLUTION_PLAN_INVALID")
    try:
        diag = json.loads(diagnostic_raw)
        if (
            diag["status"] != "UNKNOWN" or diag["http_status"] != 200
            or diag["parser"] != "TYPE_INVALID"
            or diag["invalid_type"] != {"json_type": "NoneType", "row": 81}
            or diag["law"] != "44" or diag["limit"] != 100 or diag["offset"] != 300
            or diag["hold_unchanged"] is not True or diag["cursor_unchanged"] is not True
            or diag["response_sha256"] != plan["diagnostic_response_sha256"]
        ):
            raise QueueError("DIAGNOSTIC_MISMATCH")
        start = datetime.fromisoformat(diag["start"])
        end = datetime.fromisoformat(diag["end"])
        when = datetime.fromisoformat(plan["resolved_at"])
        requested_at = datetime.fromisoformat(diag["requested_at"])
        if (when.tzinfo is None or when.utcoffset() is None or requested_at.tzinfo is None
                or requested_at.utcoffset() is None or when < requested_at):
            raise QueueError("DIAGNOSTIC_TIME_INVALID")
        scope = Scope(COMPANY, "44", start, end, 300, 100)
        cursors = tuple(tuple(c) for c in plan["expected_cursors"])
        matching = [c for c in cursors if len(c) == 5 and c[0] == "44"]
        if len(matching) != 1 or matching[0][2:] != (diag["start"], diag["end"], 300):
            raise QueueError("DIAGNOSTIC_SCOPE_MISMATCH")
    except (TypeError, ValueError, KeyError) as exc:
        raise QueueError("RESOLUTION_INPUT_INVALID") from exc
    return queue.resolve_legacy_type_hold(
        company=COMPANY, actor_id="codex-owner", resolution_id=plan_sha, resolved_at=when,
        diagnostic_response_sha=plan["diagnostic_response_sha256"], diagnostic_scope=scope,
        expected_cursors=cursors,
    )


def resolve_null_gap(queue: GosplanQueue, plan: dict) -> int:
    """Bind this post-legacy rejection and reconcile it without network access."""
    if set(plan) != {
        "company_id", "authorization", "observation_id", "response_sha256",
        "legacy_resolution_id", "binding_mode", "actor_id", "resolved_at", "coverage",
    } or (plan["company_id"] != COMPANY
          or plan["authorization"] != "USER_STANDING_AUTHORIZATION"
          or plan["coverage"] != "UNKNOWN"
          or plan["binding_mode"] not in ("POST_LEGACY", "AUTO_BOUND")
          or (plan["binding_mode"] == "AUTO_BOUND" and plan["legacy_resolution_id"] is not None)
          or (plan["binding_mode"] == "POST_LEGACY" and not isinstance(
              plan["legacy_resolution_id"], str))):
        raise QueueError("NULL_GAP_PLAN_INVALID")
    try:
        when = datetime.fromisoformat(plan["resolved_at"])
        row = queue.conn.execute(
            "SELECT response_sha FROM rejected_pages WHERE company=? AND id=?",
            (COMPANY, plan["observation_id"]),
        ).fetchone()
        if row != (plan["response_sha256"],):
            raise QueueError("NULL_GAP_SOURCE_CHANGED")
        resolved = queue.conn.execute(
            "SELECT 1 FROM partial_page_resolutions WHERE company=? AND observation_id=?",
            (COMPANY, plan["observation_id"]),
        ).fetchone()
        if not resolved and plan["binding_mode"] == "POST_LEGACY":
            queue.bind_post_legacy_hold(
                COMPANY, plan["observation_id"], plan["legacy_resolution_id"],
                plan["actor_id"], when,
            )
        elif resolved and plan["binding_mode"] == "POST_LEGACY" and queue.conn.execute(
            "SELECT resolution_id,actor_id,bound_at FROM provider_hold_binding_audit "
            "WHERE company=? AND observation_id=?", (COMPANY, plan["observation_id"]),
        ).fetchone() != (plan["legacy_resolution_id"], plan["actor_id"], when.isoformat()):
            raise QueueError("NULL_GAP_BINDING_CHANGED")
        elif plan["binding_mode"] == "AUTO_BOUND":
            binding_audit = queue.conn.execute(
                "SELECT 1 FROM provider_hold_binding_audit WHERE company=? AND observation_id=?",
                (COMPANY, plan["observation_id"]),
            ).fetchone()
            if binding_audit is not None:
                raise QueueError("NULL_GAP_BINDING_CHANGED")
        return queue.reconcile_null_type_page(
            COMPANY, plan["observation_id"], plan["actor_id"], when,
        )
    except (TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, QueueError):
            raise
        raise QueueError("NULL_GAP_PLAN_INVALID") from exc


def resolve_offset_plan(queue: GosplanQueue, plan: dict, operation: str) -> str:
    """Prepare or activate one exact offline split; never request provider data."""
    if (set(plan) != {'company_id', 'authorization', 'operation', 'law', 'actor_id',
                      'prepared_at', 'expected_cursor', 'source_observation_id', 'coverage',
                      'original_cause', 'prepared_plan_id'}
            or plan['company_id'] != COMPANY
            or plan['authorization'] != 'USER_STANDING_AUTHORIZATION'
            or plan['operation'] != operation or operation not in ('prepare', 'activate')
            or plan['law'] not in ('44', '223') or plan['coverage'] != 'UNKNOWN'
            or not isinstance(plan['actor_id'], str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', plan['actor_id'])
            or plan['original_cause'] != 'UNKNOWN'
            or (operation == 'prepare' and plan['prepared_plan_id'] is not None)
            or (operation == 'activate' and not isinstance(plan['prepared_plan_id'], str))):
        raise QueueError('OFFSET_PLAN_INVALID')
    try:
        when = datetime.fromisoformat(plan['prepared_at'])
        cursor = tuple(plan['expected_cursor'])
        if operation == 'activate':
            row = queue.conn.execute(
                "SELECT actor_id,prepared_at,source_observation_id,original_state "
                "FROM offset_recovery_plans WHERE company=? AND law=? AND plan_id=?",
                (COMPANY, plan['law'], plan['prepared_plan_id']),
            ).fetchone()
            if (row is None or row[:3] != (plan['actor_id'], when.isoformat(),
                                          plan['source_observation_id'])
                    or json.loads(row[3])['cursor'] != list(cursor)):
                raise QueueError('OFFSET_PLAN_CHANGED')
            plan_id = plan['prepared_plan_id']
            queue.activate_offset_recovery(company=COMPANY, law=plan['law'], plan_id=plan_id)
        else:
            plan_id = queue.prepare_offset_recovery(
                company=COMPANY, law=plan['law'], actor_id=plan['actor_id'], prepared_at=when,
                expected_cursor=cursor, source_observation_id=plan['source_observation_id'],
            )
        return plan_id
    except (TypeError, KeyError, ValueError) as exc:
        if isinstance(exc, QueueError):
            raise
        raise QueueError('OFFSET_PLAN_INVALID') from exc


def resolve_offset_reconciliation(queue: GosplanQueue, plan: dict, operation: str) -> str:
    """Reconcile only an exact retained split page without contacting a source."""
    if (set(plan) != {'company_id', 'authorization', 'operation', 'law', 'actor_id',
                      'resolved_at', 'plan_id', 'observation_id', 'response_sha256', 'coverage'}
            or plan['company_id'] != COMPANY
            or plan['authorization'] != 'USER_STANDING_AUTHORIZATION'
            or plan['operation'] != operation or operation not in ('page', 'null')
            or plan['law'] not in ('44', '223') or plan['coverage'] != 'UNKNOWN'
            or not isinstance(plan['actor_id'], str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', plan['actor_id'])
            or not re.fullmatch(r'[a-f0-9]{64}', plan['plan_id'])
            or not re.fullmatch(r'[a-f0-9]{64}', plan['observation_id'])
            or not re.fullmatch(r'[a-f0-9]{64}', plan['response_sha256'])):
        raise QueueError('OFFSET_RECONCILE_PLAN_INVALID')
    try:
        when = datetime.fromisoformat(plan['resolved_at'])
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError
        table = 'observations' if operation == 'page' else 'rejected_pages'
        row = queue.conn.execute(
            f'SELECT response_sha FROM {table} WHERE company=? AND id=?',
            (COMPANY, plan['observation_id']),
        ).fetchone()
        if row != (plan['response_sha256'],):
            raise QueueError('OFFSET_RECONCILE_SOURCE_CHANGED')
        if queue.conn.execute(
            'SELECT law FROM offset_recovery_plans WHERE company=? AND plan_id=?',
            (COMPANY, plan['plan_id']),
        ).fetchone() != (plan['law'],):
            raise QueueError('OFFSET_RECONCILE_PLAN_INVALID')
        if operation == 'page':
            from procurement.sources.gosplan_scan import reconcile_offset_page
            result = reconcile_offset_page(queue, COMPANY, plan['law'], plan['plan_id'],
                                           plan['observation_id'])
            return result.reason
        return str(queue.reconcile_offset_null_page(
            COMPANY, plan['plan_id'], plan['observation_id'], plan['actor_id'], when,
        ))
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, QueueError):
            raise
        raise QueueError('OFFSET_RECONCILE_PLAN_INVALID') from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan-sha256")
    group.add_argument("--null-plan-sha256")
    group.add_argument("--offset-prepare-sha256")
    group.add_argument("--offset-activate-sha256")
    group.add_argument("--offset-reconcile-page-sha256")
    group.add_argument("--offset-reconcile-null-sha256")
    parser.add_argument("--lock-identity")
    parser.add_argument("--import-lock-identity")
    args = parser.parse_args()
    if release_guard_active():
        raise QueueError("RELEASE_GUARD")
    offset_digest = (args.offset_prepare_sha256 or args.offset_activate_sha256
                     or args.offset_reconcile_page_sha256 or args.offset_reconcile_null_sha256)
    if offset_digest:
        if (not args.lock_identity or not re.fullmatch(r'\d+:\d+', args.lock_identity)
                or not args.import_lock_identity
                or not re.fullmatch(r'\d+:\d+', args.import_lock_identity)):
            raise QueueError('CYCLE_LEASE_INVALID')
        fd = os.open(CYCLE_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        import_fd = None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or f'{info.st_dev}:{info.st_ino}' != args.lock_identity):
                raise QueueError('CYCLE_LEASE_INVALID')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueError('CYCLE_LEASE_BUSY') from exc
            import_fd = os.open(IMPORT_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(import_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or f'{info.st_dev}:{info.st_ino}' != args.import_lock_identity):
                raise QueueError('IMPORT_LEASE_INVALID')
            try:
                fcntl.flock(import_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueError('IMPORT_LEASE_BUSY') from exc
            if release_guard_active():
                raise QueueError('RELEASE_GUARD')
            raw = read_bounded(OFFSET_PLAN, offset_digest)
            plan = json.loads(raw)
            queue = GosplanQueue(QUEUE)
            try:
                if args.offset_reconcile_page_sha256 or args.offset_reconcile_null_sha256:
                    operation = 'page' if args.offset_reconcile_page_sha256 else 'null'
                    detail = resolve_offset_reconciliation(queue, plan, operation)
                    plan_id = plan['plan_id']
                else:
                    operation = 'prepare' if args.offset_prepare_sha256 else 'activate'
                    plan_id = resolve_offset_plan(queue, plan, operation)
            finally:
                queue.close()
            output = {'status': 'OFFSET_' + operation.upper() + '_UNKNOWN',
                      'plan_sha256': offset_digest, 'recovery_plan_id': plan_id,
                      'source_requests': 0, 'coverage': 'UNKNOWN'}
            if operation in ('page', 'null'):
                output['result'] = detail
            print(json.dumps(output))
        finally:
            if import_fd is not None:
                os.close(import_fd)
            os.close(fd)
        return
    if os.environ.get("GOSPLAN_CYCLE_LEASE_HELD") != "1":
        raise QueueError("CYCLE_LEASE_REQUIRED")
    digest = args.plan_sha256 or args.null_plan_sha256
    raw = read_bounded(PLAN, digest)
    plan = json.loads(raw)
    queue = GosplanQueue(QUEUE)
    try:
        if args.null_plan_sha256:
            gaps = resolve_null_gap(queue, plan)
            result = {"status": "NULL_GAPS_UNKNOWN", "gaps": gaps}
        else:
            diagnostic = read_bounded(DIAGNOSTIC, plan["diagnostic_file_sha256"])
            changed = resolve(queue, plan, diagnostic, digest)
            result = {"status": "RESOLVED_UNKNOWN" if changed else "ALREADY_RESOLVED_UNKNOWN"}
    finally:
        queue.close()
    print(json.dumps({**result, "plan_sha256": digest, "source_requests": 0,
                      "coverage": "UNKNOWN"}))


if __name__ == "__main__":
    main()
