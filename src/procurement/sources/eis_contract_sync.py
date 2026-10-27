"""Bounded official by-number receipts for RGK and PRIZ, using the existing transport."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from procurement.sources.eis_contract_cards import CardSnapshot
from procurement.sources.eis_feed import parse_get_docs_ip_response
from procurement.sources.eis_feed_sync import (
    EisFeedTransport,
    EisHourSelection,
    EisSourceError,
    EisSyncError,
    _parsed_post,
    _request,
)
from procurement.sources.eis_number_sync import _number_request

MAX_COMPRESSED = 16 * 1024**2
MAX_EXPANDED = 32 * 1024**2


@dataclass(frozen=True)
class OfficialBundle:
    subsystem: str
    number: str
    requested_at: datetime
    checked_at: datetime
    request_id: str
    initial_sha256: str
    prepared_sha256: str
    responses: tuple[bytes, ...] = field(repr=False)
    archives: tuple[bytes, ...] = field(repr=False)
    selection_kind: Literal["BY_NUMBER", "BY_REGION"] = "BY_NUMBER"

    def validate(self) -> None:
        """Recheck retained response/UUID/complete-part evidence before projection."""
        identity_ok = (
            bool(re.fullmatch(r"[0-9]{19,23}", self.number))
            if self.selection_kind == "BY_NUMBER"
            else self.selection_kind == "BY_REGION"
            and bool(
                re.fullmatch(
                    r"[0-9]{1,2}/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{2}[+-][0-9]{2}:00", self.number
                )
            )
        )
        if (
            self.subsystem not in {"RGK", "PRIZ"}
            or not identity_ok
            or self.requested_at.utcoffset() is None
            or self.checked_at.utcoffset() is None
            or not self.requested_at <= self.checked_at
            or not 2 <= len(self.responses) <= 8
            or not 1 <= len(self.archives) <= 4
            or sum(map(len, self.archives)) > MAX_COMPRESSED
        ):
            raise ValueError("CONTRACT_BUNDLE_INVALID")
        replies = [parse_get_docs_ip_response(raw) for raw in self.responses]
        initial, prepared = replies[0], replies[-1]
        if (
            initial.source_sha256 != self.initial_sha256
            or initial.request_id != self.request_id
            or initial.kind != self.selection_kind
            or initial.state != "LINKS_PENDING"
            or prepared.source_sha256 != self.prepared_sha256
            or prepared.doc_request_uid != self.request_id
            or prepared.kind != "PREPARED"
            or prepared.state != "READY"
            or any(r.service != "IP" or r.source_mode != "PROD" for r in replies)
        ):
            raise ValueError("CONTRACT_RESPONSE_BINDING_INVALID")
        for reply in replies[1:]:
            if reply.kind != "PREPARED" or reply.doc_request_uid != self.request_id:
                raise ValueError("CONTRACT_RESPONSE_BINDING_INVALID")
        initial_uids = [
            parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower()
            for url in initial.archive_urls
        ]
        prepared_uids = [p.archive_uid for p in prepared.prepared_archives]
        if (
            len(set(initial_uids)) != len(initial_uids)
            or set(initial_uids) != set(prepared_uids)
            or len(initial_uids) != len(self.archives)
        ):
            raise ValueError("CONTRACT_PREPARED_PARTS_INCOMPLETE")

    def receipt(self) -> dict[str, object]:
        return {
            "subsystem": self.subsystem,
            "number": self.number,
            "selection_kind": self.selection_kind,
            "request_id": self.request_id,
            "requested_at": self.requested_at.isoformat(),
            "checked_at": self.checked_at.isoformat(),
            "initial_sha256": self.initial_sha256,
            "prepared_sha256": self.prepared_sha256,
            "archive_sha256": [hashlib.sha256(raw).hexdigest() for raw in self.archives],
            "scope": (
                "ALL_PARTS_OF_ONE_OFFICIAL_ADDRESSED_RESPONSE"
                if self.selection_kind == "BY_NUMBER"
                else "REGIONAL_CANDIDATE_DISCOVERY_NOT_A_COMPLETE_CONTRACT_HISTORY"
            ),
        }

    def xml_documents(self) -> tuple[tuple[str, bytes], ...]:
        result = []
        expanded = 0
        for raw in self.archives:
            with ZipFile(BytesIO(raw)) as archive:
                members = archive.infolist()
                expanded += sum(m.file_size for m in members)
                if (
                    len(members) > 1000
                    or expanded > MAX_EXPANDED
                    or len({m.filename for m in members}) != len(members)
                ):
                    raise ValueError("CONTRACT_ARCHIVE_LIMIT")
                for member in members:
                    if member.file_size > 4 * 1024**2 and self.selection_kind == "BY_REGION":
                        continue  # Discovery omission only; never an admissible contract receipt.
                    path = PurePosixPath(member.filename)
                    if (
                        member.is_dir()
                        or member.flag_bits & 1
                        or len(path.parts) != 1
                        or "\\" in member.filename
                        or not member.filename.endswith(".xml")
                        or not 0 < member.file_size <= 4 * 1024**2
                    ):
                        raise ValueError("CONTRACT_MEMBER_UNSAFE")
                    with archive.open(member) as stream:
                        content = stream.read(4 * 1024**2 + 1)
                    if len(content) != member.file_size:
                        raise ValueError("CONTRACT_MEMBER_SIZE")
                    if b"\0" in content or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", content, re.I):
                        raise ValueError("CONTRACT_XML_UNSAFE")
                    try:
                        content.decode("utf-8-sig")
                    except UnicodeError as error:
                        raise ValueError("CONTRACT_XML_ENCODING") from error
                    result.append((member.filename, content))
        return tuple(result)


class _RecordingTransport:
    def __init__(self, underlying: EisFeedTransport, token: str) -> None:
        self.transport, self.token = underlying, token.encode()
        self.responses: list[bytes] = []

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        status, content = await self.transport.post(xml)
        if status == 200 and 0 < len(content) <= 2 * 1024**2 and self.token not in content:
            self.responses.append(content)
        return status, content

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        return await self.transport.download(url, token)


async def fetch_official_bundle(
    transport: EisFeedTransport,
    token: str,
    *,
    subsystem: str,
    number: str | None = None,
    selection: EisHourSelection | None = None,
) -> OfficialBundle:
    """Require every prepared part; do not reinterpret NO_DATA as a completed history."""
    if subsystem not in {"PRIZ", "RGK"}:
        raise ValueError("CONTRACT_SUBSYSTEM_INVALID")
    if (number is None) == (selection is None) or (selection is not None and subsystem != "RGK"):
        raise ValueError("CONTRACT_SELECTION_INVALID")
    uid = str(uuid4())
    started = datetime.now(UTC)
    if selection is not None:
        request = ET.fromstring(_request(token, uid, selection=selection))
        number = (
            f"{selection.region}/{selection.day.isoformat()}/"
            f"{selection.hour:02d}{selection.utc_offset_hours:+03d}:00"
        )
        expected_kind = "BY_REGION"
        for node in request.iter():
            if node.tag == "documentType44":
                node.text = "contract"
    else:
        assert number is not None
        request = ET.fromstring(_number_request(token, uid, number))
        expected_kind = "BY_NUMBER"
    nodes = [node for node in request.iter() if node.tag == "subsystemType"]
    assert len(nodes) == 1
    nodes[0].text = subsystem
    recording = _RecordingTransport(transport, token)
    initial = await _parsed_post(
        recording, ET.tostring(request, encoding="utf-8", xml_declaration=True), token
    )
    if initial.state == "SERVICE_ERROR":
        raise EisSyncError(
            "CONTRACT_SOURCE_SERVICE_ERROR",
            source_error=EisSourceError("INITIAL", service_code=initial.error_code),
        )
    if (
        initial.service != "IP"
        or initial.kind != expected_kind
        or initial.source_mode != "PROD"
        or initial.request_id != uid
        or initial.state != "LINKS_PENDING"
        or not 1 <= len(initial.archive_urls) <= 4
    ):
        raise ValueError("CONTRACT_INITIAL_" + initial.state)
    prepared = None
    for _ in range(6):
        await asyncio.sleep(10)
        reply = await _parsed_post(
            recording, _request(token, str(uuid4()), original_request_id=uid), token
        )
        if reply.state == "SERVICE_ERROR":
            raise EisSyncError(
                "CONTRACT_SOURCE_SERVICE_ERROR",
                source_error=EisSourceError("PREPARED", service_code=reply.error_code),
            )
        if (
            reply.service != "IP"
            or reply.kind != "PREPARED"
            or reply.source_mode != "PROD"
            or reply.doc_request_uid != uid
        ):
            raise ValueError("CONTRACT_PREPARED_IDENTITY")
        if reply.state == "READY":
            prepared = reply
            break
        if reply.state not in {"PREPARING"}:
            raise ValueError("CONTRACT_PREPARED_" + reply.state)
    if prepared is None:
        raise ValueError("CONTRACT_PREPARATION_PENDING")
    initial_uids = [
        parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower()
        for url in initial.archive_urls
    ]
    parts = {p.archive_uid: p for p in prepared.prepared_archives}
    # preparedNotDownloadPartInfo is a READY part not yet downloaded by this
    # client; the accepted parser already unions it into prepared_archives.
    if len(set(initial_uids)) != len(initial_uids) or set(initial_uids) != set(parts):
        raise ValueError("CONTRACT_PREPARED_PARTS_INCOMPLETE")
    archives = []
    for archive_uid in initial_uids:
        status, content = await recording.download(parts[archive_uid].url, token)
        if (
            status != 200
            or not content.startswith(b"PK\x03\x04")
            or not 0 < len(content) <= 8 * 1024**2
            or token.encode() in content
        ):
            raise ValueError("CONTRACT_ARCHIVE_REJECTED")
        archives.append(content)
        if sum(len(a) for a in archives) > MAX_COMPRESSED:
            raise ValueError("CONTRACT_COMPRESSED_LIMIT")
    result = OfficialBundle(
        subsystem,
        number,
        started,
        datetime.now(UTC),
        uid,
        initial.source_sha256,
        prepared.source_sha256,
        tuple(recording.responses),
        tuple(archives),
        expected_kind,
    )
    result.xml_documents()  # All declared lengths, CRC and traversal guards before admission.
    result.validate()
    return result


class CardCaptureError(ValueError):
    """Safe public-card transport metadata, with no URL or raw exception in the message."""

    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        network_code: str | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        super().__init__(code)
        self.phase = "PUBLIC_CARD"
        self.http_status = http_status
        self.network_code = network_code
        self.retry_at = retry_at


async def capture_current_card(
    *, number: str, kind: Literal["CONTRACT", "EZK_DOCUMENTS", "EF_DOCUMENTS"]
) -> CardSnapshot:
    """Retain metadata absent from the old public HTML reader, under its shared cooldown.

    Fresh browser context, existing proxy and normal TLS. Callers own the global
    ingestion lease; a cooldown refusal is returned, never bypassed or slept through.
    """
    from procurement.sources.eis_contract_cards import (
        CONTRACT_PATH,
        DOCUMENTS_EA_PATH,
        DOCUMENTS_PATH,
        ORIGIN,
    )
    from procurement.sources.eis_public import _host_lease, _public_browser_proxy

    if not re.fullmatch(r"[0-9]{19,23}", number) or kind not in {
        "CONTRACT",
        "EZK_DOCUMENTS",
        "EF_DOCUMENTS",
    }:
        raise ValueError("CARD_CAPTURE_SELECTION_INVALID")
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright
    except ImportError as error:
        raise CardCaptureError("CARD_BROWSER_UNAVAILABLE") from error
    key, path = (
        ("reestrNumber", CONTRACT_PATH) if kind == "CONTRACT" else ("regNumber", DOCUMENTS_PATH)
    )
    if kind == "EF_DOCUMENTS":
        path = DOCUMENTS_EA_PATH
    url = f"{ORIGIN}{path}?{key}={number}"
    with _host_lease() as retry_at:
        if retry_at is not None:
            raise CardCaptureError("CARD_SOURCE_COOLDOWN", retry_at=retry_at)
        started = datetime.now(UTC)
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    timeout=15_000,
                    proxy=_public_browser_proxy(),
                )
                try:
                    page = await browser.new_page(accept_downloads=False)
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                    if response is None:
                        raise CardCaptureError("CARD_RESPONSE_ABSENT")
                    if response.status != 200:
                        raise CardCaptureError("CARD_HTTP_REJECTED", http_status=response.status)
                    if page.url != url or response.request.redirected_from is not None:
                        raise CardCaptureError("CARD_REDIRECT_UNSUPPORTED")
                    length = response.headers.get("content-length", "0") or "0"
                    if not re.fullmatch(r"[0-9]{1,10}", length):
                        raise CardCaptureError("CARD_RESPONSE_LENGTH_INVALID")
                    if int(length) > 4 * 1024**2:
                        raise CardCaptureError("CARD_RESPONSE_LIMIT")
                    content = await response.body()
                    if not 0 < len(content) <= 4 * 1024**2:
                        raise CardCaptureError("CARD_RESPONSE_LIMIT")
                    headers = tuple(
                        sorted(
                            (name, value)
                            for name, value in response.headers.items()
                            if name in {"date", "age", "content-type", "cache-control", "warning"}
                        )
                    )
                    return CardSnapshot(
                        url,
                        page.url,
                        response.status,
                        started,
                        datetime.now(UTC),
                        content,
                        headers,
                    )
                finally:
                    await browser.close()
        except (Error, TimeoutError) as error:
            from procurement.sources.eis_feed_sync import _NETWORK_CODES

            codes = re.findall(r"net::(ERR_[A-Z_]+)\b", str(error))
            code = next((value for value in codes if value in _NETWORK_CODES), None)
            code = code or ("TIMEOUT" if isinstance(error, TimeoutError) else "UNKNOWN")
            raise CardCaptureError("CARD_TRANSPORT_FAILED", network_code=code) from None
