"""Immutable application-package proposal from one approved participation decision."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import PureWindowsPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.participation_decision import (
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
)
from procurement.domain.cases import ProcurementCase, case_input_digest
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import Recommendation, RecommendationDecision
from procurement.domain.economics import _finite_decimal


class ApplicationRequirementKind(StrEnum):
    FORM = "FORM"
    DECLARATION = "DECLARATION"
    ELIGIBILITY = "ELIGIBILITY"
    CERTIFICATE = "CERTIFICATE"
    AUTHORITY = "AUTHORITY"
    TECHNICAL_PROPOSAL = "TECHNICAL_PROPOSAL"
    PRICE_PROPOSAL = "PRICE_PROPOSAL"
    OTHER = "OTHER"


class ApplicationDocumentRequirement(BaseModel):
    """One manually identified necessary item backed by exact tender evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=500)
    kind: ApplicationRequirementKind
    title: str = Field(min_length=1, max_length=1_000)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1, max_length=1_000)

    @field_validator("title", "source_document_id", "source_locator")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("application requirement text must not be blank")
        return normalized


class ApplicationAttachmentInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=500)
    requirement_ordinals: tuple[int, ...] = Field(min_length=1, max_length=500)
    document_id: str = Field(min_length=1, max_length=200)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    submission_filename: str = Field(min_length=1, max_length=255)

    @field_validator("document_id", "submission_filename")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("application attachment text must not be blank")
        return normalized

    @model_validator(mode="after")
    def _safe_filename_and_mappings(self) -> Self:
        if (
            PureWindowsPath(self.submission_filename).name != self.submission_filename
            or "/" in self.submission_filename
            or "\\" in self.submission_filename
            or self.submission_filename in {".", ".."}
            or any(ord(char) < 32 or ord(char) == 127 for char in self.submission_filename)
        ):
            raise ValueError("submission filename must be a plain filename")
        if self.requirement_ordinals != tuple(sorted(set(self.requirement_ordinals))):
            raise ValueError("attachment requirement ordinals must be sorted and unique")
        return self


class ApplicationAttachment(ApplicationAttachmentInput):
    original_filename: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=200)


class ApplicationPackageEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case: ProcurementCase
    participation: ParticipationDecisionRecord

    @model_validator(mode="after")
    def _approved_exact_case(self) -> Self:
        decision = self.participation.decision
        if decision is None or decision.status is not ParticipationDecisionStatus.APPROVED:
            raise ValueError("application package requires APPROVED participation")
        if (
            self.case.company_id != decision.company_id
            or self.case.case_id != decision.case_id
            or self.case.version != decision.case_version
            or case_input_digest(self.case)
            != self.participation.evidence.case_input_sha256
        ):
            raise ValueError("approved participation does not belong to exact case")
        return self


class ApplicationPackage(BaseModel):
    """Exact draft manifest; it is not reviewed or authorized for submission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["application-package-v1"] = "application-package-v1"
    company_id: str = Field(min_length=1, max_length=200)
    package_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    case_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tender_id: str = Field(min_length=1, max_length=200)
    participation_decision_id: str = Field(min_length=1, max_length=200)
    participation_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_id: str = Field(min_length=1, max_length=200)
    evaluation_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_price_ex_vat: Decimal = Field(gt=0)
    minimum_bid_price: Decimal = Field(gt=0)
    currency: Literal["RUB"] = "RUB"
    requirements: tuple[ApplicationDocumentRequirement, ...] = Field(
        min_length=1, max_length=500
    )
    attachments: tuple[ApplicationAttachment, ...] = Field(min_length=1, max_length=500)
    current_recommendation: Recommendation
    coverage_status: Literal[Verdict.UNKNOWN] = Verdict.UNKNOWN
    review_status: Literal["PENDING_REVIEW"] = "PENDING_REVIEW"
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: datetime
    external_action_authorized: Literal[False] = False
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("proposed_price_ex_vat", "minimum_bid_price", mode="before")
    @classmethod
    def _exact_money(cls, value: object) -> Decimal:
        return _finite_decimal(value)  # type: ignore[arg-type]

    @field_validator("prepared_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("application package time must include timezone")
        return value

    @model_validator(mode="after")
    def _exact_pending_manifest(self) -> Self:
        if self.current_recommendation.generated_at != self.prepared_at:
            raise ValueError("current recommendation time differs from package time")
        if self.current_recommendation.decision is not RecommendationDecision.PARTICIPATE:
            raise ValueError("application package requires current PARTICIPATE")
        if self.current_recommendation.minimum_bid_price != self.minimum_bid_price:
            raise ValueError("application package price floor differs from recommendation")
        if self.proposed_price_ex_vat < self.minimum_bid_price:
            raise ValueError("proposed application price is below price floor")
        if tuple(item.ordinal for item in self.requirements) != tuple(
            range(1, len(self.requirements) + 1)
        ):
            raise ValueError("application requirement ordinals must be contiguous")
        if tuple(item.ordinal for item in self.attachments) != tuple(
            range(1, len(self.attachments) + 1)
        ):
            raise ValueError("application attachment ordinals must be contiguous")
        requirement_ordinals = {item.ordinal for item in self.requirements}
        mapped = {
            ordinal
            for attachment in self.attachments
            for ordinal in attachment.requirement_ordinals
        }
        if mapped != requirement_ordinals:
            raise ValueError("every declared requirement must have an exact attachment")
        if len({item.document_id for item in self.attachments}) != len(self.attachments):
            raise ValueError("application attachment document IDs must be unique")
        filenames = [item.submission_filename.casefold() for item in self.attachments]
        if len(set(filenames)) != len(filenames):
            raise ValueError("application submission filenames must be unique")
        payload = self.model_dump(mode="json", exclude={"package_sha256"})
        if canonical_json_sha256(payload) != self.package_sha256:
            raise ValueError("application package digest does not match payload")
        return self


class ApplicationPackageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: ApplicationPackageEvidence
    package: ApplicationPackage | None = None

    @model_validator(mode="after")
    def _package_matches_evidence(self) -> Self:
        if self.package is None:
            return self
        decision = self.evidence.participation.decision
        assert decision is not None
        if (
            self.package.company_id != self.evidence.case.company_id
            or self.package.case_id != self.evidence.case.case_id
            or self.package.case_version != self.evidence.case.version
            or self.package.case_input_sha256 != case_input_digest(self.evidence.case)
            or self.package.tender_id != self.evidence.case.tender.tender_id
            or self.package.participation_decision_id != decision.decision_id
            or self.package.participation_decision_sha256 != decision.decision_sha256
            or self.package.evaluation_id != decision.evaluation_id
            or self.package.evaluation_evidence_sha256
            != decision.evaluation_evidence_sha256
        ):
            raise ValueError("application package differs from exact approved evidence")
        rebuilt = build_application_package(
            self.evidence,
            package_id=self.package.package_id,
            proposed_price_ex_vat=self.package.proposed_price_ex_vat,
            requirements=self.package.requirements,
            attachments=self.package.attachments,
            current_recommendation=self.package.current_recommendation,
            prepared_by=self.package.prepared_by,
            prepared_at=self.package.prepared_at,
        )
        if rebuilt != self.package:
            raise ValueError("application package cannot be rebuilt from exact evidence")
        return self


def build_application_package(
    evidence: ApplicationPackageEvidence,
    *,
    package_id: str,
    proposed_price_ex_vat: Decimal,
    requirements: tuple[ApplicationDocumentRequirement, ...],
    attachments: tuple[ApplicationAttachment, ...],
    current_recommendation: Recommendation,
    prepared_by: str,
    prepared_at: datetime,
) -> ApplicationPackage:
    checked = ApplicationPackageEvidence.model_validate(evidence.model_dump(mode="python"))
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("application package time must include timezone")
    if current_recommendation.generated_at != prepared_at:
        raise ValueError("current recommendation must be calculated at package time")
    if not checked.case.tender.accepts_applications_at(prepared_at):
        raise ValueError("application submission window is closed")
    if current_recommendation.decision is not RecommendationDecision.PARTICIPATE:
        raise ValueError("application package requires current PARTICIPATE")
    floor = current_recommendation.minimum_bid_price
    if floor is None:
        raise ValueError("application package requires a current price floor")
    proposed_price_ex_vat = _finite_decimal(proposed_price_ex_vat)
    if proposed_price_ex_vat > checked.case.nmck_ex_vat:
        raise ValueError("proposed application price cannot exceed exact NMCK")
    prepared_at = prepared_at.astimezone(UTC)
    current_recommendation = Recommendation.model_validate(
        current_recommendation.model_dump(mode="python")
    ).model_copy(update={"generated_at": prepared_at})
    decision = checked.participation.decision
    assert decision is not None
    fields = {
        "company_id": checked.case.company_id,
        "package_id": package_id,
        "case_id": checked.case.case_id,
        "case_version": checked.case.version,
        "case_input_sha256": case_input_digest(checked.case),
        "tender_id": checked.case.tender.tender_id,
        "participation_decision_id": decision.decision_id,
        "participation_decision_sha256": decision.decision_sha256,
        "evaluation_id": decision.evaluation_id,
        "evaluation_evidence_sha256": decision.evaluation_evidence_sha256,
        "proposed_price_ex_vat": proposed_price_ex_vat,
        "minimum_bid_price": floor,
        "currency": "RUB",
        "requirements": requirements,
        "attachments": attachments,
        "current_recommendation": current_recommendation,
        "coverage_status": Verdict.UNKNOWN,
        "review_status": "PENDING_REVIEW",
        "prepared_by": prepared_by,
        "prepared_at": prepared_at,
        "external_action_authorized": False,
    }
    digest = canonical_json_sha256({"schema_version": "application-package-v1", **fields})
    return ApplicationPackage(**fields, package_sha256=digest)


__all__ = [
    "ApplicationAttachment",
    "ApplicationAttachmentInput",
    "ApplicationDocumentRequirement",
    "ApplicationPackage",
    "ApplicationPackageEvidence",
    "ApplicationPackageRecord",
    "ApplicationRequirementKind",
    "build_application_package",
]
