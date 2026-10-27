"""Owner-aware223 projection, real disposable PostgreSQL invariants."""

import os
from uuid import uuid4

import pytest
from alembic import command
from migration_support import assert_direct_downgrade_guard, historical_database
from sqlalchemy import create_engine, delete, event, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_joint_positions import joint_positions223
from procurement.storage.eis_223_index import (
    bind_notice223_window,
    ingest_notice223_window,
    search_notice223_index,
)
from procurement.storage.eis_223_position_projection import (
    _digest,
    project_stored_positions223,
    read_position223_page,
)
from procurement.storage.models import (
    audit_events,
)
from procurement.storage.models import (
    eis_223_notice_versions as versions,
)
from procurement.storage.models import (
    eis_223_position_projections as projections,
)
from test_eis_223_archive import zip_bytes
from test_eis_223_index import NOW, URL, responses
from test_eis_223_joint_positions import ADDED_FAMILIES, family_joint_xml, joint_xml
from test_eis_223_zpesmbo import NUMBER, REGIONAL

DATABASE = "procurement_eis_test_20261005_s209"
MIGRATION = "20261027_02_eis_223_position_projection"


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def ready():
    initial, prepared = responses()
    return bind_notice223_window(
        REGIONAL, initial, prepared, {URL: zip_bytes([("joint.xml", joint_xml())])}
    )


def seeded(storage):
    company = "joint-" + uuid4().hex
    window = ready()
    assert (
        ingest_notice223_window(storage, company, window, actor_id="test", now=NOW).new_versions
        == 1
    )
    with storage.transaction(company) as conn:
        source = conn.execute(select(versions)).mappings().one()
    return company, window, source


def counts(storage, company):
    with storage.transaction(company) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t))
            for t in (versions, projections, audit_events)
        )


def test_automatic_projection_main_search_and_replay_do_not_rewrite_canonical(storage):
    company, window, source = seeded(storage)
    before = counts(storage, company)
    assert before[0:2] == (1, 1)
    assert ingest_notice223_window(storage, company, window, actor_id="test", now=NOW).replayed
    assert not project_stored_positions223(
        storage, company, NUMBER, 1, source["xml_sha256"], actor_id="test"
    )
    assert counts(storage, company) == before
    result = search_notice223_index(storage, company, NUMBER, now=NOW, paginate=True)
    lead = result.matched[0]
    assert lead.position_projection is not None
    assert [str(c.items[0].quantity.value) for c in lead.position_projection.lots[0].customers] == [
        "6290.8",
        "1140",
    ]
    assert lead.notice.lots[0].items == ()
    assert lead.position_projection.economics_status == "UNKNOWN"
    with storage.transaction(company) as conn:
        assert conn.execute(select(versions)).mappings().one() == source
    assert counts(storage, company) == before


def test_stored_canonical_without_projection_gets_idempotent_source_zero_backfill(
    storage, monkeypatch
):
    import procurement.storage.eis_223_index as index

    original = index.derive_positions223
    monkeypatch.setattr(index, "derive_positions223", lambda *a, **k: False)
    company, _, source = seeded(storage)
    monkeypatch.setattr(index, "derive_positions223", original)
    assert counts(storage, company)[1] == 0
    assert project_stored_positions223(
        storage, company, NUMBER, 1, source["xml_sha256"], actor_id="test"
    )
    before = counts(storage, company)
    assert not project_stored_positions223(
        storage, company, NUMBER, 1, source["xml_sha256"], actor_id="test"
    )
    assert counts(storage, company) == before
    with storage.transaction(company) as conn:
        assert conn.execute(select(versions)).mappings().one() == source


def test_tenant_and_wrong_xml_are_rejected_before_projection(storage):
    company, _, source = seeded(storage)
    with pytest.raises(LookupError):
        project_stored_positions223(
            storage, company + "-other", NUMBER, 1, source["xml_sha256"], actor_id="test"
        )
    with pytest.raises(ValueError, match="XML_IDENTITY"):
        project_stored_positions223(storage, company, NUMBER, 1, "f" * 64, actor_id="test")
    with storage.transaction(company + "-other") as conn:
        assert conn.scalar(select(func.count()).select_from(projections)) == 0


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_app_cannot_mutate_projection(storage, operation):
    company, _, _ = seeded(storage)
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            update(projections).values(projection_sha256="f" * 64)
            if operation == "update"
            else delete(projections)
        )
    assert counts(storage, company)[1] == 1


@pytest.mark.parametrize(
    "drift", ["xml", "tenant", "law", "number", "parser", "status", "missing", "provenance"]
)
def test_sql_fk_rls_and_identity_fail_closed(storage, drift, monkeypatch):
    import procurement.storage.eis_223_index as index

    original = index.derive_positions223
    monkeypatch.setattr(index, "derive_positions223", lambda *a, **k: False)
    company, _, source = seeded(storage)
    monkeypatch.setattr(index, "derive_positions223", original)
    from procurement.sources.eis_223_archive import Eis223NoticeSnapshot

    notice = Eis223NoticeSnapshot.model_validate(source["snapshot"])
    payload = joint_positions223(joint_xml(), notice).model_dump(mode="json")
    row = dict(
        company_id=company,
        purchase_number=NUMBER,
        version_number=1,
        notice_xml_sha256=notice.xml_sha256,
        parser_version="eis223-joint-positions-v1",
        position_set=payload,
        projection_sha256=_digest(payload),
        created_at=NOW,
    )
    if drift == "xml":
        row["notice_xml_sha256"] = "f" * 64
    elif drift == "tenant":
        row["company_id"] = company + "-other"
    elif drift == "missing":
        row["position_set"] = {}
    elif drift == "provenance":
        row["position_set"]["lots"][0]["provenance"]["document_id"] = "f" * 64
    else:
        key = {
            "law": "law",
            "number": "purchase_number",
            "parser": "parser_version",
            "status": "economics_status",
        }[drift]
        row["position_set"][key] = {
            "law": "44",
            "number": "32699999999",
            "parser": "untrusted",
            "status": "PASS",
        }[drift]
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(insert(projections).values(**row))


def test_owner_immutable_trigger_blocks_even_granted_update_delete(storage):
    company, _, _ = seeded(storage)
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        for verb in (
            "UPDATE eis_223_position_projections SET projection_sha256=projection_sha256",
            "DELETE FROM eis_223_position_projections",
        ):
            with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
                conn.execute(text("SET LOCAL row_security=off"))
                conn.execute(text(verb + " WHERE company_id=:company"), {"company": company})
    finally:
        engine.dispose()


def test_page_100_refs_reads_metadata_then_payload_in_constant_two_queries(storage):
    company, _, _ = seeded(storage)
    lead = search_notice223_index(storage, company, NUMBER, now=NOW).matched[0]
    notices = [
        lead.notice.model_copy(update={"purchase_number": f"326{i:08d}"}) for i in range(100)
    ]
    notices[1] = lead.notice
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "eis_223_position_projections" in statement:
            statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", observe)
    try:
        with storage.transaction(company) as conn:
            output = read_position223_page(conn, company, notices)
        assert len(output) == 100 and sum(o is not None for o in output) == 1
        assert len(statements) == 2 and "octet_length" in statements[0]
        assert "octet_length" not in statements[1]
    finally:
        event.remove(storage._engine, "before_cursor_execute", observe)


def test_metadata_budget_prevents_json_hydration(storage, monkeypatch):
    import procurement.storage.eis_223_position_projection as module

    company, _, _ = seeded(storage)
    notice = search_notice223_index(storage, company, NUMBER, now=NOW).matched[0].notice
    monkeypatch.setattr(module, "RECORD_BYTES", 1)
    monkeypatch.setattr(module, "_validated", lambda *a: pytest.fail("oversize payload hydrated"))
    with storage.transaction(company) as conn:
        assert read_position223_page(conn, company, [notice]) == (None,)


def test_final_wire_budget_retains_unknown(storage, monkeypatch):
    import procurement.storage.eis_223_position_projection as module

    company, _, _ = seeded(storage)
    notice = search_notice223_index(storage, company, NUMBER, now=NOW).matched[0].notice

    class Large:
        def model_dump_json(self):
            return "x" * (module.RECORD_BYTES + 1)

    monkeypatch.setattr(module, "_validated", lambda *a: Large())
    with storage.transaction(company) as conn:
        assert read_position223_page(conn, company, [notice]) == (None,)


def test_reader_rejects_tampered_digest(storage):
    from procurement.storage.eis_223_position_projection import _validated

    company, _, _ = seeded(storage)
    notice = search_notice223_index(storage, company, NUMBER, now=NOW).matched[0].notice
    payload = joint_positions223(joint_xml(), notice).model_dump(mode="json")
    with pytest.raises(ValueError, match="DIGEST"):
        _validated(notice, notice.xml_sha256, "f" * 64, payload)
    payload["source_member"] = "wrong.xml"
    with pytest.raises(ValueError, match="IDENTITY"):
        _validated(notice, notice.xml_sha256, _digest(payload), payload)


def test_downgrade_preserves_all_tenant_history(storage):
    seeded(storage)
    assert_direct_downgrade_guard(
        MIGRATION,
        expected_database=DATABASE,
        match="223 position history must be preserved",
        tenant_context="unrelated",
    )


def test_empty_migration_roundtrip_preserves_head_and_constraints():
    with historical_database(revision="20261027_01", expected_database=DATABASE) as db:
        command.upgrade(db.config, "20261027_02")
        command.downgrade(db.config, "20261027_01")
        command.upgrade(db.config, "20261027_02")


def family_ready(family):
    initial, prepared = responses()
    return bind_notice223_window(
        REGIONAL.replace("purchaseNoticeZPESMBO", family),
        initial,
        prepared,
        {URL: zip_bytes([("family.xml", family_joint_xml(family))])},
    )


@pytest.mark.parametrize("family", ADDED_FAMILIES)
def test_added_family_automatic_intake_search_and_replay(storage, family):
    company = "joint-family-" + uuid4().hex
    window = family_ready(family)
    assert (
        ingest_notice223_window(storage, company, window, actor_id="test", now=NOW).new_versions
        == 1
    )
    before = counts(storage, company)
    assert before[:2] == (1, 1)
    result = search_notice223_index(storage, company, NUMBER, now=NOW, paginate=True)
    projection = result.matched[0].position_projection
    assert projection.document_type == family
    assert projection.lots[0].customers[0].items[0].quantity.value is not None
    assert result.matched[0].notice.lots[0].items == ()
    assert ingest_notice223_window(storage, company, window, actor_id="test", now=NOW).replayed
    with storage.transaction(company) as conn:
        source = conn.execute(select(versions)).mappings().one()
    assert not project_stored_positions223(
        storage, company, NUMBER, 1, source["xml_sha256"], actor_id="test"
    )
    assert counts(storage, company) == before
    with storage.transaction(company + "-other") as conn:
        assert conn.scalar(select(func.count()).select_from(projections)) == 0


def test_new_family_downgrade_guard_sees_other_tenant_history(storage):
    company = "non-zp-" + uuid4().hex
    ingest_notice223_window(
        storage, company, family_ready("purchaseNotice"), actor_id="test", now=NOW
    )
    assert_direct_downgrade_guard(
        "20261027_03_eis_223_joint_families",
        expected_database=DATABASE,
        match="non-ZP joint position history must be preserved",
        tenant_context="unrelated",
    )


@pytest.mark.parametrize("family", ["purchaseNoticeZKESMBO", "untrusted", None])
def test_db_rejects_unadmitted_joint_document_type(storage, monkeypatch, family):
    import procurement.storage.eis_223_index as index

    derive = index.derive_positions223
    monkeypatch.setattr(index, "derive_positions223", lambda *a, **k: False)
    company, _, source = seeded(storage)
    monkeypatch.setattr(index, "derive_positions223", derive)
    notice = search_notice223_index(storage, company, NUMBER, now=NOW).matched[0].notice
    payload = joint_positions223(joint_xml(), notice).model_dump(mode="json")
    payload["document_type"] = family
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(projections).values(
                company_id=company,
                purchase_number=NUMBER,
                version_number=1,
                notice_xml_sha256=source["xml_sha256"],
                parser_version="eis223-joint-positions-v1",
                position_set=payload,
                projection_sha256=_digest(payload),
                created_at=NOW,
            )
        )


FROZEN_V55_IDENTITY_SQL = (
    "COALESCE(jsonb_typeof(position_set) = 'object' AND position_set->>'law' = '"
    "223' AND position_set->>'document_type' = 'purchaseNoticeZPESMBO' AND posit"
    "ion_set->>'purchase_number' = purchase_number AND (position_set->>'version_"
    "number')::integer = version_number AND position_set->>'notice_xml_sha256' ="
    " notice_xml_sha256 AND position_set->>'parser_version' = parser_version AND"
    " jsonb_typeof(position_set->'lots') = 'array' AND jsonb_array_length(positi"
    "on_set->'lots') > 0 AND length(position_set->>'source_member') BETWEEN 1 AN"
    "D 1024 AND position_set->>'source_item_coverage' IN ('PASS','UNKNOWN') AND "
    "position_set->>'specification_completeness' = 'UNKNOWN' AND position_set->>"
    "'economics_status' = 'UNKNOWN', false)"
)


def test_migration_from_actual_v55_check_retains_zp_bytes_and_admits_three_families():
    from procurement.storage.repository import PostgresStorage

    with historical_database(revision="20261027_02", expected_database=DATABASE) as db:
        admin = create_engine(db.admin_url)
        app = create_engine(db.app_url)
        historical = PostgresStorage(app)
        try:
            # The old migration imports current metadata; restore its exact accepted CHECK.
            with admin.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE eis_223_position_projections DROP CONSTRAINT ck_eis_2"
                        "23_position_identity"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE eis_223_position_projections ADD CONSTRAINT ck_eis_22"
                        "3_position_identity CHECK (" + FROZEN_V55_IDENTITY_SQL + ")"
                    )
                )
            company, _, _ = seeded(historical)

            def zp_bytes():
                with historical.transaction(company) as conn:
                    return conn.execute(
                        text(
                            "SELECT position_set::text, projection_sha256 FROM eis_223_positio"
                            "n_projections"
                        )
                    ).one()

            before = zp_bytes()
            for family in ADDED_FAMILIES:
                with pytest.raises(DBAPIError, match="ck_eis_223_position_identity"):
                    ingest_notice223_window(
                        historical,
                        "old-refuse-" + family,
                        family_ready(family),
                        actor_id="test",
                        now=NOW,
                    )
            command.upgrade(db.config, "20261027_03")
            assert zp_bytes() == before
            for family in ADDED_FAMILIES:
                tenant = "new-admit-" + family
                ingest_notice223_window(
                    historical, tenant, family_ready(family), actor_id="test", now=NOW
                )
                with historical.transaction(tenant) as conn:
                    assert (
                        conn.scalar(select(projections.c.position_set))["document_type"] == family
                    )
            assert zp_bytes() == before
        finally:
            app.dispose()
            admin.dispose()


def test_new_family_empty_migration_roundtrip_preserves_validated_constraint():
    with historical_database(revision="20261027_02", expected_database=DATABASE) as db:
        command.upgrade(db.config, "20261027_03")
        command.downgrade(db.config, "20261027_02")
        engine = create_engine(db.admin_url)
        try:
            with engine.connect() as conn:
                expression = conn.scalar(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname"
                        "='ck_eis_223_position_identity'"
                    )
                )
                assert (
                    "purchaseNoticeZPESMBO" in expression
                    and "purchaseNoticeAESMBO" not in expression
                )
        finally:
            engine.dispose()
        command.upgrade(db.config, "20261027_03")
