"""Требования ТЗ — атомы, которые можно проверить машинно.

Требование ТЗ разбирается на элементарные утверждения вида
"ethernet_ports >= 24". Разница между обязательным и желательным требованием
критическая: провал обязательного означает отклонение заявки, провал желательного —
минус в рейтинге.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Provenance

RequirementValue = Decimal | str | bool | list[str] | tuple[Decimal, Decimal]
"""Допустимые типы значения требования. BETWEEN использует пару чисел."""


class Operator(str, Enum):
    """Как сравнивать факт по товару с требованием ТЗ."""

    GE = ">="
    LE = "<="
    GT = ">"
    LT = "<"
    EQ = "=="
    NE = "!="
    IN = "in"
    CONTAINS = "contains"
    BETWEEN = "between"
    EXISTS = "exists"

    @property
    def is_numeric(self) -> bool:
        return self in (
            Operator.GE,
            Operator.LE,
            Operator.GT,
            Operator.LT,
            Operator.BETWEEN,
        )


class Requirement(BaseModel):
    """Одно проверяемое требование ТЗ.

    >>> from procurement.domain.provenance import Extractor
    >>> r = Requirement(
    ...     property="warranty",
    ...     operator=Operator.GE,
    ...     value=Decimal(24),
    ...     unit="мес",
    ...     mandatory=True,
    ...     raw_text="Гарантийный срок не менее 24 месяцев",
    ...     provenance=Provenance(
    ...         document_id="ТЗ.pdf", locator="стр. 16", extractor=Extractor.NATIVE_PDF
    ...     ),
    ... )
    >>> r.label()
    'warranty >= 24 мес'
    """

    model_config = ConfigDict(frozen=True)

    property: str = Field(min_length=1, description="Канонический ключ характеристики")
    operator: Operator
    value: RequirementValue | None = None
    unit: str | None = Field(default=None, description="Написание единицы из ТЗ")
    mandatory: bool = Field(description="Обязательное требование или желательное")
    weight: int = Field(default=1, ge=1, description="Вес в soft-score; только для желательных")
    raw_text: str = Field(min_length=1, description="Исходная формулировка из ТЗ")
    provenance: Provenance

    @model_validator(mode="after")
    def _check_shape(self) -> Requirement:
        if self.operator is Operator.EXISTS:
            if self.value is not None:
                raise ValueError("оператор EXISTS не принимает значение")
        elif self.value is None:
            raise ValueError(f"оператор {self.operator.value} требует значение")

        if self.operator is Operator.BETWEEN:
            if not isinstance(self.value, tuple) or len(self.value) != 2:
                raise ValueError("BETWEEN требует пару значений (low, high)")
            low, high = self.value
            if low > high:
                raise ValueError("BETWEEN: нижняя граница больше верхней")
        elif self.operator is Operator.IN and not isinstance(self.value, list):
            raise ValueError("IN требует список допустимых значений")
        elif self.operator.is_numeric and not isinstance(self.value, Decimal):
            raise ValueError(f"оператор {self.operator.value} требует числовое значение")

        if self.mandatory and self.weight != 1:
            raise ValueError(
                "вес применяется только к желательным требованиям: "
                "обязательное требование нельзя «взвесить», его провал фатален"
            )
        return self

    def label(self) -> str:
        """Человекочитаемая формулировка требования.

        Метод, а не property: поле `property` в этой модели затеняет
        встроенный декоратор внутри тела класса.
        """
        if self.operator is Operator.EXISTS:
            return f"{self.property} обязателен"
        if self.operator is Operator.BETWEEN and isinstance(self.value, tuple):
            low, high = self.value
            body = f"{low.normalize()}…{high.normalize()}"
        elif isinstance(self.value, list):
            body = ", ".join(self.value)
        elif isinstance(self.value, Decimal):
            body = str(self.value.normalize())
        else:
            body = str(self.value)
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.property} {self.operator.value} {body}{unit}"


class LineItem(BaseModel):
    """Позиция ТЗ: что, сколько и по каким требованиям."""

    model_config = ConfigDict(frozen=True)

    number: int = Field(ge=1, description="Номер позиции в ТЗ")
    name: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(default="шт")
    requirements: tuple[Requirement, ...] = Field(default=())
    ktru: str | None = None
    okpd2: str | None = None
    equivalent_allowed: bool = Field(
        default=False,
        description="Допускает ли ТЗ поставку эквивалента",
    )
    delivery_deadline: date | None = None
    delivery_place: str | None = None
    provenance: Provenance

    @property
    def mandatory_requirements(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.mandatory)

    @property
    def desirable_requirements(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if not r.mandatory)

    @model_validator(mode="after")
    def _no_duplicate_properties(self) -> LineItem:
        """Два требования на один и тот же property с одним оператором — ошибка извлечения."""
        seen: set[tuple[str, Operator]] = set()
        for req in self.requirements:
            key = (req.property, req.operator)
            if key in seen:
                raise ValueError(
                    f"дублирующее требование {req.property} {req.operator.value} "
                    f"в позиции №{self.number}"
                )
            seen.add(key)
        return self


PositiveQuantity = Annotated[Decimal, Field(gt=0)]
