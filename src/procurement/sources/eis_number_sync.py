"""Fetch exact 44-FZ notice bytes by EIS registry number, then index atomically."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4
from xml.etree import ElementTree as ET

from sqlalchemy import and_, select

from procurement.sources.eis_feed_sync import (
    HOST,
    IP_NS,
    MAX_ARCHIVE_BYTES,
    SOAP_NS,
    WSDL,
    EisFeedTransport,
    EisSyncError,
    _BrowserTransport,
    _parsed_post,
    _proxy_server,
    _request,
)
from procurement.storage.eis_notice_hold import assert_notice_source_usable
from procurement.storage.eis_notice_index import (
    MAX_WINDOW_COMPRESSED_BYTES,
    bind_ready_window,
    ingest_ready_window,
)
from procurement.storage.models import eis_notice_versions

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

_NUMBER = re.compile(r"^[0-9]{19,23}$")
_TOKEN = re.compile(r"^[A-Za-z0-9-]{16,128}$")


@dataclass(frozen=True)
class EisNumberSyncResult:
    purchase_number: str
    status: Literal["SYNCED", "NO_DATA", "PREPARING", "SERVICE_ERROR"]
    source_response_sha256: str | None = None
    archive_count: int = 0
    new_versions: int = 0
    latest_version_number: int | None = None
    latest_xml_sha256: str | None = None
    reason: str | None = None
    coverage: Literal["ONE_NUMBER_ONLY"] = "ONE_NUMBER_ONLY"


def _number_request(token: str, request_id: str, number: str) -> bytes:
    if not _TOKEN.fullmatch(token) or not _NUMBER.fullmatch(number):
        raise EisSyncError("NUMBER_REQUEST_INVALID")
    envelope = ET.Element(f"{{{SOAP_NS}}}Envelope")
    header = ET.SubElement(envelope, f"{{{SOAP_NS}}}Header")
    ET.SubElement(header, "individualPerson_token").text = token
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    payload = ET.SubElement(body, f"{{{IP_NS}}}getDocsByReestrNumberRequest")
    index = ET.SubElement(payload, "index")
    ET.SubElement(index, "id").text = request_id
    ET.SubElement(index, "createDateTime").text = datetime.now(UTC).isoformat()
    ET.SubElement(index, "mode").text = "PROD"
    params = ET.SubElement(payload, "selectionParams")
    ET.SubElement(params, "subsystemType").text = "PRIZ"
    ET.SubElement(params, "reestrNumber").text = number
    serialized = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    assert isinstance(serialized, bytes)
    return serialized


async def sync_eis_number(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    number: str,
    token: str,
    transport: EisFeedTransport,
    *,
    poll_attempts: int = 6,
    poll_delay_seconds: float = 10,
) -> EisNumberSyncResult:
    """One bounded official request; unsupported or incomplete XML never enters the index."""
    if not company_id.strip() or not actor_id.strip() or not _NUMBER.fullmatch(number):
        raise EisSyncError("NUMBER_REQUEST_INVALID")
    if not 1 <= poll_attempts <= 20 or not 0 <= poll_delay_seconds <= 60:
        raise EisSyncError("POLL_CONFIG_INVALID")
    request_id = str(uuid4())
    initial = await _parsed_post(transport, _number_request(token, request_id, number), token)
    if (
        initial.service != "IP"
        or initial.kind != "BY_NUMBER"
        or initial.request_id != request_id
        or initial.source_mode != "PROD"
    ):
        raise EisSyncError("NUMBER_RESPONSE_MISMATCH")
    if initial.state == "NO_DATA":
        return EisNumberSyncResult(number, "NO_DATA", initial.source_sha256)
    if initial.state == "SERVICE_ERROR":
        return EisNumberSyncResult(
            number, "SERVICE_ERROR", initial.source_sha256, reason="SOURCE_SERVICE_ERROR"
        )
    if initial.state != "LINKS_PENDING" or not 1 <= len(initial.archive_urls) <= 10:
        raise EisSyncError("NUMBER_ARCHIVE_SET_INVALID")
    prepared = None
    for attempt in range(poll_attempts):
        if attempt:
            await asyncio.sleep(poll_delay_seconds)
        reply = await _parsed_post(
            transport,
            _request(token, str(uuid4()), original_request_id=request_id),
            token,
        )
        if (
            reply.kind != "PREPARED"
            or reply.doc_request_uid != request_id
            or reply.source_mode != "PROD"
        ):
            raise EisSyncError("PREPARED_REQUEST_MISMATCH")
        if reply.state == "SERVICE_ERROR":
            return EisNumberSyncResult(
                number, "SERVICE_ERROR", initial.source_sha256, reason="SOURCE_SERVICE_ERROR"
            )
        if reply.state == "READY":
            prepared = reply
            break
        if reply.state != "PREPARING":
            raise EisSyncError("PREPARED_STATE_INVALID")
    if prepared is None:
        return EisNumberSyncResult(number, "PREPARING", initial.source_sha256)
    downloaded: dict[str, bytes] = {}
    total_bytes = 0
    for item in prepared.prepared_archives:
        status, content = await transport.download(item.url, token)
        if status != 200:
            raise EisSyncError("NUMBER_ARCHIVE_DOWNLOAD_FAILED")
        if (
            not content.startswith(b"PK\x03\x04")
            or not 0 < len(content) <= MAX_ARCHIVE_BYTES
            or token.encode() in content
        ):
            raise EisSyncError("NUMBER_ARCHIVE_CONTENT_REJECTED")
        total_bytes += len(content)
        if total_bytes > MAX_WINDOW_COMPRESSED_BYTES:
            raise EisSyncError("ARCHIVE_WINDOW_SIZE_LIMIT")
        downloaded[item.url] = content
    window = bind_ready_window(f"getDocsIP/PRIZ/by-number/{number}", initial, prepared, downloaded)
    report = ingest_ready_window(storage, company_id, window, actor_id=actor_id)
    with storage.transaction(company_id, consistent_read=True) as connection:
        latest = connection.execute(
            select(eis_notice_versions.c.version_number, eis_notice_versions.c.xml_sha256)
            .where(
                and_(
                    eis_notice_versions.c.company_id == company_id,
                    eis_notice_versions.c.purchase_number == number,
                )
            )
            .order_by(eis_notice_versions.c.version_number.desc())
            .limit(1)
        ).first()
        assert_notice_source_usable(connection, company_id, number, latest[0] if latest else 1)
    return EisNumberSyncResult(
        purchase_number=number,
        status="SYNCED",
        source_response_sha256=initial.source_sha256,
        archive_count=report.archive_count,
        new_versions=report.new_versions,
        latest_version_number=latest[0] if latest else None,
        latest_xml_sha256=latest[1] if latest else None,
    )


async def sync_eis_number_via_browser(
    storage: PostgresStorage, company_id: str, actor_id: str, number: str, token: str
) -> EisNumberSyncResult:
    """Use the registered token through the official origin and configured route."""
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright

        async with async_playwright() as playwright:
            proxy = _proxy_server()
            browser = await playwright.chromium.launch(
                headless=True,
                timeout=15_000,
                proxy={"server": proxy} if proxy is not None else None,
            )
            try:
                page = await browser.new_page(accept_downloads=False)
                response = await page.goto(WSDL, wait_until="domcontentloaded", timeout=25_000)
                if (
                    response is None
                    or response.status != 200
                    or not page.url.startswith(f"{HOST}/")
                ):
                    raise EisSyncError("SOURCE_WSDL_UNAVAILABLE")
                return await sync_eis_number(
                    storage, company_id, actor_id, number, token, _BrowserTransport(page)
                )
            finally:
                await browser.close()
    except ImportError as error:
        raise EisSyncError("BROWSER_DEPENDENCY_MISSING") from error
    except (Error, TimeoutError) as error:
        raise EisSyncError("SOURCE_TRANSPORT_FAILED") from error
