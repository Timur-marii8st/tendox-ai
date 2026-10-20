"""Полный tenant census запланированных окон; samples не означают полный охват ЕИС."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Date, and_, case, cast, exists, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from procurement.storage.eis_sync_journal import _DATE_WINDOW, latest_eis_attempts
from procurement.storage.models import eis_feed_windows, eis_sync_targets
from procurement.storage.repository import PostgresStorage


class GapCategory(StrEnum):
    UNATTEMPTED = "UNATTEMPTED"
    NO_DATA = "NO_DATA"
    SOURCE_RETRY = "SOURCE_RETRY"
    PARSER_REVIEW = "PARSER_REVIEW"
    RESOURCE_REVIEW = "RESOURCE_REVIEW"
    VARIANT_REVIEW = "VARIANT_REVIEW"
    SOURCE_CONTRACT_REVIEW = "SOURCE_CONTRACT_REVIEW"
    UNKNOWN = "UNKNOWN"


def gap_category(outcome: str | None, reason: str | None) -> GapCategory:
    """Только точные коды; старый transient не перекрывает последнее NO_DATA/ошибку."""
    if outcome is None:
        return GapCategory.UNATTEMPTED
    if outcome == "NO_DATA":
        return GapCategory.NO_DATA
    if outcome in {"PREPARING", "SERVICE_ERROR"} or (
        outcome == "FAILED" and reason in {"SOURCE_TRANSPORT_FAILED", "SOURCE_WSDL_UNAVAILABLE"}
    ):
        return GapCategory.SOURCE_RETRY
    if outcome != "FAILED":
        return GapCategory.UNKNOWN
    if reason in {
        "ATTACHMENT_REFERENCE_INVALID",
        "ATTACHMENT_COUNT_LIMIT",
        "MEMBER_UNSUPPORTED",
        "CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED",
    }:
        return GapCategory.PARSER_REVIEW
    if reason in {
        "ARCHIVE_WINDOW_EXPANSION_LIMIT",
        "ARCHIVE_WINDOW_COUNT_LIMIT",
        "ARCHIVE_WINDOW_SIZE_LIMIT",
        "ATTACHMENT_METADATA_COUNT_LIMIT",
        "ARCHIVE_EXPANSION_LIMIT",
        "ARCHIVE_SIZE_LIMIT",
    }:
        return GapCategory.RESOURCE_REVIEW
    if reason in {
        "DUPLICATE_NOTICE_VERSION",
        "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
        "NOTICE_VERSION_CONFLICT",
        "TRANSPORT_WINDOW_NOT_CANONICAL",
        "DUPLICATE_PROCEDURE_EVENT",
        "DUPLICATE_PROCEDURE_EVENT_IN_WINDOW",
        "PROCEDURE_EVENT_CONFLICT",
        "WINDOW_REPLAY_CONFLICT",
    }:
        return GapCategory.VARIANT_REVIEW
    if reason in {
        "PREPARED_REQUEST_MISMATCH",
        "SOURCE_RESPONSE_REJECTED",
        "SOURCE_CONTRACT_CHANGED",
    }:
        return GapCategory.SOURCE_CONTRACT_REVIEW
    return GapCategory.UNKNOWN


class GapModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisGapReasonGroup(GapModel):
    category: GapCategory
    outcome: str | None = Field(max_length=40)
    reason_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    targets: int = Field(ge=1)
    oldest_source_day: date | None
    newest_source_day: date | None
    oldest_attempt_at: datetime | None
    newest_attempt_at: datetime | None


class EisGapSample(GapModel):
    window_key: str = Field(min_length=1, max_length=500)
    planned_at: datetime
    source_day: date | None
    outcome: str | None = Field(max_length=40)
    reason_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    attempted_at: datetime | None
    attempt_id: str | None
    source_response_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    historical_source_retry_due: bool


class EisGapStatus(GapModel):
    company_id: str = Field(min_length=1)
    checked_at: datetime
    scope: Literal["TENANT_PLANNED_QUEUE"] = "TENANT_PLANNED_QUEUE"
    status: Literal["OBSERVED", "UNKNOWN"]
    planned_targets: int = Field(ge=0)
    completed_targets: int = Field(ge=0)
    pending_targets: int = Field(ge=0)
    unattempted_targets: int = Field(ge=0)
    no_data_targets: int = Field(ge=0)
    historical_source_retry_due: int = Field(ge=0)
    transport_only_targets: int = Field(ge=0)
    invalid_source_coordinates: int = Field(ge=0)
    candidate_region_codes: int = Field(ge=0)
    oldest_source_day: date | None
    newest_source_day: date | None
    groups: tuple[EisGapReasonGroup, ...]
    samples: tuple[EisGapSample, ...]
    sample_limit: int = Field(ge=1, le=100)
    samples_truncated: bool
    evidence_tables: tuple[
        Literal["eis_sync_targets", "eis_sync_attempts", "eis_feed_windows"], ...
    ] = (
        "eis_sync_targets",
        "eis_sync_attempts",
        "eis_feed_windows",
    )
    source_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> EisGapStatus:
        times = [self.checked_at]
        times += [t for g in self.groups for t in (g.oldest_attempt_at, g.newest_attempt_at) if t]
        times += [t for s in self.samples for t in (s.planned_at, s.attempted_at) if t]
        if any(t.utcoffset() is None for t in times):
            raise ValueError("GAP_STATUS_TIMEZONE_MISSING")
        if (
            self.planned_targets != self.completed_targets + self.pending_targets
            or sum(g.targets for g in self.groups) != self.pending_targets
            or len(self.samples) != min(self.sample_limit, self.pending_targets)
            or self.samples_truncated != (self.pending_targets > self.sample_limit)
            or (self.invalid_source_coordinates > 0) != (self.status == "UNKNOWN")
            or self.unattempted_targets != sum(g.targets for g in self.groups if g.outcome is None)
            or self.no_data_targets != sum(g.targets for g in self.groups if g.outcome == "NO_DATA")
            or self.historical_source_retry_due > self.pending_targets
            or self.transport_only_targets > self.pending_targets
        ):
            raise ValueError("GAP_STATUS_COUNTS_INVALID")
        return self


def read_eis_gap_status(
    storage: PostgresStorage, company_id: str, *, now: datetime, sample_limit: int = 20
) -> EisGapStatus:
    """Один repeatable-read snapshot всей очереди, без источника и изменений БД."""
    from procurement.sources.eis_corpus import historical_source_retry_clause

    if not company_id.strip() or now.utcoffset() is None or not 1 <= sample_limit <= 100:
        raise ValueError("GAP_STATUS_REQUEST_INVALID")
    target = eis_sync_targets
    latest = latest_eis_attempts(company_id)
    complete = exists(
        select(eis_feed_windows.c.window_key).where(
            eis_feed_windows.c.company_id == company_id,
            eis_feed_windows.c.window_key == target.c.window_key,
            eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
        )
    )
    transport = exists(
        select(eis_feed_windows.c.window_key).where(
            eis_feed_windows.c.company_id == company_id,
            eis_feed_windows.c.window_key == target.c.window_key,
            eis_feed_windows.c.intake_kind == "VARIANT_TRANSPORT",
        )
    )
    raw_day = func.substring(target.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    valid = and_(
        target.c.window_key.op("~")(_DATE_WINDOW.pattern), func.pg_input_is_valid(raw_day, "date")
    )
    source_day = case((valid, cast(raw_day, Date)), else_=None)
    pending = (
        select(
            target.c.window_key,
            target.c.planned_at,
            source_day.label("source_day"),
            latest.c.outcome,
            latest.c.reason_code,
            latest.c.attempted_at,
            latest.c.attempt_id,
            latest.c.source_response_sha256,
            transport.label("transport_only"),
        )
        .select_from(
            target.outerjoin(
                latest,
                and_(latest.c.company_id == company_id, latest.c.window_key == target.c.window_key),
            )
        )
        .where(
            target.c.company_id == company_id,
            ~complete,
        )
        .cte("pending_eis_gap_targets")
        .prefix_with("MATERIALIZED")
    )
    retry_due = case(
        (pending.c.attempted_at.is_not(None), historical_source_retry_clause(pending, now)),
        else_=False,
    )
    grouped = (
        select(
            pending.c.outcome,
            pending.c.reason_code,
            func.count().label("targets"),
            func.min(pending.c.source_day).label("oldest_source_day"),
            func.max(pending.c.source_day).label("newest_source_day"),
            func.min(pending.c.attempted_at).label("oldest_attempt_at"),
            func.max(pending.c.attempted_at).label("newest_attempt_at"),
        )
        .group_by(pending.c.outcome, pending.c.reason_code)
        .cte("eis_gap_reason_groups")
    )
    sampled = (
        select(
            pending.c.window_key,
            pending.c.planned_at,
            pending.c.source_day,
            pending.c.outcome,
            pending.c.reason_code,
            pending.c.attempted_at,
            pending.c.attempt_id,
            pending.c.source_response_sha256,
            func.coalesce(retry_due, False).label("historical_source_retry_due"),
        )
        .order_by(
            func.coalesce(retry_due, False).desc(),
            pending.c.source_day.desc().nulls_last(),
            pending.c.window_key,
        )
        .limit(sample_limit)
        .cte("eis_gap_bounded_samples")
    )
    # One SQL shares the materialized full pending set across totals/groups/samples.
    # Separate statements would each rebuild it despite repeatable-read isolation.
    with storage.transaction(company_id, consistent_read=True) as conn:
        totals = (
            conn.execute(
                select(
                    select(func.count())
                    .select_from(target)
                    .where(target.c.company_id == company_id)
                    .scalar_subquery()
                    .label("planned"),
                    func.count().label("pending"),
                    func.min(pending.c.source_day).label("oldest"),
                    func.max(pending.c.source_day).label("newest"),
                    func.count().filter(pending.c.outcome.is_(None)).label("unattempted"),
                    func.count().filter(pending.c.outcome == "NO_DATA").label("no_data"),
                    func.count().filter(retry_due).label("retry_due"),
                    func.count().filter(pending.c.transport_only).label("transport_only"),
                    func.count().filter(pending.c.source_day.is_(None)).label("invalid"),
                    func.count(func.distinct(func.split_part(pending.c.window_key, "/", 3)))
                    .filter(pending.c.source_day.is_not(None))
                    .label("regions"),
                    select(func.jsonb_agg(func.to_jsonb(grouped.table_valued())))
                    .scalar_subquery()
                    .label("groups"),
                    select(
                        func.jsonb_agg(
                            aggregate_order_by(
                                func.to_jsonb(sampled.table_valued()),
                                sampled.c.historical_source_retry_due.desc(),
                                sampled.c.source_day.desc().nulls_last(),
                                sampled.c.window_key,
                            )
                        )
                    )
                    .scalar_subquery()
                    .label("samples"),
                ).select_from(pending)
            )
            .mappings()
            .one()
        )
    groups = tuple(
        sorted(
            (
                EisGapReasonGroup(category=gap_category(r["outcome"], r["reason_code"]), **r)
                for r in (totals["groups"] or ())
            ),
            key=lambda g: (-g.targets, g.category, g.outcome or "", g.reason_code or ""),
        )
    )
    return EisGapStatus(
        company_id=company_id,
        checked_at=now,
        status="UNKNOWN" if totals["invalid"] else "OBSERVED",
        planned_targets=totals["planned"],
        completed_targets=int(totals["planned"]) - int(totals["pending"]),
        pending_targets=totals["pending"],
        unattempted_targets=totals["unattempted"],
        no_data_targets=totals["no_data"],
        historical_source_retry_due=totals["retry_due"],
        transport_only_targets=totals["transport_only"],
        invalid_source_coordinates=totals["invalid"],
        candidate_region_codes=totals["regions"],
        oldest_source_day=totals["oldest"],
        newest_source_day=totals["newest"],
        groups=groups,
        samples=tuple(EisGapSample(**r) for r in (totals["samples"] or ())),
        sample_limit=sample_limit,
        samples_truncated=int(totals["pending"]) > sample_limit,
    )
