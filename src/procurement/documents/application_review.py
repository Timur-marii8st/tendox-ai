"""Independent exact-package review; a positive result is still not submission approval."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.application_package import ApplicationPackageRecord
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.domain.cases import evaluate_case
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import Recommendation, RecommendationDecision


class ApplicationInventoryAssessment(StrEnum):
    CONFIRMED_COMPLETE = "CONFIRMED_COMPLETE"
    CONFIRMED_MISSING = "CONFIRMED_MISSING"
    UNRESOLVED = "UNRESOLVED"


class ApplicationPriceAssessment(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class ApplicationRequirementReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_ordinal: int = Field(ge=1, le=500)
    status: Verdict
    reason: str = Field(min_length=1, max_length=2_000)
    attachment_ordinals: tuple[int, ...] = Field(default=(), max_length=500)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("application requirement review reason must not be blank")
        return value

    @model_validator(mode="after")
    def _evidence_refs(self) -> Self:
        if self.attachment_ordinals != tuple(sorted(set(self.attachment_ordinals))):
            raise ValueError("application attachment references must be sorted and unique")
        if self.status is not Verdict.UNKNOWN and not self.attachment_ordinals:
            raise ValueError("known requirement review requires exact attachment refs")
        return self


class ApplicationAttachmentReview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_ordinal: int = Field(ge=1, le=500)
    status: Verdict
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("application attachment review reason must not be blank")
        return value


class ApplicationReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["application-review-decision-v1"] = (
        "application-review-decision-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    package_id: str = Field(min_length=1, max_length=200)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    participation_decision_id: str = Field(min_length=1, max_length=200)
    participation_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_reviews: tuple[ApplicationRequirementReview, ...] = Field(
        min_length=1, max_length=500
    )
    attachment_reviews: tuple[ApplicationAttachmentReview, ...] = Field(
        min_length=1, max_length=500
    )
    inventory_assessment: ApplicationInventoryAssessment
    inventory_source_document_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    inventory_reason: str = Field(min_length=1, max_length=4_000)
    price_assessment: ApplicationPriceAssessment
    price_reason: str = Field(min_length=1, max_length=4_000)
    current_recommendation: Recommendation
    deadline_gate: Verdict
    price_gate: Verdict
    status: Verdict
    reason: str = Field(min_length=1, max_length=4_000)
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime
    external_action_authorized: Literal[False] = False
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("inventory_reason", "price_reason", "reason")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("application review reason must not be blank")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("application review time must include timezone")
        return value

    @model_validator(mode="after")
    def _digest(self) -> Self:
        if self.current_recommendation.generated_at != self.reviewed_at:
            raise ValueError("current recommendation time differs from review")
        if canonical_json_sha256(
            self.model_dump(mode="json", exclude={"decision_sha256"})
        ) != self.decision_sha256:
            raise ValueError("application review decision digest differs")
        return self


class ApplicationReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: ApplicationPackageRecord
    decision: ApplicationReviewDecision | None = None

    @model_validator(mode="after")
    def _exact_decision(self) -> Self:
        if self.decision is None:
            return self
        expected = build_application_review_decision(
            self.evidence,
            requirement_reviews=self.decision.requirement_reviews,
            attachment_reviews=self.decision.attachment_reviews,
            inventory_assessment=self.decision.inventory_assessment,
            inventory_source_document_ids=self.decision.inventory_source_document_ids,
            inventory_reason=self.decision.inventory_reason,
            price_assessment=self.decision.price_assessment,
            price_reason=self.decision.price_reason,
            reason=self.decision.reason,
            reviewed_by=self.decision.reviewed_by,
            reviewed_at=self.decision.reviewed_at,
        )
        if expected != self.decision:
            raise ValueError("application review differs from exact package evidence")
        return self


def build_application_review_decision(
    evidence: ApplicationPackageRecord,
    *,
    requirement_reviews: tuple[ApplicationRequirementReview, ...],
    attachment_reviews: tuple[ApplicationAttachmentReview, ...],
    inventory_assessment: ApplicationInventoryAssessment,
    inventory_source_document_ids: tuple[str, ...],
    inventory_reason: str,
    price_assessment: ApplicationPriceAssessment,
    price_reason: str,
    reason: str,
    reviewed_by: str,
    reviewed_at: datetime,
) -> ApplicationReviewDecision:
    checked = ApplicationPackageRecord.model_validate(evidence.model_dump(mode="python"))
    package = checked.package
    if package is None:
        raise ValueError("application review requires a persisted package")
    if not reviewed_by.strip() or reviewed_by == package.prepared_by:
        raise ValueError("application reviewer must differ from package preparer")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("application review time must include timezone")
    if reviewed_at < package.prepared_at:
        raise ValueError("application review cannot precede package preparation")
    if tuple(item.requirement_ordinal for item in requirement_reviews) != tuple(
        range(1, len(package.requirements) + 1)
    ):
        raise ValueError("review must cover every package requirement in order")
    if tuple(item.attachment_ordinal for item in attachment_reviews) != tuple(
        range(1, len(package.attachments) + 1)
    ):
        raise ValueError("review must cover every package attachment in order")
    for row in requirement_reviews:
        allowed = {
            item.ordinal
            for item in package.attachments
            if row.requirement_ordinal in item.requirement_ordinals
        }
        if not set(row.attachment_ordinals).issubset(allowed):
            raise ValueError("requirement review references an unrelated attachment")
        if row.status is Verdict.PASS and set(row.attachment_ordinals) != allowed:
            raise ValueError("PASS must review every mapped attachment")
    source_ids = {item.source_document_id for item in package.requirements}
    if (
        inventory_source_document_ids != tuple(sorted(set(inventory_source_document_ids)))
        or not set(inventory_source_document_ids).issubset(source_ids)
    ):
        raise ValueError("inventory evidence must reference exact tender source documents")
    if (
        inventory_assessment is ApplicationInventoryAssessment.CONFIRMED_COMPLETE
        and set(inventory_source_document_ids) != source_ids
    ):
        raise ValueError("complete inventory review must include every tender source")
    reviewed_at = reviewed_at.astimezone(UTC)
    current = evaluate_case(checked.evidence.case, at=reviewed_at)
    deadline_gate = (
        Verdict.PASS
        if checked.evidence.case.tender.accepts_applications_at(reviewed_at)
        else Verdict.FAIL
    )
    if current.decision is not RecommendationDecision.PARTICIPATE:
        price_gate = Verdict.FAIL if deadline_gate is Verdict.FAIL else Verdict.UNKNOWN
    elif current.minimum_bid_price is None:
        price_gate = Verdict.UNKNOWN
    else:
        price_gate = (
            Verdict.PASS
            if current.minimum_bid_price <= package.proposed_price_ex_vat
            <= checked.evidence.case.nmck_ex_vat
            else Verdict.FAIL
        )
    has_fail = (
        any(item.status is Verdict.FAIL for item in requirement_reviews)
        or any(item.status is Verdict.FAIL for item in attachment_reviews)
        or inventory_assessment is ApplicationInventoryAssessment.CONFIRMED_MISSING
        or price_assessment is ApplicationPriceAssessment.REJECTED
        or deadline_gate is Verdict.FAIL
        or price_gate is Verdict.FAIL
    )
    can_pass = (
        all(item.status is Verdict.PASS for item in requirement_reviews)
        and all(item.status is Verdict.PASS for item in attachment_reviews)
        and inventory_assessment is ApplicationInventoryAssessment.CONFIRMED_COMPLETE
        and price_assessment is ApplicationPriceAssessment.CONFIRMED
        and deadline_gate is Verdict.PASS
        and price_gate is Verdict.PASS
        and current.decision is RecommendationDecision.PARTICIPATE
    )
    status = Verdict.FAIL if has_fail else Verdict.PASS if can_pass else Verdict.UNKNOWN
    draft = ApplicationReviewDecision.model_construct(
        company_id=package.company_id,
        package_id=package.package_id,
        package_sha256=package.package_sha256,
        participation_decision_id=package.participation_decision_id,
        participation_decision_sha256=package.participation_decision_sha256,
        requirement_reviews=requirement_reviews,
        attachment_reviews=attachment_reviews,
        inventory_assessment=inventory_assessment,
        inventory_source_document_ids=inventory_source_document_ids,
        inventory_reason=inventory_reason,
        price_assessment=price_assessment,
        price_reason=price_reason,
        current_recommendation=current,
        deadline_gate=deadline_gate,
        price_gate=price_gate,
        status=status,
        reason=reason,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        external_action_authorized=False,
        decision_sha256="0" * 64,
    )
    digest = canonical_json_sha256(draft.model_dump(mode="json", exclude={"decision_sha256"}))
    return ApplicationReviewDecision.model_validate(
        draft.model_dump(mode="python") | {"decision_sha256": digest}
    )


__all__ = [
    "ApplicationAttachmentReview",
    "ApplicationInventoryAssessment",
    "ApplicationPriceAssessment",
    "ApplicationRequirementReview",
    "ApplicationReviewDecision",
    "ApplicationReviewRecord",
    "build_application_review_decision",
]
