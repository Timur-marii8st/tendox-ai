"""Независимые риски, объяснимый рейтинг и итоговая рекомендация."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Provenance


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskFinding(BaseModel):
    """Риск не является процентом соответствия и всегда объясняется."""

    model_config = ConfigDict(frozen=True)

    category: str = Field(min_length=1)
    severity: RiskSeverity
    reason: str = Field(min_length=1)
    proposed_action: str = Field(min_length=1)
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class ScoreFactor(BaseModel):
    """Один вклад в рейтинг; диапазон позволяет как повышать, так и снижать балл."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    points: int = Field(ge=-100, le=100)
    explanation: str = Field(min_length=1)
    change_hint: str | None = None


class TenderRating(BaseModel):
    """Сортировка 0–100, но не замена hard gates."""

    model_config = ConfigDict(frozen=True)

    score: int = Field(ge=0, le=100)
    factors: tuple[ScoreFactor, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _score_equals_factor_sum(self) -> TenderRating:
        calculated = max(0, min(100, sum(factor.points for factor in self.factors)))
        if calculated != self.score:
            raise ValueError(f"рейтинг {self.score} не равен сумме факторов {calculated}")
        return self


class RecommendationDecision(str, Enum):
    PARTICIPATE = "participate"
    DO_NOT_PARTICIPATE = "do_not_participate"
    NEEDS_ANALYSIS = "needs_analysis"


class Recommendation(BaseModel):
    """Итог решения с машинными основаниями и временем расчёта."""

    model_config = ConfigDict(frozen=True)

    decision: RecommendationDecision
    reasons: tuple[str, ...] = Field(min_length=1)
    rating: TenderRating
    realistic_profit: Decimal | None = None
    realistic_margin: Decimal | None = None
    minimum_bid_price: Decimal | None = None
    generated_at: datetime

    @property
    def color(self) -> str:
        """Цвет карточки определяется решением, а не баллом рейтинга."""
        return {
            RecommendationDecision.PARTICIPATE: "green",
            RecommendationDecision.NEEDS_ANALYSIS: "yellow",
            RecommendationDecision.DO_NOT_PARTICIPATE: "red",
        }[self.decision]


def recommend(case: object, generated_at: datetime) -> Recommendation:
    """Совместимое имя для нового агрегатного API без небезопасных scalar-входов."""
    from procurement.domain.cases import ProcurementCase, evaluate_case

    checked = ProcurementCase.model_validate(case)
    return evaluate_case(checked, at=generated_at)
