"""Persisted exact AI transfer request/approval stays immutable and fail closed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from procurement.documents.ai_requirements import (
    AiRequirementsTransferManifest,
    prepare_ai_requirements_transfer,
)
from procurement.documents.ai_transfer import (
    AI_TRANSFER_APPROVAL_WINDOW,
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
    build_persisted_ai_transfer_approval,
    build_persisted_ai_transfer_request,
    is_persisted_ai_transfer_authorized,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.domain.provenance import Extractor, Provenance


def _manifest() -> AiRequirementsTransferManifest:
    block = ExtractedBlock(
        text="Мощность не менее 5 кВт",
        provenance=Provenance(
            document_id="doc-1",
            locator="paragraph 1",
            extractor=Extractor.NATIVE_DOCX,
            confidence=1,
        ),
    )
    extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(block,),
        reasons=(),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=len(block.text),
    )
    return prepare_ai_requirements_transfer(
        extraction,
        company_id="company-a",
        source_document_id="doc-1",
        source_sha256="a" * 64,
    )


def _request() -> PersistedAiTransferRequest:
    return build_persisted_ai_transfer_request(
        _manifest(),
        transfer_id="transfer-1",
        prepared_by="preparer-1",
        prepared_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
    )


def test_persisted_transfer_request_reconstructs_exact_manifest_and_digest() -> None:
    request = _request()

    assert request.source_binding == "VERIFIED_PERSISTED_SOURCE"
    assert request.retention == "RAW_RESPONSE_30_DAYS_V1"
    assert request.execution == "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"
    assert request.chunks[0].request_sha256
    assert request.response_capture_max_bytes > 0

    tampered = request.model_dump(mode="python")
    tampered["chunks"] = (request.chunks[0].model_copy(update={"source_block_ids": ("b999999",)}),)
    with pytest.raises(ValidationError):
        PersistedAiTransferRequest.model_validate(tampered)
    with pytest.raises(ValidationError):
        PersistedAiTransferRequest.model_validate(
            request.model_dump(mode="python") | {"api_key": "never"}
        )


def test_approval_binds_independent_request_for_exact_fifteen_minute_window() -> None:
    request = _request()
    approved_at = datetime(2026, 9, 17, 10, 5, tzinfo=UTC)
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=approved_at,
    )

    assert approval.expires_at - approved_at == AI_TRANSFER_APPROVAL_WINDOW
    assert is_persisted_ai_transfer_authorized(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        now=approved_at,
    )
    assert is_persisted_ai_transfer_authorized(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        now=approval.expires_at - timedelta(microseconds=1),
    )
    assert not is_persisted_ai_transfer_authorized(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        now=approval.expires_at,
    )
    with pytest.raises(ValueError, match="independent"):
        build_persisted_ai_transfer_approval(
            request,
            approved_by="preparer-1",
            approved_at=approved_at,
        )
    with pytest.raises(ValueError, match="predate"):
        build_persisted_ai_transfer_approval(
            request,
            approved_by="approver-1",
            approved_at=datetime(2026, 9, 17, 9, 59, tzinfo=UTC),
        )


def test_admission_fails_closed_for_mutation_binding_and_naive_time() -> None:
    request = _request()
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=datetime(2026, 9, 17, 10, 5, tzinfo=UTC),
    )
    forged = approval.model_copy(update={"request_payload_sha256": "b" * 64})

    assert not is_persisted_ai_transfer_authorized(
        request,
        forged,
        company_id="company-a",
        transfer_id="transfer-1",
        now=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
    )
    assert not is_persisted_ai_transfer_authorized(
        request,
        approval,
        company_id="other-company",
        transfer_id="transfer-1",
        now=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="timezone"):
        is_persisted_ai_transfer_authorized(
            request,
            approval,
            company_id="company-a",
            transfer_id="transfer-1",
            now=datetime(2026, 9, 17, 10, 6),
        )


def test_admission_compares_before_approval_as_utc_instant_across_dst_fold() -> None:
    request = _request()
    zone = ZoneInfo("America/New_York")
    approval = PersistedAiTransferApproval(
        company_id=request.company_id,
        transfer_id=request.transfer_id,
        request_payload_sha256=request.payload_sha256,
        approved_by="approver-1",
        approved_at=datetime(2026, 11, 1, 6, 5, tzinfo=UTC).astimezone(zone),
        expires_at=datetime(2026, 11, 1, 6, 20, tzinfo=UTC).astimezone(zone),
    )
    now_before_approval = datetime(2026, 11, 1, 5, 10, tzinfo=UTC).astimezone(zone)

    assert now_before_approval.fold == 0
    assert approval.approved_at.fold == 1
    assert not is_persisted_ai_transfer_authorized(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        now=now_before_approval,
    )


def test_admission_compares_after_expiry_as_utc_instant_across_dst_fold() -> None:
    request = _request()
    zone = ZoneInfo("America/New_York")
    approval = PersistedAiTransferApproval(
        company_id=request.company_id,
        transfer_id=request.transfer_id,
        request_payload_sha256=request.payload_sha256,
        approved_by="approver-1",
        approved_at=datetime(2026, 11, 1, 5, 5, tzinfo=UTC).astimezone(zone),
        expires_at=datetime(2026, 11, 1, 5, 20, tzinfo=UTC).astimezone(zone),
    )
    now_after_expiry = datetime(2026, 11, 1, 6, 10, tzinfo=UTC).astimezone(zone)

    assert approval.expires_at.fold == 0
    assert now_after_expiry.fold == 1
    assert not is_persisted_ai_transfer_authorized(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        now=now_after_expiry,
    )


def test_request_forced_nested_revalidation_rejects_rehashed_forged_chunk() -> None:
    request = _request()
    forged_chunk = request.chunks[0].model_copy(update={"request_sha256": "b" * 64})
    payload = request.model_dump(mode="python")
    payload["chunks"] = (forged_chunk,)
    payload["payload_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )

    with pytest.raises(ValidationError, match="request digest"):
        PersistedAiTransferRequest.model_validate(payload)


def test_admission_rejects_predated_forged_approval() -> None:
    request = _request()
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=datetime(2026, 9, 17, 10, 5, tzinfo=UTC),
    )
    predating = approval.model_copy(
        update={
            "approved_at": datetime(2026, 9, 17, 9, 45, tzinfo=UTC),
            "expires_at": datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
        }
    )

    assert not is_persisted_ai_transfer_authorized(
        request,
        predating,
        company_id="company-a",
        transfer_id="transfer-1",
        now=datetime(2026, 9, 17, 9, 50, tzinfo=UTC),
    )


def test_approval_rejects_nonexact_expiry_and_extra_fields() -> None:
    request = _request()
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=datetime(2026, 9, 17, 10, 5, tzinfo=UTC),
    )
    payload = approval.model_dump(mode="python")
    payload["expires_at"] = approval.expires_at + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="exactly fifteen"):
        PersistedAiTransferApproval.model_validate(payload)
    with pytest.raises(ValidationError):
        PersistedAiTransferApproval.model_validate(
            approval.model_dump(mode="python") | {"send_allowed": True}
        )
