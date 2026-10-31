"""Read-only history demand evidence; never grants an EIS source turn.

The results describe eligible work in persisted planned scope, not national coverage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text, union_all
from sqlalchemy.exc import SQLAlchemyError

from procurement.eis_freshness_dispatch_cli import probe_dispatch
from procurement.eis_history_demand import (
    HistoryDemandClassification,
    _reconciliation_days,
    classify_history_demand,
)
from procurement.sources.eis_223_regions import inspect_region_catalog
from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_freshness import EisFreshnessScope, read_due_reconciliation
from procurement.storage.eis_223_catalog_checks import catalog_refresh_due
from procurement.storage.eis_223_regions import (
    FAMILIES,
    MAX_WAVE_TARGETS,
    _accepted_catalog,
    _current,
    plan_targets,
    regional_due_windows,
)
from procurement.storage.eis_223_sync import refresh_window_key
from procurement.storage.eis_global_price import _SharedReadStorage
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import (
    eis_223_event_sync_attempts,
    eis_223_lot_event_sync_attempts,
    eis_223_sync_attempts,
    eis_sync_attempts,
)
from procurement.storage.models import eis_223_region_catalog_checks as checks
from procurement.storage.models import eis_223_region_targets as targets
from procurement.storage.repository import PostgresStorage


class HistoryReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    classification: HistoryDemandClassification
    snapshot: str | None = None
    catalog_check_id: str | None = None
    wave_id: str | None = None
    evidence_sha256: str | None = None
    evidence: dict[str, object] | None = None
    reconciliation_scope: Literal["PERSISTED_PLANNED_ONLY"] = "PERSISTED_PLANNED_ONLY"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    source_requests: Literal[0] = 0
    writes: Literal[0] = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _scope_digest(
    company: str,
    law: str,
    regions: tuple[str, ...],
    types: tuple[str, ...],
    catalog_sha: str,
    at: datetime,
) -> str:
    scope = dict(
        company_id=company,
        law=law,
        regions=regions,
        document_types=types,
        catalog_sha256=catalog_sha,
        query_at=at.astimezone(UTC).isoformat(),
        timezone="+03:00",
        days=[d.isoformat() for d in _reconciliation_days(law, at)],
        cutoff="completed-day-plus-02:05" if law == "44" else "recent-three-msk-days",
    )
    return hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _unresolved_attempts(
    conn,
    company: str,
    scope: EisFreshnessScope,
    now: datetime,
    *,
    quarantine_proofs: list[dict[str, object]] | None = None,
    snapshot: str | None = None,
) -> bool:
    """Never treat a cooling failed observation as a clear mandatory queue."""
    days44 = set(_reconciliation_days("44", now))
    keys44 = [
        item.selection.window_key
        for item in scope.targets(now)
        if item.lane == "RECENT_HOUR"
        or (item.lane == "RECONCILE_DAY" and item.selection.day in days44)
    ]
    latest44 = (
        conn.execute(
            select(eis_sync_attempts)
            .where(
                eis_sync_attempts.c.company_id == company,
                eis_sync_attempts.c.window_key.in_(keys44),
            )
            .distinct(eis_sync_attempts.c.window_key)
            .order_by(
                eis_sync_attempts.c.window_key,
                eis_sync_attempts.c.attempted_at.desc(),
                eis_sync_attempts.c.attempt_id.desc(),
            )
        )
        .mappings()
        .all()
    )
    for row in latest44:
        if (
            row["outcome"] in ("SYNCED", "NO_DATA")
            and row["source_response_sha256"]
            and row["attempted_at"] <= now
        ):
            continue
        if quarantine_proofs is None or len(quarantine_proofs) >= 2:
            return True
        from procurement.eis_quarantine_proof import verify_quarantined_conflict

        proof = verify_quarantined_conflict(conn, company, row["window_key"], row["attempt_id"])
        if proof.status != "VERIFIED" or proof.snapshot != snapshot:
            return True
        quarantine_proofs.append(proof.model_dump(mode="json"))
    days223 = set(_reconciliation_days("223", now))
    keys223 = {
        refresh_window_key(target)
        for day in days223
        for target in plan_targets(scope.regions, day - timedelta(days=1), day)
        if target.day in days223
    }
    combined = union_all(
        *(
            select(
                table.c.window_key,
                table.c.checked_at,
                table.c.status,
                table.c.response_sha256,
                table.c.attempt_id,
            ).where(table.c.company_id == company, table.c.window_key.in_(keys223))
            for table in (
                eis_223_sync_attempts,
                eis_223_event_sync_attempts,
                eis_223_lot_event_sync_attempts,
            )
        )
    ).subquery()
    latest223 = (
        conn.execute(
            select(combined)
            .distinct(combined.c.window_key)
            .order_by(
                combined.c.window_key,
                combined.c.checked_at.desc(),
                combined.c.status.not_in(("SYNCED", "NO_DATA")).desc(),
                combined.c.attempt_id.desc(),
            )
        )
        .mappings()
        .all()
    )
    return any(
        row["status"] not in ("SYNCED", "NO_DATA")
        or not row["response_sha256"]
        or row["checked_at"] > now
        for row in latest223
    )


def _blocked(reason: str) -> HistoryReadResult:
    return HistoryReadResult(
        classification=HistoryDemandClassification(status="BLOCKED", reason=reason)
    )


def read_history_demand(
    storage: PostgresStorage, company: str, *, verify_quarantine: bool = False
) -> HistoryReadResult:
    """Collect existing read-only producers within a single tenant-bound DB snapshot."""
    started = _utcnow()
    try:
        with storage.transaction(company, consistent_read=True) as conn:
            conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            conn.execute(text("SET LOCAL lock_timeout = '2000ms'"))
            if conn.scalar(text("SHOW transaction_isolation")) != "repeatable read":
                return _blocked("SNAPSHOT_ISOLATION_INVALID")
            if conn.scalar(text("SHOW transaction_read_only")) != "on":
                return _blocked("SNAPSHOT_NOT_READ_ONLY")
            snapshot = conn.scalar(text("SELECT txid_current_snapshot()::text"))
            if not snapshot:
                return _blocked("SNAPSHOT_UNAVAILABLE")
            shared = _SharedReadStorage(company, conn)
            catalog = _accepted_catalog(conn, company)
            if catalog is None:
                return _blocked("CATALOG_UNAVAILABLE")
            check = (
                conn.execute(
                    select(checks)
                    .where(
                        checks.c.company_id == company,
                        checks.c.status == "ACCEPTED",
                        checks.c.catalog_sha256 == catalog["catalog_sha256"],
                    )
                    .order_by(checks.c.checked_at.desc(), checks.c.attempt_id.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if check is None:
                return _blocked("CATALOG_ACCEPTANCE_MISSING")
            if catalog["observed_at"] > started or check["checked_at"] > started:
                return _blocked("CATALOG_TIME_INVALID")
            parsed = inspect_region_catalog(
                catalog["content"],
                source_url=catalog["source_url"],
                response_sha256=catalog["response_sha256"],
                observed_at=catalog["observed_at"],
            )
            if (
                parsed.catalog_sha256 != catalog["catalog_sha256"]
                or parsed.regions != catalog["regions"]
            ):
                return _blocked("CATALOG_PROVENANCE_INVALID")
            regions = tuple(sorted(parsed.regions))
            types44, types223 = tuple(sorted(SUPPORTED_NOTICE_TYPES)), tuple(sorted(FAMILIES))
            wave = _current(conn, company)
            if wave is None:
                return _blocked("CURRENT_REGIONAL_WAVE_MISSING")
            if wave["catalog_sha256"] != catalog["catalog_sha256"]:
                return _blocked("CURRENT_REGIONAL_WAVE_CATALOG_MISMATCH")
            expected_keys = tuple(
                refresh_window_key(target)
                for target in plan_targets(regions, wave["start_day"], wave["end_day"])
            )
            actual_keys = tuple(
                conn.scalars(
                    select(targets.c.window_key)
                    .where(targets.c.company_id == company, targets.c.wave_id == wave["wave_id"])
                    .order_by(targets.c.ordinal)
                    .limit(MAX_WAVE_TARGETS + 1)
                )
            )
            if (
                len(actual_keys) != wave["target_count"]
                or len(actual_keys) != len(expected_keys)
                or len(set(actual_keys)) != len(actual_keys)
                or set(actual_keys) != set(expected_keys)
            ):
                return _blocked("CURRENT_REGIONAL_WAVE_INCOMPLETE")
            if wave["created_at"] > started:
                return _blocked("CURRENT_REGIONAL_WAVE_TIME_INVALID")
            scope = EisFreshnessScope(regions, types44, checkpointed=True, mandatory_only=True)
            quarantine_proofs: list[dict[str, object]] = []
            if _unresolved_attempts(
                conn,
                company,
                scope,
                started,
                quarantine_proofs=quarantine_proofs if verify_quarantine else None,
                snapshot=snapshot,
            ):
                return _blocked("MANDATORY_ATTEMPT_UNRESOLVED")
            journal = EisSyncJournal(shared, company, "history-demand-read")
            probe = probe_dispatch(shared, company, scope, now=started, include_regional=True)
            if probe.status == "BLOCKED" or probe.reason is not None:
                return _blocked("FRESHNESS_DEFERRED_OR_BLOCKED")
            daily44 = read_due_reconciliation(journal, scope, now=started, limit=2)
            daily223 = regional_due_windows(
                shared, company, started, limit=2, fresh_first=True, reconciliation_only=True
            )
            refresh_due = catalog_refresh_due(shared, company, started)
            ended = _utcnow()
            catalog_id = check["attempt_id"]
            observation = dict(
                company_id=company,
                regions=regions,
                document_types=types44,
                read_started_at=started,
                checked_at=ended,
                catalog_sha256=catalog["catalog_sha256"],
                catalog_observation_id=catalog_id,
                catalog_usable=True,
                catalog_refresh_due=refresh_due,
                checkpointed=True,
                mandatory_only=True,
                include_regional=True,
                regional_scope_complete=True,
                regional_document_types=types223,
                probe=probe.model_dump(),
            )
            for law, due in (("44", daily44), ("223", daily223)):
                keys = (
                    tuple(t.selection.window_key for t in due)
                    if law == "44"
                    else tuple(refresh_window_key(t) for t in due)
                )
                digest = _scope_digest(
                    company,
                    law,
                    regions,
                    types44 if law == "44" else types223,
                    catalog["catalog_sha256"],
                    started,
                )
                evidence = hashlib.sha256(
                    f"{snapshot}/{wave['wave_id']}/{law}/{digest}".encode()
                ).hexdigest()
                observation[f"reconciliation{law}"] = dict(
                    company_id=company,
                    law=law,
                    scope_sha256=digest,
                    catalog_sha256=catalog["catalog_sha256"],
                    evidence_id=evidence,
                    status="DUE" if keys else "CLEAR",
                    checked_at=started,
                    scope_complete=True,
                    coordinates=keys,
                )
            classified = classify_history_demand(
                observation,
                company_id=company,
                regions=regions,
                document_types=types44,
                regional_document_types=types223,
                expected_catalog_sha256=catalog["catalog_sha256"],
                expected_catalog_observation_id=catalog_id,
                now=ended,
            )
            if quarantine_proofs and classified.status == "IDLE":
                # Quarantined evidence is unresolved, never a clean mandatory queue.
                classified = classified.model_copy(update={"status": "READY"})
            evidence = dict(
                quarantines=quarantine_proofs,
                snapshot=snapshot,
                wave_id=wave["wave_id"],
                wave_catalog=wave["catalog_sha256"],
                wave_start=str(wave["start_day"]),
                wave_end=str(wave["end_day"]),
                wave_targets=list(actual_keys),
                company_id=company,
                catalog_sha256=catalog["catalog_sha256"],
                catalog_response_sha256=catalog["response_sha256"],
                observation=observation,
                check_id=catalog_id,
                classification=classified.model_dump(mode="json"),
            )
            return HistoryReadResult(
                classification=classified,
                snapshot=snapshot,
                catalog_check_id=catalog_id,
                wave_id=wave["wave_id"],
                evidence_sha256=hashlib.sha256(
                    json.dumps(
                        evidence, sort_keys=True, separators=(",", ":"), default=str
                    ).encode()
                ).hexdigest(),
                evidence=json.loads(json.dumps(evidence, default=str)),
            )
    except (SQLAlchemyError, ValueError, TypeError, OSError):
        return _blocked("READ_UNAVAILABLE")
