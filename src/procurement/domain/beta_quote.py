"""Quote-backed beta financial comparison; never a participation decision."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    DiscoveryScenario,
    _bounded_money,
    _bounded_rate,
    calculate_discovery_economics,
)
from procurement.domain.economics import COST_FIELD_NAMES, CostBreakdown
from procurement.domain.provenance import Provenance
from procurement.domain.quotes import Quote
from procurement.domain.regional_discount import (
    RegionalDiscountReport,
    RegionalHistory,
    regional_discount,
)


class BetaQuoteInput(BaseModel):
    """Manual source declaration; tenant, actor and provenance are server-bound."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)
    supplier: str = Field(min_length=1, max_length=300)
    document: str = Field(min_length=1, max_length=500)
    locator: str = Field(min_length=1, max_length=500)
    amount_ex_vat: Decimal = Field(gt=0)
    quote_vat_rate: Decimal = Field(ge=0, le=1)
    issued_at: datetime
    valid_until: datetime
    covers_full_scope: StrictBool
    availability_terms: str = Field(min_length=1, max_length=1000)
    delivery_terms: str = Field(min_length=1, max_length=1000)
    payment_terms: str = Field(min_length=1, max_length=1000)
    # Missing keys stay missing. Explicit zero is a user's declaration.
    expenses: dict[str, Decimal] = Field(max_length=17)
    expense_basis: str = Field(min_length=1, max_length=2000)
    tax_model: str = Field(min_length=1, max_length=300)
    output_vat_rate: Decimal = Field(ge=0, le=1)
    realistic_discount: Decimal = Field(ge=0, lt=1)
    conservative_discount: Decimal = Field(ge=0, lt=1)
    conservative_cost_growth: Decimal = Field(ge=0, le=1)
    discount_mode: Literal["MANUAL", "REGIONAL"] = "MANUAL"

    @field_validator("amount_ex_vat", mode="before")
    @classmethod
    def exact_amount(cls, value: object) -> Decimal:
        return _bounded_money(value, field_name="quote")

    @field_validator(
        "quote_vat_rate",
        "output_vat_rate",
        "realistic_discount",
        "conservative_discount",
        "conservative_cost_growth",
        mode="before",
    )
    @classmethod
    def exact_rate(cls, value: object) -> Decimal:
        return _bounded_rate(value, field_name="rate")

    @field_validator("expenses", mode="before")
    @classmethod
    def exact_expenses(cls, value: object) -> dict[str, Decimal]:
        if not isinstance(value, dict) or set(value) - (set(COST_FIELD_NAMES) - {"goods"}):
            raise ValueError("EXPENSE_FIELDS_INVALID")
        result = {key: _bounded_money(amount, field_name=key) for key, amount in value.items()}
        if any(amount < 0 for amount in result.values()):
            raise ValueError("EXPENSE_NEGATIVE")
        return result

    @model_validator(mode="after")
    def valid_terms(self) -> BetaQuoteInput:
        for moment in (self.issued_at, self.valid_until):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("QUOTE_TIMEZONE_REQUIRED")
        if self.valid_until <= self.issued_at:
            raise ValueError("QUOTE_VALIDITY_INVALID")
        if self.conservative_discount < self.realistic_discount:
            raise ValueError("CONSERVATIVE_DISCOUNT_INVALID")
        return self


class BetaQuoteCalculation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["CALCULATED", "UNKNOWN", "BLOCKED"]
    checked_at: datetime
    quote: Quote
    costs: CostBreakdown
    expense_source: Provenance
    tax_model: str
    scenarios: tuple[DiscoveryScenario, ...] = ()
    reasons: tuple[str, ...] = ()
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    regional_discount: RegionalDiscountReport | None = None
    discount_basis: Literal["MANUAL", "REGIONAL_HISTORY"] = "MANUAL"


def calculate_quote(
    data: BetaQuoteInput,
    *,
    company: str,
    tender_id: str,
    quote_id: str,
    quote_source: Provenance,
    expense_source: Provenance,
    nmck_gross: Decimal | None,
    deadline: datetime | None,
    blocked: bool,
    now: datetime,
    regional_history: RegionalHistory | None = None,
    revenue_source: Provenance | None = None,
) -> BetaQuoteCalculation:
    """Recheck quote validity and complete costs at every read before computing scenarios."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_NOW_REQUIRED")
    quote = Quote(
        quote_id=quote_id,
        version=1,
        company_id=company,
        tender_id=tender_id,
        supplier_id=data.supplier,
        amount_ex_vat=data.amount_ex_vat,
        nds_rate=data.quote_vat_rate,
        currency="RUB",
        issued_at=data.issued_at,
        valid_until=data.valid_until,
        source=quote_source,
        covers_full_scope=data.covers_full_scope,
        availability_terms=data.availability_terms,
        delivery_terms=data.delivery_terms,
        payment_terms=data.payment_terms,
    )
    costs = CostBreakdown(goods=data.amount_ex_vat, **data.expenses)
    reasons: list[str] = []
    history_report = None
    realistic_discount = data.realistic_discount
    conservative_discount = data.conservative_discount
    history_basis = ""
    if regional_history is not None:
        cohort = regional_history.cohort
        if cohort.company_id != company or cohort.target_id != tender_id:
            raise ValueError("HISTORY_TARGET_CONTEXT_MISMATCH")
        history_report = regional_discount(regional_history, now=now)
    if blocked or (deadline is not None and deadline <= now):
        status = "BLOCKED"
        reasons.append("PROCEDURE_BLOCKED_OR_EXPIRED")
    else:
        status = "UNKNOWN"
        if deadline is None:
            reasons.append("DEADLINE_UNKNOWN")
        if not quote.is_complete or not quote.is_valid_at(now):
            reasons.append("QUOTE_INCOMPLETE_OR_NOT_VALID")
        if not costs.is_complete:
            reasons.append("EXPENSES_INCOMPLETE")
        if nmck_gross is None:
            reasons.append("SOURCE_REVENUE_UNKNOWN")
        if data.discount_mode == "REGIONAL" and history_report is None:
            reasons.append("REGIONAL_HISTORY_UNKNOWN")
        if history_report is not None:
            if revenue_source is None or history_report.cohort.source != revenue_source:
                reasons.append("REGIONAL_HISTORY_REVENUE_SOURCE_MISMATCH")
            elif history_report.status != "PASS":
                reasons.append("REGIONAL_HISTORY_UNKNOWN")
            else:
                assert history_report.realistic_discount is not None
                assert history_report.conservative_discount is not None
                realistic_discount = max(realistic_discount, history_report.realistic_discount)
                conservative_discount = max(
                    conservative_discount,
                    realistic_discount,
                    history_report.conservative_discount,
                )
                history_basis = (
                    f"; региональная история {history_report.policy}: "
                    f"{history_report.cohort.region}, {history_report.sample_size} закупок, "
                    f"{history_report.cohort.period_start.isoformat()} — "
                    f"{history_report.cohort.period_end.isoformat()}; "
                    f"снижение {realistic_discount}/{conservative_discount}, "
                    "max(ручное, nearest-rank median/p75); сценарное допущение, "
                    "не вероятность победы и не гарантия консервативности"
                )
    scenarios: tuple[DiscoveryScenario, ...] = ()
    if not reasons:
        estimate = calculate_discovery_economics(
            nmck=nmck_gross,
            costs=DiscoveryCostInput(
                goods=data.amount_ex_vat,
                expenses=sum(data.expenses.values(), Decimal("0")),
                vat_rate=data.output_vat_rate,
                realistic_discount=realistic_discount,
                conservative_discount=conservative_discount,
                conservative_cost_growth=data.conservative_cost_growth,
                basis=(
                    f"КП {data.document}; расходы: {data.expense_basis}; налоги: {data.tax_model}"
                    if not history_basis
                    else f"КП {quote_id}; расходы: см. expense_source; налоги: {data.tax_model}"
                    + history_basis
                ),
                costs_complete_ack=True,
            ),
        )
        scenarios = estimate.scenarios
        status = "CALCULATED" if len(scenarios) == 3 else "UNKNOWN"
        reasons.extend(estimate.reasons)
    return BetaQuoteCalculation(
        status=status,
        checked_at=now,
        quote=quote,
        costs=costs,
        expense_source=expense_source,
        tax_model=data.tax_model,
        scenarios=scenarios,
        reasons=tuple(reasons),
        regional_discount=history_report,
        discount_basis="REGIONAL_HISTORY" if regional_history is not None else "MANUAL",
    )
