"""Fetch one explicitly admitted 223 family/date; no partial window is published."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Literal
from uuid import uuid4
from zipfile import ZipFile

from procurement.sources.eis_223_archive import (
    DOCUMENT_TYPE,
    SUPPORTED_DOCUMENT_TYPES,
    Eis223DocumentType,
    notice223_request,
)
from procurement.sources.eis_223_regions import validate_region_code
from procurement.sources.eis_223_window_limits import (
    MAX_ARCHIVE_BYTES,
    MAX_NOTICE_COMPRESSED_BYTES,
)
from procurement.sources.eis_feed_sync import (
    EisFeedTransport,
    EisSourceError,
    EisSyncError,
    PreparedWait,
    _parsed_post,
    _request,
)
from procurement.storage.eis_223_index import (
    Eis223ReadyWindow,
    bind_notice223_window,
    preflight_notice223_window,
)


@dataclass(frozen=True)
class Eis223Observation:
    status: Literal["SYNCED", "NO_DATA", "PREPARING", "SERVICE_ERROR"]
    response_sha256: str
    window: Eis223ReadyWindow | None = None
    source_error: EisSourceError | None = None


@dataclass(frozen=True)
class Eis223RefreshTarget:
    day: date
    document_type: Eis223DocumentType
    region: str = "50"

    def __post_init__(self) -> None:
        validate_region_code(self.region)


def window_key(
    day: date,
    document_type: Eis223DocumentType = DOCUMENT_TYPE,
    *,
    region: str = "50",
) -> str:
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise EisSyncError("DOCUMENT_TYPE_UNSUPPORTED")
    return f"getDocsIP/RI223/{validate_region_code(region)}/{day.isoformat()}+03:00/{document_type}"


async def fetch_notice223_day(
    company: str,
    day: date,
    token: str,
    transport: EisFeedTransport,
    *,
    region: str = "50",
    document_type: Eis223DocumentType = DOCUMENT_TYPE,
    poll_attempts: int = 4,
    poll_delay_seconds: float = 10,
    prepared_wait: PreparedWait | None = None,
) -> Eis223Observation:
    region = validate_region_code(region)
    key = window_key(day, document_type, region=region)
    if not 1 <= poll_attempts <= 4 or not 0 <= poll_delay_seconds <= 10:
        raise EisSyncError("POLL_CONFIG_INVALID")
    uid = str(uuid4())
    initial = await _parsed_post(
        transport,
        notice223_request(token, uid, region, day, document_type=document_type),
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
        return Eis223Observation(
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
    for _ in range(poll_attempts):
        await (prepared_wait or asyncio.sleep)(poll_delay_seconds)
        poll_uid = str(uuid4())
        prepared = await _parsed_post(
            transport,
            _request(token, poll_uid, original_request_id=uid),
            token,
        )
        if (
            prepared.service != "IP"
            or prepared.kind != "PREPARED"
            or prepared.source_mode != "PROD"
            or prepared.doc_request_uid != uid
            or prepared.request_id != poll_uid
        ):
            raise EisSyncError("PREPARED_REQUEST_MISMATCH")
        if prepared.state == "SERVICE_ERROR":
            return Eis223Observation(
                "SERVICE_ERROR",
                prepared.source_sha256,
                source_error=EisSourceError("PREPARED", service_code=prepared.error_code),
            )
        if prepared.state == "PREPARING":
            continue
        # Verify the full set and every URL before any GET. Placeholder bytes are never ingested.
        bind_notice223_window(
            key,
            initial,
            prepared,
            {ref.url: b"preflight" for ref in prepared.prepared_archives},
        )
        downloaded = {}
        compressed_bytes = 0
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
            compressed_bytes += len(raw)
            if compressed_bytes > MAX_NOTICE_COMPRESSED_BYTES:
                raise EisSyncError("WINDOW_BYTES_LIMIT")
            downloaded[ref.url] = raw
        ready = bind_notice223_window(key, initial, prepared, downloaded)
        preflight_notice223_window(company, ready)
        # Inspection above establishes safe expansion bounds before secret reflection checking.
        for raw in ready.archives:
            with ZipFile(BytesIO(raw)) as archive:
                if any(token.encode() in archive.read(member) for member in archive.infolist()):
                    raise EisSyncError("XML_TOKEN_REFLECTION_REJECTED")
        return Eis223Observation("SYNCED", initial.source_sha256, ready)
    return Eis223Observation("PREPARING", prepared.source_sha256)
