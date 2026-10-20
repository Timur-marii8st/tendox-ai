"""Canonical source0 protocol read: exact identity, RLS, guards and no mutations."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_eis_notice_index_pg import storage as storage_fixture

from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_index import ingest_ready_window
from procurement.storage.eis_protocols import read_historical_protocols
from procurement.storage.models import audit_events, eis_document_jobs, eis_procedure_events
from test_eis_mixed_number_archive import NUMBER, mixed, window
from test_eis_protocols import PROPOSALS, protocol_xml, result_row

storage = storage_fixture
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def test_exact_protocol_read_no_writes_and_wrong_tenant_or_sha_fails(storage, monkeypatch):
    company = "s203-" + str(uuid4())
    raw = mixed(protocol_xml(PROPOSALS, "<n:applications>" + result_row() + "</n:applications>"))
    bound = window(raw)
    ingest_ready_window(storage, company, bound, actor_id="synthetic")
    from procurement.storage.eis_notice_index import preflight_ready_window

    notice = preflight_ready_window(bound).inspections[0].records[0]
    ref = NoticeDocumentRef(
        purchase_number=NUMBER, version_number=1, notice_xml_sha256=notice.xml_sha256
    )

    def counts():
        with storage.transaction(company, consistent_read=True) as conn:
            return tuple(
                conn.scalar(select(func.count()).select_from(table))
                for table in (audit_events, eis_document_jobs, eis_procedure_events)
            )

    before = counts()
    report = read_historical_protocols(storage, company, ref, now=NOW)
    assert len(report.documents) == 1 and report.documents[0].represented_applications.value == 1
    assert report.source_requests == 0 and report.notice_version_link == "UNKNOWN"
    assert counts() == before
    with pytest.raises(ValueError, match="PROTOCOL_NOTICE_NOT_FOUND_OR_MISMATCH"):
        read_historical_protocols(storage, "foreign-" + company, ref, now=NOW)
    with pytest.raises(ValueError, match="PROTOCOL_NOTICE_NOT_FOUND_OR_MISMATCH"):
        read_historical_protocols(
            storage, company, ref.model_copy(update={"notice_xml_sha256": "f" * 64}), now=NOW
        )
    module = __import__("procurement.storage.eis_protocols", fromlist=["MAX_COMPRESSED_BYTES"])
    monkeypatch.setattr(module, "MAX_COMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="PROTOCOL_ARCHIVE_SIZE_OR_BINDING_INVALID"):
        read_historical_protocols(storage, company, ref, now=NOW)
    assert counts() == before


def test_forged_archive_digest_is_rejected_by_storage_constraints(storage):
    from sqlalchemy.exc import IntegrityError

    from procurement.storage.eis_notice_index import preflight_ready_window
    from procurement.storage.models import eis_feed_archives

    company = "s203-corrupt-" + str(uuid4())
    raw = mixed(protocol_xml(PROPOSALS, "<n:applications>" + result_row() + "</n:applications>"))
    bound = window(raw)
    ingest_ready_window(storage, company, bound, actor_id="synthetic")
    inspection = preflight_ready_window(bound).inspections[0]
    notice = inspection.records[0]
    ref = NoticeDocumentRef(
        purchase_number=NUMBER, version_number=1, notice_xml_sha256=notice.xml_sha256
    )
    forged_sha = "f" * 64
    with pytest.raises(IntegrityError), storage.transaction(company) as conn:
        conn.execute(
            eis_feed_archives.insert().values(
                company_id=company,
                window_key=bound.window_key,
                response_sha256=bound.response_sha256,
                archive_sha256=forged_sha,
                content=raw,
                record_count=2,
            )
        )
    report = read_historical_protocols(storage, company, ref, now=NOW)
    assert len(report.documents) == 1


@pytest.mark.parametrize(
    "setting,value,reason",
    [
        ("MAX_EVENTS", 0, "PROTOCOL_EVENT_LIMIT"),
        ("MAX_ARCHIVES", 0, "PROTOCOL_ARCHIVE_LIMIT"),
        ("MAX_EXPANDED_BYTES", 1, "PROTOCOL_ARCHIVE_UNSAFE"),
        ("MAX_TOTAL_ROWS", 0, "PROTOCOL_TOTAL_APPLICATION_LIMIT"),
        ("MAX_RESPONSE_BYTES", 128, "PROTOCOL_RESPONSE_LIMIT"),
    ],
)
def test_foreground_resource_guards_fail_without_writes(
    storage, monkeypatch, setting, value, reason
):
    from procurement.storage import eis_protocols as module
    from procurement.storage.eis_notice_index import preflight_ready_window

    company = "s203-cap-" + str(uuid4())
    raw = mixed(protocol_xml(PROPOSALS, "<n:applications>" + result_row() + "</n:applications>"))
    bound = window(raw)
    ingest_ready_window(storage, company, bound, actor_id="synthetic")
    notice = preflight_ready_window(bound).inspections[0].records[0]
    ref = NoticeDocumentRef(
        purchase_number=NUMBER, version_number=1, notice_xml_sha256=notice.xml_sha256
    )
    monkeypatch.setattr(module, setting, value)
    with pytest.raises(ValueError, match=reason):
        read_historical_protocols(storage, company, ref, now=NOW)
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(audit_events)) == 1
        assert conn.scalar(select(func.count()).select_from(eis_document_jobs)) == 0


def test_invalid_clock_does_not_open_transaction():
    class NoStorage:
        def transaction(self, *args, **kwargs):
            pytest.fail("invalid clock opened transaction")

    ref = NoticeDocumentRef(purchase_number=NUMBER, version_number=1, notice_xml_sha256="a" * 64)
    with pytest.raises(ValueError, match="PROTOCOL_REQUEST_INVALID"):
        read_historical_protocols(NoStorage(), "tenant", ref, now=NOW.replace(tzinfo=None))
