"""Lot cancellation evidence; stable identity/revision resolution remains UNKNOWN."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot, TextFact
from procurement.sources.eis_223_events import Eis223EventSchemaCheck
from procurement.sources.eis_223_lot_events import Eis223LotCancellation
from procurement.sources.eis_223_schema import VALIDATOR


class Eis223LotCancellationState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    checked_at: datetime
    evidence_status: Literal["UNKNOWN"] = "UNKNOWN"
    application_status: Literal["UNKNOWN"] = "UNKNOWN"
    current_procedure_status: Literal["UNKNOWN"] = "UNKNOWN"
    source_schema_status: Literal["PASS", "FAIL", "UNKNOWN"]
    operation_hold: bool
    reason_codes: tuple[str, ...]
    events: tuple[Eis223LotCancellation, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def _bound(self) -> Eis223LotCancellationState:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        if self.operation_hold != bool(self.events or "EVENT_EVIDENCE_LIMIT" in self.reason_codes):
            raise ValueError("LOT_CANCELLATION_STATE_INVALID")
        if self.operation_hold and "LOT_CANCELLATION_REVIEW_REQUIRED" not in self.reason_codes:
            raise ValueError("LOT_CANCELLATION_REASON_MISSING")
        return self


class Eis223SelectedLotCancellationState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    selected_index: int = Field(ge=1)
    lot_ordinal: TextFact
    lot_guid: TextFact | None
    notice_xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_hold: bool
    application_status: Literal["UNKNOWN"] = "UNKNOWN"
    association_status: Literal["UNKNOWN"] = "UNKNOWN"
    reason_codes: tuple[str, ...]
    apparent_match_event_guids: tuple[str, ...]

    @model_validator(mode="after")
    def _bound(self) -> Eis223SelectedLotCancellationState:
        if self.operation_hold and "LOT_CANCELLATION_IDENTITY_UNRESOLVED" not in self.reason_codes:
            raise ValueError("LOT_ASSOCIATION_REASON_MISSING")
        if self.lot_ordinal.provenance.document_id != self.notice_xml_sha256 or (
            self.lot_guid and self.lot_guid.provenance.document_id != self.notice_xml_sha256
        ):
            raise ValueError("SELECTED_LOT_PROVENANCE_INVALID")
        return self


def resolve_lot_cancellation_state(
    purchase_number: str,
    events: Iterable[Eis223LotCancellation],
    schema_checks: Iterable[Eis223EventSchemaCheck],
    *,
    now: datetime,
    reason_codes: tuple[str, ...] = (),
    event_limit: int = 100,
) -> Eis223LotCancellationState:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if event_limit != 100:
        raise ValueError("EVENT_LIMIT_POLICY_INVALID")
    material = tuple(events)
    reasons = set(reason_codes)
    if len(material) > event_limit or "EVENT_EVIDENCE_LIMIT" in reasons:
        return Eis223LotCancellationState(
            purchase_number=purchase_number,
            checked_at=now,
            source_schema_status="UNKNOWN",
            operation_hold=True,
            events=(),
            reason_codes=tuple(
                sorted(
                    reasons
                    | {
                        "EVENT_EVIDENCE_LIMIT",
                        "LOT_CANCELLATION_REVIEW_REQUIRED",
                        "LOT_CANCELLATION_IDENTITY_UNRESOLVED",
                    }
                )
            ),
        )
    by_identity = {(e.event_guid.value, e.xml_sha256): e for e in material}
    if len(by_identity) != len(material):
        raise ValueError("EVENT_VARIANT_DUPLICATE")
    direct = {e.event_guid.value for e in material if e.purchase_number == purchase_number}
    if any(
        e.purchase_number != purchase_number and e.event_guid.value not in direct for e in material
    ):
        raise ValueError("EVENT_ASSOCIATION_INVALID")
    if not material:
        return Eis223LotCancellationState(
            purchase_number=purchase_number,
            checked_at=now,
            source_schema_status="UNKNOWN",
            operation_hold=False,
            events=(),
            reason_codes=tuple(sorted(reasons | {"NO_LOT_CANCELLATION_EVENT_EVIDENCE"})),
        )
    if any(e.purchase_number != purchase_number for e in material):
        reasons.add("LOT_EVENT_GUID_TARGET_CONFLICT")
    if len({e.event_guid.value for e in material}) != len(material):
        reasons.add("LOT_EVENT_GUID_VARIANTS")
    quality: dict[tuple[str | None, str], dict[str, str]] = {}
    for check in schema_checks:
        event = by_identity.get((check.event_guid, check.xml_sha256))
        if event is None or check.purchase_number != event.purchase_number:
            raise ValueError("EVENT_SCHEMA_ASSOCIATION_INVALID")
        key = (check.event_guid, check.xml_sha256)
        if check.schema_release in quality.setdefault(key, {}):
            raise ValueError("EVENT_SCHEMA_CHECK_DUPLICATE")
        quality[key][check.schema_release] = (
            check.status if check.validator_version == VALIDATOR else "UNKNOWN"
        )
    status: Literal["PASS", "FAIL", "UNKNOWN"] = "PASS"
    for identity in by_identity:
        checks = quality.get(identity, {})
        if "FAIL" in checks.values():
            status = "FAIL"
        elif (
            set(checks) != {"16.2", "16.3"} or set(checks.values()) != {"PASS"}
        ) and status != "FAIL":
            status = "UNKNOWN"
    if status != "PASS":
        reasons.add("LOT_CANCELLATION_SCHEMA_INCOMPLETE")
    for event in material:
        created, published = event.created_at.value, event.publication_at.value
        if created is None or published is None or created > published or published > now:
            reasons.add("LOT_CANCELLATION_TIME_UNRESOLVED")
        decisions = (
            ((event.common_cancellation_date, event.common_cancellation_cause),)
            if event.description_type == "COMMON"
            else tuple(
                (lot.cancellation_date, lot.cancellation_cause) for lot in event.cancelled_lots
            )
        )
        if not decisions or any(d.value is None or not cause.value for d, cause in decisions):
            reasons.add("LOT_CANCELLATION_DECISION_INCOMPLETE")
    reasons.update({"LOT_CANCELLATION_REVIEW_REQUIRED", "LOT_CANCELLATION_IDENTITY_UNRESOLVED"})
    return Eis223LotCancellationState(
        purchase_number=purchase_number,
        checked_at=now,
        source_schema_status=status,
        operation_hold=True,
        reason_codes=tuple(sorted(reasons)),
        events=tuple(sorted(material, key=lambda e: (e.event_guid.value or "", e.xml_sha256))),
    )


def selected_lot_cancellation_state(
    notice: Eis223NoticeSnapshot,
    selected_index: int,
    state: Eis223LotCancellationState,
) -> Eis223SelectedLotCancellationState:
    if state.purchase_number != notice.purchase_number:
        raise ValueError("LOT_EVENT_NOTICE_ASSOCIATION_INVALID")
    if not 1 <= selected_index <= len(notice.lots):
        raise ValueError("SELECTED_LOT_NOT_FOUND")
    lot = notice.lots[selected_index - 1]
    apparent = set()
    for event in state.events:
        if event.purchase_number != notice.purchase_number:
            continue
        for cancelled in event.cancelled_lots:
            if (
                lot.guid
                and lot.guid.value
                and (
                    cancelled.lot_guid.value == lot.guid.value.lower()
                    and cancelled.ordinal.value == lot.ordinal.value
                )
            ):
                apparent.add(event.event_guid.value or "")
    # Coincidence is diagnostic, never permission or proof of an unaffected lot.
    return Eis223SelectedLotCancellationState(
        selected_index=selected_index,
        lot_ordinal=lot.ordinal,
        lot_guid=lot.guid,
        notice_xml_sha256=notice.xml_sha256,
        operation_hold=state.operation_hold,
        reason_codes=state.reason_codes,
        apparent_match_event_guids=tuple(sorted(apparent)),
    )
