"""Проверяемый снимок тендерного кейса и чистая функция решения S1."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.company import CompanyProfile
from procurement.domain.decisions import (
    GateStatus,
    Recommendation,
    RecommendationDecision,
    TenderRating,
)
from procurement.domain.economics import ScenarioKind, ScenarioSet, _finite_decimal
from procurement.domain.provenance import Provenance
from procurement.domain.quotes import Quote
from procurement.domain.tenders import TenderProcedure


class ProcurementChannel(str, Enum):
    STANDARD = "standard"
    SHELF_SALES = "shelf_sales"


class GateKind(str, Enum):
    LEGAL = "legal"
    PARTICIPANT = "participant"
    TECHNICAL = "technical"
    COMPANY_POLICY = "company_policy"
    LOGISTICS = "logistics"
    DOCUMENT = "document"


class GateCheck(BaseModel):
    """Один введённый человеком hard gate с доказательствами."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: GateKind
    status: GateStatus
    reason: str = Field(min_length=1)
    evidence: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def _known_check_has_evidence(self) -> GateCheck:
        if self.status is not GateStatus.UNKNOWN and not self.evidence:
            raise ValueError("известный результат проверки требует источника")
        return self


class CaseAssessment(BaseModel):
    """Ручная оценка строго определённого снимка входных данных."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewer_id: str = Field(min_length=1)
    assessed_at: datetime
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[GateCheck, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def _unique_gate_set(self) -> CaseAssessment:
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() is None:
            raise ValueError("время ручной оценки должно содержать часовой пояс")
        kinds = [check.kind for check in self.checks]
        if len(kinds) != len(set(kinds)):
            raise ValueError("обязательные проверки не должны повторяться")
        return self


class ProcurementCase(BaseModel):
    """Один tenant-scoped снимок данных для воспроизводимого решения."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    company_id: str = Field(min_length=1)
    channel: ProcurementChannel = ProcurementChannel.STANDARD
    profile: CompanyProfile
    tender: TenderProcedure
    nmck_ex_vat: Decimal = Field(gt=0)
    nmck_source: Provenance
    selected_quote: Quote | None = None
    scenarios: ScenarioSet | None = None
    assessment: CaseAssessment | None = None
    rating: TenderRating

    @field_validator("nmck_ex_vat", mode="before")
    @classmethod
    def _nmck_is_exact_and_finite(cls, value: object) -> Decimal:
        return _finite_decimal(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _aggregate_is_consistent(self) -> ProcurementCase:
        if self.profile.company_id != self.company_id:
            raise ValueError("профиль принадлежит другой компании")
        quote = self.selected_quote
        if quote is not None:
            if quote.company_id != self.company_id:
                raise ValueError("КП принадлежит другой компании")
            if quote.tender_id != self.tender.tender_id:
                raise ValueError("КП принадлежит другой процедуре")
        if self.scenarios is not None:
            rates = [scenario.economics.nds_rate for scenario in self.scenarios.scenarios]
            if all(rate is not None for rate in rates) and len(set(rates)) != 1:
                raise ValueError("сценарии должны использовать единую ставку НДС")
            for scenario in self.scenarios.scenarios:
                economics = scenario.economics
                if economics.contract_revenue > self.nmck_ex_vat:
                    raise ValueError("выручка сценария не может превышать НМЦК")
                if quote is not None and economics.costs.goods < quote.amount_ex_vat:
                    raise ValueError("закупочная стоимость не может быть ниже выбранного КП")
        return self


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("канонический снимок не принимает неконечные числа")
    return value


def case_input_digest(case: ProcurementCase) -> str:
    """Hash полного снимка кейса за исключением самой ручной оценки."""
    snapshot = case.model_dump(mode="python", exclude={"assessment"})
    encoded = json.dumps(
        _canonical(snapshot),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recommendation(
    case: ProcurementCase,
    at: datetime,
    decision: RecommendationDecision,
    reasons: tuple[str, ...],
) -> Recommendation:
    return Recommendation(decision=decision, reasons=reasons, rating=case.rating, generated_at=at)


def evaluate_case(case: ProcurementCase, *, at: datetime) -> Recommendation:
    """Воспроизводимо решить один полностью локальный S1-кейс."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("момент решения должен содержать часовой пояс")

    # Не доверяем даже экземпляру, собранному через model_construct/model_copy.
    checked = ProcurementCase.model_validate(case.model_dump(mode="python"))
    if not checked.tender.accepts_applications_at(at):
        return _recommendation(
            checked,
            at,
            RecommendationDecision.DO_NOT_PARTICIPATE,
            ("срок подачи заявки истёк или подача не открыта",),
        )
    if checked.channel is ProcurementChannel.SHELF_SALES:
        return _recommendation(
            checked,
            at,
            RecommendationDecision.NEEDS_ANALYSIS,
            ("автоматическая рекомендация для продаж с полки ещё не поддерживается",),
        )

    assessment = checked.assessment
    if (
        assessment is None
        or assessment.assessed_at > at
        or (
            checked.selected_quote is not None
            and assessment.assessed_at < checked.selected_quote.issued_at
        )
        or assessment.input_digest != case_input_digest(checked)
    ):
        return _recommendation(
            checked,
            at,
            RecommendationDecision.NEEDS_ANALYSIS,
            ("нет актуальной ручной оценки точного снимка кейса",),
        )
    failed = tuple(check for check in assessment.checks if check.status is GateStatus.FAIL)
    if failed:
        return _recommendation(
            checked,
            at,
            RecommendationDecision.DO_NOT_PARTICIPATE,
            tuple(f"{check.kind.value}: {check.reason}" for check in failed),
        )
    unknown = tuple(check for check in assessment.checks if check.status is GateStatus.UNKNOWN)
    checked_kinds = {check.kind for check in assessment.checks}
    missing = tuple(kind for kind in GateKind if kind not in checked_kinds)
    if unknown or missing:
        return _recommendation(
            checked,
            at,
            RecommendationDecision.NEEDS_ANALYSIS,
            tuple(f"{check.kind.value}: {check.reason}" for check in unknown)
            + tuple(f"{kind.value}: обязательная проверка отсутствует" for kind in missing),
        )

    quote = checked.selected_quote
    if quote is None or not quote.is_complete or not quote.is_valid_at(at):
        return _recommendation(
            checked,
            at,
            RecommendationDecision.NEEDS_ANALYSIS,
            ("нет действующего полного КП с подтверждёнными условиями",),
        )
    scenarios = checked.scenarios
    if scenarios is None or not scenarios.is_complete:
        return _recommendation(
            checked,
            at,
            RecommendationDecision.NEEDS_ANALYSIS,
            ("не завершены base, realistic и conservative сценарии",),
        )

    realistic = scenarios.get(ScenarioKind.REALISTIC)
    policy = checked.profile.finance
    if not policy.min_contract_amount <= checked.nmck_ex_vat <= policy.max_contract_amount:
        return _recommendation(
            checked,
            at,
            RecommendationDecision.DO_NOT_PARTICIPATE,
            ("НМЦК вне допустимого диапазона компании",),
        )
    if not policy.min_contract_amount <= realistic.contract_revenue <= policy.max_contract_amount:
        return _recommendation(
            checked,
            at,
            RecommendationDecision.DO_NOT_PARTICIPATE,
            ("цена реалистичного сценария вне допустимого диапазона компании",),
        )
    minimum_bid_price = max(
        realistic.costs.all_in / (Decimal(1) - policy.price_floor_margin),
        realistic.costs.all_in + policy.min_expected_profit,
        policy.min_contract_amount,
    ).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    exact_margin = realistic.gross_profit / realistic.contract_revenue
    financial_reasons: list[str] = []
    if realistic.gross_profit < policy.min_expected_profit:
        financial_reasons.append("прибыль реалистичного сценария ниже лимита компании")
    if exact_margin < policy.min_margin:
        financial_reasons.append("маржа реалистичного сценария ниже лимита компании")
    decision = (
        RecommendationDecision.DO_NOT_PARTICIPATE
        if financial_reasons
        else RecommendationDecision.PARTICIPATE
    )
    return Recommendation(
        decision=decision,
        reasons=tuple(financial_reasons)
        or ("все hard gates пройдены, КП и экономика подтверждены",),
        rating=checked.rating,
        realistic_profit=realistic.gross_profit,
        realistic_margin=realistic.margin,
        minimum_bid_price=minimum_bid_price,
        generated_at=at,
    )
