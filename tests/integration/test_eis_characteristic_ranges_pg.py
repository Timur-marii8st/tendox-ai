"""Range source completeness requires the new evidence version, with no read writes."""

from datetime import date
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import Text, event, func, select
from test_eis_analogs_pg import NOW, archive
from test_eis_characteristic_pair_pg import counts, request
from test_eis_characteristic_pair_pg import storage as storage_fixture

from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.eis_characteristic_compare import read_characteristic_pair
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.eis_position_projection import (
    LEGACY_PARSER_VERSION,
    PARSER_VERSION,
    PREVIOUS_PARSER_VERSION,
    R1_PARSER_VERSION,
    _digest,
    project_notice_positions,
    read_position_projection,
)
from procurement.storage.models import eis_notice_position_projections


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def ingest_range(
    storage,
    company,
    *,
    malformed_max=False,
    empty_max_operator=False,
    external_sid=False,
    ambiguous_range=False,
    other_shape=None,
):
    number = "1" * 19
    extra = "<max>bad</max>" if malformed_max else ""
    if empty_max_operator:
        extra += "<maxMathNotation></maxMathNotation>"
    metadata = "<externalSid>synthetic-id</externalSid>" if external_sid else ""
    if ambiguous_range:
        extra += "<unknown>ambiguous requirement</unknown>"
    if other_shape == "description":
        metadata += "<qualityDescription>Белая</qualityDescription>"
    elif other_shape == "concrete":
        metadata += "<valueSet><concreteValue>500</concreteValue></valueSet>"
    shape = f"""<characteristics><characteristicsUsingReferenceInfo>
<name>Количество листов</name>
<characteristicsFillingInstruction><code>2</code></characteristicsFillingInstruction>
<values><value>{metadata}<rangeSet><valueRange><min>500</min><minMathNotation>greaterOrEqual</minMathNotation>{extra}</valueRange></rangeSet>
<OKEI><name>Штука</name></OKEI></value></values></characteristicsUsingReferenceInfo></characteristics>"""
    with ZipFile(BytesIO(archive(number))) as source:
        xml = source.read("notice.xml").replace(b"</KTRU>", shape.encode() + b"</KTRU>")
    output = BytesIO()
    with ZipFile(output, "w") as target:
        target.writestr("notice.xml", xml)
    selection = EisDateSelection("50", date(2026, 1, 2), 3)
    window = EisReadyWindow(selection.window_key, "a" * 64, 1, (output.getvalue(),))
    parsed = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="synthetic")
    return NoticeDocumentRef(
        purchase_number=number, version_number=1, notice_xml_sha256=parsed.xml_sha256
    )


def save_previous_projection(
    storage, company, ref, *, complete=True, version=PREVIOUS_PARSER_VERSION
):
    """Synthetic frozen v3 evidence, inserted without invoking the revised parser."""
    from procurement.sources.eis_position_evidence import PositionEvidenceSet

    position = read_characteristic_pair(storage, company, request(ref), now=NOW).target.position
    payload = PositionEvidenceSet(
        law="44",
        purchase_number=ref.purchase_number,
        version_number=ref.version_number,
        notice_xml_sha256=ref.notice_xml_sha256,
        positions=(position,),
        positions_total=1,
        positions_truncated=False,
        native_tables=(),
    ).model_dump(mode="json")
    payload["positions"][0]["characteristics"][0]["values"][0]["range_source_complete"] = complete
    with storage.transaction(company) as conn:
        conn.execute(
            eis_notice_position_projections.insert().values(
                company_id=company,
                purchase_number=ref.purchase_number,
                version_number=ref.version_number,
                notice_xml_sha256=ref.notice_xml_sha256,
                parser_version=version,
                position_set=payload,
                projection_sha256=_digest(payload),
                created_at=NOW,
            )
        )
    return payload


def legacy_ingest(storage, company, monkeypatch, **kwargs):
    import procurement.storage.eis_notice_index as writer

    original = writer.asdict

    def legacy(item):
        payload = original(item)
        for characteristic in payload.get("characteristics", []):
            for value in characteristic["values"]:
                for field in ("minimum_raw", "maximum_raw", "range_source_complete"):
                    value.pop(field, None)
        return payload

    with monkeypatch.context() as patch:
        patch.setattr(writer, "asdict", legacy)
        return ingest_range(storage, company, **kwargs)


def test_old_range_requires_explicit_v3_projection_and_replay_does_not_write(storage, monkeypatch):
    company = "s213-" + uuid4().hex
    ref = legacy_ingest(storage, company, monkeypatch)
    assert read_characteristic_pair(storage, company, request(ref), now=NOW).unknown_count == 1
    assert project_notice_positions(
        storage, company, ref, actor_id="synthetic", parser_version=LEGACY_PARSER_VERSION
    )
    old = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert old.target.storage_kind == "SAVED_PROJECTION" and old.unknown_count == 1
    assert not old.target.position.characteristics[0].values[0].range_source_complete
    before = counts(storage, company)
    assert project_notice_positions(storage, company, ref, actor_id="synthetic")
    after = counts(storage, company)
    assert after == (before[0] + 1, before[1], before[2] + 1)
    assert not project_notice_positions(storage, company, ref, actor_id="synthetic")
    assert counts(storage, company) == after
    new = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert new.policy_version == "eis-characteristic-observation-v2"
    assert new.same_count == 1 and new.technical == new.profit == new.participation == "UNKNOWN"
    value = new.target.position.characteristics[0].values[0]
    assert value.range_source_complete and value.minimum.raw == "500" and value.maximum.raw is None
    with storage.transaction(company, consistent_read=True) as conn:
        saved = read_position_projection(conn, company, ref)
        assert saved.positions[0].characteristics[0].values[0].range_source_complete


@pytest.mark.parametrize("fault", ["digest", "bytes", "shape"])
def test_invalid_preferred_v3_never_falls_back_to_valid_v2(storage, monkeypatch, fault):
    import procurement.storage.eis_characteristic_compare as reader
    import procurement.storage.eis_position_projection as writer

    company = "s213-" + uuid4().hex
    ref = ingest_range(storage, company)
    assert project_notice_positions(
        storage, company, ref, actor_id="synthetic", parser_version=LEGACY_PARSER_VERSION
    )
    save_previous_projection(storage, company, ref)
    save_previous_projection(storage, company, ref, version=R1_PARSER_VERSION)
    if fault == "digest":
        monkeypatch.setattr(writer, "_digest", lambda payload: "f" * 64)
    elif fault == "shape":
        original_digest = writer._digest

        def malformed_projection(payload):
            payload["positions"][0]["characteristics"][0]["values"][0]["range_source_complete"] = (
                "true"
            )
            return original_digest(payload)

        monkeypatch.setattr(writer, "_digest", malformed_projection)
    else:
        original_digest = writer._digest

        def larger_projection(payload):
            payload["positions"][0]["name"]["raw"] = "x" * 3000
            return original_digest(payload)

        monkeypatch.setattr(writer, "_digest", larger_projection)
    assert project_notice_positions(storage, company, ref, actor_id="synthetic")
    if fault == "bytes":
        with storage.transaction(company, consistent_read=True) as conn:
            table = eis_notice_position_projections
            sizes = dict(
                conn.execute(
                    select(
                        table.c.parser_version, func.octet_length(table.c.position_set.cast(Text))
                    ).where(table.c.company_id == company)
                ).all()
            )
        lower_limit = max(
            sizes[LEGACY_PARSER_VERSION], sizes[PREVIOUS_PARSER_VERSION], sizes[R1_PARSER_VERSION]
        )
        assert lower_limit < sizes[PARSER_VERSION]
        monkeypatch.setattr(reader, "MAX_PROJECTION_BYTES", lower_limit)
    before = counts(storage, company)
    with pytest.raises(
        ValueError,
        match=r"CHARACTERISTIC_PROJECTION_(DIGEST_MISMATCH|PAYLOAD_LIMIT)|range_source_complete",
    ):
        read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert counts(storage, company) == before


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("version", [R1_PARSER_VERSION, PREVIOUS_PARSER_VERSION])
def test_original_v3_flags_preserved_and_r1_preferred_without_mutating_old_rows(
    storage, complete, version
):
    company = "s214-" + uuid4().hex
    ref = ingest_range(storage, company, external_sid=True)
    previous = save_previous_projection(storage, company, ref, complete=complete, version=version)
    original = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert original.same_count == int(complete)
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            read_position_projection(conn, company, ref)
            .positions[0]
            .characteristics[0]
            .values[0]
            .range_source_complete
            is complete
        )
    before = counts(storage, company)
    assert project_notice_positions(storage, company, ref, actor_id="synthetic")
    after = counts(storage, company)
    assert after == (before[0] + 1, before[1], before[2] + 1)
    assert read_characteristic_pair(storage, company, request(ref), now=NOW).same_count == 1
    assert not project_notice_positions(storage, company, ref, actor_id="synthetic")
    assert counts(storage, company) == after
    with storage.transaction(company, consistent_read=True) as conn:
        table = eis_notice_position_projections
        assert (
            conn.scalar(
                select(table.c.position_set).where(
                    table.c.company_id == company,
                    table.c.parser_version == version,
                )
            )
            == previous
        )
        assert (
            read_position_projection(conn, company, ref, parser_version=version)
            .positions[0]
            .characteristics[0]
            .values[0]
            .range_source_complete
            is complete
        )
    with pytest.raises(ValueError, match="POSITION_PARSER_VERSION_UNSUPPORTED"):
        project_notice_positions(
            storage, company, ref, actor_id="synthetic", parser_version=version
        )


def test_archive_size_checked_before_loading_source_bytes(storage, monkeypatch):
    import procurement.storage.eis_position_projection as writer

    company = "s214-" + uuid4().hex
    ref = ingest_range(storage, company)
    monkeypatch.setattr(writer, "MAX_ARCHIVE_BYTES", 1)
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    before = counts(storage, company)
    event.listen(storage._engine, "before_cursor_execute", track)
    try:
        with pytest.raises(ValueError, match="POSITION_ARCHIVE_SIZE_LIMIT"):
            project_notice_positions(storage, company, ref, actor_id="synthetic")
    finally:
        event.remove(storage._engine, "before_cursor_execute", track)
    assert any("octet_length(eis_feed_archives.content)" in sql for sql in statements)
    assert not any("SELECT eis_feed_archives.content," in sql for sql in statements)
    assert counts(storage, company) == before


@pytest.mark.parametrize("case", ["malformed_max", "empty_max_operator"])
def test_opposite_bound_parse_failure_or_empty_operator_stays_unknown_after_recovery(
    storage, monkeypatch, case
):
    company = "s213-" + uuid4().hex
    ref = legacy_ingest(storage, company, monkeypatch, **{case: True})
    assert project_notice_positions(storage, company, ref, actor_id="synthetic")
    report = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert report.unknown_count == 1 and report.same_count == 0
    value = report.target.position.characteristics[0].values[0]
    if case == "malformed_max":
        assert value.maximum.raw == "bad" and value.maximum.value is None
    else:
        assert value.maximum_operator.value == ""


def test_legacy_version_cannot_claim_completeness_even_with_new_flag(storage, monkeypatch):
    import procurement.storage.eis_position_projection as writer

    company = "s213-" + uuid4().hex
    ref = ingest_range(storage, company)
    with monkeypatch.context() as patch:
        patch.setattr(writer, "_without_range_completeness", lambda result: result)
        assert project_notice_positions(
            storage, company, ref, actor_id="synthetic", parser_version=LEGACY_PARSER_VERSION
        )
    report = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert report.target.storage_kind == "SAVED_PROJECTION"
    assert not report.target.position.characteristics[0].values[0].range_source_complete
    assert report.unknown_count == 1
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            not read_position_projection(conn, company, ref)
            .positions[0]
            .characteristics[0]
            .values[0]
            .range_source_complete
        )


@pytest.mark.parametrize("other_shape", [None, "description", "concrete"])
def test_ambiguous_range_never_becomes_equal_after_metadata_intake_or_projection(
    storage, other_shape
):
    company = "s215-" + uuid4().hex
    ref = ingest_range(storage, company, ambiguous_range=True, other_shape=other_shape)
    before = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert before.target.storage_kind == "SAVED_NOTICE_FIELDS"
    assert before.target.position.characteristics_status == "UNKNOWN"
    assert before.unknown_count == 1 and before.same_count == before.different_count == 0
    assert project_notice_positions(storage, company, ref, actor_id="synthetic")
    after = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert after.target.storage_kind == "SAVED_PROJECTION"
    assert after.target.position.characteristics_status == "UNKNOWN"
    assert after.unknown_count == 1 and after.same_count == after.different_count == 0
    value = after.target.position.characteristics[0].values[0]
    assert (
        value.minimum.value is value.maximum.value is value.minimum.raw is value.maximum.raw is None
    )
    assert not value.range_source_complete
    assert after.technical == after.profit == after.participation == after.coverage == "UNKNOWN"


def test_saved_v3_read_never_reads_archives_or_writes(storage):
    company = "s213-" + uuid4().hex
    ref = ingest_range(storage, company)
    assert project_notice_positions(storage, company, ref, actor_id="synthetic")
    before = counts(storage, company)
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", track)
    try:
        assert read_characteristic_pair(storage, company, request(ref), now=NOW).same_count == 1
    finally:
        event.remove(storage._engine, "before_cursor_execute", track)
    assert counts(storage, company) == before
    assert not any(
        "eis_feed_archives" in sql or sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )
    with pytest.raises(ValueError, match="CHARACTERISTIC_NOTICE_NOT_FOUND_OR_MISMATCH"):
        read_characteristic_pair(storage, "foreign-" + company, request(ref), now=NOW)


def test_new_saved_fields_carry_complete_range_source_evidence(storage):
    company = "s213-" + uuid4().hex
    ref = ingest_range(storage, company)
    report = read_characteristic_pair(storage, company, request(ref), now=NOW)
    assert report.target.storage_kind == "SAVED_NOTICE_FIELDS" and report.same_count == 1
    assert report.target.position.characteristics[0].values[0].range_source_complete
    assert PARSER_VERSION != LEGACY_PARSER_VERSION
