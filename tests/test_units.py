"""Тесты нормализации единиц измерения.

Инвариант домена №5. Главная ловушка домена зафиксирована в
`TestCalendarVersusDays`: календарные сроки нельзя сводить к суткам.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from procurement.domain.units import Dimension, Quantity, resolve_unit


class TestResolveUnit:
    """Синонимы и регистр не должны приводить к «единица не распознана»."""

    @pytest.mark.parametrize(
        ("raw", "symbol"),
        [
            ("мес", "мес"),
            ("МЕС", "мес"),
            (" месяцев ", "мес"),
            ("года", "год"),
            ("лет", "год"),
            ("мм", "мм"),
            ("см", "см"),
            ("Гбит/с", "Гбит/с"),
            ("шт", "шт"),
        ],
    )
    def test_known_aliases(self, raw: str, symbol: str) -> None:
        unit = resolve_unit(raw)
        assert unit is not None
        assert unit.symbol == symbol

    @pytest.mark.parametrize("raw", ["попугаев", "", "   ", "мегапарсек"])
    def test_unknown_returns_none(self, raw: str) -> None:
        """Нераспознанная единица даёт None, а не «наиболее похожую»."""
        assert resolve_unit(raw) is None


class TestCanonicalValues:
    def test_length_to_millimetres(self) -> None:
        q = Quantity.parse(Decimal(30), "см")
        assert q is not None
        assert q.canonical == Decimal(300)

    def test_mass_to_grams(self) -> None:
        q = Quantity.parse(Decimal("1.5"), "кг")
        assert q is not None
        assert q.canonical == Decimal(1500)

    def test_data_rate_to_megabits(self) -> None:
        q = Quantity.parse(Decimal(10), "Гбит/с")
        assert q is not None
        assert q.canonical == Decimal(10000)

    def test_canonical_is_decimal_not_float(self) -> None:
        """Инвариант №6 распространяется и на единицы: никакого float."""
        q = Quantity.parse(Decimal("0.1"), "м")
        assert q is not None
        assert isinstance(q.canonical, Decimal)
        assert q.canonical == Decimal(100)

    def test_raw_unit_is_preserved(self) -> None:
        """Исходное написание сохраняется — его показываем пользователю."""
        q = Quantity.parse(Decimal(2), " ГОДА ")
        assert q is not None
        assert q.raw_unit == " ГОДА "

    def test_parse_unknown_unit_returns_none(self) -> None:
        assert Quantity.parse(Decimal(1), "попугаев") is None


class TestCalendarVersusDays:
    """Календарные и суточные сроки — разные величины, и это сделано намеренно."""

    def test_two_years_equals_twenty_four_months(self) -> None:
        years = Quantity.parse(Decimal(2), "года")
        months = Quantity.parse(Decimal(24), "мес")
        assert years is not None and months is not None
        assert years.canonical == months.canonical

    def test_quarter_is_three_months(self) -> None:
        q = Quantity.parse(Decimal(2), "кв")
        assert q is not None
        assert q.canonical == Decimal(6)

    def test_days_not_comparable_with_months(self) -> None:
        """730 дн против 24 мес: сведение к 30 дням дало бы ложный FAIL."""
        days = Quantity.parse(Decimal(730), "дн")
        months = Quantity.parse(Decimal(24), "мес")
        assert days is not None and months is not None
        assert days.dimension is Dimension.DURATION_DAYS
        assert months.dimension is Dimension.DURATION_CALENDAR
        assert not days.comparable_with(months)

    def test_weeks_are_days(self) -> None:
        weeks = Quantity.parse(Decimal(2), "нед")
        days = Quantity.parse(Decimal(14), "дн")
        assert weeks is not None and days is not None
        assert weeks.comparable_with(days)
        assert weeks.canonical == days.canonical


class TestComparability:
    def test_same_dimension_is_comparable(self) -> None:
        mm = Quantity.parse(Decimal(1000), "мм")
        m = Quantity.parse(Decimal(1), "м")
        assert mm is not None and m is not None
        assert mm.comparable_with(m)
        assert mm.canonical == m.canonical

    def test_different_dimensions_are_not(self) -> None:
        length = Quantity.parse(Decimal(1), "м")
        mass = Quantity.parse(Decimal(1), "кг")
        assert length is not None and mass is not None
        assert not length.comparable_with(mass)
