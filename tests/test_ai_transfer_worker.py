"""The first-chunk worker never turns a durable claim into a second attempt."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from procurement.documents.ai_requirements import (
    AiRequirementRunStatus,
    prepare_ai_requirements_transfer,
)
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
    build_persisted_ai_transfer_approval,
    build_persisted_ai_transfer_request,
)
from procurement.documents.ai_transfer_execution import (
    AiTransferDispatchClaim,
    AiTransferDispatchReceipt,
    AiTransferExecutionAdmission,
    build_ai_transfer_dispatch_claim,
    build_ai_transfer_dispatch_receipt,
    build_ai_transfer_execution_admission,
)
from procurement.documents.ai_transfer_raw import (
    AiTransferRawBinding,
    AiTransferRawMetadata,
    encrypt_ai_transfer_raw_response,
)
from procurement.documents.ai_transfer_requirement_result import (
    AiTransferRequirementMaterialization,
    AiTransferRequirementResult,
    build_ai_transfer_requirement_materialization,
)
from procurement.documents.ai_transfer_transport import (
    AiTransferTransportAttempt,
    ExactAiTransferHttpClient,
    ExactAiTransferHttpRequest,
)
from procurement.documents.ai_transfer_worker import (
    AiTransferBatchCoordinator,
    AiTransferBatchCoordinatorOutcome,
    AiTransferPreparedDispatch,
    AiTransferWorkerOutcome,
    FirstChunkAiTransferWorker,
    NextChunkAiTransferWorker,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.documents.facts import CompletenessStatus
from procurement.domain.provenance import Extractor, Provenance

SECRET = "worker-test-secret-must-not-escape"
CLAIMED_AT = datetime(2026, 9, 17, 10, 7, tzinfo=UTC)
CHECKED_AT = datetime(2026, 9, 17, 10, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {
                "action": "RECOVERY",
                "status": "PENDING",
                "reason": "BATCH_PENDING",
            },
            "recovery must return a terminal semantic status",
        ),
        (
            {
                "action": "STOPPED",
                "status": "STOPPED",
                "reason": "TERMINAL_TRANSPORT",
                "materialization_id": "forged-materialization",
            },
            "cannot expose materialization evidence",
        ),
        (
            {
                "action": "RECOVERY",
                "status": "REJECTED",
                "reason": "SEMANTIC_REJECTION",
            },
            "rejected coordinator outcome requires its receipt",
        ),
        (
            {
                "action": "RECOVERY",
                "status": "MATERIALIZED",
                "reason": "BATCH_MATERIALIZED",
                "materialization_id": "materialization-1",
            },
            "materialized coordinator outcome requires its run",
        ),
    ],
)
def test_coordinator_outcome_rejects_contradictory_terminal_evidence(
    values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        AiTransferBatchCoordinatorOutcome(
            company_id="company-a",
            execution_id="execution-1",
            network_attempted=False,
            claim_ordinal=2,
            **values,
        )


class _TestTenantKekProvider:
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


def _execution() -> tuple[
    PersistedAiTransferRequest,
    PersistedAiTransferApproval,
    AiTransferExecutionAdmission,
]:
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
    request = build_persisted_ai_transfer_request(
        manifest,
        transfer_id="transfer-1",
        prepared_by="preparer-1",
        prepared_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
    )
    approval = build_persisted_ai_transfer_approval(
        request,
        approved_by="approver-1",
        approved_at=datetime(2026, 9, 17, 10, 5, tzinfo=UTC),
    )
    admission = build_ai_transfer_execution_admission(
        request,
        approval,
        company_id=request.company_id,
        transfer_id=request.transfer_id,
        execution_id="execution-1",
        admitted_by=request.prepared_by,
        admitted_at=datetime(2026, 9, 17, 10, 6, tzinfo=UTC),
        existing_admission=None,
    )
    return request, approval, admission


def _claim_and_dispatch() -> tuple[AiTransferDispatchClaim, ExactAiTransferHttpRequest, datetime]:
    request, approval, admission = _execution()
    claim = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-1",
        claimed_by="worker-1",
        claimed_at=CLAIMED_AT,
        existing_claims=(),
        existing_receipts=(),
    )
    chunk = request.chunks[0]
    exact_request = ExactAiTransferHttpRequest(
        transport=request.transport,
        model_profile=request.model_profile,
        source_block_ids=chunk.source_block_ids,
        request_body_utf8=chunk.request_body_json,
        request_sha256=chunk.request_sha256,
        response_capture_max_bytes=request.response_capture_max_bytes,
    )
    return claim, exact_request, approval.expires_at


def _next_claim_and_dispatch() -> tuple[
    AiTransferDispatchClaim,
    ExactAiTransferHttpRequest,
    datetime,
]:
    request, approval, admission = _execution()
    first_claim = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-1",
        claimed_by="worker-1",
        claimed_at=CLAIMED_AT,
        existing_claims=(),
        existing_receipts=(),
    )
    first_receipt = build_ai_transfer_dispatch_receipt(
        first_claim,
        receipt_id="receipt-first",
        outcome="SUCCESS",
        reason="VALIDATED_RESPONSE",
        attempted=True,
        request_sha256=first_claim.request_sha256,
        http_status=200,
        capture_complete=True,
        captured_byte_count=2,
        response_body_sha256="b" * 64,
        provider_response_id="generation-first",
        provider_model=request.model_profile.model,
        assistant_content_sha256="c" * 64,
        assistant_content_byte_count=2,
        started_at=CLAIMED_AT,
        finished_at=CLAIMED_AT,
        recorded_by=first_claim.claimed_by,
        recorded_at=CLAIMED_AT,
    )
    next_claim = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-2",
        claimed_by="worker-1",
        claimed_at=CHECKED_AT,
        existing_claims=(first_claim,),
        existing_receipts=(first_receipt,),
    )
    chunk = request.chunks[1]
    exact_request = ExactAiTransferHttpRequest(
        transport=request.transport,
        model_profile=request.model_profile,
        source_block_ids=chunk.source_block_ids,
        request_body_utf8=chunk.request_body_json,
        request_sha256=chunk.request_sha256,
        response_capture_max_bytes=request.response_capture_max_bytes,
    )
    return next_claim, exact_request, approval.expires_at


def _provider_body(request: ExactAiTransferHttpRequest) -> bytes:
    content = json.dumps(
        {
            "requirements": [],
            "unresolved_block_ids": list(request.source_block_ids),
            "document_notes": [],
            "items": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return json.dumps(
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
    ).encode("utf-8")


def _streamed_response(status_code: int, content: bytes) -> httpx.Response:
    return httpx.Response(status_code, stream=httpx.ByteStream(content))


def _attempt_receipt(
    claim: AiTransferDispatchClaim,
    attempt: AiTransferTransportAttempt,
) -> AiTransferDispatchReceipt:
    return build_ai_transfer_dispatch_receipt(
        claim,
        receipt_id="receipt-1",
        outcome=attempt.outcome.value,
        reason=attempt.reason.value,
        attempted=True,
        request_sha256=attempt.request_sha256,
        http_status=attempt.http_status,
        capture_complete=attempt.capture_complete,
        captured_byte_count=attempt.captured_byte_count,
        response_body_sha256=attempt.response_body_sha256,
        provider_response_id=attempt.provider_response_id,
        provider_model=attempt.provider_model,
        assistant_content_sha256=attempt.assistant_content_sha256,
        assistant_content_byte_count=attempt.assistant_content_byte_count,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        recorded_by=claim.claimed_by,
        recorded_at=attempt.finished_at,
    )


def _fake_chunk_result(
    request: PersistedAiTransferRequest,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw: AiTransferRawMetadata,
) -> AiTransferRequirementResult:
    chunk = request.chunks[claim.ordinal - 1]
    fields = {
        "company_id": claim.company_id,
        "result_id": f"result-{claim.ordinal}",
        "transfer_id": claim.transfer_id,
        "execution_id": claim.execution_id,
        "ordinal": claim.ordinal,
        "claim_id": claim.claim_id,
        "receipt_id": receipt.receipt_id,
        "raw_response_id": raw.raw_response_id,
        "request_payload_sha256": claim.request_payload_sha256,
        "claim_payload_sha256": claim.payload_sha256,
        "receipt_payload_sha256": receipt.payload_sha256,
        "raw_metadata_sha256": raw.metadata_sha256,
        "request_sha256": claim.request_sha256,
        "response_body_sha256": raw.response_body_sha256,
        "assistant_content_sha256": receipt.assistant_content_sha256,
        "provider_response_id": receipt.provider_response_id,
        "provider_model": receipt.provider_model,
        "source_document_id": request.source_document_id,
        "source_sha256": request.source_sha256,
        "extraction_sha256": request.extraction_sha256,
        "source_block_ids": chunk.source_block_ids,
        "candidates": (),
        "item_candidates": (),
        "unresolved_block_ids": chunk.source_block_ids,
        "execution_status": AiRequirementRunStatus.COMPLETE,
        "completeness_status": CompletenessStatus.UNKNOWN,
        "prepared_by": request.prepared_by,
        "materialized_by": claim.claimed_by,
        "materialized_at": receipt.recorded_at,
    }
    return AiTransferRequirementResult.model_validate(
        {
            **fields,
            "payload_sha256": canonical_json_sha256(
                {"schema_version": "ai-transfer-requirement-result-v1", **fields}
            ),
        },
        strict=True,
    )


def _expiry_receipt(
    claim: AiTransferDispatchClaim,
    recorded_at: datetime,
) -> AiTransferDispatchReceipt:
    return build_ai_transfer_dispatch_receipt(
        claim,
        receipt_id="receipt-expired",
        outcome="FAILED",
        reason="APPROVAL_EXPIRED_BEFORE_DISPATCH",
        attempted=False,
        request_sha256=claim.request_sha256,
        http_status=None,
        capture_complete=False,
        captured_byte_count=0,
        response_body_sha256=None,
        provider_response_id=None,
        provider_model=None,
        assistant_content_sha256=None,
        assistant_content_byte_count=None,
        started_at=None,
        finished_at=None,
        recorded_by=claim.claimed_by,
        recorded_at=recorded_at,
    )


class FakeStorage:
    def __init__(self) -> None:
        self.persisted_request, _, self.admission = _execution()
        self.claim, self.request, self.expires_at = _claim_and_dispatch()
        self.execution_claim: AiTransferDispatchClaim | None = None
        self.execution_receipt: AiTransferDispatchReceipt | None = None
        self.prepare_result: AiTransferPreparedDispatch | AiTransferDispatchReceipt = (
            AiTransferPreparedDispatch(
                claim=self.claim,
                request=self.request,
                chunk_count=1,
                approval_expires_at=self.expires_at,
                checked_at=CHECKED_AT,
            )
        )
        self.claim_error: Exception | None = None
        self.capture_error: Exception | None = None
        self.claim_calls = 0
        self.prepare_calls = 0
        self.capture_calls = 0
        self.incomplete_receipt_calls = 0
        self.materialize_calls = 0
        self.batch_materialize_calls = 0
        self.materialize_error: Exception | None = None
        self.expiry_calls = 0
        self.raw_response_sha256: str | None = None
        self.raw_metadata: AiTransferRawMetadata | None = None
        self.captured_receipt: AiTransferDispatchReceipt | None = None

    def get_ai_transfer_execution(
        self,
        company_id: str,
        execution_id: str,
    ) -> (
        tuple[
            AiTransferExecutionAdmission,
            AiTransferDispatchClaim | None,
            AiTransferDispatchReceipt | None,
        ]
        | None
    ):
        assert (company_id, execution_id) == ("company-a", "execution-1")
        return self.admission, self.execution_claim, self.execution_receipt

    def claim_first_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        self.claim_calls += 1
        assert (company_id, worker_id, execution_id) == (
            "company-a",
            "worker-1",
            "execution-1",
        )
        if self.claim_error is not None:
            raise self.claim_error
        return self.claim

    def prepare_claimed_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        claim: AiTransferDispatchClaim,
    ) -> AiTransferPreparedDispatch | AiTransferDispatchReceipt:
        self.prepare_calls += 1
        assert (company_id, worker_id, execution_id, claim) == (
            "company-a",
            "worker-1",
            "execution-1",
            self.claim,
        )
        return self.prepare_result

    def record_ai_transfer_pre_dispatch_expiry(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        claim: AiTransferDispatchClaim,
        *,
        observed_at: datetime,
    ) -> AiTransferDispatchReceipt:
        self.expiry_calls += 1
        assert (company_id, worker_id, execution_id, claim) == (
            "company-a",
            "worker-1",
            "execution-1",
            self.claim,
        )
        return _expiry_receipt(claim, observed_at)

    def persist_captured_ai_transfer_result(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        attempt: AiTransferTransportAttempt,
        raw_response_body: bytes,
    ) -> tuple[AiTransferDispatchReceipt, AiTransferRawMetadata]:
        self.capture_calls += 1
        assert (company_id, worker_id, execution_id) == (
            "company-a",
            "worker-1",
            "execution-1",
        )
        self.raw_response_sha256 = hashlib.sha256(raw_response_body).hexdigest()
        if self.capture_error is not None:
            raise self.capture_error
        receipt = _attempt_receipt(self.claim, attempt)
        self.captured_receipt = receipt
        metadata = encrypt_ai_transfer_raw_response(
            binding=AiTransferRawBinding(
                company_id=self.claim.company_id,
                raw_response_id="raw-response-1",
                transfer_id=self.claim.transfer_id,
                execution_id=self.claim.execution_id,
                ordinal=self.claim.ordinal,
                claim_id=self.claim.claim_id,
                chunk_id=self.claim.chunk_id,
                claim_payload_sha256=self.claim.payload_sha256,
                receipt_id=receipt.receipt_id,
                receipt_payload_sha256=receipt.payload_sha256,
                request_sha256=self.claim.request_sha256,
                response_body_sha256=attempt.response_body_sha256 or "0" * 64,
                response_byte_count=attempt.captured_byte_count,
                received_at=attempt.finished_at,
            ),
            raw_response_body=raw_response_body,
            key_provider=_TestTenantKekProvider(),
        ).metadata
        self.raw_metadata = metadata
        return receipt, metadata

    def record_ai_transfer_dispatch_receipt(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        attempt: AiTransferTransportAttempt,
    ) -> AiTransferDispatchReceipt:
        self.incomplete_receipt_calls += 1
        assert (company_id, worker_id, execution_id) == (
            "company-a",
            "worker-1",
            "execution-1",
        )
        return _attempt_receipt(self.claim, attempt)

    def materialize_ai_transfer_requirement_run(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> tuple[AiTransferRequirementMaterialization, None]:
        self.materialize_calls += 1
        assert (company_id, worker_id, execution_id) == (
            "company-a",
            "worker-1",
            "execution-1",
        )
        if self.materialize_error is not None:
            raise self.materialize_error
        assert self.raw_metadata is not None
        assert self.captured_receipt is not None
        return (
            build_ai_transfer_requirement_materialization(
                self.persisted_request,
                self.claim,
                self.captured_receipt,
                self.raw_metadata,
                materialization_id="materialization-1",
                status="REJECTED",
                reason="UNSUPPORTED_MULTI_CHUNK",
                result=None,
                run_id=None,
                run_evidence_sha256=None,
                materialized_by=worker_id,
                materialized_at=CHECKED_AT,
            ),
            None,
        )

    def materialize_ai_transfer_requirement_batch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> tuple[tuple[AiTransferRequirementResult, ...], None, None]:
        self.batch_materialize_calls += 1
        assert (company_id, worker_id, execution_id) == (
            "company-a",
            "worker-1",
            "execution-1",
        )
        if self.materialize_error is not None:
            raise self.materialize_error
        assert self.raw_metadata is not None
        assert self.captured_receipt is not None
        results: list[AiTransferRequirementResult] = []
        if self.claim.ordinal > 1:
            request, approval, admission = _execution()
            first_claim = build_ai_transfer_dispatch_claim(
                request,
                approval,
                admission,
                claim_id="claim-1",
                claimed_by="worker-1",
                claimed_at=CLAIMED_AT,
                existing_claims=(),
                existing_receipts=(),
            )
            first_receipt = build_ai_transfer_dispatch_receipt(
                first_claim,
                receipt_id="receipt-first",
                outcome="SUCCESS",
                reason="VALIDATED_RESPONSE",
                attempted=True,
                request_sha256=first_claim.request_sha256,
                http_status=200,
                capture_complete=True,
                captured_byte_count=2,
                response_body_sha256="b" * 64,
                provider_response_id="generation-first",
                provider_model=request.model_profile.model,
                assistant_content_sha256="c" * 64,
                assistant_content_byte_count=2,
                started_at=CLAIMED_AT,
                finished_at=CLAIMED_AT,
                recorded_by=first_claim.claimed_by,
                recorded_at=CLAIMED_AT,
            )
            first_raw = AiTransferRawMetadata.model_construct(
                raw_response_id="raw-response-first",
                metadata_sha256="d" * 64,
                response_body_sha256="b" * 64,
            )
            results.append(_fake_chunk_result(request, first_claim, first_receipt, first_raw))
        results.append(
            _fake_chunk_result(
                self.persisted_request,
                self.claim,
                self.captured_receipt,
                self.raw_metadata,
            )
        )
        return tuple(results), None, None


class NextFakeStorage(FakeStorage):
    def __init__(self) -> None:
        super().__init__()
        self.claim, self.request, self.expires_at = _next_claim_and_dispatch()
        self.prepare_result = AiTransferPreparedDispatch(
            claim=self.claim,
            request=self.request,
            chunk_count=3,
            approval_expires_at=self.expires_at,
            checked_at=CHECKED_AT,
        )
        self.next_claim_calls = 0

    def claim_next_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        self.next_claim_calls += 1
        assert (company_id, worker_id, execution_id) == (
            "company-a",
            "worker-1",
            "execution-1",
        )
        if self.claim_error is not None:
            raise self.claim_error
        return self.claim


def _worker(
    storage: FakeStorage,
    handler: httpx.MockTransport,
    *,
    clock: datetime = CHECKED_AT,
) -> FirstChunkAiTransferWorker:
    return FirstChunkAiTransferWorker(
        storage=storage,
        client=ExactAiTransferHttpClient(transport=handler, clock=lambda: CHECKED_AT),
        clock=lambda: clock,
    )


def _run(worker: FirstChunkAiTransferWorker) -> AiTransferWorkerOutcome:
    return worker.run(
        company_id="company-a",
        worker_id="worker-1",
        execution_id="execution-1",
        api_key=SECRET,
    )


def _run_next(
    storage: NextFakeStorage,
    handler: httpx.MockTransport,
) -> AiTransferWorkerOutcome:
    return NextChunkAiTransferWorker(
        storage=storage,
        client=ExactAiTransferHttpClient(transport=handler, clock=lambda: CHECKED_AT),
        clock=lambda: CHECKED_AT,
    ).run(
        company_id="company-a",
        worker_id="worker-1",
        execution_id="execution-1",
        api_key=SECRET,
    )


def _run_coordinator(
    storage: FakeStorage,
    handler: httpx.MockTransport,
):
    return AiTransferBatchCoordinator(
        storage=storage,
        client=ExactAiTransferHttpClient(transport=handler, clock=lambda: CHECKED_AT),
        clock=lambda: CHECKED_AT,
    ).run_once(
        company_id="company-a",
        worker_id="worker-1",
        execution_id="execution-1",
        api_key=SECRET,
    )


def test_complete_success_is_sent_once_and_atomically_retained() -> None:
    storage = FakeStorage()
    calls = 0
    response_body = _provider_body(storage.request)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, response_body)

    outcome = _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert outcome.receipt.outcome == "SUCCESS"
    assert outcome.network_attempted is True
    assert outcome.raw_response_id == "raw-response-1"
    assert outcome.materialization_status == "REJECTED"
    assert outcome.materialization_reason == "UNSUPPORTED_MULTI_CHUNK"
    assert outcome.materialized_run_id is None
    assert storage.capture_calls == 1
    assert storage.materialize_calls == 1
    assert storage.incomplete_receipt_calls == 0
    assert storage.raw_response_sha256 == hashlib.sha256(response_body).hexdigest()


def test_coordinator_starts_only_first_chunk_for_new_execution() -> None:
    storage = FakeStorage()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, _provider_body(storage.request))

    outcome = _run_coordinator(storage, httpx.MockTransport(handler))

    assert calls == 1
    assert outcome.action == "FIRST_CHUNK"
    assert outcome.claim_ordinal == 1
    assert outcome.status == "REJECTED"
    assert outcome.network_attempted is True


def test_coordinator_advances_only_one_next_chunk() -> None:
    storage = NextFakeStorage()
    request, approval, admission = _execution()
    first_claim = build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id="claim-1",
        claimed_by="worker-1",
        claimed_at=CLAIMED_AT,
        existing_claims=(),
        existing_receipts=(),
    )
    first_receipt = build_ai_transfer_dispatch_receipt(
        first_claim,
        receipt_id="receipt-first",
        outcome="SUCCESS",
        reason="VALIDATED_RESPONSE",
        attempted=True,
        request_sha256=first_claim.request_sha256,
        http_status=200,
        capture_complete=True,
        captured_byte_count=2,
        response_body_sha256="b" * 64,
        provider_response_id="generation-first",
        provider_model=request.model_profile.model,
        assistant_content_sha256="c" * 64,
        assistant_content_byte_count=2,
        started_at=CLAIMED_AT,
        finished_at=CLAIMED_AT,
        recorded_by=first_claim.claimed_by,
        recorded_at=CLAIMED_AT,
    )
    storage.execution_claim = first_claim
    storage.execution_receipt = first_receipt
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, _provider_body(storage.request))

    outcome = _run_coordinator(storage, httpx.MockTransport(handler))

    assert calls == 1
    assert outcome.action == "NEXT_CHUNK"
    assert outcome.claim_ordinal == 2
    assert outcome.status == "PENDING"
    assert storage.next_claim_calls == 1


def test_coordinator_stops_permanently_claimed_chunk_without_receipt() -> None:
    storage = FakeStorage()
    storage.execution_claim = storage.claim
    calls = 0

    outcome = _run_coordinator(
        storage,
        httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("no network"))),
    )

    assert calls == 0
    assert outcome.action == "STOPPED"
    assert outcome.status == "STOPPED"
    assert outcome.reason == "CLAIM_WITHOUT_RECEIPT"
    assert outcome.network_attempted is False


def test_next_chunk_success_is_sent_once_and_materializes_batch_progress() -> None:
    storage = NextFakeStorage()
    calls = 0
    response_body = _provider_body(storage.request)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, response_body)

    outcome = _run_next(storage, httpx.MockTransport(handler))

    assert calls == 1
    assert storage.next_claim_calls == 1
    assert outcome.claim.ordinal == 2
    assert outcome.receipt.outcome == "SUCCESS"
    assert outcome.raw_response_id == "raw-response-1"
    assert outcome.requirement_batch_pending is True
    assert outcome.materialization_id is None
    assert outcome.materialization_status is None
    assert outcome.materialization_reason is None
    assert outcome.materialized_run_id is None
    assert storage.capture_calls == 1
    assert storage.materialize_calls == 0
    assert storage.batch_materialize_calls == 1


def test_first_chunk_of_multi_chunk_execution_materializes_batch_progress() -> None:
    storage = FakeStorage()
    assert isinstance(storage.prepare_result, AiTransferPreparedDispatch)
    storage.prepare_result = storage.prepare_result.model_copy(update={"chunk_count": 2})
    response_body = _provider_body(storage.request)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, response_body)

    outcome = _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert outcome.receipt.outcome == "SUCCESS"
    assert outcome.requirement_batch_pending is True
    assert outcome.materialization_status is None
    assert storage.materialize_calls == 0
    assert storage.batch_materialize_calls == 1


def test_next_chunk_claim_conflict_stops_before_prepare_and_network() -> None:
    storage = NextFakeStorage()
    storage.claim_error = RuntimeError("next claim is not admissible")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(RuntimeError, match="not admissible"):
        _run_next(storage, httpx.MockTransport(handler))

    assert calls == 0
    assert storage.next_claim_calls == 1
    assert storage.prepare_calls == 0


def test_next_chunk_worker_rejects_first_claim_before_prepare_and_network() -> None:
    storage = NextFakeStorage()
    storage.claim, storage.request, storage.expires_at = _claim_and_dispatch()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(ValueError, match="ordinal greater than 1"):
        _run_next(storage, httpx.MockTransport(handler))

    assert calls == 0
    assert storage.next_claim_calls == 1
    assert storage.prepare_calls == 0


def test_complete_provider_failure_uses_capture_sink_without_second_receipt() -> None:
    storage = FakeStorage()
    calls = 0
    response_body = f'{{"error":"{SECRET} raw provider text"}}'.encode()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(500, response_body)

    outcome = _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert outcome.receipt.outcome == "FAILED"
    assert outcome.receipt.reason == "HTTP_STATUS_REJECTED"
    assert outcome.raw_response_id == "raw-response-1"
    assert storage.capture_calls == 1
    assert storage.materialize_calls == 0
    assert storage.incomplete_receipt_calls == 0
    assert SECRET not in repr(outcome)
    assert "raw provider text" not in outcome.model_dump_json()


@pytest.mark.parametrize(
    ("handler_result", "reason"),
    [
        (httpx.ReadTimeout("secret provider timeout"), "TIMEOUT"),
        (httpx.Response(307, headers={"Location": "https://invalid.example"}), "REDIRECT_REJECTED"),
    ],
)
def test_incomplete_attempt_gets_one_safe_receipt(
    handler_result: httpx.Response | httpx.HTTPError,
    reason: str,
) -> None:
    storage = FakeStorage()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if isinstance(handler_result, httpx.HTTPError):
            raise handler_result
        return handler_result

    outcome = _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert outcome.receipt.reason == reason
    assert outcome.raw_response_id is None
    assert storage.capture_calls == 0
    assert storage.incomplete_receipt_calls == 1
    assert storage.materialize_calls == 0


def test_expired_between_database_check_and_send_records_terminal_without_network() -> None:
    storage = FakeStorage()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("network must remain unreachable after expiry")

    outcome = _run(_worker(storage, httpx.MockTransport(handler), clock=storage.expires_at))

    assert calls == 0
    assert outcome.network_attempted is False
    assert outcome.raw_response_id is None
    assert outcome.receipt.reason == "APPROVAL_EXPIRED_BEFORE_DISPATCH"
    assert storage.expiry_calls == 1


def test_server_terminal_expiry_short_circuits_local_clock_and_network() -> None:
    storage = FakeStorage()
    storage.prepare_result = _expiry_receipt(storage.claim, storage.expires_at)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("network must remain unreachable after server expiry")

    outcome = _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 0
    assert outcome.receipt.reason == "APPROVAL_EXPIRED_BEFORE_DISPATCH"
    assert storage.expiry_calls == 0


def test_duplicate_claim_conflict_never_prepares_or_sends() -> None:
    storage = FakeStorage()
    storage.claim_error = RuntimeError("claim already exists")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(RuntimeError, match="already exists"):
        _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 0
    assert storage.prepare_calls == 0


def test_capture_persistence_failure_is_not_retried_or_downgraded() -> None:
    storage = FakeStorage()
    storage.capture_error = httpx.ConnectError("encrypted store unavailable")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, _provider_body(storage.request))

    with pytest.raises(httpx.ConnectError, match="encrypted store unavailable"):
        _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert storage.capture_calls == 1
    assert storage.incomplete_receipt_calls == 0


def test_materialization_failure_preserves_capture_without_second_network_attempt() -> None:
    storage = FakeStorage()
    storage.materialize_error = RuntimeError("materializer interrupted after capture")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, _provider_body(storage.request))

    with pytest.raises(RuntimeError, match="interrupted after capture"):
        _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert storage.capture_calls == 1
    assert storage.materialize_calls == 1
    assert storage.incomplete_receipt_calls == 0


def test_batch_materialization_failure_preserves_capture_without_second_network_attempt() -> None:
    storage = FakeStorage()
    assert isinstance(storage.prepare_result, AiTransferPreparedDispatch)
    storage.prepare_result = storage.prepare_result.model_copy(update={"chunk_count": 2})
    storage.materialize_error = RuntimeError("batch interrupted after capture")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _streamed_response(200, _provider_body(storage.request))

    with pytest.raises(RuntimeError, match="batch interrupted after capture"):
        _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 1
    assert storage.capture_calls == 1
    assert storage.batch_materialize_calls == 1
    assert storage.incomplete_receipt_calls == 0


def test_request_claim_mismatch_fails_before_network() -> None:
    storage = FakeStorage()
    _, request, _ = _claim_and_dispatch()
    mismatched = request.model_copy(update={"request_sha256": "f" * 64})
    storage.prepare_result = AiTransferPreparedDispatch.model_construct(
        claim=storage.claim,
        request=mismatched,
        chunk_count=1,
        approval_expires_at=storage.expires_at,
        checked_at=CHECKED_AT,
    )
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    with pytest.raises(ValueError, match=r"digest does not match|exact dispatch claim"):
        _run(_worker(storage, httpx.MockTransport(handler)))

    assert calls == 0


def test_naive_worker_clock_is_rejected_before_network() -> None:
    storage = FakeStorage()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    worker = _worker(
        storage,
        httpx.MockTransport(handler),
        clock=CHECKED_AT.replace(tzinfo=None),
    )
    with pytest.raises(ValueError, match="timezone"):
        _run(worker)

    assert calls == 0


def test_worker_clock_rollback_before_server_check_is_rejected_before_network() -> None:
    storage = FakeStorage()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    worker = _worker(
        storage,
        httpx.MockTransport(handler),
        clock=CHECKED_AT - timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="predates server dispatch check"):
        _run(worker)

    assert calls == 0


def test_safe_result_and_worker_repr_never_retain_secret_or_raw_bytes() -> None:
    storage = FakeStorage()
    raw_marker = "sensitive-raw-marker"
    response_body = f'{{"error":"{raw_marker}"}}'.encode()
    worker = _worker(
        storage,
        httpx.MockTransport(lambda _: _streamed_response(429, response_body)),
    )

    outcome = _run(worker)

    serialized = outcome.model_dump_json()
    assert SECRET not in serialized
    assert SECRET not in repr(worker)
    assert raw_marker not in serialized
    assert raw_marker not in repr(outcome)
    assert storage.raw_response_sha256 == hashlib.sha256(response_body).hexdigest()


def test_prepared_dispatch_rejects_database_check_at_expiry() -> None:
    claim, request, expires_at = _claim_and_dispatch()

    with pytest.raises(ValueError, match="terminal pre-dispatch receipt"):
        AiTransferPreparedDispatch(
            claim=claim,
            request=request,
            chunk_count=1,
            approval_expires_at=expires_at,
            checked_at=expires_at,
        )


def test_prepared_dispatch_rejects_check_before_permanent_claim() -> None:
    claim, request, expires_at = _claim_and_dispatch()

    with pytest.raises(ValueError, match="cannot predate"):
        AiTransferPreparedDispatch(
            claim=claim,
            request=request,
            chunk_count=1,
            approval_expires_at=expires_at,
            checked_at=CLAIMED_AT - timedelta(microseconds=1),
        )
