"""Read planned EIS windows without a completed archive checkpoint."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.repository import PostgresStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List unresolved EIS date windows")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--region", help="optional two-digit EIS region code")
    parser.add_argument("--limit", type=int, default=100, help="1-999")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    if not 1 <= args.limit <= 999:
        parser.error("limit must be 1-999")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        journal = EisSyncJournal(PostgresStorage(engine), args.company_id, "eis-gap-reader")
        rows = journal.gaps(region=args.region, limit=args.limit + 1)
    except (ValueError, SQLAlchemyError) as error:
        code = str(error) if isinstance(error, ValueError) else "DATABASE_FAILED"
        print(json.dumps({"status": "FAILED", "reason": code, "coverage": "UNKNOWN"}))
        return 2
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "OK",
                "coverage": "UNKNOWN",
                "has_more": len(rows) > args.limit,
                "gaps": [asdict(item) for item in rows[: args.limit]],
            },
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
