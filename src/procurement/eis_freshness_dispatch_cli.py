"""Tenant read probe: idle freshness must not request a backfill handoff."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine

from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_freshness import EisFreshnessScope, read_due_freshness
from procurement.storage.eis_freshness_requests import pending_refresh_targets
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.repository import PostgresStorage

if TYPE_CHECKING:
    from collections.abc import Sequence


class FreshnessDispatchProbe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["READY", "IDLE", "BLOCKED"]
    company_id: str
    regions: tuple[str, ...]
    document_types: tuple[str, ...]
    checked_at: datetime
    baseline_due: int = Field(default=0, ge=0, le=24)
    foreground_due: int = Field(default=0, ge=0)
    reason: str | None = None
    attempted: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"


def probe_dispatch(
    storage: PostgresStorage,
    company: str,
    scope: EisFreshnessScope,
    *,
    now: datetime | None = None,
) -> FreshnessDispatchProbe:
    now = now or datetime.now(UTC)
    scope.targets(now)
    journal = EisSyncJournal(storage, company, "server-freshness-probe")
    basis = dict(
        company_id=company,
        regions=scope.regions,
        document_types=scope.document_types,
        checked_at=now,
    )
    reason = resource_gate(
        storage, company, max_database_bytes=100 * 1024**3, min_free_bytes=40 * 1024**3
    )
    if reason:
        return FreshnessDispatchProbe(status="BLOCKED", reason=reason, **basis)
    baseline = read_due_freshness(journal, scope, now=now, limit=24)
    foreground = pending_refresh_targets(journal, now=now, plan=False)
    return FreshnessDispatchProbe(
        status="READY" if baseline or foreground else "IDLE",
        baseline_due=len(baseline),
        foreground_due=len(foreground),
        **basis,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--regions", required=True)
    args = parser.parse_args(argv)
    engine = None
    scope = EisFreshnessScope(tuple(args.regions.split(",")))
    try:
        engine = create_engine(os.environ["DATABASE_URL"])
        report = probe_dispatch(PostgresStorage(engine), args.company_id, scope)
        print(report.model_dump_json())
        return 2 if report.status == "BLOCKED" else 0
    except Exception:
        print(
            FreshnessDispatchProbe(
                status="BLOCKED",
                company_id=args.company_id,
                regions=scope.regions,
                document_types=scope.document_types,
                reason="FRESHNESS_PROBE_UNAVAILABLE",
                checked_at=datetime.now(UTC),
            ).model_dump_json()
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
