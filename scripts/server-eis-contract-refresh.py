"""One official contract refresh under the existing host lease and joint budget.

Regional selection discovers candidates only. Every admitted result is fetched again
by registry number, reconciled with PRIZ and current public cards by the worker.
No loader schedule or network policy is changed by this entry point.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import create_engine, func, select, text

from procurement.eis_freshness_dispatch_cli import joint_mandatory_status, urgent44_status
from procurement.eis_joint_budget import JointStartBudget
from procurement.sources.eis_contract_results import EXPORT, contract_result
from procurement.sources.eis_contract_sync import fetch_official_bundle
from procurement.sources.eis_contract_worker import _safe_error, refresh_contract_observation
from procurement.sources.eis_feed_sync import EisHourSelection, eis_browser_transport
from procurement.storage.eis_contract_schema import contract_observations
from procurement.storage.models import audit_events
from procurement.storage.repository import PostgresStorage

MAX_SECONDS = 180
MAX_CANDIDATES = 512
MIN_FREE_BYTES = 40 * 1024**3
MAX_DB_BYTES = 100 * 1024**3


def due_registry(storage, company, numbers, *, now):
    """Absent/oldest first; failed first observations also receive a durable backoff."""
    if not 1 <= len(numbers) <= MAX_CANDIDATES:
        raise ValueError("HISTORY_DISCOVERY_LIMIT")
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
        observed = dict(
            conn.execute(
                select(
                    contract_observations.c.registry_number,
                    func.max(contract_observations.c.checked_at),
                )
                .where(
                    contract_observations.c.company_id == company,
                    contract_observations.c.registry_number.in_(numbers),
                )
                .group_by(contract_observations.c.registry_number)
            ).all()
        )
        failed = dict(
            conn.execute(
                select(audit_events.c.object_id, func.max(audit_events.c.occurred_at))
                .where(
                    audit_events.c.company_id == company,
                    audit_events.c.object_type == "eis_contract_history",
                    audit_events.c.event_type.in_(
                        (
                            "EIS_CONTRACT_HISTORY_REFRESH_FAILED",
                            "EIS_CONTRACT_HISTORY_REFRESH_PENDING",
                        )
                    ),
                    audit_events.c.object_id.in_(numbers),
                    audit_events.c.occurred_at >= now - timedelta(days=1),
                )
                .group_by(audit_events.c.object_id)
            ).all()
        )
    oldest = datetime.min.replace(tzinfo=UTC)
    times = {n: max(observed.get(n, oldest), failed.get(n, oldest)) for n in numbers}
    due = [n for n in numbers if times[n] <= now - timedelta(minutes=10)]
    return min(due, key=lambda n: (times[n], n)) if due else None


def discovery_numbers(bundle):
    """Bounded source identities only; unsupported records do not establish coverage."""
    bundle.validate()
    found = set()
    for member, raw in bundle.xml_documents():
        root = ET.fromstring(raw)
        if len(root) != 1 or root[0].tag != f"{{{EXPORT}}}contract":
            continue
        try:
            result = contract_result(raw, member)
        except ValueError:
            continue
        if result.version == 0:
            found.add(result.registry_number)
        if len(found) > MAX_CANDIDATES:
            raise ValueError("HISTORY_DISCOVERY_LIMIT")
    return tuple(sorted(found))


async def run(args):
    company = args.company
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", company):
        raise ValueError("HISTORY_COMPANY_INVALID")
    storage = PostgresStorage(create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True))
    base = {"status": "UNKNOWN", "source_requests": 0, "coverage": "UNKNOWN"}
    # Only the host wrapper may assert its already-acquired global flock.
    if os.environ.get("EIS_CONTRACT_HOST_LEASE_HELD") != "1":
        return {**base, "reason": "SERVER_IMPORT_LEASE_REQUIRED"}
    now = datetime.now(UTC)
    if (
        urgent44_status(storage, company, now) != "IDLE"
        or joint_mandatory_status(storage, company, now) != "IDLE"
    ):
        return {**base, "reason": "MANDATORY_FRESH_WORK_READY_OR_UNKNOWN"}
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        size = conn.scalar(text("SELECT pg_database_size(current_database())"))
    if size is None or size >= MAX_DB_BYTES:
        return {**base, "reason": "DATABASE_BUDGET_REACHED"}
    if shutil.disk_usage("/var/lib/eis-browser").free < MIN_FREE_BYTES:
        return {**base, "reason": "DISK_RESERVE_REACHED"}
    if args.probe:
        return {**base, "status": "READY"}
    with JointStartBudget(Path("/var/lib/eis-browser"), company) as budget:
        if not budget.can_start():
            return {**base, "reason": "JOINT_START_BUDGET_REACHED"}
        budget.begin_window(None)
        try:
            base["source_requests"] = "UNKNOWN_UNTIL_RECEIPTS"
            async with asyncio.timeout(MAX_SECONDS), eis_browser_transport() as transport:
                token = os.environ["EIS_GETDOCS_IP_TOKEN"]
                if args.registry:
                    numbers = (args.registry,)
                else:
                    selection = EisHourSelection(args.region, args.day, args.hour, 3)
                    discovery = await fetch_official_bundle(
                        transport, token, subsystem="RGK", selection=selection
                    )
                    numbers = discovery_numbers(discovery)
                    base["discovery"] = discovery.receipt()
                    base["discovered"] = len(numbers)
                if not numbers:
                    return {**base, "reason": "NO_SUPPORTED_DISCOVERY_CANDIDATES"}
                registry = due_registry(storage, company, numbers, now=datetime.now(UTC))
                if registry is None:
                    return {**base, "status": "IDLE", "reason": "HISTORY_REFRESH_BACKOFF"}
                result = await refresh_contract_observation(
                    storage,
                    company,
                    registry,
                    actor="contract-refresh",
                    transport=transport,
                    token=token,
                    timeout_seconds=MAX_SECONDS,
                )
                return {**base, **asdict(result), "source_requests": "SEE_SOURCE_RECEIPTS"}
        finally:
            budget.end_window()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", default="local-eis-supplier")
    parser.add_argument("--probe", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--registry")
    mode.add_argument("--region")
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--hour", type=int, choices=range(24))
    args = parser.parse_args()
    if args.registry and not re.fullmatch(r"[0-9]{19,23}", args.registry):
        parser.error("registry must be an official numeric identity")
    if args.region and (
        not re.fullmatch(r"[0-9]{1,2}", args.region) or args.day is None or args.hour is None
    ):
        parser.error("regional discovery requires --region, --day and --hour")
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        reasons, source_error = _safe_error(error)
        result = {
            "status": "UNKNOWN",
            "reasons": reasons,
            "coverage": "UNKNOWN",
            "source_requests": "UNKNOWN",
            "source_error": asdict(source_error) if source_error is not None else None,
        }
    print(json.dumps(result, default=lambda value: value.isoformat(), ensure_ascii=False))
    return 0 if result.get("status") in {"PASS", "IDLE", "READY"} else 75


if __name__ == "__main__":
    raise SystemExit(main())
