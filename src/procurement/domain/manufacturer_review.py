"""Evidence-bound independent review of a registry-declared manufacturer."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CitationClaim(StrEnum):
    LEGAL_NAME = "LEGAL_NAME"
    COUNTRY = "COUNTRY"
    IDENTIFIER_SCHEME = "IDENTIFIER_SCHEME"
    REGISTRATION_ID = "REGISTRATION_ID"
    MANUFACTURER_ROLE = "MANUFACTURER_ROLE"


class LegalIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    legal_name: str = Field(min_length=1, max_length=500)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    identifier_scheme: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9._-]+$")
    registration_id: str = Field(min_length=1, max_length=120)

    @field_validator("legal_name", "registration_id")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MANUFACTURER_IDENTITY_BLANK")
        return value.strip()


class StableManufacturerDossier(BaseModel):
    """Immutable source fields; date-relative validity is deliberately excluded."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: str
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_index: int = Field(ge=1, le=10)
    registry_number: str
    product_name: str
    source_manufacturer_name: str
    record_url: str
    document_expires_on: str | None
    role: Literal["MANUFACTURER_SOURCE_DECLARATION"] = "MANUFACTURER_SOURCE_DECLARATION"


class ManufacturerCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    artifact_id: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1, le=100_000)
    locator: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=1000)
    claims: tuple[CitationClaim, ...] = Field(min_length=1, max_length=5)

    @field_validator("artifact_id", "locator", "quote")
    @classmethod
    def citation_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MANUFACTURER_CITATION_BLANK")
        return value.strip()

    @field_validator("claims")
    @classmethod
    def sorted_unique_claims(cls, value: tuple[CitationClaim, ...]) -> tuple[CitationClaim, ...]:
        if len(set(value)) != len(value):
            raise ValueError("MANUFACTURER_CITATION_CLAIMS_DUPLICATE")
        return tuple(sorted(value, key=str))


class ManufacturerReviewProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["manufacturer-review-proposal-v1"] = (
        "manufacturer-review-proposal-v1"
    )
    proposal_id: str
    command_id: str
    dossier: StableManufacturerDossier
    dossier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claimed_identity: LegalIdentity
    citations: tuple[ManufacturerCitation, ...] = Field(min_length=1, max_length=3)
    proposed_by: str
    proposed_at: AwareDatetime
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("proposed_by")
    @classmethod
    def proposer_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MANUFACTURER_PROPOSER_BLANK")
        return value.strip()

    @model_validator(mode="after")
    def exact(self) -> Self:
        for identity in (self.proposal_id, self.command_id):
            if str(uuid.UUID(identity)) != identity:
                raise ValueError("MANUFACTURER_REVIEW_UUID_INVALID")
        if canonical_sha256(self.dossier) != self.dossier_sha256:
            raise ValueError("MANUFACTURER_DOSSIER_SHA_CONFLICT")
        if proposal_digest(self) != self.proposal_sha256:
            raise ValueError("MANUFACTURER_PROPOSAL_SHA_CONFLICT")
        return self


class ManufacturerReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["manufacturer-review-decision-v1"] = (
        "manufacturer-review-decision-v1"
    )
    decision_id: str
    command_id: str
    proposal_id: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dossier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_status: ReviewStatus
    role_status: ReviewStatus
    official_origin_confirmed: bool = Field(strict=True)
    identity_fields_confirmed: bool = Field(strict=True)
    exact_product_link_confirmed: bool = Field(strict=True)
    effective_until: AwareDatetime | None
    rationale: str = Field(min_length=1, max_length=2000)
    citation_indexes: tuple[Annotated[int, Field(strict=True, ge=0, le=2)], ...] = Field(
        min_length=1, max_length=3
    )
    reviewed_by: str
    reviewed_at: AwareDatetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("citation_indexes")
    @classmethod
    def unique_indexes(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value):
            raise ValueError("MANUFACTURER_DECISION_CITATIONS_INVALID")
        return value

    @field_validator("rationale", "reviewed_by")
    @classmethod
    def decision_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MANUFACTURER_DECISION_TEXT_BLANK")
        return value.strip()

    @model_validator(mode="after")
    def exact(self) -> Self:
        for identity in (self.decision_id, self.command_id, self.proposal_id):
            if str(uuid.UUID(identity)) != identity:
                raise ValueError("MANUFACTURER_REVIEW_UUID_INVALID")
        if decision_digest(self) != self.decision_sha256:
            raise ValueError("MANUFACTURER_DECISION_SHA_CONFLICT")
        return self


def canonical_sha256(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def proposal_digest(value: ManufacturerReviewProposal) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"proposal_sha256"}))


def decision_digest(value: ManufacturerReviewDecision) -> str:
    return canonical_sha256(value.model_dump(mode="json", exclude={"decision_sha256"}))


def validate_decision(
    proposal: ManufacturerReviewProposal,
    decision: ManufacturerReviewDecision,
    *,
    artifact_uploaders: set[str],
) -> None:
    """Reject false PASS while preserving explicit FAIL and UNKNOWN decisions."""
    if (
        decision.proposal_id != proposal.proposal_id
        or decision.proposal_sha256 != proposal.proposal_sha256
    ):
        raise ValueError("MANUFACTURER_DECISION_PROPOSAL_CONFLICT")
    if decision.dossier_sha256 != proposal.dossier_sha256:
        raise ValueError("MANUFACTURER_DECISION_DOSSIER_CONFLICT")
    if decision.reviewed_by == proposal.proposed_by or decision.reviewed_by in artifact_uploaders:
        raise ValueError("MANUFACTURER_REVIEW_NOT_INDEPENDENT")
    if any(index >= len(proposal.citations) for index in decision.citation_indexes):
        raise ValueError("MANUFACTURER_DECISION_CITATIONS_INVALID")
    selected = [proposal.citations[index] for index in decision.citation_indexes]
    claims = set().union(*(citation.claims for citation in selected))
    required_identity = {
        CitationClaim.LEGAL_NAME,
        CitationClaim.COUNTRY,
        CitationClaim.IDENTIFIER_SCHEME,
        CitationClaim.REGISTRATION_ID,
    }
    future = (
        decision.effective_until is not None
        and decision.effective_until > decision.reviewed_at
    )
    if decision.identity_status is ReviewStatus.PASS and not (
        decision.official_origin_confirmed
        and decision.identity_fields_confirmed
        and future
        and required_identity <= claims
    ):
        raise ValueError("MANUFACTURER_IDENTITY_PASS_UNSUPPORTED")
    if decision.role_status is ReviewStatus.PASS and not (
        decision.identity_status is ReviewStatus.PASS
        and decision.exact_product_link_confirmed
        and future
        and CitationClaim.MANUFACTURER_ROLE in claims
    ):
        raise ValueError("MANUFACTURER_ROLE_PASS_UNSUPPORTED")


def current_review_status(
    decision: ManufacturerReviewDecision, *, at: datetime | None = None
) -> ReviewStatus:
    instant = at or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("MANUFACTURER_REVIEW_AT_NAIVE")
    if decision.identity_status is ReviewStatus.FAIL or decision.role_status is ReviewStatus.FAIL:
        return ReviewStatus.FAIL
    if decision.effective_until is None:
        return ReviewStatus.UNKNOWN
    if instant >= decision.effective_until:
        return ReviewStatus.FAIL
    if decision.identity_status is ReviewStatus.PASS and decision.role_status is ReviewStatus.PASS:
        return ReviewStatus.PASS
    return ReviewStatus.UNKNOWN
