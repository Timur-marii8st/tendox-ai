"""Bounded server reindex; no EIS network requests or credential output."""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine

from procurement.storage.eis_search_index import backfill_search_keys
from procurement.storage.repository import PostgresStorage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True)
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        added = backfill_search_keys(
            PostgresStorage(engine), args.company_id, actor_id="server-search-reindex"
        )
        print(json.dumps({"indexed_versions": added, "key_version": "eis-lexical-v1"}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
