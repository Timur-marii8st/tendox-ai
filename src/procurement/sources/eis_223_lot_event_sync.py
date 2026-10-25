"""Bounded public RI223 purchase-lot-cancellation fetch without persistence."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.eis_223_archive import MAX_ARCHIVE_BYTES
from procurement.sources.eis_223_lot_events import (
    EVENT_TYPE as LOT_EVENT_TYPE,
)
from procurement.sources.eis_223_lot_events import (
    Eis223LotEventArchiveInspection,
    inspect_purchase_lot_cancellation_archive,
)
from procurement.sources.eis_223_regions import validate_region_code
from procurement.sources.eis_feed import EisFeedResponse, validate_eis_archive_url
from procurement.sources.eis_feed_sync import (
    EisFeedTransport,
    EisSourceError,
    EisSyncError,
    PreparedWait,
    _parsed_post,
    _request,
)

_WINDOW = re.compile(
    r"^getDocsIP/RI223/(?P<region>(?:0[1-9]|[1-9][0-9]))/"
    r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})\+03:00/"
    r"purchaseLotCancellation$"
)
_TOKEN = re.compile(r"^[A-Za-z0-9-]{16,128}$")
_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_IP_NS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"


class EventSyncModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Eis223LotEventReadyWindow(EventSyncModel):
    window_key: str
    response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prepared_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archives: tuple[bytes, ...] = Field(min_length=1, max_length=2)
    archive_urls: tuple[str, ...] = Field(min_length=1, max_length=2)


@dataclass(frozen=True)
class Eis223LotEventObservation:
    status: Literal["SYNCED", "NO_DATA", "PREPARING", "SERVICE_ERROR"]
    response_sha256: str
    window: Eis223LotEventReadyWindow | None = None
    source_error: EisSourceError | None = None


def lot_event_window_key(day: date, *, region: str = "50") -> str:
    return (
        f"getDocsIP/RI223/{validate_region_code(region)}/{day.isoformat()}+03:00/{LOT_EVENT_TYPE}"
    )


def purchase_lot_cancellation_request(
    token: str, request_id: str, day: date, *, region: str = "50"
) -> bytes:
    """Build the exact public/actual NSI item 80 request."""
    if not _TOKEN.fullmatch(token):
        raise EisSyncError("REQUEST_CONFIG_INVALID")
    region = validate_region_code(region)
    try:
        identifier = str(UUID(request_id))
    except ValueError as error:
        raise EisSyncError("REQUEST_ID_INVALID") from error
    envelope = ET.Element(f"{{{_SOAP_NS}}}Envelope")
    ET.SubElement(
        ET.SubElement(envelope, f"{{{_SOAP_NS}}}Header"), "individualPerson_token"
    ).text = token
    payload = ET.SubElement(
        ET.SubElement(envelope, f"{{{_SOAP_NS}}}Body"),
        f"{{{_IP_NS}}}getDocsByOrgRegionRequest",
    )
    index = ET.SubElement(payload, "index")
    for key, value in (
        ("id", identifier),
        ("createDateTime", datetime.now(UTC).isoformat()),
        ("mode", "PROD"),
    ):
        ET.SubElement(index, key).text = value
    params = ET.SubElement(payload, "selectionParams")
    for key, value in (
        ("orgRegion", region),
        ("subsystemType", "RI223"),
        ("documentType223", LOT_EVENT_TYPE),
    ):
        ET.SubElement(params, key).text = value
    ET.SubElement(ET.SubElement(params, "periodInfo"), "exactDate").text = (
        day.isoformat() + "+03:00"
    )
    serialized = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    assert isinstance(serialized, bytes)
    return serialized


def bind_purchase_lot_cancellation_window(
    window_key: str,
    initial: EisFeedResponse,
    prepared: EisFeedResponse,
    downloaded: dict[str, bytes],
) -> Eis223LotEventReadyWindow:
    match = _WINDOW.fullmatch(window_key)
    if match is None:
        raise EisSyncError("WINDOW_INVALID")
    date.fromisoformat(match["day"])
    if (
        initial.service != "IP"
        or initial.kind != "BY_REGION"
        or initial.state != "LINKS_PENDING"
        or initial.source_mode != "PROD"
        or prepared.service != "IP"
        or prepared.kind != "PREPARED"
        or prepared.state != "READY"
        or prepared.source_mode != "PROD"
        or initial.request_id != prepared.doc_request_uid
    ):
        raise EisSyncError("SOURCE_BINDING_INVALID")
    initial_uids: list[str] = []
    for url in initial.archive_urls:
        validate_eis_archive_url(url, doc_request_uid=initial.request_id)
        initial_uids.append(
            parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower()
        )
    references = prepared.prepared_archives
    if (
        not 1 <= len(initial_uids) <= 2
        or len(set(initial_uids)) != len(initial_uids)
        or len({item.archive_uid for item in references}) != len(references)
        or set(initial_uids) != {item.archive_uid for item in references}
        or set(downloaded) != {item.url for item in references}
    ):
        raise EisSyncError("ARCHIVE_SET_MISMATCH")
    by_uid = {item.archive_uid: item.url for item in references}
    for uid, url in by_uid.items():
        validate_eis_archive_url(url, doc_request_uid=initial.request_id)
        if parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower() != uid:
            raise EisSyncError("ARCHIVE_UID_MISMATCH")
    urls = tuple(by_uid[uid] for uid in initial_uids)
    return Eis223LotEventReadyWindow(
        window_key=window_key,
        response_sha256=initial.source_sha256,
        prepared_sha256=prepared.source_sha256,
        archive_urls=urls,
        archives=tuple(downloaded[url] for url in urls),
    )


def preflight_purchase_lot_cancellation_window(
    company: str, window: Eis223LotEventReadyWindow
) -> tuple[Eis223LotEventArchiveInspection, ...]:
    match = _WINDOW.fullmatch(window.window_key)
    if match is None or len(window.archives) != len(window.archive_urls):
        raise EisSyncError("WINDOW_INVALID")
    date.fromisoformat(match["day"])
    if sum(map(len, window.archives)) > 32 * 1024 * 1024:
        raise EisSyncError("WINDOW_BYTES_LIMIT")
    if len(set(window.archive_urls)) != len(window.archive_urls):
        raise EisSyncError("ARCHIVE_URL_DUPLICATE")
    for url in window.archive_urls:
        validate_eis_archive_url(url)
    inspections = tuple(
        inspect_purchase_lot_cancellation_archive(
            raw,
            company_id=company,
            source_response_sha256=window.response_sha256,
            source_locator=window.window_key,
        )
        for raw in window.archives
    )
    if len({item.archive_sha256 for item in inspections}) != len(inspections):
        raise EisSyncError("ARCHIVE_DIGEST_DUPLICATE")
    variants: set[tuple[str | None, str]] = set()
    for inspection in inspections:
        for event in inspection.records:
            identity = (event.event_guid.value, event.xml_sha256)
            if identity in variants:
                raise EisSyncError("EVENT_VARIANT_DUPLICATE")
            variants.add(identity)
    return inspections


async def fetch_purchase_lot_cancellation_day(
    company: str,
    day: date,
    token: str,
    transport: EisFeedTransport,
    *,
    region: str = "50",
    poll_attempts: int = 4,
    poll_delay_seconds: float = 10,
    prepared_wait: PreparedWait | None = None,
) -> Eis223LotEventObservation:
    region = validate_region_code(region)
    if not 1 <= poll_attempts <= 4 or not 0 <= poll_delay_seconds <= 10:
        raise EisSyncError("POLL_CONFIG_INVALID")
    key = lot_event_window_key(day, region=region)
    uid = str(uuid4())
    initial = await _parsed_post(
        transport,
        purchase_lot_cancellation_request(token, uid, day, region=region),
        token,
    )
    if (
        initial.service != "IP"
        or initial.kind != "BY_REGION"
        or initial.request_id != uid
        or initial.source_mode != "PROD"
    ):
        raise EisSyncError("INITIAL_REQUEST_MISMATCH")
    if initial.state in {"NO_DATA", "SERVICE_ERROR"}:
        return Eis223LotEventObservation(
            initial.state,
            initial.source_sha256,
            source_error=(
                EisSourceError("INITIAL", service_code=initial.error_code)
                if initial.state == "SERVICE_ERROR"
                else None
            ),
        )
    if initial.state != "LINKS_PENDING":
        raise EisSyncError("INITIAL_STATE_INVALID")
    prepared: EisFeedResponse | None = None
    for _ in range(poll_attempts):
        await (prepared_wait or asyncio.sleep)(poll_delay_seconds)
        poll_uid = str(uuid4())
        reply = await _parsed_post(
            transport, _request(token, poll_uid, original_request_id=uid), token
        )
        if (
            reply.service != "IP"
            or reply.kind != "PREPARED"
            or reply.source_mode != "PROD"
            or reply.doc_request_uid != uid
            or reply.request_id != poll_uid
        ):
            raise EisSyncError("PREPARED_REQUEST_MISMATCH")
        if reply.state == "SERVICE_ERROR":
            return Eis223LotEventObservation(
                "SERVICE_ERROR",
                reply.source_sha256,
                source_error=EisSourceError("PREPARED", service_code=reply.error_code),
            )
        if reply.state == "PREPARING":
            prepared = reply
            continue
        if reply.state != "READY":
            raise EisSyncError("PREPARED_STATE_INVALID")
        prepared = reply
        bind_purchase_lot_cancellation_window(
            key, initial, prepared, {ref.url: b"preflight" for ref in prepared.prepared_archives}
        )
        downloaded: dict[str, bytes] = {}
        for ref in prepared.prepared_archives:
            status, raw = await transport.download(ref.url, token)
            if status != 200 or not raw or len(raw) > MAX_ARCHIVE_BYTES or token.encode() in raw:
                raise EisSyncError(
                    "ARCHIVE_CONTENT_REJECTED",
                    source_error=EisSourceError(
                        "ARCHIVE",
                        http_status=status if 100 <= status <= 599 else None,
                        category=(
                            "HTTP_STATUS"
                            if status != 200
                            else "RESPONSE_EMPTY"
                            if not raw
                            else "RESPONSE_SIZE"
                            if len(raw) > MAX_ARCHIVE_BYTES
                            else "TOKEN_REFLECTION"
                        ),
                    ),
                )
            downloaded[ref.url] = raw
        ready = bind_purchase_lot_cancellation_window(key, initial, prepared, downloaded)
        preflight_purchase_lot_cancellation_window(company, ready)
        for raw in ready.archives:
            with ZipFile(BytesIO(raw)) as archive:
                if any(token.encode() in archive.read(member) for member in archive.infolist()):
                    raise EisSyncError("XML_TOKEN_REFLECTION_REJECTED")
        return Eis223LotEventObservation("SYNCED", initial.source_sha256, ready)
    assert prepared is not None
    return Eis223LotEventObservation("PREPARING", prepared.source_sha256)
