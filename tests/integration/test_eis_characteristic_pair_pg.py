"""Exact tenant/provenance and byte gates for source0 selected pair reads."""

import os
from datetime import date
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from test_eis_analogs_pg import NOW, archive
from test_eis_notice_index_pg import storage as storage_fixture
from test_eis_notice_projection_pg import prepare

from procurement.sources.eis_characteristic_compare import (
    CharacteristicPairRequest,
    PositionSelection,
)
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.eis_characteristic_compare import read_characteristic_pair
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.eis_position_projection import project_notice_positions
from procurement.storage.models import (
    audit_events,
    eis_document_jobs,
    eis_notice_position_projections,
)

GATE_DATABASE = "procurement_eis_test_20261005_s209"


@pytest.fixture(scope="module")
def storage():
    for key in ("DATABASE_URL", "DATABASE_ADMIN_URL"):
        if not os.environ.get(key):
            pytest.skip("Requires isolated PostgreSQL gate database")
        assert make_url(os.environ[key]).database == GATE_DATABASE
    yield from storage_fixture.__wrapped__()


def characteristic(value="80"):
    return f"""<characteristics><characteristicsUsingReferenceInfo>
<name>Плотность</name><characteristicsFillingInstruction><code>1</code></characteristicsFillingInstruction>
<values><value><valueSet><concreteValue>{value}</concreteValue></valueSet>
<OKEI><name>г/м2</name></OKEI></value></values>
</characteristicsUsingReferenceInfo></characteristics>"""


def ingest(storage, company, number, value="80"):
    raw = archive(number)
    with ZipFile(BytesIO(raw)) as source:
        xml = source.read("notice.xml").replace(
            b"</KTRU>", characteristic(value).encode() + b"</KTRU>"
        )
    output = BytesIO()
    with ZipFile(output, "w") as target:
        target.writestr("notice.xml", xml)
    selection = EisDateSelection("50", date(2026, 1, int(number[0]) + 1), 3)
    window = EisReadyWindow(selection.window_key, "a" * 64, 1, (output.getvalue(),))
    record = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="synthetic")
    return NoticeDocumentRef(
        purchase_number=number, version_number=1, notice_xml_sha256=record.xml_sha256
    )


def request(target, candidate=None):
    return CharacteristicPairRequest(
        target=PositionSelection(notice=target, source_index=1),
        candidate=PositionSelection(notice=candidate or target, source_index=1),
    )


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t))
            for t in (audit_events, eis_document_jobs, eis_notice_position_projections)
        )


def test_saved_fields_exact_decimal_and_read_only_without_archive_or_jobs(storage):
    company = "s210-" + uuid4().hex
    target = ingest(storage, company, "1" * 19)
    before = counts(storage, company)
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith(("SELECT", "WITH")):
            assert conn.scalar(text("SHOW transaction_read_only")) == "on"
            assert conn.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", track)
    try:
        report = read_characteristic_pair(storage, company, request(target), now=NOW)
    finally:
        event.remove(storage._engine, "before_cursor_execute", track)
    assert report.rows[0].observation == "SAME"
    assert report.source_requests == 0 and report.technical == report.participation == "UNKNOWN"
    assert report.target.storage_kind == "SAVED_NOTICE_FIELDS"
    assert counts(storage, company) == before
    assert not any("eis_feed_archives" in sql or "INSERT" in sql for sql in statements)


def test_two_exact_saved_positions_compare_differing_values_without_technical_verdict(storage):
    company = "s210-" + uuid4().hex
    target = ingest(storage, company, "1" * 19)
    candidate = ingest(storage, company, "2" * 19, "95")
    report = read_characteristic_pair(storage, company, request(target, candidate), now=NOW)
    assert report.rows[0].observation == "DIFFERENT"
    assert report.technical == report.comparability == report.profit == "UNKNOWN"
    assert report.rows[0].target_provenance.document_id == target.notice_xml_sha256
    assert report.rows[0].candidate_provenance.document_id == candidate.notice_xml_sha256


@pytest.mark.parametrize("kind", ["foreign", "sha", "position"])
def test_unavailable_exact_reference_is_error(storage, kind):
    company = "s210-" + uuid4().hex
    target = ingest(storage, company, "1" * 19)
    payload = request(target)
    if kind == "foreign":
        company = "foreign-" + company
    elif kind == "sha":
        bad = NoticeDocumentRef(
            purchase_number=target.purchase_number, version_number=1, notice_xml_sha256="f" * 64
        )
        payload = request(bad)
    else:
        payload = CharacteristicPairRequest(
            target=PositionSelection(notice=target, source_index=2), candidate=payload.candidate
        )
    with pytest.raises(
        ValueError, match=r"CHARACTERISTIC_(NOTICE_NOT_FOUND_OR_MISMATCH|POSITION_NOT_FOUND)"
    ):
        read_characteristic_pair(storage, company, payload, now=NOW)


def test_retained_unresolved_origin_blocks_even_matching_values(storage, tmp_path):
    from test_eis_notice_conflicts import notice

    company = "s210-" + uuid4().hex
    target = ingest(storage, company, "1" * 19)
    xml = notice(title="Бумага").replace(b"0373100047426001450", b"1" * 19)
    prepare(storage, company, tmp_path, members=(("conflict.xml", xml),))
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_characteristic_pair(storage, company, request(target), now=NOW)


def test_notice_byte_guard_precedes_payload_hydration(storage, monkeypatch):
    import procurement.storage.eis_characteristic_compare as reader

    company = "s210-" + uuid4().hex
    target = ingest(storage, company, "1" * 19)
    monkeypatch.setattr(reader, "MAX_NOTICE_BYTES", 1)
    with pytest.raises(ValueError, match="CHARACTERISTIC_NOTICE_PAYLOAD_LIMIT"):
        read_characteristic_pair(storage, company, request(target), now=NOW)


def test_legacy_concrete_values_remain_unknown_until_explicit_saved_projection(
    storage, monkeypatch
):
    import procurement.storage.eis_notice_index as writer

    company = "s210-" + uuid4().hex
    original = writer.asdict

    def legacy(value):
        result = original(value)
        for c in result.get("characteristics", []):
            for v in c["values"]:
                v.pop("concrete_values", None)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(writer, "asdict", legacy)
        target = ingest(storage, company, "1" * 19)
    report = read_characteristic_pair(storage, company, request(target), now=NOW)
    assert report.target.legacy_values_unknown and report.rows[0].observation == "UNKNOWN"
    assert project_notice_positions(storage, company, target, actor_id="synthetic")
    report = read_characteristic_pair(storage, company, request(target), now=NOW)
    assert not report.target.legacy_values_unknown and report.rows[0].observation == "SAME"


@pytest.mark.parametrize("fault", [None, "digest", "bytes"])
def test_saved_concrete_projection_checked_and_read_without_writes(storage, monkeypatch, fault):
    import procurement.storage.eis_characteristic_compare as reader
    import procurement.storage.eis_position_projection as writer

    company = "s210-" + uuid4().hex
    target = ingest(storage, company, "1" * 19)
    if fault == "digest":
        monkeypatch.setattr(writer, "_digest", lambda payload: "f" * 64)
    assert project_notice_positions(storage, company, target, actor_id="synthetic")
    before = counts(storage, company)
    if fault == "bytes":
        monkeypatch.setattr(reader, "MAX_PROJECTION_BYTES", 1)
    if fault:
        with pytest.raises(
            ValueError, match=r"CHARACTERISTIC_PROJECTION_(DIGEST_MISMATCH|PAYLOAD_LIMIT)"
        ):
            read_characteristic_pair(storage, company, request(target), now=NOW)
    else:
        report = read_characteristic_pair(storage, company, request(target), now=NOW)
        assert (
            report.target.storage_kind == "SAVED_PROJECTION"
            and report.rows[0].observation == "SAME"
        )
    assert counts(storage, company) == before
