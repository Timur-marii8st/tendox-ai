"""Профиль компании и её неизменяемая политика участия в закупках."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FINANCIAL_POLICY_DECIMAL_FIELDS = (
    "min_contract_amount",
    "max_contract_amount",
    "min_margin",
    "min_expected_profit",
    "max_contract_without_extra_approval",
    "max_application_security",
    "max_performance_security",
    "price_floor_margin",
)


def _finite_financial_decimal(value: object) -> Decimal:
    """Принять только точное конечное значение финансового лимита."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError("финансовый лимит должен быть Decimal, int или str, но не float")
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("финансовый лимит должен быть числом") from error
    if not decimal_value.is_finite():
        raise ValueError("финансовый лимит должен быть конечным")
    return decimal_value


class ProhibitionKind(str, Enum):
    """Юридический запрет нельзя смешивать с коммерческим решением компании."""

    LEGAL = "legal"
    COMMERCIAL = "commercial"


class ProhibitionRule(BaseModel):
    """Версионированное правило остановки кейса.

    ``condition`` — ключ детерминированного предиката из реестра правил, а не
    произвольный текст, исполняемый LLM.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(min_length=1)
    kind: ProhibitionKind
    condition: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    enabled: bool = True
    legal_basis: str | None = None

    @model_validator(mode="after")
    def _legal_rule_has_basis(self) -> ProhibitionRule:
        if self.kind is ProhibitionKind.LEGAL and not self.legal_basis:
            raise ValueError("для юридического запрета требуется правовое основание")
        return self


class CompanyIdentity(BaseModel):
    """Реквизиты участника закупки; ИНН и КПП хранятся строками."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    inn: str = Field(pattern=r"^(\d{10}|\d{12})$")
    kpp: str | None = Field(default=None, pattern=r"^\d{9}$")
    ogrn: str = Field(pattern=r"^(\d{13}|\d{15})$")
    legal_form: str = Field(min_length=1)


class GeographyPolicy(BaseModel):
    """Разрешённая география поиска и логистические ограничения."""

    model_config = ConfigDict(frozen=True)

    all_russia: bool = False
    federal_districts: frozenset[str] = frozenset()
    regions: frozenset[str] = frozenset()
    cities: frozenset[str] = frozenset()
    max_distance_km: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _scope_is_not_empty(self) -> GeographyPolicy:
        if not self.all_russia and not (self.federal_districts or self.regions or self.cities):
            raise ValueError("нужно задать хотя бы одну разрешённую территорию")
        return self


class FinancialPolicy(BaseModel):
    """Финансовые hard gates автопилота."""

    model_config = ConfigDict(frozen=True)

    min_contract_amount: Decimal = Field(ge=0)
    max_contract_amount: Decimal = Field(gt=0)
    min_margin: Decimal = Field(ge=0, le=1)
    min_expected_profit: Decimal = Field(ge=0)
    max_contract_without_extra_approval: Decimal = Field(ge=0)
    max_application_security: Decimal = Field(ge=0)
    max_performance_security: Decimal = Field(ge=0)
    price_floor_margin: Decimal = Field(ge=0, lt=1)

    @field_validator(*FINANCIAL_POLICY_DECIMAL_FIELDS, mode="before")
    @classmethod
    def _financial_fields_are_finite_decimals(cls, value: object) -> Decimal:
        return _finite_financial_decimal(value)

    @model_validator(mode="after")
    def _limits_are_ordered(self) -> FinancialPolicy:
        if self.min_contract_amount > self.max_contract_amount:
            raise ValueError("минимальная сумма контракта больше максимальной")
        if self.max_contract_without_extra_approval > self.max_contract_amount:
            raise ValueError("лимит без согласования выше максимальной суммы контракта")
        if self.price_floor_margin > self.min_margin:
            raise ValueError("порог снижения цены не может быть выше требуемой маржи")
        return self


class CompanyProfile(BaseModel):
    """Настройки одного арендатора SaaS; критические поля меняются только человеком."""

    model_config = ConfigDict(frozen=True)

    company_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    identity: CompanyIdentity
    okved: tuple[str, ...] = ()
    business_description: str = Field(min_length=1)
    supplied_goods: tuple[str, ...] = ()
    performed_works: tuple[str, ...] = ()
    provided_services: tuple[str, ...] = ()
    geography: GeographyPolicy
    finance: FinancialPolicy
    enabled_platforms: frozenset[str] = frozenset()
    subcontracting_allowed: bool = False
    allowed_procedure_methods: frozenset[str] = frozenset()
    prohibitions: tuple[ProhibitionRule, ...] = ()

    @model_validator(mode="after")
    def _business_scope_exists(self) -> CompanyProfile:
        if not (self.supplied_goods or self.performed_works or self.provided_services):
            raise ValueError("профиль должен содержать товары, работы или услуги")
        ids = [rule.rule_id for rule in self.prohibitions]
        if len(ids) != len(set(ids)):
            raise ValueError("идентификаторы правил запрета должны быть уникальны")
        return self
