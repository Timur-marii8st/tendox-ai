"""Bounded by-number intake for the two explicitly admitted 223-FZ families."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from uuid import uuid4
from xml.etree import ElementTree as ET

from sqlalchemy import select

from procurement.sources.eis_223_window_limits import MAX_ARCHIVE_BYTES, MAX_NOTICE_COMPRESSED_BYTES
from procurement.sources.eis_feed_sync import (
    IP_NS,
    SOAP_NS,
    EisFeedTransport,
    EisSyncError,
    _parsed_post,
    _request,
)
from procurement.sources.eis_number_sync import EisNumberSyncResult
from procurement.storage.eis_223_index import bind_notice223_window, ingest_notice223_window
from procurement.storage.models import eis_223_notice_versions
from procurement.storage.repository import PostgresStorage

FAMILIES = {"purchaseNoticeKESMBO", "purchaseNoticeZPESMBO"}


def number_request(token: str, uid: str, number: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token) or not re.fullmatch(r"[0-9]{11}", number):
        raise EisSyncError("NUMBER_REQUEST_INVALID")
    envelope = ET.Element(f"{{{SOAP_NS}}}Envelope")
    header = ET.SubElement(envelope, f"{{{SOAP_NS}}}Header")
    ET.SubElement(header, "individualPerson_token").text = token
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    payload = ET.SubElement(body, f"{{{IP_NS}}}getDocsByReestrNumberRequest")
    index = ET.SubElement(payload, "index")
    ET.SubElement(index, "id").text = uid
    ET.SubElement(index, "createDateTime").text = datetime.now(UTC).isoformat()
    ET.SubElement(index, "mode").text = "PROD"
    selection = ET.SubElement(payload, "selectionParams")
    ET.SubElement(selection, "subsystemType").text = "RI223"
    ET.SubElement(selection, "reestrNumber").text = number
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


async def sync_223_number(
    storage: PostgresStorage,
    company: str,
    actor: str,
    number: str,
    family: str,
    token: str,
    transport: EisFeedTransport,
) -> EisNumberSyncResult:
    """Fetch and ingest entire bound source set; mixed documents remain rejected."""
    if family not in FAMILIES or not company.strip() or not actor.strip():
        raise EisSyncError("NUMBER_SCOPE_INVALID")
    uid = str(uuid4())
    initial = await _parsed_post(transport, number_request(token, uid, number), token)
    if (
        initial.service != "IP"
        or initial.kind != "BY_NUMBER"
        or initial.request_id != uid
        or initial.source_mode != "PROD"
    ):
        raise EisSyncError("NUMBER_RESPONSE_MISMATCH")
    if initial.state in {"NO_DATA", "SERVICE_ERROR"}:
        return EisNumberSyncResult(number, initial.state, initial.source_sha256)
    if initial.state != "LINKS_PENDING":
        raise EisSyncError("NUMBER_ARCHIVE_SET_INVALID")
    prepared = None
    for _ in range(4):
        await asyncio.sleep(10)
        request_id = str(uuid4())
        reply = await _parsed_post(
            transport, _request(token, request_id, original_request_id=uid), token
        )
        if (
            reply.service != "IP"
            or reply.kind != "PREPARED"
            or reply.source_mode != "PROD"
            or reply.doc_request_uid != uid
            or reply.request_id != request_id
        ):
            raise EisSyncError("PREPARED_REQUEST_MISMATCH")
        if reply.state == "SERVICE_ERROR":
            return EisNumberSyncResult(number, "SERVICE_ERROR", initial.source_sha256)
        if reply.state == "READY":
            prepared = reply
            break
        if reply.state != "PREPARING":
            raise EisSyncError("PREPARED_STATE_INVALID")
    if prepared is None:
        return EisNumberSyncResult(number, "PREPARING", initial.source_sha256)
    key = f"getDocsIP/RI223/by-number/{number}/{family}"
    bind_notice223_window(
        key, initial, prepared, {ref.url: b"preflight" for ref in prepared.prepared_archives}
    )
    downloaded: dict[str, bytes] = {}
    size = 0
    for ref in prepared.prepared_archives:
        status, raw = await transport.download(ref.url, token)
        if status != 200 or not raw or len(raw) > MAX_ARCHIVE_BYTES or token.encode() in raw:
            raise EisSyncError("ARCHIVE_CONTENT_REJECTED")
        size += len(raw)
        if size > MAX_NOTICE_COMPRESSED_BYTES:
            raise EisSyncError("WINDOW_BYTES_LIMIT")
        downloaded[ref.url] = raw
    ready = bind_notice223_window(key, initial, prepared, downloaded)
    report = ingest_notice223_window(storage, company, ready, actor_id=actor)
    with storage.transaction(company, consistent_read=True) as conn:
        latest = conn.execute(
            select(eis_223_notice_versions.c.version_number, eis_223_notice_versions.c.xml_sha256)
            .where(
                eis_223_notice_versions.c.company_id == company,
                eis_223_notice_versions.c.purchase_number == number,
            )
            .order_by(eis_223_notice_versions.c.version_number.desc())
            .limit(1)
        ).first()
    if latest is None:
        raise EisSyncError("NOTICE_READBACK_MISSING")
    return EisNumberSyncResult(
        number,
        "SYNCED",
        initial.source_sha256,
        report.archive_count,
        report.new_versions,
        latest[0],
        latest[1],
    )
