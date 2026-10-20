"""Экономика сделки для поставщика.

Инвариант домена №6: деньги — только Decimal, НДС хранится отдельной ставкой.
Поставщик выбирает не самый дешёвый товар, а сделку с лучшим соотношением
прибыли и риска, поэтому сравнение по цене за единицу бесполезно.
Методика — docs/architecture/04-economics.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KOPECK = Decimal("0.01")
DAYS_IN_YEAR = Decimal(365)
COST_FIELD_NAMES = (
    "goods",
    "packaging",
    "logistics",
    "loading_unloading",
    "storage",
    "installation",
    "payroll_travel",
    "subcontracting",
    "insurance",
    "finance",
    "bank_guarantee",
    "platform_fees",
    "taxes",
    "certification",
    "warranty",
    "risk_reserve",
    "penalty_reserve",
    "other",
)


def _finite_decimal(value: Decimal | int | str) -> Decimal:
    """Принять только точное конечное денежное значение."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError("денежное значение должно быть Decimal, int или str, но не float")
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("денежное значение должно быть числом") from error
    if not decimal_value.is_finite():
        raise ValueError("денежное значение должно быть конечным")
    return decimal_value


def money(value: Decimal | int | str) -> Decimal:
    """Привести сумму к копейкам. float в денежных расчётах запрещён.

    >>> money("1234.567")
    Decimal('1234.57')
    """
    return _finite_decimal(value).quantize(KOPECK, rounding=ROUND_HALF_UP)


def cost_of_money(
    prepayment: Decimal | int | str,
    annual_rate: Decimal | int | str,
    cash_gap_days: int,
) -> Decimal:
    """Стоимость денег на срок кассового разрыва.

    Самый часто теряемый расход: 100% предоплата производителю при постоплате от
    заказчика означает, что поставщик кредитует сделку из своих средств.

    >>> cost_of_money(Decimal("3710000"), Decimal("0.24"), 12)
    Decimal('29273.42')
    """
    exact_prepayment = _finite_decimal(prepayment)
    exact_annual_rate = _finite_decimal(annual_rate)
    if exact_prepayment < 0:
        raise ValueError("предоплата не может быть отрицательной")
    if exact_annual_rate < 0:
        raise ValueError("годовая ставка не может быть отрицательной")
    if isinstance(cash_gap_days, bool) or not isinstance(cash_gap_days, int):
        raise ValueError("срок кассового разрыва должен быть целым числом дней")
    if cash_gap_days < 0:
        raise ValueError("срок кассового разрыва не может быть отрицательным")
    return money(exact_prepayment * exact_annual_rate * Decimal(cash_gap_days) / DAYS_IN_YEAR)


class CostBreakdown(BaseModel):
    """All-in себестоимость сделки. Все составляющие явные — иначе маржа врёт."""

    model_config = ConfigDict(frozen=True)
    _cost_field_names: ClassVar[tuple[str, ...]] = COST_FIELD_NAMES

    goods: Decimal = Field(ge=0, description="Закупка товара без НДС")
    packaging: Decimal = Field(default=Decimal(0), ge=0)
    logistics: Decimal = Field(default=Decimal(0), ge=0, description="Доставка до места из ТЗ")
    loading_unloading: Decimal = Field(default=Decimal(0), ge=0)
    storage: Decimal = Field(default=Decimal(0), ge=0)
    installation: Decimal = Field(default=Decimal(0), ge=0, description="Монтаж и пусконаладка")
    payroll_travel: Decimal = Field(default=Decimal(0), ge=0)
    subcontracting: Decimal = Field(default=Decimal(0), ge=0)
    insurance: Decimal = Field(default=Decimal(0), ge=0)
    finance: Decimal = Field(default=Decimal(0), ge=0, description="Стоимость денег")
    bank_guarantee: Decimal = Field(default=Decimal(0), ge=0)
    platform_fees: Decimal = Field(default=Decimal(0), ge=0)
    taxes: Decimal = Field(
        default=Decimal(0), ge=0, description="Налоги, кроме отдельно указанного НДС"
    )
    certification: Decimal = Field(default=Decimal(0), ge=0, description="Испытания, документы")
    warranty: Decimal = Field(default=Decimal(0), ge=0, description="Обслуживание в гарантию")
    risk_reserve: Decimal = Field(default=Decimal(0), ge=0)
    penalty_reserve: Decimal = Field(default=Decimal(0), ge=0)
    other: Decimal = Field(default=Decimal(0), ge=0)
    specified_cost_fields: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _record_specified_cost_fields(cls, value: object) -> object:
        """Сохранить явные нули при сериализации, не полагаясь на fields_set.

        Pydantic заполняет default-поля при ``model_dump()``. Поэтому при
        повторной загрузке берём сохранённый список явных статей, а не ключи
        полного JSON-представления.
        """
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        has_all_cost_fields = all(name in data for name in cls._cost_field_names)
        if has_all_cost_fields and "specified_cost_fields" in data:
            return data
        data["specified_cost_fields"] = tuple(
            name for name in cls._cost_field_names if name in data
        )
        return data

    @field_validator(*COST_FIELD_NAMES, mode="before")
    @classmethod
    def _costs_are_finite_decimals(cls, value: object) -> Decimal:
        return _finite_decimal(value)  # type: ignore[arg-type]

    @field_validator("specified_cost_fields")
    @classmethod
    def _specified_fields_are_cost_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - set(cls._cost_field_names)
        if unknown:
            raise ValueError(f"неизвестные статьи затрат: {sorted(unknown)}")
        if len(value) != len(set(value)):
            raise ValueError("статьи затрат не должны повторяться")
        return tuple(name for name in cls._cost_field_names if name in value)

    @property
    def is_complete(self) -> bool:
        """Все статьи имеют подтверждённое значение, включая явные нули."""
        return self.specified_cost_fields == self._cost_field_names

    @property
    def all_in(self) -> Decimal:
        """Полная себестоимость.

        >>> CostBreakdown(goods=Decimal("3710000"), logistics=Decimal("120000")).all_in
        Decimal('3830000.00')
        """
        return money(
            self.goods
            + self.packaging
            + self.logistics
            + self.loading_unloading
            + self.storage
            + self.installation
            + self.payroll_travel
            + self.subcontracting
            + self.insurance
            + self.finance
            + self.bank_guarantee
            + self.platform_fees
            + self.taxes
            + self.certification
            + self.warranty
            + self.risk_reserve
            + self.penalty_reserve
            + self.other
        )

    def lines(self) -> tuple[tuple[str, Decimal], ...]:
        """Расшифровка для вывода пользователю, без нулевых строк."""
        labels = (
            ("Закупка товара", self.goods),
            ("Упаковка", self.packaging),
            ("Доставка", self.logistics),
            ("Погрузка и разгрузка", self.loading_unloading),
            ("Хранение", self.storage),
            ("Монтаж и пусконаладка", self.installation),
            ("Зарплата и командировки", self.payroll_travel),
            ("Субподряд", self.subcontracting),
            ("Страхование", self.insurance),
            ("Стоимость денег", self.finance),
            ("Банковская гарантия", self.bank_guarantee),
            ("Комиссии площадки", self.platform_fees),
            ("Налоги", self.taxes),
            ("Сертификация", self.certification),
            ("Гарантийное обслуживание", self.warranty),
            ("Резерв рисков", self.risk_reserve),
            ("Резерв штрафов", self.penalty_reserve),
            ("Прочие расходы", self.other),
        )
        return tuple((label, money(value)) for label, value in labels if value)


class DealEconomics(BaseModel):
    """Прибыль и маржинальность сделки для поставщика."""

    model_config = ConfigDict(frozen=True)

    contract_revenue: Decimal = Field(gt=0, description="Цена контракта заказчика без НДС")
    costs: CostBreakdown
    nds_rate: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Ставка НДС отдельным полем; «примерно включён» — запрещено",
    )

    @field_validator("contract_revenue", "nds_rate", mode="before")
    @classmethod
    def _money_fields_are_finite_decimals(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _finite_decimal(value)  # type: ignore[arg-type]

    @property
    def is_complete(self) -> bool:
        """Экономика пригодна для решения только с известными затратами и НДС."""
        return self.costs.is_complete and self.nds_rate is not None

    @property
    def gross_profit(self) -> Decimal:
        """Прогноз прибыли.

        >>> deal = DealEconomics(
        ...     contract_revenue=Decimal("4800000"),
        ...     costs=CostBreakdown(goods=Decimal("3710000"), logistics=Decimal("120000")),
        ... )
        >>> deal.gross_profit
        Decimal('970000.00')
        """
        return money(self.contract_revenue - self.costs.all_in)

    @property
    def margin(self) -> Decimal:
        """Маржинальность как доля выручки. Может быть отрицательной — это сигнал."""
        return (self.gross_profit / self.contract_revenue).quantize(Decimal("0.0001"))

    @property
    def is_profitable(self) -> bool:
        return self.gross_profit > 0

    def report(self) -> str:
        """Раскладка из docs/architecture/04-economics.md."""
        width = 18
        rows = [f"{'Контракт заказчика':<28}{self.contract_revenue:>{width},.2f}"]
        rows += [f"{label:<28}{-value:>{width},.2f}" for label, value in self.costs.lines()]
        rows.append("-" * (28 + width))
        rows.append(f"{'Прогноз прибыли':<28}{self.gross_profit:>{width},.2f}")
        rows.append(f"{'Маржинальность':<28}{self.margin:>{width - 1}.2%}")
        return "\n".join(rows).replace(",", " ")


class ScenarioKind(str, Enum):
    """Три обязательных сценария из продуктового ТЗ."""

    BASE = "base"
    REALISTIC = "realistic"
    CONSERVATIVE = "conservative"


class EconomicsScenario(BaseModel):
    """Именованный расчёт с явными допущениями."""

    model_config = ConfigDict(frozen=True)

    kind: ScenarioKind
    economics: DealEconomics
    assumptions: tuple[str, ...] = Field(min_length=1)


class ScenarioSet(BaseModel):
    """Нельзя выдать рекомендацию по одному оптимистичному расчёту."""

    model_config = ConfigDict(frozen=True)

    scenarios: tuple[EconomicsScenario, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _all_scenarios_present(self) -> ScenarioSet:
        kinds = {scenario.kind for scenario in self.scenarios}
        if kinds != set(ScenarioKind):
            raise ValueError("нужны ровно base, realistic и conservative сценарии")
        return self

    def get(self, kind: ScenarioKind) -> DealEconomics:
        for scenario in self.scenarios:
            if scenario.kind is kind:
                return scenario.economics
        raise RuntimeError("набор сценариев повреждён")

    @property
    def is_complete(self) -> bool:
        """Все три обязательных сценария содержат полную экономику."""
        return all(scenario.economics.is_complete for scenario in self.scenarios)
