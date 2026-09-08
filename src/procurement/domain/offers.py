"""Кандидат на поставку и его характеристики.

Attribute — зеркало Requirement со стороны товара: тот же канонический ключ,
своё нормализованное значение, свой источник.

Ключевое ограничение: если Matcher не уверен в значении, атрибут либо не
создаётся вовсе, либо создаётся с низкой уверенностью — и тогда движок
соответствия вернёт UNKNOWN, а не догадку.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from procurement.domain.provenance import Provenance

AttributeValue = Decimal | str | bool | list[str]


class Attribute(BaseModel):
    """Характеристика товара, извлечённая из datasheet, каталога или КП.

    >>> from procurement.domain.provenance import Extractor
    >>> a = Attribute(
    ...     property="warranty",
    ...     value=Decimal(12),
    ...     unit="мес",
    ...     confidence=0.95,
    ...     provenance=Provenance(
    ...         document_id="КП №42", locator="стр. 3", extractor=Extractor.NATIVE_PDF
    ...     ),
    ... )
    >>> a.display()
    '12 мес'
    """

    model_config = ConfigDict(frozen=True)

    property: str = Field(min_length=1)
    value: AttributeValue
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: Provenance

    def display(self) -> str:
        """Значение с единицей для вывода пользователю.

        Метод, а не property: поле `property` затеняет декоратор.
        """
        if isinstance(self.value, Decimal):
            body = str(self.value.normalize())
        elif isinstance(self.value, list):
            body = ", ".join(self.value)
        elif isinstance(self.value, bool):
            body = "да" if self.value else "нет"
        else:
            body = str(self.value)
        return f"{body} {self.unit}".strip() if self.unit else body


class Certificate(BaseModel):
    """Разрешительный документ. Проверяется на дату поставки, а не на сегодня."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(min_length=1, description="Сертификат, декларация, СГР…")
    number: str = Field(min_length=1)
    valid_from: date | None = None
    valid_until: date | None = None
    provenance: Provenance

    def is_valid_on(self, moment: date) -> bool | None:
        """True/False, либо None если срок действия неизвестен — это UNKNOWN, не PASS."""
        if self.valid_from is None and self.valid_until is None:
            return None
        if self.valid_from is not None and moment < self.valid_from:
            return False
        # SIM103 предлагает свернуть в один return — читаемость двух явных
        # границ действия документа важнее краткости.
        if self.valid_until is not None and moment > self.valid_until:  # noqa: SIM103
            return False
        return True


class Candidate(BaseModel):
    """Товар конкретного производителя как кандидат на закрытие позиции ТЗ."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    manufacturer: str | None = None
    sku: str | None = None
    country_of_origin: str | None = None
    is_equivalent: bool = Field(
        default=False,
        description="Аналог, а не прямо указанный в ТЗ товар",
    )
    attributes: tuple[Attribute, ...] = ()
    certificates: tuple[Certificate, ...] = ()

    def attribute(self, prop: str) -> Attribute | None:
        """Атрибут по каноническому ключу. Первый найденный, None если нет.

        Отсутствие атрибута — это UNKNOWN на стороне движка соответствия,
        никогда не PASS (инвариант домена №2).
        """
        for attr in self.attributes:
            if attr.property == prop:
                return attr
        return None
