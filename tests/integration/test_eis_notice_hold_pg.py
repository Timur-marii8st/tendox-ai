"""Unresolved evidence cannot be reused through search, caches, jobs or economics."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select
from test_eis_document_queue_pg import UID, admit, docx_bytes
from test_eis_notice_index_pg import storage as storage_fixture
from test_eis_notice_variants_pg import batch

from procurement.domain.discovery_economics import DiscoveryCostInput
from procurement.sources.eis_document_worker import run_document_step
from procurement.storage.eis_comparison import EisComparisonRequest, get_eis_comparison
from procurement.storage.eis_document_store import (
    document_read_gate,
    get_document_analysis,
    get_document_status,
    plan_document_job,
    reanalyze_received_document,
    record_document_outcome,
)
from procurement.storage.eis_evidence_bridge import estimate_eis_notice, get_eis_evidence_bridge
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_mixed_comparison import MixedComparisonRequest, get_mixed_comparison
from procurement.storage.eis_notice_hold import assert_notice_source_usable, read_notice_source_hold
from procurement.storage.eis_notice_variants import store_notice_variants
from procurement.storage.eis_position_projection import project_notice_positions
from procurement.storage.eis_source_estimate import SourceEstimateRequest, get_source_estimate
from procurement.storage.models import (
    audit_events,
    eis_document_analyses,
    eis_document_blobs,
    eis_document_jobs,
    eis_document_observations,
    eis_notice_position_projections,
    eis_notice_variant_receipts,
    eis_notice_versions,
)
from test_eis_notice_conflicts import notice

NOW = datetime(2026, 10, 4, tzinfo=UTC)
REASON = "NOTICE_VARIANT_REVIEW_REQUIRED"
COSTS = DiscoveryCostInput(
    goods="1", expenses="1", vat_rate="0.20", basis="Synthetic", costs_complete_ack=True
)


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def hold(storage, company, tmp_path, ref, *, version=None, singleton=False):
    xml = notice(version=str(version or ref.version_number)).replace(
        b"0373100047426001450", ref.purchase_number.encode()
    )
    members = (
        (("a.xml", xml),)
        if singleton
        else (("a.xml", xml), ("b.xml", xml.replace(b"Synthetic", b"Changed")))
    )
    evidence, diagnosis = batch(storage, company, tmp_path, members=members)
    return store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return {
            table.name: conn.scalar(select(func.count()).select_from(table))
            for table in (
                audit_events,
                eis_document_jobs,
                eis_document_observations,
                eis_document_blobs,
                eis_document_analyses,
                eis_notice_position_projections,
                eis_notice_versions,
            )
        }


def test_existing_receipts_analysis_projection_and_economics_cannot_bypass_hold(storage, tmp_path):
    company = "hold-cache-" + uuid4().hex
    content = docx_bytes()
    ref = admit(storage, company, len(content))
    other = admit(storage, company, len(content), number=ref.purchase_number[:-1] + "5")
    plan_document_job(storage, company, ref, actor_id="test")
    record_document_outcome(storage, company, ref, UID, actor_id="test", content=content)
    project_notice_positions(storage, company, ref, actor_id="test")
    assert get_document_analysis(storage, company, ref, UID).status in {"PASS", "UNKNOWN"}
    get_eis_evidence_bridge(storage, company, ref, now=NOW)
    hold(storage, company, tmp_path, ref)
    before = counts(storage, company)
    operations = (
        lambda: get_document_status(storage, company, ref),
        lambda: get_document_analysis(storage, company, ref, UID),
        lambda: plan_document_job(storage, company, ref, actor_id="test"),
        lambda: reanalyze_received_document(storage, company, ref, UID, actor_id="test"),
        lambda: record_document_outcome(
            storage, company, ref, UID, actor_id="test", content=content
        ),
        lambda: project_notice_positions(storage, company, ref, actor_id="test"),
        lambda: get_eis_evidence_bridge(storage, company, ref, now=NOW),
        lambda: estimate_eis_notice(storage, company, ref, COSTS),
        lambda: get_eis_comparison(
            storage, company, EisComparisonRequest(notices=(ref, other)), now=NOW
        ),
        lambda: get_mixed_comparison(
            storage,
            company,
            MixedComparisonRequest.model_validate(
                {"notices": [{"law": "44", **r.model_dump()} for r in (ref, other)]}
            ),
            now=NOW,
        ),
        lambda: get_source_estimate(
            storage,
            company,
            SourceEstimateRequest.model_validate(
                {"notice": {"law": "44", **ref.model_dump()}, "costs": COSTS.model_dump()}
            ),
            actor_id="test",
            now=NOW,
        ),
    )
    for operation in operations:
        with pytest.raises(ValueError, match=REASON):
            operation()
        assert counts(storage, company) == before
    result = search_eis_index(storage, company, "бумага", now=NOW)
    assert result.held_current_notices == 1 and result.matched_count == result.eligible_count == 1
    assert [r.purchase_number for r in result.matched] == [other.purchase_number]
    assert counts(storage, company) == before


@pytest.mark.parametrize(
    "delta,singleton,held", [(0, False, True), (1, True, True), (-1, False, False)]
)
def test_version_cutoff_and_cross_tenant_never_turn_hold_into_pass(
    storage, tmp_path, delta, singleton, held
):
    company = "hold-version-" + uuid4().hex
    ref = admit(storage, company, 0, listed=False, version=2)
    hold(storage, company, tmp_path, ref, version=2 + delta, singleton=singleton)
    state = read_notice_source_hold(storage, company, ref.purchase_number, 2)
    assert (state.status == "HOLD") is held and state.resolution == "UNKNOWN"
    other = "other-" + uuid4().hex
    assert read_notice_source_hold(storage, other, ref.purchase_number, 2).status == "NO_HOLD"
    with storage.transaction(other, consistent_read=True) as conn:
        assert_notice_source_usable(conn, other, ref.purchase_number, 2)
    if held:
        with pytest.raises(ValueError, match=REASON):
            get_document_status(storage, company, ref)
    else:
        assert get_document_status(storage, company, ref).version_status == "CURRENT_KNOWN_VERSION"


def test_worker_skips_held_old_job_and_audit_is_idempotent(storage, tmp_path):
    company = "hold-worker-" + uuid4().hex
    content = docx_bytes()
    held = admit(storage, company, len(content))
    valid = admit(storage, company, len(content), number=held.purchase_number[:-1] + "5")
    for ref in (held, valid):
        plan_document_job(storage, company, ref, actor_id="test")
    hold(storage, company, tmp_path, held)
    calls = []
    before = counts(storage, company)
    probe = run_document_step(
        storage,
        company,
        actor_id="test",
        now=NOW,
        min_free_bytes=1,
        downloader=lambda url: calls.append(url) or content,
        probe_only=True,
    )
    assert probe["status"] == "READY" and not calls and counts(storage, company) == before
    result = run_document_step(
        storage,
        company,
        actor_id="test",
        now=NOW,
        min_free_bytes=1,
        downloader=lambda url: calls.append(url) or content,
    )
    assert result["purchase_number"] == valid.purchase_number and len(calls) == 1
    assert result["skip_reasons"][REASON] == 1
    gate = document_read_gate(storage, company, held, actor_id="test", now=NOW)
    assert REASON in gate.blocked_reasons
    after = counts(storage, company)
    document_read_gate(storage, company, held, actor_id="test", now=NOW)
    assert counts(storage, company) == after


def test_hold_committing_during_download_blocks_final_receipt(storage, tmp_path):
    company = "hold-late-" + uuid4().hex
    content = docx_bytes()
    ref = admit(storage, company, len(content))
    plan_document_job(storage, company, ref, actor_id="test")
    before = counts(storage, company)

    def download(url):
        hold(storage, company, tmp_path, ref)
        return content

    result = run_document_step(
        storage, company, actor_id="test", now=NOW, min_free_bytes=1, downloader=download
    )
    assert result["status"] == "BLOCKED" and result["reason"] == REASON
    after = counts(storage, company)
    for name in ("eis_document_blobs", "eis_document_analyses", "eis_document_observations"):
        assert after[name] == before[name] == 0
    assert after["eis_notice_versions"] == before["eis_notice_versions"]


def test_receipt_without_complete_origins_holds_entire_tenant(storage, tmp_path):
    company = "hold-integrity-" + uuid4().hex
    ref = admit(storage, company, 0, listed=False)
    report = hold(storage, company, tmp_path, ref)
    with storage.transaction(company, consistent_read=True) as conn:
        row = dict(conn.execute(select(eis_notice_variant_receipts)).mappings().one())
    row["receipt_id"] = str(uuid4())
    row["manifest_sha256"] = "f" * 64
    row["evidence"] = {**row["evidence"], "manifest_sha256": "f" * 64}
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_notice_variant_receipts).values(**row))
    unrelated = ref.purchase_number[:-1] + "9"
    state = read_notice_source_hold(storage, company, unrelated, 1)
    assert state.status == "INTEGRITY_ERROR" and state.resolution == "UNKNOWN"
    with pytest.raises(ValueError, match=REASON), storage.transaction(company) as conn:
        assert_notice_source_usable(conn, company, unrelated, 1)
    assert (
        read_notice_source_hold(storage, "other-" + uuid4().hex, unrelated, 1).status == "NO_HOLD"
    )
    assert report.receipt_id != row["receipt_id"]
    search = search_eis_index(storage, company, "бумага", now=NOW)
    assert search.held_current_notices == search.inspected_current_notices == 1
    assert not search.matched and search.eligible_count == search.matched_count == 0
