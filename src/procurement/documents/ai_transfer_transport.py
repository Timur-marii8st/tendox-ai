"""One-attempt exact-byte HTTP transport for an admitted AI transfer chunk.

The adapter deliberately knows nothing about approvals, claims, persistence, or
retries.  Its caller must durably claim a chunk before invoking it.  The API key
exists only as a call argument and neither the response body nor assistant
content is returned from this boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents import ai_requirements as ai_requirements_contract
from procurement.documents.ai_requirements import (
    MAX_OPENROUTER_RESPONSE_BYTES,
    AiRequirementsModelProfile,
    AiRequirementsTransferTransport,
)

AI_TRANSFER_TRANSPORT_VALIDATOR_VERSION: Literal["ai-transfer-transport-validator-v1"] = (
    "ai-transfer-transport-validator-v1"
)
AI_TRANSFER_TRANSPORT_ATTEMPT_SCHEMA_VERSION: Literal["ai-transfer-transport-attempt-v1"] = (
    "ai-transfer-transport-attempt-v1"
)


class AiTransferTransportOutcome(StrEnum):
    """Receipt-level outcome; uncertainty never becomes a deterministic failure."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"


class AiTransferTransportReason(StrEnum):
    """Sanitized transport reason taxonomy with no provider or secret text."""

    VALIDATED_RESPONSE = "VALIDATED_RESPONSE"
    REDIRECT_REJECTED = "REDIRECT_REJECTED"
    HTTP_STATUS_REJECTED = "HTTP_STATUS_REJECTED"
    MALFORMED_RESPONSE_JSON = "MALFORMED_RESPONSE_JSON"
    INVALID_PROVIDER_ENVELOPE = "INVALID_PROVIDER_ENVELOPE"
    MODEL_MISMATCH = "MODEL_MISMATCH"
    INVALID_WIRE_RESPONSE = "INVALID_WIRE_RESPONSE"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    COMPRESSED_RESPONSE = "COMPRESSED_RESPONSE"


class ExactAiTransferHttpRequest(BaseModel):
    """Exact persisted non-secret request material for one claimed chunk."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    transport: AiRequirementsTransferTransport
    model_profile: AiRequirementsModelProfile
    source_block_ids: tuple[str, ...] = Field(min_length=1)
    request_body_utf8: str = Field(min_length=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_capture_max_bytes: int = Field(ge=1, le=MAX_OPENROUTER_RESPONSE_BYTES)

    @model_validator(mode="after")
    def _request_is_exact(self) -> Self:
        # Revalidate nested models from primitives: frozen ``model_copy`` is not a
        # trust boundary and must not bypass the fixed endpoint/header policy.
        AiRequirementsTransferTransport.model_validate(
            self.transport.model_dump(mode="python"), strict=True
        )
        AiRequirementsModelProfile.model_validate(
            self.model_profile.model_dump(mode="python"), strict=True
        )
        if len(set(self.source_block_ids)) != len(self.source_block_ids):
            raise ValueError("AI transfer source block IDs must be unique")
        try:
            body_bytes = self.request_body_utf8.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("AI transfer request body must be valid UTF-8") from error
        if hashlib.sha256(body_bytes).hexdigest() != self.request_sha256:
            raise ValueError("AI transfer request body digest does not match")
        return self


class AiTransferTransportAttempt(BaseModel):
    """Sanitized metadata for exactly one network attempt.

    The full response and assistant content are represented only by digests and
    byte counts.  Raw capture belongs to the separate encrypted-storage slice.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["ai-transfer-transport-attempt-v1"] = (
        AI_TRANSFER_TRANSPORT_ATTEMPT_SCHEMA_VERSION
    )
    validator_version: Literal["ai-transfer-transport-validator-v1"] = (
        AI_TRANSFER_TRANSPORT_VALIDATOR_VERSION
    )
    attempted: Literal[True] = True
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: AiTransferTransportOutcome
    reason: AiTransferTransportReason
    http_status: int | None = Field(default=None, ge=100, le=599)
    capture_complete: bool
    captured_byte_count: int = Field(ge=0)
    response_body_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_response_id: str | None = Field(default=None, min_length=1, max_length=500)
    provider_model: str | None = Field(default=None, min_length=1, max_length=500)
    assistant_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    assistant_content_byte_count: int | None = Field(default=None, ge=1)
    started_at: datetime
    finished_at: datetime

    @field_validator("started_at", "finished_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AI transfer attempt times must include timezone")
        return value

    @field_validator("provider_response_id", "provider_model")
    @classmethod
    def _safe_provider_text(cls, value: str | None) -> str | None:
        if value is not None and not _provider_text_is_safe(value):
            raise ValueError("provider metadata must be trimmed and printable")
        return value

    @model_validator(mode="after")
    def _metadata_is_consistent(self) -> Self:
        if self.finished_at.astimezone(UTC) < self.started_at.astimezone(UTC):
            raise ValueError("AI transfer attempt cannot finish before it starts")
        if self.capture_complete != (self.response_body_sha256 is not None):
            raise ValueError("only a complete response capture has a full body digest")
        if (self.provider_response_id is None) != (self.provider_model is None):
            raise ValueError("provider response ID and model must appear together")
        content_fields = (
            self.assistant_content_sha256,
            self.assistant_content_byte_count,
        )
        if self.outcome is AiTransferTransportOutcome.SUCCESS:
            if (
                self.reason is not AiTransferTransportReason.VALIDATED_RESPONSE
                or self.http_status != 200
                or not self.capture_complete
                or self.provider_response_id is None
                or self.provider_model is None
                or any(value is None for value in content_fields)
            ):
                raise ValueError("successful AI transfer metadata is incomplete")
        elif self.reason is AiTransferTransportReason.VALIDATED_RESPONSE:
            raise ValueError("only a successful AI transfer may be validated")
        if self.outcome is not AiTransferTransportOutcome.SUCCESS and any(
            value is not None for value in content_fields
        ):
            raise ValueError("failed or unknown attempts must not retain assistant metadata")
        unknown_reasons = {
            AiTransferTransportReason.TIMEOUT,
            AiTransferTransportReason.NETWORK_ERROR,
            AiTransferTransportReason.RESPONSE_TOO_LARGE,
            AiTransferTransportReason.INCOMPLETE_RESPONSE,
            AiTransferTransportReason.COMPRESSED_RESPONSE,
        }
        if (self.outcome is AiTransferTransportOutcome.DELIVERY_UNKNOWN) != (
            self.reason in unknown_reasons
        ):
            raise ValueError("AI transfer uncertainty reason does not match outcome")
        if self.reason is AiTransferTransportReason.REDIRECT_REJECTED and (
            self.http_status is None
            or not 300 <= self.http_status <= 399
            or self.capture_complete
            or self.captured_byte_count != 0
            or self.provider_response_id is not None
        ):
            raise ValueError("redirect rejection metadata is inconsistent")
        if self.reason is AiTransferTransportReason.HTTP_STATUS_REJECTED and (
            self.http_status is None
            or self.http_status == 200
            or 300 <= self.http_status <= 399
            or not self.capture_complete
            or self.provider_response_id is not None
        ):
            raise ValueError("HTTP status rejection metadata is inconsistent")
        if self.reason in {
            AiTransferTransportReason.MALFORMED_RESPONSE_JSON,
            AiTransferTransportReason.INVALID_PROVIDER_ENVELOPE,
        } and (
            self.http_status != 200
            or not self.capture_complete
            or self.provider_response_id is not None
        ):
            raise ValueError("provider envelope failure metadata is inconsistent")
        if self.reason in {
            AiTransferTransportReason.MODEL_MISMATCH,
            AiTransferTransportReason.INVALID_WIRE_RESPONSE,
        } and (
            self.http_status != 200
            or not self.capture_complete
            or self.provider_response_id is None
        ):
            raise ValueError("validated provider failure metadata is inconsistent")
        return self


class ExactAiTransferHttpClient:
    """Send exact stored bytes once, without redirects, proxies, or retry logic."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 90.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("AI transfer timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._http_transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_clock = monotonic_clock or time.monotonic

    def send_once(
        self,
        request: ExactAiTransferHttpRequest,
        *,
        api_key: str,
        complete_capture_sink: Callable[[AiTransferTransportAttempt, bytes], None] | None = None,
        dispatch_not_before: datetime | None = None,
        dispatch_before: datetime | None = None,
    ) -> AiTransferTransportAttempt:
        """Perform exactly one claimed HTTP attempt and return sanitized metadata."""
        checked = ExactAiTransferHttpRequest.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        if not api_key or api_key != api_key.strip():
            raise ValueError("OpenRouter API key is missing or malformed")
        started_at = self._now()
        if dispatch_not_before is not None:
            dispatch_not_before = _require_aware_time(
                dispatch_not_before, field="AI transfer dispatch lower bound"
            )
            if started_at.astimezone(UTC) < dispatch_not_before.astimezone(UTC):
                raise ValueError("AI transfer transport clock predates server dispatch check")
        if dispatch_before is not None:
            dispatch_before = _require_aware_time(
                dispatch_before, field="AI transfer dispatch expiry"
            )
            if started_at.astimezone(UTC) >= dispatch_before.astimezone(UTC):
                raise ValueError("AI transfer approval expired before transport dispatch")
        if (
            dispatch_not_before is not None
            and dispatch_before is not None
            and dispatch_not_before.astimezone(UTC) >= dispatch_before.astimezone(UTC)
        ):
            raise ValueError("AI transfer dispatch time window is invalid")
        deadline = self._monotonic_clock() + self._timeout_seconds
        body_bytes = checked.request_body_utf8.encode("utf-8")
        headers = [*checked.transport.headers, ("Authorization", f"Bearer {api_key}")]
        http_request = httpx.Request(
            method=checked.transport.method,
            url=checked.transport.endpoint,
            headers=headers,
            content=body_bytes,
        )
        response: httpx.Response | None = None
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=self._http_transport,
            ) as client:
                # One and only one transport invocation.  No retry loop exists at
                # this boundary, including for connect errors and timeouts.
                response = client.send(http_request, stream=True, follow_redirects=False)
                return self._consume_response(
                    checked,
                    response,
                    started_at=started_at,
                    api_key=api_key,
                    complete_capture_sink=complete_capture_sink,
                    deadline=deadline,
                )
        except httpx.TimeoutException:
            return self._unknown(
                checked,
                reason=AiTransferTransportReason.TIMEOUT,
                started_at=started_at,
                http_status=response.status_code if response is not None else None,
            )
        except httpx.NetworkError:
            return self._unknown(
                checked,
                reason=AiTransferTransportReason.NETWORK_ERROR,
                started_at=started_at,
                http_status=response.status_code if response is not None else None,
            )
        except httpx.HTTPError:
            return self._unknown(
                checked,
                reason=AiTransferTransportReason.INCOMPLETE_RESPONSE,
                started_at=started_at,
                http_status=response.status_code if response is not None else None,
            )
        finally:
            if response is not None:
                response.close()

    def _consume_response(
        self,
        request: ExactAiTransferHttpRequest,
        response: httpx.Response,
        *,
        started_at: datetime,
        api_key: str,
        complete_capture_sink: Callable[[AiTransferTransportAttempt, bytes], None] | None,
        deadline: float,
    ) -> AiTransferTransportAttempt:
        status = response.status_code
        if 300 <= status < 400:
            return self._attempt(
                request,
                outcome=AiTransferTransportOutcome.FAILED,
                reason=AiTransferTransportReason.REDIRECT_REJECTED,
                started_at=started_at,
                http_status=status,
            )
        content_encoding = response.headers.get("Content-Encoding")
        if content_encoding is not None and content_encoding.strip().lower() != "identity":
            return self._unknown(
                request,
                reason=AiTransferTransportReason.COMPRESSED_RESPONSE,
                started_at=started_at,
                http_status=status,
            )

        captured = bytearray()
        try:
            for raw_chunk in response.iter_raw():
                if self._monotonic_clock() >= deadline:
                    return self._unknown(
                        request,
                        reason=AiTransferTransportReason.TIMEOUT,
                        started_at=started_at,
                        http_status=status,
                        captured_byte_count=len(captured),
                    )
                next_byte_count = len(captured) + len(raw_chunk)
                if next_byte_count > request.response_capture_max_bytes:
                    return self._unknown(
                        request,
                        reason=AiTransferTransportReason.RESPONSE_TOO_LARGE,
                        started_at=started_at,
                        http_status=status,
                        captured_byte_count=next_byte_count,
                    )
                captured.extend(raw_chunk)
        except httpx.TimeoutException:
            return self._unknown(
                request,
                reason=AiTransferTransportReason.TIMEOUT,
                started_at=started_at,
                http_status=status,
                captured_byte_count=len(captured),
            )

        except httpx.HTTPError:
            return self._unknown(
                request,
                reason=AiTransferTransportReason.INCOMPLETE_RESPONSE,
                started_at=started_at,
                http_status=status,
                captured_byte_count=len(captured),
            )

        if self._monotonic_clock() >= deadline:
            return self._unknown(
                request,
                reason=AiTransferTransportReason.TIMEOUT,
                started_at=started_at,
                http_status=status,
                captured_byte_count=len(captured),
            )

        response_bytes = bytes(captured)
        response_sha256 = hashlib.sha256(response_bytes).hexdigest()
        if status != 200:
            return self._deliver_complete(
                self._attempt(
                    request,
                    outcome=AiTransferTransportOutcome.FAILED,
                    reason=AiTransferTransportReason.HTTP_STATUS_REJECTED,
                    started_at=started_at,
                    http_status=status,
                    captured_byte_count=len(response_bytes),
                    response_body_sha256=response_sha256,
                ),
                response_bytes,
                complete_capture_sink,
            )
        try:
            payload = json.loads(
                response_bytes.decode("utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_unique_json_object,
            )
        except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return self._deliver_complete(
                self._failed_captured(
                    request,
                    reason=AiTransferTransportReason.MALFORMED_RESPONSE_JSON,
                    started_at=started_at,
                    status=status,
                    response_bytes=response_bytes,
                    response_sha256=response_sha256,
                ),
                response_bytes,
                complete_capture_sink,
            )

        envelope = _validated_provider_envelope(payload)
        if envelope is not None and any(api_key in value for value in envelope[:2]):
            envelope = None
        if envelope is None:
            return self._deliver_complete(
                self._failed_captured(
                    request,
                    reason=AiTransferTransportReason.INVALID_PROVIDER_ENVELOPE,
                    started_at=started_at,
                    status=status,
                    response_bytes=response_bytes,
                    response_sha256=response_sha256,
                ),
                response_bytes,
                complete_capture_sink,
            )
        response_id, response_model, content = envelope
        if response_model != request.model_profile.model:
            return self._deliver_complete(
                self._attempt(
                    request,
                    outcome=AiTransferTransportOutcome.FAILED,
                    reason=AiTransferTransportReason.MODEL_MISMATCH,
                    started_at=started_at,
                    http_status=status,
                    captured_byte_count=len(response_bytes),
                    response_body_sha256=response_sha256,
                    provider_response_id=response_id,
                    provider_model=response_model,
                ),
                response_bytes,
                complete_capture_sink,
            )
        try:
            wire = ai_requirements_contract._parse_wire_response_v2(content)
            if not _wire_source_ids(wire).issubset(request.source_block_ids):
                raise ValueError("provider wire response cites an unavailable source block")
            content_bytes = content.encode("utf-8")
        except (RecursionError, UnicodeEncodeError, ValueError):
            return self._deliver_complete(
                self._attempt(
                    request,
                    outcome=AiTransferTransportOutcome.FAILED,
                    reason=AiTransferTransportReason.INVALID_WIRE_RESPONSE,
                    started_at=started_at,
                    http_status=status,
                    captured_byte_count=len(response_bytes),
                    response_body_sha256=response_sha256,
                    provider_response_id=response_id,
                    provider_model=response_model,
                ),
                response_bytes,
                complete_capture_sink,
            )
        return self._deliver_complete(
            self._attempt(
                request,
                outcome=AiTransferTransportOutcome.SUCCESS,
                reason=AiTransferTransportReason.VALIDATED_RESPONSE,
                started_at=started_at,
                http_status=status,
                captured_byte_count=len(response_bytes),
                response_body_sha256=response_sha256,
                provider_response_id=response_id,
                provider_model=response_model,
                assistant_content_sha256=hashlib.sha256(content_bytes).hexdigest(),
                assistant_content_byte_count=len(content_bytes),
            ),
            response_bytes,
            complete_capture_sink,
        )

    @staticmethod
    def _deliver_complete(
        attempt: AiTransferTransportAttempt,
        response_bytes: bytes,
        sink: Callable[[AiTransferTransportAttempt, bytes], None] | None,
    ) -> AiTransferTransportAttempt:
        if sink is not None:
            sink(attempt, response_bytes)
        return attempt

    def _failed_captured(
        self,
        request: ExactAiTransferHttpRequest,
        *,
        reason: AiTransferTransportReason,
        started_at: datetime,
        status: int,
        response_bytes: bytes,
        response_sha256: str,
    ) -> AiTransferTransportAttempt:
        return self._attempt(
            request,
            outcome=AiTransferTransportOutcome.FAILED,
            reason=reason,
            started_at=started_at,
            http_status=status,
            captured_byte_count=len(response_bytes),
            response_body_sha256=response_sha256,
        )

    def _unknown(
        self,
        request: ExactAiTransferHttpRequest,
        *,
        reason: AiTransferTransportReason,
        started_at: datetime,
        http_status: int | None = None,
        captured_byte_count: int = 0,
    ) -> AiTransferTransportAttempt:
        return self._attempt(
            request,
            outcome=AiTransferTransportOutcome.DELIVERY_UNKNOWN,
            reason=reason,
            started_at=started_at,
            http_status=http_status,
            captured_byte_count=captured_byte_count,
        )

    def _attempt(
        self,
        request: ExactAiTransferHttpRequest,
        *,
        outcome: AiTransferTransportOutcome,
        reason: AiTransferTransportReason,
        started_at: datetime,
        http_status: int | None = None,
        captured_byte_count: int = 0,
        response_body_sha256: str | None = None,
        provider_response_id: str | None = None,
        provider_model: str | None = None,
        assistant_content_sha256: str | None = None,
        assistant_content_byte_count: int | None = None,
    ) -> AiTransferTransportAttempt:
        return AiTransferTransportAttempt(
            request_sha256=request.request_sha256,
            outcome=outcome,
            reason=reason,
            http_status=http_status,
            capture_complete=response_body_sha256 is not None,
            captured_byte_count=captured_byte_count,
            response_body_sha256=response_body_sha256,
            provider_response_id=provider_response_id,
            provider_model=provider_model,
            assistant_content_sha256=assistant_content_sha256,
            assistant_content_byte_count=assistant_content_byte_count,
            started_at=started_at,
            finished_at=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        return _require_aware_time(value, field="AI transfer transport clock")


def _require_aware_time(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return value


def _validated_provider_envelope(payload: object) -> tuple[str, str, str] | None:
    if not isinstance(payload, dict):
        return None
    response_id = payload.get("id")
    response_model = payload.get("model")
    choices = payload.get("choices")
    if (
        not isinstance(response_id, str)
        or not _provider_text_is_safe(response_id)
        or len(response_id) > 500
        or not isinstance(response_model, str)
        or not _provider_text_is_safe(response_model)
        or len(response_model) > 500
        or not isinstance(choices, list)
        or len(choices) != 1
    ):
        return None
    first = choices[0]
    if (
        not isinstance(first, dict)
        or first.get("index") != 0
        or first.get("finish_reason") != "stop"
    ):
        return None
    message = first.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    return response_id, response_model, content


def _provider_text_is_safe(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and all(character.isprintable() for character in value)
    )


def _wire_source_ids(wire: ai_requirements_contract._WireChunkResponseV2) -> set[str]:
    # The private wire model is deliberately reused so transport validation and
    # the existing importer cannot silently drift to different schemas.
    source_ids = set(wire.unresolved_block_ids)
    for requirement in wire.requirements:
        source_ids.update(requirement.source_block_ids)
    for item in wire.items:
        source_ids.update(item.item_name.source_block_ids)
        for claim in (*item.okpd2_codes, *item.ktru_codes):
            source_ids.update(claim.source_block_ids)
        if item.unit is not None:
            source_ids.update(item.unit.source_block_ids)
        if item.quantity is not None:
            source_ids.update(item.quantity.source_block_ids)
    return source_ids


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON constant is forbidden")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key is forbidden")
        result[key] = value
    return result


__all__ = [
    "AI_TRANSFER_TRANSPORT_ATTEMPT_SCHEMA_VERSION",
    "AI_TRANSFER_TRANSPORT_VALIDATOR_VERSION",
    "AiTransferTransportAttempt",
    "AiTransferTransportOutcome",
    "AiTransferTransportReason",
    "ExactAiTransferHttpClient",
    "ExactAiTransferHttpRequest",
]
