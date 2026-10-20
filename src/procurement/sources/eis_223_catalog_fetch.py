"""Bounded Chromium fetch of the official public RI223 region selector."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eis_223_regions import REGION_SELECTOR_URL
from procurement.sources.eis_feed_sync import _proxy_server

MAX_SELECTOR_BYTES = 512 * 1024
FETCH_TIMEOUT_SECONDS = 45
CatalogFetchReason = Literal[
    "BODY_BYTES_LIMIT",
    "HTTP_REJECTED",
    "REDIRECT_REJECTED",
    "SOURCE_URL_MISMATCH",
    "TIMEOUT",
    "TRANSPORT_FAILED",
]


class CatalogFetchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Eis223CatalogFetchResult(CatalogFetchModel):
    status: Literal["FETCHED", "FAILED"]
    source_url: Literal[
        "https://zakupki.gov.ru/epz/nsi/kladr/chooseRegion.html"
    ] = "https://zakupki.gov.ru/epz/nsi/kladr/chooseRegion.html"
    http_status: int | None = Field(default=None, ge=100, le=599)
    body: bytes = Field(default=b"", repr=False, max_length=MAX_SELECTOR_BYTES)
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    source_requests: int = Field(default=1, ge=0, le=1)
    reason: CatalogFetchReason | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Eis223CatalogFetchResult:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("CATALOG_TIMEZONE_MISSING")
        if self.status == "FETCHED":
            if (
                self.http_status != 200
                or not self.body
                or self.reason is not None
                or self.source_requests != 1
                or self.response_sha256 != hashlib.sha256(self.body).hexdigest()
            ):
                raise ValueError("CATALOG_FETCH_RESULT_INVALID")
        elif self.body or self.response_sha256 is not None or self.reason is None:
            raise ValueError("CATALOG_FETCH_RESULT_INVALID")
        return self


@dataclass(frozen=True)
class CatalogTransportResponse:
    status: int
    url: str
    headers: dict[str, str]
    chunks: AsyncIterator[bytes]


class CatalogTransport(Protocol):
    async def fetch(self, url: str) -> CatalogTransportResponse: ...


class CatalogTransportError(RuntimeError):
    def __init__(self, reason: CatalogFetchReason) -> None:
        super().__init__(reason)
        self.reason = reason


async def fetch_region_selector(
    transport: CatalogTransport | None = None,
    *,
    now: datetime | None = None,
) -> Eis223CatalogFetchResult:
    """Fetch exact official bytes; parsing and persistence are separate gates."""
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("CATALOG_TIMEZONE_MISSING")
    if transport is None:
        browser: CatalogTransport | None = None
        try:
            async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
                async with region_selector_browser_transport() as active_browser:
                    browser = active_browser
                    return await fetch_region_selector(browser, now=observed_at)
        except TimeoutError:
            requests = int(bool(getattr(browser, "request_started", False)))
            return _failed(observed_at, "TIMEOUT", source_requests=requests)
        except CatalogTransportError as error:
            requests = int(bool(getattr(browser, "request_started", False)))
            return _failed(observed_at, error.reason, source_requests=requests)
    status: int | None = None
    try:
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            response = await transport.fetch(REGION_SELECTOR_URL)
            status = response.status
            if 300 <= response.status < 400:
                return _failed(observed_at, "REDIRECT_REJECTED", status)
            if response.url != REGION_SELECTOR_URL:
                return _failed(observed_at, "SOURCE_URL_MISMATCH", status)
            if response.status != 200:
                return _failed(observed_at, "HTTP_REJECTED", status)
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                    if declared_length < 0:
                        return _failed(observed_at, "TRANSPORT_FAILED", status)
                    if declared_length > MAX_SELECTOR_BYTES:
                        return _failed(observed_at, "BODY_BYTES_LIMIT", status)
                except ValueError:
                    return _failed(observed_at, "TRANSPORT_FAILED", status)
            body = bytearray()
            async for chunk in response.chunks:
                if not isinstance(chunk, bytes):
                    return _failed(observed_at, "TRANSPORT_FAILED", status)
                if len(body) + len(chunk) > MAX_SELECTOR_BYTES:
                    return _failed(observed_at, "BODY_BYTES_LIMIT", status)
                body.extend(chunk)
            if not body:
                return _failed(observed_at, "TRANSPORT_FAILED", status)
            content = bytes(body)
            return Eis223CatalogFetchResult(
                status="FETCHED",
                http_status=200,
                body=content,
                response_sha256=hashlib.sha256(content).hexdigest(),
                observed_at=observed_at,
            )
    except TimeoutError:
        return _failed(observed_at, "TIMEOUT", status)
    except CatalogTransportError as error:
        return _failed(observed_at, error.reason, status)
    except Exception:
        return _failed(observed_at, "TRANSPORT_FAILED", status)


def _failed(
    observed_at: datetime,
    reason: CatalogFetchReason,
    status: int | None = None,
    *,
    source_requests: int = 1,
) -> Eis223CatalogFetchResult:
    return Eis223CatalogFetchResult(
        status="FAILED",
        http_status=status,
        observed_at=observed_at,
        reason=reason,
        source_requests=source_requests,
    )


class _BrowserCatalogTransport:
    def __init__(self, page: object) -> None:
        self.page = page
        self.request_started = False

    async def fetch(self, url: str) -> CatalogTransportResponse:
        if url != REGION_SELECTOR_URL:
            raise CatalogTransportError("SOURCE_URL_MISMATCH")
        page = self.page
        session = await page.context.new_cdp_session(page)  # type: ignore[attr-defined]
        paused: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()

        def capture(event: dict[str, object]) -> None:
            if not paused.done():
                paused.set_result(event)

        session.on("Fetch.requestPaused", capture)
        await session.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": REGION_SELECTOR_URL, "requestStage": "Response"}]},
        )
        self.request_started = True
        navigation = asyncio.create_task(
            page.goto(url, wait_until="commit", timeout=FETCH_TIMEOUT_SECONDS * 1000)  # type: ignore[attr-defined]
        )
        try:
            event = await paused
            request = event.get("request")
            final_url = request.get("url") if isinstance(request, dict) else None
            status = event.get("responseStatusCode")
            request_id = event.get("requestId")
            if not isinstance(final_url, str) or not isinstance(status, int) or not isinstance(
                request_id, str
            ):
                raise CatalogTransportError("TRANSPORT_FAILED")
            raw_headers = event.get("responseHeaders")
            header_items = raw_headers if isinstance(raw_headers, list) else []
            headers = {
                str(item.get("name", "")).lower(): str(item.get("value", ""))
                for item in header_items
                if isinstance(item, dict)
            }
            if final_url != REGION_SELECTOR_URL or status != 200:
                navigation.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await navigation

                async def empty() -> AsyncIterator[bytes]:
                    if False:
                        yield b""

                return CatalogTransportResponse(status, final_url, headers, empty())
            stream = await session.send("Fetch.takeResponseBodyAsStream", {"requestId": request_id})
            handle = stream.get("stream")
            if not isinstance(handle, str):
                raise CatalogTransportError("TRANSPORT_FAILED")

            async def chunks() -> AsyncIterator[bytes]:
                total = 0
                try:
                    while True:
                        part = await session.send("IO.read", {"handle": handle, "size": 65536})
                        encoded = part.get("data", "")
                        if not isinstance(encoded, str):
                            raise CatalogTransportError("TRANSPORT_FAILED")
                        raw = (
                            base64.b64decode(encoded, validate=True)
                            if part.get("base64Encoded")
                            else encoded.encode()
                        )
                        total += len(raw)
                        if total > MAX_SELECTOR_BYTES:
                            raise CatalogTransportError("BODY_BYTES_LIMIT")
                        if raw:
                            yield raw
                        if part.get("eof") is True:
                            break
                finally:
                    await session.send("IO.close", {"handle": handle})
                    navigation.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await navigation

            return CatalogTransportResponse(status, final_url, headers, chunks())
        except Exception:
            navigation.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await navigation
            raise


@asynccontextmanager
async def region_selector_browser_transport() -> AsyncIterator[CatalogTransport]:
    """One normal-TLS Chromium context; no source request occurs before it yields."""
    try:
        from playwright.async_api import Error, async_playwright
        from playwright.async_api import TimeoutError as PlaywrightTimeout
    except ImportError as error:
        raise CatalogTransportError("TRANSPORT_FAILED") from error
    try:
        async with async_playwright() as playwright:
            proxy = _proxy_server()
            browser = await playwright.chromium.launch(
                headless=True,
                timeout=15_000,
                proxy={"server": proxy} if proxy is not None else None,
            )
            try:
                context = await browser.new_context(service_workers="block")
                page = await context.new_page()
                yield _BrowserCatalogTransport(page)
            finally:
                await browser.close()
    except (Error, PlaywrightTimeout) as error:
        raise CatalogTransportError("TRANSPORT_FAILED") from error
