"""Pure exact-payload contract for a persisted, human-approved AI transfer.

This module records neither secrets nor a send/consume event.  Persistence and
transport remain separate boundaries; admission here only proves that immutable
request and approval evidence still bind at the instant of a caller's check.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from procurement.documents.ai_requirements import (
    AI_REQUIREMENTS_CHUNKING_VERSION,
    AI_REQUIREMENTS_PROMPT_VERSION_V2,
    AI_REQUIREMENTS_RESPONSE_SCHEMA_VERSION,
    MAX_OPENROUTER_RESPONSE_BYTES,
    AiRequirementsModelProfile,
    AiRequirementsPrivacyControls,
    AiRequirementsTransferChunk,
    AiRequirementsTransferManifest,
    AiRequirementsTransferTransport,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.facts import DocumentRole

PERSISTED_AI_TRANSFER_REQUEST_SCHEMA_VERSION: Literal["persisted-ai-transfer-request-v1"] = (
    "persisted-ai-transfer-request-v1"
)
PERSISTED_AI_TRANSFER_APPROVAL_SCHEMA_VERSION: Literal["persisted-ai-transfer-approval-v1"] = (
    "persisted-ai-transfer-approval-v1"
)
AI_TRANSFER_APPROVAL_WINDOW = timedelta(minutes=15)
MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES = MAX_OPENROUTER_RESPONSE_BYTES


class PersistedAiTransferRequest(BaseModel):
    """One immutable, non-secret request reconstructed from an exact draft manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["persisted-ai-transfer-request-v1"] = (
        PERSISTED_AI_TRANSFER_REQUEST_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_role: Literal[DocumentRole.TENDER_REQUIREMENTS] = DocumentRole.TENDER_REQUIREMENTS
    source_binding: Literal["VERIFIED_PERSISTED_SOURCE"] = "VERIFIED_PERSISTED_SOURCE"
    transport: AiRequirementsTransferTransport
    model_profile: AiRequirementsModelProfile
    privacy_controls: AiRequirementsPrivacyControls
    prompt_version: Literal["ai-requirements-v2"] = AI_REQUIREMENTS_PROMPT_VERSION_V2
    response_schema_version: Literal["ai-requirement-wire-v2"] = (
        AI_REQUIREMENTS_RESPONSE_SCHEMA_VERSION
    )
    response_schema_json: str = Field(min_length=1)
    response_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunking_version: Literal["ai-requirements-chunking-v2"] = AI_REQUIREMENTS_CHUNKING_VERSION
    max_chunk_characters: int = Field(ge=1_000)
    source_block_ids: tuple[str, ...] = Field(min_length=1)
    chunks: tuple[AiRequirementsTransferChunk, ...] = Field(min_length=1)
    retention: Literal["RAW_RESPONSE_30_DAYS_V1"] = "RAW_RESPONSE_30_DAYS_V1"
    execution: Literal["ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"] = (
        "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"
    )
    response_capture_max_bytes: int = Field(ge=1, le=MAX_OPENROUTER_RESPONSE_BYTES)
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("company_id", "transfer_id", "source_document_id", "prepared_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("persisted transfer text must not be blank")
        return normalized

    @field_validator("prepared_at")
    @classmethod
    def _aware_prepared_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("persisted transfer preparation time must include timezone")
        return value

    @model_validator(mode="after")
    def _request_is_exact(self) -> Self:
        if self.response_capture_max_bytes != MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES:
            raise ValueError("persisted transfer response capture limit must be fixed")
        _reconstruct_manifest(self)
        payload = self.model_dump(mode="json", exclude={"payload_sha256"})
        if canonical_json_sha256(payload) != self.payload_sha256:
            raise ValueError("persisted transfer request digest does not match")
        return self


class PersistedAiTransferApproval(BaseModel):
    """Independent human approval for precisely one persisted request digest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["persisted-ai-transfer-approval-v1"] = (
        PERSISTED_AI_TRANSFER_APPROVAL_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["APPROVED"] = "APPROVED"
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    expires_at: datetime

    @field_validator("company_id", "transfer_id", "approved_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("persisted transfer approval text must not be blank")
        return normalized

    @field_validator("approved_at", "expires_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("persisted transfer approval time must include timezone")
        return value

    @model_validator(mode="after")
    def _window_is_exact(self) -> Self:
        approved_utc = self.approved_at.astimezone(UTC)
        expires_utc = self.expires_at.astimezone(UTC)
        if expires_utc - approved_utc != AI_TRANSFER_APPROVAL_WINDOW:
            raise ValueError("persisted transfer approval expires exactly fifteen minutes later")
        return self


def build_persisted_ai_transfer_request(
    manifest: AiRequirementsTransferManifest,
    *,
    transfer_id: str,
    prepared_by: str,
    prepared_at: datetime,
) -> PersistedAiTransferRequest:
    """Revalidate a prepared draft and bind it to a server-verified persistence boundary."""
    validated = AiRequirementsTransferManifest.model_validate(manifest.model_dump(mode="python"))
    fields = {
        "company_id": validated.company_id,
        "transfer_id": transfer_id,
        "source_document_id": validated.source_document_id,
        "source_sha256": validated.source_sha256,
        "extraction_sha256": validated.extraction_sha256,
        "draft_manifest_sha256": validated.manifest_sha256,
        "transport": validated.transport,
        "model_profile": validated.model_profile,
        "privacy_controls": validated.privacy_controls,
        "response_schema_json": validated.response_schema_json,
        "response_schema_sha256": validated.response_schema_sha256,
        "system_prompt_sha256": validated.system_prompt_sha256,
        "max_chunk_characters": validated.max_chunk_characters,
        "source_block_ids": validated.source_block_ids,
        "chunks": validated.chunks,
        "response_capture_max_bytes": MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES,
        "prepared_by": prepared_by,
        "prepared_at": prepared_at,
    }
    payload = {
        "schema_version": PERSISTED_AI_TRANSFER_REQUEST_SCHEMA_VERSION,
        "document_role": DocumentRole.TENDER_REQUIREMENTS,
        "source_binding": "VERIFIED_PERSISTED_SOURCE",
        "prompt_version": AI_REQUIREMENTS_PROMPT_VERSION_V2,
        "response_schema_version": AI_REQUIREMENTS_RESPONSE_SCHEMA_VERSION,
        "chunking_version": AI_REQUIREMENTS_CHUNKING_VERSION,
        "retention": "RAW_RESPONSE_30_DAYS_V1",
        "execution": "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1",
        **fields,
    }
    return PersistedAiTransferRequest(
        company_id=validated.company_id,
        transfer_id=transfer_id,
        source_document_id=validated.source_document_id,
        source_sha256=validated.source_sha256,
        extraction_sha256=validated.extraction_sha256,
        draft_manifest_sha256=validated.manifest_sha256,
        transport=validated.transport,
        model_profile=validated.model_profile,
        privacy_controls=validated.privacy_controls,
        response_schema_json=validated.response_schema_json,
        response_schema_sha256=validated.response_schema_sha256,
        system_prompt_sha256=validated.system_prompt_sha256,
        max_chunk_characters=validated.max_chunk_characters,
        source_block_ids=validated.source_block_ids,
        chunks=validated.chunks,
        response_capture_max_bytes=MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES,
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        payload_sha256=canonical_json_sha256(payload),
    )


def build_persisted_ai_transfer_approval(
    request: PersistedAiTransferRequest,
    *,
    approved_by: str,
    approved_at: datetime,
) -> PersistedAiTransferApproval:
    """Create the sole exact-digest approval; it carries no execution authority itself."""
    validated = PersistedAiTransferRequest.model_validate(request.model_dump(mode="python"))
    if approved_by.strip() == validated.prepared_by:
        raise ValueError("persisted transfer approval must be independent from preparer")
    approved_utc = _require_aware(approved_at, field="approved_at").astimezone(UTC)
    if approved_utc < validated.prepared_at.astimezone(UTC):
        raise ValueError("persisted transfer approval cannot predate preparation")
    return PersistedAiTransferApproval(
        company_id=validated.company_id,
        transfer_id=validated.transfer_id,
        request_payload_sha256=validated.payload_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        expires_at=approved_utc + AI_TRANSFER_APPROVAL_WINDOW,
    )


def is_persisted_ai_transfer_authorized(
    request: PersistedAiTransferRequest,
    approval: PersistedAiTransferApproval,
    *,
    company_id: str,
    transfer_id: str,
    now: datetime,
) -> bool:
    """Fail closed for immutable request/approval admission without sending or consuming it."""
    current_utc = _require_aware(now, field="now").astimezone(UTC)
    try:
        checked_request = PersistedAiTransferRequest.model_validate(
            request.model_dump(mode="python")
        )
        checked_approval = PersistedAiTransferApproval.model_validate(
            approval.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return False
    return (
        checked_request.company_id == company_id
        and checked_request.transfer_id == transfer_id
        and checked_approval.company_id == company_id
        and checked_approval.transfer_id == transfer_id
        and checked_approval.request_payload_sha256 == checked_request.payload_sha256
        and checked_approval.approved_by != checked_request.prepared_by
        and checked_request.prepared_at.astimezone(UTC)
        <= checked_approval.approved_at.astimezone(UTC)
        and checked_approval.approved_at.astimezone(UTC)
        <= current_utc
        < checked_approval.expires_at.astimezone(UTC)
    )


def _reconstruct_manifest(request: PersistedAiTransferRequest) -> None:
    """Reuse the draft validator so persisted payload cannot relax any fixed transfer policy."""
    # Dump nested models before validation: passing model instances directly can
    # preserve an invalid ``model_copy`` without rerunning its own validators.
    AiRequirementsTransferManifest.model_validate(
        {
            "company_id": request.company_id,
            "source_document_id": request.source_document_id,
            "source_sha256": request.source_sha256,
            "extraction_sha256": request.extraction_sha256,
            "transport": request.transport.model_dump(mode="python"),
            "model_profile": request.model_profile.model_dump(mode="python"),
            "privacy_controls": request.privacy_controls.model_dump(mode="python"),
            "response_schema_json": request.response_schema_json,
            "response_schema_sha256": request.response_schema_sha256,
            "system_prompt_sha256": request.system_prompt_sha256,
            "max_chunk_characters": request.max_chunk_characters,
            "source_block_ids": request.source_block_ids,
            "chunks": tuple(chunk.model_dump(mode="python") for chunk in request.chunks),
            "manifest_sha256": request.draft_manifest_sha256,
        }
    )


def _require_aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return value
