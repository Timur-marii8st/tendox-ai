"""Ограниченное чтение исторических XML по tenant и выбранному извещению."""

from __future__ import annotations

import hashlib
from datetime import datetime
from io import BytesIO
from typing import Literal
from zipfile import BadZipFile, ZipFile

from pydantic import AwareDatetime, Field, TypeAdapter
from sqlalchemy import func, select, tuple_

from procurement.sources.eis_feed_archive import COMPANION_TYPES, EisProcedureEvent
from procurement.sources.eis_procedure_state import resolve_procedure_state
from procurement.sources.eis_protocols import (
    MAX_XML_BYTES,
    SUPPORTED_PROTOCOL_TYPES,
    EisProtocolFacts,
    ProtocolModel,
    parse_protocol_facts,
)
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_hold import assert_notice_source_usable
from procurement.storage.models import eis_feed_archives, eis_notice_versions, eis_procedure_events
from procurement.storage.repository import PostgresStorage

MAX_EVENTS = 40
MAX_DOCUMENTS = 12
MAX_ARCHIVES = 4
MAX_COMPRESSED_BYTES = 8 * 1024**2
MAX_EXPANDED_BYTES = 32 * 1024**2
MAX_SELECTED_XML_BYTES = 16 * 1024**2
MAX_TOTAL_ROWS = 400
MAX_RESPONSE_BYTES = 1024**2
_EVENT_FIELDS = frozenset(EisProcedureEvent.__dataclass_fields__)


class EisHistoricalProtocolReport(ProtocolModel):
    company_id: str
    notice: NoticeDocumentRef
    checked_at: AwareDatetime
    linkage_scope: Literal["PURCHASE_NUMBER_ONLY"] = "PURCHASE_NUMBER_ONLY"
    notice_version_link: Literal["UNKNOWN"] = "UNKNOWN"
    application_status: Literal["FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]
    metadata_documents: int = Field(ge=0)
    uninterpreted_document_types: tuple[str, ...]
    documents: tuple[EisProtocolFacts, ...]
    source_requests: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    source_freshness: Literal["UNKNOWN"] = "UNKNOWN"
    profit: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"


def read_historical_protocols(
    storage: PostgresStorage, company_id: str, ref: NoticeDocumentRef, *, now: datetime
) -> EisHistoricalProtocolReport:
    """Читать только сохранённые bytes; не изменять индекс и не обращаться к ЕИС."""
    if not company_id.strip() or now.utcoffset() is None:
        raise ValueError("PROTOCOL_REQUEST_INVALID")
    a, n, e = eis_feed_archives, eis_notice_versions, eis_procedure_events
    with storage.transaction(company_id, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout = '20s'")
        conn.exec_driver_sql("SET LOCAL lock_timeout = '2s'")
        assert_notice_source_usable(conn, company_id, ref.purchase_number, ref.version_number)
        notice = (
            conn.execute(
                select(n.c.xml_sha256, n.c.deadline).where(
                    n.c.company_id == company_id,
                    n.c.purchase_number == ref.purchase_number,
                    n.c.version_number == ref.version_number,
                )
            )
            .mappings()
            .one_or_none()
        )
        if notice is None or notice["xml_sha256"] != ref.notice_xml_sha256:
            raise ValueError("PROTOCOL_NOTICE_NOT_FOUND_OR_MISMATCH")
        rows = (
            conn.execute(
                select(e)
                .where(e.c.company_id == company_id, e.c.purchase_number == ref.purchase_number)
                .order_by(e.c.document_type, e.c.xml_sha256)
                .limit(MAX_EVENTS + 1)
            )
            .mappings()
            .all()
        )
        if len(rows) > MAX_EVENTS:
            raise ValueError("PROTOCOL_EVENT_LIMIT")
        events = tuple(
            TypeAdapter(EisProcedureEvent).validate_python({key: row[key] for key in _EVENT_FIELDS})
            for row in rows
        )
        selected = [row for row in rows if row["document_type"] in SUPPORTED_PROTOCOL_TYPES]
        if len(selected) > MAX_DOCUMENTS:
            raise ValueError("PROTOCOL_DOCUMENT_LIMIT")
        keys = {
            (row["window_key"], row["response_sha256"], row["archive_sha256"]) for row in selected
        }
        if len(keys) > MAX_ARCHIVES:
            raise ValueError("PROTOCOL_ARCHIVE_LIMIT")
        archive_where = (
            a.c.company_id == company_id,
            tuple_(a.c.window_key, a.c.response_sha256, a.c.archive_sha256).in_(sorted(keys)),
        )
        # Check sizes before fetching bytea; no unbounded history/source read.
        sizes = (
            conn.execute(
                select(func.octet_length(a.c.content)).where(*archive_where).limit(MAX_ARCHIVES + 1)
            )
            .scalars()
            .all()
            if keys
            else []
        )
        if len(sizes) != len(keys) or sum(sizes) > MAX_COMPRESSED_BYTES:
            raise ValueError("PROTOCOL_ARCHIVE_SIZE_OR_BINDING_INVALID")
        archives = (
            conn.execute(select(a).where(*archive_where).limit(MAX_ARCHIVES + 1)).mappings().all()
            if keys
            else []
        )
    documents = []
    expanded_bytes = selected_bytes = total_rows = response_bytes = 0
    for archive in archives:
        raw = bytes(archive["content"])
        if hashlib.sha256(raw).hexdigest() != archive["archive_sha256"]:
            raise ValueError("PROTOCOL_ARCHIVE_SHA_MISMATCH")
        members = [
            row
            for row in selected
            if (row["window_key"], row["response_sha256"], row["archive_sha256"])
            == (archive["window_key"], archive["response_sha256"], archive["archive_sha256"])
        ]
        try:
            with ZipFile(BytesIO(raw)) as zipped:
                infos = zipped.infolist()
                names = [info.filename for info in infos]
                expanded_bytes += sum(info.file_size for info in infos)
                if (
                    len(infos) > 1000
                    or len(set(names)) != len(names)
                    or expanded_bytes > MAX_EXPANDED_BYTES
                    or any(
                        info.flag_bits & 1
                        or info.is_dir()
                        or "/" in info.filename
                        or "\\" in info.filename
                        or not info.filename.lower().endswith(".xml")
                        for info in infos
                    )
                ):
                    raise ValueError("PROTOCOL_ARCHIVE_UNSAFE")
                by_name = {info.filename: info for info in infos}
                for row in members:
                    info = by_name.get(row["source_member"])
                    if info is None or info.file_size > MAX_XML_BYTES:
                        raise ValueError("PROTOCOL_MEMBER_MISSING_OR_OVERSIZE")
                    selected_bytes += info.file_size
                    if selected_bytes > MAX_SELECTED_XML_BYTES:
                        raise ValueError("PROTOCOL_XML_TOTAL_LIMIT")
                    xml = zipped.read(info)
                    event = TypeAdapter(EisProcedureEvent).validate_python(
                        {key: row[key] for key in _EVENT_FIELDS}
                    )
                    facts = parse_protocol_facts(xml, event)
                    total_rows += len(facts.applications)
                    if total_rows > MAX_TOTAL_ROWS:
                        raise ValueError("PROTOCOL_TOTAL_APPLICATION_LIMIT")
                    # Per-document serialization is bounded by names/fields/rows;
                    # reject cumulative output before assembling the full report.
                    response_bytes += len(facts.model_dump_json().encode())
                    if response_bytes > MAX_RESPONSE_BYTES - 64 * 1024:
                        raise ValueError("PROTOCOL_RESPONSE_LIMIT")
                    documents.append(facts)
        except (BadZipFile, KeyError, RuntimeError) as error:
            raise ValueError("PROTOCOL_ARCHIVE_INVALID") from error
    if len(documents) != len(selected):
        raise ValueError("PROTOCOL_DOCUMENT_BINDING_MISMATCH")
    state = resolve_procedure_state(events, purchase_number=ref.purchase_number, now=now)
    expired = notice["deadline"] is not None and notice["deadline"] <= now
    result = EisHistoricalProtocolReport(
        company_id=company_id,
        notice=ref,
        checked_at=now,
        application_status="FAIL" if expired or state.application_status == "FAIL" else "UNKNOWN",
        reasons=tuple(state.reasons) + (("DEADLINE_EXPIRED",) if expired else ()),
        metadata_documents=sum(row["document_type"] in COMPANION_TYPES for row in rows),
        uninterpreted_document_types=tuple(
            sorted(
                {
                    row["document_type"]
                    for row in rows
                    if row["document_type"] in COMPANION_TYPES
                    and row["document_type"] not in SUPPORTED_PROTOCOL_TYPES
                }
            )
        ),
        documents=tuple(
            sorted(documents, key=lambda item: (item.source.document_type, item.source.xml_sha256))
        ),
    )
    if len(result.model_dump_json().encode()) > MAX_RESPONSE_BYTES:
        raise ValueError("PROTOCOL_RESPONSE_LIMIT")
    return result
