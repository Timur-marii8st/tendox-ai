"""Drug derivation is atomic, source bound and separate from canonical replay."""

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import event, func, select
from test_eis_notice_hold_pg import hold
from test_eis_notice_index_pg import storage as storage_fixture
from test_eis_notice_projection_pg import prepare

from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_global_price import GlobalPriceOptions, search_global_price
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_index import EisReadyWindow, ingest_ready_window
from procurement.storage.eis_notice_projection import project_retained_notice_variants
from procurement.storage.eis_position_projection import (
    project_notice_positions,
    read_position_projection,
    read_position_projection_page,
)
from procurement.storage.models import (
    audit_events,
    eis_notice_position_projections,
    eis_notice_versions,
)
from test_eis_drug_positions import drug, source


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def fixture():
    notice, xml = source(drug(undefined=True) + drug(quantity="5625"))
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("notice.xml", xml)
    window = EisReadyWindow("getDocsIP/PRIZ/50/2026-10-26+03:00", "a" * 64, 1, (output.getvalue(),))
    ref = NoticeDocumentRef(
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
    )
    return window, ref, xml


def counts(storage, company):
    with storage.transaction(company) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t))
            for t in (eis_notice_versions, eis_notice_position_projections, audit_events)
        )


def test_new_intake_projection_search_and_replay_are_source_bound(storage, monkeypatch):
    company = "drug-" + uuid4().hex
    window, ref, _ = fixture()
    assert ingest_ready_window(storage, company, window, actor_id="test").new_versions == 1
    before = counts(storage, company)
    assert ingest_ready_window(storage, company, window, actor_id="test").replayed
    assert not project_notice_positions(storage, company, ref, actor_id="test")
    assert counts(storage, company) == before
    with storage.transaction(company) as conn:
        canonical = conn.execute(select(eis_notice_versions)).mappings().one()
        assert canonical["lot_items"] == [] and canonical["lot_parse_status"] == "UNKNOWN"
        positions = read_position_projection(conn, company, ref)
        assert positions is not None and positions.positions_total == 2
        assert positions.positions[0].quantity.value is None
        assert str(positions.positions[1].quantity.value) == "5625"
    with pytest.raises(LookupError):
        project_notice_positions(storage, "other-" + company, ref, actor_id="test")

    # GET must not invoke the XML parser, enqueue jobs or persist facts.
    def forbidden(*args, **kwargs):
        raise AssertionError("GET_PARSED_SOURCE")

    monkeypatch.setattr("procurement.storage.eis_position_projection.drug_positions44", forbidden)
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", capture)
    try:
        now = datetime.now(UTC)
        for _ in range(2):
            result = search_eis_index(storage, company, ref.purchase_number, now=now, paginate=True)
            assert result.matched[0].position_set == positions
            assert result.matched[0].lot_items == ()
        assert not any("eis_feed_archives.content" in s for s in statements)
        priced = search_global_price(
            storage, company, GlobalPriceOptions(query=ref.purchase_number, law="44"), now=now
        )
        assert priced.result44.matched[0].position_set == positions
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture)
    assert not any(
        s.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for s in statements
    )
    assert counts(storage, company) == before


def test_existing_empty_canonical_requires_explicit_idempotent_projection(storage, monkeypatch):
    company = "drug-old-" + uuid4().hex
    window, ref, _ = fixture()
    with monkeypatch.context() as m:
        m.setattr(
            "procurement.storage.eis_position_projection.derive_new_drug_positions",
            lambda *args, **kwargs: False,
        )
        ingest_ready_window(storage, company, window, actor_id="old-version")
    before = counts(storage, company)
    assert ingest_ready_window(storage, company, window, actor_id="new-version").replayed
    assert counts(storage, company) == before
    clock = datetime.now(UTC)
    assert (
        search_eis_index(storage, company, ref.purchase_number, now=clock, paginate=True)
        .matched[0]
        .position_set
        is None
    )
    assert project_notice_positions(storage, company, ref, actor_id="source0-backfill")
    assert (
        search_eis_index(storage, company, ref.purchase_number, now=clock, paginate=True)
        .matched[0]
        .position_set.positions_total
        == 2
    )
    after = counts(storage, company)
    assert after == (before[0], before[1] + 1, before[2] + 1)
    assert not project_notice_positions(storage, company, ref, actor_id="source0-backfill")
    assert counts(storage, company) == after


def test_variant_writer_derives_only_after_authenticated_admission(storage, tmp_path):
    company = "drug-variant-" + uuid4().hex
    _, ref, xml = fixture()
    receipt, archives, _ = prepare(storage, company, tmp_path, members=(("notice.xml", xml),))
    report = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    )
    assert report.projected_count == 1 and report.held_count == 0
    with storage.transaction(company) as conn:
        positions = read_position_projection(conn, company, ref)
        assert positions is not None and positions.positions_total == 2
    before = counts(storage, company)
    assert project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    ).replayed
    assert counts(storage, company) == before


def test_derivation_failure_rolls_back_new_canonical_transaction(storage, monkeypatch):
    company = "drug-rollback-" + uuid4().hex
    window, _, _ = fixture()
    before = counts(storage, company)

    def broken(*args, **kwargs):
        raise ValueError("SYNTHETIC_DERIVATION_FAILURE")

    monkeypatch.setattr("procurement.storage.eis_position_projection.drug_positions44", broken)
    with pytest.raises(ValueError, match="SYNTHETIC_DERIVATION_FAILURE"):
        ingest_ready_window(storage, company, window, actor_id="test")
    assert counts(storage, company) == before


def test_unresolved_newer_variant_keeps_new_canonical_without_drug_derivation(storage, tmp_path):
    company = "drug-held-" + uuid4().hex
    window, ref, _ = fixture()
    hold(storage, company, tmp_path, ref, version=2)
    assert ingest_ready_window(storage, company, window, actor_id="test").new_versions == 1
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_notice_versions)) == 1
        assert conn.scalar(select(func.count()).select_from(eis_notice_position_projections)) == 0
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        project_notice_positions(storage, company, ref, actor_id="test")
    assert not search_eis_index(
        storage, company, ref.purchase_number, now=datetime.now(UTC)
    ).matched


def test_same_batch_newer_hold_does_not_rollback_admitted_older_snapshot(storage, tmp_path):
    company = "drug-batch-held-" + uuid4().hex
    _, ref, xml = fixture()
    v2 = xml.replace(b"<p:versionNumber>1", b"<p:versionNumber>2")
    receipt, archives, _ = prepare(
        storage,
        company,
        tmp_path,
        members=(
            ("notice.xml", xml),
            ("v2.xml", v2),
            ("v2b.xml", v2.replace(b"5625", b"5626")),
        ),
    )
    report = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    )
    assert report.projected_count == 1 and report.held_count == 1
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_notice_versions)) == 1
        assert conn.scalar(select(func.count()).select_from(eis_notice_position_projections)) == 0
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        project_notice_positions(storage, company, ref, actor_id="test")
    before = counts(storage, company)
    assert project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    ).replayed
    assert counts(storage, company) == before


def test_search_checks_projection_size_before_json_hydration(storage):
    company = "drug-size-" + uuid4().hex
    _, xml = source(drug(name="N" * 4000, unit="U" * 4000) * 25)
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("notice.xml", xml)
    window = EisReadyWindow("getDocsIP/PRIZ/50/2026-10-26+03:00", "a" * 64, 1, (output.getvalue(),))
    ingest_ready_window(storage, company, window, actor_id="test")
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", capture)
    try:
        result = search_eis_index(storage, company, "0123456789026000001", now=datetime.now(UTC))
        assert result.matched and result.matched[0].position_set is None
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture)
    metadata = [s for s in statements if "eis_notice_position_projections" in s]
    assert metadata and all("octet_length(CAST(" in s for s in metadata)


def test_projection_page_bounds_and_constant_queries_for_100_missing_refs(storage):
    company = "drug-page-" + uuid4().hex
    refs = tuple(
        NoticeDocumentRef(
            purchase_number=f"0123456789026{i:06d}", version_number=1, notice_xml_sha256="a" * 64
        )
        for i in range(100)
    )
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    with storage.transaction(company, consistent_read=True) as conn:
        event.listen(storage._engine, "before_cursor_execute", capture)
        try:
            assert read_position_projection_page(conn, company, refs) == (None,) * 100
            assert len(statements) == 2
        finally:
            event.remove(storage._engine, "before_cursor_execute", capture)
        with pytest.raises(ValueError, match="POSITION_PAGE_SIZE_LIMIT"):
            read_position_projection_page(conn, company, (*refs, refs[0]))
        with pytest.raises(ValueError, match="POSITION_PAGE_DUPLICATE_REF"):
            read_position_projection_page(conn, company, (refs[0], refs[0]))
    populated = []
    for i in range(10):
        _, xml = source(drug(name="N" * 1000, unit="U" * 1000) * 25)
        number = refs[i].purchase_number
        xml = xml.replace(b"0123456789026000001", number.encode())
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("notice.xml", xml)
        digest = hashlib.sha256(xml).hexdigest()
        window = EisReadyWindow(
            "getDocsIP/PRIZ/by-number/" + number, digest, 1, (output.getvalue(),)
        )
        ingest_ready_window(storage, company, window, actor_id="test")
        populated.append(
            NoticeDocumentRef(purchase_number=number, version_number=1, notice_xml_sha256=digest)
        )
    with storage.transaction(company, consistent_read=True) as conn:
        page = read_position_projection_page(conn, company, populated)
        known = [p for p in page if p is not None]
        assert 0 < len(known) < len(populated)
        assert sum(len(p.model_dump_json().encode()) for p in known) <= 2 * 1024**2
        assert all(len(p.model_dump_json().encode()) <= 512 * 1024 for p in known)
        assert read_position_projection_page(conn, "foreign-" + company, populated) == (None,) * 10
        bad = populated[0].model_copy(update={"notice_xml_sha256": "b" * 64})
        with pytest.raises(ValueError, match="POSITION_PROJECTION_DIGEST_MISMATCH"):
            read_position_projection_page(conn, company, (bad,))
