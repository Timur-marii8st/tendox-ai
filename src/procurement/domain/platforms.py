"""Цифровые платформы: отдельный канал продаж и доказательства его допуска.

Не содержит действующего правового ruleset или сетевого адаптера.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Provenance


class PlatformUse(str, Enum):
    SUPPLIER_SOURCING = "supplier_sourcing"
    SHELF_SALES = "shelf_sales"


class PlatformCondition(str, Enum):
    LEGAL_BASIS = "legal_basis"
    EDUCATION_BENEFICIARY = "education_beneficiary"
    GOODS = "goods"
    PLATFORM_REGISTER = "platform_register"
    GOVERNMENT_OPERATOR_LIST = "government_operator_list"
    OPERATOR_REQUIREMENTS = "operator_requirements"
    OPERATOR_LOGISTICS = "operator_logistics"


class PlatformCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    condition: PlatformCondition
    status: GateStatus
    reason: str = Field(min_length=1)
    evidence: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def _known_result_requires_evidence(self) -> PlatformCheck:
        if self.status is not GateStatus.UNKNOWN and not self.evidence:
            raise ValueError("известный результат требует источника")
        return self


class PlatformRuleSnapshot(BaseModel):
    """Проверенная человеком версия правил; даты относятся к публикации извещения."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    notice_valid_from: date
    notice_valid_through: date
    official_source: Provenance
    reviewed_by: str = Field(min_length=1)
    reviewed_on: date

    @model_validator(mode="after")
    def _dates_are_ordered(self) -> PlatformRuleSnapshot:
        if self.notice_valid_through < self.notice_valid_from:
            raise ValueError("неверный период действия правила")
        return self


class DigitalPlatformCase(BaseModel):
    """Кейс платформы не заменяет тендер и не выдаёт разрешения отправлять оферту."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    platform_id: str = Field(min_length=1)
    use: PlatformUse
    notice_published_on: date | None = None
    notice_provenance: Provenance | None = None
    rules: PlatformRuleSnapshot | None = None
    checks: tuple[PlatformCheck, ...] = ()

    @model_validator(mode="after")
    def _checks_are_unique(self) -> DigitalPlatformCase:
        conditions = [check.condition for check in self.checks]
        if len(conditions) != len(set(conditions)):
            raise ValueError("проверки условий не должны дублироваться")
        return self

    def shelf_eligibility(self) -> GateStatus:
        """Допуск канала продаж; остальные legal/commercial/quote gates обязательны.

        Без утверждённой версии и полного набора доказательств возвращает UNKNOWN.
        """
        if self.use is not PlatformUse.SHELF_SALES:
            raise ValueError("поиск поставщика не является закупкой с полки")
        if self.rules is None:
            return GateStatus.UNKNOWN
        if self.notice_published_on is None or self.notice_provenance is None:
            return GateStatus.UNKNOWN
        if not (
            self.rules.notice_valid_from
            <= self.notice_published_on
            <= self.rules.notice_valid_through
        ):
            return GateStatus.FAIL
        statuses = {check.condition: check.status for check in self.checks}
        if GateStatus.FAIL in statuses.values():
            return GateStatus.FAIL
        if set(statuses) != set(PlatformCondition) or GateStatus.UNKNOWN in statuses.values():
            return GateStatus.UNKNOWN
        return GateStatus.PASS
