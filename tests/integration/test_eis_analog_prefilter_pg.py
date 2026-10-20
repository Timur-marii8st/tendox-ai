"""S208 disjoint lexical identities preserve the immutable S206 report contract."""

import hashlib
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.engine import make_url
from test_eis_analogs_pg import NOW
from test_eis_analogs_pg import ingest as ingest_fixture
from test_eis_notice_hold_pg import hold
from test_eis_notice_index_pg import storage as storage_fixture

from procurement.sources.eis_analogs import AnalogRequest
from procurement.storage import eis_notice_index
from procurement.storage.eis_analogs import read_analog_candidates
from procurement.storage.models import (
    audit_events,
    eis_document_jobs,
    eis_notice_search_keys,
    eis_notice_versions,
)

BASELINE_SHA = "12e41b09bf4c415549aaef265543d615b4f614d8a901f7bd707c36ebc52fc0b5"
GATE_DATABASE = "procurement_eis_test_20261005_s208"
GATE_DATABASES = {GATE_DATABASE, "procurement_eis_test_20261005_s209"}


@pytest.fixture(scope="module")
def storage():
    for key in ("DATABASE_URL", "DATABASE_ADMIN_URL"):
        if not os.environ.get(key):
            pytest.skip("Requires isolated PostgreSQL gate database")
        assert make_url(os.environ[key]).database in GATE_DATABASES
    yield from storage_fixture.__wrapped__()


@pytest.fixture(scope="module")
def legacy():
    path = os.environ.get("S208_BASELINE_ANALOGS_PATH")
    if not path:
        pytest.skip("Requires immutable S206 release reader")
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == BASELINE_SHA
    spec = importlib.util.spec_from_file_location("s208_baseline_analogs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_analog_candidates


def tenant():
    assert make_url(os.environ["DATABASE_URL"]).database in GATE_DATABASES
    return "s208-" + uuid4().hex


DEFAULT_KEYS = object()


def ingest(storage, company, number, *, keys=DEFAULT_KEYS, **kwargs):
    # Model pre-key versions or synthetic derivations at insert; no owner UPDATE,
    # evidence deletion, trigger disabling or production data mutation.
    assert make_url(os.environ["DATABASE_URL"]).database in GATE_DATABASES
    assert make_url(os.environ["DATABASE_ADMIN_URL"]).database in GATE_DATABASES
    if keys is DEFAULT_KEYS:
        return ingest_fixture(storage, company, number, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(eis_notice_index, "insert_search_keys", lambda *a, **kw: False)
        ref = ingest_fixture(storage, company, number, **kwargs)
    if keys is not None:
        with storage.transaction(company) as conn:
            conn.execute(
                insert(eis_notice_search_keys).values(
                    company_id=company,
                    purchase_number=ref.purchase_number,
                    version_number=ref.version_number,
                    keys=keys,
                    key_version="eis-lexical-v1",
                )
            )
    return ref


def same(storage, company, request, legacy):
    expected = legacy(storage, company, request, now=NOW)
    actual = read_analog_candidates(storage, company, request, now=NOW)
    assert actual == expected
    return actual


def request_for(storage, company):
    target = ingest(storage, company, "0" * 19, published="2026-10-04T12:00:00Z")
    return AnalogRequest(target=target, source_index=1, query="бумага")


def test_missing_empty_nonmatching_and_overlap_are_disjoint_and_do_not_write(storage, legacy):
    company = tenant()
    request = request_for(storage, company)
    refs = [
        ingest(storage, company, str(i) * 19, keys=keys)
        for i, keys in enumerate([DEFAULT_KEYS, [], None, ["server"]], 1)
    ]

    def counts():
        with storage.transaction(company, consistent_read=True) as conn:
            return tuple(
                conn.scalar(select(func.count()).select_from(table))
                for table in (
                    eis_notice_versions,
                    eis_notice_search_keys,
                    audit_events,
                    eis_document_jobs,
                )
            )

    before = counts()
    result = same(storage, company, request, legacy)
    assert [c.notice for c in result.candidates] == [refs[0], refs[2]]
    assert result.selected_notices == result.evaluated_positions == 2
    assert not result.selection_truncated and result.source_requests == 0
    assert counts() == before


def test_foreign_derivation_never_masks_missing_tenant_keys_or_leaks_candidates(storage, legacy):
    company, foreign = tenant(), tenant()
    request = request_for(storage, company)
    local = ingest(storage, company, "1" * 19, keys=None)
    ingest(storage, foreign, "1" * 19, keys=[])
    ingest(storage, foreign, "2" * 19)
    assert [c.notice for c in same(storage, company, request, legacy).candidates] == [local]
    with pytest.raises(ValueError, match="TARGET_NOT_FOUND_OR_MISMATCH"):
        read_analog_candidates(storage, foreign, request, now=NOW)


def test_latest_version_filters_apply_after_identity_union_without_duplicates(storage, legacy):
    company = tenant()
    request = request_for(storage, company)
    a = ingest(storage, company, "1" * 19)
    ingest(storage, company, "1" * 19, version=2, keys=[])
    ingest(storage, company, "2" * 19, keys=None)
    ingest(storage, company, "2" * 19, version=2, keys=["server"])
    ingest(storage, company, "3" * 19)
    c2 = ingest(storage, company, "3" * 19, version=2, keys=None)
    ingest(storage, company, "4" * 19)
    d2 = ingest(storage, company, "4" * 19, version=2)
    result = same(storage, company, request, legacy)
    assert [c.notice for c in result.candidates] == [c2, d2]
    assert a.purchase_number not in {c.notice.purchase_number for c in result.candidates}


@pytest.mark.parametrize("missing", [False, True])
def test_no_early_branch_limit_before_history_filter_and_ties(storage, legacy, missing):
    company = tenant()
    request = request_for(storage, company)
    for i in range(1, 24):
        ingest(
            storage,
            company,
            f"{i:019d}",
            published="2026-10-04T11:00:00Z",
            deadline="2026-10-10T12:00:00Z",
            keys=None if missing else DEFAULT_KEYS,
        )
    eligible = []
    for i in range(30, 51):
        ref = ingest(storage, company, f"{i:019d}", keys=None if i % 2 else DEFAULT_KEYS)
        eligible.append(ref)
    result = same(storage, company, request, legacy)
    assert [c.notice for c in result.candidates] == eligible[:20]
    assert result.selected_notices == 20 and result.selection_truncated


def test_period_boundaries_and_missing_target_date_still_match(storage, legacy):
    company = tenant()
    request = request_for(storage, company).model_copy(update={"lookback_days": 1})
    inside = ingest(storage, company, "1" * 19, published="2026-10-03T12:00:00Z", keys=None)
    ingest(storage, company, "2" * 19, published="2026-10-03T11:59:59Z")
    end = ingest(storage, company, "3" * 19, published="2026-10-04T12:00:00Z")
    ingest(storage, company, "4" * 19, published="2026-10-04T12:00:01Z")
    assert [c.notice for c in same(storage, company, request, legacy).candidates] == [end, inside]
    missing = ingest(storage, company, "9" * 19, published=None)
    result = same(
        storage, company, AnalogRequest(target=missing, source_index=1, query="бумага"), legacy
    )
    assert result.selected_notices == 0 and result.period_start is None
    assert "TARGET_PUBLICATION_MISSING" in result.reasons


@pytest.mark.parametrize("delta", [0, 1])
def test_missing_derivation_preserves_same_or_newer_source_hold(storage, legacy, tmp_path, delta):
    company = tenant()
    request = request_for(storage, company)
    blocked = ingest(storage, company, "1" * 19, version=2, keys=None)
    control = ingest(storage, company, "2" * 19, keys=None)
    hold(storage, company, tmp_path, blocked, version=2 + delta, singleton=delta == 1)
    assert [c.notice for c in same(storage, company, request, legacy).candidates] == [control]
