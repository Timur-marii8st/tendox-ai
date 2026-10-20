"""Fail-closed orchestration for one permanently claimed AI transfer attempt.

The worker owns no secret or raw-response state.  Its storage gateway must
commit a permanent claim before this module can reach the network and must
atomically retain every complete response together with its terminal receipt.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.ai_requirement_review import (
    AiRequirementReviewRecord,
    AiRequirementTransferBatchRunSnapshot,
)
from procurement.documents.ai_transfer_execution import (
    AiTransferDispatchClaim,
    AiTransferDispatchReceipt,
    AiTransferExecutionAdmission,
)
from procurement.documents.ai_transfer_raw import AiTransferRawMetadata
from procurement.documents.ai_transfer_requirement_result import (
    AiTransferRequirementChunkRejection,
    AiTransferRequirementMaterialization,
    AiTransferRequirementResult,
)
from procurement.documents.ai_transfer_transport import (
    AiTransferTransportAttempt,
    ExactAiTransferHttpClient,
    ExactAiTransferHttpRequest,
)


class AiTransferPreparedDispatch(BaseModel):
    """Server-revalidated exact request material for one committed claim."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    claim: AiTransferDispatchClaim
    request: ExactAiTransferHttpRequest
    chunk_count: int = Field(ge=1, le=9_999)
    approval_expires_at: datetime
    checked_at: datetime

    @field_validator("approval_expires_at", "checked_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value, field="prepared dispatch time")

    @model_validator(mode="after")
    def _binding_is_exact_and_current(self) -> Self:
        claim = _checked_claim(self.claim)
        request = _checked_request(self.request)
        if request.request_sha256 != claim.request_sha256:
            raise ValueError("prepared request does not bind the exact dispatch claim")
        if claim.ordinal > self.chunk_count:
            raise ValueError("prepared request chunk is outside the admitted batch")
        if self.checked_at.astimezone(UTC) < claim.claimed_at.astimezone(UTC):
            raise ValueError("prepared dispatch check cannot predate its claim")
        if self.checked_at.astimezone(UTC) >= self.approval_expires_at.astimezone(UTC):
            raise ValueError("expired approval must return a terminal pre-dispatch receipt")
        return self


class AiTransferWorkerOutcome(BaseModel):
    """Safe terminal result; it contains neither API keys nor response bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    claim: AiTransferDispatchClaim
    receipt: AiTransferDispatchReceipt
    network_attempted: bool
    raw_response_id: str | None = Field(default=None, min_length=1, max_length=200)
    materialization_id: str | None = Field(default=None, min_length=1, max_length=200)
    materialization_status: Literal["MATERIALIZED", "REJECTED"] | None = None
    materialization_reason: (
        Literal[
            "MATERIALIZED",
            "UNSUPPORTED_MULTI_CHUNK",
            "INVALID_CANDIDATE_EVIDENCE",
        ]
        | None
    ) = None
    materialized_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    requirement_batch_pending: bool = False

    @model_validator(mode="after")
    def _receipt_is_exact(self) -> Self:
        claim = _checked_claim(self.claim)
        receipt = _checked_receipt(self.receipt)
        _require_receipt_binding(receipt, claim)
        if self.network_attempted != receipt.attempted:
            raise ValueError("worker outcome network flag differs from its receipt")
        if (self.raw_response_id is not None) != receipt.capture_complete:
            raise ValueError("only a complete capture has retained raw response metadata")
        materialization_fields = (
            self.materialization_id,
            self.materialization_status,
            self.materialization_reason,
        )
        if receipt.outcome == "SUCCESS":
            has_any_materialization = any(value is not None for value in materialization_fields)
            has_materialization = all(value is not None for value in materialization_fields)
            if (
                not receipt.capture_complete
                or (self.requirement_batch_pending and has_any_materialization)
                or (not self.requirement_batch_pending and not has_materialization)
            ):
                raise ValueError("successful capture requires materialization or a pending batch")
        elif (
            any(value is not None for value in materialization_fields)
            or self.materialized_run_id
            or self.requirement_batch_pending
        ):
            raise ValueError("non-successful transfer cannot have a materialization receipt")
        if self.materialization_status == "MATERIALIZED":
            if self.materialization_reason != "MATERIALIZED" or self.materialized_run_id is None:
                raise ValueError("materialized outcome requires its run identity")
        elif self.materialized_run_id is not None:
            raise ValueError("rejected materialization cannot expose a run identity")
        return self


class AiTransferBatchCoordinatorOutcome(BaseModel):
    """One bounded coordinator step with at most one provider attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    company_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    action: Literal["FIRST_CHUNK", "NEXT_CHUNK", "RECOVERY", "STOPPED"]
    status: Literal["PENDING", "MATERIALIZED", "REJECTED", "STOPPED"]
    network_attempted: bool
    claim_ordinal: int | None = Field(default=None, ge=1, le=9_999)
    materialization_id: str | None = Field(default=None, min_length=1, max_length=200)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    reason: Literal[
        "BATCH_PENDING",
        "BATCH_MATERIALIZED",
        "SEMANTIC_REJECTION",
        "TERMINAL_TRANSPORT",
        "CLAIM_WITHOUT_RECEIPT",
    ]
    worker_outcome: AiTransferWorkerOutcome | None = None

    @model_validator(mode="after")
    def _step_is_consistent(self) -> Self:
        attempted_action = self.action in {"FIRST_CHUNK", "NEXT_CHUNK"}
        if attempted_action != (self.worker_outcome is not None):
            raise ValueError("AI transfer coordinator attempt requires its worker outcome")
        if self.worker_outcome is not None:
            if (
                self.worker_outcome.claim.company_id != self.company_id
                or self.worker_outcome.claim.execution_id != self.execution_id
                or self.worker_outcome.claim.ordinal != self.claim_ordinal
                or self.worker_outcome.network_attempted != self.network_attempted
            ):
                raise ValueError("AI transfer coordinator worker identity differs")
        elif self.network_attempted:
            raise ValueError("AI transfer coordinator recovery cannot attempt network")
        if self.status == "MATERIALIZED":
            if (
                self.run_id is None
                or self.materialization_id is None
                or self.reason != "BATCH_MATERIALIZED"
            ):
                raise ValueError("materialized coordinator outcome requires its run")
        elif self.run_id is not None:
            raise ValueError("non-materialized coordinator outcome cannot expose a run")
        if self.status == "REJECTED" and (
            self.materialization_id is None or self.reason != "SEMANTIC_REJECTION"
        ):
            raise ValueError("rejected coordinator outcome requires its receipt")
        if self.status == "STOPPED" and self.reason not in {
            "TERMINAL_TRANSPORT",
            "CLAIM_WITHOUT_RECEIPT",
        }:
            raise ValueError("stopped coordinator outcome requires a terminal reason")
        if self.status == "PENDING" and (
            self.reason != "BATCH_PENDING" or self.materialization_id is not None
        ):
            raise ValueError("pending coordinator outcome cannot expose terminal evidence")
        if self.status == "STOPPED" and self.materialization_id is not None:
            raise ValueError("stopped coordinator outcome cannot expose materialization evidence")
        if self.action == "RECOVERY" and self.status not in {"MATERIALIZED", "REJECTED"}:
            raise ValueError("AI transfer recovery must return a terminal semantic status")
        if self.action == "STOPPED" and self.status != "STOPPED":
            raise ValueError("AI transfer stopped action requires stopped status")
        return self


class AiTransferWorkerStorage(Protocol):
    """Persistence capabilities required by the one-attempt worker."""

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
    ): ...

    def claim_first_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim: ...

    def claim_next_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim: ...

    def prepare_claimed_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        claim: AiTransferDispatchClaim,
    ) -> AiTransferPreparedDispatch | AiTransferDispatchReceipt: ...

    def record_ai_transfer_pre_dispatch_expiry(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        claim: AiTransferDispatchClaim,
        *,
        observed_at: datetime,
    ) -> AiTransferDispatchReceipt: ...

    def persist_captured_ai_transfer_result(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        attempt: AiTransferTransportAttempt,
        raw_response_body: bytes,
    ) -> tuple[AiTransferDispatchReceipt, AiTransferRawMetadata]: ...

    def record_ai_transfer_dispatch_receipt(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        attempt: AiTransferTransportAttempt,
    ) -> AiTransferDispatchReceipt: ...

    def materialize_ai_transfer_requirement_run(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> tuple[AiTransferRequirementMaterialization, AiRequirementReviewRecord | None]: ...

    def materialize_ai_transfer_requirement_batch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> tuple[
        tuple[AiTransferRequirementResult, ...],
        AiRequirementReviewRecord | None,
        AiTransferRequirementChunkRejection | None,
    ]: ...


class _OneChunkAiTransferWorker:
    """Shared one-attempt runner; subclasses select exactly one claim boundary."""

    def __init__(
        self,
        *,
        storage: AiTransferWorkerStorage,
        client: ExactAiTransferHttpClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        *,
        company_id: str,
        worker_id: str,
        execution_id: str,
        api_key: str,
    ) -> AiTransferWorkerOutcome:
        """Commit one claim, then execute its sole attempt without retrying."""
        claim = _checked_claim(self._claim(company_id, worker_id, execution_id))
        _require_claim_context(
            claim,
            company_id=company_id,
            worker_id=worker_id,
            execution_id=execution_id,
        )
        self._require_claim_ordinal(claim)
        prepared_or_expired = self._storage.prepare_claimed_ai_transfer_dispatch(
            company_id,
            worker_id,
            execution_id,
            claim,
        )
        if isinstance(prepared_or_expired, AiTransferDispatchReceipt):
            receipt = _checked_receipt(prepared_or_expired)
            _require_pre_dispatch_expiry(receipt, claim)
            return AiTransferWorkerOutcome(
                claim=claim,
                receipt=receipt,
                network_attempted=False,
                raw_response_id=None,
                materialization_id=None,
                materialization_status=None,
                materialization_reason=None,
                materialized_run_id=None,
                requirement_batch_pending=False,
            )

        prepared = AiTransferPreparedDispatch.model_validate(
            prepared_or_expired.model_dump(mode="python"), strict=True
        )
        if prepared.claim != claim:
            raise ValueError("prepared dispatch does not contain the newly committed claim")

        observed_at = _require_aware(self._clock(), field="AI transfer worker clock")
        if observed_at.astimezone(UTC) < prepared.checked_at.astimezone(UTC):
            raise ValueError("AI transfer worker clock predates server dispatch check")
        if observed_at.astimezone(UTC) >= prepared.approval_expires_at.astimezone(UTC):
            receipt = _checked_receipt(
                self._storage.record_ai_transfer_pre_dispatch_expiry(
                    company_id,
                    worker_id,
                    execution_id,
                    claim,
                    observed_at=observed_at,
                )
            )
            _require_pre_dispatch_expiry(receipt, claim)
            return AiTransferWorkerOutcome(
                claim=claim,
                receipt=receipt,
                network_attempted=False,
                raw_response_id=None,
                materialization_id=None,
                materialization_status=None,
                materialization_reason=None,
                materialized_run_id=None,
                requirement_batch_pending=False,
            )

        captured_receipt: AiTransferDispatchReceipt | None = None
        captured_raw_response_id: str | None = None

        def persist_complete(
            attempt: AiTransferTransportAttempt,
            raw_response_body: bytes,
        ) -> None:
            nonlocal captured_raw_response_id, captured_receipt
            if captured_receipt is not None:
                raise RuntimeError("complete AI transfer result was delivered to its sink twice")
            try:
                receipt, raw_metadata = self._storage.persist_captured_ai_transfer_result(
                    company_id,
                    worker_id,
                    execution_id,
                    attempt,
                    raw_response_body,
                )
            except Exception as error:
                # ``ExactAiTransferHttpClient`` translates httpx transport errors
                # into DELIVERY_UNKNOWN.  A storage sink could coincidentally use
                # the same exception family, so wrap it to prevent a successful
                # HTTP capture from being misclassified and receipted twice.
                raise _CompleteCapturePersistenceError(error) from error
            captured_receipt = _checked_receipt(receipt)
            _require_receipt_binding(captured_receipt, claim)
            _require_receipt_matches_attempt(captured_receipt, attempt)
            try:
                checked_raw_metadata = AiTransferRawMetadata.model_validate(
                    raw_metadata.model_dump(mode="python"), strict=True
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise _CompleteCapturePersistenceError(
                    ValueError("retained raw metadata is invalid")
                ) from error
            if (
                checked_raw_metadata.company_id != claim.company_id
                or checked_raw_metadata.execution_id != claim.execution_id
                or checked_raw_metadata.claim_id != claim.claim_id
                or checked_raw_metadata.receipt_id != captured_receipt.receipt_id
                or checked_raw_metadata.request_sha256 != claim.request_sha256
                or checked_raw_metadata.response_body_sha256 != attempt.response_body_sha256
                or checked_raw_metadata.response_byte_count != attempt.captured_byte_count
            ):
                raise _CompleteCapturePersistenceError(
                    ValueError("retained raw metadata differs from the exact capture")
                )
            captured_raw_response_id = checked_raw_metadata.raw_response_id

        try:
            attempt = self._client.send_once(
                prepared.request,
                api_key=api_key,
                complete_capture_sink=persist_complete,
                dispatch_not_before=prepared.checked_at,
                dispatch_before=prepared.approval_expires_at,
            )
        except _CompleteCapturePersistenceError as error:
            raise error.original from None
        if attempt.capture_complete:
            if captured_receipt is None:
                raise RuntimeError("complete AI transfer response was not retained atomically")
            receipt = captured_receipt
        else:
            receipt = _checked_receipt(
                self._storage.record_ai_transfer_dispatch_receipt(
                    company_id,
                    worker_id,
                    execution_id,
                    attempt,
                )
            )
            _require_receipt_binding(receipt, claim)
            _require_receipt_matches_attempt(receipt, attempt)
        materialization_id: str | None = None
        materialization_status: Literal["MATERIALIZED", "REJECTED"] | None = None
        materialization_reason: (
            Literal[
                "MATERIALIZED",
                "UNSUPPORTED_MULTI_CHUNK",
                "INVALID_CANDIDATE_EVIDENCE",
            ]
            | None
        ) = None
        materialized_run_id: str | None = None
        if receipt.outcome == "SUCCESS":
            if not receipt.capture_complete or captured_raw_response_id is None:
                raise RuntimeError("successful AI transfer receipt lacks durable raw capture")
            if prepared.chunk_count == 1:
                stored_materialization, _ = self._storage.materialize_ai_transfer_requirement_run(
                    company_id,
                    worker_id,
                    execution_id,
                )
                materialization = AiTransferRequirementMaterialization.model_validate(
                    stored_materialization.model_dump(mode="python"), strict=True
                )
                _require_materialization_binding(
                    materialization, claim, receipt, captured_raw_response_id
                )
                materialization_id = materialization.materialization_id
                materialization_status = materialization.status
                materialization_reason = materialization.reason
                materialized_run_id = materialization.run_id
            else:
                results, record, rejection = (
                    self._storage.materialize_ai_transfer_requirement_batch(
                        company_id,
                        worker_id,
                        execution_id,
                    )
                )
                (
                    materialization_id,
                    materialization_status,
                    materialization_reason,
                    materialized_run_id,
                ) = _batch_materialization_projection(
                    results=results,
                    record=record,
                    rejection=rejection,
                    claim=claim,
                    receipt=receipt,
                    raw_response_id=captured_raw_response_id,
                )

        return AiTransferWorkerOutcome(
            claim=claim,
            receipt=receipt,
            network_attempted=True,
            raw_response_id=captured_raw_response_id,
            materialization_id=materialization_id,
            materialization_status=materialization_status,
            materialization_reason=materialization_reason,
            materialized_run_id=materialized_run_id,
            requirement_batch_pending=(
                receipt.outcome == "SUCCESS"
                and prepared.chunk_count > 1
                and materialization_status is None
            ),
        )

    def _claim(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        raise NotImplementedError

    def _require_claim_ordinal(self, claim: AiTransferDispatchClaim) -> None:
        raise NotImplementedError


class FirstChunkAiTransferWorker(_OneChunkAiTransferWorker):
    """Claim and perform at most one network attempt for the first chunk."""

    def _claim(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        return self._storage.claim_first_ai_transfer_dispatch(
            company_id,
            worker_id,
            execution_id,
        )

    def _require_claim_ordinal(self, claim: AiTransferDispatchClaim) -> None:
        if claim.ordinal != 1:
            raise ValueError("first-chunk worker requires ordinal 1")


class NextChunkAiTransferWorker(_OneChunkAiTransferWorker):
    """Claim, perform and materialize progress for one exact next chunk."""

    def _claim(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        return self._storage.claim_next_ai_transfer_dispatch(
            company_id,
            worker_id,
            execution_id,
        )

    def _require_claim_ordinal(self, claim: AiTransferDispatchClaim) -> None:
        if claim.ordinal <= 1:
            raise ValueError("next-chunk worker requires ordinal greater than 1")


class AiTransferBatchCoordinator:
    """Advance one execution by at most one permanently claimed chunk."""

    def __init__(
        self,
        *,
        storage: AiTransferWorkerStorage,
        client: ExactAiTransferHttpClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._client = client
        self._clock = clock

    def run_once(
        self,
        *,
        company_id: str,
        worker_id: str,
        execution_id: str,
        api_key: str,
    ) -> AiTransferBatchCoordinatorOutcome:
        """Read durable state and perform only its next bounded action."""
        stored = self._storage.get_ai_transfer_execution(company_id, execution_id)
        if stored is None:
            raise ValueError("AI transfer execution is unavailable")
        admission = AiTransferExecutionAdmission.model_validate(
            stored[0].model_dump(mode="python"), strict=True
        )
        if admission.company_id != company_id or admission.execution_id != execution_id:
            raise ValueError("AI transfer execution identity differs")
        claim = None if stored[1] is None else _checked_claim(stored[1])
        receipt = None if stored[2] is None else _checked_receipt(stored[2])
        if claim is None:
            if receipt is not None:
                raise ValueError("AI transfer receipt cannot exist without a claim")
            outcome = FirstChunkAiTransferWorker(
                storage=self._storage,
                client=self._client,
                clock=self._clock,
            ).run(
                company_id=company_id,
                worker_id=worker_id,
                execution_id=execution_id,
                api_key=api_key,
            )
            return _coordinator_attempt_outcome("FIRST_CHUNK", outcome)
        if (
            claim.company_id != company_id
            or claim.execution_id != execution_id
            or claim.transfer_id != admission.transfer_id
            or claim.request_payload_sha256 != admission.request_payload_sha256
            or claim.ordinal > admission.chunk_count
        ):
            raise ValueError("AI transfer current claim differs from its admission")
        if receipt is None:
            return AiTransferBatchCoordinatorOutcome(
                company_id=company_id,
                execution_id=execution_id,
                action="STOPPED",
                status="STOPPED",
                network_attempted=False,
                claim_ordinal=claim.ordinal,
                reason="CLAIM_WITHOUT_RECEIPT",
            )
        _require_receipt_binding(receipt, claim)
        if receipt.outcome != "SUCCESS" or not receipt.capture_complete:
            return AiTransferBatchCoordinatorOutcome(
                company_id=company_id,
                execution_id=execution_id,
                action="STOPPED",
                status="STOPPED",
                network_attempted=False,
                claim_ordinal=claim.ordinal,
                reason="TERMINAL_TRANSPORT",
            )
        if claim.ordinal < admission.chunk_count:
            outcome = NextChunkAiTransferWorker(
                storage=self._storage,
                client=self._client,
                clock=self._clock,
            ).run(
                company_id=company_id,
                worker_id=worker_id,
                execution_id=execution_id,
                api_key=api_key,
            )
            return _coordinator_attempt_outcome("NEXT_CHUNK", outcome)
        return self._recover_terminal(
            admission=admission,
            claim=claim,
            receipt=receipt,
            worker_id=worker_id,
        )

    def _recover_terminal(
        self,
        *,
        admission: AiTransferExecutionAdmission,
        claim: AiTransferDispatchClaim,
        receipt: AiTransferDispatchReceipt,
        worker_id: str,
    ) -> AiTransferBatchCoordinatorOutcome:
        if admission.chunk_count == 1:
            materialization, _ = self._storage.materialize_ai_transfer_requirement_run(
                admission.company_id,
                worker_id,
                admission.execution_id,
            )
            checked = AiTransferRequirementMaterialization.model_validate(
                materialization.model_dump(mode="python"), strict=True
            )
            if (
                checked.company_id != admission.company_id
                or checked.execution_id != admission.execution_id
                or checked.claim_id != claim.claim_id
                or checked.receipt_id != receipt.receipt_id
            ):
                raise ValueError("AI transfer recovery materialization identity differs")
            status: Literal["MATERIALIZED", "REJECTED"] = checked.status
            return AiTransferBatchCoordinatorOutcome(
                company_id=admission.company_id,
                execution_id=admission.execution_id,
                action="RECOVERY",
                status=status,
                network_attempted=False,
                claim_ordinal=claim.ordinal,
                materialization_id=checked.materialization_id,
                run_id=checked.run_id,
                reason=("BATCH_MATERIALIZED" if status == "MATERIALIZED" else "SEMANTIC_REJECTION"),
            )
        results, record, rejection = self._storage.materialize_ai_transfer_requirement_batch(
            admission.company_id,
            worker_id,
            admission.execution_id,
        )
        raw_response_id = (
            rejection.raw_response_id
            if rejection is not None
            else results[-1].raw_response_id
            if results
            else ""
        )
        materialization_id, batch_status, _, run_id = _batch_materialization_projection(
            results=results,
            record=record,
            rejection=rejection,
            claim=claim,
            receipt=receipt,
            raw_response_id=raw_response_id,
        )
        if batch_status is None:
            raise ValueError("complete AI transfer recovery remained pending")
        return AiTransferBatchCoordinatorOutcome(
            company_id=admission.company_id,
            execution_id=admission.execution_id,
            action="RECOVERY",
            status=batch_status,
            network_attempted=False,
            claim_ordinal=claim.ordinal,
            materialization_id=materialization_id,
            run_id=run_id,
            reason=(
                "BATCH_MATERIALIZED" if batch_status == "MATERIALIZED" else "SEMANTIC_REJECTION"
            ),
        )


def _checked_claim(value: AiTransferDispatchClaim) -> AiTransferDispatchClaim:
    return AiTransferDispatchClaim.model_validate(value.model_dump(mode="python"), strict=True)


def _coordinator_attempt_outcome(
    action: Literal["FIRST_CHUNK", "NEXT_CHUNK"],
    outcome: AiTransferWorkerOutcome,
) -> AiTransferBatchCoordinatorOutcome:
    checked = AiTransferWorkerOutcome.model_validate(outcome.model_dump(mode="python"), strict=True)
    if checked.receipt.outcome != "SUCCESS":
        status: Literal["PENDING", "MATERIALIZED", "REJECTED", "STOPPED"] = "STOPPED"
        reason: Literal[
            "BATCH_PENDING",
            "BATCH_MATERIALIZED",
            "SEMANTIC_REJECTION",
            "TERMINAL_TRANSPORT",
        ] = "TERMINAL_TRANSPORT"
    elif checked.materialization_status == "MATERIALIZED":
        status = "MATERIALIZED"
        reason = "BATCH_MATERIALIZED"
    elif checked.materialization_status == "REJECTED":
        status = "REJECTED"
        reason = "SEMANTIC_REJECTION"
    else:
        status = "PENDING"
        reason = "BATCH_PENDING"
    return AiTransferBatchCoordinatorOutcome(
        company_id=checked.claim.company_id,
        execution_id=checked.claim.execution_id,
        action=action,
        status=status,
        network_attempted=checked.network_attempted,
        claim_ordinal=checked.claim.ordinal,
        materialization_id=checked.materialization_id,
        run_id=checked.materialized_run_id,
        reason=reason,
        worker_outcome=checked,
    )


def _checked_request(value: ExactAiTransferHttpRequest) -> ExactAiTransferHttpRequest:
    return ExactAiTransferHttpRequest.model_validate(value.model_dump(mode="python"), strict=True)


def _checked_receipt(value: AiTransferDispatchReceipt) -> AiTransferDispatchReceipt:
    return AiTransferDispatchReceipt.model_validate(value.model_dump(mode="python"), strict=True)


def _require_receipt_binding(
    receipt: AiTransferDispatchReceipt,
    claim: AiTransferDispatchClaim,
) -> None:
    if (
        receipt.company_id != claim.company_id
        or receipt.transfer_id != claim.transfer_id
        or receipt.execution_id != claim.execution_id
        or receipt.claim_id != claim.claim_id
        or receipt.claim_payload_sha256 != claim.payload_sha256
        or receipt.ordinal != claim.ordinal
        or receipt.chunk_id != claim.chunk_id
        or receipt.request_sha256 != claim.request_sha256
        or receipt.recorded_by != claim.claimed_by
        or receipt.recorded_at.astimezone(UTC) < claim.claimed_at.astimezone(UTC)
    ):
        raise ValueError("terminal receipt does not bind the exact dispatch claim")


def _require_claim_context(
    claim: AiTransferDispatchClaim,
    *,
    company_id: str,
    worker_id: str,
    execution_id: str,
) -> None:
    if (
        claim.company_id != company_id
        or claim.execution_id != execution_id
        or claim.claimed_by != worker_id
    ):
        raise ValueError("permanent claim does not bind the requested worker execution")


def _require_materialization_binding(
    materialization: AiTransferRequirementMaterialization,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw_response_id: str,
) -> None:
    if (
        materialization.company_id != claim.company_id
        or materialization.transfer_id != claim.transfer_id
        or materialization.execution_id != claim.execution_id
        or materialization.claim_id != claim.claim_id
        or materialization.receipt_id != receipt.receipt_id
        or materialization.raw_response_id != raw_response_id
        or materialization.claim_payload_sha256 != claim.payload_sha256
        or materialization.receipt_payload_sha256 != receipt.payload_sha256
        or materialization.request_payload_sha256 != claim.request_payload_sha256
    ):
        raise ValueError("AI transfer materialization does not bind the exact capture")


def _batch_materialization_projection(
    *,
    results: tuple[AiTransferRequirementResult, ...],
    record: AiRequirementReviewRecord | None,
    rejection: AiTransferRequirementChunkRejection | None,
    claim: AiTransferDispatchClaim,
    receipt: AiTransferDispatchReceipt,
    raw_response_id: str,
) -> tuple[
    str | None,
    Literal["MATERIALIZED", "REJECTED"] | None,
    Literal["MATERIALIZED", "INVALID_CANDIDATE_EVIDENCE"] | None,
    str | None,
]:
    if record is not None and rejection is not None:
        raise ValueError("AI transfer batch cannot be materialized and rejected")
    checked_results = tuple(
        AiTransferRequirementResult.model_validate(result.model_dump(mode="python"), strict=True)
        for result in results
    )
    if tuple(result.ordinal for result in checked_results) != tuple(
        range(1, len(checked_results) + 1)
    ):
        raise ValueError("AI transfer batch progress is not contiguous")
    if rejection is not None:
        checked_rejection = AiTransferRequirementChunkRejection.model_validate(
            rejection.model_dump(mode="python"), strict=True
        )
        if len(checked_results) != checked_rejection.ordinal - 1 or (
            checked_rejection.company_id != claim.company_id
            or checked_rejection.transfer_id != claim.transfer_id
            or checked_rejection.execution_id != claim.execution_id
            or checked_rejection.ordinal != claim.ordinal
            or checked_rejection.claim_id != claim.claim_id
            or checked_rejection.receipt_id != receipt.receipt_id
            or checked_rejection.raw_response_id != raw_response_id
            or checked_rejection.claim_payload_sha256 != claim.payload_sha256
            or checked_rejection.receipt_payload_sha256 != receipt.payload_sha256
            or checked_rejection.request_payload_sha256 != claim.request_payload_sha256
        ):
            raise ValueError("AI transfer batch rejection does not bind the exact capture")
        return (
            checked_rejection.rejection_id,
            "REJECTED",
            "INVALID_CANDIDATE_EVIDENCE",
            None,
        )
    if not checked_results or checked_results[-1].ordinal != claim.ordinal:
        raise ValueError("AI transfer batch progress omits the captured chunk")
    current = checked_results[-1]
    if (
        current.company_id != claim.company_id
        or current.transfer_id != claim.transfer_id
        or current.execution_id != claim.execution_id
        or current.claim_id != claim.claim_id
        or current.receipt_id != receipt.receipt_id
        or current.raw_response_id != raw_response_id
        or current.claim_payload_sha256 != claim.payload_sha256
        or current.receipt_payload_sha256 != receipt.payload_sha256
        or current.request_payload_sha256 != claim.request_payload_sha256
    ):
        raise ValueError("AI transfer batch result does not bind the exact capture")
    if record is None:
        return None, None, None, None
    snapshot = record.snapshot
    if not isinstance(snapshot, AiRequirementTransferBatchRunSnapshot) or (
        snapshot.company_id != claim.company_id
        or snapshot.result.execution_id != claim.execution_id
        or snapshot.result.chunk_results != checked_results
    ):
        raise ValueError("AI transfer batch run differs from its exact chunk results")
    return snapshot.result.batch_result_id, "MATERIALIZED", "MATERIALIZED", snapshot.run_id


def _require_receipt_matches_attempt(
    receipt: AiTransferDispatchReceipt,
    attempt: AiTransferTransportAttempt,
) -> None:
    receipt_evidence = (
        receipt.outcome,
        receipt.reason,
        receipt.attempted,
        receipt.request_sha256,
        receipt.http_status,
        receipt.capture_complete,
        receipt.captured_byte_count,
        receipt.response_body_sha256,
        receipt.provider_response_id,
        receipt.provider_model,
        receipt.assistant_content_sha256,
        receipt.assistant_content_byte_count,
        receipt.validator_version,
        receipt.started_at,
        receipt.finished_at,
    )
    attempt_evidence = (
        attempt.outcome.value,
        attempt.reason.value,
        attempt.attempted,
        attempt.request_sha256,
        attempt.http_status,
        attempt.capture_complete,
        attempt.captured_byte_count,
        attempt.response_body_sha256,
        attempt.provider_response_id,
        attempt.provider_model,
        attempt.assistant_content_sha256,
        attempt.assistant_content_byte_count,
        attempt.validator_version,
        attempt.started_at,
        attempt.finished_at,
    )
    if receipt_evidence != attempt_evidence:
        raise ValueError("terminal receipt differs from the sole transport attempt")


def _require_pre_dispatch_expiry(
    receipt: AiTransferDispatchReceipt,
    claim: AiTransferDispatchClaim,
) -> None:
    _require_receipt_binding(receipt, claim)
    if (
        receipt.outcome != "FAILED"
        or receipt.reason != "APPROVAL_EXPIRED_BEFORE_DISPATCH"
        or receipt.attempted
    ):
        raise ValueError("storage did not return a terminal pre-dispatch expiry receipt")


def _require_aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return value


class _CompleteCapturePersistenceError(Exception):
    """Keep sink failures outside the transport's HTTP exception taxonomy."""

    def __init__(self, original: Exception) -> None:
        self.original = original
        super().__init__("complete AI transfer capture persistence failed")


__all__ = [
    "AiTransferBatchCoordinator",
    "AiTransferBatchCoordinatorOutcome",
    "AiTransferPreparedDispatch",
    "AiTransferWorkerOutcome",
    "AiTransferWorkerStorage",
    "FirstChunkAiTransferWorker",
    "NextChunkAiTransferWorker",
]
