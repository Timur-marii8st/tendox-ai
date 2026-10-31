"""One bounded provider page compared with tenant-scoped EIS snapshots; read-only."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.gosplan_discovery import GosplanError, classify, fetch_page
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope
from procurement.storage.models import eis_223_notice_versions, eis_notice_versions
from procurement.storage.repository import PostgresStorage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--law", choices=("44", "223"), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--queue", type=Path, help="Optional protected local observation store")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.company):
            raise ValueError("COMPANY_INVALID")
        key = os.environ["GOSPLAN_API_KEY"]
        storage = PostgresStorage.from_url(
            os.environ["DATABASE_URL"],
            hide_parameters=True,
            connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
        )
        start, end = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
        observed_at = datetime.now(UTC)
        scope = Scope(args.company, args.law, start, end, args.offset, args.limit)
        with httpx.Client(timeout=25, trust_env=True) as client:
            page = fetch_page(
                client,
                key,
                args.law,
                start=start,
                end=end,
                offset=args.offset,
                limit=args.limit,
                now=observed_at,
            )
        table = eis_notice_versions if args.law == "44" else eis_223_notice_versions
        numbers = [c.number for c in page.candidates]
        with storage.transaction(args.company, consistent_read=True) as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            present = set(
                conn.scalars(
                    select(table.c.purchase_number)
                    .distinct()
                    .where(table.c.company_id == args.company, table.c.purchase_number.in_(numbers))
                )
            )
        observation_id = None
        if args.queue is not None:
            queue = GosplanQueue(args.queue)
            try:
                observation_id = queue.record(scope, page, observed_at)
            finally:
                queue.close()
        result = {
            "company_id": args.company,
            "law": args.law,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "offset": args.offset,
            "limit": args.limit,
            "response_sha256": page.response_sha256,
            "may_have_more": page.may_have_more,
            "coverage": "UNKNOWN",
            "source_status": "HINT_ONLY",
            "observation_id": observation_id,
            "candidates": [
                {**asdict(c), "observed_at": c.observed_at.isoformat(), "status": status}
                for c, status in classify(page, present)
            ],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (
        GosplanError,
        QueueError,
        ValueError,
        KeyError,
        SQLAlchemyError,
        OSError,
        sqlite3.Error,
    ) as exc:
        # Never log response bodies, request headers or exception chains.
        print(
            json.dumps(
                {
                    "status": "UNKNOWN",
                    "reason": str(exc)
                    if isinstance(exc, GosplanError)
                    else "CONFIG_OR_SCOPE_INVALID",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
