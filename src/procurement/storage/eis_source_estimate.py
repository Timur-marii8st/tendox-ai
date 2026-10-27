"""Ephemeral, exact-source preliminary economics; never a participation decision."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    DiscoveryEstimate,
    calculate_discovery_economics,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import DecimalFact, TextFact
from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.sources.eis_223_events import Eis223RejectionState
from procurement.sources.eis_223_lot_event_policy import (
    Eis223LotCancellationState,
    Eis223SelectedLotCancellationState,
    selected_lot_cancellation_state,
)
from procurement.storage.eis_223_comparison import read_comparison223_row
from procurement.storage.eis_comparison import comparison44_row
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_evidence_bridge import read_eis_evidence_bridge
from procurement.storage.eis_mixed_comparison import MixedNoticeRef

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


class SourceLotError(ValueError):
    """The explicitly selected source lot does not exist."""


class SourceEstimateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    notice: MixedNoticeRef
    lot_index: StrictInt | None = Field(default=None, ge=1)
    costs: DiscoveryCostInput

    @model_validator(mode="after")
    def law_bound_lot(self) -> SourceEstimateRequest:
        if (self.notice.law == "223") != (self.lot_index is not None):
            raise ValueError("223 requires an explicit lot; 44 does not accept a lot index")
        return self


class SourceEstimateResult(BaseModel):
    cancellation_state: Eis223RejectionState | None = None
    lot_cancellation_state: Eis223LotCancellationState | None = None
    selected_lot_cancellation_state: Eis223SelectedLotCancellationState | None = None
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SourceEstimateRequest
    checked_at: datetime
    actor_id: str = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manual_provenance: Provenance
    ceiling: DecimalFact
    ceiling_rub: Decimal | None
    unit_quantity: DecimalFact | None = None
    quantity_unit: TextFact | None = None
    lot_ordinal: TextFact | None = None
    currency: TextFact | None = None
    source_schema_status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    source_price_kind: (
        Literal["INITIAL_SUM", "MAX_CONTRACT_PRICE", "TEXT_ONLY", "UNKNOWN"] | None
    ) = None
    blocking_reasons: tuple[str, ...]
    source_reasons: tuple[str, ...]
    estimate: DiscoveryEstimate
    calculation_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    quote_status: Literal["UNKNOWN"] = "UNKNOWN"
    requirement_status: Literal["UNKNOWN"] = "UNKNOWN"
    full_cost_review: Literal["UNKNOWN"] = "UNKNOWN"
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    profit_order_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def exact_evidence(self) -> SourceEstimateResult:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        if self.ceiling.provenance.document_id != self.request.notice.notice_xml_sha256:
            raise ValueError("CEILING_EVIDENCE_MISMATCH")
        for fact in (self.unit_quantity, self.quantity_unit):
            if (
                fact is not None
                and fact.provenance.document_id != self.request.notice.notice_xml_sha256
            ):
                raise ValueError("UNIT_BASIS_EVIDENCE_MISMATCH")
        if self.manual_provenance.extractor != Extractor.MANUAL:
            raise ValueError("MANUAL_INPUT_REQUIRED")
        if self.ceiling_rub is not None and self.ceiling_rub != self.ceiling.value:
            raise ValueError("CEILING_VALUE_MISMATCH")
        if self.blocking_reasons and (self.estimate.status != "BLOCKED" or self.estimate.scenarios):
            raise ValueError("SOURCE_BLOCKER_CANNOT_BE_OVERRIDDEN")
        return self


def get_source_estimate(
    storage: PostgresStorage,
    company: str,
    request: SourceEstimateRequest,
    *,
    actor_id: str,
    now: datetime | None = None,
) -> SourceEstimateResult:
    """One tenant read snapshot, cached evidence only, no writes or source fetches."""
    at = now or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if not company.strip() or not actor_id.strip():
        raise ValueError("TENANT_ACTOR_REQUIRED")
    chosen = request.notice
    payload = chosen.model_dump(exclude={"law"})
    ordinal = currency = None
    unit_quantity = quantity_unit = None
    cancellation_state = None
    lot_cancellation_state = None
    selected_state = None
    quality_status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    price_kind: Literal["INITIAL_SUM", "MAX_CONTRACT_PRICE", "TEXT_ONLY", "UNKNOWN"] | None = None
    blockers: tuple[str, ...]
    with storage.transaction(company, consistent_read=True) as conn:
        if chosen.law == "44":
            bridge = read_eis_evidence_bridge(
                conn,
                company,
                NoticeDocumentRef.model_validate(payload),
                now=at,
                include_competition_criteria=False,
            )
            row = comparison44_row(bridge)
            blockers = row.blocking_reasons
            reasons = row.reasons + bridge.application_reasons
            ceiling_rub = bridge.nmck_rub
            positions = bridge.position_set
            if (
                positions is not None
                and positions.positions_total == 1
                and not positions.positions_truncated
                and len(positions.positions) == 1
            ):
                unit_quantity = positions.positions[0].quantity
                quantity_unit = positions.positions[0].unit
            ceiling = DecimalFact(
                value=ceiling_rub,
                raw=None,
                provenance=bridge.nmck_provenance
                or Provenance(
                    document_id=chosen.notice_xml_sha256,
                    locator=f"{bridge.document_type}/notificationInfo/contractConditionsInfo/maxPriceInfo/maxPrice",
                    extractor=Extractor.API,
                ),
            )
        else:
            row223 = read_comparison223_row(
                conn,
                company,
                Notice223DocumentRef.model_validate(payload),
                now=at,
            )
            index = request.lot_index
            if index is None or index > len(row223.notice.lots):
                raise SourceLotError("SELECTED_LOT_NOT_FOUND")
            lot = row223.notice.lots[index - 1]
            if len(lot.items) == 1:
                unit_quantity = lot.items[0].quantity
                quantity_unit = lot.items[0].unit_name
            blockers = tuple(
                code
                for code in row223.blocking_reasons
                if code != "LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED"
            )
            lot_cancellation_state = row223.lot_cancellation_state
            if lot_cancellation_state is not None:
                selected_state = selected_lot_cancellation_state(
                    row223.notice, index, lot_cancellation_state
                )
                if selected_state.operation_hold:
                    blockers += selected_state.reason_codes
            elif "LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED" in row223.blocking_reasons:
                blockers += ("LOT_CANCELLATION_IDENTITY_UNRESOLVED",)
            cancellation_state = row223.cancellation_state
            if (lot.cancelled_raw.value or "").strip().lower() in {"true", "1"}:
                blockers += ("SELECTED_LOT_CANCELLED",)
            quality_status = row223.source_schema_status
            price_kind = lot.source_price_kind or "INITIAL_SUM"
            reasons = row223.reasons
            ceiling, ceiling_rub = lot.initial_sum, lot.initial_sum_rub
            ordinal = lot.ordinal
            currency = (
                lot.currency_letter_code
                if lot.currency_letter_code and lot.currency_letter_code.value
                else lot.currency
            )
    estimate = calculate_discovery_economics(ceiling_rub, request.costs, blocked=bool(blockers))
    if blockers:
        estimate = estimate.model_copy(
            update={
                "reasons": tuple(f"Расчёт заблокирован источником: {code}." for code in blockers)
            }
        )
    # The engine uses the generic NMCK label. Preserve the 223 lot's distinct meaning.
    if chosen.law == "223":
        estimate = estimate.model_copy(
            update={
                "reasons": tuple(
                    r.replace(
                        "опубликованной НМЦК", "опубликованной начальной цене выбранного лота"
                    ).replace(
                        "НМЦК не подтверждена", "Начальная цена выбранного лота не подтверждена"
                    )
                    for r in estimate.reasons
                ),
                "scenarios": tuple(
                    s.model_copy(
                        update={
                            "assumptions": tuple(
                                a.replace("НМЦК", "начальная цена выбранного лота")
                                for a in s.assumptions
                            )
                        }
                    )
                    for s in estimate.scenarios
                ),
            }
        )
    digest = hashlib.sha256(
        json.dumps(
            {"company": company, "actor": actor_id, "request": request.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return SourceEstimateResult(
        cancellation_state=cancellation_state,
        lot_cancellation_state=lot_cancellation_state,
        selected_lot_cancellation_state=selected_state,
        request=request,
        checked_at=at,
        actor_id=actor_id,
        input_sha256=digest,
        manual_provenance=Provenance(
            document_id=f"manual:eis-source-estimate:{digest}",
            locator="/request/costs",
            extractor=Extractor.MANUAL,
        ),
        ceiling=ceiling,
        ceiling_rub=ceiling_rub,
        unit_quantity=unit_quantity,
        quantity_unit=quantity_unit,
        lot_ordinal=ordinal,
        currency=currency,
        blocking_reasons=blockers,
        source_schema_status=quality_status,
        source_price_kind=price_kind,
        source_reasons=reasons,
        estimate=estimate,
    )
