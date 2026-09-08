"""Тесты моделей требований и позиции ТЗ.

Модель обязана отвергать бессмысленные требования на входе. Требование, которое
нельзя проверить, — это баг в парсере ТЗ, и он должен падать здесь, а не тихо
превращаться в UNKNOWN на глазах пользователя.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from conftest import TZ, line_item, req
from procurement.domain.requirements import LineItem, Operator, Requirement


class TestOperatorShape:
    """Форма значения должна соответствовать оператору."""

    def test_numeric_operator_requires_decimal(self) -> None:
        with pytest.raises(ValidationError):
            req("warranty", Operator.GE, "двадцать четыре", unit="мес")

    def test_exists_takes_no_value(self) -> None:
        with pytest.raises(ValidationError):
            req("rohs", Operator.EXISTS, "да")

    def test_exists_without_value_is_valid(self) -> None:
        assert req("rohs", Operator.EXISTS).value is None

    def test_between_requires_ordered_pair(self) -> None:
        with pytest.raises(ValidationError):
            req("depth", Operator.BETWEEN, (Decimal(400), Decimal(200)), unit="мм")

    def test_between_accepts_ordered_pair(self) -> None:
        r = req("depth", Operator.BETWEEN, (Decimal(200), Decimal(400)), unit="мм")
        assert r.value == (Decimal(200), Decimal(400))

    def test_in_requires_list(self) -> None:
        with pytest.raises(ValidationError):
            req("form_factor", Operator.IN, "1U")


class TestMandatoryWeight:
    """Обязательное требование нельзя «взвесить»: его провал фатален."""

    def test_mandatory_with_weight_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            req("warranty", Operator.GE, Decimal(24), unit="мес", weight=5)

    def test_desirable_may_have_weight(self) -> None:
        assert req("poe", Operator.EQ, "да", mandatory=False, weight=5).weight == 5


class TestProvenanceRequired:
    """Инвариант №1: требование без источника создать нельзя."""

    def test_requirement_without_provenance_fails(self) -> None:
        with pytest.raises(ValidationError):
            Requirement(  # type: ignore[call-arg]
                property="warranty",
                operator=Operator.GE,
                value=Decimal(24),
                raw_text="гарантия не менее 24 мес",
            )

    def test_label_mentions_operator_and_unit(self) -> None:
        r = req("warranty", Operator.GE, Decimal(24), unit="мес")
        assert r.label() == "warranty >= 24 мес"


class TestLineItem:
    def test_duplicate_requirement_property_is_rejected(self) -> None:
        """Один и тот же property с одним оператором дважды — ошибка извлечения ТЗ."""
        with pytest.raises(ValidationError):
            line_item(
                req("warranty", Operator.GE, Decimal(24), unit="мес"),
                req("warranty", Operator.GE, Decimal(36), unit="мес"),
            )

    def test_range_as_two_requirements_is_allowed(self) -> None:
        """«от 24 до 60 мес» законно раскладывается на GE и LE — это не дубль."""
        item = line_item(
            req("warranty", Operator.GE, Decimal(24), unit="мес"),
            req("warranty", Operator.LE, Decimal(60), unit="мес"),
        )
        assert len(item.requirements) == 2

    def test_mandatory_and_desirable_are_split(self) -> None:
        item = line_item(
            req("warranty", Operator.GE, Decimal(24), unit="мес"),
            req("poe", Operator.EQ, "да", mandatory=False),
        )
        assert [r.property for r in item.mandatory_requirements] == ["warranty"]
        assert [r.property for r in item.desirable_requirements] == ["poe"]

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            LineItem(
                number=1,
                name="Коммутатор",
                quantity=Decimal(0),
                requirements=(),
                provenance=TZ,
            )

    def test_delivery_deadline_is_optional(self) -> None:
        assert line_item(delivery_deadline=None).delivery_deadline is None
        item = line_item(delivery_deadline=date(2026, 12, 1))
        assert item.delivery_deadline == date(2026, 12, 1)

    def test_model_is_frozen(self) -> None:
        """Позиция ТЗ неизменяема: правка требования — это новая версия дела."""
        item = line_item()
        with pytest.raises(ValidationError):
            item.name = "Другой товар"  # type: ignore[misc]
