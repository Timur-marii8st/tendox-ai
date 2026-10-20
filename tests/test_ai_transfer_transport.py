from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from procurement.documents.ai_requirements import (
    DEFAULT_OPENROUTER_MODEL,
    AiRequirementsModelProfile,
    AiRequirementsTransferTransport,
)
from procurement.documents.ai_transfer_transport import (
    AI_TRANSFER_TRANSPORT_ATTEMPT_SCHEMA_VERSION,
    AI_TRANSFER_TRANSPORT_VALIDATOR_VERSION,
    AiTransferTransportOutcome,
    AiTransferTransportReason,
    ExactAiTransferHttpClient,
    ExactAiTransferHttpRequest,
)

SECRET = "test-secret-must-never-be-retained"
REQUEST_BODY = '{  "model" : "google/gemma-4-31b-it:free", "note":"точные bytes" }'
WIRE_CONTENT = json.dumps(
    {
        "requirements": [],
        "unresolved_block_ids": ["b000001"],
        "document_notes": [],
        "items": [],
    },
    ensure_ascii=False,
    separators=(",", ":"),
)


def exact_request(*, max_bytes: int = 4096) -> ExactAiTransferHttpRequest:
    return ExactAiTransferHttpRequest(
        transport=AiRequirementsTransferTransport(),
        model_profile=AiRequirementsModelProfile(
            profile_id="gemma-json-object-v1",
            model=DEFAULT_OPENROUTER_MODEL,
            response_format="json_object",
        ),
        source_block_ids=("b000001",),
        request_body_utf8=REQUEST_BODY,
        request_sha256=hashlib.sha256(REQUEST_BODY.encode("utf-8")).hexdigest(),
        response_capture_max_bytes=max_bytes,
    )


def provider_body(
    *,
    model: str = DEFAULT_OPENROUTER_MODEL,
    content: object = WIRE_CONTENT,
    response_id: object = "generation-1",
) -> bytes:
    return json.dumps(
        {
            "id": response_id,
            "model": model,
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


def streamed_response(
    status_code: int,
    content: bytes,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers,
        stream=httpx.ByteStream(content),
    )


def test_exact_bytes_one_call_and_sanitized_success_metadata() -> None:
    calls = 0
    response_bytes = provider_body()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.content == REQUEST_BODY.encode("utf-8")
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["X-OpenRouter-Metadata"] == "enabled"
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        return streamed_response(200, response_bytes)

    result = ExactAiTransferHttpClient(transport=httpx.MockTransport(handler)).send_once(
        exact_request(), api_key=SECRET
    )

    assert calls == 1
    assert result.schema_version == AI_TRANSFER_TRANSPORT_ATTEMPT_SCHEMA_VERSION
    assert result.validator_version == AI_TRANSFER_TRANSPORT_VALIDATOR_VERSION
    assert result.attempted is True
    assert result.outcome is AiTransferTransportOutcome.SUCCESS
    assert result.reason is AiTransferTransportReason.VALIDATED_RESPONSE
    assert result.capture_complete is True
    assert result.captured_byte_count == len(response_bytes)
    assert result.response_body_sha256 == hashlib.sha256(response_bytes).hexdigest()
    assert result.provider_response_id == "generation-1"
    assert result.provider_model == DEFAULT_OPENROUTER_MODEL
    assert (
        result.assistant_content_sha256 == hashlib.sha256(WIRE_CONTENT.encode("utf-8")).hexdigest()
    )
    assert result.assistant_content_byte_count == len(WIRE_CONTENT.encode("utf-8"))
    assert result.started_at.tzinfo is not None
    assert SECRET not in repr(result)
    assert SECRET not in result.model_dump_json()
    assert REQUEST_BODY not in repr(result)
    assert WIRE_CONTENT not in result.model_dump_json()


@pytest.mark.parametrize(
    ("clock", "lower", "upper", "message"),
    [
        (
            datetime(2026, 9, 17, 9, 59, 59, tzinfo=UTC),
            datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 17, 10, 15, tzinfo=UTC),
            "predates server dispatch check",
        ),
        (
            datetime(2026, 9, 17, 10, 15, tzinfo=UTC),
            datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 17, 10, 15, tzinfo=UTC),
            "expired before transport dispatch",
        ),
    ],
)
def test_dispatch_time_window_is_checked_before_network(
    clock: datetime,
    lower: datetime,
    upper: datetime,
    message: str,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    client = ExactAiTransferHttpClient(transport=httpx.MockTransport(handler), clock=lambda: clock)
    with pytest.raises(ValueError, match=message):
        client.send_once(
            exact_request(),
            api_key=SECRET,
            dispatch_not_before=lower,
            dispatch_before=upper,
        )

    assert calls == 0


def test_redirect_is_rejected_without_following() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(307, headers={"Location": "https://example.invalid/leak"})

    result = ExactAiTransferHttpClient(transport=httpx.MockTransport(handler)).send_once(
        exact_request(), api_key=SECRET
    )

    assert calls == 1
    assert result.outcome is AiTransferTransportOutcome.FAILED
    assert result.reason is AiTransferTransportReason.REDIRECT_REJECTED
    assert result.http_status == 307
    assert result.capture_complete is False


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ReadTimeout("provider echoed test-secret-must-never-be-retained"), "TIMEOUT"),
        (httpx.ConnectError("provider echoed test-secret-must-never-be-retained"), "NETWORK_ERROR"),
    ],
)
def test_timeout_and_connect_error_are_unknown_once(
    error: httpx.HTTPError,
    reason: str,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error

    result = ExactAiTransferHttpClient(transport=httpx.MockTransport(handler)).send_once(
        exact_request(), api_key=SECRET
    )

    assert calls == 1
    assert result.outcome is AiTransferTransportOutcome.DELIVERY_UNKNOWN
    assert result.reason.value == reason
    assert SECRET not in repr(result)


def test_non_2xx_is_failed_after_bounded_complete_capture_without_body_leak() -> None:
    response_bytes = f'{{"error":"{SECRET} and document text"}}'.encode()
    result = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: streamed_response(401, response_bytes))
    ).send_once(exact_request(), api_key=SECRET)

    assert result.outcome is AiTransferTransportOutcome.FAILED
    assert result.reason is AiTransferTransportReason.HTTP_STATUS_REJECTED
    assert result.capture_complete is True
    assert result.response_body_sha256 == hashlib.sha256(response_bytes).hexdigest()
    assert SECRET not in result.model_dump_json()
    assert "document text" not in repr(result)


class OversizeStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"12345"
        yield b"67890"


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b'{"id":'
        raise httpx.ReadError("incomplete secret body")


class CompressedStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"compressed"


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(200, stream=OversizeStream()), "RESPONSE_TOO_LARGE"),
        (httpx.Response(200, stream=BrokenStream()), "INCOMPLETE_RESPONSE"),
        (
            httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=CompressedStream(),
            ),
            "COMPRESSED_RESPONSE",
        ),
    ],
)
def test_unbounded_incomplete_or_compressed_response_is_unknown(
    response: httpx.Response,
    reason: str,
) -> None:
    result = ExactAiTransferHttpClient(transport=httpx.MockTransport(lambda _: response)).send_once(
        exact_request(max_bytes=8), api_key=SECRET
    )

    assert result.outcome is AiTransferTransportOutcome.DELIVERY_UNKNOWN
    assert result.reason.value == reason
    assert result.capture_complete is False
    assert result.response_body_sha256 is None


@pytest.mark.parametrize(
    ("response_bytes", "reason"),
    [
        (b"{not-json", "MALFORMED_RESPONSE_JSON"),
        (provider_body(content=None), "INVALID_PROVIDER_ENVELOPE"),
        (provider_body(response_id=SECRET), "INVALID_PROVIDER_ENVELOPE"),
        (provider_body(model="unexpected/model"), "MODEL_MISMATCH"),
        (provider_body(content='{"requirements":[]}'), "INVALID_WIRE_RESPONSE"),
        (
            provider_body(
                content=json.dumps(
                    {
                        "requirements": [],
                        "unresolved_block_ids": ["not-in-request"],
                        "document_notes": [],
                        "items": [],
                    }
                )
            ),
            "INVALID_WIRE_RESPONSE",
        ),
    ],
)
def test_captured_invalid_response_is_failed(response_bytes: bytes, reason: str) -> None:
    result = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: streamed_response(200, response_bytes))
    ).send_once(exact_request(), api_key=SECRET)

    assert result.outcome is AiTransferTransportOutcome.FAILED
    assert result.reason.value == reason
    assert result.capture_complete is True
    assert result.response_body_sha256 == hashlib.sha256(response_bytes).hexdigest()
    assert SECRET not in result.model_dump_json()


def test_only_http_200_can_be_success() -> None:
    response_bytes = provider_body()
    result = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: streamed_response(201, response_bytes))
    ).send_once(exact_request(), api_key=SECRET)

    assert result.outcome is AiTransferTransportOutcome.FAILED
    assert result.reason is AiTransferTransportReason.HTTP_STATUS_REJECTED


@pytest.mark.parametrize("field_value", [" generation-1", "generation-1\n", "generation-\x7f"])
def test_untrusted_provider_metadata_must_be_trimmed_and_printable(field_value: str) -> None:
    response_bytes = provider_body(response_id=field_value)
    result = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: streamed_response(200, response_bytes))
    ).send_once(exact_request(), api_key=SECRET)

    assert result.outcome is AiTransferTransportOutcome.FAILED
    assert result.reason is AiTransferTransportReason.INVALID_PROVIDER_ENVELOPE
    assert result.provider_response_id is None


def test_forged_nested_transport_and_wrong_digest_fail_before_network() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return streamed_response(200, provider_body())

    valid = exact_request()
    forged = valid.model_copy(
        update={
            "transport": valid.transport.model_copy(
                update={"endpoint": "https://example.invalid/exfiltrate"}
            )
        }
    )
    client = ExactAiTransferHttpClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValidationError):
        client.send_once(forged, api_key=SECRET)

    wrong_digest = valid.model_copy(update={"request_sha256": "0" * 64})
    with pytest.raises(ValidationError):
        client.send_once(wrong_digest, api_key=SECRET)
    assert called is False


def test_secret_is_never_stored_on_client_or_input_validation_error() -> None:
    client = ExactAiTransferHttpClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))

    with pytest.raises(ValueError) as error:
        client.send_once(exact_request(), api_key=f" {SECRET} ")

    assert SECRET not in str(error.value)
    assert SECRET not in repr(client)
    assert SECRET not in repr(exact_request())


def test_attempt_rejects_naive_clock_before_network() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, content=provider_body())

    client = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime(2026, 9, 17),
    )
    with pytest.raises(ValueError, match="timezone"):
        client.send_once(exact_request(), api_key=SECRET)
    assert called is False


def test_clock_metadata_is_utc_comparable() -> None:
    now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    result = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: streamed_response(500, b"{}")),
        clock=lambda: now,
    ).send_once(exact_request(), api_key=SECRET)
    assert result.started_at == now
    assert result.finished_at == now


def test_complete_capture_sink_receives_exact_bytes_but_unknown_does_not() -> None:
    captured: list[tuple[object, bytes]] = []
    response_bytes = provider_body()
    client = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: streamed_response(200, response_bytes))
    )

    attempt = client.send_once(
        exact_request(),
        api_key=SECRET,
        complete_capture_sink=lambda metadata, body: captured.append((metadata, body)),
    )

    assert captured == [(attempt, response_bytes)]

    captured.clear()
    unknown = ExactAiTransferHttpClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=BrokenStream()))
    ).send_once(
        exact_request(),
        api_key=SECRET,
        complete_capture_sink=lambda metadata, body: captured.append((metadata, body)),
    )
    assert unknown.outcome is AiTransferTransportOutcome.DELIVERY_UNKNOWN
    assert captured == []


def test_total_stream_budget_stops_slow_chunk_sequence_without_capture_handoff() -> None:
    monotonic_values = iter((0.0, 91.0))
    captured: list[bytes] = []
    result = ExactAiTransferHttpClient(
        timeout_seconds=90,
        transport=httpx.MockTransport(lambda _: streamed_response(200, provider_body())),
        monotonic_clock=lambda: next(monotonic_values),
    ).send_once(
        exact_request(),
        api_key=SECRET,
        complete_capture_sink=lambda _metadata, body: captured.append(body),
    )

    assert result.outcome is AiTransferTransportOutcome.DELIVERY_UNKNOWN
    assert result.reason is AiTransferTransportReason.TIMEOUT
    assert result.capture_complete is False
    assert captured == []
