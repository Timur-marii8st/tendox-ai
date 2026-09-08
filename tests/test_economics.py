"""Тесты экономики сделки.

Инвариант домена №6: деньги — только Decimal, НДС отдельной ставкой. Тесты
здесь защищают от двух классов ошибок: потери расходов (маржа завышена) и
арифметики float (копейки расходятся с бухгалтерией).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.economics import (
    CostBreakdown,
    DealEconomics,
    EconomicsScenario,
    ScenarioKind,
    ScenarioSet,
    cost_of_money,
    money,
)


class TestMoney:
    def test_rounds_to_kopecks_half_up(self) -> None:
        assert money("1234.565") == Decimal("1234.57")
        assert money("1234.564") == Decimal("1234.56")

    def test_accepts_int_and_str(self) -> None:
        assert money(1000) == Decimal("1000.00")
        assert money("1000") == Decimal("1000.00")

    def test_result_is_always_two_places(self) -> None:
        assert str(money(Decimal(1))) == "1.00"

    @pytest.mark.parametrize("value", [1.0, True, "NaN", Decimal("Infinity")])
    def test_rejects_float_boolean_and_nonfinite_values(self, value: object) -> None:
        with pytest.raises(ValueError):
            money(value)  # type: ignore[arg-type]


class TestCostOfMoney:
    """Самый часто теряемый расход: предоплата производителю при постоплате заказчика."""

    def test_known_case(self) -> None:
        assert cost_of_money(Decimal("3710000"), Decimal("0.24"), 12) == Decimal("29273.42")

    def test_zero_gap_costs_nothing(self) -> None:
        assert cost_of_money(Decimal("3710000"), Decimal("0.24"), 0) == Decimal("0.00")

    def test_zero_prepayment_costs_nothing(self) -> None:
        assert cost_of_money(Decimal(0), Decimal("0.24"), 90) == Decimal("0.00")

    def test_longer_gap_costs_more(self) -> None:
        short = cost_of_money(Decimal("1000000"), Decimal("0.24"), 30)
        long = cost_of_money(Decimal("1000000"), Decimal("0.24"), 90)
        assert long > short

    def test_negative_inputs_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            cost_of_money(Decimal(-1), Decimal("0.24"), 30)
        with pytest.raises(ValueError):
            cost_of_money(Decimal(1000), Decimal("0.24"), -1)
        with pytest.raises(ValueError):
            cost_of_money(Decimal(1000), Decimal("-0.01"), 30)

    @pytest.mark.parametrize("value", [1.0, "NaN", Decimal("Infinity")])
    def test_rejects_non_decimal_monetary_inputs(self, value: object) -> None:
        with pytest.raises(ValueError):
            cost_of_money(value, Decimal("0.24"), 30)  # type: ignore[arg-type]


class TestCostBreakdown:
    def test_all_in_sums_every_component(self) -> None:
        costs = CostBreakdown(
            goods=Decimal("3710000"),
            logistics=Decimal("120000"),
            finance=Decimal("29273.42"),
            bank_guarantee=Decimal("48000"),
            platform_fees=Decimal("5000"),
            certification=Decimal("15000"),
            warranty=Decimal("60000"),
            other=Decimal("2500"),
        )
        assert costs.all_in == Decimal("3989773.42")

    def test_defaults_are_zero(self) -> None:
        costs = CostBreakdown(goods=Decimal("100"))
        assert costs.all_in == Decimal("100.00")
        assert costs.is_complete is False

    def test_all_explicit_zero_costs_are_complete(self) -> None:
        costs = CostBreakdown(**{field: Decimal(0) for field in CostBreakdown._cost_field_names})
        assert costs.is_complete is True

    def test_omitted_taxes_remain_unknown(self) -> None:
        values = {field: Decimal(0) for field in CostBreakdown._cost_field_names}
        del values["taxes"]
        assert CostBreakdown(**values).is_complete is False

    def test_omitted_costs_remain_incomplete_after_json_round_trip(self) -> None:
        costs = CostBreakdown(goods=Decimal("100"), logistics=Decimal(0))
        restored = CostBreakdown.model_validate_json(costs.model_dump_json())
        assert costs.is_complete is False
        assert restored.specified_cost_fields == ("goods", "logistics")
        assert restored.is_complete is False

    def test_negative_component_is_rejected(self) -> None:
        """Отрицательный расход — это скидка, её место в цене закупки, а не в расходах."""
        with pytest.raises(ValidationError):
            CostBreakdown(goods=Decimal("100"), logistics=Decimal("-10"))

    def test_lines_skip_zero_rows(self) -> None:
        costs = CostBreakdown(goods=Decimal("100"), logistics=Decimal("10"))
        labels = [label for label, _ in costs.lines()]
        assert labels == ["Закупка товара", "Доставка"]

    def test_lines_are_quantized(self) -> None:
        costs = CostBreakdown(goods=Decimal("100.005"))
        assert costs.lines()[0][1] == Decimal("100.01")

    @pytest.mark.parametrize("value", [1.0, "NaN", Decimal("Infinity"), True])
    def test_rejects_float_nonfinite_and_boolean_costs(self, value: object) -> None:
        with pytest.raises(ValidationError):
            CostBreakdown(goods=value)  # type: ignore[arg-type]


class TestDealEconomics:
    def _deal(self, revenue: str = "4800000") -> DealEconomics:
        return DealEconomics(
            contract_revenue=Decimal(revenue),
            costs=CostBreakdown(goods=Decimal("3710000"), logistics=Decimal("120000")),
        )

    def test_gross_profit(self) -> None:
        assert self._deal().gross_profit == Decimal("970000.00")

    def test_margin_is_share_of_revenue(self) -> None:
        assert self._deal().margin == Decimal("0.2021")

    def test_loss_is_visible_not_hidden(self) -> None:
        """Убыток должен быть отрицательным числом, а не нулём или ошибкой."""
        deal = self._deal(revenue="3500000")
        assert deal.gross_profit < 0
        assert deal.margin < 0
        assert deal.is_profitable is False

    def test_nds_rate_is_separate_field(self) -> None:
        """«НДС примерно включён» запрещено: ставка — отдельное поле."""
        assert self._deal().nds_rate is None
        assert self._deal().is_complete is False

    def test_known_nds_does_not_complete_omitted_costs(self) -> None:
        deal = DealEconomics(
            contract_revenue=Decimal("100"),
            costs=CostBreakdown(goods=Decimal("50")),
            nds_rate=Decimal("0.20"),
        )
        assert deal.is_complete is False

    def test_nds_rate_out_of_range_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DealEconomics(
                contract_revenue=Decimal("100"),
                costs=CostBreakdown(goods=Decimal("50")),
                nds_rate=Decimal("1.5"),
            )

    def test_zero_revenue_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DealEconomics(contract_revenue=Decimal(0), costs=CostBreakdown(goods=Decimal("50")))

    def test_report_lists_costs_and_margin(self) -> None:
        text = self._deal().report()
        assert "Контракт заказчика" in text
        assert "Закупка товара" in text
        assert "Прогноз прибыли" in text
        assert "%" in text
        assert "Банковская гарантия" not in text, "нулевые строки не показываем"

    def test_costs_are_never_float(self) -> None:
        deal = self._deal()
        assert isinstance(deal.gross_profit, Decimal)
        assert isinstance(deal.costs.all_in, Decimal)

    @pytest.mark.parametrize("value", [1.0, "NaN", Decimal("Infinity"), True])
    def test_rejects_float_nonfinite_and_boolean_deal_money(self, value: object) -> None:
        with pytest.raises(ValidationError):
            DealEconomics(
                contract_revenue=value,  # type: ignore[arg-type]
                costs=CostBreakdown(goods=Decimal("50")),
                nds_rate=Decimal("0.20"),
            )


class TestScenarioSetCompleteness:
    def test_requires_all_three_economics_to_be_complete(self) -> None:
        incomplete = DealEconomics(
            contract_revenue=Decimal("100"), costs=CostBreakdown(goods=Decimal("50"))
        )
        scenarios = ScenarioSet(
            scenarios=tuple(
                EconomicsScenario(
                    kind=kind,
                    economics=incomplete,
                    assumptions=("synthetic",),
                )
                for kind in ScenarioKind
            )
        )
        assert scenarios.is_complete is False
