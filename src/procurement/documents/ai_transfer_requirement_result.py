"""Pure server-managed materialization of one successful AI transfer response.

The builder consumes raw response bytes transiently, revalidates every durable
binding, and returns only typed review candidates plus immutable digests.  Raw
provider content and encryption key material never enter the result model.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from procurement.documents.ai_requirements import (
    AiProcurementItemCandidate,
    AiRequirementCandidate,
    AiRequirementRunStatus,
    AiSourceBlock,
    materialize_ai_requirement_wire_v2,
    parse_ai_requirement_provider_envelope,
    parse_ai_requirement_transfer_source_records,
)
from procurement.documents.ai_transfer import PersistedAiTransferRequest
from procurement.documents.ai_transfer_execution import (
    AiTransferDispatchClaim,
    AiTransferDispatchReceipt,
)
from procurement.documents.ai_transfer_raw import AiTransferRawMetadata
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractionResult, ExtractionStatus
from procurement.documents.facts import CompletenessStatus
from procurement.domain.provenance import Extractor

AI_TRANSFER_REQUIREMENT_RESULT_SCHEMA_VERSION: Literal["ai-transfer-requirement-result-v1"] = (
    "ai-transfer-requirement-result-v1"
)
AI_TRANSFER_REQUIREMENT_BATCH_SCHEMA_VERSION: Literal["ai-transfer-requirement-batch-v1"] = (
    "ai-transfer-requirement-batch-v1"
)
AI_TRANSFER_REQUIREMENT_PARSER_VERSION: Literal["ai-transfer-requirement-parser-v1"] = (
    "ai-transfer-requirement-parser-v1"
)
AI_TRANSFER_REQUIREMENT_MATERIALIZATION_SCHEMA_VERSION: Literal[
    "ai-transfer-requirement-materialization-v1"
] = "ai-transfer-requirement-materialization-v1"
AI_TRANSFER_REQUIREMENT_CHUNK_REJECTION_SCHEMA_VERSION: Literal[
    "ai-transfer-requirement-chunk-rejection-v1"
] = "ai-transfer-requirement-chunk-rejection-v1"


class AiTransferRequirementResultErrorCode(StrEnum):
    """Sanitized semantic failure; no provider or source text is exposed."""

    INVALID_BINDING = "INVALID_BINDING"
    UNSUPPORTED_MULTI_CHUNK = "UNSUPPORTED_MULTI_CHUNK"
    INVALID_RAW_RESPONSE = "INVALID_RAW_RESPONSE"
    INVALID_PROVIDER_ENVELOPE = "INVALID_PROVIDER_ENVELOPE"
    MODEL_MISMATCH = "MODEL_MISMATCH"
    INVALID_WIRE_RESPONSE = "INVALID_WIRE_RESPONSE"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"


class AiTransferRequirementResultError(ValueError):
    """Typed fail-closed materialization error safe for audit and API output."""

    def __init__(self, code: AiTransferRequirementResultErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class AiTransferRequirementChunkRejection(BaseModel):
    """Raw-free terminal receipt for one semantically invalid captured chunk."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-requirement-chunk-rejection-v1"] = (
        AI_TRANSFER_REQUIREMENT_CHUNK_REJECTION_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    rejection_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    ordinal: int = Field(ge=1, le=9_999)
    claim_id: str = Field(min_length=1, max_length=200)
    receipt_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: Literal["ai-transfer-requirement-parser-v1"] = (
        AI_TRANSFER_REQUIREMENT_PARSER_VERSION
    )
    reason: Literal["INVALID_CANDIDATE_EVIDENCE"] = "INVALID_CANDIDATE_EVIDENCE"
    rejected_by: str = Field(min_length=1, max_length=200)
    rejected_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "rejection_id",
        "transfer_id",
        "execution_id",
        "claim_id",
        "receipt_id",
        "raw_response_id",
        "rejected_by",
    )
    @classmethod
    def _safe_rejection_text(cls, value: str) -> str:
        if value != value.strip() or any(not character.isprintable() for character in value):
            raise ValueError("AI transfer chunk rejection text must be trimmed and printable")
        return value

    @field_validator("rejected_at")
    @classmethod
    def _aware_rejection_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI transfer chunk rejection time must include timezone")
        return value

    @model_validator(mode="after")
    def _rejection_is_exact(self) -> Self:
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"payload_sha256"}))
        if self.payload_sha256 != expected:
            raise ValueError("AI transfer chunk rejection digest does not match")
        return self


class AiTransferRequirementMaterialization(BaseModel):
    """Append-only safe receipt for a semantic materialization attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-requirement-materialization-v1"] = (
        AI_TRANSFER_REQUIREMENT_MATERIALIZATION_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    materialization_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    ordinal: Literal[1] = 1
    claim_id: str = Field(min_length=1, max_length=200)
    receipt_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: Literal["ai-transfer-requirement-parser-v1"] = (
        AI_TRANSFER_REQUIREMENT_PARSER_VERSION
    )
    status: Literal["MATERIALIZED", "REJECTED"]
    reason: Literal[
        "MATERIALIZED",
        "UNSUPPORTED_MULTI_CHUNK",
        "INVALID_CANDIDATE_EVIDENCE",
    ]
    result_id: str | None = Field(default=None, min_length=1, max_length=200)
    result_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    run_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    materialized_by: str = Field(min_length=1, max_length=200)
    materialized_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "materialization_id",
        "transfer_id",
        "execution_id",
        "claim_id",
        "receipt_id",
        "raw_response_id",
        "result_id",
        "run_id",
        "materialized_by",
    )
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or any(not character.isprintable() for character in value)
        ):
            raise ValueError("AI materialization text must be trimmed and printable")
        return value

    @field_validator("materialized_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI materialization time must include timezone")
        return value

    @model_validator(mode="after")
    def _receipt_is_exact(self) -> Self:
        outputs = (
            self.result_id,
            self.result_payload_sha256,
            self.run_id,
            self.run_evidence_sha256,
        )
        if self.status == "MATERIALIZED":
            if self.reason != "MATERIALIZED" or any(value is None for value in outputs):
                raise ValueError("materialized receipt requires exact result and run evidence")
        elif self.reason == "MATERIALIZED" or any(value is not None for value in outputs):
            raise ValueError("rejected materialization cannot expose result or run evidence")
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"payload_sha256"}))
        if self.payload_sha256 != expected:
            raise ValueError("AI materialization receipt digest does not match")
        return self


class AiTransferRequirementResult(BaseModel):
    """Raw-free review candidates bound to one exact successful transfer receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-requirement-result-v1"] = (
        AI_TRANSFER_REQUIREMENT_RESULT_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    result_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    ordinal: int = Field(ge=1, le=9_999)
    claim_id: str = Field(min_length=1, max_length=200)
    receipt_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assistant_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_response_id: str = Field(min_length=1, max_length=500)
    provider_model: str = Field(min_length=1, max_length=500)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_block_ids: tuple[str, ...] = Field(min_length=1)
    candidates: tuple[AiRequirementCandidate, ...] = ()
    item_candidates: tuple[AiProcurementItemCandidate, ...] = ()
    unresolved_block_ids: tuple[str, ...] = ()
    execution_status: Literal[AiRequirementRunStatus.COMPLETE] = AiRequirementRunStatus.COMPLETE
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN
    prepared_by: str = Field(min_length=1, max_length=200)
    materialized_by: str = Field(min_length=1, max_length=200)
    materialized_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "result_id",
        "transfer_id",
        "execution_id",
        "claim_id",
        "receipt_id",
        "raw_response_id",
        "source_document_id",
        "prepared_by",
        "materialized_by",
        "provider_response_id",
        "provider_model",
    )
    @classmethod
    def _safe_text(cls, value: str) -> str:
        if value != value.strip() or any(not character.isprintable() for character in value):
            raise ValueError("AI transfer result text must be trimmed and printable")
        return value

    @field_validator("materialized_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI transfer result time must include timezone")
        return value

    @model_validator(mode="after")
    def _result_is_exact_and_raw_free(self) -> Self:
        if len(set(self.source_block_ids)) != len(self.source_block_ids):
            raise ValueError("AI transfer result source block IDs must be unique")
        if not set(self.unresolved_block_ids).issubset(self.source_block_ids):
            raise ValueError("AI transfer result unresolved block is outside source")
        if len(set(self.unresolved_block_ids)) != len(self.unresolved_block_ids):
            raise ValueError("AI transfer result unresolved block IDs must be unique")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("AI transfer result requirement candidates must be unique")
        if len({item.candidate_id for item in self.item_candidates}) != len(self.item_candidates):
            raise ValueError("AI transfer result item candidates must be unique")
        source_ids = set(self.source_block_ids)
        if any(
            evidence.block_id not in source_ids
            for candidate in self.candidates
            for evidence in candidate.evidence
        ):
            raise ValueError("AI transfer result requirement evidence is outside source")
        for item in self.item_candidates:
            if (
                item.company_id != self.company_id
                or item.source_document_id != self.source_document_id
                or item.source_sha256 != self.source_sha256
            ):
                raise ValueError("AI transfer result item source identity mismatch")
            if not set(_item_evidence_ids(item)).issubset(source_ids):
                raise ValueError("AI transfer result item evidence is outside source")
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"payload_sha256"}))
        if self.payload_sha256 != expected:
            raise ValueError("AI transfer requirement result digest does not match")
        return self


class AiTransferRequirementBatchResult(BaseModel):
    """Raw-free aggregate of every exact result in one ordered transfer batch."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-requirement-batch-v1"] = (
        AI_TRANSFER_REQUIREMENT_BATCH_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    batch_result_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_block_ids: tuple[str, ...] = Field(min_length=1)
    chunk_results: tuple[AiTransferRequirementResult, ...] = Field(min_length=1)
    candidates: tuple[AiRequirementCandidate, ...] = ()
    item_candidates: tuple[AiProcurementItemCandidate, ...] = ()
    unresolved_block_ids: tuple[str, ...] = ()
    execution_status: Literal[AiRequirementRunStatus.COMPLETE] = AiRequirementRunStatus.COMPLETE
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN
    prepared_by: str = Field(min_length=1, max_length=200)
    aggregated_by: str = Field(min_length=1, max_length=200)
    aggregated_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "batch_result_id",
        "transfer_id",
        "execution_id",
        "source_document_id",
        "prepared_by",
        "aggregated_by",
    )
    @classmethod
    def _safe_batch_text(cls, value: str) -> str:
        if value != value.strip() or any(not character.isprintable() for character in value):
            raise ValueError("AI transfer batch text must be trimmed and printable")
        return value

    @field_validator("aggregated_at")
    @classmethod
    def _aware_batch_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI transfer batch time must include timezone")
        return value

    @model_validator(mode="after")
    def _batch_is_exact_and_complete(self) -> Self:
        expected_ordinals = tuple(range(1, len(self.chunk_results) + 1))
        if tuple(result.ordinal for result in self.chunk_results) != expected_ordinals:
            raise ValueError("AI transfer batch results must be ordered and contiguous")
        if len(set(self.source_block_ids)) != len(self.source_block_ids):
            raise ValueError("AI transfer batch source block IDs must be unique")
        if not set(self.unresolved_block_ids).issubset(self.source_block_ids):
            raise ValueError("AI transfer batch unresolved block is outside source")
        if len(set(self.unresolved_block_ids)) != len(self.unresolved_block_ids):
            raise ValueError("AI transfer batch unresolved block IDs must be unique")
        aggregate_utc = self.aggregated_at.astimezone(UTC)
        if not all(
            result.company_id == self.company_id
            and result.transfer_id == self.transfer_id
            and result.execution_id == self.execution_id
            and result.request_payload_sha256 == self.request_payload_sha256
            and result.source_document_id == self.source_document_id
            and result.source_sha256 == self.source_sha256
            and result.extraction_sha256 == self.extraction_sha256
            and result.prepared_by == self.prepared_by
            and result.materialized_at.astimezone(UTC) <= aggregate_utc
            for result in self.chunk_results
        ):
            raise ValueError("AI transfer batch result identity differs")
        unique_fields = (
            tuple(result.result_id for result in self.chunk_results),
            tuple(result.claim_id for result in self.chunk_results),
            tuple(result.receipt_id for result in self.chunk_results),
            tuple(result.raw_response_id for result in self.chunk_results),
            tuple(result.claim_payload_sha256 for result in self.chunk_results),
            tuple(result.receipt_payload_sha256 for result in self.chunk_results),
            tuple(result.raw_metadata_sha256 for result in self.chunk_results),
        )
        if any(len(values) != len(set(values)) for values in unique_fields):
            raise ValueError("AI transfer batch reuses per-chunk evidence")
        covered_ids = tuple(
            dict.fromkeys(
                block_id for result in self.chunk_results for block_id in result.source_block_ids
            )
        )
        if covered_ids != self.source_block_ids:
            raise ValueError("AI transfer batch source coverage is incomplete or reordered")
        expected_requirements: dict[str, AiRequirementCandidate] = {}
        expected_items: dict[str, AiProcurementItemCandidate] = {}
        unresolved_ids: set[str] = set()
        for result in self.chunk_results:
            unresolved_ids.update(result.unresolved_block_ids)
            for candidate in result.candidates:
                _merge_exact_candidate(expected_requirements, candidate)
            for item in result.item_candidates:
                _merge_exact_item_candidate(expected_items, item)
        expected_unresolved = tuple(
            block_id for block_id in self.source_block_ids if block_id in unresolved_ids
        )
        if (
            tuple(expected_requirements.values()) != self.candidates
            or tuple(expected_items.values()) != self.item_candidates
            or expected_unresolved != self.unresolved_block_ids
        ):
            raise ValueError("AI transfer batch projection differs from chunk results")
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"payload_sha256"}))
        if self.payload_sha256 != expected:
            raise ValueError("AI transfer requirement batch digest does not match")
        return self


def build_ai_transfer_requirement_result(
    request: PersistedAiTransferRequest,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw_metadata: AiTransferRawMetadata,
    raw_response: bytes,
    extraction: ExtractionResult,
    *,
    result_id: str,
    prepared_by: str,
    materialized_by: str,
    materialized_at: datetime,
) -> AiTransferRequirementResult:
    """Materialize one successful chunk after revalidating every exact binding."""
    checked_request, checked_claim, checked_receipt, checked_raw = _validate_inputs(
        request, claim, receipt, raw_metadata
    )
    if prepared_by != checked_request.prepared_by:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    _require_success_binding(checked_request, checked_claim, checked_receipt, checked_raw)
    if materialized_at.utcoffset() is None:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    materialized_utc = materialized_at.astimezone(UTC)
    if (
        materialized_utc < checked_receipt.recorded_at.astimezone(UTC)
        or materialized_utc < checked_raw.received_at.astimezone(UTC)
        or materialized_utc >= checked_raw.expires_at.astimezone(UTC)
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    source_blocks = _validate_source(checked_request, extraction, checked_claim.ordinal)
    if not isinstance(raw_response, bytes):
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_RAW_RESPONSE
        )
    if (
        len(raw_response) != checked_raw.response_byte_count
        or hashlib.sha256(raw_response).hexdigest() != checked_raw.response_body_sha256
    ):
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_RAW_RESPONSE
        )
    try:
        envelope = parse_ai_requirement_provider_envelope(raw_response)
    except (RecursionError, TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_PROVIDER_ENVELOPE
        ) from error
    if envelope.model != checked_request.model_profile.model:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.MODEL_MISMATCH)
    try:
        content_bytes = envelope.content.encode("utf-8")
    except UnicodeEncodeError as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_PROVIDER_ENVELOPE
        ) from error
    if (
        envelope.response_id != checked_receipt.provider_response_id
        or envelope.model != checked_receipt.provider_model
        or hashlib.sha256(content_bytes).hexdigest() != checked_receipt.assistant_content_sha256
        or len(content_bytes) != checked_receipt.assistant_content_byte_count
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    try:
        materialized = materialize_ai_requirement_wire_v2(
            envelope.content,
            company_id=checked_request.company_id,
            source_document_id=checked_request.source_document_id,
            source_sha256=checked_request.source_sha256,
            source_blocks=source_blocks,
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_WIRE_RESPONSE
        ) from error

    fields: dict[str, object] = {
        "company_id": checked_request.company_id,
        "result_id": result_id,
        "transfer_id": checked_request.transfer_id,
        "execution_id": checked_claim.execution_id,
        "ordinal": checked_claim.ordinal,
        "claim_id": checked_claim.claim_id,
        "receipt_id": checked_receipt.receipt_id,
        "raw_response_id": checked_raw.raw_response_id,
        "request_payload_sha256": checked_request.payload_sha256,
        "claim_payload_sha256": checked_claim.payload_sha256,
        "receipt_payload_sha256": checked_receipt.payload_sha256,
        "raw_metadata_sha256": checked_raw.metadata_sha256,
        "request_sha256": checked_claim.request_sha256,
        "response_body_sha256": checked_raw.response_body_sha256,
        "assistant_content_sha256": checked_receipt.assistant_content_sha256,
        "provider_response_id": envelope.response_id,
        "provider_model": envelope.model,
        "source_document_id": checked_request.source_document_id,
        "source_sha256": checked_request.source_sha256,
        "extraction_sha256": checked_request.extraction_sha256,
        "source_block_ids": checked_request.chunks[checked_claim.ordinal - 1].source_block_ids,
        "candidates": materialized.candidates,
        "item_candidates": materialized.item_candidates,
        "unresolved_block_ids": materialized.unresolved_block_ids,
        "execution_status": AiRequirementRunStatus.COMPLETE,
        "completeness_status": CompletenessStatus.UNKNOWN,
        "prepared_by": prepared_by,
        "materialized_by": materialized_by,
        "materialized_at": materialized_at,
    }
    payload_sha256 = canonical_json_sha256(
        {"schema_version": AI_TRANSFER_REQUIREMENT_RESULT_SCHEMA_VERSION, **fields}
    )
    try:
        return AiTransferRequirementResult.model_validate(
            {**fields, "payload_sha256": payload_sha256}, strict=True
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_BINDING
        ) from error


def build_ai_transfer_requirement_batch_result(
    request: PersistedAiTransferRequest,
    chunk_results: tuple[AiTransferRequirementResult, ...],
    *,
    batch_result_id: str,
    aggregated_by: str,
    aggregated_at: datetime,
) -> AiTransferRequirementBatchResult:
    """Aggregate a complete ordered batch without weakening provenance or completeness."""
    try:
        checked_request = PersistedAiTransferRequest.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        checked_results = tuple(
            AiTransferRequirementResult.model_validate(
                result.model_dump(mode="python"), strict=True
            )
            for result in chunk_results
        )
    except (AttributeError, TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_BINDING
        ) from error
    if aggregated_at.utcoffset() is None:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    if len(checked_results) != len(checked_request.chunks):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)

    aggregate_utc = aggregated_at.astimezone(UTC)
    requirement_candidates: dict[str, AiRequirementCandidate] = {}
    item_candidates: dict[str, AiProcurementItemCandidate] = {}
    unresolved_ids: set[str] = set()
    covered_ids: set[str] = set()
    for ordinal, (chunk, result) in enumerate(
        zip(checked_request.chunks, checked_results, strict=True), start=1
    ):
        if (
            result.company_id != checked_request.company_id
            or result.transfer_id != checked_request.transfer_id
            or result.request_payload_sha256 != checked_request.payload_sha256
            or result.source_document_id != checked_request.source_document_id
            or result.source_sha256 != checked_request.source_sha256
            or result.extraction_sha256 != checked_request.extraction_sha256
            or result.prepared_by != checked_request.prepared_by
            or result.ordinal != ordinal
            or result.request_sha256 != chunk.request_sha256
            or result.source_block_ids != chunk.source_block_ids
            or aggregate_utc < result.materialized_at.astimezone(UTC)
        ):
            raise AiTransferRequirementResultError(
                AiTransferRequirementResultErrorCode.INVALID_BINDING
            )
        covered_ids.update(result.source_block_ids)
        unresolved_ids.update(result.unresolved_block_ids)
        for candidate in result.candidates:
            _merge_exact_candidate(requirement_candidates, candidate)
        for item in result.item_candidates:
            _merge_exact_item_candidate(item_candidates, item)
    if covered_ids != set(checked_request.source_block_ids):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)

    fields: dict[str, object] = {
        "company_id": checked_request.company_id,
        "batch_result_id": batch_result_id,
        "transfer_id": checked_request.transfer_id,
        "execution_id": checked_results[0].execution_id,
        "request_payload_sha256": checked_request.payload_sha256,
        "source_document_id": checked_request.source_document_id,
        "source_sha256": checked_request.source_sha256,
        "extraction_sha256": checked_request.extraction_sha256,
        "source_block_ids": checked_request.source_block_ids,
        "chunk_results": checked_results,
        "candidates": tuple(requirement_candidates.values()),
        "item_candidates": tuple(item_candidates.values()),
        "unresolved_block_ids": tuple(
            block_id for block_id in checked_request.source_block_ids if block_id in unresolved_ids
        ),
        "execution_status": AiRequirementRunStatus.COMPLETE,
        "completeness_status": CompletenessStatus.UNKNOWN,
        "prepared_by": checked_request.prepared_by,
        "aggregated_by": aggregated_by,
        "aggregated_at": aggregated_at,
    }
    payload_sha256 = canonical_json_sha256(
        {"schema_version": AI_TRANSFER_REQUIREMENT_BATCH_SCHEMA_VERSION, **fields}
    )
    try:
        return AiTransferRequirementBatchResult.model_validate(
            {**fields, "payload_sha256": payload_sha256}, strict=True
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_BINDING
        ) from error


def build_ai_transfer_requirement_materialization(
    request: PersistedAiTransferRequest,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw_metadata: AiTransferRawMetadata,
    *,
    materialization_id: str,
    status: Literal["MATERIALIZED", "REJECTED"],
    reason: Literal[
        "MATERIALIZED",
        "UNSUPPORTED_MULTI_CHUNK",
        "INVALID_CANDIDATE_EVIDENCE",
    ],
    result: AiTransferRequirementResult | None,
    run_id: str | None,
    run_evidence_sha256: str | None,
    materialized_by: str,
    materialized_at: datetime,
) -> AiTransferRequirementMaterialization:
    """Build one append-only semantic receipt from exact durable transport evidence."""
    checked_request, checked_claim, checked_receipt, checked_raw = _validate_inputs(
        request, claim, receipt, raw_metadata
    )
    _require_success_binding(checked_request, checked_claim, checked_receipt, checked_raw)
    if materialized_at.utcoffset() is None:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    materialized_utc = materialized_at.astimezone(UTC)
    if (
        materialized_utc < checked_receipt.recorded_at.astimezone(UTC)
        or materialized_utc < checked_raw.received_at.astimezone(UTC)
        or (
            reason != "UNSUPPORTED_MULTI_CHUNK"
            and materialized_utc >= checked_raw.expires_at.astimezone(UTC)
        )
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    checked_result: AiTransferRequirementResult | None = None
    if result is not None:
        try:
            checked_result = AiTransferRequirementResult.model_validate(
                result.model_dump(mode="python"), strict=True
            )
        except (AttributeError, TypeError, ValidationError, ValueError) as error:
            raise AiTransferRequirementResultError(
                AiTransferRequirementResultErrorCode.INVALID_BINDING
            ) from error
        if (
            checked_result.company_id != checked_request.company_id
            or checked_result.transfer_id != checked_request.transfer_id
            or checked_result.execution_id != checked_claim.execution_id
            or checked_result.ordinal != checked_claim.ordinal
            or checked_result.claim_id != checked_claim.claim_id
            or checked_result.receipt_id != checked_receipt.receipt_id
            or checked_result.raw_response_id != checked_raw.raw_response_id
            or checked_result.request_payload_sha256 != checked_request.payload_sha256
            or checked_result.claim_payload_sha256 != checked_claim.payload_sha256
            or checked_result.receipt_payload_sha256 != checked_receipt.payload_sha256
            or checked_result.raw_metadata_sha256 != checked_raw.metadata_sha256
            or checked_result.request_sha256 != checked_claim.request_sha256
            or checked_result.response_body_sha256 != checked_raw.response_body_sha256
            or checked_result.assistant_content_sha256 != checked_receipt.assistant_content_sha256
            or checked_result.provider_response_id != checked_receipt.provider_response_id
            or checked_result.provider_model != checked_receipt.provider_model
            or checked_result.source_document_id != checked_request.source_document_id
            or checked_result.source_sha256 != checked_request.source_sha256
            or checked_result.extraction_sha256 != checked_request.extraction_sha256
            or checked_result.source_block_ids != checked_request.source_block_ids
            or checked_result.prepared_by != checked_request.prepared_by
            or checked_result.materialized_by != materialized_by
            or checked_result.materialized_at != materialized_at
        ):
            raise AiTransferRequirementResultError(
                AiTransferRequirementResultErrorCode.INVALID_BINDING
            )
    fields: dict[str, object] = {
        "company_id": checked_request.company_id,
        "materialization_id": materialization_id,
        "transfer_id": checked_request.transfer_id,
        "execution_id": checked_claim.execution_id,
        "ordinal": 1,
        "claim_id": checked_claim.claim_id,
        "receipt_id": checked_receipt.receipt_id,
        "raw_response_id": checked_raw.raw_response_id,
        "request_payload_sha256": checked_request.payload_sha256,
        "claim_payload_sha256": checked_claim.payload_sha256,
        "receipt_payload_sha256": checked_receipt.payload_sha256,
        "raw_metadata_sha256": checked_raw.metadata_sha256,
        "parser_version": AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
        "status": status,
        "reason": reason,
        "result_id": checked_result.result_id if checked_result is not None else None,
        "result_payload_sha256": (
            checked_result.payload_sha256 if checked_result is not None else None
        ),
        "run_id": run_id,
        "run_evidence_sha256": run_evidence_sha256,
        "materialized_by": materialized_by,
        "materialized_at": materialized_at,
    }
    payload_sha256 = canonical_json_sha256(
        {
            "schema_version": AI_TRANSFER_REQUIREMENT_MATERIALIZATION_SCHEMA_VERSION,
            **fields,
        }
    )
    try:
        return AiTransferRequirementMaterialization.model_validate(
            {**fields, "payload_sha256": payload_sha256}, strict=True
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_BINDING
        ) from error


def build_ai_transfer_requirement_chunk_rejection(
    request: PersistedAiTransferRequest,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw_metadata: AiTransferRawMetadata,
    *,
    rejection_id: str,
    rejected_by: str,
    rejected_at: datetime,
) -> AiTransferRequirementChunkRejection:
    """Bind one terminal semantic rejection to exact successful transport evidence."""
    checked_request, checked_claim, checked_receipt, checked_raw = _validate_inputs(
        request, claim, receipt, raw_metadata
    )
    _require_success_binding(checked_request, checked_claim, checked_receipt, checked_raw)
    if rejected_at.utcoffset() is None:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    rejected_utc = rejected_at.astimezone(UTC)
    if (
        rejected_utc < checked_receipt.recorded_at.astimezone(UTC)
        or rejected_utc < checked_raw.received_at.astimezone(UTC)
        or rejected_utc >= checked_raw.expires_at.astimezone(UTC)
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    fields: dict[str, object] = {
        "company_id": checked_request.company_id,
        "rejection_id": rejection_id,
        "transfer_id": checked_request.transfer_id,
        "execution_id": checked_claim.execution_id,
        "ordinal": checked_claim.ordinal,
        "claim_id": checked_claim.claim_id,
        "receipt_id": checked_receipt.receipt_id,
        "raw_response_id": checked_raw.raw_response_id,
        "request_payload_sha256": checked_request.payload_sha256,
        "claim_payload_sha256": checked_claim.payload_sha256,
        "receipt_payload_sha256": checked_receipt.payload_sha256,
        "raw_metadata_sha256": checked_raw.metadata_sha256,
        "parser_version": AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
        "reason": "INVALID_CANDIDATE_EVIDENCE",
        "rejected_by": rejected_by,
        "rejected_at": rejected_at,
    }
    payload_sha256 = canonical_json_sha256(
        {"schema_version": AI_TRANSFER_REQUIREMENT_CHUNK_REJECTION_SCHEMA_VERSION, **fields}
    )
    try:
        return AiTransferRequirementChunkRejection.model_validate(
            {**fields, "payload_sha256": payload_sha256}, strict=True
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_BINDING
        ) from error


def _validate_inputs(
    request: PersistedAiTransferRequest,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw_metadata: AiTransferRawMetadata,
) -> tuple[
    PersistedAiTransferRequest,
    AiTransferDispatchClaim,
    AiTransferDispatchReceipt,
    AiTransferRawMetadata,
]:
    try:
        return (
            PersistedAiTransferRequest.model_validate(
                request.model_dump(mode="python"), strict=True
            ),
            AiTransferDispatchClaim.model_validate(claim.model_dump(mode="python"), strict=True),
            AiTransferDispatchReceipt.model_validate(
                receipt.model_dump(mode="python"), strict=True
            ),
            AiTransferRawMetadata.model_validate(
                raw_metadata.model_dump(mode="python"), strict=True
            ),
        )
    except (AttributeError, TypeError, ValidationError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.INVALID_BINDING
        ) from error


def _require_success_binding(
    request: PersistedAiTransferRequest,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw: AiTransferRawMetadata,
) -> None:
    if claim.ordinal > len(request.chunks):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    chunk = request.chunks[claim.ordinal - 1]
    valid = (
        claim.company_id == request.company_id
        and receipt.company_id == request.company_id
        and raw.company_id == request.company_id
        and claim.transfer_id == request.transfer_id
        and receipt.transfer_id == request.transfer_id
        and raw.transfer_id == request.transfer_id
        and receipt.execution_id == claim.execution_id == raw.execution_id
        and claim.request_payload_sha256 == request.payload_sha256
        and receipt.claim_id == claim.claim_id == raw.claim_id
        and receipt.claim_payload_sha256 == claim.payload_sha256
        and raw.claim_payload_sha256 == claim.payload_sha256
        and raw.receipt_id == receipt.receipt_id
        and raw.receipt_payload_sha256 == receipt.payload_sha256
        and claim.ordinal == receipt.ordinal == raw.ordinal
        and claim.chunk_id == receipt.chunk_id == raw.chunk_id == chunk.chunk_id
        and claim.request_sha256
        == receipt.request_sha256
        == raw.request_sha256
        == chunk.request_sha256
        and receipt.outcome == "SUCCESS"
        and receipt.reason == "VALIDATED_RESPONSE"
        and receipt.capture_complete
        and receipt.response_body_sha256 == raw.response_body_sha256
        and receipt.captured_byte_count == raw.response_byte_count
        and receipt.provider_response_id is not None
        and receipt.provider_model is not None
        and receipt.assistant_content_sha256 is not None
        and receipt.assistant_content_byte_count is not None
    )
    if not valid:
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)


def _validate_source(
    request: PersistedAiTransferRequest,
    extraction: ExtractionResult,
    ordinal: int,
) -> tuple[AiSourceBlock, ...]:
    native = {Extractor.NATIVE_PDF, Extractor.NATIVE_DOCX, Extractor.NATIVE_XLSX}
    if (
        extraction.status is not ExtractionStatus.PASS
        or extraction.reasons
        or not extraction.blocks
        or extraction.source_units_extracted != extraction.source_units_total
        or any(block.provenance.extractor not in native for block in extraction.blocks)
        or {block.provenance.document_id for block in extraction.blocks}
        != {request.source_document_id}
        or canonical_json_sha256(extraction) != request.extraction_sha256
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.SOURCE_MISMATCH)
    if ordinal > len(request.chunks):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.SOURCE_MISMATCH)
    chunk = request.chunks[ordinal - 1]
    try:
        records = parse_ai_requirement_transfer_source_records(chunk.request_body_json)
    except (TypeError, ValueError) as error:
        raise AiTransferRequirementResultError(
            AiTransferRequirementResultErrorCode.SOURCE_MISMATCH
        ) from error
    expected_ids = tuple(f"b{index:06d}" for index in range(1, len(extraction.blocks) + 1))
    if (
        request.source_block_ids != expected_ids
        or tuple(record[0] for record in records) != chunk.source_block_ids
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.SOURCE_MISMATCH)
    block_by_id = dict(zip(expected_ids, extraction.blocks, strict=True))
    source_blocks: list[AiSourceBlock] = []
    for record in records:
        block_id, locator, text = record
        block = block_by_id.get(block_id)
        if block is None or locator != block.provenance.locator or text != block.text:
            raise AiTransferRequirementResultError(
                AiTransferRequirementResultErrorCode.SOURCE_MISMATCH
            )
        source_blocks.append(
            AiSourceBlock(block_id=block_id, text=block.text, provenance=block.provenance)
        )
    return tuple(source_blocks)


def _merge_exact_candidate(
    candidates: dict[str, AiRequirementCandidate], candidate: AiRequirementCandidate
) -> None:
    existing = candidates.get(candidate.candidate_id)
    if existing is None:
        candidates[candidate.candidate_id] = candidate
        return
    if existing.model_dump(exclude={"uncertainties"}) != candidate.model_dump(
        exclude={"uncertainties"}
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    candidates[candidate.candidate_id] = existing.model_copy(
        update={
            "uncertainties": tuple(
                dict.fromkeys((*existing.uncertainties, *candidate.uncertainties))
            )
        }
    )


def _merge_exact_item_candidate(
    candidates: dict[str, AiProcurementItemCandidate], candidate: AiProcurementItemCandidate
) -> None:
    existing = candidates.get(candidate.candidate_id)
    if existing is None:
        candidates[candidate.candidate_id] = candidate
        return
    if existing.model_dump(exclude={"uncertainties"}) != candidate.model_dump(
        exclude={"uncertainties"}
    ):
        raise AiTransferRequirementResultError(AiTransferRequirementResultErrorCode.INVALID_BINDING)
    candidates[candidate.candidate_id] = existing.model_copy(
        update={
            "uncertainties": tuple(
                dict.fromkeys((*existing.uncertainties, *candidate.uncertainties))
            )
        }
    )


def _item_evidence_ids(item: AiProcurementItemCandidate) -> tuple[str, ...]:
    ids = [block.block_id for block in item.item_name.evidence]
    for claim in (*item.okpd2_codes, *item.ktru_codes):
        ids.extend(block.block_id for block in claim.evidence)
    if item.unit is not None:
        ids.extend(block.block_id for block in item.unit.evidence)
    if item.quantity is not None:
        ids.extend(block.block_id for block in item.quantity.evidence)
    return tuple(ids)


__all__ = [
    "AI_TRANSFER_REQUIREMENT_BATCH_SCHEMA_VERSION",
    "AI_TRANSFER_REQUIREMENT_CHUNK_REJECTION_SCHEMA_VERSION",
    "AI_TRANSFER_REQUIREMENT_MATERIALIZATION_SCHEMA_VERSION",
    "AI_TRANSFER_REQUIREMENT_PARSER_VERSION",
    "AI_TRANSFER_REQUIREMENT_RESULT_SCHEMA_VERSION",
    "AiTransferRequirementBatchResult",
    "AiTransferRequirementChunkRejection",
    "AiTransferRequirementMaterialization",
    "AiTransferRequirementResult",
    "AiTransferRequirementResultError",
    "AiTransferRequirementResultErrorCode",
    "build_ai_transfer_requirement_batch_result",
    "build_ai_transfer_requirement_chunk_rejection",
    "build_ai_transfer_requirement_materialization",
    "build_ai_transfer_requirement_result",
]
