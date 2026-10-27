"""Bounded financial ordering with the selected profile; qualification remains separate."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from procurement.domain.company_profile_snapshot import CompanyProfileSnapshot
from procurement.sources.tender_navigation import region_name_key
from procurement.storage.beta_quote import BetaQuoteRef, BetaQuoteReport, quote_report
from procurement.storage.company_profile import ProfileNotFound, read_profile, read_selection
from procurement.storage.repository import PostgresStorage
from procurement.storage.tender_navigation import read_navigation


class BetaShortlistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notices: tuple[BetaQuoteRef, ...] = Field(min_length=1, max_length=20)
    region: str = Field(default="", max_length=200)
    ranking: Literal["TOTAL_PROFIT", "UNIT_PROFIT"] = "TOTAL_PROFIT"


class BetaFinancialRow(BaseModel):
    report: BetaQuoteReport
    profile_status: Literal["FAIL", "UNKNOWN"] = "UNKNOWN"
    reasons: tuple[str, ...] = ()
    financial_position: int | None = None
    unit_profit: Decimal | None = None


class UnitFinancialOrder(BaseModel):
    unit: str
    record_ids: tuple[str, ...]


class BetaShortlist(BaseModel):
    checked_at: datetime
    profile: CompanyProfileSnapshot | None
    rows: tuple[BetaFinancialRow, ...]
    financial_order: tuple[str, ...]
    ranking: Literal["TOTAL_PROFIT", "UNIT_PROFIT"] = "TOTAL_PROFIT"
    unit_orders: tuple[UnitFinancialOrder, ...] = ()
    scope: Literal["LOADED_SELECTED_NOTICES_MAX20"] = "LOADED_SELECTED_NOTICES_MAX20"
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"


def shortlist(
    storage: PostgresStorage,
    company: str,
    request: BetaShortlistRequest,
    *,
    actor: str,
    now: datetime | None = None,
    source_company: str | None = None,
) -> BetaShortlist:
    """Order up to five positive conservative calculations; never issue PARTICIPATE."""
    at = now or datetime.now(UTC)
    try:
        selection = read_selection(storage, company)
        profile = read_profile(storage, company, selection.profile_ref.version)
        if profile.snapshot_sha256 != selection.profile_ref.snapshot_sha256:
            raise ValueError("PROFILE_SELECTION_CHANGED")
    except ProfileNotFound:
        profile = None
    rows = []
    order: list[tuple[Decimal, Decimal, str]] = []
    seen: set[tuple[str, str, int | None]] = set()
    unit_by_id: dict[str, str] = {}

    def normalize(value: str) -> tuple[str, ...]:
        return region_name_key(value)

    for ref in request.notices:
        identity = (ref.notice.law, ref.notice.purchase_number, ref.lot_index)
        if identity in seen:
            raise ValueError("DUPLICATE_SHORTLIST_NOTICE")
        seen.add(identity)
        report = quote_report(
            storage, company, ref, actor=actor, now=at, source_company=source_company
        )
        reasons: list[str] = []
        failed = False
        excluded = False
        unit_profit = None
        calculation = report.calculation
        if profile is None:
            reasons.append("SELECTED_PROFILE_MISSING")
        if calculation and calculation.status == "CALCULATED":
            realistic = next(s for s in calculation.scenarios if s.kind == "realistic")
            conservative = next(s for s in calculation.scenarios if s.kind == "conservative")
            if profile:
                checks = {
                    "min_contract_amount": realistic.revenue_net,
                    "max_contract_amount": realistic.revenue_net,
                    "min_margin": realistic.profit,
                    "min_expected_profit": realistic.profit,
                }
                for key, actual in checks.items():
                    fact = profile.facts[f"finance.{key}"]
                    if fact.knowledge != "KNOWN":
                        reasons.append(f"PROFILE_{key.upper()}_UNKNOWN")
                    else:
                        limit = Decimal(str(fact.value))
                        if key == "min_margin":
                            # Compare exact money; scenario.margin is rounded for display.
                            limit *= realistic.revenue_net
                        if actual > limit if key.startswith("max") else actual < limit:
                            failed = True
                            reasons.append(f"PROFILE_{key.upper()}_FAIL")
            if request.region or profile:
                navigation = read_navigation(storage, source_company or company, ref.notice)
                regions = {normalize(f.value) for f in navigation.delivery_regions}
                if request.region and normalize(request.region) not in regions:
                    excluded = True
                    reasons.append("SELECTED_DELIVERY_REGION_NOT_CONFIRMED")
                if profile:
                    all_russia = profile.facts["geography.all_russia"]
                    allowed = profile.facts["geography.regions"]
                    if all_russia.knowledge == "KNOWN" and all_russia.value is True:
                        pass
                    elif allowed.knowledge == "KNOWN" and isinstance(allowed.value, tuple):
                        if regions and not regions <= {normalize(r) for r in allowed.value}:
                            failed = True
                            reasons.append("PROFILE_DELIVERY_REGION_FAIL")
                        elif not regions:
                            reasons.append("PROFILE_DELIVERY_REGION_UNKNOWN")
                    else:
                        reasons.append("PROFILE_DELIVERY_REGION_UNKNOWN")
            if conservative.profit <= 0:
                excluded = True
                reasons.append("CONSERVATIVE_NOT_PROFITABLE")
            basis, unit = report.unit_quantity, report.quantity_unit
            valid_basis = (
                basis is not None
                and basis.value is not None
                and basis.value.is_finite()
                and basis.value > 0
                and unit is not None
                and bool((unit.value or "").strip())
                and basis.provenance.document_id == ref.notice.notice_xml_sha256
                and unit.provenance.document_id == ref.notice.notice_xml_sha256
            )
            if valid_basis:
                unit_profit = conservative.profit / basis.value
            if request.ranking == "UNIT_PROFIT" and unit_profit is None:
                excluded = True
                reasons.append("UNIT_PROFIT_BASIS_UNKNOWN")
            if not failed and not excluded and profile is not None:
                record_id = report.record_id or ""
                if request.ranking == "UNIT_PROFIT":
                    unit_by_id[record_id] = " ".join(unit.value.casefold().split())
                value = unit_profit if request.ranking == "UNIT_PROFIT" else conservative.profit
                order.append((value, conservative.profit / conservative.revenue_net, record_id))
        # This is a financial comparison, not a hard-gate rating or recommendation.
        reasons.append("TECHNICAL_LEGAL_AND_FULL_PROFILE_REVIEW_REQUIRED")
        rows.append(
            BetaFinancialRow(
                report=report,
                profile_status="FAIL" if failed else "UNKNOWN",
                reasons=tuple(reasons),
                unit_profit=unit_profit,
            )
        )
    unique_purchases: set[tuple[str, str, str]] = set()
    grouped: dict[str, list[str]] = {}
    chosen: list[str] = []
    ref_by_id = {row.report.record_id: row.report.ref.notice for row in rows}
    for _, _, record_id in sorted(order, key=lambda x: (-x[0], -x[1], x[2])):
        notice = ref_by_id[record_id]
        group = unit_by_id.get(record_id, "")
        purchase = (group, notice.law, notice.purchase_number)
        if purchase in unique_purchases:
            continue
        bucket = grouped.setdefault(group, [])
        if len(bucket) >= 5:
            continue
        unique_purchases.add(purchase)
        bucket.append(record_id)
        chosen.append(record_id)
    ordered = tuple(chosen) if request.ranking == "TOTAL_PROFIT" else ()
    positions_by_id = {
        record_id: i + 1 for ids in grouped.values() for i, record_id in enumerate(ids)
    }
    rows = [
        row.model_copy(update={"financial_position": positions_by_id[row.report.record_id]})
        if row.report.record_id in positions_by_id
        else row
        for row in rows
    ]
    return BetaShortlist(
        checked_at=at,
        profile=profile,
        rows=tuple(rows),
        financial_order=ordered,
        ranking=request.ranking,
        unit_orders=tuple(
            UnitFinancialOrder(unit=unit, record_ids=tuple(grouped[unit]))
            for unit in sorted(grouped)
            if unit
        ),
    )
