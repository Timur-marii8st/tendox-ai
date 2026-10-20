"""Tenant immutable exact requests, fair pending selection and safe retry journal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_223_documents import Notice223DocumentRef, manifest223
from procurement.storage.eis_223_documents import (
    Document223Status,
    _blocked,
    _notice,
    _where,
    get_document223_status,
)
from procurement.storage.models import (
    audit_events,
    eis_223_document_attempts,
    eis_223_document_jobs,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.storage.repository import PostgresStorage

_PENDING = """
FROM eis_223_document_jobs j JOIN eis_223_notice_versions n
 ON n.company_id=j.company_id AND n.purchase_number=j.purchase_number
 AND n.version_number=j.version_number AND n.xml_sha256=j.notice_xml_sha256
CROSS JOIN LATERAL jsonb_array_elements(n.snapshot->'attachments') WITH ORDINALITY a(item,ordinal)
WHERE j.company_id=:company
 AND NOT EXISTS(SELECT 1 FROM eis_223_notice_versions newer
  WHERE newer.company_id=j.company_id AND newer.purchase_number=j.purchase_number
  AND newer.version_number>j.version_number)
 AND NOT EXISTS(SELECT 1 FROM eis_223_events e
  WHERE e.company_id=j.company_id AND e.purchase_number=j.purchase_number)
 AND NOT EXISTS(SELECT 1 FROM eis_223_lot_events e
  WHERE e.company_id=j.company_id AND e.purchase_number=j.purchase_number)
 AND ((CASE WHEN n.snapshot->>'document_type'='purchaseNotice'
    THEN n.snapshot->'selected_deadline' ELSE n.snapshot->'deadline' END)->>'value' IS NULL
  OR ((CASE WHEN n.snapshot->>'document_type'='purchaseNotice'
    THEN n.snapshot->'selected_deadline' ELSE n.snapshot->'deadline' END)->>'value')
    ::timestamptz>:now)
 AND NOT EXISTS(SELECT 1 FROM eis_223_document_receipts r
  WHERE r.company_id=j.company_id AND r.purchase_number=j.purchase_number
  AND r.version_number=j.version_number AND r.notice_xml_sha256=j.notice_xml_sha256
  AND r.content_uid=a.item->'content_uid'->>'value')
 AND (SELECT count(*) FROM eis_223_document_attempts t
  WHERE t.company_id=j.company_id AND t.purchase_number=j.purchase_number
  AND t.version_number=j.version_number AND t.notice_xml_sha256=j.notice_xml_sha256
  AND t.content_uid=a.item->'content_uid'->>'value'
  AND (t.reason IS NULL OR t.reason NOT IN ('ROBOTS_CRAWL_DELAY','SOURCE_BUSY')))<5
"""
_RETRY = """
 AND NOT EXISTS(SELECT 1 FROM eis_223_document_attempts t
  WHERE t.company_id=j.company_id AND t.purchase_number=j.purchase_number
  AND t.version_number=j.version_number AND t.notice_xml_sha256=j.notice_xml_sha256
  AND t.content_uid=a.item->'content_uid'->>'value'
  AND t.observed_at + CASE WHEN t.reason IN ('ROBOTS_CRAWL_DELAY','SOURCE_BUSY')
    THEN interval '60 seconds' ELSE interval '30 minutes' END > :now)
"""


def next_document223(
    storage: PostgresStorage, company: str, now: datetime
) -> tuple[Notice223DocumentRef, str] | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    with storage.transaction(company, consistent_read=True) as conn:
        row = (
            conn.execute(
                text(
                    "SELECT j.purchase_number,j.version_number,j.notice_xml_sha256, "
                    "a.item->'content_uid'->>'value' AS uid "
                    + _PENDING
                    + _RETRY
                    + " ORDER BY j.created_at,j.purchase_number,a.ordinal LIMIT 1"
                ),
                {"company": company, "now": now},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return Notice223DocumentRef(**{k: row[k] for k in Notice223DocumentRef.model_fields}), row[
        "uid"
    ]


def _audit(
    conn: Connection,
    company: str,
    actor: str,
    ref: Notice223DocumentRef,
    event: str,
    basis: dict[str, object],
    now: datetime,
) -> None:
    conn.execute(
        insert(audit_events).values(
            company_id=company,
            event_id=str(uuid4()),
            actor_id=actor,
            event_type=event,
            object_type="EIS_223_NOTICE",
            object_id=ref.purchase_number,
            object_version=ref.version_number,
            occurred_at=now,
            basis={"xml_sha256": ref.notice_xml_sha256, "eligibility": "UNKNOWN", **basis},
        )
    )


def plan_document223_job(
    storage: PostgresStorage, company: str, ref: Notice223DocumentRef, *, actor_id: str
) -> Document223Status:
    if not actor_id.strip():
        raise ValueError("ACTOR_MISSING")
    now = datetime.now(UTC)
    with storage.transaction(company) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"), {"tenant": company}
        )
        notice = _notice(conn, company, ref)
        blocked = _blocked(conn, company, notice, now)
        if blocked:
            raise ValueError(blocked[0])
        manifest = manifest223(notice)
        if manifest.status != "READY":
            raise ValueError("UNKNOWN_MANIFEST")
        table = eis_223_document_jobs
        exists = conn.scalar(select(table.c.purchase_number).where(*_where(table, company, ref)))
        if not exists:
            recent = conn.scalar(
                select(func.count())
                .select_from(table)
                .where(
                    table.c.company_id == company, table.c.created_at >= now - timedelta(hours=1)
                )
            )
            if recent and recent >= 10:
                raise ValueError("DOCUMENT_223_REQUEST_RATE_LIMIT")
            pending = conn.execute(
                text(
                    "SELECT DISTINCT j.purchase_number,j.version_number " + _PENDING + " LIMIT 11"
                ),
                {"company": company, "now": now},
            ).all()
            if len(pending) >= 10:
                raise ValueError("DOCUMENT_223_QUEUE_FULL")
            conn.execute(
                pg_insert(table).values(
                    company_id=company, **ref.model_dump(), created_by=actor_id, created_at=now
                )
            )
            _audit(
                conn,
                company,
                actor_id,
                ref,
                "EIS_223_DOCUMENT_JOB_PLANNED",
                {"listed_count": len(manifest.documents)},
                now,
            )
    return get_document223_status(storage, company, ref)


def record_document223_attempt(
    storage: PostgresStorage,
    company: str,
    ref: Notice223DocumentRef,
    uid: str,
    status: Literal["RECEIVED", "FAILED"],
    reason: str | None,
    *,
    actor_id: str,
    now: datetime,
) -> None:
    if not actor_id.strip() or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DOCUMENT_WORKER_INPUT_INVALID")
    with storage.transaction(company) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"), {"tenant": company}
        )
        table = eis_223_document_attempts
        count = conn.scalar(
            select(func.count())
            .select_from(table)
            .where(
                *_where(table, company, ref),
                table.c.content_uid == uid,
                (
                    table.c.reason.is_(None)
                    | table.c.reason.not_in(("ROBOTS_CRAWL_DELAY", "SOURCE_BUSY"))
                ),
            )
        )
        if count and count >= 5:
            raise ValueError("DOCUMENT_223_ATTEMPT_LIMIT")
        conn.execute(
            insert(table).values(
                company_id=company,
                **ref.model_dump(),
                attempt_id=str(uuid4()),
                content_uid=uid,
                status=status,
                reason=reason,
                observed_at=now,
            )
        )
        _audit(
            conn,
            company,
            actor_id,
            ref,
            "EIS_223_DOCUMENT_ATTEMPT",
            {"content_uid": uid, "status": status, "reason": reason},
            now,
        )
