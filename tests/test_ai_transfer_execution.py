"""Durable AI transfer execution admission stays ordered and fail closed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from procurement.documents.ai_requirements import prepare_ai_requirements_transfer
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
    build_persisted_ai_transfer_approval,
    build_persisted_ai_transfer_request,
)
from procurement.documents.ai_transfer_execution import (
    AiTransferDispatchClaim,
    AiTransferDispatchOutcome,
    AiTransferDispatchReceipt,
    AiTransferExecutionAdmission,
    build_ai_transfer_dispatch_claim,
    build_ai_transfer_dispatch_receipt,
    build_ai_transfer_execution_admission,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.domain.provenance import Extractor, Provenance


def _request() -> PersistedAiTransferRequest:
    blocks = tuple(
        ExtractedBlock(
            text=f"Требование {index}: " + ("x" * 600),
            provenance=Provenance(
                document_id="doc-1",
                locator=f"paragraph {index}",
                extractor=Extractor.NATIVE_DOCX,
                confidence=1,
            ),
        )
        for index in (1, 2)
    )
    extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=blocks,
        reasons=(),
        source_units_total=2,
        source_units_extracted=2,
        characters_extracted=sum(len(block.text) for block in blocks),
    )
    manifest = prepare_ai_requirements_transfer(
        extraction,
        company_id="company-a",
        source_document_id="doc-1",
        source_sha256="a" * 64,
        max_chunk_characters=1_000,
    )
    assert len(manifest.chunks) == 2
    return build_persisted_ai_transfer_request(
        manifest,
        transfer_id="transfer-1",
        prepared_by="preparer-1",
        prepared_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
    )


def _execution() -> tuple[
    PersistedAiTransferRequest,
    PersistedAiTransferApproval,
    AiTransferExecutionAdmission,
]:
    request = _request()
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=datetime(2026, 9, 17, 10, 5, tzinfo=UTC),
    )
    admission = build_ai_transfer_execution_admission(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        execution_id="execution-1",
        admitted_by="preparer-1",
        admitted_at=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
        existing_admission=None,
    )
    return request, approval, admission


def _first_claim(
    request: PersistedAiTransferRequest,
    approval: PersistedAiTransferApproval,
    admission: AiTransferExecutionAdmission,
) -> AiTransferDispatchClaim:
    return build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-1",
        claimed_by="worker-1",
        claimed_at=datetime(2026, 9, 17, 10, 7, tzinfo=UTC),
        existing_claims=(),
        existing_receipts=(),
    )


def _receipt(
    claim: AiTransferDispatchClaim,
    *,
    outcome: AiTransferDispatchOutcome = "SUCCESS",
    recorded_at: datetime,
) -> AiTransferDispatchReceipt:
    common: dict[str, object] = {
        "receipt_id": f"receipt-{claim.claim_id}",
        "outcome": outcome,
        "attempted": True,
        "request_sha256": claim.request_sha256,
        "recorded_by": claim.claimed_by,
        "recorded_at": recorded_at,
        "started_at": claim.claimed_at,
        "finished_at": claim.claimed_at + timedelta(seconds=1),
    }
    if outcome == "SUCCESS":
        common.update(
            reason="VALIDATED_RESPONSE",
            http_status=200,
            capture_complete=True,
            captured_byte_count=100,
            response_body_sha256="b" * 64,
            provider_response_id="response-1",
            provider_model="google/gemma-4-31b-it:free",
            assistant_content_sha256="c" * 64,
            assistant_content_byte_count=10,
        )
    elif outcome == "FAILED":
        common.update(
            reason="HTTP_STATUS_REJECTED",
            http_status=500,
            capture_complete=True,
            captured_byte_count=2,
            response_body_sha256="d" * 64,
            provider_response_id=None,
            provider_model=None,
            assistant_content_sha256=None,
            assistant_content_byte_count=None,
        )
    else:
        common.update(
            reason="TIMEOUT",
            http_status=None,
            capture_complete=False,
            captured_byte_count=0,
            response_body_sha256=None,
            provider_response_id=None,
            provider_model=None,
            assistant_content_sha256=None,
            assistant_content_byte_count=None,
        )
    return build_ai_transfer_dispatch_receipt(claim, **common)  # type: ignore[arg-type]


def test_admission_atomically_consumes_one_exact_approval_and_batch() -> None:
    request, approval, admission = _execution()

    assert admission.status == "ADMITTED"
    assert admission.execution_policy == "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"
    assert admission.chunk_count == 2
    assert admission.approved_by == approval.approved_by
    assert admission.approved_at == approval.approved_at
    assert admission.approval_expires_at == approval.expires_at

    with pytest.raises(ValueError, match="already been admitted"):
        build_ai_transfer_execution_admission(
            request,
            approval,
            company_id="company-a",
            transfer_id="transfer-1",
            execution_id="execution-2",
            admitted_by="operator-2",
            admitted_at=datetime(2026, 9, 17, 10, 7, tzinfo=UTC),
            existing_admission=admission,
        )


def test_admission_rejects_wrong_tenant_digest_and_forged_nested_models() -> None:
    request, approval, admission = _execution()
    with pytest.raises(ValueError, match="not valid"):
        build_ai_transfer_execution_admission(
            request,
            approval,
            company_id="company-b",
            transfer_id="transfer-1",
            execution_id="execution-x",
            admitted_by="operator-1",
            admitted_at=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
            existing_admission=None,
        )

    forged_approval = approval.model_copy(update={"request_payload_sha256": "b" * 64})
    with pytest.raises(ValueError, match="not valid"):
        build_ai_transfer_execution_admission(
            request,
            forged_approval,
            company_id="company-a",
            transfer_id="transfer-1",
            execution_id="execution-x",
            admitted_by="operator-1",
            admitted_at=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
            existing_admission=None,
        )

    forged_admission = admission.model_copy(update={"execution_id": "execution-forged"})
    with pytest.raises(ValidationError, match="digest"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            forged_admission,
            claim_id="claim-x",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 7, tzinfo=UTC),
            existing_claims=(),
            existing_receipts=(),
        )

    rehashed_payload = admission.model_dump(mode="python")
    rehashed_payload["approved_by"] = "other-approver"
    rehashed_payload["payload_sha256"] = canonical_json_sha256(
        {key: value for key, value in rehashed_payload.items() if key != "payload_sha256"}
    )
    rehashed_forgery = AiTransferExecutionAdmission.model_validate(rehashed_payload)
    with pytest.raises(ValueError, match="exact request and approval"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            rehashed_forgery,
            claim_id="claim-rehashed-approval",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 7, tzinfo=UTC),
            existing_claims=(),
            existing_receipts=(),
        )

    with pytest.raises(ValueError, match="request preparer"):
        build_ai_transfer_execution_admission(
            request,
            approval,
            company_id="company-a",
            transfer_id="transfer-1",
            execution_id="execution-wrong-actor",
            admitted_by="other-operator",
            admitted_at=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
            existing_admission=None,
        )


def test_first_claim_is_one_permanent_attempt_with_unknown_delivery() -> None:
    request, approval, admission = _execution()
    claim = _first_claim(request, approval, admission)

    assert claim.ordinal == 1
    assert claim.chunk_id == request.chunks[0].chunk_id
    assert claim.request_sha256 == request.chunks[0].request_sha256
    assert claim.admission_payload_sha256 == admission.payload_sha256
    assert claim.attempt == 1
    assert claim.claim_status == "PERMANENTLY_CLAIMED"
    assert claim.delivery_state == "DELIVERY_UNKNOWN"


def test_next_claim_requires_exact_terminal_success_and_is_strictly_ordered() -> None:
    request, approval, admission = _execution()
    first = _first_claim(request, approval, admission)
    receipt = _receipt(first, recorded_at=datetime(2026, 9, 17, 10, 8, tzinfo=UTC))
    second = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-2",
        claimed_by="worker-1",
        claimed_at=datetime(2026, 9, 17, 10, 9, tzinfo=UTC),
        existing_claims=(first,),
        existing_receipts=(receipt,),
    )

    assert second.ordinal == 2
    assert second.chunk_id == request.chunks[1].chunk_id
    with pytest.raises(ValueError, match="already have permanent claims"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-3",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 10, tzinfo=UTC),
            existing_claims=(first, second),
            existing_receipts=(
                receipt,
                _receipt(second, recorded_at=datetime(2026, 9, 17, 10, 9, 30, tzinfo=UTC)),
            ),
        )


@pytest.mark.parametrize("outcome", ["FAILED", "DELIVERY_UNKNOWN"])
def test_failure_or_unknown_permanently_stops_batch(outcome: str) -> None:
    request, approval, admission = _execution()
    first = _first_claim(request, approval, admission)
    receipt = _receipt(
        first,
        outcome=outcome,  # type: ignore[arg-type]
        recorded_at=datetime(2026, 9, 17, 10, 8, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="permanently stops"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-2",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 9, tzinfo=UTC),
            existing_claims=(first,),
            existing_receipts=(receipt,),
        )


def test_unreceipted_claim_blocks_retry_and_next_chunk() -> None:
    request, approval, admission = _execution()
    first = _first_claim(request, approval, admission)

    with pytest.raises(ValueError, match="exactly one terminal receipt"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-retry-or-next",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 8, tzinfo=UTC),
            existing_claims=(first,),
            existing_receipts=(),
        )


def test_next_claim_cannot_reuse_id_or_predate_prior_success_receipt() -> None:
    request, approval, admission = _execution()
    first = _first_claim(request, approval, admission)
    receipt = _receipt(first, recorded_at=datetime(2026, 9, 17, 10, 9, tzinfo=UTC))
    with pytest.raises(ValueError, match="predate"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-2",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 8, tzinfo=UTC),
            existing_claims=(first,),
            existing_receipts=(receipt,),
        )
    with pytest.raises(ValueError, match="already been used"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-1",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 10, tzinfo=UTC),
            existing_claims=(first,),
            existing_receipts=(receipt,),
        )


def test_expiry_between_chunks_prevents_new_claim_but_not_receipt() -> None:
    request, approval, admission = _execution()
    first = _first_claim(request, approval, admission)
    receipt = _receipt(first, recorded_at=approval.expires_at + timedelta(seconds=1))
    assert receipt.outcome == "SUCCESS"

    with pytest.raises(ValueError, match="expired"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-2",
            claimed_by="worker-1",
            claimed_at=approval.expires_at,
            existing_claims=(first,),
            existing_receipts=(receipt,),
        )


def test_claim_history_revalidates_model_copy_and_exact_receipt_binding() -> None:
    request, approval, admission = _execution()
    first = _first_claim(request, approval, admission)
    forged_claim = first.model_copy(update={"request_sha256": "b" * 64})
    with pytest.raises(ValidationError, match="digest"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-2",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 9, tzinfo=UTC),
            existing_claims=(forged_claim,),
            existing_receipts=(),
        )

    receipt = _receipt(first, recorded_at=datetime(2026, 9, 17, 10, 8, tzinfo=UTC))
    forged_receipt = receipt.model_copy(update={"claim_id": "other"})
    with pytest.raises(ValidationError, match="digest"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-2",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 9, 17, 10, 9, tzinfo=UTC),
            existing_claims=(first,),
            existing_receipts=(forged_receipt,),
        )


def test_strict_integer_and_outcome_contract_rejects_bool_partial_and_extras() -> None:
    request, approval, admission = _execution()
    claim = _first_claim(request, approval, admission)

    claim_payload = claim.model_dump(mode="python")
    claim_payload["ordinal"] = True
    claim_payload["payload_sha256"] = canonical_json_sha256(
        {key: value for key, value in claim_payload.items() if key != "payload_sha256"}
    )
    with pytest.raises(ValidationError):
        AiTransferDispatchClaim.model_validate(claim_payload)

    admission_payload = admission.model_dump(mode="python")
    admission_payload["chunk_count"] = True
    admission_payload["payload_sha256"] = canonical_json_sha256(
        {key: value for key, value in admission_payload.items() if key != "payload_sha256"}
    )
    with pytest.raises(ValidationError):
        AiTransferExecutionAdmission.model_validate(admission_payload)

    admission_payload["chunk_count"] = 10_000
    admission_payload["payload_sha256"] = canonical_json_sha256(
        {key: value for key, value in admission_payload.items() if key != "payload_sha256"}
    )
    with pytest.raises(ValidationError):
        AiTransferExecutionAdmission.model_validate(admission_payload)

    with pytest.raises(ValidationError):
        AiTransferDispatchReceipt.model_validate(
            _receipt(
                claim,
                recorded_at=datetime(2026, 9, 17, 10, 8, tzinfo=UTC),
            ).model_dump(mode="python")
            | {"outcome": "PARTIAL_SUCCESS", "retry_allowed": True}
        )


def test_receipt_cannot_predate_claim() -> None:
    request, approval, admission = _execution()
    claim = _first_claim(request, approval, admission)
    with pytest.raises(ValueError, match="predate"):
        _receipt(claim, recorded_at=claim.claimed_at - timedelta(microseconds=1))


def test_transport_cannot_start_before_durable_claim() -> None:
    request, approval, admission = _execution()
    claim = _first_claim(request, approval, admission)
    with pytest.raises(ValueError, match="durable claim"):
        build_ai_transfer_dispatch_receipt(
            claim,
            receipt_id="receipt-predated-transport",
            outcome="FAILED",
            reason="HTTP_STATUS_REJECTED",
            attempted=True,
            request_sha256=claim.request_sha256,
            http_status=500,
            capture_complete=True,
            captured_byte_count=2,
            response_body_sha256="d" * 64,
            provider_response_id=None,
            provider_model=None,
            assistant_content_sha256=None,
            assistant_content_byte_count=None,
            started_at=claim.claimed_at - timedelta(microseconds=1),
            finished_at=claim.claimed_at,
            recorded_by=claim.claimed_by,
            recorded_at=claim.claimed_at + timedelta(seconds=1),
        )


def test_receipt_rejects_forged_terminal_reason_evidence() -> None:
    request, approval, admission = _execution()
    claim = _first_claim(request, approval, admission)
    recorded_at = datetime(2026, 9, 17, 10, 8, tzinfo=UTC)

    with pytest.raises(ValidationError, match="HTTP status failure"):
        build_ai_transfer_dispatch_receipt(
            claim,
            receipt_id="receipt-forged-http",
            outcome="FAILED",
            reason="HTTP_STATUS_REJECTED",
            attempted=True,
            request_sha256=claim.request_sha256,
            http_status=200,
            capture_complete=True,
            captured_byte_count=2,
            response_body_sha256="d" * 64,
            provider_response_id=None,
            provider_model=None,
            assistant_content_sha256=None,
            assistant_content_byte_count=None,
            started_at=claim.claimed_at,
            finished_at=claim.claimed_at + timedelta(seconds=1),
            recorded_by=claim.claimed_by,
            recorded_at=recorded_at,
        )

    rejected_201 = build_ai_transfer_dispatch_receipt(
        claim,
        receipt_id="receipt-http-201",
        outcome="FAILED",
        reason="HTTP_STATUS_REJECTED",
        attempted=True,
        request_sha256=claim.request_sha256,
        http_status=201,
        capture_complete=True,
        captured_byte_count=2,
        response_body_sha256="d" * 64,
        provider_response_id=None,
        provider_model=None,
        assistant_content_sha256=None,
        assistant_content_byte_count=None,
        started_at=claim.claimed_at,
        finished_at=claim.claimed_at + timedelta(seconds=1),
        recorded_by=claim.claimed_by,
        recorded_at=recorded_at,
    )
    assert rejected_201.http_status == 201

    with pytest.raises(ValidationError, match="appear together"):
        build_ai_transfer_dispatch_receipt(
            claim,
            receipt_id="receipt-forged-provider-pair",
            outcome="FAILED",
            reason="MODEL_MISMATCH",
            attempted=True,
            request_sha256=claim.request_sha256,
            http_status=200,
            capture_complete=True,
            captured_byte_count=100,
            response_body_sha256="d" * 64,
            provider_response_id="response-1",
            provider_model=None,
            assistant_content_sha256=None,
            assistant_content_byte_count=None,
            started_at=claim.claimed_at,
            finished_at=claim.claimed_at + timedelta(seconds=1),
            recorded_by=claim.claimed_by,
            recorded_at=recorded_at,
        )


def test_admission_and_claim_compare_dst_folds_as_utc_instants() -> None:
    request = _request()
    zone = ZoneInfo("America/New_York")
    approval = PersistedAiTransferApproval(
        company_id=request.company_id,
        transfer_id=request.transfer_id,
        request_payload_sha256=request.payload_sha256,
        approved_by="approver-1",
        approved_at=datetime(2026, 11, 1, 5, 55, tzinfo=UTC).astimezone(zone),
        expires_at=datetime(2026, 11, 1, 6, 10, tzinfo=UTC).astimezone(zone),
    )
    admitted_at = datetime(2026, 11, 1, 6, 5, tzinfo=UTC).astimezone(zone)
    assert approval.approved_at.fold == 0
    assert approval.expires_at.fold == 1
    assert admitted_at.fold == 1
    admission = build_ai_transfer_execution_admission(
        request,
        approval,
        company_id="company-a",
        transfer_id="transfer-1",
        execution_id="execution-fold",
        admitted_by="preparer-1",
        admitted_at=admitted_at,
        existing_admission=None,
    )
    claim = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-fold",
        claimed_by="worker-1",
        claimed_at=datetime(2026, 11, 1, 6, 9, tzinfo=UTC).astimezone(zone),
        existing_claims=(),
        existing_receipts=(),
    )
    assert claim.ordinal == 1

    with pytest.raises(ValueError, match="expired"):
        build_ai_transfer_dispatch_claim(
            request,
            approval,
            admission,
            claim_id="claim-after-fold-expiry",
            claimed_by="worker-1",
            claimed_at=datetime(2026, 11, 1, 6, 10, tzinfo=UTC).astimezone(zone),
            existing_claims=(),
            existing_receipts=(),
        )
