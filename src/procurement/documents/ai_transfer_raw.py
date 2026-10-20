"""Encrypted-at-rest contract for one complete external AI response capture.

This module deliberately provides no default key.  Production code must supply
an authenticated, tenant-aware KEK provider; tests may use an ephemeral one.
Plaintext response bytes and key material never become model fields.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, Self

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.ai_transfer import MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES
from procurement.documents.completeness_review import canonical_json_sha256

AI_TRANSFER_RAW_BINDING_SCHEMA_VERSION: Literal["ai-transfer-raw-binding-v1"] = (
    "ai-transfer-raw-binding-v1"
)
AI_TRANSFER_RAW_METADATA_SCHEMA_VERSION: Literal["ai-transfer-raw-metadata-v1"] = (
    "ai-transfer-raw-metadata-v1"
)
AI_TRANSFER_RAW_ENVELOPE_SCHEMA_VERSION: Literal["ai-transfer-raw-envelope-v1"] = (
    "ai-transfer-raw-envelope-v1"
)
AI_TRANSFER_RAW_DELETION_RECEIPT_SCHEMA_VERSION: Literal["ai-transfer-raw-deletion-receipt-v1"] = (
    "ai-transfer-raw-deletion-receipt-v1"
)
AI_TRANSFER_RAW_ALGORITHM: Literal["AES-256-GCM+TENANT-KEK-V1"] = "AES-256-GCM+TENANT-KEK-V1"
AI_TRANSFER_RAW_RETENTION = timedelta(hours=720)
_AES_GCM_NONCE_BYTES = 12
_AES_256_KEY_BYTES = 32
_AES_GCM_TAG_BYTES = 16


class AiTransferRawErrorCode(StrEnum):
    """Stable non-sensitive failures exposed by the crypto boundary."""

    INVALID_INPUT = "INVALID_INPUT"
    KEY_UNAVAILABLE = "KEY_UNAVAILABLE"
    ENCRYPTION_FAILED = "ENCRYPTION_FAILED"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    EXPIRED = "EXPIRED"
    RETENTION_ACTIVE = "RETENTION_ACTIVE"


_ERROR_MESSAGES = {
    AiTransferRawErrorCode.INVALID_INPUT: "raw response input is invalid",
    AiTransferRawErrorCode.KEY_UNAVAILABLE: "tenant encryption key is unavailable",
    AiTransferRawErrorCode.ENCRYPTION_FAILED: "raw response encryption failed",
    AiTransferRawErrorCode.BINDING_MISMATCH: "raw response binding does not match",
    AiTransferRawErrorCode.AUTHENTICATION_FAILED: "raw response authentication failed",
    AiTransferRawErrorCode.EXPIRED: "raw response retention has expired",
    AiTransferRawErrorCode.RETENTION_ACTIVE: "raw response retention is still active",
}


class AiTransferRawError(Exception):
    """A fixed-message failure that cannot echo plaintext or key material."""

    def __init__(self, code: AiTransferRawErrorCode) -> None:
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


class TenantKekProvider(Protocol):
    """Tenant KEK boundary; implementations own key lookup and key material."""

    def active_key_id(self, *, company_id: str) -> str:
        """Return the versioned identifier of the active tenant KEK."""

    def wrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        dek: bytes,
        aad: bytes,
    ) -> bytes:
        """Authenticate and encrypt one 32-byte DEK with the identified KEK."""

    def unwrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        wrapped_dek: bytes,
        aad: bytes,
    ) -> bytes:
        """Authenticate and decrypt one DEK with the identified tenant KEK."""


class AiTransferRawBinding(BaseModel):
    """Trusted complete-capture facts that encryption must bind exactly."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-raw-binding-v1"] = AI_TRANSFER_RAW_BINDING_SCHEMA_VERSION
    company_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    ordinal: int = Field(ge=1, le=9_999)
    claim_id: str = Field(min_length=1, max_length=200)
    chunk_id: str = Field(pattern=r"^chunk-\d{4}$")
    claim_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str = Field(min_length=1, max_length=200)
    receipt_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_byte_count: int = Field(ge=0, le=MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES)
    received_at: datetime

    @field_validator(
        "company_id",
        "raw_response_id",
        "transfer_id",
        "execution_id",
        "claim_id",
        "receipt_id",
    )
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        return _require_safe_text(value, "raw response identifier")

    @field_validator("received_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value)


class AiTransferRawMetadata(BaseModel):
    """Immutable storage metadata; contains neither plaintext nor key bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-raw-metadata-v1"] = AI_TRANSFER_RAW_METADATA_SCHEMA_VERSION
    company_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    ordinal: int = Field(ge=1, le=9_999)
    claim_id: str = Field(min_length=1, max_length=200)
    chunk_id: str = Field(pattern=r"^chunk-\d{4}$")
    claim_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str = Field(min_length=1, max_length=200)
    receipt_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_byte_count: int = Field(ge=0, le=MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES)
    received_at: datetime
    expires_at: datetime
    algorithm: Literal["AES-256-GCM+TENANT-KEK-V1"] = AI_TRANSFER_RAW_ALGORITHM
    key_id: str = Field(min_length=1, max_length=200)
    body_aad_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "raw_response_id",
        "transfer_id",
        "execution_id",
        "claim_id",
        "receipt_id",
        "key_id",
    )
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _require_safe_text(value, "raw response metadata")

    @field_validator("received_at", "expires_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def _exact_binding(self) -> Self:
        if self.expires_at.astimezone(UTC) - self.received_at.astimezone(UTC) != (
            AI_TRANSFER_RAW_RETENTION
        ):
            raise ValueError("raw response expiry must be exactly 720 hours")
        if self.body_aad_sha256 != _sha256(_body_aad_bytes(self)):
            raise ValueError("raw response body AAD digest mismatch")
        payload = self.model_dump(mode="json", exclude={"metadata_sha256"})
        if self.metadata_sha256 != canonical_json_sha256(payload):
            raise ValueError("raw response metadata digest mismatch")
        return self


class AiTransferRawEnvelope(BaseModel):
    """Authenticated encrypted body plus wrapped per-blob DEK."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-raw-envelope-v1"] = AI_TRANSFER_RAW_ENVELOPE_SCHEMA_VERSION
    metadata: AiTransferRawMetadata
    raw_response_id: str = Field(min_length=1, max_length=200)
    algorithm: Literal["AES-256-GCM+TENANT-KEK-V1"] = AI_TRANSFER_RAW_ALGORITHM
    key_id: str = Field(min_length=1, max_length=200)
    body_nonce: bytes = Field(min_length=_AES_GCM_NONCE_BYTES, repr=False)
    ciphertext: bytes = Field(min_length=_AES_GCM_TAG_BYTES, repr=False)
    wrapping_nonce: bytes = Field(min_length=_AES_GCM_NONCE_BYTES, repr=False)
    wrapped_dek: bytes = Field(min_length=_AES_256_KEY_BYTES + _AES_GCM_TAG_BYTES, repr=False)
    wrap_aad_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("raw_response_id", "key_id")
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _require_safe_text(value, "raw response envelope")

    @model_validator(mode="after")
    def _exact_envelope(self) -> Self:
        if (
            self.raw_response_id != self.metadata.raw_response_id
            or self.algorithm != self.metadata.algorithm
            or self.key_id != self.metadata.key_id
        ):
            raise ValueError("raw response envelope projection mismatch")
        if len(self.body_nonce) != _AES_GCM_NONCE_BYTES:
            raise ValueError("raw response body nonce length is invalid")
        if len(self.wrapping_nonce) != _AES_GCM_NONCE_BYTES:
            raise ValueError("raw response wrapping nonce length is invalid")
        if self.body_nonce == self.wrapping_nonce:
            raise ValueError("raw response nonces must be distinct")
        if len(self.ciphertext) != self.metadata.response_byte_count + _AES_GCM_TAG_BYTES:
            raise ValueError("raw response ciphertext length mismatch")
        if len(self.wrapped_dek) != _AES_256_KEY_BYTES + _AES_GCM_TAG_BYTES:
            raise ValueError("wrapped data key length mismatch")
        wrap_aad = _wrap_aad_bytes(self.metadata)
        if self.wrap_aad_sha256 != _sha256(wrap_aad):
            raise ValueError("wrapped data key AAD digest mismatch")
        if self.envelope_sha256 != _envelope_sha256(self):
            raise ValueError("raw response envelope digest mismatch")
        return self


class AiTransferRawDeletionReceipt(BaseModel):
    """Long-lived evidence that expired ciphertext and wrapped key were deleted."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-raw-deletion-receipt-v1"] = (
        AI_TRANSFER_RAW_DELETION_RECEIPT_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    raw_response_id: str = Field(min_length=1, max_length=200)
    deletion_receipt_id: str = Field(min_length=1, max_length=200)
    receipt_id: str = Field(min_length=1, max_length=200)
    response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_byte_count: int = Field(ge=0, le=MAX_PERSISTED_AI_TRANSFER_RESPONSE_CAPTURE_BYTES)
    received_at: datetime
    expires_at: datetime
    metadata_schema_version: Literal["ai-transfer-raw-metadata-v1"] = (
        AI_TRANSFER_RAW_METADATA_SCHEMA_VERSION
    )
    algorithm: Literal["AES-256-GCM+TENANT-KEK-V1"] = AI_TRANSFER_RAW_ALGORITHM
    key_id: str = Field(min_length=1, max_length=200)
    body_aad_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wrap_aad_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: Literal["RETENTION_EXPIRED"] = "RETENTION_EXPIRED"
    deleted_by: str = Field(min_length=1, max_length=200)
    deleted_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "raw_response_id",
        "deletion_receipt_id",
        "receipt_id",
        "key_id",
        "deleted_by",
    )
    @classmethod
    def _safe_text(cls, value: str) -> str:
        return _require_safe_text(value, "raw response deletion receipt")

    @field_validator("received_at", "expires_at", "deleted_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def _exact_receipt(self) -> Self:
        if self.expires_at.astimezone(UTC) - self.received_at.astimezone(UTC) != (
            AI_TRANSFER_RAW_RETENTION
        ):
            raise ValueError("raw response expiry must be exactly 720 hours")
        if self.deleted_at.astimezone(UTC) < self.expires_at.astimezone(UTC):
            raise ValueError("raw response cannot be deleted before retention expiry")
        payload = self.model_dump(mode="json", exclude={"payload_sha256"})
        if self.payload_sha256 != canonical_json_sha256(payload):
            raise ValueError("raw response deletion receipt digest mismatch")
        return self


def build_ai_transfer_raw_deletion_receipt(
    metadata: AiTransferRawMetadata,
    *,
    wrap_aad_sha256: str,
    envelope_sha256: str,
    deletion_receipt_id: str,
    deleted_by: str,
    deleted_at: datetime,
) -> AiTransferRawDeletionReceipt:
    """Build exact append-only evidence for an authorized expired-blob purge."""
    try:
        checked = AiTransferRawMetadata.model_validate(metadata.model_dump(mode="python"))
        checked_deleted_at = _require_aware(deleted_at)
        checked_deletion_id = _require_safe_text(
            deletion_receipt_id, "raw response deletion receipt ID"
        )
        checked_actor = _require_safe_text(deleted_by, "raw response deletion actor")
    except (AttributeError, TypeError, ValueError) as error:
        raise AiTransferRawError(AiTransferRawErrorCode.INVALID_INPUT) from error
    if checked_deleted_at.astimezone(UTC) < checked.expires_at.astimezone(UTC):
        raise AiTransferRawError(AiTransferRawErrorCode.RETENTION_ACTIVE)
    unsigned = AiTransferRawDeletionReceipt.model_construct(
        schema_version=AI_TRANSFER_RAW_DELETION_RECEIPT_SCHEMA_VERSION,
        company_id=checked.company_id,
        raw_response_id=checked.raw_response_id,
        deletion_receipt_id=checked_deletion_id,
        receipt_id=checked.receipt_id,
        response_body_sha256=checked.response_body_sha256,
        response_byte_count=checked.response_byte_count,
        received_at=checked.received_at,
        expires_at=checked.expires_at,
        metadata_schema_version=checked.schema_version,
        algorithm=checked.algorithm,
        key_id=checked.key_id,
        body_aad_sha256=checked.body_aad_sha256,
        metadata_sha256=checked.metadata_sha256,
        wrap_aad_sha256=wrap_aad_sha256,
        envelope_sha256=envelope_sha256,
        reason="RETENTION_EXPIRED",
        deleted_by=checked_actor,
        deleted_at=checked_deleted_at,
        payload_sha256="0" * 64,
    )
    return AiTransferRawDeletionReceipt(
        schema_version=AI_TRANSFER_RAW_DELETION_RECEIPT_SCHEMA_VERSION,
        company_id=checked.company_id,
        raw_response_id=checked.raw_response_id,
        deletion_receipt_id=checked_deletion_id,
        receipt_id=checked.receipt_id,
        response_body_sha256=checked.response_body_sha256,
        response_byte_count=checked.response_byte_count,
        received_at=checked.received_at,
        expires_at=checked.expires_at,
        metadata_schema_version=checked.schema_version,
        algorithm=checked.algorithm,
        key_id=checked.key_id,
        body_aad_sha256=checked.body_aad_sha256,
        metadata_sha256=checked.metadata_sha256,
        wrap_aad_sha256=wrap_aad_sha256,
        envelope_sha256=envelope_sha256,
        reason="RETENTION_EXPIRED",
        deleted_by=checked_actor,
        deleted_at=checked_deleted_at,
        payload_sha256=canonical_json_sha256(
            unsigned.model_dump(mode="json", exclude={"payload_sha256"})
        ),
    )


def encrypt_ai_transfer_raw_response(
    *,
    binding: AiTransferRawBinding,
    raw_response_body: bytes,
    key_provider: TenantKekProvider,
) -> AiTransferRawEnvelope:
    """Encrypt one complete, bounded capture with a random DEK and exact 30-day expiry."""

    if type(raw_response_body) is not bytes:  # bytes only: no mutable buffer aliasing
        raise AiTransferRawError(AiTransferRawErrorCode.INVALID_INPUT)
    try:
        checked_binding = AiTransferRawBinding.model_validate(binding.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError):
        raise AiTransferRawError(AiTransferRawErrorCode.INVALID_INPUT) from None
    if len(raw_response_body) != checked_binding.response_byte_count or (
        _sha256(raw_response_body) != checked_binding.response_body_sha256
    ):
        raise AiTransferRawError(AiTransferRawErrorCode.BINDING_MISMATCH)
    try:
        key_id = _require_safe_text(
            key_provider.active_key_id(company_id=checked_binding.company_id), "tenant key id"
        )
        if len(key_id) > 200:
            raise ValueError("tenant key id is too long")
    except Exception:
        raise AiTransferRawError(AiTransferRawErrorCode.KEY_UNAVAILABLE) from None

    metadata = _build_metadata(binding=checked_binding, key_id=key_id)
    body_aad = _body_aad_bytes(metadata)
    wrap_aad = _wrap_aad_bytes(metadata)
    dek = AESGCM.generate_key(bit_length=256)
    body_nonce = os.urandom(_AES_GCM_NONCE_BYTES)
    wrapping_nonce = os.urandom(_AES_GCM_NONCE_BYTES)
    while wrapping_nonce == body_nonce:
        wrapping_nonce = os.urandom(_AES_GCM_NONCE_BYTES)
    try:
        ciphertext = AESGCM(dek).encrypt(body_nonce, raw_response_body, body_aad)
        wrapped_dek = key_provider.wrap_dek(
            company_id=checked_binding.company_id,
            key_id=key_id,
            nonce=wrapping_nonce,
            dek=dek,
            aad=wrap_aad,
        )
    except Exception:
        raise AiTransferRawError(AiTransferRawErrorCode.ENCRYPTION_FAILED) from None
    if type(wrapped_dek) is not bytes or len(wrapped_dek) != (
        _AES_256_KEY_BYTES + _AES_GCM_TAG_BYTES
    ):
        raise AiTransferRawError(AiTransferRawErrorCode.ENCRYPTION_FAILED)

    wrap_aad_sha256 = _sha256(wrap_aad)
    unsigned = AiTransferRawEnvelope.model_construct(
        schema_version=AI_TRANSFER_RAW_ENVELOPE_SCHEMA_VERSION,
        metadata=metadata,
        raw_response_id=metadata.raw_response_id,
        algorithm=metadata.algorithm,
        key_id=metadata.key_id,
        body_nonce=body_nonce,
        ciphertext=ciphertext,
        wrapping_nonce=wrapping_nonce,
        wrapped_dek=wrapped_dek,
        wrap_aad_sha256=wrap_aad_sha256,
        envelope_sha256="0" * 64,
    )
    return AiTransferRawEnvelope(
        metadata=metadata,
        raw_response_id=metadata.raw_response_id,
        algorithm=metadata.algorithm,
        key_id=metadata.key_id,
        body_nonce=body_nonce,
        ciphertext=ciphertext,
        wrapping_nonce=wrapping_nonce,
        wrapped_dek=wrapped_dek,
        wrap_aad_sha256=wrap_aad_sha256,
        envelope_sha256=_envelope_sha256(unsigned),
    )


def decrypt_ai_transfer_raw_response(
    *,
    envelope: AiTransferRawEnvelope,
    expected_metadata: AiTransferRawMetadata,
    key_provider: TenantKekProvider,
    at: datetime,
) -> bytes:
    """Authenticate, decrypt, and re-check exact binding, digest, count, and retention."""

    try:
        checked = AiTransferRawEnvelope.model_validate(envelope.model_dump(mode="python"))
        expected = AiTransferRawMetadata.model_validate(expected_metadata.model_dump(mode="python"))
        checked_at = _require_aware(at)
    except (AttributeError, TypeError, ValueError):
        raise AiTransferRawError(AiTransferRawErrorCode.INVALID_INPUT) from None
    if checked.metadata != expected:
        raise AiTransferRawError(AiTransferRawErrorCode.BINDING_MISMATCH)
    if checked_at.astimezone(UTC) >= checked.metadata.expires_at.astimezone(UTC):
        raise AiTransferRawError(AiTransferRawErrorCode.EXPIRED)

    wrap_aad = _wrap_aad_bytes(checked.metadata)
    try:
        dek = key_provider.unwrap_dek(
            company_id=checked.metadata.company_id,
            key_id=checked.key_id,
            nonce=checked.wrapping_nonce,
            wrapped_dek=checked.wrapped_dek,
            aad=wrap_aad,
        )
    except Exception:
        raise AiTransferRawError(AiTransferRawErrorCode.KEY_UNAVAILABLE) from None
    if type(dek) is not bytes or len(dek) != _AES_256_KEY_BYTES:
        raise AiTransferRawError(AiTransferRawErrorCode.KEY_UNAVAILABLE)
    try:
        plaintext = AESGCM(dek).decrypt(
            checked.body_nonce,
            checked.ciphertext,
            _body_aad_bytes(checked.metadata),
        )
    except (InvalidTag, ValueError):
        raise AiTransferRawError(AiTransferRawErrorCode.AUTHENTICATION_FAILED) from None
    if len(plaintext) != checked.metadata.response_byte_count or (
        _sha256(plaintext) != checked.metadata.response_body_sha256
    ):
        raise AiTransferRawError(AiTransferRawErrorCode.AUTHENTICATION_FAILED)
    return plaintext


def _build_metadata(*, binding: AiTransferRawBinding, key_id: str) -> AiTransferRawMetadata:
    expires_at = binding.received_at.astimezone(UTC) + AI_TRANSFER_RAW_RETENTION
    provisional = _construct_metadata(
        binding=binding,
        expires_at=expires_at,
        key_id=key_id,
        body_aad_sha256="0" * 64,
        metadata_sha256="0" * 64,
    )
    body_aad_sha256 = _sha256(_body_aad_bytes(provisional))
    unsigned = _construct_metadata(
        binding=binding,
        expires_at=expires_at,
        key_id=key_id,
        body_aad_sha256=body_aad_sha256,
        metadata_sha256="0" * 64,
    )
    metadata_sha256 = canonical_json_sha256(
        unsigned.model_dump(mode="json", exclude={"metadata_sha256"})
    )
    return AiTransferRawMetadata.model_validate(
        _construct_metadata(
            binding=binding,
            expires_at=expires_at,
            key_id=key_id,
            body_aad_sha256=body_aad_sha256,
            metadata_sha256=metadata_sha256,
        ).model_dump(mode="python")
    )


def _construct_metadata(
    *,
    binding: AiTransferRawBinding,
    expires_at: datetime,
    key_id: str,
    body_aad_sha256: str,
    metadata_sha256: str,
) -> AiTransferRawMetadata:
    return AiTransferRawMetadata.model_construct(
        schema_version=AI_TRANSFER_RAW_METADATA_SCHEMA_VERSION,
        company_id=binding.company_id,
        raw_response_id=binding.raw_response_id,
        transfer_id=binding.transfer_id,
        execution_id=binding.execution_id,
        ordinal=binding.ordinal,
        claim_id=binding.claim_id,
        chunk_id=binding.chunk_id,
        claim_payload_sha256=binding.claim_payload_sha256,
        receipt_id=binding.receipt_id,
        receipt_payload_sha256=binding.receipt_payload_sha256,
        request_sha256=binding.request_sha256,
        response_body_sha256=binding.response_body_sha256,
        response_byte_count=binding.response_byte_count,
        received_at=binding.received_at,
        expires_at=expires_at,
        algorithm=AI_TRANSFER_RAW_ALGORITHM,
        key_id=key_id,
        body_aad_sha256=body_aad_sha256,
        metadata_sha256=metadata_sha256,
    )


def _body_aad_bytes(metadata: AiTransferRawMetadata) -> bytes:
    return _canonical_bytes(
        {
            "schema_version": metadata.schema_version,
            "algorithm": metadata.algorithm,
            "company_id": metadata.company_id,
            "raw_response_id": metadata.raw_response_id,
            "transfer_id": metadata.transfer_id,
            "execution_id": metadata.execution_id,
            "ordinal": metadata.ordinal,
            "claim_id": metadata.claim_id,
            "chunk_id": metadata.chunk_id,
            "claim_payload_sha256": metadata.claim_payload_sha256,
            "receipt_id": metadata.receipt_id,
            "receipt_payload_sha256": metadata.receipt_payload_sha256,
            "request_sha256": metadata.request_sha256,
            "response_body_sha256": metadata.response_body_sha256,
            "response_byte_count": metadata.response_byte_count,
            "received_at": _canonical_time(metadata.received_at),
            "expires_at": _canonical_time(metadata.expires_at),
        }
    )


def _wrap_aad_bytes(metadata: AiTransferRawMetadata) -> bytes:
    return _canonical_bytes(
        {
            "schema_version": metadata.schema_version,
            "algorithm": metadata.algorithm,
            "company_id": metadata.company_id,
            "raw_response_id": metadata.raw_response_id,
            "key_id": metadata.key_id,
            "body_aad_sha256": metadata.body_aad_sha256,
        }
    )


def _envelope_sha256(envelope: AiTransferRawEnvelope) -> str:
    return canonical_json_sha256(
        {
            "schema_version": envelope.schema_version,
            "metadata_sha256": envelope.metadata.metadata_sha256,
            "raw_response_id": envelope.raw_response_id,
            "algorithm": envelope.algorithm,
            "key_id": envelope.key_id,
            "body_nonce": _b64(envelope.body_nonce),
            "ciphertext": _b64(envelope.ciphertext),
            "wrapping_nonce": _b64(envelope.wrapping_nonce),
            "wrapped_dek": _b64(envelope.wrapped_dek),
            "wrap_aad_sha256": envelope.wrap_aad_sha256,
        }
    )


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("raw response time must be timezone-aware")
    return value


def _require_safe_text(value: str, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError(f"{field} must be nonblank and trimmed")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} must not contain control characters")
    return value


__all__ = [
    "AI_TRANSFER_RAW_ALGORITHM",
    "AI_TRANSFER_RAW_BINDING_SCHEMA_VERSION",
    "AI_TRANSFER_RAW_DELETION_RECEIPT_SCHEMA_VERSION",
    "AI_TRANSFER_RAW_ENVELOPE_SCHEMA_VERSION",
    "AI_TRANSFER_RAW_METADATA_SCHEMA_VERSION",
    "AI_TRANSFER_RAW_RETENTION",
    "AiTransferRawBinding",
    "AiTransferRawDeletionReceipt",
    "AiTransferRawEnvelope",
    "AiTransferRawError",
    "AiTransferRawErrorCode",
    "AiTransferRawMetadata",
    "TenantKekProvider",
    "build_ai_transfer_raw_deletion_receipt",
    "decrypt_ai_transfer_raw_response",
    "encrypt_ai_transfer_raw_response",
]
