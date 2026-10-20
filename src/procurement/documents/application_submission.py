"""Exact, short-lived approval for one reviewed application submission intent.

This module prepares an internal submission command. It performs no platform I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.application_review import ApplicationReviewRecord
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.domain.actions import ActionRequest, ActionType, Approval, is_authorized
from procurement.domain.cases import evaluate_case
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import RecommendationDecision

APPROVAL_LIFETIME = timedelta(minutes=15)


class SubmissionApprovalStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApplicationSubmissionIntent(BaseModel):
    """A server-built canonical command containing the exact reviewed price/files."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["application-submission-intent-v1"] = "application-submission-intent-v1"
    package_id: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_by: str = Field(min_length=1)
    request: ActionRequest

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if self.request.action_type is not ActionType.SUBMIT_APPLICATION:
            raise ValueError("submission intent requires SUBMIT_APPLICATION")
        payload = self.request.payload
        if (
            payload.get("schema_version") != self.schema_version
            or payload.get("package_id") != self.package_id
            or payload.get("package_sha256") != self.package_sha256
            or payload.get("review_decision_sha256") != self.review_decision_sha256
        ):
            raise ValueError("submission intent identity differs from payload")
        return self


class ApplicationSubmissionApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["application-submission-approval-v1"] = (
        "application-submission-approval-v1"
    )
    company_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SubmissionApprovalStatus
    reason: str = Field(min_length=1, max_length=4_000)
    decided_by: str = Field(min_length=1)
    decided_at: datetime
    approval: Approval | None = None
    external_action_performed: Literal[False] = False
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _digest(self) -> Self:
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("approval time must be timezone-aware")
        if (self.status is SubmissionApprovalStatus.APPROVED) != (self.approval is not None):
            raise ValueError("positive decision requires exact approval")
        if self.approval is not None and (
            self.approval.company_id != self.company_id
            or self.approval.action_id != self.action_id
            or self.approval.payload_sha256 != self.payload_sha256
            or self.approval.approved_by != self.decided_by
            or self.approval.approved_at != self.decided_at
        ):
            raise ValueError("approval identity differs")
        if (
            canonical_json_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
            != self.decision_sha256
        ):
            raise ValueError("submission approval digest differs")
        return self


class ApplicationSubmissionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: ApplicationReviewRecord
    intent: ApplicationSubmissionIntent | None = None
    decision: ApplicationSubmissionApproval | None = None

    @model_validator(mode="after")
    def _rebuild(self) -> Self:
        if self.intent is None:
            if self.decision is not None:
                raise ValueError("approval without intent")
            return self
        expected = build_submission_intent(
            self.evidence,
            action_id=self.intent.request.action_id,
            destination=self.intent.request.payload["destination"],
            prepared_by=self.intent.prepared_by,
            prepared_at=self.intent.request.created_at,
        )
        if expected != self.intent:
            raise ValueError("submission intent differs from reviewed package")
        if self.decision is not None:
            rebuilt = build_submission_approval(
                self,
                status=self.decision.status,
                reason=self.decision.reason,
                decided_by=self.decision.decided_by,
                decided_at=self.decision.decided_at,
            )
            if rebuilt != self.decision:
                raise ValueError("submission approval differs from exact intent")
        return self


def _current_gate(evidence: ApplicationReviewRecord, at: datetime) -> datetime:
    package = evidence.evidence.package
    review = evidence.decision
    if package is None or review is None or review.status is not Verdict.PASS:
        raise ValueError("submission requires a PASS package review")
    case = evidence.evidence.evidence.case
    current = evaluate_case(case, at=at)
    if (
        current.decision is not RecommendationDecision.PARTICIPATE
        or current.minimum_bid_price is None
        or package.proposed_price_ex_vat < current.minimum_bid_price
        or package.proposed_price_ex_vat > case.nmck_ex_vat
        or not case.tender.accepts_applications_at(at)
    ):
        raise ValueError("current submission gates are not PASS")
    assert case.tender.submission is not None
    return case.tender.submission.closes_at


def build_submission_intent(
    evidence: ApplicationReviewRecord,
    *,
    action_id: str,
    destination: str,
    prepared_by: str,
    prepared_at: datetime,
) -> ApplicationSubmissionIntent:
    """Freeze reviewed package bytes/price and an exact HTTPS destination."""
    checked = ApplicationReviewRecord.model_validate(evidence.model_dump(mode="python"))
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("preparation time must be timezone-aware")
    _current_gate(checked, prepared_at)
    assert checked.decision is not None
    if prepared_at <= checked.decision.reviewed_at:
        raise ValueError("submission intent must follow terminal review")
    parts = urlsplit(destination)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or len(destination) > 2_000
    ):
        raise ValueError("submission destination must be an exact HTTPS URL")
    package = checked.evidence.package
    review = checked.decision
    assert package is not None and review is not None
    payload = {
        "schema_version": "application-submission-intent-v1",
        "destination": destination,
        "case_id": package.case_id,
        "case_version": package.case_version,
        "package_id": package.package_id,
        "package_sha256": package.package_sha256,
        "review_decision_sha256": review.decision_sha256,
        "price_ex_vat": str(package.proposed_price_ex_vat),
        "currency": package.currency,
        "attachments": [
            {
                "ordinal": item.ordinal,
                "document_id": item.document_id,
                "document_sha256": item.document_sha256,
                "submission_filename": item.submission_filename,
                "media_type": item.media_type,
            }
            for item in package.attachments
        ],
    }
    return ApplicationSubmissionIntent(
        package_id=package.package_id,
        package_sha256=package.package_sha256,
        review_decision_sha256=review.decision_sha256,
        prepared_by=prepared_by,
        request=ActionRequest.prepare(
            action_id=action_id,
            company_id=package.company_id,
            tender_id=package.tender_id,
            action_type=ActionType.SUBMIT_APPLICATION,
            payload=payload,
            created_at=prepared_at,
        ),
    )


def build_submission_approval(
    record: ApplicationSubmissionRecord,
    *,
    status: SubmissionApprovalStatus,
    reason: str,
    decided_by: str,
    decided_at: datetime,
) -> ApplicationSubmissionApproval:
    intent = record.intent
    package = record.evidence.evidence.package
    review = record.evidence.decision
    if intent is None or package is None or review is None:
        raise ValueError("submission approval requires a prepared intent")
    if decided_by in {intent.prepared_by, package.prepared_by, review.reviewed_by}:
        raise ValueError("submission approver must be independent")
    if decided_at.tzinfo is None or decided_at.utcoffset() is None:
        raise ValueError("decision time must be timezone-aware")
    if decided_at < intent.request.created_at or not reason.strip():
        raise ValueError("invalid decision time or reason")
    decided_at = decided_at.astimezone(UTC)
    approval = None
    if status is SubmissionApprovalStatus.APPROVED:
        deadline = _current_gate(record.evidence, decided_at)
        case = record.evidence.evidence.evidence.case
        limits = [decided_at + APPROVAL_LIFETIME, deadline]
        if case.selected_quote is not None:
            limits.append(case.selected_quote.valid_until)
        expires_at = min(limits)
        if expires_at <= decided_at:
            raise ValueError("approval window has expired")
        approval = Approval(
            company_id=intent.request.company_id,
            tender_id=intent.request.tender_id,
            action_type=ActionType.SUBMIT_APPLICATION,
            action_id=intent.request.action_id,
            payload_sha256=intent.request.payload_sha256,
            approved_by=decided_by,
            approved_at=decided_at,
            expires_at=expires_at,
        )
    draft = ApplicationSubmissionApproval.model_construct(
        company_id=intent.request.company_id,
        action_id=intent.request.action_id,
        payload_sha256=intent.request.payload_sha256,
        status=status,
        reason=reason.strip(),
        decided_by=decided_by,
        decided_at=decided_at,
        approval=approval,
        external_action_performed=False,
        decision_sha256="0" * 64,
    )
    return ApplicationSubmissionApproval.model_validate(
        draft.model_dump(mode="python")
        | {
            "decision_sha256": canonical_json_sha256(
                draft.model_dump(mode="json", exclude={"decision_sha256"})
            )
        }
    )


def submission_approval_is_current(record: ApplicationSubmissionRecord, at: datetime) -> bool:
    """Pure check only; a future executor must consume/revalidate atomically."""
    try:
        record = ApplicationSubmissionRecord.model_validate(record.model_dump(mode="python"))
        if record.intent is None or record.decision is None or record.decision.approval is None:
            return False
        _current_gate(record.evidence, at)
    except (ValueError, TypeError):
        return False
    return is_authorized(record.intent.request, record.decision.approval, at)
