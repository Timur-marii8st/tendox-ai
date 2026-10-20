"""Bounded historical EIS backfill; no credential values in output."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_backfill import (
    EisBackfillIncomplete,
    backfill_eis_dates,
    recent_completed_date_range,
)
from procurement.sources.eis_feed_archive import DEFAULT_NOTICE_TYPE, SUPPORTED_NOTICE_TYPES
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.repository import PostgresStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import up to 31 completed EIS dates")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--document-type", choices=SUPPORTED_NOTICE_TYPES, default=DEFAULT_NOTICE_TYPE
    )
    parser.add_argument("--from-day", help="YYYY-MM-DD")
    parser.add_argument("--through-day", help="YYYY-MM-DD")
    parser.add_argument("--recent-days", type=int, help="last 1-31 completed local dates")
    parser.add_argument("--utc-offset", type=int, required=True)
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    token = os.environ.get("EIS_GETDOCS_IP_TOKEN")
    if not database_url or not token:
        parser.error("DATABASE_URL and EIS_GETDOCS_IP_TOKEN are required")
    reference_now = datetime.now(UTC)
    if args.recent_days is not None:
        if args.from_day or args.through_day or not 1 <= args.recent_days <= 31:
            parser.error("use --recent-days 1-31 without an explicit date range")
        try:
            first_day, last_day = recent_completed_date_range(
                reference_now, args.utc_offset, args.recent_days
            )
        except ValueError:
            parser.error("invalid UTC offset or recent-day count")
    else:
        if not args.from_day or not args.through_day:
            parser.error("provide both --from-day and --through-day, or --recent-days")
        try:
            first_day = date.fromisoformat(args.from_day)
            last_day = date.fromisoformat(args.through_day)
        except ValueError:
            parser.error("invalid date format")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        storage = PostgresStorage(engine)
        journal = EisSyncJournal(storage, args.company_id, args.actor_id)
        summary = asyncio.run(
            backfill_eis_dates(
                storage,
                args.company_id,
                args.actor_id,
                args.region,
                first_day,
                last_day,
                args.utc_offset,
                token,
                now=reference_now,
                journal=journal,
                document_type=args.document_type,
            )
        )
    except EisBackfillIncomplete as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "day": error.day.isoformat(),
                    "reason": error.code,
                    "completed_days": error.completed_days,
                    "coverage": "UNKNOWN",
                }
            )
        )
        return 2
    except (ValueError, SQLAlchemyError) as error:
        code = str(error) if isinstance(error, ValueError) else "DATABASE_FAILED"
        print(json.dumps({"status": "FAILED", "reason": code, "coverage": "UNKNOWN"}))
        return 2
    finally:
        engine.dispose()
    has_gaps = bool(summary.no_data_observations)
    print(
        json.dumps(
            {"status": "PARTIAL" if has_gaps else "COMPLETE", **asdict(summary)},
            default=str,
        )
    )
    return 2 if has_gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
