"""Bounded live reconciliation proof; run under the shared server import lock."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, select

from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_feed_sync import sync_eis_window_via_browser
from procurement.sources.eis_freshness import EisFreshnessScope
from procurement.storage.eis_notice_index import has_ingested_window
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import eis_feed_archives, eis_feed_windows, eis_sync_attempts
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
ACTOR = "server-freshness-smoke"


def snapshots(storage: PostgresStorage, key: str) -> list[dict[str, object]]:
    with storage.transaction(COMPANY) as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(eis_feed_windows)
                .where(
                    eis_feed_windows.c.company_id == COMPANY,
                    eis_feed_windows.c.window_key == key,
                )
                .order_by(eis_feed_windows.c.ingested_at)
            ).mappings()
        ]


async def main() -> int:
    now = datetime.now(UTC)
    root = (
        Path("/var/lib/eis-browser/research/freshness") / COMPANY / now.strftime("%Y%m%dT%H%M%S%fZ")
    )
    root.mkdir(parents=True, exist_ok=False)
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        storage = PostgresStorage(engine)
        journal = EisSyncJournal(storage, COMPANY, ACTOR)
        stopped = resource_gate(
            storage, COMPANY, max_database_bytes=100 * 1024**3, min_free_bytes=40 * 1024**3
        )
        if stopped:
            print(json.dumps({"status": "BLOCKED", "reason": stopped}))
            return 2
        scope = EisFreshnessScope(("50", "77"), ("epNotificationEF2020",))
        selection = next(
            (
                target.selection
                for target in scope.targets(now)
                if target.lane == "RECONCILE_DAY"
                and has_ingested_window(storage, COMPANY, target.selection.window_key)
            ),
            None,
        )
        if selection is None:
            print(json.dumps({"status": "BLOCKED", "reason": "NO_COMPLETED_CHECKPOINT"}))
            return 2
        key = selection.window_key
        journal.plan((selection,))
        before = snapshots(storage, key)
        result = await sync_eis_window_via_browser(
            storage, COMPANY, ACTOR, selection, os.environ["EIS_GETDOCS_IP_TOKEN"], refresh=True
        )
        journal.record(key, result.status, source_response_sha256=result.source_response_sha256)
        after = snapshots(storage, key)
        with storage.transaction(COMPANY) as connection:
            attempts = [
                dict(row)
                for row in connection.execute(
                    select(eis_sync_attempts)
                    .where(
                        eis_sync_attempts.c.company_id == COMPANY,
                        eis_sync_attempts.c.actor_id.in_([ACTOR, "server-freshness-worker"]),
                    )
                    .order_by(eis_sync_attempts.c.attempted_at.desc())
                    .limit(30)
                ).mappings()
            ]
            archive_bytes = connection.scalar(
                select(func.sum(func.octet_length(eis_feed_archives.c.content))).where(
                    eis_feed_archives.c.company_id == COMPANY,
                    eis_feed_archives.c.window_key == key,
                )
            )
        proof = {
            "schema": "s135-live-v1",
            "company_id": COMPANY,
            "started_at": now,
            "finished_at": datetime.now(UTC),
            "source_scope": asdict(scope),
            "result": asdict(result),
            "before": before,
            "after": after,
            "prior_snapshots_preserved": all(row in after for row in before),
            "archive_bytes_for_key": archive_bytes,
            "attempts": attempts,
            "code_sha256": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [
                    Path(__file__),
                    Path("src/procurement/sources/eis_freshness.py"),
                    Path("src/procurement/sources/eis_feed_sync.py"),
                ]
            },
            "coverage": "UNKNOWN",
            "freshness": "UNKNOWN",
        }
        content = json.dumps(proof, default=str, ensure_ascii=False, indent=2).encode()
        report = root / "reconcile.json"
        report.write_bytes(content)
        print(
            json.dumps(
                {
                    "report": str(report),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "result": asdict(result),
                    "prior_snapshots_preserved": proof["prior_snapshots_preserved"],
                },
                default=str,
            )
        )
        return 0 if result.status == "SYNCED" and proof["prior_snapshots_preserved"] else 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
