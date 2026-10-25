"""Tenant read probe: idle freshness must not request a backfill handoff."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_freshness import EisFreshnessScope, read_due_freshness
from procurement.storage.eis_223_regions import _accepted_catalog, _current, regional_due_windows
from procurement.storage.eis_223_sync import MSK
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
    urgent_due: int = Field(default=0, ge=0)
    foreground_due: int = Field(default=0, ge=0)
    regional_due: int = Field(default=0, ge=0)
    regional_new_wave_due: bool = False
    reason: str | None = None
    attempted: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"


def _regional_demand(storage: PostgresStorage, company: str, now: datetime) -> tuple[int, bool]:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        if _accepted_catalog(conn, company) is None:
            raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
        current = _current(conn, company)
    new_wave = current is None or current["end_day"] < now.astimezone(MSK).date()
    due = regional_due_windows(storage, company, now, limit=2, fresh_first=True, fresh_only=True)
    if not due:
        due = regional_due_windows(
            storage, company, now, limit=2, fresh_first=True, recovery_only=True
        )
    return len(due), new_wave


def urgent44_status(storage: PostgresStorage, company: str, now: datetime) -> str:
    """Cheap current-hour gate; retained outage debt is not old history."""
    try:
        with storage.transaction(company, consistent_read=True) as conn:
            conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            catalog = _accepted_catalog(conn, company)
        if catalog is None:
            return "BLOCKED"
        journal = EisSyncJournal(storage, company, "server-freshness-probe")
        due = read_due_freshness(
            journal,
            EisFreshnessScope(
                tuple(sorted(catalog["regions"])),
                checkpointed=True,
                mandatory_only=True,
                urgent_only=True,
            ),
            now=now,
            limit=1,
        )
        return "READY" if due else "IDLE"
    except (ValueError, SQLAlchemyError):
        return "BLOCKED"


def joint_mandatory_status(storage: PostgresStorage, company: str, now: datetime) -> str:
    """Read persisted demand under the existing shared lease; uncertainty blocks history."""
    try:
        with storage.transaction(company, consistent_read=True) as conn:
            conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            catalog = _accepted_catalog(conn, company)
        if catalog is None:
            return "BLOCKED"
        from procurement.storage.eis_223_catalog_checks import catalog_refresh_due

        if catalog_refresh_due(storage, company, now):
            return "READY"
        return probe_dispatch(
            storage,
            company,
            EisFreshnessScope(
                tuple(sorted(catalog["regions"])), checkpointed=True, mandatory_only=True
            ),
            now=now,
            include_regional=True,
        ).status
    except (ValueError, SQLAlchemyError):
        return "BLOCKED"


def probe_dispatch(
    storage: PostgresStorage,
    company: str,
    scope: EisFreshnessScope,
    *,
    now: datetime | None = None,
    include_regional: bool = False,
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
    deferred = journal.freshness_recovery_reason if scope.checkpointed else None
    regional, new_wave = 0, False
    if include_regional:
        try:
            regional, new_wave = _regional_demand(storage, company, now)
        except (ValueError, SQLAlchemyError):
            return FreshnessDispatchProbe(
                status="BLOCKED", reason="REGIONAL_DEMAND_UNAVAILABLE", **basis
            )
    return FreshnessDispatchProbe(
        status="READY"
        if baseline or foreground or regional or new_wave
        else "BLOCKED"
        if deferred
        else "IDLE",
        reason=deferred,
        baseline_due=len(baseline),
        urgent_due=(
            len(read_due_freshness(journal, replace(scope, urgent_only=True), now=now, limit=24))
            if scope.mandatory_only and scope.checkpointed
            else sum(getattr(t, "lane", None) == "RECENT_HOUR" for t in baseline)
        )
        + len(foreground),
        foreground_due=len(foreground),
        regional_due=regional,
        regional_new_wave_due=new_wave,
        **basis,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--regions", required=True)
    parser.add_argument("--checkpointed", action="store_true")
    parser.add_argument("--mandatory-only", action="store_true")
    parser.add_argument("--joint", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    scope = EisFreshnessScope(
        tuple(args.regions.split(",")),
        checkpointed=args.checkpointed,
        mandatory_only=args.mandatory_only,
    )
    try:
        engine = create_engine(os.environ["DATABASE_URL"])
        if args.regions == "official":
            storage = PostgresStorage(engine)
            with storage.transaction(args.company_id, consistent_read=True) as conn:
                catalog = _accepted_catalog(conn, args.company_id)
            if catalog is None:
                raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
            scope = EisFreshnessScope(
                tuple(sorted(catalog["regions"])),
                checkpointed=args.checkpointed,
                mandatory_only=args.mandatory_only,
            )
        report = probe_dispatch(
            PostgresStorage(engine), args.company_id, scope, include_regional=args.joint
        )
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
