from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from procurement.documents.ai_transfer_raw import (
    AI_TRANSFER_RAW_RETENTION,
    AiTransferRawBinding,
    AiTransferRawEnvelope,
    AiTransferRawError,
    AiTransferRawErrorCode,
    TenantKekProvider,
    build_ai_transfer_raw_deletion_receipt,
    decrypt_ai_transfer_raw_response,
    encrypt_ai_transfer_raw_response,
)


class EphemeralTenantKekProvider(TenantKekProvider):
    def __init__(self, keys: dict[tuple[str, str], bytes], active: dict[str, str]) -> None:
        self._keys = keys
        self._active = active

    def active_key_id(self, *, company_id: str) -> str:
        return self._active[company_id]

    def wrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        dek: bytes,
        aad: bytes,
    ) -> bytes:
        return AESGCM(self._keys[(company_id, key_id)]).encrypt(nonce, dek, aad)

    def unwrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        wrapped_dek: bytes,
        aad: bytes,
    ) -> bytes:
        return AESGCM(self._keys[(company_id, key_id)]).decrypt(nonce, wrapped_dek, aad)


def _provider(*, key: bytes | None = None) -> EphemeralTenantKekProvider:
    return EphemeralTenantKekProvider(
        {("company-1", "tenant/company-1/kek/v7"): key or bytes(range(32))},
        {"company-1": "tenant/company-1/kek/v7"},
    )


def _binding(body: bytes) -> AiTransferRawBinding:
    return AiTransferRawBinding(
        company_id="company-1",
        raw_response_id="raw-response-1",
        transfer_id="transfer-1",
        execution_id="execution-1",
        ordinal=1,
        claim_id="claim-1",
        chunk_id="chunk-0001",
        claim_payload_sha256="a" * 64,
        receipt_id="receipt-1",
        receipt_payload_sha256="b" * 64,
        request_sha256="c" * 64,
        response_body_sha256=hashlib.sha256(body).hexdigest(),
        response_byte_count=len(body),
        received_at=datetime(2026, 9, 17, 12, 30, tzinfo=UTC),
    )


def _envelope(body: bytes = b"\x00\xffexact\x80binary") -> AiTransferRawEnvelope:
    return encrypt_ai_transfer_raw_response(
        binding=_binding(body), raw_response_body=body, key_provider=_provider()
    )


def _tamper(envelope: AiTransferRawEnvelope, **changes: object) -> AiTransferRawEnvelope:
    payload = envelope.model_dump(mode="python")
    payload["metadata"] = envelope.metadata
    payload.update(changes)
    return AiTransferRawEnvelope.model_construct(**payload)


def test_exact_binary_round_trip_and_exact_720_hour_expiry() -> None:
    body = bytes(range(256)) + b"\x00\xff\x00"
    envelope = _envelope(body)

    assert envelope.metadata.expires_at - envelope.metadata.received_at == (
        AI_TRANSFER_RAW_RETENTION
    )
    assert envelope.body_nonce != envelope.wrapping_nonce
    assert (
        decrypt_ai_transfer_raw_response(
            envelope=envelope,
            expected_metadata=envelope.metadata,
            key_provider=_provider(),
            at=envelope.metadata.received_at + timedelta(days=1),
        )
        == body
    )


@pytest.mark.parametrize("body", [b"", b"\x00"])
def test_complete_capture_can_round_trip_zero_or_one_byte(body: bytes) -> None:
    envelope = _envelope(body)

    assert (
        decrypt_ai_transfer_raw_response(
            envelope=envelope,
            expected_metadata=envelope.metadata,
            key_provider=_provider(),
            at=envelope.metadata.received_at,
        )
        == body
    )


def test_expiry_is_720_absolute_hours_across_dst_change() -> None:
    body = b"response"
    binding = _binding(body).model_copy(
        update={"received_at": datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Europe/Berlin"))}
    )
    envelope = encrypt_ai_transfer_raw_response(
        binding=binding, raw_response_body=body, key_provider=_provider()
    )

    assert (
        envelope.metadata.expires_at.astimezone(UTC)
        - (envelope.metadata.received_at.astimezone(UTC))
        == AI_TRANSFER_RAW_RETENTION
    )


def test_plaintext_and_keys_are_absent_from_repr_and_models() -> None:
    body = b"TOP-SECRET-RAW-PROVIDER-BODY"
    envelope = _envelope(body)
    rendered = repr(envelope)

    assert body.decode() not in rendered
    assert bytes(range(32)).hex() not in rendered
    assert "ciphertext=" not in rendered
    assert "wrapped_dek=" not in rendered
    assert "body_nonce=" not in rendered
    assert "wrapping_nonce=" not in rendered
    assert "raw_response_body" not in AiTransferRawEnvelope.model_fields
    assert "dek" not in AiTransferRawEnvelope.model_fields


def test_plaintext_digest_or_count_mismatch_is_rejected_before_key_use() -> None:
    body = b"complete-response"
    binding = _binding(body)

    with pytest.raises(AiTransferRawError) as digest_error:
        encrypt_ai_transfer_raw_response(
            binding=binding,
            raw_response_body=b"tampered-response",
            key_provider=_provider(),
        )
    assert digest_error.value.code is AiTransferRawErrorCode.BINDING_MISMATCH


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("body_nonce", b"n" * 12),
        ("wrapping_nonce", b"w" * 12),
        ("ciphertext", b"x" * (len(b"\x00\xffexact\x80binary") + 16)),
        ("wrapped_dek", b"k" * 48),
    ],
)
def test_nonce_ciphertext_and_wrapped_key_tampering_is_rejected(
    field: str, replacement: bytes
) -> None:
    envelope = _envelope()
    tampered = _tamper(envelope, **{field: replacement})

    with pytest.raises(AiTransferRawError) as error:
        decrypt_ai_transfer_raw_response(
            envelope=tampered,
            expected_metadata=envelope.metadata,
            key_provider=_provider(),
            at=envelope.metadata.received_at,
        )
    assert error.value.code in {
        AiTransferRawErrorCode.INVALID_INPUT,
        AiTransferRawErrorCode.AUTHENTICATION_FAILED,
        AiTransferRawErrorCode.KEY_UNAVAILABLE,
    }


def test_metadata_aad_tampering_is_rejected() -> None:
    envelope = _envelope()
    metadata_payload = envelope.metadata.model_dump(mode="python")
    metadata_payload["request_sha256"] = "d" * 64
    tampered_metadata = envelope.metadata.model_construct(**metadata_payload)
    tampered = _tamper(envelope, metadata=tampered_metadata)

    with pytest.raises(AiTransferRawError) as error:
        decrypt_ai_transfer_raw_response(
            envelope=tampered,
            expected_metadata=envelope.metadata,
            key_provider=_provider(),
            at=envelope.metadata.received_at,
        )
    assert error.value.code is AiTransferRawErrorCode.INVALID_INPUT


def test_wrong_expected_tenant_binding_is_rejected_before_decryption() -> None:
    body = b"\x00\xffexact\x80binary"
    envelope = _envelope()
    provider = EphemeralTenantKekProvider(
        {
            ("company-1", "tenant/company-1/kek/v7"): bytes(range(32)),
            ("company-2", "tenant/company-2/kek/v3"): b"2" * 32,
        },
        {
            "company-1": "tenant/company-1/kek/v7",
            "company-2": "tenant/company-2/kek/v3",
        },
    )
    wrong_binding = _binding(body).model_copy(
        update={"company_id": "company-2", "raw_response_id": "raw-response-2"}
    )
    wrong_expected = encrypt_ai_transfer_raw_response(
        binding=wrong_binding, raw_response_body=body, key_provider=provider
    ).metadata

    with pytest.raises(AiTransferRawError) as error:
        decrypt_ai_transfer_raw_response(
            envelope=envelope,
            expected_metadata=wrong_expected,
            key_provider=provider,
            at=envelope.metadata.received_at,
        )
    assert error.value.code is AiTransferRawErrorCode.BINDING_MISMATCH


def test_wrong_tenant_key_is_rejected_without_leaking_provider_error() -> None:
    envelope = _envelope()
    wrong_provider = _provider(key=b"z" * 32)

    with pytest.raises(AiTransferRawError) as error:
        decrypt_ai_transfer_raw_response(
            envelope=envelope,
            expected_metadata=envelope.metadata,
            key_provider=wrong_provider,
            at=envelope.metadata.received_at,
        )
    assert error.value.code is AiTransferRawErrorCode.KEY_UNAVAILABLE
    assert str(error.value) == "tenant encryption key is unavailable"


def test_expired_capture_is_not_decrypted() -> None:
    envelope = _envelope()

    with pytest.raises(AiTransferRawError) as error:
        decrypt_ai_transfer_raw_response(
            envelope=envelope,
            expected_metadata=envelope.metadata,
            key_provider=_provider(),
            at=envelope.metadata.expires_at,
        )
    assert error.value.code is AiTransferRawErrorCode.EXPIRED


def test_naive_decryption_time_is_rejected_with_fixed_error() -> None:
    envelope = _envelope()

    with pytest.raises(AiTransferRawError) as error:
        decrypt_ai_transfer_raw_response(
            envelope=envelope,
            expected_metadata=envelope.metadata,
            key_provider=_provider(),
            at=datetime(2026, 9, 17, 12, 30),
        )
    assert error.value.code is AiTransferRawErrorCode.INVALID_INPUT


def test_mutable_plaintext_buffer_is_rejected() -> None:
    body = b"complete-response"

    with pytest.raises(AiTransferRawError) as error:
        encrypt_ai_transfer_raw_response(
            binding=_binding(body),
            raw_response_body=bytearray(body),  # type: ignore[arg-type]
            key_provider=_provider(),
        )
    assert error.value.code is AiTransferRawErrorCode.INVALID_INPUT


def test_deletion_receipt_is_exact_and_only_after_expiry() -> None:
    envelope = _envelope()
    deleted_at = envelope.metadata.expires_at
    receipt = build_ai_transfer_raw_deletion_receipt(
        envelope.metadata,
        wrap_aad_sha256=envelope.wrap_aad_sha256,
        envelope_sha256=envelope.envelope_sha256,
        deletion_receipt_id="deletion-1",
        deleted_by="retention-worker",
        deleted_at=deleted_at,
    )

    assert receipt.reason == "RETENTION_EXPIRED"
    assert receipt.deleted_at == deleted_at
    assert receipt.metadata_sha256 == envelope.metadata.metadata_sha256
    assert receipt.metadata_schema_version == envelope.metadata.schema_version
    assert receipt.body_aad_sha256 == envelope.metadata.body_aad_sha256
    assert receipt.wrap_aad_sha256 == envelope.wrap_aad_sha256
    assert receipt.envelope_sha256 == envelope.envelope_sha256

    with pytest.raises(AiTransferRawError) as error:
        build_ai_transfer_raw_deletion_receipt(
            envelope.metadata,
            wrap_aad_sha256=envelope.wrap_aad_sha256,
            envelope_sha256=envelope.envelope_sha256,
            deletion_receipt_id="deletion-too-early",
            deleted_by="retention-worker",
            deleted_at=deleted_at - timedelta(microseconds=1),
        )
    assert error.value.code is AiTransferRawErrorCode.RETENTION_ACTIVE
