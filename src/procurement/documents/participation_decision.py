"""Independent human decision over one exact positive case evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.domain.decisions import Recommendation, RecommendationDecision


class ParticipationDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ParticipationEvaluationEvidence(BaseModel):
    """Exact persisted evaluation plus the actor recorded by its audit event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["participation-evaluation-evidence-v1"] = (
        "participation-evaluation-evidence-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    evaluation_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    effective_at: datetime
    case_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine_version: str = Field(min_length=1, max_length=200)
    recommendation: Recommendation
    evaluated_by: str = Field(min_length=1, max_length=200)
    evaluated_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("company_id", "evaluation_id", "case_id", "engine_version", "evaluated_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("participation evaluation evidence text must not be blank")
        return normalized

    @field_validator("effective_at", "evaluated_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("participation evaluation evidence time must include timezone")
        return value

    @model_validator(mode="after")
    def _exact_digest(self) -> Self:
        if self.recommendation.generated_at != self.effective_at:
            raise ValueError("recommendation time does not match evaluation effective_at")
        payload = self.model_dump(mode="json", exclude={"evidence_sha256"})
        if canonical_json_sha256(payload) != self.evidence_sha256:
            raise ValueError("participation evaluation evidence digest does not match payload")
        return self


class ParticipationDecision(BaseModel):
    """Terminal internal approval or rejection; it authorizes no external action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["participation-decision-v1"] = "participation-decision-v1"
    company_id: str = Field(min_length=1, max_length=200)
    decision_id: str = Field(min_length=1, max_length=200)
    evaluation_id: str = Field(min_length=1, max_length=200)
    evaluation_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    status: ParticipationDecisionStatus
    current_recommendation: Recommendation
    reason: str = Field(min_length=1, max_length=4_000)
    decided_by: str = Field(min_length=1, max_length=200)
    decided_at: datetime
    external_action_authorized: Literal[False] = False
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id", "decision_id", "evaluation_id", "case_id", "reason", "decided_by"
    )
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("participation decision text must not be blank")
        return normalized

    @field_validator("decided_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("participation decision time must include timezone")
        return value

    @model_validator(mode="after")
    def _exact_digest(self) -> Self:
        if self.current_recommendation.generated_at != self.decided_at:
            raise ValueError("current recommendation time does not match decision time")
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if canonical_json_sha256(payload) != self.decision_sha256:
            raise ValueError("participation decision digest does not match payload")
        return self


class ParticipationDecisionRecord(BaseModel):
    """Exact evaluation evidence and its optional terminal human decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: ParticipationEvaluationEvidence
    decision: ParticipationDecision | None = None

    @model_validator(mode="after")
    def _decision_matches_evidence(self) -> Self:
        if self.decision is None:
            return self
        if (
            self.decision.company_id != self.evidence.company_id
            or self.decision.evaluation_id != self.evidence.evaluation_id
            or self.decision.evaluation_evidence_sha256 != self.evidence.evidence_sha256
            or self.decision.case_id != self.evidence.case_id
            or self.decision.case_version != self.evidence.case_version
        ):
            raise ValueError("participation decision differs from exact evaluation evidence")
        if self.evidence.recommendation.decision is not RecommendationDecision.PARTICIPATE:
            raise ValueError("participation decision source is not PARTICIPATE")
        if self.decision.decided_by == self.evidence.evaluated_by:
            raise ValueError("participation decision is not independently reviewed")
        if (
            self.decision.status is ParticipationDecisionStatus.APPROVED
            and self.decision.current_recommendation.decision
            is not RecommendationDecision.PARTICIPATE
        ):
            raise ValueError("approved participation decision lacks current PARTICIPATE")
        return self


def build_participation_evaluation_evidence(
    *,
    company_id: str,
    evaluation_id: str,
    case_id: str,
    case_version: int,
    effective_at: datetime,
    case_input_sha256: str,
    engine_version: str,
    recommendation: Recommendation,
    evaluated_by: str,
    evaluated_at: datetime,
) -> ParticipationEvaluationEvidence:
    if effective_at.tzinfo is None or effective_at.utcoffset() is None:
        raise ValueError("participation evaluation effective_at must include timezone")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("participation evaluation evaluated_at must include timezone")
    effective_at = effective_at.astimezone(UTC)
    evaluated_at = evaluated_at.astimezone(UTC)
    recommendation = Recommendation.model_validate(
        recommendation.model_dump(mode="python")
    ).model_copy(update={"generated_at": effective_at})
    fields = {
        "company_id": company_id,
        "evaluation_id": evaluation_id,
        "case_id": case_id,
        "case_version": case_version,
        "effective_at": effective_at,
        "case_input_sha256": case_input_sha256,
        "engine_version": engine_version,
        "recommendation": recommendation,
        "evaluated_by": evaluated_by,
        "evaluated_at": evaluated_at,
    }
    digest = canonical_json_sha256(
        {"schema_version": "participation-evaluation-evidence-v1", **fields}
    )
    return ParticipationEvaluationEvidence(**fields, evidence_sha256=digest)


def build_participation_decision(
    evidence: ParticipationEvaluationEvidence,
    *,
    decision_id: str,
    status: ParticipationDecisionStatus,
    current_recommendation: Recommendation,
    reason: str,
    decided_by: str,
    decided_at: datetime,
) -> ParticipationDecision:
    checked = ParticipationEvaluationEvidence.model_validate(evidence.model_dump(mode="python"))
    if checked.recommendation.decision is not RecommendationDecision.PARTICIPATE:
        raise ValueError("participation decision requires an exact PARTICIPATE evaluation")
    if decided_by.strip() == checked.evaluated_by:
        raise ValueError("participation approver must differ from evaluation actor")
    if decided_at.tzinfo is None or decided_at.utcoffset() is None:
        raise ValueError("participation decision time must include timezone")
    if current_recommendation.generated_at != decided_at:
        raise ValueError("current recommendation must be calculated at decision time")
    if (
        status is ParticipationDecisionStatus.APPROVED
        and current_recommendation.decision is not RecommendationDecision.PARTICIPATE
    ):
        raise ValueError("APPROVED requires a current PARTICIPATE recommendation")
    decided_at = decided_at.astimezone(UTC)
    current_recommendation = Recommendation.model_validate(
        current_recommendation.model_dump(mode="python")
    ).model_copy(update={"generated_at": decided_at})
    fields = {
        "company_id": checked.company_id,
        "decision_id": decision_id,
        "evaluation_id": checked.evaluation_id,
        "evaluation_evidence_sha256": checked.evidence_sha256,
        "case_id": checked.case_id,
        "case_version": checked.case_version,
        "status": status,
        "current_recommendation": current_recommendation,
        "reason": reason,
        "decided_by": decided_by,
        "decided_at": decided_at,
        "external_action_authorized": False,
    }
    digest = canonical_json_sha256({"schema_version": "participation-decision-v1", **fields})
    return ParticipationDecision(**fields, decision_sha256=digest)


__all__ = [
    "ParticipationDecision",
    "ParticipationDecisionRecord",
    "ParticipationDecisionStatus",
    "ParticipationEvaluationEvidence",
    "build_participation_decision",
    "build_participation_evaluation_evidence",
]
