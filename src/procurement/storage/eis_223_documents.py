"""Exact tenant 223 document receipts; status reads never fetch or analyze."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_223_documents import (
    Manifest223,
    Manifest223Item,
    Notice223DocumentRef,
    download_public223_attachment,
    manifest223,
)
from procurement.sources.eis_223_events import Eis223RejectionState
from procurement.sources.eis_223_lot_event_policy import Eis223LotCancellationState
from procurement.sources.eis_223_policy import deadline223, unavailable223
from procurement.sources.eis_analysis import DocumentAnalysis, analyze_document
from procurement.sources.eis_corpus import resource_gate
from procurement.storage.eis_223_events import read_event223_states
from procurement.storage.eis_223_lot_events import read_lot_event223_states
from procurement.storage.models import (
    audit_events,
    eis_223_document_attempts,
    eis_223_document_jobs,
    eis_223_document_receipts,
    eis_223_notice_versions,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection, Table
    from sqlalchemy.sql.elements import ColumnElement

    from procurement.storage.repository import PostgresStorage


class Document223StatusItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reference: Manifest223Item
    received: bool
    analysis: DocumentAnalysis | None
    attempt_count: int = 0
    last_failure: str | None = None


class Document223Status(BaseModel):
    cancellation_state: Eis223RejectionState | None = None
    lot_cancellation_state: Eis223LotCancellationState | None = None
    model_config = ConfigDict(frozen=True, extra="forbid")
    manifest: Manifest223
    checked_at: datetime
    version_status: Literal["CURRENT_KNOWN_VERSION", "STALE"]
    blocked_reasons: tuple[str, ...]
    documents: tuple[Document223StatusItem, ...]
    download_status: Literal["INCOMPLETE", "COMPLETE_LISTED_SET", "UNKNOWN_MANIFEST"]
    review_status: Literal["UNKNOWN"] = "UNKNOWN"
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"
    economics_status: Literal["UNKNOWN"] = "UNKNOWN"
    requested: bool = False
    queue_status: Literal[
        "NOT_REQUESTED", "QUEUED", "COMPLETE", "BLOCKED", "ATTENTION_REQUIRED"
    ] = "NOT_REQUESTED"


def _where(
    table: Table, company: str, ref: Notice223DocumentRef
) -> tuple[ColumnElement[bool], ...]:
    return (
        table.c.company_id == company,
        table.c.purchase_number == ref.purchase_number,
        table.c.version_number == ref.version_number,
        table.c.notice_xml_sha256 == ref.notice_xml_sha256,
    )


def _notice(conn: Connection, company: str, ref: Notice223DocumentRef) -> Eis223NoticeSnapshot:
    table = eis_223_notice_versions
    row = (
        conn.execute(
            select(table).where(
                table.c.company_id == company,
                table.c.purchase_number == ref.purchase_number,
                table.c.version_number == ref.version_number,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("NOTICE_223_NOT_FOUND")
    if row["xml_sha256"] != ref.notice_xml_sha256:
        raise ValueError("NOTICE_DIGEST_CONFLICT")
    notice = Eis223NoticeSnapshot.model_validate(row["snapshot"])
    if (notice.purchase_number, notice.version_number, notice.xml_sha256) != (
        ref.purchase_number,
        ref.version_number,
        ref.notice_xml_sha256,
    ):
        raise ValueError("NOTICE_DIGEST_CONFLICT")
    return notice


def _blocked(
    conn: Connection,
    company: str,
    notice: Eis223NoticeSnapshot,
    now: datetime,
    cancellation_state: Eis223RejectionState | None = None,
    lot_cancellation_state: Eis223LotCancellationState | None = None,
) -> tuple[str, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    table = eis_223_notice_versions
    latest = conn.scalar(
        select(func.max(table.c.version_number)).where(
            table.c.company_id == company, table.c.purchase_number == notice.purchase_number
        )
    )
    reasons = []
    if latest != notice.version_number:
        reasons.append("NOTICE_VERSION_STALE")
    deadline = deadline223(notice)
    reasons.extend(unavailable223(notice))
    state = (
        cancellation_state
        or read_event223_states(conn, company, (notice.purchase_number,), now=now)[
            notice.purchase_number
        ]
    )
    if state.operation_hold:
        reasons.append(
            "PURCHASE_REJECTION_CONFIRMED"
            if state.application_status == "FAIL"
            else "PURCHASE_REJECTION_REVIEW_REQUIRED"
        )
        reasons.extend(c for c in state.reason_codes if c not in reasons)
    lot_state = (
        lot_cancellation_state
        or read_lot_event223_states(conn, company, (notice.purchase_number,), now=now)[
            notice.purchase_number
        ]
    )
    if lot_state.operation_hold:
        # Documents have notice scope; this is a review hold, never whole FAIL.
        reasons.append("LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED")
    if deadline.value is not None and deadline.value <= now:
        reasons.append("DEADLINE_EXPIRED")
    return tuple(reasons)


def get_document223_status(
    storage: PostgresStorage,
    company: str,
    ref: Notice223DocumentRef,
    *,
    now: datetime | None = None,
) -> Document223Status:
    at = now or datetime.now(UTC)
    with storage.transaction(company, consistent_read=True) as conn:
        return read_document223_status(conn, company, ref, now=at)


def read_document223_status(
    conn: Connection, company: str, ref: Notice223DocumentRef, *, now: datetime
) -> Document223Status:
    """Read in the caller's tenant transaction, including comparison snapshot."""
    notice = _notice(conn, company, ref)
    manifest = manifest223(notice)
    state = read_event223_states(conn, company, (notice.purchase_number,), now=now)[
        notice.purchase_number
    ]
    lot_state = read_lot_event223_states(conn, company, (notice.purchase_number,), now=now)[
        notice.purchase_number
    ]
    blocked = _blocked(
        conn, company, notice, now, cancellation_state=state, lot_cancellation_state=lot_state
    )
    rows = conn.execute(
        select(eis_223_document_receipts.c.content_uid, eis_223_document_receipts.c.analysis).where(
            *_where(eis_223_document_receipts, company, ref)
        )
    ).mappings()
    saved = {row["content_uid"]: DocumentAnalysis.model_validate(row["analysis"]) for row in rows}
    requested = (
        conn.scalar(
            select(eis_223_document_jobs.c.purchase_number).where(
                *_where(eis_223_document_jobs, company, ref)
            )
        )
        is not None
    )
    attempts = list(
        conn.execute(
            select(eis_223_document_attempts)
            .where(*_where(eis_223_document_attempts, company, ref))
            .order_by(
                eis_223_document_attempts.c.observed_at, eis_223_document_attempts.c.attempt_id
            )
        ).mappings()
    )
    documents = tuple(
        Document223StatusItem(
            reference=item,
            received=item.content_uid in saved,
            analysis=saved.get(item.content_uid),
            attempt_count=sum(
                a["content_uid"] == item.content_uid
                and a["reason"] not in {"ROBOTS_CRAWL_DELAY", "SOURCE_BUSY"}
                for a in attempts
            ),
            last_failure=next(
                (a["reason"] for a in reversed(attempts) if a["content_uid"] == item.content_uid),
                None,
            ),
        )
        for item in manifest.documents
    )
    for item in documents:
        analysis = item.analysis
        if analysis and (
            analysis.filename != item.reference.filename
            or analysis.url != item.reference.source_url
        ):
            raise ValueError("DOCUMENT_ANALYSIS_EVIDENCE_CONFLICT")
    return Document223Status(
        cancellation_state=state,
        lot_cancellation_state=lot_state,
        manifest=manifest,
        checked_at=now,
        version_status="STALE" if "NOTICE_VERSION_STALE" in blocked else "CURRENT_KNOWN_VERSION",
        blocked_reasons=blocked,
        documents=documents,
        download_status="UNKNOWN_MANIFEST"
        if manifest.status != "READY"
        else "COMPLETE_LISTED_SET"
        if all(d.received for d in documents)
        else "INCOMPLETE",
        requested=requested,
        queue_status=(
            "NOT_REQUESTED"
            if not requested
            else "BLOCKED"
            if blocked
            else "COMPLETE"
            if all(d.received for d in documents)
            else "ATTENTION_REQUIRED"
            if all(d.received or d.attempt_count >= 5 for d in documents)
            else "QUEUED"
        ),
    )


def collect_document223(
    storage: PostgresStorage,
    company: str,
    ref: Notice223DocumentRef,
    uid: str,
    *,
    actor_id: str,
    downloader: Callable[[str, str], bytes] = download_public223_attachment,
) -> Document223Status:
    """One exact UID, maximum20MiB; no admission/completeness/LLM transfer."""
    if not actor_id.strip():
        raise ValueError("ACTOR_MISSING")
    status = get_document223_status(storage, company, ref)
    if status.blocked_reasons:
        raise ValueError(status.blocked_reasons[0])
    if status.manifest.status != "READY":
        raise ValueError("UNKNOWN_MANIFEST")
    item = next((d for d in status.documents if d.reference.content_uid == uid), None)
    if item is None:
        raise ValueError("UNLISTED_DOCUMENT_UID")
    if item.received:
        return status
    reason = resource_gate(
        storage, company, max_database_bytes=100 * 1024**3, min_free_bytes=40 * 1024**3
    )
    if reason:
        raise ValueError(reason)
    # Serialize this tenant's one-file operations; exact source state is rechecked in the lock.
    with storage.transaction(company) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"), {"tenant": company}
        )
        notice = _notice(conn, company, ref)
        blocked = _blocked(conn, company, notice, datetime.now(UTC))
        if blocked:
            raise ValueError(blocked[0])
        table = eis_223_document_receipts
        if conn.scalar(
            select(table.c.content_uid).where(
                *_where(table, company, ref), table.c.content_uid == uid
            )
        ):
            pass
        else:
            total = (
                conn.scalar(
                    select(func.sum(func.octet_length(table.c.content))).where(
                        *_where(table, company, ref)
                    )
                )
                or 0
            )
            if total + 20 * 1024**2 > 100 * 1024**2:
                raise ValueError("DOCUMENT_SET_RESOURCE_LIMIT")
            reference = item.reference
            assert reference.source_url is not None and reference.filename is not None
            content = downloader(reference.source_url, uid)
            if not content or len(content) > 20 * 1024**2:
                raise ValueError("DOCUMENT_BYTES_RESOURCE_LIMIT")
            digest = hashlib.sha256(content).hexdigest()
            # A refreshed source during I/O must never be presented as current evidence.
            blocked = _blocked(conn, company, notice, datetime.now(UTC))
            if blocked:
                raise ValueError(blocked[0])
            analysis = analyze_document(content, reference.filename, reference.source_url)
            conn.execute(
                pg_insert(table).values(
                    company_id=company,
                    **ref.model_dump(),
                    content_uid=uid,
                    filename=reference.filename,
                    source_url=reference.source_url,
                    source_locator=reference.source_locator,
                    sha256=digest,
                    content=content,
                    analysis=analysis.model_dump(mode="json"),
                    analyzer_version="eis-native-v3-doc",
                    received_at=datetime.now(UTC),
                )
            )
            conn.execute(
                insert(audit_events).values(
                    company_id=company,
                    event_id=str(uuid4()),
                    actor_id=actor_id,
                    event_type="EIS_223_DOCUMENT_RECEIVED",
                    object_type="EIS_223_NOTICE",
                    object_id=ref.purchase_number,
                    object_version=ref.version_number,
                    occurred_at=datetime.now(UTC),
                    basis={
                        "xml_sha256": ref.notice_xml_sha256,
                        "content_uid": uid,
                        "document_sha256": digest,
                        "byte_count": len(content),
                        "extraction_status": analysis.status,
                        "eligibility": "UNKNOWN",
                    },
                )
            )
    return get_document223_status(storage, company, ref)
