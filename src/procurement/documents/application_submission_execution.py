"""One-time admission of exact application bytes without a platform dispatch."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.application_submission import (
    ApplicationSubmissionRecord,
    SubmissionApprovalStatus,
    submission_approval_is_current,
)
from procurement.documents.completeness_review import canonical_json_sha256


class SubmissionAttachmentByteEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=500)
    document_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    submission_filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)


class ApplicationSubmissionAdmission(BaseModel):
    """Permanent claim that consumes one exact approval; no send has happened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["application-submission-admission-v1"] = (
        "application-submission-admission-v1"
    )
    company_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    admission_id: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    approval_expires_at: datetime
    attachments: tuple[SubmissionAttachmentByteEvidence, ...] = Field(min_length=1, max_length=500)
    admitted_by: str = Field(min_length=1)
    admitted_at: datetime
    status: Literal["ADMITTED_NO_DISPATCH"] = "ADMITTED_NO_DISPATCH"
    external_action_performed: Literal[False] = False
    admission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _exact_digest(self) -> Self:
        if (
            self.admitted_at.tzinfo is None
            or self.admitted_at.utcoffset() is None
            or self.approval_expires_at.tzinfo is None
            or self.approval_expires_at.utcoffset() is None
        ):
            raise ValueError("admission times must include timezone")
        if self.admitted_at >= self.approval_expires_at:
            raise ValueError("admission cannot occur after approval expiry")
        if tuple(item.ordinal for item in self.attachments) != tuple(
            range(1, len(self.attachments) + 1)
        ):
            raise ValueError("admission must cover every attachment in order")
        if (
            canonical_json_sha256(self.model_dump(mode="json", exclude={"admission_sha256"}))
            != self.admission_sha256
        ):
            raise ValueError("admission digest differs")
        return self


class ApplicationSubmissionExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    submission: ApplicationSubmissionRecord
    admission: ApplicationSubmissionAdmission | None = None

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if self.admission is None:
            return self
        intent = self.submission.intent
        decision = self.submission.decision
        review = self.submission.evidence.decision
        package = self.submission.evidence.evidence.package
        if (
            intent is None
            or decision is None
            or decision.status is not SubmissionApprovalStatus.APPROVED
            or decision.approval is None
            or review is None
            or package is None
            or self.admission.company_id != intent.request.company_id
            or self.admission.package_id != package.package_id
            or self.admission.action_id != intent.request.action_id
            or self.admission.payload_sha256 != intent.request.payload_sha256
            or self.admission.approval_decision_sha256 != decision.decision_sha256
            or self.admission.approved_by != decision.decided_by
            or self.admission.approval_expires_at != decision.approval.expires_at
            or not submission_approval_is_current(self.submission, self.admission.admitted_at)
            or self.admission.admitted_by in {
                intent.prepared_by, package.prepared_by,
                review.reviewed_by, decision.decided_by,
            }
        ):
            raise ValueError("admission differs from exact approved submission")
        expected = tuple(
            (
                item.ordinal,
                item.document_id,
                item.document_sha256,
                item.submission_filename,
                item.media_type,
            )
            for item in package.attachments
        )
        actual = tuple(
            (item.ordinal, item.document_id, item.sha256, item.submission_filename, item.media_type)
            for item in self.admission.attachments
        )
        if actual != expected:
            raise ValueError("admitted attachments differ from exact package")
        return self


def build_submission_admission(
    submission: ApplicationSubmissionRecord,
    *,
    attachment_bytes: Mapping[str, bytes],
    admission_id: str,
    admitted_by: str,
    admitted_at: datetime,
) -> ApplicationSubmissionAdmission:
    """Verify all original bytes, then bind one immutable no-dispatch claim."""
    checked = ApplicationSubmissionRecord.model_validate(submission.model_dump(mode="python"))
    intent = checked.intent
    decision = checked.decision
    package = checked.evidence.evidence.package
    review = checked.evidence.decision
    if (
        intent is None
        or decision is None
        or decision.approval is None
        or package is None
        or review is None
    ):
        raise ValueError("admission requires exact positive approval")
    if admitted_at.tzinfo is None or admitted_at.utcoffset() is None:
        raise ValueError("admission time must include timezone")
    if not submission_approval_is_current(checked, admitted_at):
        raise ValueError("approval or current submission gates have expired")
    if admitted_by in {
        intent.prepared_by,
        package.prepared_by,
        review.reviewed_by,
        decision.decided_by,
    }:
        raise ValueError("execution actor must be independent")
    if not admission_id.strip() or not admitted_by.strip():
        raise ValueError("admission identities must not be blank")
    if set(attachment_bytes) != {item.document_id for item in package.attachments}:
        raise ValueError("admission requires exactly the approved attachment set")
    byte_evidence = []
    for attachment in package.attachments:
        content = attachment_bytes[attachment.document_id]
        if not isinstance(content, bytes) or not content:
            raise ValueError("attachment bytes must be nonempty")
        digest = hashlib.sha256(content).hexdigest()
        if digest != attachment.document_sha256:
            raise ValueError("attachment bytes differ from approved SHA-256")
        byte_evidence.append(
            SubmissionAttachmentByteEvidence(
                ordinal=attachment.ordinal,
                document_id=attachment.document_id,
                sha256=digest,
                byte_size=len(content),
                submission_filename=attachment.submission_filename,
                media_type=attachment.media_type,
            )
        )
    draft = ApplicationSubmissionAdmission.model_construct(
        company_id=intent.request.company_id,
        package_id=package.package_id,
        action_id=intent.request.action_id,
        admission_id=admission_id,
        payload_sha256=intent.request.payload_sha256,
        approval_decision_sha256=decision.decision_sha256,
        approved_by=decision.decided_by,
        approval_expires_at=decision.approval.expires_at,
        attachments=tuple(byte_evidence),
        admitted_by=admitted_by,
        admitted_at=admitted_at.astimezone(UTC),
        status="ADMITTED_NO_DISPATCH",
        external_action_performed=False,
        admission_sha256="0" * 64,
    )
    return ApplicationSubmissionAdmission.model_validate(
        draft.model_dump(mode="python")
        | {
            "admission_sha256": canonical_json_sha256(
                draft.model_dump(mode="json", exclude={"admission_sha256"})
            )
        }
    )
