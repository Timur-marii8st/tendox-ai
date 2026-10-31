"""One Gosplan candidate via official EIS; run only via the guarded host wrapper."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from procurement.eis_freshness_dispatch_cli import joint_mandatory_status, urgent44_status
from procurement.eis_history_demand import _reconciliation_days
from procurement.eis_history_reader import read_history_demand
from procurement.eis_joint_budget import JointStartBudget
from procurement.sources.eis_feed_sync import eis_browser_transport
from procurement.sources.gosplan_queue import (
    GosplanQueue,
    OffsetRecoveryReserved,
    release_guard_active,
)
from procurement.sources.gosplan_recovery import RECOVERABLE_44, recover_one_44, recover_one_223
from procurement.sources.gosplan_turn_ledger import finish_turn, start_turn
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
QUEUE = Path("/var/lib/eis-browser/gosplan/local-eis-supplier/queue.sqlite")
STATE_ROOT = Path("/var/lib/eis-browser")


async def run(law: str, number: str) -> dict[str, object]:
    if release_guard_active():
        return {"status": "UNKNOWN", "reason": "RELEASE_GUARD"}
    if os.environ.get("GOSPLAN_IMPORT_LEASE_HELD") != "1":
        return {"status": "UNKNOWN", "reason": "IMPORT_LEASE_REQUIRED"}
    if not QUEUE.is_file() or QUEUE.is_symlink():
        return {"status": "UNKNOWN", "reason": "QUEUE_UNAVAILABLE"}
    storage = PostgresStorage.from_url(
        os.environ["DATABASE_URL"],
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
    )
    now = datetime.now(UTC)
    priority = {
        "urgent44": urgent44_status(storage, COMPANY, now),
        "joint_mandatory": joint_mandatory_status(storage, COMPANY, now),
    }
    if any(status not in ("IDLE", "READY") for status in priority.values()):
        return {"status": "UNKNOWN", "reason": "MANDATORY_WORK_NOT_IDLE", "priority": priority}
    demand = read_history_demand(storage, COMPANY, verify_quarantine=True)
    if (
        demand.classification.status not in ("IDLE", "READY")
        or not demand.evidence_sha256
        or not demand.evidence
    ):
        return {
            "status": "UNKNOWN",
            "reason": "TRUSTED_DEMAND_NOT_IDLE",
            "demand_status": demand.classification.status,
        }
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        db_size = conn.scalar(text("SELECT pg_database_size(current_database())"))
    if (
        db_size is None
        or db_size >= 100 * 1024**3
        or shutil.disk_usage("/var/lib/eis-browser").free < 40 * 1024**3
    ):
        return {"status": "UNKNOWN", "reason": "SOURCE_CAPACITY_GUARD"}
    queue = GosplanQueue(QUEUE)
    try:
        if (law, number) not in {(item[0], item[1]) for item in queue.pending(COMPANY)}:
            return {"status": "UNKNOWN", "reason": "CANDIDATE_NOT_PENDING"}
        if law == "44" and queue.candidate_type(COMPANY, "44", number) not in RECOVERABLE_44:
            return {"status": "UNKNOWN", "reason": "UNSUPPORTED_FAMILY"}
        if law == "223":
            from procurement.sources.eis_223_number_sync import FAMILIES

            if queue.candidate_type(COMPANY, "223", number) not in FAMILIES:
                return {"status": "UNKNOWN", "reason": "UNSUPPORTED_FAMILY"}
        if queue.conn.execute(
            "SELECT 1 FROM attempts WHERE company=? AND outcome IS NULL LIMIT 1", (COMPANY,)
        ).fetchone():
            return {"status": "UNKNOWN", "reason": "QUEUE_ATTEMPT_UNRESOLVED"}
        with JointStartBudget(STATE_ROOT, COMPANY) as budget:
            if not budget.protected_reconciliation:
                return {"status": "UNKNOWN", "reason": "PROTECTED_SHARES_REQUIRED"}
            if not budget.can_start(pending_reconciliation=("44", "223")):
                return {"status": "UNKNOWN", "reason": "JOINT_BUDGET_EXHAUSTED"}
            checked = demand.classification.checked_at
            current = datetime.now(UTC)
            if (
                checked is None
                or checked > current
                or (current - checked).total_seconds() > 30
                or any(
                    _reconciliation_days(k, checked) != _reconciliation_days(k, current)
                    for k in ("44", "223")
                )
            ):
                return {"status": "UNKNOWN", "reason": "DEMAND_SNAPSHOT_EXPIRED"}
            turn = start_turn(
                storage, COMPANY, law, number, demand.evidence_sha256, demand.evidence
            )
            if turn is None:
                return {"status": "UNKNOWN", "reason": "TURN_UNRESOLVED_OR_HOURLY_LIMIT"}
            current = datetime.now(UTC)
            if (
                current < checked
                or (current - checked).total_seconds() > 30
                or any(
                    _reconciliation_days(k, checked) != _reconciliation_days(k, current)
                    for k in ("44", "223")
                )
                or not budget.can_start(pending_reconciliation=("44", "223"))
            ):
                finish_turn(storage, COMPANY, turn, "NOT_STARTED")
                return {"status": "UNKNOWN", "reason": "DEMAND_OR_BUDGET_EXPIRED"}
            budget.begin_window(None)
            try:
                async with asyncio.timeout(180), eis_browser_transport() as transport:
                    fn = recover_one_44 if law == "44" else recover_one_223
                    try:
                        status = await fn(
                            queue,
                            storage,
                            COMPANY,
                            number,
                            os.environ["EIS_GETDOCS_IP_TOKEN"],
                            transport,
                        )
                    except OffsetRecoveryReserved:
                        # claim() raised before creating an attempt or touching EIS.
                        finish_turn(storage, COMPANY, turn, "NOT_STARTED")
                        return {"status": "UNKNOWN", "reason": "OFFSET_RECOVERY_RESERVED"}
                if status in {"SYNCED", "NO_DATA", "PREPARING", "SERVICE_ERROR"}:
                    finish_turn(storage, COMPANY, turn, status)
                return {
                    "status": status,
                    "law": law,
                    "number": number,
                    "coverage": "UNKNOWN",
                    "priority": priority,
                }
            finally:
                budget.end_window()
    finally:
        queue.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--law", choices=("44", "223"), required=True)
    parser.add_argument("--number", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.law, args.number))
    except Exception as error:
        result = {
            "status": "UNKNOWN",
            "reason": "GUARD_OR_RUNTIME_ERROR",
            "error_type": type(error).__name__,
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "SYNCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
