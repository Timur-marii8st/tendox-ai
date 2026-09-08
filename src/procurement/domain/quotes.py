"""Версионированное коммерческое предложение на весь комплект поставки."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.economics import _finite_decimal
from procurement.domain.provenance import Provenance


class Currency(str, Enum):
    RUB = "RUB"


class Quote(BaseModel):
    """Одно КП поставщика; неизвестное условие остаётся ``None``."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    quote_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    company_id: str = Field(min_length=1)
    tender_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    amount_ex_vat: Decimal = Field(gt=0)
    nds_rate: Decimal | None = Field(default=None, ge=0, le=1)
    currency: Currency
    issued_at: datetime
    valid_until: datetime
    source: Provenance
    covers_full_scope: bool | None = None
    availability_terms: str | None = Field(default=None, min_length=1)
    delivery_terms: str | None = Field(default=None, min_length=1)
    payment_terms: str | None = Field(default=None, min_length=1)

    @field_validator("amount_ex_vat", "nds_rate", mode="before")
    @classmethod
    def _money_is_exact_and_finite(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _finite_decimal(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _validity_window_is_usable(self) -> Quote:
        for moment in (self.issued_at, self.valid_until):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("даты КП должны содержать часовой пояс")
        if self.valid_until <= self.issued_at:
            raise ValueError("срок действия КП должен быть позже даты выдачи")
        return self

    @property
    def is_complete(self) -> bool:
        """Полнота требует подтверждённого покрытия и всех явных условий."""
        return (
            self.nds_rate is not None
            and self.covers_full_scope is True
            and self.availability_terms is not None
            and self.delivery_terms is not None
            and self.payment_terms is not None
        )

    def is_valid_at(self, moment: datetime) -> bool:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("момент проверки должен содержать часовой пояс")
        return self.issued_at <= moment < self.valid_until
