"""Read real scoped receipts/cache after recovery; print metadata, never source text."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select

from procurement.storage.eis_document_store import (
    NoticeDocumentRef,
    get_document_analysis,
    get_document_status,
)
from procurement.storage.models import (
    eis_document_analyses,
    eis_document_blobs,
    eis_document_jobs,
    eis_document_observations,
    eis_feed_windows,
    eis_notice_versions,
    eis_procedure_events,
    eis_sync_attempts,
)
from procurement.storage.repository import PostgresStorage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", default="local-eis-supplier")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    storage = PostgresStorage(engine)
    try:
        with storage.transaction(args.company_id, consistent_read=True) as connection:
            counts = {
                table.name: connection.scalar(select(func.count()).select_from(table))
                for table in (
                    eis_notice_versions,
                    eis_feed_windows,
                    eis_document_jobs,
                    eis_document_blobs,
                    eis_document_analyses,
                    eis_document_observations,
                    eis_procedure_events,
                )
            }
            counts["document_bytes"] = connection.scalar(
                select(func.coalesce(func.sum(eis_document_blobs.c.byte_count), 0))
            )
            counts["database_bytes"] = connection.scalar(
                select(func.pg_database_size(func.current_database()))
            )
            counts["current_notices"] = connection.scalar(
                select(func.count(func.distinct(eis_notice_versions.c.purchase_number)))
            )
            attempts = [
                dict(row)
                for row in connection.execute(
                    select(
                        eis_sync_attempts.c.window_key,
                        eis_sync_attempts.c.outcome,
                        eis_sync_attempts.c.reason_code,
                        eis_sync_attempts.c.source_response_sha256,
                    )
                    .order_by(eis_sync_attempts.c.attempted_at.desc())
                    .limit(8)
                ).mappings()
            ]
            rows = (
                connection.execute(
                    select(eis_document_jobs).order_by(eis_document_jobs.c.created_at).limit(20)
                )
                .mappings()
                .all()
            )
        jobs = []
        for row in rows:
            ref = NoticeDocumentRef(**{key: row[key] for key in NoticeDocumentRef.model_fields})
            report = get_document_status(storage, args.company_id, ref)
            files = []
            for document in report.documents:
                item = {
                    "uid": document.content_uid,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "fetch_status": document.fetch_status,
                    "extraction_status": document.extraction_status,
                    "reasons": document.reasons,
                }
                if document.fetch_status == "RECEIVED":
                    with storage.transaction(args.company_id, consistent_read=True) as connection:
                        blob = (
                            connection.execute(
                                select(eis_document_blobs).where(
                                    eis_document_blobs.c.sha256 == document.sha256
                                )
                            )
                            .mappings()
                            .one()
                        )
                    assert len(blob["content"]) == blob["byte_count"]
                    assert hashlib.sha256(blob["content"]).hexdigest() == document.sha256
                    assert document.declared_byte_count == document.received_byte_count
                    first = get_document_analysis(
                        storage, args.company_id, ref, document.content_uid
                    )
                    second = get_document_analysis(
                        storage, args.company_id, ref, document.content_uid
                    )
                    assert first == second and first.sha256 == document.sha256
                    assert first.document_role == "UNKNOWN"
                    assert all(not candidate.reviewed for candidate in first.requirement_candidates)
                    item.update(
                        blocks=first.blocks_total,
                        snippets=len(first.snippets),
                        candidates=len(first.requirement_candidates),
                        cache_replay_equal=True,
                    )
                files.append(item)
            jobs.append(
                {
                    **ref.model_dump(),
                    "version_status": report.version_status,
                    "listed": report.listed_count,
                    "received": report.received_count,
                    "download_status": report.download_status,
                    "review_status": report.review_status,
                    "source_manifest_coverage": report.source_manifest_coverage,
                    "blocks": sum(item.get("blocks", 0) for item in files),
                    "snippets": sum(item.get("snippets", 0) for item in files),
                    **({} if args.summary else {"files": files}),
                }
            )
        print(
            json.dumps(
                {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "counts": counts,
                    "jobs": jobs,
                    "recent_intake": attempts,
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
