"""Plan or consume a durable EIS corpus worklist; never print secrets."""

import argparse
import asyncio
import json
import os
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_attachment_recovery import (
    AttachmentRecoveryRunReport,
    read_attachment_recovery_plan,
    run_attachment_recovery,
)
from procurement.sources.eis_corpus import (
    EisCorpusScope,
    extend_corpus,
    plan_corpus,
    resource_gate,
    run_corpus,
)
from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_feed_sync import eis_browser_transport
from procurement.sources.eis_freshness import EisFreshnessReport, EisFreshnessScope, run_freshness
from procurement.sources.eis_freshness_status import freshness_status
from procurement.storage.eis_gap_status import read_eis_gap_status
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.repository import PostgresStorage


async def _fresh_pass(
    journal: EisSyncJournal,
    token: str,
    scope: EisFreshnessScope,
    *,
    now: datetime,
    max_windows: int,
    max_seconds: int,
    max_database_bytes: int,
    min_free_bytes: int,
) -> EisFreshnessReport:
    from procurement.eis_joint_budget import JointStartBudget

    budget_context = (
        JointStartBudget(Path("/var/lib/eis-browser"), journal.company_id)
        if os.environ.get("EIS_JOINT_BUDGET_ENABLED") == "1"
        else nullcontext(None)
    )
    with budget_context as budget:
        if budget is not None and not budget.can_start():
            return EisFreshnessReport(
                status="BLOCKED",
                company_id=journal.company_id,
                checked_at=now,
                regions=scope.regions,
                document_types=scope.document_types,
                selected=0,
                attempted=0,
                synced=0,
                no_data=0,
                new_versions=0,
                new_events=0,
                reason="JOINT_START_BUDGET_REACHED",
                window_keys=(),
            )
        async with eis_browser_transport() as transport:
            return await run_freshness(
                journal,
                token,
                scope,
                now=now,
                max_windows=max_windows,
                max_seconds=max_seconds,
                max_database_bytes=max_database_bytes,
                min_free_bytes=min_free_bytes,
                transport=transport,
                include_requests=True,
                paced_transport=True,
                joint_budget=budget,
            )


async def _corpus_pass(
    journal: EisSyncJournal,
    token: str,
    *,
    now: datetime,
    max_windows: int,
    max_database_bytes: int,
    min_free_bytes: int,
    priority_request: Path | None,
    regional_request: Path | None,
    mandatory_fresh_first: bool = False,
) -> dict[str, object]:
    """Reuse one lazy browser session for one bounded sequential corpus pass."""
    async with eis_browser_transport() as transport:
        return await run_corpus(
            journal,
            token,
            now=now,
            max_windows=max_windows,
            max_database_bytes=max_database_bytes,
            min_free_bytes=min_free_bytes,
            priority_request=priority_request,
            regional_request=regional_request,
            transport=transport,
            mandatory_fresh_first=mandatory_fresh_first,
        )


async def _attachment_recovery_pass(
    journal: EisSyncJournal,
    token: str,
    *,
    now: datetime,
    max_windows: int,
    max_seconds: int,
    max_database_bytes: int,
    min_free_bytes: int,
) -> AttachmentRecoveryRunReport:
    async with eis_browser_transport() as transport:
        return await run_attachment_recovery(
            journal,
            token,
            now=now,
            max_windows=max_windows,
            max_seconds=max_seconds,
            max_database_bytes=max_database_bytes,
            min_free_bytes=min_free_bytes,
            transport=transport,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resumable multi-region EIS queue")
    parser.add_argument(
        "action",
        choices=(
            "plan",
            "run",
            "fresh",
            "fresh-status",
            "gap-status",
            "attachment-recovery-status",
            "attachment-recovery",
        ),
    )
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument(
        "--regions", help="comma-separated two-digit codes; all = candidate codes 01..99"
    )
    parser.add_argument("--document-types", nargs="+", choices=SUPPORTED_NOTICE_TYPES)
    parser.add_argument("--from-day")
    parser.add_argument("--through-day")
    parser.add_argument("--max-windows", type=int)
    parser.add_argument("--max-database-gib", type=int, default=100)
    parser.add_argument("--min-free-gib", type=int, default=40)
    parser.add_argument("--max-seconds", type=int)
    parser.add_argument("--checkpointed", action="store_true")
    parser.add_argument("--mandatory-only", action="store_true")
    parser.add_argument("--mandatory-fresh-first", action="store_true")
    parser.add_argument("--cadence-seconds", type=int, default=300)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--priority-request", type=Path)
    parser.add_argument("--regional-request", type=Path)
    parser.add_argument(
        "--base-scope-sha256", help="extend committed baseline before consuming queue"
    )
    args = parser.parse_args(argv)
    is_recovery = args.action in {"attachment-recovery-status", "attachment-recovery"}
    if args.max_windows is None:
        args.max_windows = (
            3 if is_recovery else (24 if args.action in {"fresh", "fresh-status"} else 60)
        )
    if args.max_seconds is None:
        args.max_seconds = 600 if is_recovery else 240
    if is_recovery and (
        not 1 <= args.max_windows <= 3
        or not 1 <= args.max_seconds <= 600
        or args.max_database_gib <= 0
        or args.min_free_gib <= 0
        or args.regions
        or args.document_types
        or args.from_day
        or args.through_day
        or args.base_scope_sha256
    ):
        parser.error("attachment recovery requires 1..3 windows, 1..600 seconds and planned scope")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    now = datetime.now(UTC)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        journal = EisSyncJournal(PostgresStorage(engine), args.company_id, args.actor_id)
        if args.action == "gap-status":
            gap_report = read_eis_gap_status(
                journal.storage, journal.company_id, now=now, sample_limit=args.sample_limit
            )
            print(gap_report.model_dump_json())
            return 0
        if args.action == "attachment-recovery-status":
            recovery_plan = read_attachment_recovery_plan(journal, now=now, limit=args.max_windows)
            print(recovery_plan.model_dump_json())
            return 0
        if args.action == "attachment-recovery":
            recovery_token = os.environ.get("EIS_GETDOCS_IP_TOKEN")
            if not recovery_token:
                parser.error("EIS_GETDOCS_IP_TOKEN is required for attachment recovery")
            recovery_report = asyncio.run(
                _attachment_recovery_pass(
                    journal,
                    recovery_token,
                    now=now,
                    max_windows=args.max_windows,
                    max_seconds=args.max_seconds,
                    max_database_bytes=args.max_database_gib * 1024**3,
                    min_free_bytes=args.min_free_gib * 1024**3,
                )
            )
            print(recovery_report.model_dump_json())
            return 2 if recovery_report.status == "BLOCKED" else 0
        if args.action == "plan":
            if (
                not args.regions
                or not args.document_types
                or not args.from_day
                or not args.through_day
            ):
                parser.error("plan requires regions, document types and both dates")
            regions = (
                tuple(f"{code:02d}" for code in range(1, 100))
                if args.regions == "all"
                else tuple(args.regions.split(","))
            )
            scope = EisCorpusScope(
                regions,
                tuple(args.document_types),
                date.fromisoformat(args.from_day),
                date.fromisoformat(args.through_day),
            )
            created = plan_corpus(journal, scope, now=now)
            result: dict[str, object] = {
                "status": "PLANNED",
                "new_targets": created,
                "expected_windows": scope.expected_windows,
                "scope_sha256": scope.sha256,
                "region_registry_status": "UNKNOWN",
                "coverage": "UNKNOWN",
            }
        elif args.action == "fresh-status":
            if not args.regions or args.regions == "all":
                parser.error("fresh-status requires an explicit region scope")
            status = freshness_status(
                journal.storage,
                journal.company_id,
                EisFreshnessScope(
                    tuple(args.regions.split(",")),
                    tuple(args.document_types or SUPPORTED_NOTICE_TYPES),
                ),
                now=now,
                run_slots=args.max_windows,
                run_seconds=args.max_seconds,
                cadence_seconds=args.cadence_seconds,
            )
            print(status.model_dump_json())
            return 0
        elif args.action == "fresh":
            token = os.environ.get("EIS_GETDOCS_IP_TOKEN")
            if not token or not args.regions or args.regions == "all":
                parser.error("fresh requires token and an explicit measured region scope")
            regions = tuple(args.regions.split(","))
            if args.regions == "official":
                from procurement.storage.eis_223_regions import _accepted_catalog

                with journal.storage.transaction(args.company_id, consistent_read=True) as conn:
                    catalog = _accepted_catalog(conn, args.company_id)
                if catalog is None:
                    raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
                regions = tuple(sorted(catalog["regions"]))
            report = asyncio.run(
                _fresh_pass(
                    journal,
                    token,
                    EisFreshnessScope(
                        regions,
                        tuple(args.document_types or SUPPORTED_NOTICE_TYPES),
                        checkpointed=args.checkpointed,
                        mandatory_only=args.mandatory_only,
                    ),
                    now=now,
                    max_windows=args.max_windows,
                    max_seconds=args.max_seconds,
                    max_database_bytes=args.max_database_gib * 1024**3,
                    min_free_bytes=args.min_free_gib * 1024**3,
                )
            )
            result = asdict(report)
            result["observations"] = [item.model_dump(mode="json") for item in report.observations]
        else:
            token = os.environ.get("EIS_GETDOCS_IP_TOKEN")
            if not token:
                parser.error("EIS_GETDOCS_IP_TOKEN is required for run")
            if args.base_scope_sha256:
                stopped = resource_gate(
                    journal.storage,
                    journal.company_id,
                    max_database_bytes=args.max_database_gib * 1024**3,
                    min_free_bytes=args.min_free_gib * 1024**3,
                )
                if stopped:
                    print(
                        json.dumps({"status": "BLOCKED", "reason": stopped, "coverage": "UNKNOWN"})
                    )
                    return 2
                extend_corpus(journal, args.base_scope_sha256, now=now)
            result = asyncio.run(
                _corpus_pass(
                    journal,
                    token,
                    now=now,
                    max_windows=args.max_windows,
                    max_database_bytes=args.max_database_gib * 1024**3,
                    min_free_bytes=args.min_free_gib * 1024**3,
                    priority_request=args.priority_request,
                    regional_request=args.regional_request,
                    mandatory_fresh_first=args.mandatory_fresh_first,
                )
            )
        print(json.dumps(result, default=str))
        return 2 if result["status"] == "BLOCKED" else 0
    except (ValueError, SQLAlchemyError):
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": "CORPUS_CONFIG_OR_DATABASE_FAILED",
                    "coverage": "UNKNOWN",
                }
            )
        )
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
