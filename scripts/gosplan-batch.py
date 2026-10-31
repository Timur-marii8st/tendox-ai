"""Collect a bounded batch of provider hints into a protected local queue."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import httpx

from procurement.sources.gosplan_pagination import collect_batch
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--law", choices=("44", "223"), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=3)
    args = parser.parse_args()
    try:
        scope = Scope(
            args.company,
            args.law,
            datetime.fromisoformat(args.start),
            datetime.fromisoformat(args.end),
            args.offset,
            args.limit,
        )
        key = os.environ["GOSPLAN_API_KEY"]
        queue = GosplanQueue(args.queue)
        try:
            with httpx.Client(timeout=25, trust_env=True) as client:
                result = collect_batch(client, key, queue, scope, max_pages=args.max_pages)
        finally:
            queue.close()
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 0 if result.status == "STOPPED" else 1
    except (ValueError, KeyError, QueueError, sqlite3.Error, OSError):
        print(json.dumps({"status": "UNKNOWN", "reason": "CONFIG_OR_STORE_INVALID"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
