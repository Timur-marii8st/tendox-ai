"""Classify supplied read-only demand observations; this never grants a source turn."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, ValidationError

from procurement.eis_freshness_dispatch_cli import FreshnessDispatchProbe
from procurement.sources.eis_corpus import parse_date_window
from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES
from procurement.storage.eis_223_regions import FAMILIES

_MSK = timezone(timedelta(hours=3))


def _reconciliation_days(law: str, at: datetime) -> tuple[date, ...]:
    """Mirror the default protected producer scope, not its database outcomes."""
    local_day = at.astimezone(_MSK).date()
    days = tuple(local_day - timedelta(days=n) for n in range(1, 4))
    if law == "44":
        return tuple(
            day
            for day in days
            if datetime.combine(day, datetime.min.time(), _MSK)
            + timedelta(days=1, hours=2, minutes=5)
            <= at
        )
    return days


class ReconciliationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["DUE", "CLEAR", "UNKNOWN"]
    company_id: str
    law: Literal["44", "223"]
    scope_sha256: str
    catalog_sha256: str
    evidence_id: str
    checked_at: AwareDatetime
    scope_complete: StrictBool
    coordinates: tuple[str, ...] = Field(max_length=2)


class HistoryDemandObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: str
    regions: tuple[str, ...]
    document_types: tuple[str, ...]
    read_started_at: AwareDatetime
    checked_at: AwareDatetime
    catalog_sha256: str
    catalog_observation_id: str
    catalog_usable: StrictBool
    catalog_refresh_due: StrictBool
    checkpointed: StrictBool
    mandatory_only: StrictBool
    include_regional: StrictBool
    regional_scope_complete: StrictBool
    regional_document_types: tuple[str, ...]
    probe: FreshnessDispatchProbe
    reconciliation44: ReconciliationObservation
    reconciliation223: ReconciliationObservation


class HistoryDemandClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["READY", "IDLE", "BLOCKED"]
    reason: str | None = None
    company_id: str | None = None
    regions: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()
    regional_document_types: tuple[str, ...] = ()
    catalog_sha256: str | None = None
    observation_sha256: str | None = None
    read_started_at: AwareDatetime | None = None
    checked_at: AwareDatetime | None = None
    source_requests: Literal[0] = 0
    writes: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


def classify_history_demand(
    value: Mapping[str, object],
    *,
    company_id: str,
    regions: tuple[str, ...],
    document_types: tuple[str, ...],
    regional_document_types: tuple[str, ...],
    expected_catalog_sha256: str,
    expected_catalog_observation_id: str,
    now: datetime,
) -> HistoryDemandClassification:
    """Describe verified observations only; a separate guarded caller decides admission."""
    blocked = HistoryDemandClassification(status="BLOCKED", reason="OBSERVATION_UNAVAILABLE")
    if now.tzinfo is None or now.utcoffset() is None:
        return blocked
    probe_value = value.get("probe")
    required = {
        "status",
        "company_id",
        "regions",
        "document_types",
        "checked_at",
        "baseline_due",
        "urgent_due",
        "foreground_due",
        "regional_due",
        "regional_new_wave_due",
        "reason",
        "attempted",
        "coverage",
        "freshness",
    }
    counters = ("baseline_due", "urgent_due", "foreground_due", "regional_due", "attempted")
    if not isinstance(probe_value, Mapping) or not required <= probe_value.keys():
        return blocked
    if (
        any(type(probe_value[k]) is not int for k in counters)
        or type(probe_value["regional_new_wave_due"]) is not bool
    ):
        return blocked
    try:
        item = HistoryDemandObservation.model_validate(value)
    except (ValidationError, ValueError, TypeError):
        return blocked
    probe = item.probe
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", company_id)
        or item.company_id != company_id
        or probe.company_id != company_id
        or not regions
        or regions != tuple(sorted(set(regions)))
        or any(not re.fullmatch(r"(?:0[1-9]|[1-9][0-9])", region) for region in regions)
        or item.regions != regions
        or probe.regions != regions
        or not document_types
        or document_types != tuple(sorted(set(document_types)))
        or item.document_types != document_types
        or probe.document_types != document_types
        or any(kind not in SUPPORTED_NOTICE_TYPES for kind in document_types)
        or not regional_document_types
        or regional_document_types != tuple(sorted(set(regional_document_types)))
        or item.regional_document_types != regional_document_types
        or regional_document_types != tuple(sorted(FAMILIES))
        or not (item.checkpointed and item.mandatory_only and item.include_regional)
        or not item.regional_scope_complete
        or not re.fullmatch(r"[0-9a-f]{64}", item.catalog_sha256)
        or item.catalog_sha256 != expected_catalog_sha256
        or item.catalog_observation_id != expected_catalog_observation_id
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item.catalog_observation_id)
        or not item.catalog_usable
        or probe.reason is not None
        or probe.status == "BLOCKED"
    ):
        return blocked
    now = now.astimezone(UTC)
    start, end = item.read_started_at.astimezone(UTC), item.checked_at.astimezone(UTC)
    if not (start <= end <= now) or (now - start).total_seconds() > 30:
        return blocked
    times = (probe.checked_at, item.reconciliation44.checked_at, item.reconciliation223.checked_at)
    if any(
        t.tzinfo is None or t.utcoffset() is None or not start <= t.astimezone(UTC) <= end
        for t in times
    ):
        return blocked
    due = False
    for law, obs in (("44", item.reconciliation44), ("223", item.reconciliation223)):
        days = _reconciliation_days(law, obs.checked_at)
        if _reconciliation_days(law, start) != days or _reconciliation_days(law, now) != days:
            return blocked
        scope = dict(
            company_id=company_id,
            law=law,
            regions=regions,
            document_types=document_types if law == "44" else regional_document_types,
            catalog_sha256=item.catalog_sha256,
            query_at=obs.checked_at.astimezone(UTC).isoformat(),
            timezone="+03:00",
            days=[day.isoformat() for day in days],
            cutoff="completed-day-plus-02:05" if law == "44" else "recent-three-msk-days",
        )
        digest = hashlib.sha256(
            json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if (
            obs.status == "UNKNOWN"
            or obs.company_id != company_id
            or obs.law != law
            or obs.catalog_sha256 != item.catalog_sha256
            or obs.scope_sha256 != digest
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", obs.evidence_id)
            or (obs.status == "CLEAR" and (not obs.scope_complete or obs.coordinates))
            or (obs.status == "DUE" and not obs.coordinates)
            or any(not re.fullmatch(r"[^\x00-\x1f\x7f]{1,512}", key) for key in obs.coordinates)
        ):
            return blocked
        for key in obs.coordinates:
            try:
                if law == "44":
                    selection = parse_date_window(key)
                    valid = (
                        selection.window_key == key
                        and selection.region in regions
                        and selection.document_type in document_types
                        and selection.utc_offset_hours == 3
                        and selection.day in days
                    )
                else:
                    match = re.fullmatch(
                        r"getDocsIP/RI223/([0-9]{1,2})/(\d{4}-\d{2}-\d{2})\+03:00/([A-Za-z0-9]+)",
                        key,
                    )
                    valid = bool(
                        match
                        and match[1] in regions
                        and match[3] in regional_document_types
                        and date.fromisoformat(match[2]) in days
                    )
                if not valid:
                    return blocked
            except (ValueError, TypeError):
                return blocked
        due |= obs.status == "DUE"
    probe_due = bool(
        probe.baseline_due
        or probe.foreground_due
        or probe.regional_due
        or probe.regional_new_wave_due
    )
    if (probe.status == "READY") != probe_due:
        return blocked
    if (
        probe.regional_due > 2
        or probe.urgent_due < probe.foreground_due
        or probe.urgent_due > 24 + probe.foreground_due
        or (not probe_due and probe.urgent_due)
    ):
        return blocked
    raw = json.dumps(
        item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return HistoryDemandClassification(
        status="READY" if probe_due or due or item.catalog_refresh_due else "IDLE",
        company_id=company_id,
        regions=regions,
        document_types=document_types,
        regional_document_types=regional_document_types,
        catalog_sha256=item.catalog_sha256,
        observation_sha256=hashlib.sha256(raw).hexdigest(),
        read_started_at=start,
        checked_at=end,
    )
