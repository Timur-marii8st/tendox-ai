"""Immutable, independently reviewed requirement sets bound to one case version.

The source table is retained row-for-row.  A row may contain an executable
``Requirement`` or remain an explicit manual-review obligation.  Approval of
the set therefore confirms coverage and normalization; it never turns an
unmapped row or a supplier card into technical ``PASS``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.domain.compliance import Verdict
from procurement.domain.provenance import Provenance
from procurement.domain.requirements import Requirement


class RequirementEntryDisposition(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class RequirementSetCoverageAssessment(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNRESOLVED = "UNRESOLVED"


class RequirementSetNormalizationAssessment(StrEnum):
    REVIEWED = "REVIEWED"
    UNRESOLVED = "UNRESOLVED"


class ReviewedRequirementEntry(BaseModel):
    """One source row, retained even when it cannot be executed safely."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    ordinal: int = Field(ge=1, le=500)
    raw_name: str = Field(min_length=1, max_length=1_000)
    raw_value: str = Field(min_length=1, max_length=4_000)
    provenance: Provenance
    disposition: RequirementEntryDisposition
    requirement: Requirement | None = None
    review_note: str = Field(min_length=1, max_length=2_000)

    @field_validator("raw_name", "raw_value", "review_note")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("requirement-set entry text must not be blank")
        return normalized

    @model_validator(mode="after")
    def _disposition_matches_payload(self) -> Self:
        if self.disposition is RequirementEntryDisposition.EXECUTABLE:
            if self.requirement is None:
                raise ValueError("executable entry requires a typed requirement")
            if self.requirement.provenance != self.provenance:
                raise ValueError("typed requirement provenance must match its source row")
        elif self.requirement is not None:
            raise ValueError("manual-review entry must not contain an executable requirement")
        return self


class ReviewedRequirementSetProposal(BaseModel):
    """Exact operator-prepared projection of every source-table row."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["reviewed-requirement-set-proposal-v1"] = (
        "reviewed-requirement-set-proposal-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    set_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_scope: str = Field(min_length=1, max_length=4_000)
    expected_entry_count: int = Field(ge=1, le=500)
    entries: tuple[ReviewedRequirementEntry, ...] = Field(min_length=1, max_length=500)
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: datetime
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("company_id", "set_id", "source_document_id", "declared_scope", "prepared_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("requirement-set proposal text must not be blank")
        return normalized

    @field_validator("prepared_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requirement-set proposal time must include timezone")
        return value

    @model_validator(mode="after")
    def _proposal_is_complete_and_bound(self) -> Self:
        if len(self.entries) != self.expected_entry_count:
            raise ValueError("entries must cover the declared source-row count")
        if tuple(item.ordinal for item in self.entries) != tuple(
            range(1, self.expected_entry_count + 1)
        ):
            raise ValueError("requirement-set entries must be contiguous and ordered")
        if any(item.provenance.document_id != self.source_document_id for item in self.entries):
            raise ValueError("every entry must point to the exact source document")
        payload = self.model_dump(mode="json", exclude={"proposal_sha256"})
        if canonical_json_sha256(payload) != self.proposal_sha256:
            raise ValueError("requirement-set proposal digest does not match payload")
        return self

    @property
    def executable_requirements(self) -> tuple[Requirement, ...]:
        return tuple(item.requirement for item in self.entries if item.requirement is not None)

    @property
    def manual_entry_ordinals(self) -> tuple[int, ...]:
        return tuple(item.ordinal for item in self.entries if item.requirement is None)


class ReviewedRequirementSetDecision(BaseModel):
    """Independent decision over one exact proposal digest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["reviewed-requirement-set-decision-v1"] = (
        "reviewed-requirement-set-decision-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    set_id: str = Field(min_length=1, max_length=200)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_assessment: RequirementSetCoverageAssessment
    normalization_assessment: RequirementSetNormalizationAssessment
    manual_review_entry_ordinals: tuple[int, ...] = Field(max_length=500)
    status: Verdict
    reason: str = Field(min_length=1, max_length=4_000)
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("company_id", "set_id", "reason", "reviewed_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("requirement-set decision text must not be blank")
        return normalized

    @field_validator("reviewed_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requirement-set review time must include timezone")
        return value

    @model_validator(mode="after")
    def _decision_is_bound(self) -> Self:
        if (
            tuple(sorted(set(self.manual_review_entry_ordinals)))
            != self.manual_review_entry_ordinals
        ):
            raise ValueError("manual-review ordinals must be unique and ordered")
        if self.status is Verdict.PASS and (
            self.coverage_assessment is not RequirementSetCoverageAssessment.CONFIRMED
            or self.normalization_assessment is not RequirementSetNormalizationAssessment.REVIEWED
        ):
            raise ValueError("PASS requires confirmed coverage and reviewed normalization")
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if canonical_json_sha256(payload) != self.decision_sha256:
            raise ValueError("requirement-set decision digest does not match payload")
        return self


class ReviewedRequirementSetRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    proposal: ReviewedRequirementSetProposal
    decision: ReviewedRequirementSetDecision | None = None

    @model_validator(mode="after")
    def _record_is_exact(self) -> Self:
        if self.decision is not None and (
            self.decision.company_id != self.proposal.company_id
            or self.decision.set_id != self.proposal.set_id
            or self.decision.proposal_sha256 != self.proposal.proposal_sha256
            or self.decision.manual_review_entry_ordinals != self.proposal.manual_entry_ordinals
        ):
            raise ValueError("requirement-set decision does not match proposal")
        return self


class CaseRequirementSetBinding(BaseModel):
    """Exact PASS decision selected for one immutable case version."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["case-requirement-set-binding-v1"] = "case-requirement-set-binding-v1"
    company_id: str = Field(min_length=1, max_length=200)
    binding_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    set_id: str = Field(min_length=1, max_length=200)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_by: str = Field(min_length=1, max_length=200)
    bound_by: str = Field(min_length=1, max_length=200)
    bound_at: datetime
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("bound_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requirement-set binding time must include timezone")
        return value

    @model_validator(mode="after")
    def _binding_is_exact(self) -> Self:
        if self.bound_by == self.reviewed_by:
            raise ValueError("case binder must differ from requirement-set reviewer")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_json_sha256(payload) != self.binding_sha256:
            raise ValueError("requirement-set binding digest does not match payload")
        return self


def build_reviewed_requirement_set_proposal(
    *,
    company_id: str,
    set_id: str,
    source_document_id: str,
    source_document_sha256: str,
    declared_scope: str,
    expected_entry_count: int,
    entries: tuple[ReviewedRequirementEntry, ...],
    prepared_by: str,
    prepared_at: datetime,
) -> ReviewedRequirementSetProposal:
    payload = {
        "schema_version": "reviewed-requirement-set-proposal-v1",
        "company_id": company_id,
        "set_id": set_id,
        "source_document_id": source_document_id,
        "source_document_sha256": source_document_sha256,
        "declared_scope": declared_scope,
        "expected_entry_count": expected_entry_count,
        "entries": entries,
        "prepared_by": prepared_by,
        "prepared_at": prepared_at,
    }
    return ReviewedRequirementSetProposal(
        company_id=company_id,
        set_id=set_id,
        source_document_id=source_document_id,
        source_document_sha256=source_document_sha256,
        declared_scope=declared_scope,
        expected_entry_count=expected_entry_count,
        entries=entries,
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        proposal_sha256=canonical_json_sha256(
            {**payload, "entries": tuple(item.model_dump(mode="json") for item in entries)}
        ),
    )


def build_reviewed_requirement_set_decision(
    proposal: ReviewedRequirementSetProposal,
    *,
    coverage_assessment: RequirementSetCoverageAssessment,
    normalization_assessment: RequirementSetNormalizationAssessment,
    status: Verdict,
    reason: str,
    reviewed_by: str,
    reviewed_at: datetime,
) -> ReviewedRequirementSetDecision:
    if reviewed_by.strip() == proposal.prepared_by:
        raise ValueError("requirement-set reviewer must differ from preparer")
    payload = {
        "schema_version": "reviewed-requirement-set-decision-v1",
        "company_id": proposal.company_id,
        "set_id": proposal.set_id,
        "proposal_sha256": proposal.proposal_sha256,
        "coverage_assessment": coverage_assessment,
        "normalization_assessment": normalization_assessment,
        "manual_review_entry_ordinals": proposal.manual_entry_ordinals,
        "status": status,
        "reason": reason,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
    }
    return ReviewedRequirementSetDecision(
        company_id=proposal.company_id,
        set_id=proposal.set_id,
        proposal_sha256=proposal.proposal_sha256,
        coverage_assessment=coverage_assessment,
        normalization_assessment=normalization_assessment,
        manual_review_entry_ordinals=proposal.manual_entry_ordinals,
        status=status,
        reason=reason,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        decision_sha256=canonical_json_sha256(payload),
    )


def build_case_requirement_set_binding(
    proposal: ReviewedRequirementSetProposal,
    decision: ReviewedRequirementSetDecision,
    *,
    binding_id: str,
    case_id: str,
    case_version: int,
    bound_by: str,
    bound_at: datetime,
) -> CaseRequirementSetBinding:
    ReviewedRequirementSetRecord(proposal=proposal, decision=decision)
    if decision.status is not Verdict.PASS:
        raise ValueError("only a PASS requirement-set decision can be bound to a case")
    payload = {
        "schema_version": "case-requirement-set-binding-v1",
        "company_id": proposal.company_id,
        "binding_id": binding_id,
        "case_id": case_id,
        "case_version": case_version,
        "set_id": proposal.set_id,
        "proposal_sha256": proposal.proposal_sha256,
        "decision_sha256": decision.decision_sha256,
        "reviewed_by": decision.reviewed_by,
        "bound_by": bound_by,
        "bound_at": bound_at,
    }
    return CaseRequirementSetBinding(
        company_id=proposal.company_id,
        binding_id=binding_id,
        case_id=case_id,
        case_version=case_version,
        set_id=proposal.set_id,
        proposal_sha256=proposal.proposal_sha256,
        decision_sha256=decision.decision_sha256,
        reviewed_by=decision.reviewed_by,
        bound_by=bound_by,
        bound_at=bound_at,
        binding_sha256=canonical_json_sha256(payload),
    )
