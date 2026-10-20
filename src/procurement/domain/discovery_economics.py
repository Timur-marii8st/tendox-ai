"""Preliminary economics for a discovered procurement opportunity.

The calculation is deliberately smaller than :mod:`procurement.domain.economics`.
It turns a published gross NMCK and a supplier's rough, explicitly acknowledged
cost estimate into three *estimates*.  It is never a complete commercial
proposal and never authorizes participation.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from procurement.domain.economics import money

EstimateStatus = Literal["ESTIMATE", "UNKNOWN", "BLOCKED"]
DiscoveryRecommendation = Literal["needs_analysis", "do_not_participate"]
DiscoveryScenarioKind = Literal["base", "realistic", "conservative"]

ZERO = Decimal("0")
ONE = Decimal("1")
MAX_MONEY = Decimal("1000000000000000000")
MAX_RATE_DECIMAL_PLACES = 6


class _UncomputableScenario(Exception):
    """A rounded preliminary scenario has no meaningful revenue to assess."""


def _finite_decimal(value: object, *, field_name: str) -> Decimal:
    """Accept a finite exact number, never a float or a boolean."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError(f"{field_name} must be Decimal, int, or str, never float")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _bounded_money(value: object, *, field_name: str) -> Decimal:
    """Validate a monetary input before rounding it to kopecks."""
    result = _finite_decimal(value, field_name=field_name)
    if abs(result) > MAX_MONEY:
        raise ValueError(f"{field_name} must not exceed {MAX_MONEY}")
    return money(result)


def _bounded_rate(value: object, *, field_name: str) -> Decimal:
    """Accept a bounded fraction with no more than six decimal places."""
    result = _finite_decimal(value, field_name=field_name)
    if abs(result) > ONE:
        raise ValueError(f"{field_name} must be between zero and one")
    exponent = result.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -MAX_RATE_DECIMAL_PLACES:
        raise ValueError(f"{field_name} must have at most {MAX_RATE_DECIMAL_PLACES} decimal places")
    return result


class DiscoveryCostInput(BaseModel):
    """Supplier's preliminary net cost estimate with explicit tax assumptions.

    ``expenses`` includes every non-goods net cost, including taxes other than
    output VAT.  ``costs_complete_ack`` records the supplier's acknowledgement
    that this two-line preliminary estimate includes all such known costs; it
    does not claim the detailed ``CostBreakdown`` required for a final decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    goods: Decimal = Field(ge=0, description="Whole lot goods cost, net of VAT")
    expenses: Decimal = Field(
        ge=0,
        description="All other net costs, including taxes except output VAT",
    )
    vat_rate: Decimal = Field(ge=0, le=1, description="Explicit output VAT rate")
    realistic_discount: Decimal = Field(default=Decimal("0.05"), ge=0, lt=1)
    conservative_discount: Decimal = Field(default=Decimal("0.10"), ge=0, lt=1)
    conservative_cost_growth: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)
    basis: str = Field(
        min_length=1,
        max_length=2000,
        description="Supplier/user source note for this estimate",
    )
    costs_complete_ack: StrictBool = Field(
        description="Supplier/user confirms the preliminary cost total includes known costs"
    )

    @field_validator("goods", "expenses", mode="before")
    @classmethod
    def _money_is_exact(cls, value: object) -> Decimal:
        return _bounded_money(value, field_name="money")

    @field_validator(
        "vat_rate",
        "realistic_discount",
        "conservative_discount",
        "conservative_cost_growth",
        mode="before",
    )
    @classmethod
    def _rate_is_exact(cls, value: object) -> Decimal:
        return _bounded_rate(value, field_name="rate")

    @field_validator("basis")
    @classmethod
    def _basis_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("basis must not be blank")
        return value

    @model_validator(mode="after")
    def _conservative_is_not_better_than_realistic(self) -> DiscoveryCostInput:
        if self.conservative_discount < self.realistic_discount:
            raise ValueError("conservative_discount must be at least realistic_discount")
        return self

    @property
    def costs_net(self) -> Decimal:
        """Total preliminary costs, without misrepresenting them as a detailed breakdown."""
        return money(self.goods + self.expenses)


class DiscoveryScenario(BaseModel):
    """One non-binding opportunity estimate under an explicit scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DiscoveryScenarioKind
    revenue_net: Decimal
    costs_net: Decimal
    profit: Decimal
    margin: Decimal
    assumptions: tuple[str, ...] = Field(min_length=1)
    break_even_gross: Decimal
    maximum_discount: Decimal
    basis: str


class DiscoveryEstimate(BaseModel):
    """Result of preliminary discovery economics, never a participation decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EstimateStatus
    recommendation: DiscoveryRecommendation
    scenarios: tuple[DiscoveryScenario, ...] = ()
    basis: str
    reasons: tuple[str, ...] = ()


def _scenario(
    *,
    kind: DiscoveryScenarioKind,
    nmck_gross: Decimal,
    costs: DiscoveryCostInput,
    discount: Decimal,
    cost_growth: Decimal,
    assumptions: tuple[str, ...],
) -> DiscoveryScenario:
    gross_revenue = money(nmck_gross * (ONE - discount))
    revenue_net = money(gross_revenue / (ONE + costs.vat_rate))
    if revenue_net <= ZERO:
        raise _UncomputableScenario
    costs_net = money(costs.costs_net * (ONE + cost_growth))
    profit = money(revenue_net - costs_net)
    margin = (profit / revenue_net).quantize(Decimal("0.0001"))
    break_even_gross = money(costs_net * (ONE + costs.vat_rate))
    maximum_discount = (ONE - (break_even_gross / nmck_gross)).quantize(Decimal("0.0001"))
    return DiscoveryScenario(
        kind=kind,
        revenue_net=revenue_net,
        costs_net=costs_net,
        profit=profit,
        margin=margin,
        assumptions=assumptions,
        break_even_gross=break_even_gross,
        maximum_discount=maximum_discount,
        basis=costs.basis,
    )


def calculate_discovery_economics(
    nmck: Decimal | None,
    costs: DiscoveryCostInput,
    *,
    blocked: bool = False,
) -> DiscoveryEstimate:
    """Estimate supplier opportunity economics from a published gross NMCK.

    Missing NMCK or an unacknowledged preliminary cost total remains ``UNKNOWN``.
    A blocked opportunity returns no scenarios.  Even an ``ESTIMATE`` only asks
    for further analysis; a complete quote and the final economics workflow are
    required before any participation recommendation.
    """
    nmck_gross: Decimal | None = None
    if nmck is not None:
        nmck_gross = _bounded_money(nmck, field_name="nmck")

    if blocked:
        return DiscoveryEstimate(
            status="BLOCKED",
            recommendation="do_not_participate",
            basis=costs.basis,
            reasons=(
                "Подача закрыта или закупка отменена; предварительная прибыль не рассчитывается.",
            ),
        )
    if nmck_gross is None or nmck_gross <= ZERO or not costs.costs_complete_ack:
        reasons = []
        if nmck_gross is None or nmck_gross <= ZERO:
            reasons.append("НМЦК не подтверждена положительной суммой в рублях.")
        if not costs.costs_complete_ack:
            reasons.append("Поставщик не подтвердил полноту известных расходов.")
        return DiscoveryEstimate(
            status="UNKNOWN",
            recommendation="needs_analysis",
            basis=costs.basis,
            reasons=tuple(reasons),
        )

    if nmck_gross is None:  # Narrowed above; this protects future control-flow edits.
        raise RuntimeError("nmck must be set for an estimate")

    try:
        scenarios = (
            _scenario(
                kind="base",
                nmck_gross=nmck_gross,
                costs=costs,
                discount=ZERO,
                cost_growth=ZERO,
                assumptions=("Опубликованная НМЦК без снижения цены.", "Рост затрат не заложен."),
            ),
            _scenario(
                kind="realistic",
                nmck_gross=nmck_gross,
                costs=costs,
                discount=costs.realistic_discount,
                cost_growth=ZERO,
                assumptions=(
                    f"Снижение цены: {costs.realistic_discount}.",
                    "Рост затрат не заложен.",
                ),
            ),
            _scenario(
                kind="conservative",
                nmck_gross=nmck_gross,
                costs=costs,
                discount=costs.conservative_discount,
                cost_growth=costs.conservative_cost_growth,
                assumptions=(
                    f"Снижение цены: {costs.conservative_discount}.",
                    f"Рост затрат: {costs.conservative_cost_growth}.",
                ),
            ),
        )
    except _UncomputableScenario:
        return DiscoveryEstimate(
            status="UNKNOWN",
            recommendation="needs_analysis",
            basis=costs.basis,
            reasons=("После сценарного снижения выручка не позволяет оценить маржу.",),
        )
    return DiscoveryEstimate(
        status="ESTIMATE",
        recommendation="needs_analysis",
        scenarios=scenarios,
        basis=costs.basis,
        reasons=(
            "Сравнение основано на опубликованной НМЦК и расходах, введённых поставщиком.",
            (
                "При заданных расходах консервативный сценарий убыточен."
                if scenarios[-1].profit < ZERO
                else "При заданных расходах консервативный сценарий не убыточен."
            ),
            "ТЗ, действительное полное КП, ограничения и результат торгов ещё не подтверждены.",
        ),
    )
