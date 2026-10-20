"""Bounded official getDocsIP date/hour intake for 44-FZ auctions.

Each run handles one source window. Only a complete READY archive set can be
checkpointed; NO_DATA and transient source states remain explicitly unresolved.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree import ElementTree as ET

from procurement.sources.eis_browser import EisBrowserConfigError, eis_browser_proxy_server
from procurement.sources.eis_feed import (
    EisFeedContractError,
    EisFeedResponse,
    parse_get_docs_ip_response,
)
from procurement.sources.eis_feed_archive import (
    DEFAULT_NOTICE_TYPE,
    SUPPORTED_NOTICE_TYPES,
    EisFeedArchiveError,
)
from procurement.sources.eis_no_data_evidence import no_data_evidence_root, retain_no_data_reply
from procurement.sources.eis_notice_conflicts import (
    EisNoticeConflictDiagnosis,
    diagnose_notice_conflicts,
)
from procurement.sources.eis_rejected_evidence import (
    EisRejectedEvidence,
    RejectionReason,
    retain_rejected_window,
)
from procurement.sources.eis_variant_intake import (
    EisVariantIntakeReport,
    intake_notice_variants,
    variant_intake_failure,
)
from procurement.storage.eis_no_data_evidence import record_no_data_evidence
from procurement.storage.eis_notice_index import (
    MAX_WINDOW_ARCHIVES,
    MAX_WINDOW_COMPRESSED_BYTES,
    EisIndexConflict,
    EisReadyWindow,
    bind_ready_window,
    has_ingested_window,
    ingest_ready_window,
)
from procurement.storage.eis_notice_projection import read_reusable_notice_transport
from procurement.storage.eis_rejected_evidence import (
    record_notice_conflict_diagnosis,
    record_rejected_evidence,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from procurement.storage.repository import PostgresStorage

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
IP_NS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"
HOST = "https://int.zakupki.gov.ru"
ENDPOINT = f"{HOST}/eis-integration/services/getDocsIP"
WSDL = f"{ENDPOINT}?wsdl"
SOAP_ACTION = '"http://zakupki.gov.ru/fz44/queue/ws/get-docs-ip"'
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TOKEN = re.compile(r"^[A-Za-z0-9-]{16,128}$")


class EisSyncError(ValueError):
    """A non-sensitive source or configuration failure code."""


class EisRejectedWindowError(EisSyncError):
    """Original source conflict plus bounded retention metadata, never source bytes."""

    def __init__(
        self,
        reason: str,
        response_sha256: str,
        evidence: EisRejectedEvidence | None,
        audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"],
        diagnosis: EisNoticeConflictDiagnosis | None = None,
        diagnosis_audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] = "NOT_REQUIRED",
        variant_intake: EisVariantIntakeReport | None = None,
    ):
        super().__init__(reason)
        self.source_response_sha256 = response_sha256
        self.evidence = evidence
        self.audit_status = audit_status
        self.diagnosis = diagnosis
        self.diagnosis_audit_status = diagnosis_audit_status
        self.variant_intake = variant_intake or EisVariantIntakeReport()

    def safe_metadata(self) -> dict[str, object]:
        return {
            "reason": str(self),
            "source_response_sha256": self.source_response_sha256,
            "retention_status": self.evidence.status if self.evidence else "UNAVAILABLE",
            "retention_reason": self.evidence.retention_reason
            if self.evidence
            else "RETENTION_UNAVAILABLE",
            "manifest_sha256": self.evidence.manifest_sha256 if self.evidence else None,
            "audit_status": self.audit_status,
            "variant_intake": self.variant_intake.model_dump(mode="json"),
            "conflict_diagnosis": {
                **(
                    self.diagnosis.safe_summary()
                    if self.diagnosis
                    else {
                        "status": "UNAVAILABLE",
                        "coverage": "UNKNOWN",
                    }
                ),
                "audit_status": self.diagnosis_audit_status,
            },
        }


def rejection_error(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    window: EisReadyWindow,
    token: str,
    reason: RejectionReason,
) -> EisRejectedWindowError:
    if reason == "TRANSPORT_WINDOW_NOT_CANONICAL":
        try:
            receipt, reused_diagnosis = read_reusable_notice_transport(storage, company_id, window)
        except Exception as error:
            return EisRejectedWindowError(
                reason,
                window.response_sha256,
                None,
                "NOT_REQUIRED",
                diagnosis_audit_status="FAILED",
                variant_intake=variant_intake_failure("DIAGNOSIS", error),
            )
        return EisRejectedWindowError(
            reason,
            window.response_sha256,
            receipt.evidence,
            "RECORDED",
            reused_diagnosis,
            "RECORDED",
            intake_notice_variants(
                storage,
                company_id,
                receipt.evidence,
                reused_diagnosis,
                window.archives,
                actor_id=actor_id,
            ),
        )
    raw_root = os.environ.get("EIS_REJECTED_EVIDENCE_DIR")
    evidence = None
    audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] = "NOT_REQUIRED"
    variant_intake = EisVariantIntakeReport()
    try:
        evidence = retain_rejected_window(
            window,
            company_id=company_id,
            reason=reason,
            token=token,
            observed_at=datetime.now(UTC),
            root=Path(raw_root) if raw_root else None,
        )
        if evidence.status != "DISABLED":
            record_rejected_evidence(storage, company_id, evidence, actor_id=actor_id)
            audit_status = "RECORDED"
        if evidence.status == "FAILED":
            variant_intake = variant_intake_failure("RETENTION", RuntimeError())
    except Exception as error:
        # Failed retention/audit must not conceal the original source conflict.
        audit_status = "FAILED"
        variant_intake = variant_intake_failure("RETENTION", error)
    diagnosis = None
    diagnosis_audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] = "NOT_REQUIRED"
    if evidence and evidence.status == "RETAINED" and audit_status == "RECORDED":
        try:
            inspected = diagnose_notice_conflicts(window.archives, token)
            record_notice_conflict_diagnosis(
                storage,
                company_id,
                evidence,
                inspected,
                actor_id=actor_id,
            )
            diagnosis = inspected
            diagnosis_audit_status = "RECORDED"
        except Exception as error:
            # An incomplete diagnosis never conceals the original rejection.
            diagnosis_audit_status = "FAILED"
            variant_intake = variant_intake_failure("DIAGNOSIS", error)
    if diagnosis is not None and diagnosis_audit_status == "RECORDED":
        variant_intake = intake_notice_variants(
            storage, company_id, evidence, diagnosis, window.archives, actor_id=actor_id
        )
    return EisRejectedWindowError(
        reason,
        window.response_sha256,
        evidence,
        audit_status,
        diagnosis,
        diagnosis_audit_status,
        variant_intake,
    )


def _proxy_server() -> str | None:
    """Операторский маршрут браузера ЕИС; credentials в URL запрещены."""
    try:
        return eis_browser_proxy_server()
    except EisBrowserConfigError as error:
        raise EisSyncError("PROXY_CONFIG_INVALID") from error


@dataclass(frozen=True)
class EisHourSelection:
    region: str
    day: date
    hour: int
    utc_offset_hours: int
    document_type: str = DEFAULT_NOTICE_TYPE

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[0-9]{1,2}", self.region)
            or not 0 <= self.hour <= 23
            or not -12 <= self.utc_offset_hours <= 14
            or self.document_type not in SUPPORTED_NOTICE_TYPES
        ):
            raise ValueError("SOURCE_WINDOW_INVALID")

    @property
    def window_key(self) -> str:
        key = (
            f"getDocsIP/PRIZ/{self.region}/{self.day.isoformat()}/"
            f"{self.hour:02d}{self.utc_offset_hours:+03d}:00"
        )
        return key if self.document_type == DEFAULT_NOTICE_TYPE else f"{key}/{self.document_type}"


@dataclass(frozen=True)
class EisDateSelection:
    region: str
    day: date
    utc_offset_hours: int
    document_type: str = DEFAULT_NOTICE_TYPE

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[0-9]{1,2}", self.region)
            or not -12 <= self.utc_offset_hours <= 14
            or self.document_type not in SUPPORTED_NOTICE_TYPES
        ):
            raise ValueError("SOURCE_WINDOW_INVALID")

    @property
    def window_key(self) -> str:
        key = f"getDocsIP/PRIZ/{self.region}/{self.day.isoformat()}{self.utc_offset_hours:+03d}:00"
        return key if self.document_type == DEFAULT_NOTICE_TYPE else f"{key}/{self.document_type}"


EisSelection = EisHourSelection | EisDateSelection


@dataclass(frozen=True)
class EisHourSyncResult:
    window_key: str
    status: Literal["SYNCED", "SKIPPED", "NO_DATA", "PREPARING", "SERVICE_ERROR"]
    archive_count: int = 0
    notice_count: int = 0
    new_versions: int = 0
    new_events: int = 0
    source_error_code: int | None = None
    source_response_sha256: str | None = None
    corpus_coverage: str = "UNKNOWN"
    archive_bytes: int = 0
    no_data_retention_status: Literal["RETAINED", "DISABLED", "FAILED"] | None = None
    no_data_retention_reason: str | None = None
    no_data_manifest_sha256: str | None = None
    no_data_retention_audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] | None = None
    no_data_retention_audit_event_id: str | None = None


class EisFeedTransport(Protocol):
    async def post(self, xml: bytes) -> tuple[int, bytes]: ...

    async def download(self, url: str, token: str) -> tuple[int, bytes]: ...


def _request(
    token: str,
    request_id: str,
    *,
    selection: EisSelection | None = None,
    original_request_id: str | None = None,
) -> bytes:
    if not _TOKEN.fullmatch(token) or (selection is None) == (original_request_id is None):
        raise EisSyncError("REQUEST_CONFIG_INVALID")
    envelope = ET.Element(f"{{{SOAP_NS}}}Envelope")
    header = ET.SubElement(envelope, f"{{{SOAP_NS}}}Header")
    ET.SubElement(header, "individualPerson_token").text = token
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    method = "getDocsByOrgRegionRequest" if selection is not None else "getPreparedPartRequest"
    payload = ET.SubElement(body, f"{{{IP_NS}}}{method}")
    index = ET.SubElement(payload, "index")
    ET.SubElement(index, "id").text = request_id
    ET.SubElement(index, "createDateTime").text = datetime.now(UTC).isoformat()
    ET.SubElement(index, "mode").text = "PROD"
    if selection is not None:
        params = ET.SubElement(payload, "selectionParams")
        ET.SubElement(params, "orgRegion").text = selection.region
        ET.SubElement(params, "subsystemType").text = "PRIZ"
        ET.SubElement(params, "documentType44").text = selection.document_type
        period = ET.SubElement(params, "periodInfo")
        if isinstance(selection, EisHourSelection):
            one_hour = ET.SubElement(period, "oneHourInfo")
            ET.SubElement(one_hour, "date").text = selection.day.isoformat()
            ET.SubElement(one_hour, "fromHour").text = str(selection.hour)
            ET.SubElement(one_hour, "offsetTimeZone").text = f"{selection.utc_offset_hours:+d}"
        else:
            ET.SubElement(
                period, "exactDate"
            ).text = f"{selection.day.isoformat()}{selection.utc_offset_hours:+03d}:00"
    else:
        ET.SubElement(payload, "docRequestUid").text = original_request_id
    serialized = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    assert isinstance(serialized, bytes)
    return serialized


async def _parsed_post(transport: EisFeedTransport, xml: bytes, token: str) -> EisFeedResponse:
    reply, _ = await _parsed_post_raw(transport, xml, token)
    return reply


async def _parsed_post_raw(
    transport: EisFeedTransport, xml: bytes, token: str
) -> tuple[EisFeedResponse, bytes]:
    status, raw = await transport.post(xml)
    if status != 200 or len(raw) > MAX_RESPONSE_BYTES or token.encode() in raw:
        raise EisSyncError("SOURCE_RESPONSE_REJECTED")
    try:
        return parse_get_docs_ip_response(raw), raw
    except EisFeedContractError as error:
        raise EisSyncError("SOURCE_CONTRACT_CHANGED") from error


async def sync_eis_window(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    selection: EisSelection,
    token: str,
    transport: EisFeedTransport,
    *,
    refresh: bool = False,
    poll_attempts: int = 6,
    poll_delay_seconds: float = 10,
    archive_retry_attempts: int = 3,
    archive_retry_delay_seconds: float = 10,
) -> EisHourSyncResult:
    """Fetch one exact date or hour, fail closed on incomplete archives."""
    if (
        not company_id.strip()
        or not actor_id.strip()
        or not _TOKEN.fullmatch(token)
        or token in company_id
        or token in actor_id
    ):
        raise EisSyncError("SYNC_CONFIG_INVALID")
    if not 1 <= poll_attempts <= 20 or not 0 <= poll_delay_seconds <= 60:
        raise EisSyncError("POLL_CONFIG_INVALID")
    if not 1 <= archive_retry_attempts <= 5 or not 0 <= archive_retry_delay_seconds <= 60:
        raise EisSyncError("ARCHIVE_RETRY_CONFIG_INVALID")
    key = selection.window_key
    if not refresh and has_ingested_window(storage, company_id, key):
        return EisHourSyncResult(window_key=key, status="SKIPPED")
    request_id = str(uuid4())
    initial, initial_raw = await _parsed_post_raw(
        transport, _request(token, request_id, selection=selection), token
    )
    if (
        initial.service != "IP"
        or initial.kind != "BY_REGION"
        or initial.request_id != request_id
        or initial.source_mode != "PROD"
    ):
        raise EisSyncError("INITIAL_REQUEST_MISMATCH")
    if initial.state == "NO_DATA":
        evidence = retain_no_data_reply(
            initial_raw,
            initial,
            company_id=company_id,
            actor_id=actor_id,
            window_key=key,
            request_id=request_id,
            observed_at=datetime.now(UTC),
            token=token,
            root=no_data_evidence_root(),
        )
        audit_status: Literal["RECORDED", "FAILED", "NOT_REQUIRED"] = "NOT_REQUIRED"
        audit_id = None
        if evidence.status != "DISABLED":
            try:
                audit_id = record_no_data_evidence(storage, company_id, evidence, actor_id=actor_id)
                audit_status = "RECORDED"
            except Exception:
                # A valid source observation remains NO_DATA; retention/audit never close a window.
                audit_status = "FAILED"
        return EisHourSyncResult(
            window_key=key,
            status="NO_DATA",
            source_response_sha256=initial.source_sha256,
            no_data_retention_status=evidence.status,
            no_data_retention_reason=evidence.reason,
            no_data_manifest_sha256=evidence.manifest_sha256,
            no_data_retention_audit_status=audit_status,
            no_data_retention_audit_event_id=audit_id,
        )
    if initial.state == "SERVICE_ERROR":
        return EisHourSyncResult(
            window_key=key,
            status="SERVICE_ERROR",
            source_error_code=initial.error_code,
            source_response_sha256=initial.source_sha256,
        )
    if initial.state != "LINKS_PENDING":
        raise EisSyncError("INITIAL_STATE_INVALID")
    if len(initial.archive_urls) > MAX_WINDOW_ARCHIVES:
        raise EisSyncError("ARCHIVE_WINDOW_COUNT_LIMIT")
    prepared = None
    for attempt in range(poll_attempts):
        if attempt:
            await asyncio.sleep(poll_delay_seconds)
        reply = await _parsed_post(
            transport,
            _request(token, str(uuid4()), original_request_id=initial.request_id),
            token,
        )
        if (
            reply.kind != "PREPARED"
            or reply.doc_request_uid != initial.request_id
            or reply.source_mode != "PROD"
        ):
            raise EisSyncError("PREPARED_REQUEST_MISMATCH")
        if reply.state == "SERVICE_ERROR":
            return EisHourSyncResult(
                window_key=key,
                status="SERVICE_ERROR",
                source_error_code=reply.error_code,
                source_response_sha256=reply.source_sha256,
            )
        if reply.state == "READY":
            prepared = reply
            break
        if reply.state != "PREPARING":
            raise EisSyncError("PREPARED_STATE_INVALID")
    if prepared is None:
        return EisHourSyncResult(window_key=key, status="PREPARING")
    urls = tuple(item.url for item in prepared.prepared_archives)
    if len(urls) > MAX_WINDOW_ARCHIVES:
        raise EisSyncError("ARCHIVE_WINDOW_COUNT_LIMIT")
    downloaded: dict[str, bytes] = {}
    downloaded_bytes = 0
    for url in urls:
        for attempt in range(archive_retry_attempts):
            if attempt:
                await asyncio.sleep(archive_retry_delay_seconds)
            status, content = await transport.download(url, token)
            if status in {404, 503} and attempt + 1 < archive_retry_attempts:
                continue
            if status != 200:
                raise EisSyncError(f"ARCHIVE_DOWNLOAD_HTTP_{status}")
            if (
                not content.startswith(b"PK\x03\x04")
                or not 0 < len(content) <= MAX_ARCHIVE_BYTES
                or token.encode() in content
            ):
                raise EisSyncError("ARCHIVE_CONTENT_REJECTED")
            break
        downloaded_bytes += len(content)
        if downloaded_bytes > MAX_WINDOW_COMPRESSED_BYTES:
            raise EisSyncError("ARCHIVE_WINDOW_SIZE_LIMIT")
        downloaded[url] = content
    window = bind_ready_window(key, initial, prepared, downloaded)
    try:
        report = ingest_ready_window(storage, company_id, window, actor_id=actor_id)
    except (EisFeedArchiveError, EisIndexConflict) as error:
        if str(error) not in {
            "DUPLICATE_NOTICE_VERSION",
            "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
            "NOTICE_VERSION_CONFLICT",
            "TRANSPORT_WINDOW_NOT_CANONICAL",
        }:
            raise
        raise rejection_error(
            storage, company_id, actor_id, window, token, cast(RejectionReason, str(error))
        ) from None
    return EisHourSyncResult(
        window_key=key,
        status="SYNCED",
        archive_count=report.archive_count,
        notice_count=report.notice_count,
        new_versions=report.new_versions,
        new_events=report.new_events,
        source_response_sha256=initial.source_sha256,
        archive_bytes=downloaded_bytes,
    )


class _BrowserTransport:
    def __init__(self, page: Page) -> None:
        self.page = page

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        # Sequential worker + spacing stays below the documented SOAP request quota.
        await asyncio.sleep(2)
        argument = {"url": ENDPOINT, "xml": xml.decode("utf-8"), "action": SOAP_ACTION}
        async with self.page.expect_response(
            lambda response: response.url == ENDPOINT and response.request.method == "POST",
            timeout=30_000,
        ) as pending:
            await self.page.evaluate(
                """async ({url, xml, action}) => {
                    const response = await fetch(url, {
                        method: 'POST',
                        headers: {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': action},
                        body: xml
                    });
                    return response.status;
                }""",
                argument,
            )
        response = await pending.value
        return response.status, await response.body()

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        await asyncio.sleep(2)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in {
            "int.zakupki.gov.ru",
            "int44.zakupki.gov.ru",
            "int44-ttls-cert.zakupki.gov.ru",
        }:
            raise EisSyncError("ARCHIVE_URL_INVALID")
        async with self.page.expect_response(
            lambda response: response.url == url and response.request.method == "GET",
            timeout=40_000,
        ) as pending:
            await self.page.evaluate(
                """async ({url, token}) => {
                    const response = await fetch(url, {
                        headers: {'individualPerson_token': token}
                    });
                    return response.status;
                }""",
                {"url": url, "token": token},
            )
        response = await pending.value
        if int(response.headers.get("content-length", "0") or "0") > MAX_ARCHIVE_BYTES:
            raise EisSyncError("ARCHIVE_DOWNLOAD_REJECTED")
        return response.status, await response.body()


class _BrowserSession:
    """Lazy, sequential official transport with a worker-owned lifetime."""

    def __init__(self, stack: AsyncExitStack) -> None:
        self.stack = stack
        self.transport: _BrowserTransport | None = None

    async def _ready(self) -> _BrowserTransport:
        if self.transport is None:
            from playwright.async_api import async_playwright

            proxy_server = _proxy_server()
            playwright = await self.stack.enter_async_context(async_playwright())
            browser = await playwright.chromium.launch(
                headless=True,
                timeout=15_000,
                proxy={"server": proxy_server} if proxy_server is not None else None,
            )
            self.stack.push_async_callback(browser.close)
            page = await browser.new_page(accept_downloads=False)
            response = await page.goto(WSDL, wait_until="domcontentloaded", timeout=25_000)
            if response is None or response.status != 200 or not page.url.startswith(f"{HOST}/"):
                raise EisSyncError("SOURCE_WSDL_UNAVAILABLE")
            self.transport = _BrowserTransport(page)
        return self.transport

    async def _invoke(
        self, *, xml: bytes | None = None, url: str = "", token: str = ""
    ) -> tuple[int, bytes]:
        try:
            from playwright.async_api import Error, TimeoutError
        except ImportError as error:
            raise EisSyncError("BROWSER_DEPENDENCY_MISSING") from error
        try:
            transport = await self._ready()
            if xml is not None:
                return await transport.post(xml)
            return await transport.download(url, token)
        except (Error, TimeoutError) as error:
            raise EisSyncError("SOURCE_TRANSPORT_FAILED") from error

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        return await self._invoke(xml=xml)

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        return await self._invoke(url=url, token=token)


@asynccontextmanager
async def eis_browser_transport() -> AsyncIterator[EisFeedTransport]:
    """Reuse one official-origin browser in a bounded sequential worker pass."""
    async with AsyncExitStack() as stack:
        yield _BrowserSession(stack)


async def sync_eis_hour(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    selection: EisHourSelection,
    token: str,
    transport: EisFeedTransport,
    *,
    poll_attempts: int = 6,
    poll_delay_seconds: float = 10,
    archive_retry_attempts: int = 3,
    archive_retry_delay_seconds: float = 10,
) -> EisHourSyncResult:
    """Compatibility entry point for recurring hourly windows."""
    return await sync_eis_window(
        storage,
        company_id,
        actor_id,
        selection,
        token,
        transport,
        poll_attempts=poll_attempts,
        poll_delay_seconds=poll_delay_seconds,
        archive_retry_attempts=archive_retry_attempts,
        archive_retry_delay_seconds=archive_retry_delay_seconds,
    )


async def sync_eis_window_via_browser(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    selection: EisSelection,
    token: str,
    *,
    refresh: bool = False,
) -> EisHourSyncResult:
    """Use Chromium's normal TLS validation and official origin for one run."""
    if not refresh and has_ingested_window(storage, company_id, selection.window_key):
        return EisHourSyncResult(window_key=selection.window_key, status="SKIPPED")
    async with eis_browser_transport() as transport:
        return await sync_eis_window(
            storage, company_id, actor_id, selection, token, transport, refresh=refresh
        )


async def sync_eis_hour_via_browser(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    selection: EisHourSelection,
    token: str,
) -> EisHourSyncResult:
    """Compatibility entry point for recurring hourly windows."""
    return await sync_eis_window_via_browser(storage, company_id, actor_id, selection, token)
