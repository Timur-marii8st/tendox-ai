from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    calculate_discovery_economics,
)


def costs(**changes: object) -> DiscoveryCostInput:
    values: dict[str, object] = {
        "goods": Decimal("600.00"),
        "expenses": Decimal("100.00"),
        "vat_rate": Decimal("0.20"),
        "realistic_discount": Decimal("0.05"),
        "conservative_discount": Decimal("0.10"),
        "conservative_cost_growth": Decimal("0.10"),
        "basis": "Supplier email of 2026-09-26",
        "costs_complete_ack": True,
    }
    values.update(changes)
    return DiscoveryCostInput(**values)


@pytest.mark.parametrize("field", ["goods", "expenses", "vat_rate"])
@pytest.mark.parametrize("value", [1.0, True, "NaN", Decimal("Infinity")])
def test_rejects_inexact_or_nonfinite_numbers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        costs(**{field: value})


def test_missing_nmck_is_unknown() -> None:
    result = calculate_discovery_economics(None, costs())

    assert result.status == "UNKNOWN"
    assert result.recommendation == "needs_analysis"
    assert result.scenarios == ()
    assert any("НМЦК" in reason for reason in result.reasons)


def test_zero_nmck_is_unavailable_and_remains_unknown() -> None:
    result = calculate_discovery_economics(Decimal("0"), costs())

    assert result.status == "UNKNOWN"
    assert result.scenarios == ()
    assert any("НМЦК" in reason for reason in result.reasons)


def test_cost_acknowledgement_is_required_to_calculate() -> None:
    result = calculate_discovery_economics(Decimal("1200"), costs(costs_complete_ack=False))

    assert result.status == "UNKNOWN"
    assert result.scenarios == ()
    assert any("полноту" in reason for reason in result.reasons)


def test_discount_ordering_is_enforced() -> None:
    with pytest.raises(ValidationError, match="conservative_discount"):
        costs(realistic_discount=Decimal("0.11"), conservative_discount=Decimal("0.10"))


def test_tiny_revenue_after_discount_remains_unknown_instead_of_dividing_by_zero() -> None:
    result = calculate_discovery_economics(
        Decimal("0.01"),
        costs(
            realistic_discount=Decimal("0.999999"),
            conservative_discount=Decimal("0.999999"),
        ),
    )

    assert result.status == "UNKNOWN"
    assert result.scenarios == ()


@pytest.mark.parametrize("value", ["1e9999", Decimal("1000000000000000000.01")])
def test_rejects_unbounded_monetary_values(value: object) -> None:
    with pytest.raises(ValidationError):
        costs(goods=value)


def test_rejects_unbounded_nmck_before_any_calculation() -> None:
    with pytest.raises(ValueError, match="nmck"):
        calculate_discovery_economics(Decimal("1e9999"), costs())


def test_rates_are_limited_to_six_decimal_places() -> None:
    with pytest.raises(ValidationError, match="decimal places"):
        costs(vat_rate=Decimal("0.1234567"))


@pytest.mark.parametrize("value", ["true", 1, 0])
def test_acknowledgement_is_a_strict_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        costs(costs_complete_ack=value)


def test_basis_is_bounded_and_unknown_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        costs(basis="x" * 2001)
    with pytest.raises(ValidationError):
        DiscoveryCostInput(**costs().model_dump(), unexpected="value")


def test_negative_profit_and_negative_maximum_discount_are_visible() -> None:
    result = calculate_discovery_economics(Decimal("600"), costs())
    base = result.scenarios[0]

    assert base.profit == Decimal("-200.00")
    assert base.maximum_discount == Decimal("-0.4000")
    assert result.recommendation == "needs_analysis"
    assert any("КП" in reason for reason in result.reasons)
    assert any("убыточен" in reason for reason in result.reasons)


def test_vat_rate_reduces_net_revenue_for_the_same_gross_nmck() -> None:
    no_vat = calculate_discovery_economics(Decimal("1200"), costs(vat_rate=Decimal("0")))
    vat = calculate_discovery_economics(Decimal("1200"), costs(vat_rate=Decimal("0.20")))

    assert vat.scenarios[0].revenue_net < no_vat.scenarios[0].revenue_net
    assert vat.scenarios[0].profit < no_vat.scenarios[0].profit


def test_blocked_opportunity_has_no_scenario_or_ranked_profit() -> None:
    result = calculate_discovery_economics(Decimal("1200"), costs(), blocked=True)

    assert result.status == "BLOCKED"
    assert result.recommendation == "do_not_participate"
    assert result.scenarios == ()
    assert any("закрыта" in reason for reason in result.reasons)
