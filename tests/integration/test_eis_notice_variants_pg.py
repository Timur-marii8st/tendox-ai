"""Evidence ledger is atomic, immutable, tenant scoped and never canonical intake."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from migration_support import assert_direct_downgrade_guard, historical_database
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_eis_notice_index_pg import storage as storage_fixture

from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_rejected_evidence import retain_rejected_window
from procurement.storage.eis_notice_index import EisReadyWindow
from procurement.storage.eis_notice_variants import (
    read_notice_variant_receipt,
    read_notice_variant_state,
    store_notice_variants,
)
from procurement.storage.eis_rejected_evidence import (
    record_notice_conflict_diagnosis,
    record_rejected_evidence,
)
from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_notice_variant_origins,
    eis_notice_variant_receipts,
    eis_notice_variants,
    eis_notice_versions,
    eis_sync_attempts,
)
from test_eis_notice_conflicts import TOKEN, bundle, notice

NUMBER = "0373100047426001450"
LEDGER = (eis_notice_variant_receipts, eis_notice_variants, eis_notice_variant_origins)


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def batch(
    storage, company, tmp_path, *, members=None, day="29", response="a", audited=True, observed=None
):
    members = members or (
        ("first.xml", notice()),
        (
            "second.xml",
            notice(published="2026-10-01T10:01:27+03:00", start="2026-10-01T10:01:27+03:00"),
        ),
    )
    archives = (bundle(*members),)
    window = EisReadyWindow(
        f"getDocsIP/PRIZ/77/2026-09-{day}+03:00",
        response * 64,
        1,
        archives,
        "b" * 64,
        (
            "https://int44.zakupki.gov.ru/dstore/common/download/compound?docRequestUid="
            "11111111-1111-4111-8111-111111111111&compoundUid=" + "A" * 32,
        ),
    )
    evidence = retain_rejected_window(
        window, company, "DUPLICATE_NOTICE_VERSION", TOKEN, observed or datetime.now(UTC), tmp_path
    )
    diagnosis = diagnose_notice_conflicts(archives, TOKEN)
    assert evidence.status == "RETAINED"
    if audited:
        record_rejected_evidence(storage, company, evidence, actor_id="test")
        record_notice_conflict_diagnosis(storage, company, evidence, diagnosis, actor_id="test")
    return evidence, diagnosis


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return {
            table.name: conn.scalar(select(func.count()).select_from(table))
            for table in (
                *LEDGER,
                eis_feed_windows,
                eis_notice_versions,
                eis_sync_attempts,
                audit_events,
            )
        }


def test_empty_migration_roundtrip_before_ledger_history(storage):
    with historical_database(
        expected_database="procurement_eis_test_20261004_s178",
        revision="20261004_02",
    ) as database:
        command.downgrade(database.config, "20261004_01")
        engine = create_engine(database.admin_url)
        try:
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20261004_01"
                )
            command.upgrade(database.config, "20261004_02")
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20261004_02"
                )
                assert all(
                    conn.scalar(text("SELECT to_regclass(:name)"), {"name": table.name})
                    for table in LEDGER
                )
        finally:
            engine.dispose()


def test_atomic_all_variants_origins_replay_rls_and_no_canonical_writes(storage, tmp_path):
    company = "variants-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    before = counts(storage, company)
    report = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert report.inserted_variants == report.inserted_origins == 2
    assert report.canonical_admission == "NOT_ENABLED" and report.resolution == "UNKNOWN"
    after = counts(storage, company)
    assert (
        after[eis_notice_variant_receipts.name] == 1
        and after[audit_events.name] == before[audit_events.name] + 1
    )
    for table in (eis_feed_windows, eis_notice_versions, eis_sync_attempts):
        assert after[table.name] == before[table.name] == 0
    replay = store_notice_variants(storage, company, evidence, diagnosis, actor_id="retry")
    assert replay.replayed and replay.inserted_variants == replay.inserted_origins == 0
    assert counts(storage, company) == after
    state = read_notice_variant_state(storage, company, NUMBER, 1)
    assert state.status == "COMPLETE" and state.ambiguity is True
    assert len(state.variants) == len(state.origins) == 2 and state.resolution == "UNKNOWN"
    receipt = read_notice_variant_receipt(storage, company, report.receipt_id)
    assert (
        receipt.occurrence_count == receipt.variant_count == 2
        and receipt.diagnosis_sha256 == diagnosis.sha256
    )
    other = "other-" + uuid4().hex
    assert read_notice_variant_state(storage, other, NUMBER, 1).status == "NONE"
    assert read_notice_variant_receipt(storage, other, report.receipt_id) is None
    for table in LEDGER:
        with storage.transaction(other, consistent_read=True) as conn:
            assert conn.scalar(select(func.count()).select_from(table)) == 0
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(delete(table))
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(update(table).values(company_id=company))
    assert counts(storage, company) == after


def test_identical_bytes_every_origin_cross_window_variants_accumulate(storage, tmp_path):
    company = "variants-reused-" + uuid4().hex
    xml = notice()
    evidence, diagnosis = batch(
        storage, company, tmp_path, members=(("a.xml", xml), ("b.xml", xml))
    )
    first = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert first.inserted_variants == 1 and first.inserted_origins == 2
    state = read_notice_variant_state(storage, company, NUMBER, 1)
    assert state.ambiguity is False and state.canonical_admission == "NOT_ENABLED"
    evidence, diagnosis = batch(
        storage, company, tmp_path, members=(("c.xml", xml), ("d.xml", xml)), day="28", response="c"
    )
    second = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert (
        second.receipt_id != first.receipt_id
        and second.inserted_variants == 0
        and second.inserted_origins == 2
    )
    evidence, diagnosis = batch(
        storage,
        company,
        tmp_path,
        members=(("e.xml", xml), ("f.xml", notice(title="changed"))),
        day="27",
        response="d",
    )
    third = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert third.inserted_variants == 1 and third.inserted_origins == 2
    state = read_notice_variant_state(storage, company, NUMBER, 1)
    assert state.ambiguity is True and len(state.variants) == 2 and len(state.origins) == 6


def test_unaudited_missing_key_and_wrong_tenant_batches_leave_no_ledger(storage, tmp_path):
    company = "variants-invalid-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path, audited=False)
    before = counts(storage, company)
    with pytest.raises(ValueError):
        store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert counts(storage, company) == before
    record_rejected_evidence(storage, company, evidence, actor_id="test")
    record_notice_conflict_diagnosis(storage, company, evidence, diagnosis, actor_id="test")
    other = "other-" + uuid4().hex
    with pytest.raises(ValueError):
        store_notice_variants(storage, other, evidence, diagnosis, actor_id="test")
    malformed = notice().replace(
        b"<ep:versionNumber>1</ep:versionNumber>", b"<ep:versionNumber>0</ep:versionNumber>"
    )
    evidence, diagnosis = batch(
        storage, company, tmp_path, members=(("missing.xml", malformed),), day="26", response="e"
    )
    before = counts(storage, company)
    with pytest.raises(ValueError):
        store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert counts(storage, company) == before


def test_audit_last_failure_rolls_back_entire_batch(storage, tmp_path, monkeypatch):
    from sqlalchemy.engine import Connection

    company = "variants-rollback-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    before = counts(storage, company)
    execute = Connection.execute

    def fail_audit(self, statement, *args, **kwargs):
        if (
            getattr(statement, "is_insert", False)
            and getattr(statement, "table", None) is audit_events
        ):
            raise ValueError("TEST_AUDIT_FAILED")
        return execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", fail_audit)
    with pytest.raises(ValueError, match="TEST_AUDIT_FAILED"):
        store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert counts(storage, company) == before


def test_existing_last_variant_payload_conflict_rolls_back_new_variants(storage, tmp_path):
    company = "variants-facts-conflict-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    last = sorted(diagnosis.occurrences, key=lambda item: item.xml_sha256)[-1]
    facts = last.model_dump(
        mode="json", exclude={"archive_ordinal", "archive_sha256", "member_filename"}
    )
    facts["document_id"] = "12345"
    digest = hashlib.sha256(
        json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_notice_variants).values(
                company_id=company,
                purchase_number=last.purchase_number,
                version_number=last.version_number,
                document_type=last.document_type,
                xml_sha256=last.xml_sha256,
                facts=facts,
                facts_sha256=digest,
            )
        )
    before = counts(storage, company)
    with pytest.raises(ValueError, match="FACT_CONFLICT"):
        store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    assert counts(storage, company) == before
    assert before[eis_notice_variants.name] == 1 and before[eis_notice_variant_receipts.name] == 0


def test_reader_overflow_never_returns_subset_as_complete(storage, tmp_path, monkeypatch):
    from procurement.storage import eis_notice_variants as module

    company = "variants-overflow-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    report = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    monkeypatch.setattr(module, "MAX_ORIGINS", 1)
    state = read_notice_variant_state(storage, company, NUMBER, 1)
    assert state.status == "OVERFLOW" and state.resolution == "UNKNOWN"
    assert not state.variants and not state.origins and state.ambiguity is None
    with pytest.raises(ValueError, match="OVERFLOW"):
        read_notice_variant_receipt(storage, company, report.receipt_id)


@pytest.mark.parametrize("zone", [UTC, timezone(timedelta(hours=3))])
def test_receipt_roundtrip_retains_audited_timezone(storage, tmp_path, zone):
    company = "variants-time-" + uuid4().hex
    evidence, diagnosis = batch(
        storage, company, tmp_path, observed=datetime(2026, 10, 4, 9, 0, tzinfo=zone)
    )
    report = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    receipt = read_notice_variant_receipt(storage, company, report.receipt_id)
    assert receipt.evidence.model_dump(mode="json") == evidence.model_dump(mode="json")
    assert receipt.receipt_sha256 == report.receipt_sha256
    assert read_notice_variant_state(storage, company, NUMBER, 1).status == "COMPLETE"


def test_combined_receipt_and_audit_budget_returns_empty_overflow(storage, tmp_path, monkeypatch):
    from procurement.storage import eis_notice_variants as module

    company = "variants-budget-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    report = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    monkeypatch.setattr(module, "MAX_RECEIPTS", 0)
    state = read_notice_variant_state(storage, company, NUMBER, 1)
    assert state.status == "OVERFLOW" and not state.variants and not state.origins
    monkeypatch.setattr(module, "MAX_RECEIPTS", 20)
    monkeypatch.setattr(module, "MAX_READ_PAYLOAD_BYTES", 1)
    assert read_notice_variant_state(storage, company, NUMBER, 1).status == "OVERFLOW"
    with pytest.raises(ValueError, match="OVERFLOW"):
        read_notice_variant_receipt(storage, company, report.receipt_id)


def test_owner_cannot_mutate_ledger_history(storage, tmp_path):
    company = "variants-owner-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        for table in LEDGER:
            with pytest.raises(DBAPIError), engine.begin() as conn:
                conn.execute(delete(table).where(table.c.company_id == company))
    finally:
        engine.dispose()
    assert read_notice_variant_state(storage, company, NUMBER, 1).status == "COMPLETE"


@pytest.mark.parametrize("field", ["status", "complete_set"])
def test_receipt_db_rejects_missing_and_json_null_evidence_keys(storage, tmp_path, field):
    company = "variants-db-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    report = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    with storage.transaction(company, consistent_read=True) as conn:
        row = dict(conn.execute(select(eis_notice_variant_receipts)).mappings().one())
    for replacement in ("missing", None):
        damaged = {
            **row,
            "receipt_id": str(uuid4()),
            "manifest_sha256": "f" * 64,
            "evidence": dict(row["evidence"]),
        }
        damaged["evidence"]["manifest_sha256"] = damaged["manifest_sha256"]
        if replacement == "missing":
            damaged["evidence"].pop(field)
        else:
            damaged["evidence"][field] = None
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(insert(eis_notice_variant_receipts).values(**damaged))
    assert read_notice_variant_receipt(storage, company, report.receipt_id) is not None


def test_downgrade_sees_history_of_other_tenant_and_keeps_schema(storage, tmp_path):
    company = "variant-downgrade-" + uuid4().hex
    evidence, diagnosis = batch(storage, company, tmp_path)
    store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261004_02_eis_notice_variant_ledger",
        expected_database="procurement_eis_test_20261004_s178",
        match="variant evidence history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with engine.connect() as conn:
            assert all(
                conn.scalar(text("SELECT to_regclass(:name)"), {"name": table.name})
                for table in LEDGER
            )
    finally:
        engine.dispose()
    assert counts(storage, company) == before
