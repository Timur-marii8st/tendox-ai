"""Scoped resolution proves the same source gate, retaining global receipt integrity."""

import hashlib
import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, insert, literal, select, text
from sqlalchemy.engine import make_url
from test_eis_analogs_pg import NOW, ingest
from test_eis_notice_index_pg import storage as storage_fixture
from test_eis_notice_projection_pg import prepare

from procurement.sources.eis_analogs import AnalogRequest
from procurement.storage.eis_analogs import read_analog_candidates
from procurement.storage.eis_notice_hold import (
    notice_variant_hold_clause,
    read_notice_source_hold_connection,
)
from procurement.storage.eis_notice_projection import project_retained_notice_variants
from procurement.storage.models import (
    audit_events,
    eis_document_jobs,
    eis_notice_variant_receipts,
    eis_notice_versions,
)
from test_eis_notice_conflicts import notice

GATE_DATABASE = (
    "procurement_eis_test_history"
    if os.environ.get("HISTORY_READER_INSTALLED_SCHEMA_TEST") == "1"
    else "procurement_eis_test_20261005_s209"
)
ANALOG_SHA = "3b43638c735e443423d923a0fbb48a6f4cad56906c7448edb3fb46e7bd64b619"
HOLD_SHA = "b044241cc52de3cc742d13f597060cb76d0268072e78879b0680d6d80e6cf570"


@pytest.fixture(scope="module")
def storage():
    for key in ("DATABASE_URL", "DATABASE_ADMIN_URL"):
        if not os.environ.get(key):
            pytest.skip("Requires isolated PostgreSQL gate database")
        assert make_url(os.environ[key]).database == GATE_DATABASE
    if os.environ.get("HISTORY_READER_INSTALLED_SCHEMA_TEST") == "1":
        from procurement.storage.repository import PostgresStorage

        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        yield PostgresStorage(engine)
        engine.dispose()
    else:
        yield from storage_fixture.__wrapped__()


def load(name, env, sha):
    path = os.environ.get(env)
    if not path:
        pytest.skip("Requires both immutable S208 release modules")
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def legacy():
    hold = load("s209_old_hold", "S209_BASELINE_HOLD_PATH", HOLD_SHA)
    analog = load("s209_old_analog", "S209_BASELINE_ANALOGS_PATH", ANALOG_SHA)
    analog.notice_variant_hold_clause = hold.notice_variant_hold_clause
    analog.assert_notice_source_usable = hold.assert_notice_source_usable
    return analog, hold


def tenant():
    assert make_url(os.environ["DATABASE_URL"]).database == GATE_DATABASE
    return "s209-" + uuid4().hex


def setup(storage, company):
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    control = ingest(storage, company, "9" * 19)
    return AnalogRequest(target=target, source_index=1, query="бумага"), control


def xml(number="1" * 19, **kwargs):
    return notice(
        title="Бумага A4", extra="<ep:endDT>2026-10-03T12:00:00Z</ep:endDT>", **kwargs
    ).replace(b"0373100047426001450", number.encode())


def project(storage, company, tmp_path, *, members=None, day="29", response="a"):
    members = members or (("paper.xml", xml()),)
    receipt, archives, _ = prepare(
        storage, company, tmp_path, members=members, day=day, response=response
    )
    result = project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    return receipt, result


def same(storage, company, request, legacy):
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(text("SHOW transaction_read_only")) == "on"
        assert conn.scalar(text("SHOW transaction_isolation")) == "repeatable read"

        class Snapshot:
            @contextmanager
            def transaction(self, company_id, *, consistent_read=False):
                assert company_id == company and consistent_read
                yield conn

        expected = legacy[0].read_analog_candidates(Snapshot(), company, request, now=NOW)
        actual = read_analog_candidates(Snapshot(), company, request, now=NOW)
        assert actual == expected
        return actual


def scope(company, number, version):
    return select(
        literal(company).label("company_id"),
        literal(number).label("purchase_number"),
        literal(version).label("version_number"),
    ).cte("test_resolution_scope")


def holds(storage, company, number, version, legacy, *, scope_company=None):
    selected = scope(scope_company or company, number, version)
    with storage.transaction(company, consistent_read=True) as conn:
        old = bool(
            conn.scalar(select(legacy[1].notice_variant_hold_clause(company, number, version)))
        )
        default = bool(conn.scalar(select(notice_variant_hold_clause(company, number, version))))
        actual_hold = read_notice_source_hold_connection(conn, company, number, version)
        assert (actual_hold.status != "NO_HOLD") == default
        scoped = bool(
            conn.scalar(
                select(
                    notice_variant_hold_clause(
                        company,
                        number,
                        version,
                        _resolution_scope=selected,
                    )
                )
            )
        )
    assert old == default
    return old, scoped


def test_shared_multi_purchase_batch_keeps_full_audit_array_and_read_only_identity(
    storage, legacy, tmp_path
):
    company = tenant()
    request, control = setup(storage, company)
    project(
        storage,
        company,
        tmp_path,
        members=(
            ("paper.xml", xml()),
            ("other.xml", xml("2" * 19).replace("Бумага A4".encode(), "Сервер".encode())),
        ),
    )

    def counts():
        with storage.transaction(company, consistent_read=True) as conn:
            return tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (
                    audit_events,
                    eis_document_jobs,
                    eis_notice_versions,
                    eis_notice_variant_receipts,
                )
            )

    before = counts()
    report = same(storage, company, request, legacy)
    assert [c.notice.purchase_number for c in report.candidates] == [
        control.purchase_number,
        "1" * 19,
    ]
    assert holds(storage, company, "1" * 19, 1, legacy) == (False, False)
    assert counts() == before and report.source_requests == 0
    with pytest.raises(ValueError, match="TARGET_NOT_FOUND_OR_MISMATCH"):
        read_analog_candidates(storage, "foreign-" + company, request, now=NOW)


@pytest.mark.parametrize("conflict", [False, True])
def test_all_origins_from_additional_receipt_revalidated(storage, legacy, tmp_path, conflict):
    company = tenant()
    request, control = setup(storage, company)
    project(storage, company, tmp_path)
    changed = xml().replace("Бумага A4".encode(), "Бумага A3".encode()) if conflict else xml()
    prepare(storage, company, tmp_path, members=(("later.xml", changed),), day="30", response="d")
    result = same(storage, company, request, legacy)
    assert ("1" * 19 in {c.notice.purchase_number for c in result.candidates}) is not conflict
    assert control.purchase_number in {c.notice.purchase_number for c in result.candidates}
    assert holds(storage, company, "1" * 19, 1, legacy) == (conflict, conflict)


@pytest.mark.parametrize("resolved", [False, True])
def test_same_newer_pairs_include_evidence_outside_candidate_publication_period(
    storage, legacy, tmp_path, resolved
):
    company = tenant()
    request, control = setup(storage, company)
    project(storage, company, tmp_path)
    newer = (("newer.xml", xml(version="2", published="2026-10-04T13:00:00Z")),)
    if resolved:
        project(storage, company, tmp_path, members=newer, day="30", response="d")
    else:
        prepare(storage, company, tmp_path, members=newer, day="30", response="d")
    report = same(storage, company, request, legacy)
    assert [c.notice for c in report.candidates] == [control]
    # The scope's cutoff is version1, but the resolution must include version2,
    # even outside the analog publication period. Hold existence is not scoped.
    assert holds(storage, company, "1" * 19, 1, legacy) == (not resolved, not resolved)


@pytest.mark.parametrize("mode", ["null", "string", "empty", "truncated", "changed_decision"])
def test_malformed_or_changed_audit_never_resolves_scope(
    storage, legacy, tmp_path, monkeypatch, mode
):
    import procurement.storage.eis_notice_projection as writer

    company = tenant()
    request, control = setup(storage, company)
    original = writer._json
    faults = []

    def fault(value):
        result = original(value)
        if (
            isinstance(result, dict)
            and result.get("batch", {}).get("company_id") == company
            and isinstance(result.get("decisions"), list)
            and len(result["decisions"]) == 2
            and result["decisions"][0]["snapshot_sha256"] != "f" * 64
        ):
            if mode == "null":
                result["decisions"] = None
            elif mode == "string":
                result["decisions"] = "not-an-array"
            elif mode == "empty":
                result["decisions"] = []
            elif mode == "truncated":
                result["decisions"] = result["decisions"][:1]
            else:
                result["decisions"][0]["snapshot_sha256"] = "f" * 64
            faults.append(True)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(writer, "_json", fault)
        project(
            storage,
            company,
            tmp_path,
            members=(
                ("paper.xml", xml()),
                ("other.xml", xml("2" * 19).replace("Бумага A4".encode(), "Сервер".encode())),
            ),
        )
    assert faults == [True]
    assert [c.notice for c in same(storage, company, request, legacy).candidates] == [control]
    assert holds(storage, company, "1" * 19, 1, legacy) == (True, True)


def test_unrelated_incomplete_receipt_keeps_global_hold_and_other_tenant_isolated(
    storage, legacy, tmp_path
):
    company = tenant()
    request, _ = setup(storage, company)
    receipt, _ = project(storage, company, tmp_path)
    with storage.transaction(company, consistent_read=True) as conn:
        row = dict(
            conn.execute(
                select(eis_notice_variant_receipts).where(
                    eis_notice_variant_receipts.c.receipt_id == receipt.receipt_id,
                )
            )
            .mappings()
            .one()
        )
    row["receipt_id"] = str(uuid4())
    row["manifest_sha256"] = "f" * 64
    row["evidence"] = {**row["evidence"], "manifest_sha256": "f" * 64}
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_notice_variant_receipts).values(**row))
    assert holds(storage, company, "1" * 19, 1, legacy) == (True, True)
    for reader in (legacy[0].read_analog_candidates, read_analog_candidates):
        with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
            reader(storage, company, request, now=NOW)
    other = tenant()
    other_request, control = setup(storage, other)
    assert [c.notice for c in same(storage, other, other_request, legacy).candidates] == [control]


def test_foreign_resolution_scope_fails_closed_while_default_consumer_unchanged(
    storage, legacy, tmp_path
):
    company = tenant()
    setup(storage, company)
    project(storage, company, tmp_path)
    assert holds(storage, company, "1" * 19, 1, legacy, scope_company="foreign") == (False, True)
