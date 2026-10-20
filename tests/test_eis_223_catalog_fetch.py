"""Pure synthetic transport tests; no browser or official source calls."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

import procurement.sources.eis_223_catalog_fetch as subject
from procurement.sources.eis_223_catalog_fetch import (
    MAX_SELECTOR_BYTES,
    CatalogTransportResponse,
    Eis223CatalogFetchResult,
    fetch_region_selector,
)
from procurement.sources.eis_223_regions import REGION_SELECTOR_URL

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


class Transport:
    def __init__(
        self,
        *,
        status: int = 200,
        url: str = REGION_SELECTOR_URL,
        chunks: tuple[bytes, ...] = (b"synthetic",),
        headers: dict[str, str] | None = None,
        failure: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.status = status
        self.url = url
        self.parts = chunks
        self.headers = headers or {}
        self.failure = failure
        self.delay = delay
        self.calls = 0
        self.yielded = 0
        self.request_started = False

    async def fetch(self, url: str) -> CatalogTransportResponse:
        self.calls += 1
        self.request_started = True
        assert url == REGION_SELECTOR_URL
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure

        async def chunks():
            for part in self.parts:
                self.yielded += 1
                yield part

        return CatalogTransportResponse(self.status, self.url, self.headers, chunks())


def fetch(transport: Transport):
    return asyncio.run(fetch_region_selector(transport, now=NOW))


def test_exact_200_stream_returns_typed_bytes_hash_and_aware_observation():
    transport = Transport(chunks=(b"one", b"two"))
    result = fetch(transport)
    assert result.status == "FETCHED" and result.body == b"onetwo"
    assert result.response_sha256 == (
        "25b6746d5172ed6352966a013d93ac846e1110d5a25e8f183b5931f4688842a1"
    )
    assert result.observed_at == NOW and result.source_requests == transport.calls == 1
    assert "onetwo" not in repr(result)


def test_content_length_oversize_rejects_before_reading_stream():
    transport = Transport(headers={"content-length": str(MAX_SELECTOR_BYTES + 1)})
    result = fetch(transport)
    assert result.status == "FAILED" and result.reason == "BODY_BYTES_LIMIT"
    assert transport.yielded == 0 and result.body == b"" and result.response_sha256 is None


def test_chunked_oversize_aborts_without_consuming_later_chunks():
    transport = Transport(
        chunks=(b"a" * MAX_SELECTOR_BYTES, b"b", b"must-not-be-read")
    )
    result = fetch(transport)
    assert result.reason == "BODY_BYTES_LIMIT" and transport.yielded == 2


@pytest.mark.parametrize(
    ("transport", "reason"),
    [
        (Transport(status=302), "REDIRECT_REJECTED"),
        (Transport(status=503), "HTTP_REJECTED"),
        (Transport(url="https://zakupki.gov.ru/other"), "SOURCE_URL_MISMATCH"),
        (Transport(failure=RuntimeError("secret source detail")), "TRANSPORT_FAILED"),
        (Transport(chunks=()), "TRANSPORT_FAILED"),
    ],
)
def test_source_failures_return_only_safe_reason(transport, reason):
    result = fetch(transport)
    assert result.status == "FAILED" and result.reason == reason
    assert "secret" not in repr(result) and result.source_requests == 1


def test_timeout_is_bounded_and_safe(monkeypatch):
    monkeypatch.setattr(subject, "FETCH_TIMEOUT_SECONDS", 0.001)
    result = fetch(Transport(delay=0.1))
    assert result.status == "FAILED" and result.reason == "TIMEOUT"


def test_browser_startup_timeout_has_no_source_request(monkeypatch):
    @asynccontextmanager
    async def stalled() -> AsyncIterator[Transport]:
        await asyncio.sleep(0.1)
        yield Transport()

    monkeypatch.setattr(subject, "FETCH_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(subject, "region_selector_browser_transport", stalled)
    result = asyncio.run(fetch_region_selector(now=NOW))
    assert result.status == "FAILED" and result.reason == "TIMEOUT"
    assert result.source_requests == 0


def test_outer_timeout_after_dispatch_preserves_source_request(monkeypatch):
    transport = Transport()

    @asynccontextmanager
    async def slow_close() -> AsyncIterator[Transport]:
        try:
            yield transport
        finally:
            await asyncio.sleep(0.1)

    monkeypatch.setattr(subject, "FETCH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(subject, "region_selector_browser_transport", slow_close)
    result = asyncio.run(fetch_region_selector(now=NOW))
    assert result.status == "FAILED" and result.reason == "TIMEOUT"
    assert transport.request_started and result.source_requests == 1


def test_close_failure_after_dispatch_preserves_source_request(monkeypatch):
    transport = Transport()

    @asynccontextmanager
    async def failed_close() -> AsyncIterator[Transport]:
        yield transport
        raise subject.CatalogTransportError("TRANSPORT_FAILED")

    monkeypatch.setattr(subject, "region_selector_browser_transport", failed_close)
    result = asyncio.run(fetch_region_selector(now=NOW))
    assert result.status == "FAILED" and result.reason == "TRANSPORT_FAILED"
    assert transport.request_started and result.source_requests == 1


@pytest.mark.parametrize("length", ["-1", "not-a-number"])
def test_invalid_content_length_is_transport_failure(length):
    transport = Transport(headers={"content-length": length})
    result = fetch(transport)
    assert result.status == "FAILED" and result.reason == "TRANSPORT_FAILED"
    assert transport.yielded == 0 and result.source_requests == 1


def test_result_rejects_naive_time_or_inconsistent_success():
    with pytest.raises(ValueError, match="CATALOG_TIMEZONE_MISSING"):
        asyncio.run(fetch_region_selector(Transport(), now=datetime(2026, 10, 3)))
    with pytest.raises(ValueError, match="CATALOG_FETCH_RESULT_INVALID"):
        Eis223CatalogFetchResult(
            status="FETCHED",
            http_status=200,
            body=b"synthetic",
            response_sha256="0" * 64,
            observed_at=NOW,
        )
