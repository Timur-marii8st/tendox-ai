"""Removing duplicate reads preserves complete source gates and report identity."""

import hashlib
import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, select, text
from sqlalchemy.engine import make_url
from test_eis_analogs_pg import NOW, ingest
from test_eis_notice_hold_pg import hold
from test_eis_notice_index_pg import storage as storage_fixture
from test_eis_notice_projection_pg import prepare

from procurement.sources.eis_analogs import AnalogRequest
from procurement.storage.eis_analogs import read_analog_candidates
from procurement.storage.eis_notice_projection import project_retained_notice_variants
from procurement.storage.models import eis_notice_variant_receipts
from test_eis_notice_conflicts import notice

BASELINE_SHA = "b94a0c850223006787457bad239f7bb77fa0ae2dd06e584f179839f4810be84b"
GATE_DATABASES = {
    "procurement_eis_test_20261005_s206",
    "procurement_eis_test_20261005_s208",
    "procurement_eis_test_20261005_s209",
}


@pytest.fixture(scope="module")
def storage():
    for key in ("DATABASE_URL", "DATABASE_ADMIN_URL"):
        if not os.environ.get(key):
            pytest.skip("Requires isolated PostgreSQL gate database")
        assert make_url(os.environ[key]).database in GATE_DATABASES
    yield from storage_fixture.__wrapped__()


@pytest.fixture(scope="module")
def legacy():
    path = os.environ.get("S206_BASELINE_ANALOGS_PATH")
    if not path:
        pytest.skip("Requires immutable S205 release reader for equivalence gate")
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == BASELINE_SHA
    spec = importlib.util.spec_from_file_location("s206_baseline_analogs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_analog_candidates


def tenant():
    # All synthetic fault inserts are confined to this disposable gate database.
    assert make_url(os.environ["DATABASE_URL"]).database in GATE_DATABASES
    return "s206-" + uuid4().hex


def cohort(storage, company):
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    control = ingest(storage, company, "9" * 19)
    return AnalogRequest(target=target, source_index=1, query="бумага"), control


def same(storage, company, request, legacy):
    expected = legacy(storage, company, request, now=NOW)
    actual = read_analog_candidates(storage, company, request, now=NOW)
    assert actual == expected
    return actual


def retained(storage, company, tmp_path):
    xml = notice(title="Бумага A4", extra="<ep:endDT>2026-10-03T12:00:00Z</ep:endDT>").replace(
        b"0373100047426001450", ("1" * 19).encode()
    )
    receipt, archives, _ = prepare(storage, company, tmp_path, members=(("notice.xml", xml),))
    return receipt, archives, xml


def test_twenty_candidates_identical_with_thirty_nine_fewer_sql_commands(storage, legacy):
    company = tenant()
    request, _ = cohort(storage, company)
    for index in range(19):
        ingest(storage, company, f"{index + 1:019d}")
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.split()[0])

    event.listen(storage._engine, "before_cursor_execute", capture)
    try:
        expected = legacy(storage, company, request, now=NOW)
        old_count = len(statements)
        statements.clear()
        actual = read_analog_candidates(storage, company, request, now=NOW)
        assert actual == expected and actual.selected_notices == 20
        assert old_count == 52 and len(statements) == 13
    finally:
        event.remove(storage._engine, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    "delta,singleton,excluded", [(0, False, True), (1, True, True), (-1, False, False)]
)
def test_same_newer_and_older_evidence_cutoffs_are_preserved(
    storage, tmp_path, legacy, delta, singleton, excluded
):
    company = tenant()
    request, control = cohort(storage, company)
    candidate = ingest(storage, company, "1" * 19, version=2)
    hold(storage, company, tmp_path, candidate, version=2 + delta, singleton=singleton)
    report = same(storage, company, request, legacy)
    numbers = {c.notice.purchase_number for c in report.candidates}
    assert (candidate.purchase_number not in numbers) == excluded
    assert control.purchase_number in numbers
    with pytest.raises(ValueError, match="TARGET_NOT_FOUND_OR_MISMATCH"):
        read_analog_candidates(storage, "foreign-" + company, request, now=NOW)


def test_incomplete_receipt_blocks_entire_tenant_but_not_foreign_tenant(storage, tmp_path, legacy):
    company = tenant()
    request, control = cohort(storage, company)
    hold(storage, company, tmp_path, control)
    with storage.transaction(company, consistent_read=True) as conn:
        row = dict(conn.execute(select(eis_notice_variant_receipts)).mappings().one())
    row["receipt_id"] = str(uuid4())
    row["manifest_sha256"] = "f" * 64
    row["evidence"] = {**row["evidence"], "manifest_sha256": "f" * 64}
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_notice_variant_receipts).values(**row))
    for reader in (legacy, read_analog_candidates):
        with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
            reader(storage, company, request, now=NOW)
    other = tenant()
    other_request, other_control = cohort(storage, other)
    assert same(storage, other, other_request, legacy).candidates[0].notice == other_control


def test_resolved_candidate_then_changed_complete_origin_is_excluded(storage, tmp_path, legacy):
    company = tenant()
    request, control = cohort(storage, company)
    receipt, archives, xml = retained(storage, company, tmp_path)
    project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    assert {
        c.notice.purchase_number for c in same(storage, company, request, legacy).candidates
    } == {"1" * 19, control.purchase_number}
    prepare(
        storage,
        company,
        tmp_path,
        day="30",
        response="d",
        members=(("changed.xml", xml.replace("Бумага A4".encode(), "Бумага A3".encode())),),
    )
    report = same(storage, company, request, legacy)
    assert [c.notice for c in report.candidates] == [control]


def test_invalid_audit_decision_insert_never_discharges_source_hold(
    storage, tmp_path, legacy, monkeypatch
):
    import procurement.storage.eis_notice_projection as writer

    company = tenant()
    request, control = cohort(storage, company)
    receipt, archives, _ = retained(storage, company, tmp_path)
    original_json = writer._json
    corrupted = []

    def wrong_audit(value):
        result = original_json(value)
        if (
            isinstance(result, dict)
            and result.get("batch", {}).get("company_id") == company
            and result["decisions"][0]["snapshot_sha256"] != "f" * 64
        ):
            result["decisions"][0]["snapshot_sha256"] = "f" * 64
            corrupted.append(True)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(writer, "_json", wrong_audit)
        project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    assert corrupted == [True]
    assert [c.notice for c in same(storage, company, request, legacy).candidates] == [control]


def test_reader_requires_one_read_only_repeatable_snapshot(storage, legacy, monkeypatch):
    company = tenant()
    request, _ = cohort(storage, company)
    original_transaction = storage.transaction
    snapshots = []
    jit_values = []
    with original_transaction(company, consistent_read=True) as conn:
        default_jit = conn.scalar(text("SHOW jit"))

    @contextmanager
    def verified_transaction(company_id, *, consistent_read=False):
        assert consistent_read
        with original_transaction(company_id, consistent_read=consistent_read) as conn:
            assert conn.scalar(text("SHOW transaction_read_only")) == "on"
            assert conn.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            snapshots.append(True)
            yield conn
            jit_values.append(conn.scalar(text("SHOW jit")))

    monkeypatch.setattr(storage, "transaction", verified_transaction)
    same(storage, company, request, legacy)
    assert snapshots == [True, True]
    assert jit_values == [default_jit, "off"]
    with original_transaction(company, consistent_read=True) as conn:
        assert conn.scalar(text("SHOW jit")) == default_jit
