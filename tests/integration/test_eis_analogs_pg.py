"""Historical filters precede LIMIT; exact tenant loads, bytes and source0 invariants."""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from itertools import count
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import Text, event, func, select
from test_eis_notice_index_pg import storage as storage_fixture

from procurement.sources.eis_analogs import AnalogRequest
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.eis_analogs import read_analog_candidates
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.models import audit_events, eis_document_jobs, eis_notice_versions

storage = storage_fixture
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
WINDOW_COUNTER = count()


def archive(
    number,
    *,
    deadline="2026-10-03T12:00:00Z",
    published="2026-10-01T12:00:00Z",
    version=1,
    positions=1,
):
    publication_xml = f"<publishDTInEIS>{published}</publishDTInEIS>" if published else ""
    xml = (
        f"""<export xmlns="http://zakupki.gov.ru/oos/export/1"><epNotificationEF2020>
<versionNumber>{version}</versionNumber><commonInfo><purchaseNumber>{number}</purchaseNumber>
<purchaseObjectInfo>Бумага A4</purchaseObjectInfo>{publication_xml}</commonInfo>
<notificationInfo><procedureInfo><collectingInfo><endDT>{deadline}</endDT></collectingInfo></procedureInfo>
<purchaseObjectsInfo><notDrugPurchaseObjectsInfo>"""
        + "".join(
            """<purchaseObject><name>Бумага A4</name>
<KTRU><code>17.12.14.110-00000001</code><OKPD2><OKPDCode>17.12.14.110</OKPDCode></OKPD2></KTRU>
<quantity><value>100</value></quantity><OKEI><name>пачка</name></OKEI></purchaseObject>"""
            for _ in range(positions)
        )
        + """
</notDrugPurchaseObjectsInfo></purchaseObjectsInfo></notificationInfo></epNotificationEF2020></export>"""
    )
    output = BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr("notice.xml", xml.encode())
    return output.getvalue()


def ingest(storage, company, number, **kwargs):
    selection = EisDateSelection("50", date(2026, 1, 1) + timedelta(days=next(WINDOW_COUNTER)), 3)
    window = EisReadyWindow(selection.window_key, "a" * 64, 1, (archive(number, **kwargs),))
    snapshot = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="synthetic")
    return NoticeDocumentRef(
        purchase_number=number,
        version_number=snapshot.version_number,
        notice_xml_sha256=snapshot.xml_sha256,
    )


def test_historical_and_self_filters_precede_limit_and_read_does_not_mutate(storage):
    company = "s205-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    for i in range(22):
        ingest(
            storage,
            company,
            f"{i + 1:019d}",
            deadline="2026-10-10T12:00:00Z",
            published="2026-10-04T11:00:00Z",
        )
    history = ingest(storage, company, "8" * 19, positions=26)

    def counts():
        with storage.transaction(company, consistent_read=True) as conn:
            return tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_document_jobs, eis_notice_versions)
            )

    before = counts()
    req = AnalogRequest(target=target, source_index=1, query="бумага")
    report = read_analog_candidates(storage, company, req, now=NOW)
    assert report.selected_notices == 1 and report.candidates[0].notice == history
    assert report.evaluated_positions == 25 and report.uninspected_positions == 1
    assert report.review_rows == 25 and report.source_requests == 0 and counts() == before
    with pytest.raises(ValueError, match="TARGET_NOT_FOUND_OR_MISMATCH"):
        read_analog_candidates(storage, "foreign-" + company, req, now=NOW)
    with pytest.raises(ValueError, match="TARGET_NOT_FOUND_OR_MISMATCH"):
        read_analog_candidates(
            storage,
            company,
            req.model_copy(
                update={"target": target.model_copy(update={"notice_xml_sha256": "f" * 64})}
            ),
            now=NOW,
        )
    assert counts() == before


def test_latest_version_and_date_before_limit_with_explicit_truncation(storage):
    company = "s205-limit-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    for i in range(21):
        ingest(storage, company, f"{i + 1:019d}")
    number = "7" * 19
    ingest(storage, company, number, published="2026-10-04T11:59:00Z")
    ingest(storage, company, number, version=2, deadline="2026-10-10T12:00:00Z")
    ingest(storage, company, "9" * 19, published="2026-10-04T12:00:01Z")
    result = read_analog_candidates(
        storage, company, AnalogRequest(target=target, source_index=1, query="бумага"), now=NOW
    )
    assert result.selected_notices == 20 and result.selection_truncated
    assert number not in {c.notice.purchase_number for c in result.candidates}
    assert "9" * 19 not in {c.notice.purchase_number for c in result.candidates}


def test_missing_target_date_returns_unknown_and_source_or_payload_limits_fail(
    storage, monkeypatch
):
    company = "s205-unknown-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published=None)
    req = AnalogRequest(target=target, source_index=1, query="бумага")
    result = read_analog_candidates(storage, company, req, now=NOW)
    assert result.selected_notices == 0 and result.period_start is None
    module = __import__("procurement.storage.eis_analogs", fromlist=["MAX_NOTICE_BYTES"])
    monkeypatch.setattr(module, "MAX_NOTICE_BYTES", 1)
    with pytest.raises(ValueError, match="NOTICE_PAYLOAD_LIMIT"):
        read_analog_candidates(storage, company, req, now=NOW)

    def held(*args, **kwargs):
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")

    monkeypatch.setattr(module, "assert_notice_source_usable", held)
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_analog_candidates(storage, company, req, now=NOW)


@pytest.mark.parametrize(
    "setting,value,reason",
    [
        ("MAX_TOTAL_BYTES", 1, "TOTAL_PAYLOAD_LIMIT"),
        ("MAX_RESPONSE_BYTES", 1, "RESPONSE_LIMIT"),
        ("MAX_READ_SECONDS", -1, "TIME_LIMIT"),
    ],
)
def test_total_output_time_bounds_are_explicit_failures(
    storage, monkeypatch, setting, value, reason
):
    company = "s205-bounds-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    ingest(storage, company, "1" * 19)
    module = __import__("procurement.storage.eis_analogs", fromlist=[setting])
    monkeypatch.setattr(module, setting, value)
    with pytest.raises(ValueError, match=reason):
        read_analog_candidates(
            storage, company, AnalogRequest(target=target, source_index=1, query="бумага"), now=NOW
        )


def test_old_publication_does_not_enter_small_cohort(storage):
    company = "s205-old-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    ingest(storage, company, "1" * 19, published="2025-01-01T12:00:00Z")
    report = read_analog_candidates(
        storage, company, AnalogRequest(target=target, source_index=1, query="бумага"), now=NOW
    )
    assert report.selected_notices == 0 and report.review_rows == 0


def test_candidate_payload_omissions_keep_order_and_allow_later_fit(storage, monkeypatch):
    company = "s216-omissions-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    refs = [
        ingest(
            storage, company, f"{index:019d}", positions=8 if index == 1 else 4 if index == 2 else 1
        )
        for index in range(1, 22)
    ]
    with storage.transaction(company, consistent_read=True) as conn:
        sizes = dict(
            conn.execute(
                select(
                    eis_notice_versions.c.purchase_number,
                    func.octet_length(eis_notice_versions.c.lot_items.cast(Text)),
                ).where(eis_notice_versions.c.company_id == company)
            ).all()
        )
    target_bytes = sizes[target.purchase_number]
    large_bytes = sizes[refs[0].purchase_number]
    medium_bytes = sizes[refs[1].purchase_number]
    small_bytes = sizes[refs[2].purchase_number]
    assert large_bytes > medium_bytes > small_bytes

    module = __import__("procurement.storage.eis_analogs", fromlist=["_notice"])
    monkeypatch.setattr(module, "MAX_NOTICE_BYTES", medium_bytes)
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", target_bytes + small_bytes)
    original_notice = module._notice
    hydrated = []
    hydration_parameters = []

    def capture_hydration(_conn, _cursor, statement, parameters, _context, _executemany):
        if "lot_items" in statement and "octet_length" not in statement:
            hydration_parameters.append(parameters)

    def observed_notice(row):
        hydrated.append(row["purchase_number"])
        if row["purchase_number"] == refs[0].purchase_number:
            raise AssertionError("oversized candidate was hydrated")
        return original_notice(row)

    monkeypatch.setattr(module, "_notice", observed_notice)
    event.listen(storage._engine, "before_cursor_execute", capture_hydration)
    try:
        report = read_analog_candidates(
            storage,
            company,
            AnalogRequest(target=target, source_index=1, query="бумага"),
            now=NOW,
        )
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture_hydration)
    assert report.selection_truncated
    assert len(report.candidates) + len(report.omitted_candidates) == 20
    assert report.omitted_candidates[0].notice == refs[0]
    assert report.omitted_candidates[0].reason == "CANDIDATE_NOTICE_PAYLOAD_LIMIT"
    assert report.omitted_candidates[0].limit_bytes == medium_bytes
    assert report.omitted_candidates[1].notice == refs[1]
    assert report.omitted_candidates[1].reason == "CANDIDATE_TOTAL_PAYLOAD_LIMIT"
    assert report.omitted_candidates[1].limit_bytes == small_bytes
    assert report.candidates[0].notice == refs[2]
    assert refs[20] not in {candidate.notice for candidate in report.candidates}
    assert refs[20] not in {omission.notice for omission in report.omitted_candidates}
    assert refs[0].purchase_number not in hydrated
    rendered_hydration_parameters = repr(hydration_parameters)
    assert refs[0].purchase_number not in rendered_hydration_parameters
    assert refs[1].purchase_number not in rendered_hydration_parameters
    assert refs[2].purchase_number in rendered_hydration_parameters


def test_target_at_notice_cap_and_all_twenty_candidates_omitted_without_refill(
    storage, monkeypatch
):
    company = "s216-all-omitted-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    refs = [
        ingest(storage, company, f"{index:019d}", positions=2) for index in range(1, 22)
    ]
    with storage.transaction(company, consistent_read=True) as conn:
        target_bytes = conn.scalar(
            select(func.octet_length(eis_notice_versions.c.lot_items.cast(Text))).where(
                eis_notice_versions.c.company_id == company,
                eis_notice_versions.c.purchase_number == target.purchase_number,
            )
        )
    module = __import__("procurement.storage.eis_analogs", fromlist=["MAX_NOTICE_BYTES"])
    monkeypatch.setattr(module, "MAX_NOTICE_BYTES", target_bytes)
    report = read_analog_candidates(
        storage,
        company,
        AnalogRequest(target=target, source_index=1, query="бумага"),
        now=NOW,
    )
    assert report.selection_truncated and not report.candidates
    assert len(report.omitted_candidates) == 20
    assert all(
        omission.reason == "CANDIDATE_NOTICE_PAYLOAD_LIMIT"
        and omission.limit_bytes == target_bytes
        and omission.payload_bytes > target_bytes
        for omission in report.omitted_candidates
    )
    assert refs[20] not in {omission.notice for omission in report.omitted_candidates}


def test_actual_source_hold_blocks_target_and_excludes_candidate_before_limit(storage, tmp_path):
    from test_eis_notice_hold_pg import hold

    company = "s205-hold-" + str(uuid4())
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    candidate = ingest(storage, company, "1" * 19)
    hold(storage, company, tmp_path, candidate)
    request = AnalogRequest(target=target, source_index=1, query="бумага")
    assert read_analog_candidates(storage, company, request, now=NOW).selected_notices == 0
    hold(storage, company, tmp_path, target)
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_analog_candidates(storage, company, request, now=NOW)
