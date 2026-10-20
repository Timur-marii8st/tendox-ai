"""Pure durable-admission events for one approved external AI transfer batch.

The models in this module authorize no network operation on their own.  They
bind an immutable approval consumption, one admitted ordered batch, permanent
per-chunk dispatch claims, and terminal receipts.  Persistence must enforce the
same uniqueness constraints transactionally before a transport worker may use
a newly committed claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
    is_persisted_ai_transfer_authorized,
)
from procurement.documents.completeness_review import canonical_json_sha256

AI_TRANSFER_EXECUTION_ADMISSION_SCHEMA_VERSION: Literal["ai-transfer-execution-admission-v1"] = (
    "ai-transfer-execution-admission-v1"
)
AI_TRANSFER_DISPATCH_CLAIM_SCHEMA_VERSION: Literal["ai-transfer-dispatch-claim-v1"] = (
    "ai-transfer-dispatch-claim-v1"
)
AI_TRANSFER_DISPATCH_RECEIPT_SCHEMA_VERSION: Literal["ai-transfer-dispatch-receipt-v1"] = (
    "ai-transfer-dispatch-receipt-v1"
)

AiTransferDispatchOutcome = Literal["SUCCESS", "FAILED", "DELIVERY_UNKNOWN"]
AiTransferDispatchReason = Literal[
    "VALIDATED_RESPONSE",
    "REDIRECT_REJECTED",
    "HTTP_STATUS_REJECTED",
    "MALFORMED_RESPONSE_JSON",
    "INVALID_PROVIDER_ENVELOPE",
    "MODEL_MISMATCH",
    "INVALID_WIRE_RESPONSE",
    "TIMEOUT",
    "NETWORK_ERROR",
    "RESPONSE_TOO_LARGE",
    "INCOMPLETE_RESPONSE",
    "COMPRESSED_RESPONSE",
    "APPROVAL_EXPIRED_BEFORE_DISPATCH",
]


class AiTransferExecutionAdmission(BaseModel):
    """Atomic approval consumption and immutable admitted ordered batch."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-execution-admission-v1"] = (
        AI_TRANSFER_EXECUTION_ADMISSION_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    approval_expires_at: datetime
    chunk_count: int = Field(ge=1, le=9_999)
    execution_policy: Literal["ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"] = (
        "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"
    )
    status: Literal["ADMITTED"] = "ADMITTED"
    admitted_by: str = Field(min_length=1, max_length=200)
    admitted_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("company_id", "transfer_id", "execution_id", "approved_by", "admitted_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return _nonblank(value, field="execution admission")

    @field_validator("approved_at", "approval_expires_at", "admitted_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value, field="admitted_at")

    @model_validator(mode="after")
    def _digest_is_exact(self) -> Self:
        _require_exact_payload_digest(self)
        return self


class AiTransferDispatchClaim(BaseModel):
    """Permanent claim for one exact chunk and its sole dispatch attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-dispatch-claim-v1"] = (
        AI_TRANSFER_DISPATCH_CLAIM_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    claim_id: str = Field(min_length=1, max_length=200)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordinal: int = Field(ge=1, le=9_999)
    chunk_id: str = Field(pattern=r"^chunk-\d{4}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt: Literal[1] = 1
    claim_status: Literal["PERMANENTLY_CLAIMED"] = "PERMANENTLY_CLAIMED"
    delivery_state: Literal["DELIVERY_UNKNOWN"] = "DELIVERY_UNKNOWN"
    claimed_by: str = Field(min_length=1, max_length=200)
    claimed_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("company_id", "transfer_id", "execution_id", "claim_id", "claimed_by")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return _nonblank(value, field="dispatch claim")

    @field_validator("claimed_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value, field="claimed_at")

    @model_validator(mode="after")
    def _digest_is_exact(self) -> Self:
        _require_exact_payload_digest(self)
        return self


class AiTransferDispatchReceipt(BaseModel):
    """Terminal transport evidence for a permanent claim, without raw content."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-dispatch-receipt-v1"] = (
        AI_TRANSFER_DISPATCH_RECEIPT_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    transfer_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    claim_id: str = Field(min_length=1, max_length=200)
    receipt_id: str = Field(min_length=1, max_length=200)
    claim_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordinal: int = Field(ge=1, le=9_999)
    chunk_id: str = Field(pattern=r"^chunk-\d{4}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: AiTransferDispatchOutcome
    reason: AiTransferDispatchReason
    attempted: bool
    http_status: int | None = Field(default=None, ge=100, le=599)
    capture_complete: bool
    captured_byte_count: int = Field(ge=0)
    response_body_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_response_id: str | None = Field(default=None, min_length=1, max_length=500)
    provider_model: str | None = Field(default=None, min_length=1, max_length=500)
    assistant_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    assistant_content_byte_count: int | None = Field(default=None, ge=1)
    validator_version: Literal["ai-transfer-transport-validator-v1"] = (
        "ai-transfer-transport-validator-v1"
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: Literal["TERMINAL"] = "TERMINAL"
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "transfer_id",
        "execution_id",
        "claim_id",
        "receipt_id",
        "recorded_by",
    )
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return _nonblank(value, field="dispatch receipt")

    @field_validator("started_at", "finished_at", "recorded_at")
    @classmethod
    def _aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            return _require_aware(value, field="dispatch receipt time")
        return value

    @field_validator("provider_response_id", "provider_model")
    @classmethod
    def _safe_provider_text(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or any(not character.isprintable() for character in value)
        ):
            raise ValueError("provider metadata must be trimmed and contain no controls")
        return value

    @model_validator(mode="after")
    def _digest_is_exact(self) -> Self:
        if self.capture_complete != (self.response_body_sha256 is not None):
            raise ValueError("complete capture requires exactly one full response body digest")
        if (self.provider_response_id is None) != (self.provider_model is None):
            raise ValueError("provider response ID and model must appear together")
        if self.attempted:
            if self.started_at is None or self.finished_at is None:
                raise ValueError("attempted dispatch requires start and finish times")
            if self.finished_at.astimezone(UTC) < self.started_at.astimezone(UTC):
                raise ValueError("dispatch receipt finish cannot predate start")
        elif self.started_at is not None or self.finished_at is not None:
            raise ValueError("unattempted dispatch cannot have transport times")
        if self.outcome == "SUCCESS":
            if (
                self.reason != "VALIDATED_RESPONSE"
                or not self.attempted
                or self.http_status != 200
                or not self.capture_complete
                or self.captured_byte_count < 1
                or self.provider_response_id is None
                or self.provider_model is None
                or self.assistant_content_sha256 is None
                or self.assistant_content_byte_count is None
            ):
                raise ValueError(
                    "successful dispatch requires complete validated response evidence"
                )
        elif self.outcome == "DELIVERY_UNKNOWN":
            if (
                self.reason
                not in {
                    "TIMEOUT",
                    "NETWORK_ERROR",
                    "RESPONSE_TOO_LARGE",
                    "INCOMPLETE_RESPONSE",
                    "COMPRESSED_RESPONSE",
                }
                or not self.attempted
                or self.capture_complete
                or self.provider_response_id is not None
                or self.provider_model is not None
                or self.assistant_content_sha256 is not None
                or self.assistant_content_byte_count is not None
            ):
                raise ValueError("unknown delivery requires incomplete transport evidence")
        elif self.reason == "APPROVAL_EXPIRED_BEFORE_DISPATCH":
            if (
                self.attempted
                or self.http_status is not None
                or self.capture_complete
                or self.captured_byte_count != 0
                or self.provider_response_id is not None
                or self.provider_model is not None
                or self.assistant_content_sha256 is not None
                or self.assistant_content_byte_count is not None
            ):
                raise ValueError("pre-dispatch expiry cannot contain transport evidence")
        elif not self.attempted:
            raise ValueError("failed dispatch requires a transport attempt")
        elif self.reason == "REDIRECT_REJECTED":
            if (
                self.http_status is None
                or not 300 <= self.http_status <= 399
                or self.capture_complete
                or self.captured_byte_count != 0
                or self.provider_response_id is not None
            ):
                raise ValueError("redirect failure metadata is inconsistent")
        elif self.reason == "HTTP_STATUS_REJECTED":
            if (
                self.http_status is None
                or self.http_status == 200
                or 300 <= self.http_status <= 399
                or not self.capture_complete
                or self.provider_response_id is not None
            ):
                raise ValueError("HTTP status failure metadata is inconsistent")
        elif self.reason in {"MALFORMED_RESPONSE_JSON", "INVALID_PROVIDER_ENVELOPE"}:
            if (
                self.http_status != 200
                or not self.capture_complete
                or self.provider_response_id is not None
            ):
                raise ValueError("provider envelope failure metadata is inconsistent")
        elif self.reason in {"MODEL_MISMATCH", "INVALID_WIRE_RESPONSE"}:
            if (
                self.http_status != 200
                or not self.capture_complete
                or self.provider_response_id is None
            ):
                raise ValueError("validated provider failure metadata is inconsistent")
        else:
            raise ValueError("failed dispatch requires a safe terminal failure reason")
        if self.outcome != "SUCCESS" and (
            self.assistant_content_sha256 is not None
            or self.assistant_content_byte_count is not None
        ):
            raise ValueError("only validated success may expose assistant content metadata")
        _require_exact_payload_digest(self)
        return self


def build_ai_transfer_execution_admission(
    request: PersistedAiTransferRequest,
    approval: PersistedAiTransferApproval,
    *,
    company_id: str,
    transfer_id: str,
    execution_id: str,
    admitted_by: str,
    admitted_at: datetime,
    existing_admission: AiTransferExecutionAdmission | None,
) -> AiTransferExecutionAdmission:
    """Atomically consume one valid approval into one immutable ordered batch."""
    checked_request = _checked_request(request)
    checked_approval = _checked_approval(approval)
    admitted_at = _require_aware(admitted_at, field="admitted_at")
    execution_id = _nonblank(execution_id, field="execution_id")
    admitted_by = _nonblank(admitted_by, field="admitted_by")
    if existing_admission is not None:
        checked_existing = _checked_admission(existing_admission)
        expected_binding = (
            checked_request.company_id,
            checked_request.transfer_id,
            checked_request.payload_sha256,
            checked_approval.approved_by,
            checked_approval.approved_at.astimezone(UTC),
            checked_approval.expires_at.astimezone(UTC),
        )
        existing_binding = (
            checked_existing.company_id,
            checked_existing.transfer_id,
            checked_existing.request_payload_sha256,
            checked_existing.approved_by,
            checked_existing.approved_at.astimezone(UTC),
            checked_existing.approval_expires_at.astimezone(UTC),
        )
        if existing_binding != expected_binding:
            raise ValueError("existing execution admission does not bind this approval")
        raise ValueError("AI transfer approval has already been admitted")
    if not is_persisted_ai_transfer_authorized(
        checked_request,
        checked_approval,
        company_id=company_id,
        transfer_id=transfer_id,
        now=admitted_at,
    ):
        raise ValueError("AI transfer approval is not valid for execution admission")
    if admitted_by != checked_request.prepared_by:
        raise ValueError("execution must be admitted by the request preparer")
    fields: dict[str, object] = {
        "company_id": company_id,
        "transfer_id": transfer_id,
        "execution_id": execution_id,
        "request_payload_sha256": checked_request.payload_sha256,
        "approved_by": checked_approval.approved_by,
        "approved_at": checked_approval.approved_at,
        "approval_expires_at": checked_approval.expires_at,
        "chunk_count": len(checked_request.chunks),
        "admitted_by": admitted_by,
        "admitted_at": admitted_at,
    }
    payload_sha256 = _payload_sha256(
        AI_TRANSFER_EXECUTION_ADMISSION_SCHEMA_VERSION,
        fields,
        execution_policy="ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1",
        status="ADMITTED",
    )
    return AiTransferExecutionAdmission(
        company_id=company_id,
        transfer_id=transfer_id,
        execution_id=execution_id,
        request_payload_sha256=checked_request.payload_sha256,
        approved_by=checked_approval.approved_by,
        approved_at=checked_approval.approved_at,
        approval_expires_at=checked_approval.expires_at,
        chunk_count=len(checked_request.chunks),
        admitted_by=admitted_by,
        admitted_at=admitted_at,
        payload_sha256=payload_sha256,
    )


def build_ai_transfer_dispatch_claim(
    request: PersistedAiTransferRequest,
    approval: PersistedAiTransferApproval,
    admission: AiTransferExecutionAdmission,
    *,
    claim_id: str,
    claimed_by: str,
    claimed_at: datetime,
    existing_claims: tuple[AiTransferDispatchClaim, ...],
    existing_receipts: tuple[AiTransferDispatchReceipt, ...],
) -> AiTransferDispatchClaim:
    """Claim only the next chunk after every earlier claim has succeeded.

    A committed claim is the sole attempt for its chunk.  With no matching
    receipt its delivery status remains ``UNKNOWN`` and no subsequent claim is
    admissible.
    """
    checked_request = _checked_request(request)
    checked_approval = _checked_approval(approval)
    checked_admission = _checked_admission(admission)
    claimed_at = _require_aware(claimed_at, field="claimed_at")
    claim_id = _nonblank(claim_id, field="claim_id")
    claimed_by = _nonblank(claimed_by, field="claimed_by")
    _require_execution_binding(
        checked_request,
        checked_approval,
        checked_admission,
    )
    if claimed_at.astimezone(UTC) < checked_admission.admitted_at.astimezone(UTC):
        raise ValueError("dispatch claim cannot predate execution admission")
    if not is_persisted_ai_transfer_authorized(
        checked_request,
        checked_approval,
        company_id=checked_admission.company_id,
        transfer_id=checked_admission.transfer_id,
        now=claimed_at,
    ):
        raise ValueError("AI transfer approval expired before the next dispatch claim")

    claims = tuple(_checked_claim(item) for item in existing_claims)
    receipts = tuple(_checked_receipt(item) for item in existing_receipts)
    _require_successful_ordered_history(
        checked_request,
        checked_admission,
        claims=claims,
        receipts=receipts,
        before_claim_at=claimed_at,
    )
    if claim_id in {item.claim_id for item in claims}:
        raise ValueError("dispatch claim ID has already been used")
    chunk_index = len(claims)
    if chunk_index >= len(checked_request.chunks):
        raise ValueError("all AI transfer chunks already have permanent claims")
    chunk = checked_request.chunks[chunk_index]
    fields: dict[str, object] = {
        "company_id": checked_admission.company_id,
        "transfer_id": checked_admission.transfer_id,
        "execution_id": checked_admission.execution_id,
        "claim_id": claim_id,
        "request_payload_sha256": checked_request.payload_sha256,
        "admission_payload_sha256": checked_admission.payload_sha256,
        "ordinal": chunk_index + 1,
        "chunk_id": chunk.chunk_id,
        "request_sha256": chunk.request_sha256,
        "claimed_by": claimed_by,
        "claimed_at": claimed_at,
    }
    payload_sha256 = _payload_sha256(
        AI_TRANSFER_DISPATCH_CLAIM_SCHEMA_VERSION,
        fields,
        attempt=1,
        claim_status="PERMANENTLY_CLAIMED",
        delivery_state="DELIVERY_UNKNOWN",
    )
    return AiTransferDispatchClaim(
        company_id=checked_admission.company_id,
        transfer_id=checked_admission.transfer_id,
        execution_id=checked_admission.execution_id,
        claim_id=claim_id,
        request_payload_sha256=checked_request.payload_sha256,
        admission_payload_sha256=checked_admission.payload_sha256,
        ordinal=chunk_index + 1,
        chunk_id=chunk.chunk_id,
        request_sha256=chunk.request_sha256,
        claimed_by=claimed_by,
        claimed_at=claimed_at,
        payload_sha256=payload_sha256,
    )


def build_ai_transfer_dispatch_receipt(
    claim: AiTransferDispatchClaim,
    *,
    receipt_id: str,
    outcome: AiTransferDispatchOutcome,
    reason: AiTransferDispatchReason,
    attempted: bool,
    request_sha256: str,
    http_status: int | None,
    capture_complete: bool,
    captured_byte_count: int,
    response_body_sha256: str | None,
    provider_response_id: str | None,
    provider_model: str | None,
    assistant_content_sha256: str | None,
    assistant_content_byte_count: int | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    recorded_by: str,
    recorded_at: datetime,
) -> AiTransferDispatchReceipt:
    """Bind trusted transport metadata to one claim without retaining raw content."""
    checked_claim = _checked_claim(claim)
    recorded_at = _require_aware(recorded_at, field="recorded_at")
    receipt_id = _nonblank(receipt_id, field="receipt_id")
    recorded_by = _nonblank(recorded_by, field="recorded_by")
    if recorded_at.astimezone(UTC) < checked_claim.claimed_at.astimezone(UTC):
        raise ValueError("dispatch receipt cannot predate its claim")
    if recorded_by != checked_claim.claimed_by:
        raise ValueError("dispatch receipt must be recorded by the claiming worker")
    if request_sha256 != checked_claim.request_sha256:
        raise ValueError("dispatch receipt request digest differs from the exact claim")
    if started_at is not None and _require_aware(started_at, field="started_at").astimezone(
        UTC
    ) < checked_claim.claimed_at.astimezone(UTC):
        raise ValueError("dispatch transport cannot start before its durable claim")
    if finished_at is not None and recorded_at.astimezone(UTC) < _require_aware(
        finished_at, field="finished_at"
    ).astimezone(UTC):
        raise ValueError("dispatch receipt cannot be recorded before transport finished")
    fields: dict[str, object] = {
        "company_id": checked_claim.company_id,
        "transfer_id": checked_claim.transfer_id,
        "execution_id": checked_claim.execution_id,
        "claim_id": checked_claim.claim_id,
        "receipt_id": receipt_id,
        "claim_payload_sha256": checked_claim.payload_sha256,
        "ordinal": checked_claim.ordinal,
        "chunk_id": checked_claim.chunk_id,
        "request_sha256": request_sha256,
        "outcome": outcome,
        "reason": reason,
        "attempted": attempted,
        "http_status": http_status,
        "capture_complete": capture_complete,
        "captured_byte_count": captured_byte_count,
        "response_body_sha256": response_body_sha256,
        "provider_response_id": provider_response_id,
        "provider_model": provider_model,
        "assistant_content_sha256": assistant_content_sha256,
        "assistant_content_byte_count": assistant_content_byte_count,
        "validator_version": "ai-transfer-transport-validator-v1",
        "started_at": started_at,
        "finished_at": finished_at,
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
    }
    payload_sha256 = _payload_sha256(
        AI_TRANSFER_DISPATCH_RECEIPT_SCHEMA_VERSION,
        fields,
        status="TERMINAL",
    )
    return AiTransferDispatchReceipt(
        company_id=checked_claim.company_id,
        transfer_id=checked_claim.transfer_id,
        execution_id=checked_claim.execution_id,
        claim_id=checked_claim.claim_id,
        receipt_id=receipt_id,
        claim_payload_sha256=checked_claim.payload_sha256,
        ordinal=checked_claim.ordinal,
        chunk_id=checked_claim.chunk_id,
        request_sha256=request_sha256,
        outcome=outcome,
        reason=reason,
        attempted=attempted,
        http_status=http_status,
        capture_complete=capture_complete,
        captured_byte_count=captured_byte_count,
        response_body_sha256=response_body_sha256,
        provider_response_id=provider_response_id,
        provider_model=provider_model,
        assistant_content_sha256=assistant_content_sha256,
        assistant_content_byte_count=assistant_content_byte_count,
        started_at=started_at,
        finished_at=finished_at,
        recorded_by=recorded_by,
        recorded_at=recorded_at,
        payload_sha256=payload_sha256,
    )


def _require_execution_binding(
    request: PersistedAiTransferRequest,
    approval: PersistedAiTransferApproval,
    admission: AiTransferExecutionAdmission,
) -> None:
    if (
        admission.company_id != request.company_id
        or admission.company_id != approval.company_id
        or admission.transfer_id != request.transfer_id
        or admission.transfer_id != approval.transfer_id
        or admission.request_payload_sha256 != request.payload_sha256
        or admission.approved_by != approval.approved_by
        or admission.approved_at.astimezone(UTC) != approval.approved_at.astimezone(UTC)
        or admission.approval_expires_at.astimezone(UTC) != approval.expires_at.astimezone(UTC)
        or admission.chunk_count != len(request.chunks)
        or admission.admitted_by != request.prepared_by
    ):
        raise ValueError("execution admission does not bind exact request and approval")
    if approval.approved_by == request.prepared_by:
        raise ValueError("AI transfer approval must remain independent from preparer")
    admitted_utc = admission.admitted_at.astimezone(UTC)
    if not (
        approval.approved_at.astimezone(UTC) <= admitted_utc < approval.expires_at.astimezone(UTC)
    ):
        raise ValueError("execution admission is outside the approval window")


def _require_successful_ordered_history(
    request: PersistedAiTransferRequest,
    admission: AiTransferExecutionAdmission,
    *,
    claims: tuple[AiTransferDispatchClaim, ...],
    receipts: tuple[AiTransferDispatchReceipt, ...],
    before_claim_at: datetime,
) -> None:
    if len(claims) > len(request.chunks):
        raise ValueError("dispatch history has more claims than approved chunks")
    if len({claim.claim_id for claim in claims}) != len(claims):
        raise ValueError("dispatch claim IDs must be unique")
    if len({receipt.claim_payload_sha256 for receipt in receipts}) != len(receipts):
        raise ValueError("each dispatch claim may have only one terminal receipt")
    receipt_by_claim = {receipt.claim_payload_sha256: receipt for receipt in receipts}
    if len(receipt_by_claim) != len(claims):
        raise ValueError("every permanent prior claim requires exactly one terminal receipt")
    for index, claim in enumerate(claims):
        chunk = request.chunks[index]
        if (
            claim.company_id != admission.company_id
            or claim.transfer_id != admission.transfer_id
            or claim.execution_id != admission.execution_id
            or claim.request_payload_sha256 != request.payload_sha256
            or claim.admission_payload_sha256 != admission.payload_sha256
            or claim.ordinal != index + 1
            or claim.chunk_id != chunk.chunk_id
            or claim.request_sha256 != chunk.request_sha256
        ):
            raise ValueError("dispatch claim history is not exact, ordered, and contiguous")
        receipt = receipt_by_claim.get(claim.payload_sha256)
        if receipt is None or not _receipt_binds_claim(receipt, claim):
            raise ValueError("terminal receipt does not bind its exact dispatch claim")
        if receipt.recorded_at.astimezone(UTC) > before_claim_at.astimezone(UTC):
            raise ValueError("next dispatch claim cannot predate the prior terminal receipt")
        if receipt.outcome != "SUCCESS":
            raise ValueError("non-successful dispatch permanently stops the ordered batch")


def _receipt_binds_claim(
    receipt: AiTransferDispatchReceipt,
    claim: AiTransferDispatchClaim,
) -> bool:
    return (
        receipt.company_id == claim.company_id
        and receipt.transfer_id == claim.transfer_id
        and receipt.execution_id == claim.execution_id
        and receipt.claim_id == claim.claim_id
        and receipt.claim_payload_sha256 == claim.payload_sha256
        and receipt.ordinal == claim.ordinal
        and receipt.chunk_id == claim.chunk_id
        and receipt.request_sha256 == claim.request_sha256
        and receipt.recorded_by == claim.claimed_by
        and receipt.recorded_at.astimezone(UTC) >= claim.claimed_at.astimezone(UTC)
        and (
            receipt.started_at is None
            or receipt.started_at.astimezone(UTC) >= claim.claimed_at.astimezone(UTC)
        )
    )


def _checked_request(value: PersistedAiTransferRequest) -> PersistedAiTransferRequest:
    return PersistedAiTransferRequest.model_validate(value.model_dump(mode="python"))


def _checked_approval(value: PersistedAiTransferApproval) -> PersistedAiTransferApproval:
    return PersistedAiTransferApproval.model_validate(value.model_dump(mode="python"))


def _checked_admission(value: AiTransferExecutionAdmission) -> AiTransferExecutionAdmission:
    return AiTransferExecutionAdmission.model_validate(value.model_dump(mode="python"))


def _checked_claim(value: AiTransferDispatchClaim) -> AiTransferDispatchClaim:
    return AiTransferDispatchClaim.model_validate(value.model_dump(mode="python"))


def _checked_receipt(value: AiTransferDispatchReceipt) -> AiTransferDispatchReceipt:
    return AiTransferDispatchReceipt.model_validate(value.model_dump(mode="python"))


def _payload_sha256(
    schema_version: str,
    fields: dict[str, object],
    **fixed_fields: object,
) -> str:
    return canonical_json_sha256({"schema_version": schema_version, **fields, **fixed_fields})


def _require_exact_payload_digest(value: BaseModel) -> None:
    dumped = value.model_dump(mode="json")
    supplied = dumped.pop("payload_sha256")
    if canonical_json_sha256(dumped) != supplied:
        raise ValueError("AI transfer execution event digest does not match")


def _nonblank(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} text must not be blank")
    return normalized


def _require_aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return value


__all__ = [
    "AI_TRANSFER_DISPATCH_CLAIM_SCHEMA_VERSION",
    "AI_TRANSFER_DISPATCH_RECEIPT_SCHEMA_VERSION",
    "AI_TRANSFER_EXECUTION_ADMISSION_SCHEMA_VERSION",
    "AiTransferDispatchClaim",
    "AiTransferDispatchOutcome",
    "AiTransferDispatchReason",
    "AiTransferDispatchReceipt",
    "AiTransferExecutionAdmission",
    "build_ai_transfer_dispatch_claim",
    "build_ai_transfer_dispatch_receipt",
    "build_ai_transfer_execution_admission",
]
