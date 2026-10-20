"""Server-managed transfer materialization stays exact, typed, and raw-free."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from procurement.documents.ai_requirement_review import (
    AiRequirementCandidateDecision,
    CandidateDisposition,
    CandidateKind,
    build_ai_requirement_review_decision,
    build_ai_requirement_transfer_batch_run_snapshot,
    build_ai_requirement_transfer_run_snapshot,
)
from procurement.documents.ai_requirements import prepare_ai_requirements_transfer
from procurement.documents.ai_transfer import (
    build_persisted_ai_transfer_approval,
    build_persisted_ai_transfer_request,
)
from procurement.documents.ai_transfer_execution import (
    build_ai_transfer_dispatch_claim,
    build_ai_transfer_dispatch_receipt,
    build_ai_transfer_execution_admission,
)
from procurement.documents.ai_transfer_raw import (
    AiTransferRawBinding,
    encrypt_ai_transfer_raw_response,
)
from procurement.documents.ai_transfer_requirement_result import (
    AiTransferRequirementBatchResult,
    AiTransferRequirementResult,
    AiTransferRequirementResultError,
    AiTransferRequirementResultErrorCode,
    build_ai_transfer_requirement_batch_result,
    build_ai_transfer_requirement_materialization,
    build_ai_transfer_requirement_result,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.documents.facts import CompletenessStatus
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 17, 10, 10, tzinfo=UTC)


class _Kek:
    def active_key_id(self, *, company_id: str) -> str:
        return f"test/{company_id}/v1"

    def wrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        dek: bytes,
        aad: bytes,
    ) -> bytes:
        del company_id, key_id
        return AESGCM(b"k" * 32).encrypt(nonce, dek, aad)

    def unwrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        wrapped_dek: bytes,
        aad: bytes,
    ) -> bytes:
        del company_id, key_id
        return AESGCM(b"k" * 32).decrypt(nonce, wrapped_dek, aad)


def _extraction() -> ExtractionResult:
    rows = (
        ("Насос 28.13.14.110 28.13.14.110-00000001 мощность 5 кВт", "table 1 row 2 cell 1"),
        ("шт", "table 1 row 2 cell 2"),
        ("2,00", "table 1 row 2 cell 3"),
    )
    blocks = tuple(
        ExtractedBlock(
            text=text,
            provenance=Provenance(
                document_id="doc-1",
                locator=locator,
                extractor=Extractor.NATIVE_DOCX,
                confidence=1,
            ),
        )
        for text, locator in rows
    )
    return ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=blocks,
        reasons=(),
        source_units_total=3,
        source_units_extracted=3,
        characters_extracted=sum(len(block.text) for block in blocks),
    )


def _wire(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {
        "item_name": {"value": "Насос", "source_block_ids": ["b000001"]},
        "okpd2_codes": [{"value": "28.13.14.110", "source_block_ids": ["b000001"]}],
        "ktru_codes": [{"value": "28.13.14.110-00000001", "source_block_ids": ["b000001"]}],
        "unit": {"value": "шт", "source_block_ids": ["b000002"]},
        "quantity": {"value": "2,00", "source_block_ids": ["b000003"]},
        "uncertainty": None,
    }
    item.update(changes)
    return {
        "items": [item],
        "requirements": [
            {
                "item_name": "Насос",
                "property": "power",
                "operator": ">=",
                "value": "5",
                "unit": "кВт",
                "mandatory": True,
                "source_block_ids": ["b000001"],
                "uncertainty": None,
            }
        ],
        "unresolved_block_ids": [],
        "document_notes": [],
    }


def _fixture(
    wire: dict[str, object] | None = None,
    *,
    max_chunk_characters: int = 24_000,
    wire_content: str | None = None,
) -> tuple[object, ...]:
    extraction = _extraction()
    if max_chunk_characters < 24_000:
        padded_blocks = tuple(
            block.model_copy(
                update={
                    "text": block.text + (" x" * 300),
                    "provenance": block.provenance.model_copy(
                        update={"locator": f"paragraph {index}"}
                    ),
                }
            )
            for index, block in enumerate(extraction.blocks, start=1)
        )
        extraction = extraction.model_copy(
            update={
                "blocks": padded_blocks,
                "characters_extracted": sum(len(block.text) for block in padded_blocks),
            }
        )
    manifest = prepare_ai_requirements_transfer(
        extraction,
        company_id="company-a",
        source_document_id="doc-1",
        source_sha256="a" * 64,
        max_chunk_characters=max_chunk_characters,
    )
    request = build_persisted_ai_transfer_request(
        manifest,
        transfer_id="transfer-1",
        prepared_by="preparer-1",
        prepared_at=NOW - timedelta(minutes=10),
    )
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=NOW - timedelta(minutes=8),
    )
    admission = build_ai_transfer_execution_admission(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        execution_id="execution-1",
        admitted_by="preparer-1",
        admitted_at=NOW - timedelta(minutes=7),
        existing_admission=None,
    )
    claim = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-1",
        claimed_by="worker-1",
        claimed_at=NOW - timedelta(minutes=6),
        existing_claims=(),
        existing_receipts=(),
    )
    content = wire_content or json.dumps(wire or _wire(), ensure_ascii=False, separators=(",", ":"))
    raw = json.dumps(
        {
            "id": "generation-1",
            "model": request.model_profile.model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    receipt = build_ai_transfer_dispatch_receipt(
        claim,
        receipt_id="receipt-1",
        outcome="SUCCESS",
        reason="VALIDATED_RESPONSE",
        attempted=True,
        request_sha256=claim.request_sha256,
        http_status=200,
        capture_complete=True,
        captured_byte_count=len(raw),
        response_body_sha256=hashlib.sha256(raw).hexdigest(),
        provider_response_id="generation-1",
        provider_model=request.model_profile.model,
        assistant_content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        assistant_content_byte_count=len(content.encode()),
        started_at=claim.claimed_at,
        finished_at=claim.claimed_at + timedelta(seconds=1),
        recorded_by="worker-1",
        recorded_at=claim.claimed_at + timedelta(seconds=1),
    )
    encrypted = encrypt_ai_transfer_raw_response(
        binding=AiTransferRawBinding(
            company_id="company-a",
            raw_response_id="raw-1",
            transfer_id="transfer-1",
            execution_id="execution-1",
            ordinal=1,
            claim_id="claim-1",
            chunk_id="chunk-0001",
            claim_payload_sha256=claim.payload_sha256,
            receipt_id="receipt-1",
            receipt_payload_sha256=receipt.payload_sha256,
            request_sha256=claim.request_sha256,
            response_body_sha256=hashlib.sha256(raw).hexdigest(),
            response_byte_count=len(raw),
            received_at=receipt.finished_at,
        ),
        raw_response_body=raw,
        key_provider=_Kek(),
    )
    return extraction, request, claim, receipt, encrypted.metadata, raw


def _result(parts: tuple[object, ...]):
    extraction, request, claim, receipt, metadata, raw = parts
    return build_ai_transfer_requirement_result(
        request,
        claim,
        receipt,
        metadata,
        raw,
        extraction,
        result_id="result-1",
        prepared_by="preparer-1",
        materialized_by="worker-2",
        materialized_at=NOW,
    )


def _multi_chunk_results():
    extraction, request, *_ = _fixture(max_chunk_characters=1_000)
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=NOW - timedelta(minutes=8),
    )
    admission = build_ai_transfer_execution_admission(
        request,
        approval,
        company_id=request.company_id,
        transfer_id=request.transfer_id,
        execution_id="execution-multi",
        admitted_by=request.prepared_by,
        admitted_at=NOW - timedelta(minutes=7),
        existing_admission=None,
    )
    claims = []
    receipts = []
    results = []
    for ordinal, chunk in enumerate(request.chunks, start=1):
        claimed_at = NOW - timedelta(minutes=6) + timedelta(seconds=ordinal)
        claim = build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id=f"claim-multi-{ordinal}",
            claimed_by="worker-1",
            claimed_at=claimed_at,
            existing_claims=tuple(claims),
            existing_receipts=tuple(receipts),
        )
        content = json.dumps(
            {
                "items": [],
                "requirements": [],
                "unresolved_block_ids": list(chunk.source_block_ids),
                "document_notes": [],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raw = json.dumps(
            {
                "id": f"generation-multi-{ordinal}",
                "model": request.model_profile.model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        receipt = build_ai_transfer_dispatch_receipt(
            claim,
            receipt_id=f"receipt-multi-{ordinal}",
            outcome="SUCCESS",
            reason="VALIDATED_RESPONSE",
            attempted=True,
            request_sha256=claim.request_sha256,
            http_status=200,
            capture_complete=True,
            captured_byte_count=len(raw),
            response_body_sha256=hashlib.sha256(raw).hexdigest(),
            provider_response_id=f"generation-multi-{ordinal}",
            provider_model=request.model_profile.model,
            assistant_content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            assistant_content_byte_count=len(content.encode()),
            started_at=claimed_at,
            finished_at=claimed_at + timedelta(milliseconds=100),
            recorded_by=claim.claimed_by,
            recorded_at=claimed_at + timedelta(milliseconds=100),
        )
        encrypted = encrypt_ai_transfer_raw_response(
            binding=AiTransferRawBinding(
                company_id=request.company_id,
                raw_response_id=f"raw-multi-{ordinal}",
                transfer_id=request.transfer_id,
                execution_id=admission.execution_id,
                ordinal=ordinal,
                claim_id=claim.claim_id,
                chunk_id=chunk.chunk_id,
                claim_payload_sha256=claim.payload_sha256,
                receipt_id=receipt.receipt_id,
                receipt_payload_sha256=receipt.payload_sha256,
                request_sha256=claim.request_sha256,
                response_body_sha256=hashlib.sha256(raw).hexdigest(),
                response_byte_count=len(raw),
                received_at=receipt.finished_at,
            ),
            raw_response_body=raw,
            key_provider=_Kek(),
        )
        result = build_ai_transfer_requirement_result(
            request,
            claim,
            receipt,
            encrypted.metadata,
            raw,
            extraction,
            result_id=f"result-multi-{ordinal}",
            prepared_by=request.prepared_by,
            materialized_by="materializer-1",
            materialized_at=NOW + timedelta(seconds=ordinal),
        )
        claims.append(claim)
        receipts.append(receipt)
        results.append(result)
    return extraction, request, tuple(results)


def test_happy_path_is_raw_free_unknown_and_review_covers_every_candidate() -> None:
    parts = _fixture()
    result = _result(parts)
    snapshot = build_ai_requirement_transfer_run_snapshot(
        run_id="run-1", extraction=parts[0], result=result
    )
    serialized = snapshot.model_dump_json()

    assert result.completeness_status is CompletenessStatus.UNKNOWN
    assert "response_content" not in serialized
    assert "ciphertext" not in serialized
    assert "wrapped_dek" not in serialized
    assert "generation-1" in serialized  # identifier is evidence, not raw content
    decisions = (
        AiRequirementCandidateDecision(
            candidate_kind=CandidateKind.REQUIREMENT,
            candidate_id=result.candidates[0].candidate_id,
            disposition=CandidateDisposition.ACCEPTED,
            reason="checked",
        ),
        AiRequirementCandidateDecision(
            candidate_kind=CandidateKind.PROCUREMENT_ITEM,
            candidate_id=result.item_candidates[0].candidate_id,
            disposition=CandidateDisposition.ACCEPTED,
            reason="checked",
        ),
    )
    with pytest.raises(ValueError, match="every exact candidate"):
        build_ai_requirement_review_decision(
            snapshot,
            evidence_sha256=snapshot.evidence_sha256,
            candidate_decisions=decisions[:-1],
            reviewed_by="reviewer-1",
            reviewed_at=NOW,
        )
    with pytest.raises(ValueError, match="own run"):
        build_ai_requirement_review_decision(
            snapshot,
            evidence_sha256=snapshot.evidence_sha256,
            candidate_decisions=decisions,
            reviewed_by="preparer-1",
            reviewed_at=NOW,
        )
    decision = build_ai_requirement_review_decision(
        snapshot,
        evidence_sha256=snapshot.evidence_sha256,
        candidate_decisions=decisions,
        reviewed_by="worker-2",  # materializer is not the original submitter
        reviewed_at=NOW,
    )
    assert len(decision.candidate_decisions) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"item_name": {"value": "Компрессор", "source_block_ids": ["b000001"]}},
        {"okpd2_codes": [{"value": "29.99.99.999", "source_block_ids": ["b000001"]}]},
        {"quantity": {"value": "3,00", "source_block_ids": ["b000003"]}},
    ],
)
def test_forged_literal_code_and_quantity_are_typed_semantic_rejections(
    changes: dict[str, object],
) -> None:
    with pytest.raises(AiTransferRequirementResultError) as caught:
        _result(_fixture(_wire(**changes)))
    assert caught.value.code is AiTransferRequirementResultErrorCode.INVALID_WIRE_RESPONSE


@pytest.mark.parametrize(
    ("position", "field", "replacement"),
    [
        (1, "company_id", "other-company"),
        (1, "payload_sha256", "0" * 64),
        (2, "request_sha256", "0" * 64),
        (3, "provider_model", "other/model"),
        (3, "assistant_content_sha256", "0" * 64),
        (4, "response_body_sha256", "0" * 64),
        (4, "receipt_payload_sha256", "0" * 64),
    ],
)
def test_cross_binding_digest_model_and_tenant_mismatch_is_rejected(
    position: int,
    field: str,
    replacement: object,
) -> None:
    parts = list(_fixture())
    original = parts[position]
    parts[position] = original.model_copy(update={field: replacement})

    with pytest.raises(AiTransferRequirementResultError) as caught:
        _result(tuple(parts))
    assert caught.value.code is AiTransferRequirementResultErrorCode.INVALID_BINDING


def test_source_raw_and_out_of_chunk_evidence_are_rejected() -> None:
    parts = list(_fixture())
    changed = _extraction().model_copy(
        update={
            "blocks": (
                _extraction().blocks[0].model_copy(update={"text": "changed"}),
                *_extraction().blocks[1:],
            )
        }
    )
    parts[0] = changed
    with pytest.raises(AiTransferRequirementResultError) as source_error:
        _result(tuple(parts))
    assert source_error.value.code is AiTransferRequirementResultErrorCode.SOURCE_MISMATCH

    raw_parts = list(_fixture())
    raw_parts[5] = b"tampered"
    with pytest.raises(AiTransferRequirementResultError) as raw_error:
        _result(tuple(raw_parts))
    assert raw_error.value.code is AiTransferRequirementResultErrorCode.INVALID_RAW_RESPONSE

    multi = _fixture(max_chunk_characters=1_000)
    assert len(multi[1].chunks) > 1
    with pytest.raises(AiTransferRequirementResultError) as multi_error:
        _result(multi)
    assert multi_error.value.code is AiTransferRequirementResultErrorCode.INVALID_WIRE_RESPONSE


def test_complete_multi_chunk_results_form_one_raw_free_unknown_batch() -> None:
    extraction, request, results = _multi_chunk_results()
    batch = build_ai_transfer_requirement_batch_result(
        request,
        results,
        batch_result_id="batch-result-1",
        aggregated_by="aggregator-1",
        aggregated_at=NOW + timedelta(minutes=1),
    )

    assert tuple(result.ordinal for result in batch.chunk_results) == tuple(
        range(1, len(request.chunks) + 1)
    )
    assert batch.source_block_ids == request.source_block_ids
    assert batch.unresolved_block_ids == request.source_block_ids
    assert batch.completeness_status is CompletenessStatus.UNKNOWN
    serialized = batch.model_dump_json()
    assert "response_content" not in serialized
    assert "ciphertext" not in serialized
    assert "wrapped_dek" not in serialized

    snapshot = build_ai_requirement_transfer_batch_run_snapshot(
        run_id="batch-run-1",
        extraction=extraction,
        result=batch,
    )
    assert snapshot.completeness_status is CompletenessStatus.UNKNOWN
    assert snapshot.result == batch
    assert "response_content" not in snapshot.model_dump_json()


def test_multi_chunk_batch_rejects_missing_reordered_and_forged_projection() -> None:
    _, request, results = _multi_chunk_results()
    for invalid in (results[:-1], tuple(reversed(results))):
        with pytest.raises(AiTransferRequirementResultError) as caught:
            build_ai_transfer_requirement_batch_result(
                request,
                invalid,
                batch_result_id="batch-invalid",
                aggregated_by="aggregator-1",
                aggregated_at=NOW + timedelta(minutes=1),
            )
        assert caught.value.code is AiTransferRequirementResultErrorCode.INVALID_BINDING

    batch = build_ai_transfer_requirement_batch_result(
        request,
        results,
        batch_result_id="batch-result-1",
        aggregated_by="aggregator-1",
        aggregated_at=NOW + timedelta(minutes=1),
    )
    forged_fields = batch.model_dump(mode="python", exclude={"payload_sha256"})
    forged_fields["unresolved_block_ids"] = ()
    with pytest.raises(ValueError, match="projection differs"):
        AiTransferRequirementBatchResult.model_validate(
            {
                **forged_fields,
                "payload_sha256": canonical_json_sha256(
                    {
                        "schema_version": "ai-transfer-requirement-batch-v1",
                        **forged_fields,
                    }
                ),
            },
            strict=True,
        )


def test_append_only_materialization_receipt_has_exact_terminal_shape() -> None:
    parts = _fixture()
    result = _result(parts)
    snapshot = build_ai_requirement_transfer_run_snapshot(
        run_id="run-1", extraction=parts[0], result=result
    )
    receipt = build_ai_transfer_requirement_materialization(
        parts[1],
        parts[2],
        parts[3],
        parts[4],
        materialization_id="materialization-1",
        status="MATERIALIZED",
        reason="MATERIALIZED",
        result=result,
        run_id=snapshot.run_id,
        run_evidence_sha256=snapshot.evidence_sha256,
        materialized_by="worker-2",
        materialized_at=NOW,
    )
    assert receipt.result_payload_sha256 == result.payload_sha256
    assert receipt.run_evidence_sha256 == snapshot.evidence_sha256

    rejected_parts = _fixture(max_chunk_characters=1_000)
    rejected = build_ai_transfer_requirement_materialization(
        rejected_parts[1],
        rejected_parts[2],
        rejected_parts[3],
        rejected_parts[4],
        materialization_id="materialization-2",
        status="REJECTED",
        reason="UNSUPPORTED_MULTI_CHUNK",
        result=None,
        run_id=None,
        run_evidence_sha256=None,
        materialized_by="worker-2",
        materialized_at=NOW,
    )
    assert rejected.result_id is None
    assert rejected.run_evidence_sha256 is None


def test_materialization_rejects_hash_valid_result_with_forged_receipt_digest() -> None:
    parts = _fixture()
    result = _result(parts)
    forged_fields = result.model_dump(mode="python", exclude={"payload_sha256"})
    forged_fields["receipt_payload_sha256"] = "0" * 64
    forged = AiTransferRequirementResult.model_validate(
        {
            **forged_fields,
            "payload_sha256": canonical_json_sha256(forged_fields),
        },
        strict=True,
    )

    with pytest.raises(AiTransferRequirementResultError) as caught:
        build_ai_transfer_requirement_materialization(
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            materialization_id="materialization-forged",
            status="MATERIALIZED",
            reason="MATERIALIZED",
            result=forged,
            run_id="run-forged",
            run_evidence_sha256="f" * 64,
            materialized_by="worker-2",
            materialized_at=NOW,
        )
    assert caught.value.code is AiTransferRequirementResultErrorCode.INVALID_BINDING


def test_result_rejects_materialization_before_receipt_and_raw_capture() -> None:
    extraction, request, claim, receipt, metadata, raw = _fixture()

    with pytest.raises(AiTransferRequirementResultError) as caught:
        build_ai_transfer_requirement_result(
            request,
            claim,
            receipt,
            metadata,
            raw,
            extraction,
            result_id="result-backdated",
            prepared_by="preparer-1",
            materialized_by="worker-2",
            materialized_at=receipt.recorded_at - timedelta(seconds=1),
        )
    assert caught.value.code is AiTransferRequirementResultErrorCode.INVALID_BINDING

    with pytest.raises(AiTransferRequirementResultError) as expiry_caught:
        build_ai_transfer_requirement_result(
            request,
            claim,
            receipt,
            metadata,
            raw,
            extraction,
            result_id="result-at-expiry",
            prepared_by="preparer-1",
            materialized_by="worker-2",
            materialized_at=metadata.expires_at,
        )
    assert expiry_caught.value.code is AiTransferRequirementResultErrorCode.INVALID_BINDING


def test_deeply_nested_provider_content_is_a_terminal_semantic_rejection() -> None:
    nested = "[" * 200_000 + "0" + "]" * 200_000

    with pytest.raises(AiTransferRequirementResultError) as caught:
        _result(_fixture(wire_content=nested))
    assert caught.value.code is AiTransferRequirementResultErrorCode.INVALID_WIRE_RESPONSE
