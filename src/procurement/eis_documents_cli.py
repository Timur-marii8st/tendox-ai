"""Bounded server document worker, configured through environment secrets."""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine

from procurement.sources.eis_document_worker import run_document_step
from procurement.storage.repository import PostgresStorage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--actor-id", default="server-document-worker")
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        result = run_document_step(PostgresStorage(engine), args.company_id, actor_id=args.actor_id)
        print(json.dumps(result, ensure_ascii=True))
        return 2 if result["status"] in {"BLOCKED", "PARTIAL"} else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
