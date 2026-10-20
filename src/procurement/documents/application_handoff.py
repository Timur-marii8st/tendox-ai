"""Verified, local-only handoff of an approved application to a human operator."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, Self
from zipfile import ZIP_STORED, ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.application_submission import (
    ApplicationSubmissionRecord,
    submission_approval_is_current,
)
from procurement.documents.completeness_review import canonical_json_sha256

MAX_HANDOFF_BYTES = 100 * 1024 * 1024


class HandoffFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=500)
    document_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    archive_path: str = Field(min_length=1)


class ApplicationHandoffManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["application-handoff-v1"] = "application-handoff-v1"
    company_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_id: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination: str = Field(min_length=1)
    price_ex_vat: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    generated_at: datetime
    approval_expires_at: datetime
    files: tuple[HandoffFile, ...] = Field(min_length=1, max_length=500)
    external_action_performed: Literal[False] = False
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _verify(self) -> Self:
        if any(value.tzinfo is None or value.utcoffset() is None for value in (
            self.generated_at, self.approval_expires_at,
        )):
            raise ValueError("handoff times must be timezone-aware")
        if self.generated_at >= self.approval_expires_at:
            raise ValueError("handoff requires an unexpired approval")
        if tuple(item.ordinal for item in self.files) != tuple(range(1, len(self.files) + 1)):
            raise ValueError("handoff files must follow exact attachment order")
        if (
            canonical_json_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("handoff manifest digest differs")
        return self


def build_application_handoff(
    submission: ApplicationSubmissionRecord,
    *,
    attachment_bytes: Mapping[str, bytes],
    at: datetime,
) -> tuple[ApplicationHandoffManifest, bytes]:
    """Build a bounded archive from verified originals; no platform I/O occurs."""
    checked = ApplicationSubmissionRecord.model_validate(submission.model_dump(mode="python"))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("handoff time must include timezone")
    if not submission_approval_is_current(checked, at):
        raise ValueError("handoff requires a current exact approval and current gates")
    intent = checked.intent
    decision = checked.decision
    package = checked.evidence.evidence.package
    assert intent is not None and decision is not None and decision.approval is not None
    assert package is not None
    if set(attachment_bytes) != {item.document_id for item in package.attachments}:
        raise ValueError("handoff requires the exact attachment set")
    files: list[HandoffFile] = []
    total = 0
    for attachment in package.attachments:
        content = attachment_bytes[attachment.document_id]
        if not isinstance(content, bytes) or not content:
            raise ValueError("handoff attachment bytes must be nonempty")
        total += len(content)
        if total > MAX_HANDOFF_BYTES:
            raise ValueError("handoff exceeds archive size limit")
        digest = hashlib.sha256(content).hexdigest()
        if digest != attachment.document_sha256:
            raise ValueError("handoff attachment bytes differ from approved SHA-256")
        files.append(HandoffFile(
            ordinal=attachment.ordinal,
            document_id=attachment.document_id,
            filename=attachment.submission_filename,
            media_type=attachment.media_type,
            sha256=digest,
            byte_size=len(content),
            archive_path=f"files/{attachment.ordinal:03d}-{attachment.submission_filename}",
        ))
    fields = dict(
        company_id=intent.request.company_id,
        package_id=package.package_id,
        package_sha256=package.package_sha256,
        action_id=intent.request.action_id,
        payload_sha256=intent.request.payload_sha256,
        approval_decision_sha256=decision.decision_sha256,
        destination=intent.request.payload["destination"],
        price_ex_vat=intent.request.payload["price_ex_vat"],
        currency=intent.request.payload["currency"],
        generated_at=at.astimezone(UTC),
        approval_expires_at=decision.approval.expires_at,
        files=tuple(files),
        external_action_performed=False,
    )
    draft = ApplicationHandoffManifest.model_construct(**fields, manifest_sha256="0" * 64)
    manifest = ApplicationHandoffManifest.model_validate(
        draft.model_dump(mode="python") | {
            "manifest_sha256": canonical_json_sha256(
                draft.model_dump(mode="json", exclude={"manifest_sha256"})
            )
        }
    )
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        for item in files:
            archive.writestr(item.archive_path, attachment_bytes[item.document_id])
    return manifest, stream.getvalue()
