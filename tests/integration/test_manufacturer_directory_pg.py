"""Real PostgreSQL projection tests for the bounded manufacturer directory."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.engine import make_url
from test_manufacturer_search_pg import _capture

from procurement.domain.manufacturer_review import (
    CitationClaim,
    LegalIdentity,
    ManufacturerCitation,
    ReviewStatus,
)
from procurement.storage import manufacturer_search as search_module
from procurement.storage.manufacturer_directory import build_manufacturer_directory
from procurement.storage.manufacturer_review import (
    ManufacturerReviewSourceMismatch,
    _build_proposal,
    decide_manufacturer_review,
    prepare_manufacturer_review,
    store_evidence_artifact,
)
from procurement.storage.manufacturer_search import ManufacturerSearchNotFound, start_search
from procurement.storage.models import manufacturer_review_proposals
from procurement.storage.repository import PostgresStorage

DATABASE = "procurement_manufacturer_test"
PDF = b"%PDF-1.4\nsynthetic independent manufacturer evidence\n%%EOF"


@pytest.fixture
def storage() -> PostgresStorage:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required")
    if make_url(url).database != DATABASE:
        pytest.fail(f"manufacturer directory requires isolated database {DATABASE}")
    return PostgresStorage.from_url(url)


def setup(storage, monkeypatch, *, company: str, decision=True):
    monkeypatch.setattr(
        search_module,
        "capture_manufacturer_search",
        lambda query: _capture(query, expiry=date(2027, 1, 1)),
    )
    search = start_search(storage, company, "насос", "operator", str(uuid.uuid4()))
    candidate = search.report.candidates[0]
    artifact = store_evidence_artifact(
        storage, company, PDF, "Official extract", "https://example.test/evidence.pdf",
        "evidence.pdf", "uploader", str(uuid.uuid4()),
    )
    citation = ManufacturerCitation(
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        page=1,
        locator="page 1",
        quote="Factory LLC manufactures the exact registry product.",
        claims=tuple(CitationClaim),
    )
    proposal = prepare_manufacturer_review(
        storage, company, search.report.run_id, candidate.record_id,
        LegalIdentity(legal_name="Factory LLC", country_code="RU",
                      identifier_scheme="INN", registration_id="123"),
        (citation,), "operator", str(uuid.uuid4()),
    )
    if decision:
        decide_manufacturer_review(
            storage, company, proposal.proposal.proposal_id,
            ReviewStatus.PASS, ReviewStatus.PASS, True, True, True,
            datetime.now(UTC) + timedelta(days=30), "Exact evidence confirmed.",
            (0,), "reviewer", str(uuid.uuid4()),
        )
    return search, candidate, artifact, citation, proposal


def test_directory_reconstructs_exact_pass_without_network(storage, monkeypatch):
    company = "manufacturer-directory-" + uuid.uuid4().hex
    search, candidate, _, _, proposal = setup(storage, monkeypatch, company=company)
    monkeypatch.setattr(
        search_module,
        "capture_manufacturer_search",
        lambda query: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    result = build_manufacturer_directory(storage, company, search.report.run_id)
    assert result.overall_status is ReviewStatus.PASS
    assert result.response_sha256 == search.report.response_sha256
    assert result.groups[0].record_ids == (candidate.record_id,)
    assert result.records[0].review_evidence[0].proposal_sha256 == (
        proposal.proposal.proposal_sha256
    )
    assert result.technical == result.seller == result.quote == "UNKNOWN"
    with pytest.raises(ManufacturerSearchNotFound):
        build_manufacturer_directory(storage, "other-" + company, search.report.run_id)


def test_missing_decision_is_unknown(storage, monkeypatch):
    company = "manufacturer-directory-unknown-" + uuid.uuid4().hex
    search, *_ = setup(storage, monkeypatch, company=company, decision=False)
    result = build_manufacturer_directory(storage, company, search.report.run_id)
    assert result.overall_status is ReviewStatus.UNKNOWN and result.groups == ()
    assert result.records[0].review_status is ReviewStatus.UNKNOWN


def test_requested_evaluation_time_controls_decision_expiry(storage, monkeypatch):
    company = "manufacturer-directory-expiry-" + uuid.uuid4().hex
    search, *_ = setup(storage, monkeypatch, company=company)
    result = build_manufacturer_directory(
        storage,
        company,
        search.report.run_id,
        evaluated_at=datetime.now(UTC) + timedelta(days=31),
    )
    assert result.records[0].review_status is ReviewStatus.FAIL
    assert result.overall_status is ReviewStatus.FAIL


def test_twenty_one_reviews_make_coverage_incomplete(storage, monkeypatch):
    company = "manufacturer-directory-overflow-" + uuid.uuid4().hex
    search, candidate, _artifact, citation, _ = setup(
        storage, monkeypatch, company=company, decision=False
    )
    identity = LegalIdentity(
        legal_name="Factory LLC", country_code="RU", identifier_scheme="INN",
        registration_id="123",
    )
    for _ in range(20):  # one proposal already exists
        prepare_manufacturer_review(
            storage, company, search.report.run_id, candidate.record_id, identity,
            (citation,), "operator", str(uuid.uuid4()),
        )
    result = build_manufacturer_directory(storage, company, search.report.run_id)
    assert result.coverage == "INCOMPLETE" and result.review_count == 20
    assert result.overall_status is ReviewStatus.UNKNOWN and result.groups == ()
    assert result.records[0].review_evidence == ()
    assert result.unreviewed_record_ids == ()


def test_naive_evaluation_time_is_rejected(storage, monkeypatch):
    company = "manufacturer-directory-time-" + uuid.uuid4().hex
    search, *_ = setup(storage, monkeypatch, company=company, decision=False)
    with pytest.raises(ValueError, match="TIME_NAIVE"):
        build_manufacturer_directory(
            storage, company, search.report.run_id, evaluated_at=datetime(2026, 10, 6)
        )


def test_forged_dossier_link_fails_closed(storage, monkeypatch):
    company = "manufacturer-directory-corrupt-" + uuid.uuid4().hex
    search, candidate, _, citation, saved = setup(
        storage, monkeypatch, company=company, decision=False
    )
    forged = _build_proposal(
        proposal_id=str(uuid.uuid4()),
        command_id=str(uuid.uuid4()),
        dossier=saved.proposal.dossier.model_copy(update={"product_name": "Forged product"}),
        claimed_identity=saved.proposal.claimed_identity,
        citations=(citation,),
        actor_id="operator",
        at=datetime.now(UTC),
    )
    canonical = json.dumps(
        forged.model_dump(mode="json", exclude={"proposal_sha256"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with storage.transaction(company) as conn:
        conn.execute(
            insert(manufacturer_review_proposals).values(
                company_id=company,
                proposal_id=forged.proposal_id,
                command_id=forged.command_id,
                run_id=search.report.run_id,
                record_id=candidate.record_id,
                dossier_sha256=forged.dossier_sha256,
                proposal_sha256=forged.proposal_sha256,
                proposal_canonical=canonical,
                proposal=forged.model_dump(mode="json"),
                proposed_by=forged.proposed_by,
                proposed_at=forged.proposed_at,
            )
        )
    with pytest.raises(
        ManufacturerReviewSourceMismatch,
        match="MANUFACTURER_DIRECTORY_PROPOSAL_SOURCE_CONFLICT",
    ):
        build_manufacturer_directory(storage, company, search.report.run_id)
