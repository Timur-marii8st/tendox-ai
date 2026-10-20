"""Independent row-complete review of one exact server-offer proposal."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.reviewed_requirements import ReviewedRequirementSetRecord
from procurement.documents.server_offer import ServerOfferProposal
from procurement.domain.compliance import Verdict


class ServerOfferEvidenceKind(StrEnum):
    BOM_LINE = "BOM_LINE"
    COMMERCIAL_TERMS = "COMMERCIAL_TERMS"


class ServerOfferEvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ServerOfferEvidenceKind
    bom_line_ordinal: int | None = Field(default=None, ge=1, le=500)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.kind is ServerOfferEvidenceKind.BOM_LINE) != (
            self.bom_line_ordinal is not None
        ):
            raise ValueError("BOM_LINE alone requires an ordinal")
        return self


class ServerOfferRequirementDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_ordinal: int = Field(ge=1, le=500)
    status: Verdict
    reason: str = Field(min_length=1, max_length=2_000)
    evidence: tuple[ServerOfferEvidenceRef, ...] = Field(default=(), max_length=50)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _known_status_has_evidence(self) -> Self:
        if self.status is not Verdict.UNKNOWN and not self.evidence:
            raise ValueError("known requirement decision requires offer evidence")
        if len(self.evidence) != len(set(self.evidence)):
            raise ValueError("requirement evidence references must be unique")
        return self


class ServerOfferBomScopeAssessment(StrEnum):
    CONFIRMED_COMPLETE = "CONFIRMED_COMPLETE"
    CONFIRMED_INCOMPLETE = "CONFIRMED_INCOMPLETE"
    UNRESOLVED = "UNRESOLVED"


class ServerOfferCommercialAssessment(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class ServerOfferReviewEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: ServerOfferProposal
    requirement_set: ReviewedRequirementSetRecord

    @model_validator(mode="after")
    def _same_exact_scope(self) -> Self:
        decision = self.requirement_set.decision
        if decision is None or decision.status is not Verdict.PASS:
            raise ValueError("offer review requires terminal PASS requirement set")
        if (
            self.proposal.company_id != self.requirement_set.proposal.company_id
            or self.proposal.requirement_set_binding_sha256 == ""
        ):
            raise ValueError("offer and requirement evidence do not share tenant scope")
        return self


class ServerOfferReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["server-offer-review-decision-v1"] = (
        "server-offer-review-decision-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    offer_id: str = Field(min_length=1, max_length=200)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_set_id: str = Field(min_length=1, max_length=200)
    requirement_set_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_set_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_decisions: tuple[ServerOfferRequirementDecision, ...] = Field(
        min_length=1, max_length=500
    )
    bom_scope_assessment: ServerOfferBomScopeAssessment
    commercial_terms_assessment: ServerOfferCommercialAssessment
    quote_gate_status: Verdict
    quote_gate_reason: str = Field(min_length=1, max_length=2_000)
    status: Verdict
    reason: str = Field(min_length=1, max_length=4_000)
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reason", "quote_gate_reason")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("reviewed_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review time must include timezone")
        return value

    @model_validator(mode="after")
    def _decision_digest(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if canonical_json_sha256(payload) != self.decision_sha256:
            raise ValueError("server-offer review decision digest does not match payload")
        return self


class ServerOfferReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: ServerOfferReviewEvidence
    decision: ServerOfferReviewDecision | None = None

    @model_validator(mode="after")
    def _exact_decision(self) -> Self:
        if self.decision is not None:
            expected = build_server_offer_review_decision(
                self.evidence,
                requirement_decisions=self.decision.requirement_decisions,
                bom_scope_assessment=self.decision.bom_scope_assessment,
                commercial_terms_assessment=self.decision.commercial_terms_assessment,
                reason=self.decision.reason,
                reviewed_by=self.decision.reviewed_by,
                reviewed_at=self.decision.reviewed_at,
            )
            if expected != self.decision:
                raise ValueError("review decision does not match offer evidence")
        return self


def _quote_gate(proposal: ServerOfferProposal, reviewed_at: datetime) -> tuple[Verdict, str]:
    terms = proposal.commercial_terms
    if terms.covers_full_scope is False:
        return Verdict.FAIL, "КП явно не покрывает весь заявленный scope"
    if reviewed_at >= terms.valid_until:
        return Verdict.FAIL, "срок действия КП истёк"
    if reviewed_at < terms.issued_at:
        return Verdict.UNKNOWN, "КП ещё не вступило в действие"
    if not terms.is_complete:
        return Verdict.UNKNOWN, "не подтверждены НДС, полный scope или коммерческие условия"
    return Verdict.PASS, "полное КП действует на момент review"


def build_server_offer_review_decision(
    evidence: ServerOfferReviewEvidence,
    *,
    requirement_decisions: tuple[ServerOfferRequirementDecision, ...],
    bom_scope_assessment: ServerOfferBomScopeAssessment,
    commercial_terms_assessment: ServerOfferCommercialAssessment,
    reason: str,
    reviewed_by: str,
    reviewed_at: datetime,
) -> ServerOfferReviewDecision:
    proposal = evidence.proposal
    requirement_set = evidence.requirement_set
    if reviewed_by == proposal.prepared_by:
        raise ValueError("server-offer reviewer must differ from proposal preparer")
    expected = tuple(range(1, requirement_set.proposal.expected_entry_count + 1))
    if tuple(item.requirement_ordinal for item in requirement_decisions) != expected:
        raise ValueError("review must decide every requirement ordinal exactly once")
    max_bom_ordinal = len(proposal.bom_lines)
    if any(
        ref.kind is ServerOfferEvidenceKind.BOM_LINE
        and (ref.bom_line_ordinal or 0) > max_bom_ordinal
        for item in requirement_decisions
        for ref in item.evidence
    ):
        raise ValueError("requirement decision references a missing BOM line")
    quote_status, quote_reason = _quote_gate(proposal, reviewed_at)
    has_fail = (
        any(item.status is Verdict.FAIL for item in requirement_decisions)
        or bom_scope_assessment is ServerOfferBomScopeAssessment.CONFIRMED_INCOMPLETE
        or commercial_terms_assessment is ServerOfferCommercialAssessment.REJECTED
        or quote_status is Verdict.FAIL
    )
    can_pass = (
        all(item.status is Verdict.PASS for item in requirement_decisions)
        and bom_scope_assessment is ServerOfferBomScopeAssessment.CONFIRMED_COMPLETE
        and commercial_terms_assessment is ServerOfferCommercialAssessment.CONFIRMED
        and quote_status is Verdict.PASS
    )
    status = Verdict.FAIL if has_fail else Verdict.PASS if can_pass else Verdict.UNKNOWN
    decision = requirement_set.decision
    assert decision is not None
    draft = ServerOfferReviewDecision.model_construct(
        schema_version="server-offer-review-decision-v1",
        company_id=proposal.company_id,
        offer_id=proposal.offer_id,
        proposal_sha256=proposal.proposal_sha256,
        requirement_set_id=requirement_set.proposal.set_id,
        requirement_set_proposal_sha256=requirement_set.proposal.proposal_sha256,
        requirement_set_decision_sha256=decision.decision_sha256,
        requirement_decisions=requirement_decisions,
        bom_scope_assessment=bom_scope_assessment,
        commercial_terms_assessment=commercial_terms_assessment,
        quote_gate_status=quote_status,
        quote_gate_reason=quote_reason,
        status=status,
        reason=reason,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        decision_sha256="0" * 64,
    )
    digest = canonical_json_sha256(draft.model_dump(mode="json", exclude={"decision_sha256"}))
    return ServerOfferReviewDecision.model_validate(
        draft.model_dump(mode="python") | {"decision_sha256": digest}
    )
