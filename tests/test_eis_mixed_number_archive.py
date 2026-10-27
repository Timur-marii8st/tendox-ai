"""Mixed exact-number archives preserve all metadata without granting participation."""

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources.eis_feed_archive import COMPANION_TYPES, EisFeedArchiveError
from procurement.sources.eis_index_search import compare_indexed_notices
from procurement.sources.eis_procedure_state import resolve_procedure_state
from procurement.storage.eis_notice_index import (
    bind_ready_window,
    ingest_ready_window,
    preflight_ready_window,
)
from test_eis_notice_index import URL, WINDOW, _responses, _zip
from test_eis_procedure_state import event_zip, parse

NUMBER = "0848300054826000991"
OTHER = "0848300054826000992"
NOW = datetime(2026, 10, 5, tzinfo=UTC)
EP = "http://zakupki.gov.ru/oos/EPtypes/1"
OOS = "http://zakupki.gov.ru/oos/types/1"


def companion(kind, number=NUMBER, *, namespace=None, published="2026-10-04T15:00:00+03:00"):
    ns = namespace or (OOS if kind == "fcsPlacementResult" else EP)
    result = kind in {"fcsPlacementResult", "fcsProposalsResult"}
    field = "docPublishDTInEIS" if kind == "epClarificationDoc" else "publishDTInEIS"
    fields = f"<n:purchaseNumber>{number}</n:purchaseNumber>"
    if result:
        fields += f"<n:versionNumber>0</n:versionNumber><n:createDate>{published}</n:createDate>"
    else:
        fields = f"<n:commonInfo>{fields}<n:{field}>{published}</n:{field}></n:commonInfo>"
    return (
        '<export xmlns="http://zakupki.gov.ru/oos/export/1">'
        f'<{kind} xmlns:n="{ns}">{fields}</{kind}></export>'
    ).encode()


def mixed(*documents, number=NUMBER):
    out = BytesIO()
    with ZipFile(out, "w") as archive:
        with ZipFile(BytesIO(_zip(number))) as notice:
            archive.writestr("notice.xml", notice.read("notice.xml"))
        for index, document in enumerate(documents):
            archive.writestr(f"companion-{index}.xml", document)
    return out.getvalue()


def window(raw, number=NUMBER):
    initial, prepared = _responses()
    initial = replace(initial, kind="BY_NUMBER")
    return bind_ready_window(f"getDocsIP/PRIZ/by-number/{number}", initial, prepared, {URL: raw})


@pytest.mark.parametrize("kind", COMPANION_TYPES)
def test_metadata_family_has_exact_xml_and_publication_semantics(kind):
    xml = companion(kind)
    inspection = preflight_ready_window(window(mixed(xml))).inspections[0]
    assert len(inspection.records) == len(inspection.events) == 1
    event = inspection.events[0]
    assert event.purchase_number == NUMBER
    assert event.xml_sha256 == hashlib.sha256(xml).hexdigest()
    assert event.document_id == f"sha256:{event.xml_sha256}"
    assert event.parser_version == "eis-companion-document-v1"
    assert (event.published_at is None) == kind.startswith("fcs")
    assert (
        resolve_procedure_state((event,), purchase_number=NUMBER, now=NOW).application_status
        == "UNKNOWN"
    )


@pytest.mark.parametrize("kind", COMPANION_TYPES)
def test_foreign_number_in_any_family_blocks_entire_set(kind):
    with pytest.raises(ValueError, match="BY_NUMBER_PURCHASE_MISMATCH"):
        preflight_ready_window(window(mixed(companion(kind, OTHER))))


def test_mixed_all_members_are_admitted_only_by_number():
    raw = mixed(*(companion(kind) for kind in COMPANION_TYPES))
    flight = preflight_ready_window(window(raw))
    assert flight.notice_count == 1 + len(COMPANION_TYPES)
    assert len(flight.inspections[0].events) == len(COMPANION_TYPES)
    initial, prepared = _responses()
    with pytest.raises(EisFeedArchiveError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_ready_window(bind_ready_window(WINDOW, initial, prepared, {URL: raw}))


def _assert_protocol_retained_without_masking_cancellation(kind):
    xml = companion(kind)
    raw = mixed(xml)
    inspection = preflight_ready_window(window(raw)).inspections[0]
    assert inspection.archive_sha256 == hashlib.sha256(raw).hexdigest()
    assert len(inspection.records) == len(inspection.events) == 1
    final = inspection.events[0]
    assert final.document_type == kind
    assert final.document_id == "sha256:" + hashlib.sha256(xml).hexdigest()
    assert final.locator == kind + "/commonInfo/purchaseNumber"
    assert final.published_at == datetime.fromisoformat("2026-10-04T15:00:00+03:00")
    cancel = parse(event_zip(number=NUMBER))
    state = resolve_procedure_state((cancel, final), purchase_number=NUMBER, now=NOW)
    assert state.application_status == "FAIL"
    assert any(final.xml_sha256 in reason for reason in state.reasons)


def test_ezk_final_is_retained_with_notice_and_cannot_mask_cancellation():
    _assert_protocol_retained_without_masking_cancellation("epProtocolEZK2020Final")


@pytest.mark.parametrize("kind", ["epProtocolEF2020SubmitOffers", "epProtocolEF2020Final"])
def test_ea_protocol_is_retained_without_masking_cancellation(kind):
    _assert_protocol_retained_without_masking_cancellation(kind)


@pytest.mark.parametrize("namespace", ["urn:forged", "http://zakupki.gov.ru/oos/export/1"])
def test_namespace_spoof_is_not_number_evidence(namespace):
    with pytest.raises(EisFeedArchiveError, match="COMPANION_FIELD_NAMESPACE_INVALID"):
        preflight_ready_window(window(mixed(companion(COMPANION_TYPES[0], namespace=namespace))))


def _assert_protocol_namespace_spoof_rejected(namespace, kind):
    with pytest.raises(EisFeedArchiveError, match="COMPANION_FIELD_NAMESPACE_INVALID"):
        preflight_ready_window(window(mixed(companion(kind, namespace=namespace))))


@pytest.mark.parametrize("namespace", ["urn:forged", "http://zakupki.gov.ru/oos/export/1"])
def test_ezk_final_namespace_spoof_is_rejected(namespace):
    _assert_protocol_namespace_spoof_rejected(namespace, "epProtocolEZK2020Final")


@pytest.mark.parametrize("namespace", ["urn:forged", "http://zakupki.gov.ru/oos/export/1"])
@pytest.mark.parametrize("kind", ["epProtocolEF2020SubmitOffers", "epProtocolEF2020Final"])
def test_ea_protocol_namespace_spoof_is_rejected(namespace, kind):
    _assert_protocol_namespace_spoof_rejected(namespace, kind)


def test_nested_number_and_unknown_member_are_not_silently_skipped():
    xml = companion(COMPANION_TYPES[0]).replace(
        f"<n:purchaseNumber>{NUMBER}</n:purchaseNumber>".encode(),
        f"<n:extra><n:purchaseNumber>{NUMBER}</n:purchaseNumber></n:extra>".encode(),
    )
    with pytest.raises(EisFeedArchiveError, match="FIELD_MISSING_OR_DUPLICATE"):
        preflight_ready_window(window(mixed(xml)))
    with pytest.raises(EisFeedArchiveError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_ready_window(window(mixed(companion("epUnknown"))))


def test_duplicate_event_and_missing_publication_never_create_pass():
    xml = companion(COMPANION_TYPES[0])
    with pytest.raises(EisFeedArchiveError, match="DUPLICATE_PROCEDURE_EVENT"):
        preflight_ready_window(window(mixed(xml, xml)))
    event = (
        preflight_ready_window(
            window(mixed(companion(COMPANION_TYPES[0], published="2026-10-04T15:00:00")))
        )
        .inspections[0]
        .events[0]
    )
    assert event.published_at is None


def test_later_metadata_never_masks_cancel_and_expired_notice_is_failed():
    inspection = preflight_ready_window(window(mixed(companion(COMPANION_TYPES[3])))).inspections[0]
    cancel = parse(event_zip(number=NUMBER))
    state = resolve_procedure_state((cancel, *inspection.events), purchase_number=NUMBER, now=NOW)
    assert state.application_status == "FAIL"
    assert any(inspection.events[0].xml_sha256 in reason for reason in state.reasons)
    notice = replace(inspection.records[0], deadline=NOW - timedelta(seconds=1))
    result = compare_indexed_notices(
        (notice,),
        "бумага",
        now=NOW,
        procedure_states={
            NUMBER: resolve_procedure_state(inspection.events, purchase_number=NUMBER, now=NOW)
        },
    )
    assert result.matched_notices[0].application_status == "FAIL"


def test_isolated_pg_atomic_complete_metadata_index_replay_and_constraints():
    urls = [os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")]
    if not all(urls):
        pytest.skip("isolated PostgreSQL required")
    if any("procurement_eis_test_" not in url for url in urls):
        pytest.fail("explicit isolated DB required")
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.exc import IntegrityError

    from procurement.storage.eis_document_store import NoticeDocumentRef, plan_document_job
    from procurement.storage.models import (
        eis_notice_search_keys,
        eis_notice_versions,
        eis_procedure_events,
    )
    from procurement.storage.repository import PostgresStorage

    engine = create_engine(urls[0])
    storage = PostgresStorage(engine)
    raw = mixed(*(companion(kind) for kind in COMPANION_TYPES))
    bound = window(raw)
    try:
        report = ingest_ready_window(storage, "s202-synthetic", bound, actor_id="synthetic")
        assert report.new_versions == 1 and report.new_events == len(COMPANION_TYPES)
        replay = ingest_ready_window(storage, "s202-synthetic", bound, actor_id="synthetic")
        assert replay.replayed and replay.new_versions == replay.new_events == 0
        with storage.transaction("s202-synthetic", consistent_read=True) as conn:
            assert conn.scalar(select(func.count()).select_from(eis_notice_versions)) == 1
            assert conn.scalar(select(func.count()).select_from(eis_notice_search_keys)) == 1
            events = conn.execute(select(eis_procedure_events)).mappings().all()
            notice = conn.execute(select(eis_notice_versions)).mappings().one()
        assert len(events) == len(COMPANION_TYPES)
        ref = NoticeDocumentRef(
            purchase_number=NUMBER, version_number=1, notice_xml_sha256=notice["xml_sha256"]
        )
        assert plan_document_job(storage, "s202-synthetic", ref, actor_id="synthetic").notice == ref
        with storage.transaction("foreign-s202", consistent_read=True) as conn:
            assert conn.scalar(select(func.count()).select_from(eis_procedure_events)) == 0
        with pytest.raises(IntegrityError), storage.transaction("s202-synthetic") as conn:
            row = dict(events[0])
            row["document_id"] = "forged-id"
            conn.execute(eis_procedure_events.insert().values(**row))
        with pytest.raises(ValueError), storage.transaction("s202-rejected") as conn:
            ingest_ready_window(
                storage,
                "s202-rejected",
                window(mixed(companion(COMPANION_TYPES[0], OTHER))),
                actor_id="synthetic",
            )
        with storage.transaction("s202-rejected", consistent_read=True) as conn:
            assert conn.scalar(select(func.count()).select_from(eis_notice_versions)) == 0
    finally:
        engine.dispose()
