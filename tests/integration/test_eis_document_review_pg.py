"""Review capture never changes legacy analysis, approvals or source state."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import event, func, insert, select
from test_eis_document_queue_pg import UID, admit, docx_bytes
from test_eis_document_queue_pg import storage as pg_storage
from test_eis_notice_hold_pg import hold

from procurement.storage.eis_document_review import (
    ReviewDocumentRequest,
    prepare_review_document,
    read_review_document_page,
)
from procurement.storage.eis_document_store import (
    get_document_analysis,
    plan_document_job,
    record_document_outcome,
)
from procurement.storage.models import (
    audit_events,
    eis_document_analyses,
    eis_document_blobs,
    eis_document_observations,
)
from procurement.storage.repository import PostgresStorage

storage = pg_storage


def prepared_source(storage: PostgresStorage):  # type: ignore[no-untyped-def]
    company = f"document-review-{uuid.uuid4()}"
    content = docx_bytes()
    ref = admit(storage, company, len(content))
    plan_document_job(storage, company, ref, actor_id="test")
    record_document_outcome(storage, company, ref, UID, actor_id="test", content=content)
    return (
        company,
        content,
        ReviewDocumentRequest(
            notice=ref,
            content_uid=UID,
            expected_document_sha256=hashlib.sha256(content).hexdigest(),
        ),
    )


def test_capture_replay_pages_and_legacy_unchanged(storage: PostgresStorage) -> None:
    company, _, request = prepared_source(storage)
    old = get_document_analysis(storage, company, request.notice, UID)
    before = old.model_dump_json()
    result = prepare_review_document(storage, company, request, actor_id="test")
    assert result.analysis_created and result.source_requests == result.jobs_created == 0
    assert result.requirement_status == result.full_tspec_completeness == "UNKNOWN"
    assert result.page.blocks
    assert all(
        block.provenance.document_id == request.expected_document_sha256
        for block in result.page.blocks
    )
    trace: list[str] = []

    def capture(conn, cursor, statement, parameters, context, many):  # type: ignore[no-untyped-def]
        if statement.startswith("SELECT eis_document_blobs.content"):
            trace.append(statement)

    event.listen(storage._engine, "before_cursor_execute", capture)
    try:
        replay = prepare_review_document(storage, company, request, actor_id="test")
        page = read_review_document_page(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture)
    assert not replay.analysis_created and not page.analysis_created and not trace
    assert page.page == replay.page == result.page
    assert get_document_analysis(storage, company, request.notice, UID).model_dump_json() == before
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_document_analyses)
                .where(eis_document_analyses.c.analyzer_version == "eis-native-review-v1")
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_type == "EIS_DOCUMENT_REVIEW_PREPARED")
            )
            == 1
        )


@pytest.mark.parametrize("kind", ["tenant", "uid", "sha", "stale", "latest_failed"])
def test_exact_source_gate(storage: PostgresStorage, kind: str) -> None:
    company, _, request = prepared_source(storage)
    if kind == "tenant":
        company = f"foreign-{uuid.uuid4()}"
    elif kind == "uid":
        request = request.model_copy(update={"content_uid": "B" * 32})
    elif kind == "sha":
        request = request.model_copy(update={"expected_document_sha256": "f" * 64})
    elif kind == "stale":
        admit(storage, company, 100, version=2)
    else:
        with storage.transaction(company) as conn:
            conn.execute(
                insert(eis_document_observations).values(
                    company_id=company,
                    purchase_number=request.notice.purchase_number,
                    version_number=request.notice.version_number,
                    observation_id=str(uuid.uuid4()),
                    content_uid=UID,
                    sha256=None,
                    fetch_status="FAILED",
                    reason_code="SOURCE_ERROR",
                    observed_at=datetime.now(UTC) + timedelta(seconds=1),
                )
            )
    with pytest.raises((ValueError, LookupError)):
        prepare_review_document(storage, company, request, actor_id="test")
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_document_analyses)
                .where(eis_document_analyses.c.analyzer_version == "eis-native-review-v1")
            )
            == 0
        )


def test_blob_metadata_guard_before_hydration(storage: PostgresStorage) -> None:
    company = f"document-review-cap-{uuid.uuid4()}"
    ref = admit(storage, company, 16)
    plan_document_job(storage, company, ref, actor_id="test")
    content = b"x" * (4 * 1024**2 + 1)
    digest = hashlib.sha256(content).hexdigest()
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_document_blobs).values(
                company_id=company,
                sha256=digest,
                content=content,
                byte_count=len(content),
                received_at=datetime.now(UTC),
            )
        )
        conn.execute(
            insert(eis_document_observations).values(
                company_id=company,
                purchase_number=ref.purchase_number,
                version_number=ref.version_number,
                observation_id=str(uuid.uuid4()),
                content_uid=UID,
                sha256=digest,
                fetch_status="RECEIVED",
                observed_at=datetime.now(UTC),
            )
        )
    request = ReviewDocumentRequest(notice=ref, content_uid=UID, expected_document_sha256=digest)
    trace: list[str] = []

    def capture(conn, cursor, statement, parameters, context, many):  # type: ignore[no-untyped-def]
        if statement.startswith("SELECT eis_document_blobs.content"):
            trace.append(statement)

    event.listen(storage._engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ValueError, match="REVIEW_DOCUMENT_BYTES_LIMIT"):
            prepare_review_document(storage, company, request, actor_id="test")
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture)
    assert not trace


def test_unprepared_read_and_strict_page_inputs(storage: PostgresStorage) -> None:
    company, _, request = prepared_source(storage)
    with pytest.raises(LookupError, match="REVIEW_ANALYSIS_NOT_PREPARED"):
        read_review_document_page(storage, company, request)
    for offset, limit in [(True, 1), (0, True), (-1, 1), (1000, 1), (0, 26)]:
        with pytest.raises(ValueError, match="REVIEW_PAGE_INVALID"):
            read_review_document_page(storage, company, request, offset=offset, limit=limit)


def test_invalid_blob_digest_never_creates_analysis(storage: PostgresStorage) -> None:
    company = f"document-review-digest-{uuid.uuid4()}"
    content = docx_bytes()
    ref = admit(storage, company, len(content))
    plan_document_job(storage, company, ref, actor_id="test")
    wrong_digest = "e" * 64
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_document_blobs).values(
                company_id=company,
                sha256=wrong_digest,
                content=content,
                byte_count=len(content),
                received_at=datetime.now(UTC),
            )
        )
        conn.execute(
            insert(eis_document_observations).values(
                company_id=company,
                purchase_number=ref.purchase_number,
                version_number=ref.version_number,
                observation_id=str(uuid.uuid4()),
                content_uid=UID,
                sha256=wrong_digest,
                fetch_status="RECEIVED",
                observed_at=datetime.now(UTC),
            )
        )
    request = ReviewDocumentRequest(
        notice=ref, content_uid=UID, expected_document_sha256=wrong_digest
    )
    with pytest.raises(ValueError, match="DOCUMENT_BYTES_NOT_VERIFIABLE"):
        prepare_review_document(storage, company, request, actor_id="test")
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_document_analyses)) == 0


@pytest.mark.parametrize("cached", [False, True])
def test_source_hold_blocks_capture_and_cached_reads(
    storage: PostgresStorage, tmp_path: Path, cached: bool
) -> None:
    company, _, request = prepared_source(storage)
    if cached:
        prepare_review_document(storage, company, request, actor_id="test")
    hold(storage, company, tmp_path, request.notice)
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        prepare_review_document(storage, company, request, actor_id="test")
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_review_document_page(storage, company, request)


def test_corrupt_review_cache_does_not_fall_back_to_v3(storage: PostgresStorage) -> None:
    company, _, request = prepared_source(storage)
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_document_analyses).values(
                company_id=company,
                sha256=request.expected_document_sha256,
                filename="spec.docx",
                analyzer_version="eis-native-review-v1",
                payload={"sha256": "f" * 64},
                analyzed_at=datetime.now(UTC),
            )
        )
    with pytest.raises(ValueError):
        prepare_review_document(storage, company, request, actor_id="test")
    with pytest.raises(ValueError):
        read_review_document_page(storage, company, request)
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_type == "EIS_DOCUMENT_REVIEW_PREPARED")
            )
            == 0
        )


def test_pages_recover_entire_retained_text_including_large_block(storage: PostgresStorage) -> None:
    company = f"document-review-pages-{uuid.uuid4()}"
    document = Document()
    texts = ["a" * 30000, "Поставка в Москву", "Соседний контекст"]
    for text_value in texts:
        document.add_paragraph(text_value)
    output = BytesIO()
    document.save(output)
    content = output.getvalue()
    ref = admit(storage, company, len(content))
    plan_document_job(storage, company, ref, actor_id="test")
    record_document_outcome(storage, company, ref, UID, actor_id="test", content=content)
    request = ReviewDocumentRequest(
        notice=ref, content_uid=UID, expected_document_sha256=hashlib.sha256(content).hexdigest()
    )
    first = prepare_review_document(storage, company, request, actor_id="test")
    pages = [first.page]
    while pages[-1].next_offset is not None:
        previous = pages[-1]
        assert len(pages) < 5
        pages.append(
            read_review_document_page(
                storage,
                company,
                request,
                offset=previous.next_offset,
                character_offset=previous.next_character_offset,
            ).page
        )
    rebuilt = {index: "" for index in range(len(texts))}
    for page in pages:
        assert page.native_text_completeness == "UNKNOWN"
        for block in page.blocks:
            assert block.text and block.character_start == len(rebuilt[block.block_index])
            rebuilt[block.block_index] += block.text
    assert list(rebuilt.values()) == texts


def test_ambiguous_reference_blocks_review_before_receipt(storage):
    company = f"ambiguous-review-{uuid.uuid4()}"
    content = docx_bytes()
    ref = admit(storage, company, len(content), ambiguous_attachment=True)
    request = ReviewDocumentRequest(
        notice=ref, content_uid=UID, expected_document_sha256=hashlib.sha256(content).hexdigest()
    )
    with pytest.raises(ValueError, match="ATTACHMENT_REFERENCE_REQUIRES_REVIEW"):
        prepare_review_document(storage, company, request, actor_id="test")


def test_ambiguous_metadata_cannot_reuse_cached_analysis_or_review(storage, monkeypatch):
    """Simulate legacy readers ignoring aliases, without mutating immutable notices."""
    from dataclasses import replace
    from types import SimpleNamespace

    from procurement.storage import eis_document_review as review
    from procurement.storage import eis_document_store as documents

    company = f"cached-ambiguous-{uuid.uuid4()}"
    content = docx_bytes()
    ref = admit(storage, company, len(content), ambiguous_attachment=True)
    plan_document_job(storage, company, ref, actor_id="test")
    request = ReviewDocumentRequest(
        notice=ref, content_uid=UID, expected_document_sha256=hashlib.sha256(content).hexdigest()
    )
    original_load, original_adapter = documents.load_notice, review._ATTACHMENTS

    def legacy_load(*args):
        notice = original_load(*args)
        return replace(
            notice, attachments=tuple(replace(a, aliases=()) for a in notice.attachments)
        )

    with monkeypatch.context() as legacy:
        legacy.setattr(documents, "load_notice", legacy_load)
        legacy.setattr(
            review,
            "_ATTACHMENTS",
            SimpleNamespace(
                validate_python=lambda raw: tuple(
                    replace(a, aliases=()) for a in original_adapter.validate_python(raw)
                )
            ),
        )
        record_document_outcome(storage, company, ref, UID, actor_id="test", content=content)
        prepare_review_document(storage, company, request, actor_id="test")
    get_document_status = documents.get_document_status
    reanalyze_received_document = documents.reanalyze_received_document
    status = get_document_status(storage, company, request.notice)
    assert status.extraction_status == "UNKNOWN"
    assert status.documents[0].reasons == ("ATTACHMENT_REFERENCE_REQUIRES_REVIEW",)
    from procurement.storage.eis_evidence_bridge import get_eis_evidence_bridge

    bridge = get_eis_evidence_bridge(storage, company, request.notice)
    assert bridge.documents[0].conditions == ()
    assert bridge.collection.extraction_status == "UNKNOWN"
    assert "ATTACHMENT_REFERENCE_REQUIRES_REVIEW" in bridge.review_gaps
    calls = (
        lambda: get_document_analysis(storage, company, request.notice, UID),
        lambda: reanalyze_received_document(storage, company, request.notice, UID, actor_id="test"),
        lambda: record_document_outcome(
            storage, company, request.notice, UID, actor_id="test", content=content
        ),
        lambda: prepare_review_document(storage, company, request, actor_id="test"),
    )
    for call in calls:
        with pytest.raises(ValueError, match="ATTACHMENT_REFERENCE_REQUIRES_REVIEW"):
            call()
