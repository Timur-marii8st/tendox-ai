"""Quote-backed beta calculations; source gates and tenant are always server-derived."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import insert, select

from procurement.domain.actions import payload_digest
from procurement.domain.beta_quote import BetaQuoteCalculation, BetaQuoteInput, calculate_quote
from procurement.domain.discovery_economics import DiscoveryCostInput
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_223_policy import deadline223
from procurement.storage.beta_quote_schema import beta_quote_records as records
from procurement.storage.eis_mixed_comparison import MixedNoticeRef
from procurement.storage.eis_source_estimate import SourceEstimateRequest, get_source_estimate
from procurement.storage.models import audit_events, eis_223_notice_versions, eis_notice_versions
from procurement.storage.repository import PostgresStorage


class BetaQuoteRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    notice: MixedNoticeRef
    lot_index: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def law_lot(self) -> BetaQuoteRef:
        if (self.notice.law == "223") != (self.lot_index is not None):
            raise ValueError("EXPLICIT_223_LOT_REQUIRED")
        return self


class BetaQuoteCommand(BetaQuoteRef):
    record_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    quote: BetaQuoteInput


class BetaQuoteReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ref: BetaQuoteRef
    record_id: str | None = None
    input: BetaQuoteInput | None = None
    calculation: BetaQuoteCalculation | None = None
    source_reasons: tuple[str, ...] = ()
    revenue_source: Provenance | None = None
    source_status: Literal["CHECKED", "NO_QUOTE"]
    declaration_kind: Literal["USER_DECLARED_QUOTE_AND_COSTS"] = "USER_DECLARED_QUOTE_AND_COSTS"


def quote_report(
    storage: PostgresStorage,
    company: str,
    ref: BetaQuoteRef,
    *,
    actor: str,
    command: BetaQuoteCommand | None = None,
    now: datetime | None = None,
) -> BetaQuoteReport:
    """Save immutable declarations, or recompute latest saved quote on current source gates."""
    at = now or datetime.now(UTC)
    r = ref.notice
    identity = (
        records.c.company_id == company,
        records.c.law == r.law,
        records.c.purchase_number == r.purchase_number,
        records.c.version_number == r.version_number,
        records.c.xml_sha256 == r.notice_xml_sha256,
        records.c.lot_index == (ref.lot_index or 0),
    )
    row = None
    with storage.transaction(company, consistent_read=True) as conn:
        row = (
            conn.execute(
                select(records)
                .where(*identity)
                .order_by(records.c.created_at.desc(), records.c.record_id.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
    if command is None and row is None:
        return BetaQuoteReport(ref=ref, source_status="NO_QUOTE")
    data = command.quote if command else BetaQuoteInput.model_validate(row["payload"])
    if (
        row is not None
        and command is None
        and payload_digest(row["payload"]) != row["payload_sha256"]
    ):
        raise ValueError("QUOTE_PAYLOAD_DIGEST")
    costs = DiscoveryCostInput(
        goods=data.amount_ex_vat,
        expenses=sum(data.expenses.values(), Decimal("0")),
        vat_rate=data.output_vat_rate,
        realistic_discount=data.realistic_discount,
        conservative_discount=data.conservative_discount,
        conservative_cost_growth=data.conservative_cost_growth,
        basis=data.expense_basis,
        costs_complete_ack=False,
    )
    source = get_source_estimate(
        storage,
        company,
        SourceEstimateRequest(notice=r, lot_index=ref.lot_index, costs=costs),
        actor_id=actor,
        now=at,
    )
    with storage.transaction(company, consistent_read=True) as conn:
        n = eis_notice_versions if r.law == "44" else eis_223_notice_versions
        notice = (
            conn.execute(
                select(n).where(
                    n.c.company_id == company,
                    n.c.purchase_number == r.purchase_number,
                    n.c.version_number == r.version_number,
                    n.c.xml_sha256 == r.notice_xml_sha256,
                )
            )
            .mappings()
            .one()
        )
        deadline = (
            notice["deadline"]
            if r.law == "44"
            else deadline223(Eis223NoticeSnapshot.model_validate(notice["snapshot"])).value
        )
    record_id = command.record_id if command else row["record_id"]
    declaration = Provenance(
        document_id=f"beta-quote:{company}:{record_id}",
        locator=f"{data.document} · {data.locator}",
        extractor=Extractor.MANUAL,
    )
    expense_source = Provenance(
        document_id=declaration.document_id,
        locator=f"expenses: {data.expense_basis}",
        extractor=Extractor.MANUAL,
    )
    calculation = calculate_quote(
        data,
        company=company,
        tender_id=f"{r.law}:{r.purchase_number}:{ref.lot_index or 0}",
        quote_id=record_id,
        quote_source=declaration,
        expense_source=expense_source,
        nmck_gross=(
            source.ceiling_rub
            if r.law == "44" or source.source_price_kind == "INITIAL_SUM"
            else None
        ),
        deadline=deadline,
        blocked=bool(source.blocking_reasons) or source.source_schema_status == "FAIL",
        now=at,
    )
    if command is not None:
        payload = data.model_dump(mode="json")
        digest = payload_digest(payload)
        with storage.transaction(company) as conn:
            existing = (
                conn.execute(
                    select(records).where(
                        records.c.company_id == company, records.c.record_id == record_id
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["payload_sha256"] != digest or any(
                    existing[name] != value
                    for name, value in {
                        "law": r.law,
                        "purchase_number": r.purchase_number,
                        "version_number": r.version_number,
                        "xml_sha256": r.notice_xml_sha256,
                        "lot_index": ref.lot_index or 0,
                    }.items()
                ):
                    raise ValueError("QUOTE_IDEMPOTENCY_CONFLICT")
            else:
                audit_id = str(uuid4())
                conn.execute(
                    insert(audit_events).values(
                        company_id=company,
                        event_id=audit_id,
                        actor_id=actor,
                        event_type="beta_quote_declared",
                        object_type="beta_quote",
                        object_id=record_id,
                        object_version=1,
                        occurred_at=at,
                        basis={"ref": ref.model_dump(mode="json"), "payload_sha256": digest},
                    )
                )
                conn.execute(
                    insert(records).values(
                        company_id=company,
                        record_id=record_id,
                        law=r.law,
                        purchase_number=r.purchase_number,
                        version_number=r.version_number,
                        xml_sha256=r.notice_xml_sha256,
                        lot_index=ref.lot_index or 0,
                        payload=payload,
                        payload_sha256=digest,
                        created_by=actor,
                        created_at=at,
                        audit_event_id=audit_id,
                    )
                )
    return BetaQuoteReport(
        ref=ref,
        record_id=record_id,
        input=data,
        calculation=calculation,
        source_reasons=source.blocking_reasons + source.source_reasons,
        revenue_source=source.ceiling.provenance,
        source_status="CHECKED",
    )
