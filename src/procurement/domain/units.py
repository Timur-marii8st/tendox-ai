"""Нормализация единиц измерения.

Инвариант домена №5: величины приводятся к каноническим единицам на входе,
исходная строка сохраняется рядом. Это снимает целый класс ошибок — месяцы против
лет в гарантии, мм против см, Мбит/с против Гбит/с.

Календарные и суточные сроки — **разные измерения**. "24 мес" и "730 дн"
сознательно несопоставимы: месяц не равен фиксированному числу дней, и попытка
свести их к общему знаменателю даёт неверные вердикты (2 года = 730 дн против
24 мес = 720 дн дала бы FAIL на эквивалентных сроках). Несопоставимые единицы
дают UNKNOWN, а не догадку.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Dimension(str, Enum):
    """Физическая величина. Сравнивать можно только внутри одного измерения."""

    COUNT = "count"
    LENGTH = "length"
    MASS = "mass"
    DURATION_CALENDAR = "duration_calendar"
    DURATION_DAYS = "duration_days"
    DATA_RATE = "data_rate"
    POWER = "power"
    VOLTAGE = "voltage"
    FREQUENCY = "frequency"
    CAPACITY = "capacity"


@dataclass(frozen=True, slots=True)
class Unit:
    """Единица измерения и её коэффициент к канонической единице измерения."""

    symbol: str
    dimension: Dimension
    factor: Decimal

    @property
    def is_canonical(self) -> bool:
        return self.factor == Decimal(1)


def _u(symbol: str, dimension: Dimension, factor: str) -> Unit:
    return Unit(symbol=symbol, dimension=dimension, factor=Decimal(factor))


# Канонические единицы: шт, мм, г, мес, дн, Мбит/с, Вт, В, Гц, ГБ.
_DEFS: tuple[tuple[Unit, tuple[str, ...]], ...] = (
    (_u("шт", Dimension.COUNT, "1"), ("шт", "шт.", "штука", "штук", "pcs", "ед", "ед.")),
    (_u("мм", Dimension.LENGTH, "1"), ("мм", "mm")),
    (_u("см", Dimension.LENGTH, "10"), ("см", "cm")),
    (_u("м", Dimension.LENGTH, "1000"), ("м", "m", "метр", "метров")),
    (_u("г", Dimension.MASS, "1"), ("г", "g", "гр")),
    (_u("кг", Dimension.MASS, "1000"), ("кг", "kg")),
    (_u("т", Dimension.MASS, "1000000"), ("т", "тонна", "тонн")),
    (_u("мес", Dimension.DURATION_CALENDAR, "1"), ("мес", "мес.", "месяц", "месяцев", "months")),
    (_u("кв", Dimension.DURATION_CALENDAR, "3"), ("кв", "квартал", "кварталов")),
    (_u("год", Dimension.DURATION_CALENDAR, "12"), ("год", "года", "лет", "г.", "years")),
    (_u("дн", Dimension.DURATION_DAYS, "1"), ("дн", "дн.", "день", "дней", "days", "суток")),
    (_u("нед", Dimension.DURATION_DAYS, "7"), ("нед", "нед.", "неделя", "недель", "weeks")),
    (_u("Мбит/с", Dimension.DATA_RATE, "1"), ("мбит/с", "mbps", "мбит")),
    (_u("Гбит/с", Dimension.DATA_RATE, "1000"), ("гбит/с", "gbps", "гбит")),
    (_u("Вт", Dimension.POWER, "1"), ("вт", "w", "ватт")),
    (_u("кВт", Dimension.POWER, "1000"), ("квт", "kw")),
    (_u("В", Dimension.VOLTAGE, "1"), ("в", "v", "вольт")),
    (_u("кВ", Dimension.VOLTAGE, "1000"), ("кв.", "kv")),
    (_u("Гц", Dimension.FREQUENCY, "1"), ("гц", "hz")),
    (_u("кГц", Dimension.FREQUENCY, "1000"), ("кгц", "khz")),
    (_u("МГц", Dimension.FREQUENCY, "1000000"), ("мгц", "mhz")),
    (_u("ГБ", Dimension.CAPACITY, "1"), ("гб", "gb")),
    (_u("ТБ", Dimension.CAPACITY, "1024"), ("тб", "tb")),
    (_u("МБ", Dimension.CAPACITY, "0.0009765625"), ("мб", "mb")),
)

_REGISTRY: dict[str, Unit] = {alias.lower(): unit for unit, aliases in _DEFS for alias in aliases}


def resolve_unit(raw: str | None) -> Unit | None:
    """Найти единицу по написанию. Возвращает None, если единица неизвестна.

    >>> resolve_unit("мес.").symbol
    'мес'
    >>> resolve_unit("года").factor
    Decimal('12')
    >>> resolve_unit("попугаев") is None
    True
    """
    if raw is None:
        return None
    return _REGISTRY.get(raw.strip().lower().rstrip(","))


@dataclass(frozen=True, slots=True)
class Quantity:
    """Числовое значение с единицей измерения и исходным написанием.

    >>> q = Quantity.parse(Decimal(2), "года")
    >>> q.canonical
    Decimal('24')
    >>> q.comparable_with(Quantity.parse(Decimal(24), "мес"))
    True
    """

    value: Decimal
    unit: Unit
    raw_unit: str

    @classmethod
    def parse(cls, value: Decimal, raw_unit: str) -> Quantity | None:
        """Создать величину, если единица распознана. Иначе None → UNKNOWN."""
        unit = resolve_unit(raw_unit)
        if unit is None:
            return None
        return cls(value=value, unit=unit, raw_unit=raw_unit)

    @property
    def canonical(self) -> Decimal:
        """Значение в канонической единице своего измерения."""
        return self.value * self.unit.factor

    @property
    def dimension(self) -> Dimension:
        return self.unit.dimension

    def comparable_with(self, other: Quantity) -> bool:
        """Сравнивать можно только внутри одного измерения."""
        return self.dimension is other.dimension

    def __str__(self) -> str:
        return f"{self.value.normalize()} {self.unit.symbol}"
