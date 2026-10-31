"""Frozen regional waves, journal-backed fairness and honest read-only coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Date, DateTime, and_, cast, exists, func, insert, or_, select, union_all
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.sql.selectable import CTE, Subquery

from procurement.eis_joint_budget import NATIONAL_RECOVERY_START
from procurement.sources.eis_223_archive import SUPPORTED_DOCUMENT_TYPES
from procurement.sources.eis_223_regions import (
    REGION_SELECTOR_URL,
    inspect_region_catalog,
    validate_region_code,
)
from procurement.sources.eis_223_sync import Eis223RefreshTarget
from procurement.storage.eis_223_sync import (
    MSK,
    Eis223EventRefreshTarget,
    RefreshTarget,
    _aware,
    refresh_window_key,
)
from procurement.storage.models import (
    audit_events,
    eis_223_event_sync_attempts,
    eis_223_lot_event_sync_attempts,
    eis_223_sync_attempts,
)
from procurement.storage.models import (
    eis_223_region_catalog_checks as catalog_checks,
)
from procurement.storage.models import (
    eis_223_region_catalogs as catalogs,
)
from procurement.storage.models import (
    eis_223_region_targets as targets,
)
from procurement.storage.models import (
    eis_223_region_waves as waves,
)

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

TERMINAL = ("SYNCED", "NO_DATA")
FAMILIES = (*SUPPORTED_DOCUMENT_TYPES, "purchaseRejection", "purchaseLotCancellation")
LEGACY_FAMILY_SCOPES = (
    tuple(f for f in FAMILIES if f != "purchaseNoticeZPESMBO"),
    tuple(f for f in FAMILIES if f not in ("purchaseNoticeKESMBO", "purchaseNoticeZPESMBO")),
)
MAX_WAVE_TARGETS = 99 * 2 * len(FAMILIES)


class Eis223RegionalCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    company_id: str
    checked_at: datetime
    catalog_sha256: str | None = None
    catalog_observed_at: datetime | None = None
    catalog_source_url: str | None = None
    catalog_scope: Literal["UNKNOWN", "PUBLIC_KLADR_SELECTOR", "NSI_SUBJECT_RF"] = "UNKNOWN"
    catalog_regions: int = 0
    catalog_last_success_at: datetime | None = None
    latest_catalog_sha256: str | None = None
    latest_catalog_checked_at: datetime | None = None
    catalog_check_status: Literal["ACCEPTED", "FAILED", "REVIEW_REQUIRED"] | None = None
    catalog_check_reason: str | None = None
    wave_id: str | None = None
    start_day: date | None = None
    end_day: date | None = None
    planned: int = 0
    attempted: int = 0
    synced: int = 0
    no_data: int = 0
    failed: int = 0
    unattempted: int = 0
    due: int = 0
    cooling: int = 0
    regions_attempted: int = 0
    regions_terminal: int = 0
    old_gaps: int = 0
    oldest_gap_day: date | None = None
    observation_watermark: datetime | None = None
    source_day_lag: int | None = None
    first_sweep_finished: bool = False
    scope_status: Literal["UNKNOWN", "PARTIAL", "COMPLETE"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"
    reason: str = "OFFICIAL_REGION_CATALOG_MISSING"


def _latest(company: str) -> CTE:
    combined = union_all(
        *(
            select(
                table.c.window_key, table.c.checked_at, table.c.status, table.c.attempt_id
            ).where(table.c.company_id == company)
            for table in (
                eis_223_sync_attempts,
                eis_223_event_sync_attempts,
                eis_223_lot_event_sync_attempts,
            )
        )
    ).subquery()
    return (
        select(combined)
        .distinct(combined.c.window_key)
        .order_by(
            combined.c.window_key,
            combined.c.checked_at.desc(),
            combined.c.status.not_in(TERMINAL).desc(),
            combined.c.attempt_id.desc(),
        )
        # Dispatch joins this history to many planned windows. Computing it once
        # avoids rescanning DISTINCT ON for each row of a nested-loop join.
        .cte("eis_223_latest_attempts")
        .prefix_with("MATERIALIZED")
    )


def _current(conn: Connection, company: str) -> RowMapping | None:
    # Prefer additive ZP, then KES scopes for equal calendar/created timestamps. UUID
    # order alone could keep the predecessor current and append forever.
    expanded = exists(
        select(targets.c.window_key).where(
            targets.c.company_id == waves.c.company_id,
            targets.c.wave_id == waves.c.wave_id,
            targets.c.window_key.like("%/purchaseNoticeKESMBO"),
        )
    ).correlate(waves)
    zp_expanded = exists(
        select(targets.c.window_key).where(
            targets.c.company_id == waves.c.company_id,
            targets.c.wave_id == waves.c.wave_id,
            targets.c.window_key.like("%/purchaseNoticeZPESMBO"),
        )
    ).correlate(waves)
    return (
        conn.execute(
            select(waves)
            .where(waves.c.company_id == company)
            .order_by(
                waves.c.end_day.desc(),
                zp_expanded.desc(),
                expanded.desc(),
                waves.c.created_at.desc(),
                waves.c.wave_id.desc(),
            )
            .limit(1)
        )
        .mappings()
        .first()
    )


def _audit(
    conn: Connection,
    company: str,
    actor: str,
    kind: str,
    identity: str,
    now: datetime,
    basis: dict[str, object],
) -> None:
    if not actor.strip():
        raise ValueError("ACTOR_REQUIRED")
    conn.execute(
        insert(audit_events).values(
            company_id=company,
            event_id=str(uuid4()),
            actor_id=actor,
            event_type=kind,
            object_type="EIS_223_REGIONAL_PLAN",
            object_id=identity,
            object_version=None,
            occurred_at=now,
            basis=basis,
        )
    )


def register_region_catalog(
    storage: PostgresStorage,
    company: str,
    content: bytes,
    *,
    source_url: str,
    response_sha256: str,
    observed_at: datetime,
    actor_id: str,
) -> str:
    """Derive membership from retained official bytes, never caller-supplied code lists."""
    catalog = inspect_region_catalog(
        content, source_url=source_url, response_sha256=response_sha256, observed_at=observed_at
    )
    with storage.transaction(company) as conn:
        # Serialize catalog/wave materialization; source dispatch uses the server lease.
        conn.scalar(
            select(func.pg_advisory_xact_lock(func.hashtextextended(company + "/223-regions", 0)))
        )
        exists = conn.scalar(
            select(catalogs.c.catalog_sha256).where(
                catalogs.c.company_id == company,
                catalogs.c.catalog_sha256 == catalog.catalog_sha256,
            )
        )
        if exists is not None:
            return catalog.catalog_sha256
        conn.execute(
            insert(catalogs).values(company_id=company, content=content, **catalog.model_dump())
        )
        _audit(
            conn,
            company,
            actor_id,
            "EIS_223_REGION_CATALOG_RETAINED",
            catalog.catalog_sha256,
            observed_at,
            {
                "catalog_sha256": catalog.catalog_sha256,
                "response_sha256": response_sha256,
                "regions": len(catalog.regions),
                "coverage": "UNKNOWN",
            },
        )
    return catalog.catalog_sha256


def _accepted_catalog(conn: Connection, company: str) -> RowMapping | None:
    latest = (
        select(catalog_checks.c.catalog_sha256, catalog_checks.c.checked_at)
        .where(catalog_checks.c.company_id == company, catalog_checks.c.status == "ACCEPTED")
        .order_by(catalog_checks.c.checked_at.desc(), catalog_checks.c.attempt_id.desc())
        .limit(1)
        .subquery()
    )
    accepted = (
        conn.execute(
            select(catalogs, latest.c.checked_at.label("last_checked_at"))
            .join(latest, catalogs.c.catalog_sha256 == latest.c.catalog_sha256)
            .where(catalogs.c.company_id == company)
        )
        .mappings()
        .first()
    )
    if accepted is not None:
        return accepted
    return (
        conn.execute(
            select(catalogs, catalogs.c.observed_at.label("last_checked_at"))
            .where(catalogs.c.company_id == company)
            .order_by(catalogs.c.observed_at.desc(), catalogs.c.catalog_sha256)
            .limit(1)
        )
        .mappings()
        .first()
    )


def _create_wave(
    conn: Connection,
    company: str,
    now: datetime,
    actor: str,
    catalog_sha256: str,
    start_day: date,
    end_day: date,
    keys: tuple[str, ...],
    *,
    transition: dict[str, object] | None = None,
) -> str:
    identity = str(uuid4())
    conn.execute(
        insert(waves).values(
            company_id=company,
            wave_id=identity,
            catalog_sha256=catalog_sha256,
            start_day=start_day,
            end_day=end_day,
            target_count=len(keys),
            created_at=now,
        )
    )
    conn.execute(
        insert(targets),
        [
            dict(company_id=company, wave_id=identity, window_key=key, ordinal=index)
            for index, key in enumerate(keys)
        ],
    )
    _audit(
        conn,
        company,
        actor,
        "EIS_223_REGIONAL_WAVE_CREATED",
        identity,
        now,
        {
            "catalog_sha256": catalog_sha256,
            "target_count": len(keys),
            "start_day": start_day.isoformat(),
            "end_day": end_day.isoformat(),
            "coverage": "UNKNOWN",
            **(transition or {}),
        },
    )
    return identity


def _expand_family_scope(
    conn: Connection,
    company: str,
    current: RowMapping,
    catalog: RowMapping,
    now: datetime,
    actor: str,
) -> str | None:
    """Append only recognized complete five/six-to-seven family transitions."""
    regions = conn.scalar(
        select(catalogs.c.regions).where(
            catalogs.c.company_id == company,
            catalogs.c.catalog_sha256 == current["catalog_sha256"],
        )
    )
    if not regions or not 1 <= current["target_count"] <= MAX_WAVE_TARGETS:
        raise ValueError("REGIONAL_FAMILY_SCOPE_UNVERIFIED")
    desired = tuple(
        refresh_window_key(t)
        for t in plan_targets(tuple(sorted(regions)), current["start_day"], current["end_day"])
    )
    actual = tuple(
        conn.scalars(
            select(targets.c.window_key)
            .where(
                targets.c.company_id == company,
                targets.c.wave_id == current["wave_id"],
            )
            .order_by(targets.c.ordinal)
            .limit(MAX_WAVE_TARGETS + 1)
        )
    )
    if len(actual) != current["target_count"] or len(set(actual)) != len(actual):
        raise ValueError("REGIONAL_FAMILY_SCOPE_UNVERIFIED")
    if set(actual) == set(desired):
        return None
    previous_families = next(
        (
            families
            for families in LEGACY_FAMILY_SCOPES
            if set(actual) == {k for k in desired if k.rsplit("/", 1)[1] in families}
        ),
        None,
    )
    if previous_families is None or current["catalog_sha256"] != catalog["catalog_sha256"]:
        raise ValueError("REGIONAL_FAMILY_SCOPE_UNVERIFIED")

    def digest(keys: tuple[str, ...]) -> str:
        return hashlib.sha256(json.dumps(sorted(keys), separators=(",", ":")).encode()).hexdigest()

    return _create_wave(
        conn,
        company,
        now,
        actor,
        current["catalog_sha256"],
        current["start_day"],
        current["end_day"],
        desired,
        transition={
            "change": "REGULAR_ZPESMBO_FAMILY_EXPANSION",
            "predecessor_wave_id": current["wave_id"],
            "previous_families": list(previous_families),
            "families": list(FAMILIES),
            "previous_target_count": len(actual),
            "previous_scope_sha256": digest(actual),
            "scope_sha256": digest(desired),
        },
    )


def ensure_region_wave(
    storage: PostgresStorage,
    company: str,
    now: datetime,
    *,
    actor_id: str,
    fresh_first: bool = False,
) -> str | None:
    """Advance after a complete first sweep; retain failed gaps and frozen old dates.

    Catch-up waves move at most two source days, so a slow sweep does not skip days.
    A new catalog is applied atomically on the next wave, never rewrites past targets.
    """
    _aware(now)
    today = now.astimezone(MSK).date()
    with storage.transaction(company) as conn:
        conn.scalar(
            select(func.pg_advisory_xact_lock(func.hashtextextended(company + "/223-regions", 0)))
        )
        catalog = _accepted_catalog(conn, company)
        if catalog is None:
            return None
        current = _current(conn, company)
        if current is not None:
            expanded = _expand_family_scope(conn, company, current, catalog, now, actor_id)
            if expanded is not None:
                return expanded
        end_day = today
        if current and fresh_first:
            if current["end_day"] >= today:
                intervals = conn.execute(
                    select(waves.c.start_day, waves.c.end_day).where(waves.c.company_id == company)
                ).all()
                covered = {day for start, end in intervals for day in (start, end)}
                cursor = min(covered)
                while cursor <= today and cursor in covered:
                    cursor += timedelta(days=1)
                if cursor > today:
                    return str(current["wave_id"])
                # Materialize one retained catch-up pair per call. The latest
                # calendar wave stays current by end_day, not creation time.
                end_day = min(today, cursor + timedelta(days=1))
        elif current:
            latest = _latest(company)
            unattempted = conn.scalar(
                select(func.count())
                .select_from(targets.outerjoin(latest, targets.c.window_key == latest.c.window_key))
                .where(
                    targets.c.company_id == company,
                    targets.c.wave_id == current["wave_id"],
                    latest.c.checked_at.is_(None),
                )
            )
            if unattempted or current["end_day"] >= today:
                return str(current["wave_id"])
            end_day = min(today, current["end_day"] + timedelta(days=2))
        start_day = end_day - timedelta(days=1)
        keys = tuple(
            refresh_window_key(target)
            for target in plan_targets(tuple(sorted(catalog["regions"])), start_day, end_day)
        )
        return _create_wave(
            conn, company, now, actor_id, catalog["catalog_sha256"], start_day, end_day, keys
        )


def plan_targets(
    regions: tuple[str, ...], start_day: date, end_day: date
) -> tuple[RefreshTarget, ...]:
    if (
        not 1 <= len(regions) <= 99
        or len(set(regions)) != len(regions)
        or end_day - start_day != timedelta(days=1)
    ):
        raise ValueError("REGIONAL_PLAN_INVALID")
    for region in regions:
        validate_region_code(region)
    # Adjacent current/previous dates avoid waiting a country-wide empty day
    # sweep before importing yesterday's fresh notices.
    return tuple(
        target_from_key(f"getDocsIP/RI223/{region}/{day.isoformat()}+03:00/{family}")
        for family in FAMILIES
        for region in regions
        for day in (end_day, start_day)
    )


def target_from_key(key: str) -> RefreshTarget:
    pieces = key.split("/")
    if len(pieces) != 5 or pieces[:2] != ["getDocsIP", "RI223"] or not pieces[3].endswith("+03:00"):
        raise ValueError("REGIONAL_TARGET_INVALID")
    region = validate_region_code(pieces[2])
    day = date.fromisoformat(pieces[3][:-6])
    family = pieces[4]
    if family == "purchaseRejection":
        return Eis223EventRefreshTarget(day, "purchaseRejection", region)
    if family == "purchaseLotCancellation":
        return Eis223EventRefreshTarget(day, "purchaseLotCancellation", region)
    if family not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError("REGIONAL_TARGET_INVALID")
    return Eis223RefreshTarget(day, family, region)


def _scope(company: str) -> Subquery:
    return (
        select(
            targets.c.window_key,
            func.min(waves.c.created_at).label("planned_at"),
            func.min(targets.c.ordinal).label("ordinal"),
        )
        .select_from(
            targets.join(
                waves,
                and_(
                    targets.c.company_id == waves.c.company_id, targets.c.wave_id == waves.c.wave_id
                ),
            )
        )
        .where(targets.c.company_id == company)
        .group_by(targets.c.window_key)
        .subquery()
    )


def regional_due_windows(
    storage: PostgresStorage,
    company: str,
    now: datetime,
    *,
    limit: int = 32,
    fresh_first: bool = False,
    fresh_only: bool = False,
    recovery_only: bool = False,
    reconciliation_only: bool = False,
) -> tuple[RefreshTarget, ...]:
    _aware(now)
    if not 2 <= limit <= 32:
        raise ValueError("REGIONAL_BATCH_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        current = _current(conn, company)
        if current is None:
            return ()
        latest, scope = _latest(company), _scope(company)
        # Materialize the complete join before applying date/family filters. Those
        # expressions otherwise underestimate the queue and cause repeated scans
        # of the materialized history in a nested-loop left join.
        dispatch = (
            select(
                scope.c.window_key,
                scope.c.planned_at,
                scope.c.ordinal,
                latest.c.checked_at,
                latest.c.status,
            )
            .select_from(scope.outerjoin(latest, scope.c.window_key == latest.c.window_key))
            .cte("eis_223_region_dispatch")
            .prefix_with("MATERIALIZED")
        )
        active_keys = select(targets.c.window_key).where(
            targets.c.company_id == company, targets.c.wave_id == current["wave_id"]
        )
        failed_due = and_(
            dispatch.c.status.not_in(TERMINAL), dispatch.c.checked_at <= now - timedelta(hours=1)
        )
        fresh_due = and_(
            dispatch.c.window_key.in_(active_keys),
            dispatch.c.status.in_(TERMINAL),
            dispatch.c.checked_at <= now - timedelta(hours=6),
        )
        if fresh_first:
            source_day = cast(func.left(func.split_part(dispatch.c.window_key, "/", 4), 10), Date)
            final_cutoff = (
                func.timezone("UTC", cast(source_day, DateTime(timezone=False)))
                + timedelta(days=1, hours=2, minutes=5)
                - timedelta(hours=3)
            )
            fresh_due = and_(
                dispatch.c.status.in_(TERMINAL),
                or_(
                    and_(
                        source_day == now.astimezone(MSK).date(),
                        dispatch.c.checked_at <= now - timedelta(hours=6),
                    ),
                    and_(
                        source_day == now.astimezone(MSK).date() - timedelta(days=1),
                        dispatch.c.checked_at <= now - timedelta(hours=24),
                    ),
                    and_(dispatch.c.checked_at < final_cutoff, final_cutoff <= now),
                ),
            )
        statement = select(dispatch.c.window_key)
        if reconciliation_only:
            if not fresh_first or fresh_only or recovery_only:
                raise ValueError("RECONCILIATION_REQUIRES_FRESH_FIRST")
            catalog = _accepted_catalog(conn, company)
            if catalog is None:
                raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
            statement = statement.where(
                source_day >= now.astimezone(MSK).date() - timedelta(days=3),
                source_day < now.astimezone(MSK).date(),
                func.split_part(dispatch.c.window_key, "/", 3).in_(catalog["regions"]),
                func.split_part(dispatch.c.window_key, "/", 5).in_(FAMILIES),
            )
        if recovery_only:
            if not fresh_first or fresh_only:
                raise ValueError("RECOVERY_REQUIRES_FRESH_FIRST")
            catalog = _accepted_catalog(conn, company)
            if catalog is None:
                raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
            statement = statement.where(
                source_day < now.astimezone(MSK).date() - timedelta(days=1),
                source_day >= NATIONAL_RECOVERY_START,
                func.split_part(dispatch.c.window_key, "/", 3).in_(catalog["regions"]),
                func.split_part(dispatch.c.window_key, "/", 5).in_(FAMILIES),
            )
        if fresh_only:
            if not fresh_first:
                raise ValueError("FRESH_ONLY_REQUIRES_FRESH_FIRST")
            statement = statement.where(
                source_day >= now.astimezone(MSK).date() - timedelta(days=1)
            )
        if fresh_first:
            # Newest unobserved dates before historical gaps or terminal rechecks.
            new = list(
                conn.scalars(
                    statement.where(
                        dispatch.c.checked_at.is_(None), dispatch.c.window_key.in_(active_keys)
                    )
                    .order_by(
                        func.split_part(dispatch.c.window_key, "/", 4).desc(), dispatch.c.ordinal
                    )
                    .limit(limit)
                )
            )
            # Keep a failed current coordinate progressing even while rechecks are due.
            retry = (
                list(
                    conn.scalars(
                        statement.where(failed_due)
                        .order_by(dispatch.c.checked_at, dispatch.c.ordinal)
                        .limit(1)
                    )
                )
                if fresh_only or recovery_only or reconciliation_only
                else []
            )
            if retry:
                new = new[: limit - 1]
            remaining = limit - len(new) - len(retry)
            # A bounded six-hour recheck covers late publication/amendments.
            repeated = (
                list(
                    conn.scalars(
                        statement.where(fresh_due)
                        .order_by(dispatch.c.checked_at, dispatch.c.ordinal)
                        .limit(
                            remaining
                            if fresh_only or recovery_only or reconciliation_only
                            else min(remaining, max(1, limit // 8))
                        )
                    )
                )
                if remaining
                else []
            )
            remaining -= len(repeated)
            recovery = (
                list(
                    conn.scalars(
                        statement.where(
                            or_(dispatch.c.checked_at.is_(None), failed_due),
                            dispatch.c.window_key.not_in(new + retry + repeated),
                        )
                        .order_by(
                            func.split_part(dispatch.c.window_key, "/", 4).desc(),
                            dispatch.c.ordinal,
                        )
                        .limit(remaining)
                    )
                )
                if remaining
                else []
            )
            return tuple(target_from_key(k) for k in retry + new + repeated + recovery)
        unseen = list(
            conn.scalars(
                statement.where(dispatch.c.checked_at.is_(None))
                .order_by(dispatch.c.planned_at, dispatch.c.ordinal, dispatch.c.window_key)
                .limit(limit)
            )
        )
        # One retry slot per batch keeps old failures progressing without starving new regions.
        retries = list(
            conn.scalars(
                statement.where(failed_due)
                .order_by(dispatch.c.checked_at, dispatch.c.planned_at, dispatch.c.ordinal)
                .limit(limit)
            )
        )
        fresh = list(
            conn.scalars(
                statement.where(fresh_due)
                .order_by(dispatch.c.checked_at, dispatch.c.ordinal)
                .limit(limit)
            )
        )
        # Reserve each useful lane early so a partial run cannot starve it.
        keys = (fresh[:1] if limit >= 3 else []) + retries[:1]
        keys += unseen[: limit - len(keys)]
        if len(keys) < limit:
            keys += [key for key in retries if key not in keys][: limit - len(keys)]
        if len(keys) < limit:
            keys += [key for key in fresh if key not in keys][: limit - len(keys)]
    return tuple(target_from_key(key) for key in keys)


def read_region_coverage(
    storage: PostgresStorage, company: str, *, now: datetime
) -> Eis223RegionalCoverage:
    _aware(now)
    with storage.transaction(company, consistent_read=True) as conn:
        current = _current(conn, company)
        if current is None:
            return Eis223RegionalCoverage(company_id=company, checked_at=now)
        catalog = (
            conn.execute(
                select(catalogs.c.observed_at, catalogs.c.regions, catalogs.c.source_url).where(
                    catalogs.c.company_id == company,
                    catalogs.c.catalog_sha256 == current["catalog_sha256"],
                )
            )
            .mappings()
            .one()
        )
        catalog_observation = (
            conn.execute(
                select(catalog_checks.c.status, catalog_checks.c.reason)
                .where(catalog_checks.c.company_id == company)
                .order_by(
                    catalog_checks.c.checked_at.desc(),
                    (catalog_checks.c.status != "ACCEPTED").desc(),
                    catalog_checks.c.attempt_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        wave_success = conn.scalar(
            select(func.max(catalog_checks.c.checked_at)).where(
                catalog_checks.c.company_id == company,
                catalog_checks.c.catalog_sha256 == current["catalog_sha256"],
                catalog_checks.c.status == "ACCEPTED",
            )
        )
        latest_catalog = _accepted_catalog(conn, company)
        catalog_state = {
            "catalog_last_success_at": wave_success or catalog["observed_at"],
            "latest_catalog_sha256": latest_catalog["catalog_sha256"] if latest_catalog else None,
            "latest_catalog_checked_at": latest_catalog["last_checked_at"]
            if latest_catalog
            else None,
            "catalog_check_status": catalog_observation["status"] if catalog_observation else None,
            "catalog_check_reason": catalog_observation["reason"] if catalog_observation else None,
        }
        latest = _latest(company)
        rows = (
            conn.execute(
                select(targets.c.window_key, latest.c.status, latest.c.checked_at)
                .select_from(targets.outerjoin(latest, targets.c.window_key == latest.c.window_key))
                .where(targets.c.company_id == company, targets.c.wave_id == current["wave_id"])
                .order_by(targets.c.ordinal)
                .limit(MAX_WAVE_TARGETS + 1)
            )
            .mappings()
            .all()
        )
        if len(rows) != current["target_count"] or len(rows) > MAX_WAVE_TARGETS:
            raise ValueError("REGIONAL_PLAN_INCOMPLETE")
        scope = _scope(company)
        old = conn.execute(
            select(func.count(), func.min(scope.c.window_key))
            .select_from(scope.outerjoin(latest, scope.c.window_key == latest.c.window_key))
            .where(
                scope.c.window_key.not_in([row["window_key"] for row in rows]),
                or_(latest.c.status.is_(None), latest.c.status.not_in(TERMINAL)),
            )
        ).one()
        old_day = None
        if old[0]:
            old_day_raw = conn.scalar(
                select(func.min(func.split_part(scope.c.window_key, "/", 4)))
                .select_from(scope.outerjoin(latest, scope.c.window_key == latest.c.window_key))
                .where(
                    scope.c.window_key.not_in([row["window_key"] for row in rows]),
                    or_(latest.c.status.is_(None), latest.c.status.not_in(TERMINAL)),
                )
            )
            old_day = date.fromisoformat(old_day_raw[:-6])
    return coverage_from_rows(
        company, now, current, catalog, rows, int(old[0]), old_day
    ).model_copy(update=catalog_state)


def coverage_from_rows(
    company: str,
    now: datetime,
    wave: RowMapping,
    catalog: RowMapping,
    rows: Sequence[RowMapping],
    old_gaps: int,
    old_day: date | None,
) -> Eis223RegionalCoverage:
    counts = {status: sum(row["status"] == status for row in rows) for status in TERMINAL}
    unattempted = sum(row["status"] is None for row in rows)
    failed = len(rows) - unattempted - sum(counts.values())
    due = sum(
        row["checked_at"] is None
        or now - row["checked_at"] >= timedelta(hours=6 if row["status"] in TERMINAL else 1)
        for row in rows
    )
    by_region: dict[str, list[RowMapping]] = {}
    for row in rows:
        by_region.setdefault(row["window_key"].split("/")[2], []).append(row)
    all_terminal = unattempted == failed == 0
    pending_days = [
        target_from_key(row["window_key"]).day for row in rows if row["status"] not in TERMINAL
    ]
    if old_day:
        pending_days.append(old_day)
    return Eis223RegionalCoverage(
        company_id=company,
        checked_at=now,
        catalog_sha256=wave["catalog_sha256"],
        catalog_observed_at=catalog["observed_at"],
        catalog_source_url=catalog["source_url"],
        catalog_scope="PUBLIC_KLADR_SELECTOR"
        if catalog["source_url"] == REGION_SELECTOR_URL
        else "NSI_SUBJECT_RF",
        catalog_regions=len(catalog["regions"]),
        wave_id=wave["wave_id"],
        start_day=wave["start_day"],
        end_day=wave["end_day"],
        planned=len(rows),
        attempted=len(rows) - unattempted,
        synced=counts["SYNCED"],
        no_data=counts["NO_DATA"],
        failed=failed,
        unattempted=unattempted,
        due=due,
        cooling=len(rows) - due,
        regions_attempted=sum(
            any(r["status"] is not None for r in group) for group in by_region.values()
        ),
        regions_terminal=sum(
            all(r["status"] in TERMINAL for r in group) for group in by_region.values()
        ),
        old_gaps=old_gaps,
        oldest_gap_day=min(pending_days) if pending_days else None,
        observation_watermark=min(row["checked_at"] for row in rows) if all_terminal else None,
        source_day_lag=max(0, (now.astimezone(MSK).date() - wave["end_day"]).days),
        first_sweep_finished=unattempted == 0,
        scope_status="COMPLETE" if all_terminal else "PARTIAL",
        reason="EXACT_PLANNED_SCOPE_ONLY",
    )
