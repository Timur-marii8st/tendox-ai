"""Position fragment links are immutable source0 records over one exact tenant snapshot."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy import delete, event, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_eis_analogs_pg import archive
from test_eis_characteristic_pair_pg import storage as storage_fixture
from test_eis_document_queue_pg import UID, docx_bytes
from test_eis_notice_hold_pg import hold

from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.sources.eis_position_association import (
    AssociationCursor,
    AssociationDetailRequest,
    AssociationListRequest,
    AssociationReadScope,
    AssociationRequest,
    FragmentSelection,
)
from procurement.storage.eis_document_review import ReviewDocumentRequest, prepare_review_document
from procurement.storage.eis_document_store import (
    NoticeDocumentRef,
    plan_document_job,
    record_document_outcome,
)
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.eis_position_association import (
    list_position_fragment_associations,
    read_position_fragment_association,
    read_position_fragment_association_detail,
    save_position_fragment_association,
)
from procurement.storage.eis_supplier_search import SupplierSearchRequest
from procurement.storage.models import (
    audit_events,
    eis_document_observations,
    eis_position_fragment_associations,
)

storage = storage_fixture
NUMBER = "0848300054826000154"


def admit_combined(storage, company, *, version=1, prepare=True):
    content = docx_bytes()
    with ZipFile(BytesIO(archive(NUMBER, version=version))) as zipped:
        xml = zipped.read("notice.xml")
    attachment = f"""<attachmentsInfo><attachmentInfo><publishedContentId>{UID}</publishedContentId>
<fileName>spec.docx</fileName><fileSize>{len(content)}</fileSize>
<url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid={UID}</url>
</attachmentInfo></attachmentsInfo>""".encode()
    xml = xml.replace(b"</commonInfo>", b"</commonInfo>" + attachment)
    output = BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr("notice.xml", xml)
    selection = EisDateSelection("50", date(2026, 3, version), 3)
    window = EisReadyWindow(selection.window_key, "a" * 64, 1, (output.getvalue(),))
    snapshot = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="test")
    ref = NoticeDocumentRef(
        purchase_number=NUMBER,
        version_number=version,
        notice_xml_sha256=snapshot.xml_sha256,
    )
    plan_document_job(storage, company, ref, actor_id="test")
    record_document_outcome(storage, company, ref, UID, actor_id="test", content=content)
    document = ReviewDocumentRequest(
        notice=ref,
        content_uid=UID,
        expected_document_sha256=hashlib.sha256(content).hexdigest(),
    )
    if prepare:
        prepare_review_document(storage, company, document, actor_id="test")
    request = AssociationRequest(
        position=SupplierSearchRequest(
            selection=PositionSelection(notice=ref, source_index=1)
        ),
        document=document,
        fragments=(FragmentSelection(block_index=0, character_start=0, character_end=8),),
    )
    return request


def test_save_replay_read_and_no_blob_hydration(storage):
    company = f"position-association-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    trace = []

    def capture(conn, cursor, statement, parameters, context, many):  # type: ignore[no-untyped-def]
        if "eis_document_blobs.content" in statement:
            trace.append(statement)

    event.listen(storage._engine, "before_cursor_execute", capture)
    try:
        created = save_position_fragment_association(
            storage, company, request, actor_id="operator"
        )
        replay = save_position_fragment_association(
            storage, company, request, actor_id="operator"
        )
        read = read_position_fragment_association(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture)
    assert created.created and not replay.created and not read.created
    assert created.report == replay.report == read.report
    assert created.report.fragments[0].text == "Поставка"
    assert created.report.source_requests == created.report.jobs_created == 0
    assert not trace
    with storage.transaction(company, consistent_read=True) as conn:
        count = conn.scalar(select(func.count()).select_from(eis_position_fragment_associations))
        assert count == 1
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_type == "EIS_POSITION_FRAGMENTS_LINKED")
            )
            == 1
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            update(eis_position_fragment_associations).values(report_sha256="f" * 64)
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(delete(eis_position_fragment_associations))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        ref = request.position.selection.notice
        conn.execute(
            insert(eis_position_fragment_associations).values(
                company_id=company,
                association_id=str(uuid.uuid4()),
                cache_key="f" * 64,
                purchase_number=ref.purchase_number,
                version_number=ref.version_number,
                notice_xml_sha256=ref.notice_xml_sha256,
                source_index=request.position.selection.source_index,
                content_uid=request.document.content_uid,
                document_sha256=request.document.expected_document_sha256,
                report=None,
                report_sha256="e" * 64,
                created_at=created.report.created_at,
            )
        )


def test_tenant_hold_and_stale_revision_fail_without_association(storage, tmp_path):
    company = f"position-association-gates-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    with pytest.raises((ValueError, LookupError)):
        save_position_fragment_association(
            storage, "foreign-" + company, request, actor_id="operator"
        )
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        count = conn.scalar(select(func.count()).select_from(eis_position_fragment_associations))
        assert count == 0
    hold(storage, company, tmp_path, request.document.notice)
    with pytest.raises(ValueError):
        save_position_fragment_association(storage, company, request, actor_id="operator")

    company = f"position-association-stale-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    admit_combined(storage, company, version=2)
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        save_position_fragment_association(storage, company, request, actor_id="operator")


def test_wrong_position_document_and_unprepared_analysis_fail_source0(storage):
    company = f"position-association-exact-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    bad_position = request.model_copy(
        update={
            "position": request.position.model_copy(
                update={
                    "selection": request.position.selection.model_copy(
                        update={"source_index": 2}
                    )
                }
            )
        }
    )
    with pytest.raises((ValueError, LookupError)):
        save_position_fragment_association(
            storage, company, bad_position, actor_id="operator"
        )
    payload = request.model_dump(mode="python")
    payload["document"]["expected_document_sha256"] = "f" * 64
    bad_document = AssociationRequest.model_validate(payload)
    with pytest.raises(ValueError, match="DOCUMENT_RECEIPT_DIGEST_CONFLICT"):
        save_position_fragment_association(
            storage, company, bad_document, actor_id="operator"
        )

    company = f"position-association-unprepared-{uuid.uuid4()}"
    unprepared = admit_combined(storage, company, prepare=False)
    with pytest.raises(LookupError, match="ANALYSIS_NOT_PREPARED"):
        save_position_fragment_association(
            storage, company, unprepared, actor_id="operator"
        )


def test_latest_failed_document_receipt_cannot_reuse_older_analysis(storage):
    company = f"position-association-receipt-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_document_observations).values(
                company_id=company,
                purchase_number=request.document.notice.purchase_number,
                version_number=request.document.notice.version_number,
                observation_id=str(uuid.uuid4()),
                content_uid=request.document.content_uid,
                sha256=None,
                fetch_status="FAILED",
                reason_code="SOURCE_ERROR",
                observed_at=datetime.now(UTC) + timedelta(seconds=1),
            )
        )
    with pytest.raises(LookupError, match="DOCUMENT_RECEIPT_NOT_FOUND"):
        save_position_fragment_association(storage, company, request, actor_id="operator")


def test_busy_tenant_lease_fails_before_snapshot_or_insert(storage):
    company = f"position-association-busy-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    key = company
    with storage._engine.connect() as lease:
        assert lease.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key}
        )
        lease.commit()
        try:
            with pytest.raises(ValueError, match="POSITION_ASSOCIATION_BUSY"):
                save_position_fragment_association(
                    storage, company, request, actor_id="operator"
                )
        finally:
            lease.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key}
            )
            lease.commit()
    with storage.transaction(company, consistent_read=True) as conn:
        count = conn.scalar(select(func.count()).select_from(eis_position_fragment_associations))
        assert count == 0


def test_metadata_pagination_ties_and_exact_detail_scope(storage):
    company = f"position-association-list-{uuid.uuid4()}"
    original = admit_combined(storage, company)
    requests = tuple(
        original.model_copy(
            update={
                "fragments": (
                    FragmentSelection(
                        block_index=0,
                        character_start=index,
                        character_end=index + 1,
                    ),
                )
            }
        )
        for index in range(3)
    )
    tied = datetime(2026, 10, 6, 12, tzinfo=UTC)
    saved = tuple(
        save_position_fragment_association(
            storage, company, request, actor_id="operator", now=tied
        )
        for request in requests
    )
    scope = AssociationReadScope(
        position=original.position,
        document=original.document,
        analyzer_version=original.analyzer_version,
    )
    first_request = AssociationListRequest(scope=scope, limit=2)
    first = list_position_fragment_associations(storage, company, first_request)
    assert len(first.items) == 2 and first.next_cursor is not None
    second = list_position_fragment_associations(
        storage,
        company,
        AssociationListRequest(scope=scope, limit=2, cursor=first.next_cursor),
    )
    assert len(second.items) == 1 and second.next_cursor is None
    ids = [item.association_id for item in (*first.items, *second.items)]
    assert ids == sorted((item.report.association_id for item in saved), reverse=True)
    detail = read_position_fragment_association_detail(
        storage,
        company,
        AssociationDetailRequest(scope=scope, association_id=ids[0]),
    )
    assert not detail.created and detail.report.association_id == ids[0]
    with pytest.raises(LookupError, match="POSITION_ASSOCIATION_NOT_FOUND"):
        list_position_fragment_associations(
            storage,
            company,
            AssociationListRequest(
                scope=scope,
                cursor=first.next_cursor.model_copy(
                    update={"association_id": str(uuid.uuid4())}
                ),
            ),
        )


def test_list_filters_old_same_sha_receipt_before_page_limit(storage):
    company = f"position-association-receipt-refresh-{uuid.uuid4()}"
    request = admit_combined(storage, company)
    old = save_position_fragment_association(
        storage, company, request, actor_id="operator"
    )
    refreshed_at = old.report.observed_at + timedelta(seconds=1)
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_document_observations).values(
                company_id=company,
                purchase_number=request.document.notice.purchase_number,
                version_number=request.document.notice.version_number,
                observation_id=str(uuid.uuid4()),
                content_uid=request.document.content_uid,
                sha256=request.document.expected_document_sha256,
                fetch_status="RECEIVED",
                observed_at=refreshed_at,
            )
        )
    current = save_position_fragment_association(
        storage, company, request, actor_id="operator"
    )
    assert current.created and current.report.association_id != old.report.association_id
    scope = AssociationReadScope(
        position=request.position,
        document=request.document,
        analyzer_version=request.analyzer_version,
    )
    result = list_position_fragment_associations(
        storage, company, AssociationListRequest(scope=scope, limit=1)
    )
    assert [item.association_id for item in result.items] == [
        current.report.association_id
    ]
    assert result.next_cursor is None
    with pytest.raises(LookupError, match="POSITION_ASSOCIATION_NOT_FOUND"):
        list_position_fragment_associations(
            storage,
            company,
            AssociationListRequest(
                scope=scope,
                cursor=AssociationCursor(
                    created_at=old.report.created_at,
                    association_id=old.report.association_id,
                ),
            ),
        )
