"""Isolated PG cancellation gates; all XML and quality observations are synthetic."""

from uuid import uuid4

import pytest
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.sources.eis_223_event_sync import Eis223EventReadyWindow
from procurement.sources.eis_223_events import Eis223EventSchemaCheck, parse_purchase_rejection_xml
from procurement.sources.eis_223_schema import SCHEMAS, VALIDATOR
from procurement.storage.eis_223_comparison import read_comparison223_row
from procurement.storage.eis_223_document_queue import next_document223, plan_document223_job
from procurement.storage.eis_223_documents import read_document223_status
from procurement.storage.eis_223_events import (
    ingest_event223_window,
    read_event223_states,
    record_event_schema_check,
)
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.eis_223_sync import due_windows, record_attempt
from procurement.storage.models import (
    audit_events,
    eis_223_event_archive_sources,
    eis_223_event_schema_checks,
    eis_223_event_sync_attempts,
    eis_223_event_windows,
    eis_223_events,
)
from test_eis_223_events import event_xml, zip_bytes
from test_eis_223_index import NOW, URL, window

TABLES = (
    eis_223_event_windows,
    eis_223_event_archive_sources,
    eis_223_events,
    eis_223_event_schema_checks,
    eis_223_event_sync_attempts,
    audit_events,
)


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def counts(storage, company):
    with storage.transaction(company) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t).where(t.c.company_id == company))
            for t in TABLES
        )


def ready(raw, response="a" * 64):
    return Eis223EventReadyWindow(
        window_key="getDocsIP/RI223/50/2026-10-01+03:00/purchaseRejection",
        response_sha256=response,
        prepared_sha256="b" * 64,
        archive_urls=(URL,),
        archives=(zip_bytes([("rejection.xml", raw)]),),
    )


def store(storage, company, raw, response="a" * 64):
    return ingest_event223_window(storage, company, ready(raw, response), actor_id="test", now=NOW)


def state(storage, company, number="32600000001"):
    with storage.transaction(company, consistent_read=True) as conn:
        return read_event223_states(conn, company, (number,), now=NOW)[number]


def quality(storage, company, raw):
    event = parse_purchase_rejection_xml(raw, source_member="rejection.xml")
    for release, hashes in SCHEMAS.items():
        check = Eis223EventSchemaCheck(
            event_guid=event.event_guid.value,
            purchase_number=event.purchase_number,
            xml_sha256=event.xml_sha256,
            schema_release=release,
            package_sha256=hashes[0],
            root_sha256=hashes[1],
            tree_sha256=hashes[2],
            validator_version=VALIDATOR,
            status="PASS",
            diagnostics=(),
            checked_at=NOW,
        )
        assert record_event_schema_check(storage, company, check, actor_id="test")
        before = counts(storage, company)
        assert not record_event_schema_check(storage, company, check, actor_id="test")
        assert counts(storage, company) == before


def test_event_before_notice_replay_rls_and_confirmed_quality(storage):
    company = "event-before-" + uuid4().hex
    raw = event_xml(number="32600000001", publication="2026-10-01T10:10:00+03:00")
    result = store(storage, company, raw)
    assert result.new_events == 1
    assert state(storage, company).operation_hold
    assert state(storage, company).evidence_status == "UNKNOWN"
    before = counts(storage, company)
    assert store(storage, company, raw).replayed
    assert counts(storage, company) == before
    assert not state(storage, "other-" + company).operation_hold
    with storage.transaction("other-" + company) as conn:
        assert conn.execute(select(eis_223_events)).first() is None
    quality(storage, company, raw)
    known = state(storage, company)
    assert known.application_status == "FAIL" and known.evidence_status == "PASS"
    assert known.current_procedure_status == "UNKNOWN" and known.operation_hold


def test_same_guid_variants_and_cross_number_are_retained(storage):
    company = "event-variants-" + uuid4().hex
    raw = event_xml(number="32600000001", publication="2026-10-01T10:10:00+03:00")
    store(storage, company, raw)
    quality(storage, company, raw)
    changed = event_xml(number="32600000002", publication="2026-10-01T10:10:00+03:00")
    report = store(storage, company, changed, "c" * 64)
    assert report.new_events == report.guid_conflicts == 1
    for number in ("32600000001", "32600000002"):
        result = state(storage, company, number)
        assert result.operation_hold and result.application_status == "UNKNOWN"
        assert len(result.events) == 2 and "EVENT_GUID_TARGET_CONFLICT" in result.reason_codes
    assert counts(storage, company)[2] == 2


def test_whole_window_rejects_unsafe_member_atomically(storage):
    company = "event-unsafe-" + uuid4().hex
    prepared = ready(event_xml(number="32600000001"))
    prepared = prepared.model_copy(
        update={
            "archives": (
                zip_bytes([("ok.xml", event_xml(number="32600000001")), ("../evil.xml", b"bad")]),
            )
        }
    )
    before = counts(storage, company)
    with pytest.raises(ValueError):
        ingest_event223_window(storage, company, prepared, actor_id="test", now=NOW)
    assert counts(storage, company) == before


@pytest.mark.parametrize("operation", [update, delete])
def test_variants_are_immutable(storage, operation):
    company = "event-immutable-" + uuid4().hex
    store(storage, company, event_xml(number="32600000001"))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        query = operation(eis_223_events).where(eis_223_events.c.company_id == company)
        if operation is update:
            query = query.values(purchase_number="32600000002")
        conn.execute(query)


def test_event_hold_reaches_search_documents_comparison_and_stays_after_new_notice(storage):
    company = "event-consumers-" + uuid4().hex
    ingest_notice223_window(storage, company, window(), actor_id="test", now=NOW)
    lead = search_notice223_index(storage, company, "бумага", now=NOW).matched[0]
    ref = Notice223DocumentRef(
        purchase_number=lead.notice.purchase_number,
        version_number=lead.notice.version_number,
        notice_xml_sha256=lead.notice.xml_sha256,
    )
    plan_document223_job(storage, company, ref, actor_id="test")
    raw = event_xml(number=ref.purchase_number, publication="2026-10-01T10:10:00+03:00")
    store(storage, company, raw)
    quality(storage, company, raw)
    before = counts(storage, company)
    result = search_notice223_index(storage, company, "бумага", now=NOW).matched[0]
    assert result.application_status == "FAIL" and result.cancellation_state.operation_hold
    with storage.transaction(company, consistent_read=True) as conn:
        documents = read_document223_status(conn, company, ref, now=NOW)
        comparison = read_comparison223_row(conn, company, ref, now=NOW)
    assert documents.queue_status == "BLOCKED" and documents.blocked_reasons
    assert next_document223(storage, company, NOW) is None
    from procurement.storage.eis_223_documents import collect_document223

    def forbidden(*args):
        raise AssertionError("Held cancellation must not fetch")

    with pytest.raises(ValueError, match="PURCHASE_REJECTION_CONFIRMED"):
        collect_document223(storage, company, ref, "any", actor_id="test", downloader=forbidden)
    assert (
        comparison.readiness_status == "BLOCKED"
        and comparison.cancellation_state == result.cancellation_state
    )
    from test_eis_223_archive import xml

    raw_notice = xml().replace(b"<p:version>2</p:version>", b"<p:version>3</p:version>")
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("new.xml", raw_notice)]), response="d" * 64),
        actor_id="test",
        now=NOW,
    )
    assert (
        search_notice223_index(storage, company, "бумага", now=NOW).matched[0].application_status
        == "FAIL"
    )
    # Source notice writes only; event read consumers added no records.
    assert counts(storage, company)[:5] == before[:5]
    from procurement.storage.eis_source_estimate import SourceEstimateRequest, get_source_estimate
    from test_eis_source_estimate import request as estimate_request

    payload = estimate_request("223").model_dump()
    payload["notice"] = {"law": "223", **ref.model_dump()}
    estimate = get_source_estimate(
        storage, company, SourceEstimateRequest.model_validate(payload), actor_id="test", now=NOW
    )
    assert estimate.estimate.status == "BLOCKED" and not estimate.estimate.scenarios
    assert estimate.cancellation_state.operation_hold


def test_uncertain_event_never_passes_and_refresh_journal_requires_real_checkpoint(storage):
    company = "event-unknown-" + uuid4().hex
    raw = event_xml(number="32600000001", publication=None)
    store(storage, company, raw)
    quality(storage, company, raw)
    result = state(storage, company)
    assert (
        result.operation_hold and result.evidence_status == result.application_status == "UNKNOWN"
    )
    key = ready(raw).window_key
    with pytest.raises(ValueError, match="SYNCED_CHECKPOINT_MISSING"):
        record_attempt(
            storage,
            company,
            key,
            "SYNCED",
            actor_id="test",
            checked_at=NOW,
            response_sha256="c" * 64,
        )
    record_attempt(
        storage, company, key, "SYNCED", actor_id="test", checked_at=NOW, response_sha256="a" * 64
    )
    targets = due_windows(storage, company, NOW, include_events=True)
    assert len(targets) == 13
    assert sum(t.document_type == "purchaseRejection" for t in targets) == 1


def test_overflow_holds_instead_of_truncating_evidence(storage):
    company = "event-limit-" + uuid4().hex
    variants = [
        (f"e{i}.xml", event_xml(guid=f"{i:08x}-aaaa-aaaa-aaaa-aaaaaaaaaaaa", number="32600000001"))
        for i in range(101)
    ]
    prepared = ready(event_xml()).model_copy(update={"archives": (zip_bytes(variants),)})
    ingest_event223_window(storage, company, prepared, actor_id="test", now=NOW)
    result = state(storage, company)
    assert result.operation_hold and result.evidence_status == "UNKNOWN"
    assert "EVENT_EVIDENCE_LIMIT" in result.reason_codes and len(result.events) <= 100


def test_downgrade_preserves_any_tenant_event_history(storage):
    company = "event-downgrade-" + uuid4().hex
    store(storage, company, event_xml(number="32600000001"))
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261003_02_eis_223_events",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 cancellation history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    assert counts(storage, company) == before
