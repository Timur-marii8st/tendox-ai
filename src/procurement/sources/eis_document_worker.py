"""One bounded file step from the persisted document queue."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from procurement.sources.eis_analysis import document_filename_requires_review
from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_public import EisPublicError, download_public_attachment
from procurement.storage.eis_document_store import (
    NoticeDocumentRef,
    document_read_gate,
    get_document_status,
    reanalyze_received_document,
    record_document_outcome,
)
from procurement.storage.eis_notice_hold import (
    assert_notice_source_usable,
    notice_variant_hold_clause,
)
from procurement.storage.models import eis_document_jobs

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


def run_document_step(
    storage: PostgresStorage,
    company_id: str,
    *,
    actor_id: str,
    now: datetime | None = None,
    downloader: Callable[[str], bytes] = download_public_attachment,
    max_database_bytes: int = 100 * 1024**3,
    min_free_bytes: int = 40 * 1024**3,
    probe_only: bool = False,
) -> dict[str, object]:
    """Process one file, or probe due work without source/analysis/audit writes."""
    explicit_now = now
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None or not actor_id.strip():
        raise ValueError("DOCUMENT_WORKER_INPUT_INVALID")
    reason = resource_gate(
        storage, company_id, max_database_bytes=max_database_bytes, min_free_bytes=min_free_bytes
    )
    if reason:
        return {"status": "BLOCKED", "reason": reason, "attempted": 0}
    skipped_jobs = 0
    skip_reasons: dict[str, int] = {}

    def audit_hold(ref: NoticeDocumentRef) -> None:
        nonlocal skipped_jobs
        if not probe_only:
            document_read_gate(
                storage,
                company_id,
                ref,
                actor_id=actor_id,
                now=explicit_now or datetime.now(UTC),
            )
        skipped_jobs += 1
        code = "NOTICE_VARIANT_REVIEW_REQUIRED"
        skip_reasons[code] = skip_reasons.get(code, 0) + 1

    held_clause = notice_variant_hold_clause(
        company_id, eis_document_jobs.c.purchase_number, eis_document_jobs.c.version_number
    )
    # Audit a bounded sample; held jobs never consume the actionable page capacity.
    with storage.transaction(company_id, consistent_read=True) as connection:
        held_rows = (
            connection.execute(
                select(eis_document_jobs)
                .where(eis_document_jobs.c.company_id == company_id, held_clause)
                .order_by(eis_document_jobs.c.created_at, eis_document_jobs.c.purchase_number)
                .limit(50)
            )
            .mappings()
            .all()
        )
    for row in held_rows:
        audit_hold(NoticeDocumentRef(**{key: row[key] for key in NoticeDocumentRef.model_fields}))
    after: tuple[datetime, str] | None = None
    # Keyset pages prevent completed jobs from starving later requests.
    while True:
        with storage.transaction(company_id, consistent_read=probe_only) as connection:
            statement = select(eis_document_jobs).where(
                eis_document_jobs.c.company_id == company_id, ~held_clause
            )
            if after is not None:
                from sqlalchemy import tuple_

                statement = statement.where(
                    tuple_(eis_document_jobs.c.created_at, eis_document_jobs.c.purchase_number)
                    > after
                )
            rows = (
                connection.execute(
                    statement.order_by(
                        eis_document_jobs.c.created_at, eis_document_jobs.c.purchase_number
                    ).limit(50)
                )
                .mappings()
                .all()
            )
        if not rows:
            return {
                "status": "IDLE",
                "attempted": 0,
                "skipped_jobs": skipped_jobs,
                "skip_reasons": skip_reasons,
            }
        for row in rows:
            ref = NoticeDocumentRef(**{key: row[key] for key in NoticeDocumentRef.model_fields})
            try:
                with storage.transaction(company_id, consistent_read=True) as connection:
                    assert_notice_source_usable(
                        connection, company_id, ref.purchase_number, ref.version_number
                    )
                report = get_document_status(storage, company_id, ref, now=now)
            except ValueError as error:
                if str(error) != "NOTICE_VARIANT_REVIEW_REQUIRED":
                    raise
                audit_hold(ref)
                continue
            if report.read_gate is not None and (
                "NOTICE_VARIANT_REVIEW_REQUIRED" in report.read_gate.blocked_reasons
            ):
                audit_hold(ref)
                continue
            late_hold = False
            if report.version_status != "STALE":
                for document in report.documents:
                    if (
                        document.reference_status == "PASS"
                        and document.fetch_status == "RECEIVED"
                        and document.reasons == ("ANALYSIS_NOT_AVAILABLE",)
                    ):
                        if probe_only:
                            return {"status": "READY", "attempted": 0, "operation": "ANALYSIS"}
                        try:
                            changed = reanalyze_received_document(
                                storage,
                                company_id,
                                ref,
                                document.content_uid,
                                actor_id=actor_id,
                            )
                        except ValueError as error:
                            if str(error) == "NOTICE_VARIANT_REVIEW_REQUIRED":
                                audit_hold(ref)
                                late_hold = True
                                break
                            if str(error) != "NOTICE_VERSION_STALE":
                                raise
                            break  # Source changed after the read; normal gate below records it.
                        if changed:
                            return {
                                "status": "REANALYZED",
                                "attempted": 0,
                                "analyzed": 1,
                                "purchase_number": ref.purchase_number,
                                "content_uid": document.content_uid,
                                "analyzer_version": report.analyzer_version,
                            }
            if late_hold:
                continue
            if all(document.fetch_status == "RECEIVED" for document in report.documents):
                continue
            gate = (
                report.read_gate
                if probe_only
                else document_read_gate(
                    storage,
                    company_id,
                    ref,
                    actor_id=actor_id,
                    now=explicit_now or datetime.now(UTC),
                )
            )
            if gate is None:
                raise ValueError("DOCUMENT_JOB_NOT_FOUND")
            if gate.blocked_reasons:
                skipped_jobs += 1
                for blocked in gate.blocked_reasons:
                    skip_reasons[blocked] = skip_reasons.get(blocked, 0) + 1
                continue
            for document in report.documents:
                if document.fetch_status == "RECEIVED":
                    continue
                delay = (
                    timedelta(seconds=60)
                    if document.reasons
                    in {
                        ("ROBOTS_CRAWL_DELAY",),
                        ("SOURCE_BUSY",),
                    }
                    else timedelta(minutes=30)
                )
                if document.observed_at and document.observed_at + delay > now:
                    continue
                if document.reference_status == "UNKNOWN" or document_filename_requires_review(
                    document.filename
                ):
                    code = (
                        "ATTACHMENT_REFERENCE_REQUIRES_REVIEW"
                        if document.reference_status == "UNKNOWN"
                        else "ATTACHMENT_FILENAME_REQUIRES_REVIEW"
                    )
                    if not probe_only:
                        try:
                            record_document_outcome(
                                storage,
                                company_id,
                                ref,
                                document.content_uid,
                                actor_id=actor_id,
                                failure_code=code,
                            )
                        except ValueError as late_error:
                            if str(late_error) != "NOTICE_VARIANT_REVIEW_REQUIRED":
                                raise
                            audit_hold(ref)
                            code = str(late_error)
                    return {"status": "BLOCKED", "reason": code, "attempted": 0}
                if probe_only:
                    return {"status": "READY", "attempted": 0, "operation": "SOURCE"}
                try:
                    content = downloader(document.source_url)
                    record_document_outcome(
                        storage,
                        company_id,
                        ref,
                        document.content_uid,
                        actor_id=actor_id,
                        content=content,
                    )
                except EisPublicError as error:
                    reason = str(error)
                    try:
                        record_document_outcome(
                            storage,
                            company_id,
                            ref,
                            document.content_uid,
                            actor_id=actor_id,
                            failure_code=reason,
                        )
                    except ValueError as late_error:
                        if str(late_error) != "NOTICE_VARIANT_REVIEW_REQUIRED":
                            raise
                        audit_hold(ref)
                        reason = str(late_error)
                    return {"status": "BLOCKED", "reason": reason, "attempted": 1}
                except ValueError as error:
                    reason = str(error)
                    if reason == "NOTICE_VARIANT_REVIEW_REQUIRED":
                        audit_hold(ref)
                        return {
                            "status": "BLOCKED",
                            "reason": reason,
                            "attempted": 1,
                            "skipped_jobs": skipped_jobs,
                            "skip_reasons": skip_reasons,
                        }
                    if reason not in {"DOCUMENT_BYTES_RESOURCE_LIMIT", "DOCUMENT_CONTENT_CONFLICT"}:
                        raise
                    try:
                        record_document_outcome(
                            storage,
                            company_id,
                            ref,
                            document.content_uid,
                            actor_id=actor_id,
                            failure_code=reason,
                        )
                    except ValueError as late_error:
                        if str(late_error) != "NOTICE_VARIANT_REVIEW_REQUIRED":
                            raise
                        audit_hold(ref)
                        return {
                            "status": "BLOCKED",
                            "reason": str(late_error),
                            "attempted": 1,
                        }
                    return {"status": "PARTIAL", "reason": reason, "attempted": 1}
                return {
                    "status": "PROCESSED",
                    "attempted": 1,
                    "skipped_jobs": skipped_jobs,
                    "skip_reasons": skip_reasons,
                    "purchase_number": ref.purchase_number,
                    "content_uid": document.content_uid,
                }
        after = rows[-1]["created_at"], rows[-1]["purchase_number"]
