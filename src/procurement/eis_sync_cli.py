"""One-date or one-hour EIS intake without logging the getDocsIP credential."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_feed_archive import (
    DEFAULT_NOTICE_TYPE,
    SUPPORTED_NOTICE_TYPES,
    EisFeedArchiveError,
)
from procurement.sources.eis_feed_sync import (
    EisDateSelection,
    EisHourSelection,
    EisSyncError,
    sync_eis_window_via_browser,
)
from procurement.storage.eis_notice_index import EisIndexConflict
from procurement.storage.repository import PostgresStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import one EIS auction date or hour (44-FZ)")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--region", required=True, help="two-digit EIS region code")
    parser.add_argument(
        "--document-type", choices=SUPPORTED_NOTICE_TYPES, default=DEFAULT_NOTICE_TYPE
    )
    parser.add_argument("--day", required=True, help="YYYY-MM-DD")
    period = parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--hour", type=int, help="0-23, for regular synchronization")
    period.add_argument("--exact-date", action="store_true", help="whole date for backfill")
    parser.add_argument("--utc-offset", type=int, required=True, help="hours relative to UTC")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    token = os.environ.get("EIS_GETDOCS_IP_TOKEN")
    if not database_url or not token:
        parser.error("DATABASE_URL and EIS_GETDOCS_IP_TOKEN are required")
    try:
        day = date.fromisoformat(args.day)
        selection = (
            EisDateSelection(args.region, day, args.utc_offset, args.document_type)
            if args.exact_date
            else EisHourSelection(args.region, day, args.hour, args.utc_offset, args.document_type)
        )
    except ValueError:
        parser.error("invalid region, date, hour or UTC offset")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        result = asyncio.run(
            sync_eis_window_via_browser(
                PostgresStorage(engine), args.company_id, args.actor_id, selection, token
            )
        )
    except (EisSyncError, EisFeedArchiveError, EisIndexConflict, SQLAlchemyError) as error:
        code = "DATABASE_FAILED" if isinstance(error, SQLAlchemyError) else str(error)
        print(json.dumps({"status": "FAILED", "reason": code}))
        return 2
    finally:
        engine.dispose()
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0 if result.status in {"SYNCED", "SKIPPED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
