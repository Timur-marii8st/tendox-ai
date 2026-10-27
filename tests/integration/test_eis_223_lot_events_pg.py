"""Isolated synthetic PostgreSQL lot-event slice and consumer regression gates."""

from uuid import uuid4

import pytest
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.sources.eis_223_events import Eis223EventSchemaCheck
from procurement.sources.eis_223_lot_event_policy import selected_lot_cancellation_state
from procurement.sources.eis_223_lot_event_sync import Eis223LotEventReadyWindow
from procurement.sources.eis_223_lot_events import parse_purchase_lot_cancellation_xml
from procurement.sources.eis_223_schema import SCHEMAS, VALIDATOR
from procurement.storage.eis_223_comparison import read_comparison223_row
from procurement.storage.eis_223_document_queue import next_document223, plan_document223_job
from procurement.storage.eis_223_documents import collect_document223, read_document223_status
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.eis_223_lot_events import (
    ingest_lot_event223_window,
    read_lot_event223_states,
    record_lot_event_schema_check,
)
from procurement.storage.eis_223_sync import due_windows, record_attempt
from procurement.storage.eis_source_estimate import SourceEstimateRequest, get_source_estimate
from procurement.storage.models import (
    audit_events,
    eis_223_lot_event_schema_checks,
    eis_223_lot_event_windows,
    eis_223_lot_events,
)
from test_eis_223_index import NOW, URL, window
from test_eis_223_lot_events import lot_event_xml, zip_bytes

NUMBER = "32600000001"


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def raw(number=NUMBER):
    return lot_event_xml().replace(b"12345678901", number.encode())


def ready(content, response="a" * 64):
    return Eis223LotEventReadyWindow(
        window_key="getDocsIP/RI223/50/2026-10-01+03:00/purchaseLotCancellation",
        response_sha256=response,
        prepared_sha256="b" * 64,
        archive_urls=(URL,),
        archives=(zip_bytes([("lot.xml", content)]),),
    )


def store(storage, company, content=None, response="a" * 64):
    return ingest_lot_event223_window(
        storage, company, ready(content or raw(), response), actor_id="test", now=NOW
    )


def state(storage, company, number=NUMBER):
    with storage.transaction(company, consistent_read=True) as conn:
        return read_lot_event223_states(conn, company, (number,), now=NOW)[number]


def counts(storage, company):
    with storage.transaction(company) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t).where(t.c.company_id == company))
            for t in (
                eis_223_lot_event_windows,
                eis_223_lot_events,
                eis_223_lot_event_schema_checks,
                audit_events,
            )
        )


def quality(storage, company, content):
    event = parse_purchase_lot_cancellation_xml(content, source_member="lot.xml")
    for release, policy in SCHEMAS.items():
        check = Eis223EventSchemaCheck(
            event_guid=event.event_guid.value,
            purchase_number=event.purchase_number,
            xml_sha256=event.xml_sha256,
            schema_release=release,
            package_sha256=policy[0],
            root_sha256=policy[1],
            tree_sha256=policy[2],
            validator_version=VALIDATOR,
            status="PASS",
            diagnostics=(),
            checked_at=NOW,
        )
        assert record_lot_event_schema_check(storage, company, check, actor_id="test")
        before = counts(storage, company)
        assert not record_lot_event_schema_check(storage, company, check, actor_id="test")
        assert counts(storage, company) == before


def test_event_before_notice_replay_rls_and_full_quality_still_unknown(storage):
    company = "lot-before-" + uuid4().hex
    assert store(storage, company).new_events == 1
    before = counts(storage, company)
    assert store(storage, company).replayed
    assert counts(storage, company) == before
    assert not state(storage, "other-" + company).operation_hold
    with storage.transaction("other-" + company) as conn:
        assert conn.execute(select(eis_223_lot_events)).first() is None
    quality(storage, company, raw())
    result = state(storage, company)
    assert result.source_schema_status == "PASS" and result.operation_hold
    assert (
        result.application_status
        == result.evidence_status
        == result.current_procedure_status
        == "UNKNOWN"
    )


def test_same_guid_cross_purchase_variants_retained_and_held(storage):
    company = "lot-conflict-" + uuid4().hex
    store(storage, company)
    result = store(storage, company, raw("32600000002"), "c" * 64)
    assert result.guid_conflicts == result.new_events == 1
    for number in (NUMBER, "32600000002"):
        result = state(storage, company, number)
        assert len(result.events) == 2 and result.operation_hold
        assert "LOT_EVENT_GUID_TARGET_CONFLICT" in result.reason_codes


@pytest.mark.parametrize("operation", [update, delete])
def test_lot_evidence_is_immutable(storage, operation):
    company = "lot-immutable-" + uuid4().hex
    store(storage, company)
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        query = operation(eis_223_lot_events).where(eis_223_lot_events.c.company_id == company)
        if operation is update:
            query = query.values(purchase_number="32600000002")
        conn.execute(query)


def test_unsafe_full_window_rolls_back(storage):
    company = "lot-unsafe-" + uuid4().hex
    prepared = ready(raw()).model_copy(
        update={"archives": (zip_bytes([("ok.xml", raw()), ("../bad.xml", raw())]),)}
    )
    before = counts(storage, company)
    with pytest.raises(ValueError):
        ingest_lot_event223_window(storage, company, prepared, actor_id="test", now=NOW)
    assert counts(storage, company) == before


def test_shared_consumer_hold_not_whole_fail_or_price_override(storage):
    company = "lot-consumer-" + uuid4().hex
    ingest_notice223_window(storage, company, window(), actor_id="test", now=NOW)
    lead = search_notice223_index(storage, company, "бумага", now=NOW).matched[0]
    ref = Notice223DocumentRef(
        purchase_number=lead.notice.purchase_number,
        version_number=lead.notice.version_number,
        notice_xml_sha256=lead.notice.xml_sha256,
    )
    plan_document223_job(storage, company, ref, actor_id="test")
    store(storage, company)
    quality(storage, company, raw())
    before = counts(storage, company)
    lead = search_notice223_index(storage, company, "бумага", now=NOW).matched[0]
    assert lead.application_status == "UNKNOWN" and lead.lot_cancellation_state.operation_hold
    assert not lead.cancellation_state.operation_hold
    with storage.transaction(company, consistent_read=True) as conn:
        documents = read_document223_status(conn, company, ref, now=NOW)
        comparison = read_comparison223_row(conn, company, ref, now=NOW)
    assert documents.queue_status == "BLOCKED" and comparison.readiness_status == "BLOCKED"
    assert "LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED" in documents.blocked_reasons
    assert next_document223(storage, company, NOW) is None

    def forbidden(*args):
        raise AssertionError("held lot event must not fetch")

    with pytest.raises(ValueError, match="LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED"):
        collect_document223(storage, company, ref, "any", actor_id="test", downloader=forbidden)
    from test_eis_source_estimate import request

    body = request("223").model_dump()
    body["notice"] = {"law": "223", **ref.model_dump()}
    estimate = get_source_estimate(
        storage, company, SourceEstimateRequest.model_validate(body), actor_id="test", now=NOW
    )
    assert estimate.estimate.status == "BLOCKED" and not estimate.estimate.scenarios
    assert estimate.selected_lot_cancellation_state.operation_hold
    assert estimate.selected_lot_cancellation_state.application_status == "UNKNOWN"
    assert "LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED" not in estimate.blocking_reasons
    assert "LOT_CANCELLATION_IDENTITY_UNRESOLVED" in estimate.blocking_reasons
    assert counts(storage, company) == before
    from test_eis_223_archive import xml

    newer = xml().replace(b"<p:version>2</p:version>", b"<p:version>3</p:version>")
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("new.xml", newer)]), response="d" * 64),
        actor_id="test",
        now=NOW,
    )
    assert (
        search_notice223_index(storage, company, "бумага", now=NOW)
        .matched[0]
        .lot_cancellation_state.operation_hold
    )


def test_real_family_journal_checkpoint_and_shared_ten_targets(storage):
    company = "lot-journal-" + uuid4().hex
    key = ready(raw()).window_key
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
    store(storage, company)
    record_attempt(
        storage, company, key, "SYNCED", actor_id="test", checked_at=NOW, response_sha256="a" * 64
    )
    targets = due_windows(storage, company, NOW, include_events=True)
    assert (
        len(targets) == 13
        and sum(t.document_type == "purchaseLotCancellation" for t in targets) == 1
    )


def test_snapshot_byte_budget_holds_before_large_json_materialization(storage, monkeypatch):
    import procurement.storage.eis_223_lot_events as module

    company = "lot-bytes-" + uuid4().hex
    store(storage, company)
    monkeypatch.setattr(module, "MAX_EVENT_SNAPSHOT_BYTES", 1)
    result = state(storage, company)
    assert (
        result.operation_hold
        and not result.events
        and "EVENT_EVIDENCE_LIMIT" in result.reason_codes
    )
    from test_eis_223_archive import parse_notice223_xml, xml

    assert selected_lot_cancellation_state(
        parse_notice223_xml(xml(), source_member="notice.xml"), 1, result
    ).operation_hold


def test_downgrade_cannot_drop_lot_history_in_any_tenant(storage):
    company = "lot-downgrade-" + uuid4().hex
    store(storage, company)
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261003_03_eis_223_lot_events",
        expected_database="procurement_eis_test_20261005_s209",
        match="lot cancellation history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    assert counts(storage, company) == before
