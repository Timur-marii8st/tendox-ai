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


class BetaFinancialRow(BaseModel):
    report: BetaQuoteReport
    profile_status: Literal["FAIL", "UNKNOWN"] = "UNKNOWN"
    reasons: tuple[str, ...] = ()
    financial_position: int | None = None


class BetaShortlist(BaseModel):
    checked_at: datetime
    profile: CompanyProfileSnapshot | None
    rows: tuple[BetaFinancialRow, ...]
    financial_order: tuple[str, ...]
    scope: Literal["LOADED_SELECTED_NOTICES_MAX20"] = "LOADED_SELECTED_NOTICES_MAX20"
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"


def shortlist(
    storage: PostgresStorage,
    company: str,
    request: BetaShortlistRequest,
    *,
    actor: str,
    now: datetime | None = None,
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

    def normalize(value: str) -> tuple[str, ...]:
        return region_name_key(value)

    for ref in request.notices:
        identity = (ref.notice.law, ref.notice.purchase_number, ref.lot_index)
        if identity in seen:
            raise ValueError("DUPLICATE_SHORTLIST_NOTICE")
        seen.add(identity)
        report = quote_report(storage, company, ref, actor=actor, now=at)
        reasons: list[str] = []
        failed = False
        excluded = False
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
                navigation = read_navigation(storage, company, ref.notice)
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
            if not failed and not excluded and profile is not None:
                order.append((conservative.profit, conservative.margin, report.record_id or ""))
        # This is a financial comparison, not a hard-gate rating or recommendation.
        reasons.append("TECHNICAL_LEGAL_AND_FULL_PROFILE_REVIEW_REQUIRED")
        rows.append(
            BetaFinancialRow(
                report=report,
                profile_status="FAIL" if failed else "UNKNOWN",
                reasons=tuple(reasons),
            )
        )
    unique_purchases: set[tuple[str, str]] = set()
    chosen: list[str] = []
    ref_by_id = {row.report.record_id: row.report.ref.notice for row in rows}
    for _, _, record_id in sorted(order, key=lambda x: (-x[0], -x[1], x[2])):
        notice = ref_by_id[record_id]
        purchase = (notice.law, notice.purchase_number)
        if purchase in unique_purchases:
            continue
        unique_purchases.add(purchase)
        chosen.append(record_id)
        if len(chosen) == 5:
            break
    ordered = tuple(chosen)
    rows = [
        row.model_copy(update={"financial_position": ordered.index(row.report.record_id) + 1})
        if row.report.record_id in ordered
        else row
        for row in rows
    ]
    return BetaShortlist(checked_at=at, profile=profile, rows=tuple(rows), financial_order=ordered)
