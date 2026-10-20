"""Evidence-backed regional polling lag and measured worker capacity, not recall."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import RowMapping

from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_variant_intake import EisVariantIntakeReport
from procurement.storage.models import audit_events, eis_feed_windows, eis_sync_attempts

if TYPE_CHECKING:
    from procurement.sources.eis_freshness import EisFreshnessScope, FreshnessTarget
    from procurement.storage.repository import PostgresStorage


class EisWindowObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    company_id: str = Field(min_length=1)
    window_key: str
    region: str
    document_type: str
    lane: Literal["RECENT_HOUR", "RECONCILE_DAY", "EARLIER_HOUR"]
    started_at: datetime
    finished_at: datetime
    duration_ms: Decimal = Field(ge=0)
    outcome: Literal["SYNCED", "SKIPPED", "NO_DATA", "PREPARING", "SERVICE_ERROR", "FAILED"]
    reason: str | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    archive_bytes: int | None = Field(default=None, ge=0)
    new_versions: int = Field(default=0, ge=0)
    new_events: int = Field(default=0, ge=0)
    rejection_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rejection_retention_status: Literal["RETAINED", "DISABLED", "FAILED", "UNAVAILABLE"] | None = (
        None
    )
    rejection_audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] | None = None
    rejection_diagnosis_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rejection_diagnosis_audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] | None = None
    variant_intake: EisVariantIntakeReport | None = None

    @model_validator(mode="after")
    def validate_times(self) -> EisWindowObservation:
        parts = self.window_key.split("/")
        if len(parts) < 4 or parts[:2] != ["getDocsIP", "PRIZ"] or parts[2] != self.region:
            raise ValueError("OBSERVATION_SOURCE_COORDINATES_INVALID")
        kind = parts[-1] if parts[-1].startswith("epNotification") else "epNotificationEF2020"
        if kind != self.document_type:
            raise ValueError("OBSERVATION_SOURCE_COORDINATES_INVALID")
        for value in (self.started_at, self.finished_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("OBSERVATION_TIMEZONE_MISSING")
        if self.finished_at < self.started_at:
            raise ValueError("OBSERVATION_CLOCK_REVERSED")
        if self.outcome in {"SYNCED", "NO_DATA"} and self.response_sha256 is None:
            raise ValueError("OBSERVATION_SOURCE_EVIDENCE_MISSING")
        if self.rejection_retention_status is not None and (
            self.outcome != "FAILED"
            or self.response_sha256 is None
            or self.rejection_audit_status is None
        ):
            raise ValueError("REJECTION_OBSERVATION_INVALID")
        if (self.rejection_retention_status == "RETAINED") != (
            self.rejection_manifest_sha256 is not None
        ):
            raise ValueError("REJECTION_OBSERVATION_INVALID")
        if (self.rejection_diagnosis_audit_status == "RECORDED") != (
            self.rejection_diagnosis_sha256 is not None
        ):
            raise ValueError("REJECTION_DIAGNOSIS_OBSERVATION_INVALID")
        if self.rejection_diagnosis_audit_status is not None and (
            self.outcome != "FAILED" or self.rejection_retention_status is None
        ):
            raise ValueError("REJECTION_DIAGNOSIS_OBSERVATION_INVALID")
        if self.rejection_diagnosis_sha256 and (
            self.rejection_retention_status != "RETAINED"
            or self.rejection_audit_status != "RECORDED"
        ):
            raise ValueError("REJECTION_DIAGNOSIS_OBSERVATION_INVALID")
        if self.variant_intake is not None:
            if self.outcome != "FAILED" or self.rejection_retention_status is None:
                raise ValueError("VARIANT_INTAKE_OBSERVATION_INVALID")
            if self.variant_intake.status == "PARTIAL" and (
                self.rejection_retention_status != "RETAINED"
                or self.rejection_audit_status != "RECORDED"
                or self.rejection_diagnosis_audit_status != "RECORDED"
                or self.new_versions != self.variant_intake.new_versions
            ):
                raise ValueError("VARIANT_INTAKE_OBSERVATION_INVALID")
        return self


class EisRegionalFreshness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    region: str
    document_type: str
    hour_targets: int
    date_targets: int
    unattempted: int
    due: int
    failed: int
    no_data: int
    latest_attempted_at: datetime | None
    latest_synced_at: datetime | None
    latest_no_data_at: datetime | None
    oldest_due_hour_start: datetime | None
    latest_ingested_hour_start: datetime | None
    eligible_hour_lag_seconds: int | None
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"


class EisCapacityEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    samples: int
    completed_samples: int
    failed_samples: int
    p50_ms: Decimal | None
    p95_ms: Decimal | None
    nominal_slots_per_hour: int
    measured_slots_per_hour: int | None
    required_latest_hour_slots_per_hour: int
    conservative_recent_poll_slots_per_hour: int
    projected_recent_poll_seconds: Decimal | None
    recent_poll_budget_fit: Literal["PASS", "FAIL", "UNKNOWN"]
    # Ongoing source availability, backlog, and every family are not certified.
    overall_feasibility: Literal["UNKNOWN"] = "UNKNOWN"
    conservative_peak_slots_per_hour: Decimal
    peak_budget_fit: Literal["PASS", "FAIL", "UNKNOWN"]


def capacity_estimate(
    observations: tuple[EisWindowObservation, ...],
    *,
    regions: int,
    document_types: int,
    run_slots: int = 24,
    run_seconds: int = 240,
    cadence_seconds: int = 300,
) -> EisCapacityEstimate:
    if not 1 <= regions <= 99 or not 1 <= document_types <= len(SUPPORTED_NOTICE_TYPES):
        raise ValueError("CAPACITY_SCOPE_INVALID")
    if min(run_slots, run_seconds, cadence_seconds) <= 0:
        raise ValueError("CAPACITY_BUDGET_INVALID")
    durations = sorted(
        observation.duration_ms
        for observation in observations
        if observation.outcome in {"SYNCED", "NO_DATA"}
    )
    failures = sum(
        item.outcome in {"FAILED", "SERVICE_ERROR", "PREPARING"} for item in observations
    )
    nominal = run_slots * 3600 // cadence_seconds
    p50 = durations[math.ceil(len(durations) * Decimal("0.50")) - 1] if durations else None
    p95 = durations[math.ceil(len(durations) * Decimal("0.95")) - 1] if durations else None
    measured = None
    projected = None
    fit: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    recent = regions * document_types * 2
    # Maximum 22 addressable current-day hours: 2 recent, 20 earlier / 6h,
    # plus three completed days / 24h. Does not include startup/backfill contention.
    peak = Decimal(regions * document_types) * (Decimal(2) + Decimal(20) / 6 + Decimal(3) / 24)
    if len(durations) >= 8 and p95 is not None and p95 > 0:
        # Include the existing two-second spacing between windows.
        slot_seconds = p95 / 1000 + Decimal(2)
        measured = min(nominal, int(Decimal(run_seconds) / slot_seconds) * 3600 // cadence_seconds)
        projected = (slot_seconds * recent).quantize(Decimal("0.001"))
        fit = "PASS" if recent <= measured else "FAIL"
    return EisCapacityEstimate(
        samples=len(observations),
        completed_samples=len(durations),
        failed_samples=failures,
        p50_ms=p50,
        p95_ms=p95,
        nominal_slots_per_hour=nominal,
        measured_slots_per_hour=measured,
        required_latest_hour_slots_per_hour=regions * document_types,
        conservative_recent_poll_slots_per_hour=recent,
        projected_recent_poll_seconds=projected,
        recent_poll_budget_fit=fit,
        conservative_peak_slots_per_hour=peak.quantize(Decimal("0.001")),
        peak_budget_fit=("UNKNOWN" if measured is None else "PASS" if peak <= measured else "FAIL"),
    )


class EisFreshnessStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    company_id: str
    checked_at: datetime
    regions: tuple[str, ...]
    document_types: tuple[str, ...]
    observation_hours: int
    regional: tuple[EisRegionalFreshness, ...]
    capacity: EisCapacityEstimate
    evidence_attempt_ids: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]
    observations_without_metrics: int
    observation_limit_reached: bool
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"


def freshness_status(
    storage: PostgresStorage,
    company_id: str,
    scope: EisFreshnessScope,
    *,
    now: datetime,
    observation_hours: int = 24,
    run_slots: int = 24,
    run_seconds: int = 240,
    cadence_seconds: int = 300,
) -> EisFreshnessStatus:
    from procurement.sources.eis_feed_sync import EisHourSelection
    from procurement.sources.eis_freshness import due_target

    targets = scope.targets(now)
    if not company_id.strip() or not 1 <= observation_hours <= 168:
        raise ValueError("FRESHNESS_STATUS_INVALID")
    keys = [item.selection.window_key for item in targets]
    with storage.transaction(company_id, consistent_read=True) as connection:
        attempts = (
            connection.execute(
                select(eis_sync_attempts)
                .where(
                    eis_sync_attempts.c.company_id == company_id,
                    eis_sync_attempts.c.window_key.in_(keys),
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
        history = (
            connection.execute(
                select(
                    eis_sync_attempts.c.window_key,
                    eis_sync_attempts.c.outcome,
                    func.max(eis_sync_attempts.c.attempted_at).label("at"),
                )
                .where(
                    eis_sync_attempts.c.company_id == company_id,
                    eis_sync_attempts.c.window_key.in_(keys),
                )
                .group_by(eis_sync_attempts.c.window_key, eis_sync_attempts.c.outcome)
            )
            .mappings()
            .all()
        )
        ingested = set(
            connection.execute(
                select(eis_feed_windows.c.window_key)
                .where(
                    eis_feed_windows.c.company_id == company_id,
                    eis_feed_windows.c.window_key.in_(keys),
                    eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
                )
                .distinct()
            ).scalars()
        )
        metrics_rows = (
            connection.execute(
                select(audit_events.c.event_id, audit_events.c.basis)
                .where(
                    and_(
                        audit_events.c.company_id == company_id,
                        audit_events.c.event_type == "EIS_SYNC_ATTEMPT_RECORDED",
                        audit_events.c.occurred_at >= now - timedelta(hours=observation_hours),
                        audit_events.c.occurred_at <= now,
                        or_(
                            *[
                                audit_events.c.object_id.like(f"getDocsIP/PRIZ/{region}/%")
                                for region in scope.regions
                            ]
                        ),
                    ),
                )
                .order_by(audit_events.c.occurred_at.desc())
                .limit(2001)
            )
            .mappings()
            .all()
        )
    latest: dict[str, RowMapping] = {row["window_key"]: row for row in attempts}
    observations: list[EisWindowObservation] = []
    event_ids: list[str] = []
    missing = 0
    for row in metrics_rows[:2000]:
        raw = row["basis"].get("observation")
        if raw is None:
            missing += 1
            continue
        item = EisWindowObservation.model_validate(raw)
        if item.company_id != company_id or item.region not in scope.regions:
            raise ValueError("OBSERVATION_TENANT_OR_WINDOW_MISMATCH")
        if item.document_type not in scope.document_types:
            continue
        observations.append(item)
        event_ids.append(row["event_id"])
    regional: list[EisRegionalFreshness] = []
    for region in scope.regions:
        for kind in scope.document_types:
            selected = [
                target
                for target in targets
                if target.selection.region == region and target.selection.document_type == kind
            ]
            known = [
                latest[target.selection.window_key]
                for target in selected
                if target.selection.window_key in latest
            ]
            selected_keys = {target.selection.window_key for target in selected}
            due = []
            for target in selected:
                last = latest.get(target.selection.window_key)
                if due_target(
                    target,
                    now=now,
                    attempted_at=last["attempted_at"] if last else None,
                    outcome=last["outcome"] if last else None,
                    reason=last["reason_code"] if last else None,
                ):
                    due.append(target)

            def hour_start(target: FreshnessTarget) -> datetime:
                selection = target.selection
                assert isinstance(selection, EisHourSelection)
                return datetime.combine(selection.day, datetime.min.time()).replace(
                    hour=selection.hour,
                    tzinfo=timezone(timedelta(hours=selection.utc_offset_hours)),
                )

            ingested_hours = [
                hour_start(target)
                for target in selected
                if isinstance(target.selection, EisHourSelection)
                and target.selection.window_key in ingested
            ]
            due_hours = [
                hour_start(target)
                for target in due
                if isinstance(target.selection, EisHourSelection)
            ]
            eligible_hours = [
                hour_start(target)
                for target in selected
                if isinstance(target.selection, EisHourSelection)
            ]
            lag = (
                int((max(eligible_hours) - max(ingested_hours)).total_seconds())
                if ingested_hours
                else None
            )
            regional.append(
                EisRegionalFreshness(
                    region=region,
                    document_type=kind,
                    hour_targets=len(eligible_hours),
                    date_targets=len(selected) - len(eligible_hours),
                    unattempted=len(selected) - len(known),
                    due=len(due),
                    failed=sum(
                        row["outcome"] in {"FAILED", "SERVICE_ERROR", "PREPARING"} for row in known
                    ),
                    no_data=sum(row["outcome"] == "NO_DATA" for row in known),
                    latest_attempted_at=max((row["attempted_at"] for row in known), default=None),
                    latest_synced_at=max(
                        (
                            row["at"]
                            for row in history
                            if row["window_key"] in selected_keys and row["outcome"] == "SYNCED"
                        ),
                        default=None,
                    ),
                    latest_no_data_at=max(
                        (
                            row["at"]
                            for row in history
                            if row["window_key"] in selected_keys and row["outcome"] == "NO_DATA"
                        ),
                        default=None,
                    ),
                    oldest_due_hour_start=min(due_hours, default=None),
                    latest_ingested_hour_start=max(ingested_hours, default=None),
                    eligible_hour_lag_seconds=lag,
                )
            )
    return EisFreshnessStatus(
        company_id=company_id,
        checked_at=now,
        regions=scope.regions,
        document_types=scope.document_types,
        observation_hours=observation_hours,
        regional=tuple(regional),
        capacity=capacity_estimate(
            tuple(observations),
            regions=len(scope.regions),
            document_types=len(scope.document_types),
            run_slots=run_slots,
            run_seconds=run_seconds,
            cadence_seconds=cadence_seconds,
        ),
        evidence_attempt_ids=tuple(row["attempt_id"] for row in attempts),
        evidence_event_ids=tuple(event_ids),
        observations_without_metrics=missing,
        observation_limit_reached=len(metrics_rows) > 2000,
    )
