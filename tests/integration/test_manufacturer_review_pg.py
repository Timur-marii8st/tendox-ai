"""Real PostgreSQL gates for exact manufacturer evidence and independent review."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_manufacturer_search_pg import _capture

from procurement.domain.manufacturer_review import (
    CitationClaim,
    LegalIdentity,
    ManufacturerCitation,
    ReviewStatus,
)
from procurement.storage import manufacturer_search as search_module
from procurement.storage.manufacturer_review import (
    ManufacturerReviewConflict,
    ManufacturerReviewIndependenceViolation,
    ManufacturerReviewNotFound,
    ManufacturerReviewSourceMismatch,
    decide_manufacturer_review,
    list_manufacturer_proposals,
    prepare_manufacturer_review,
    read_manufacturer_decision,
    read_proposal_artifact,
    store_evidence_artifact,
)
from procurement.storage.manufacturer_search import start_search
from procurement.storage.models import (
    manufacturer_evidence_artifacts,
    manufacturer_review_decisions,
)
from procurement.storage.repository import PostgresStorage

DATABASE = "procurement_manufacturer_test"
PDF = b"%PDF-1.4\nsynthetic official extract\n%%EOF"


@pytest.fixture
def storage() -> PostgresStorage:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required")
    if make_url(url).database != DATABASE:
        pytest.fail(f"manufacturer review requires isolated database {DATABASE}")
    return PostgresStorage.from_url(url)


def setup_proposal(storage, monkeypatch, *, company: str, uploader="uploader", proposer="operator"):
    monkeypatch.setattr(search_module, "capture_manufacturer_search", _capture)
    search = start_search(storage, company, "насос", proposer, str(uuid.uuid4()))
    artifact = store_evidence_artifact(
        storage, company, PDF, "Official extract", "https://example.test/extract.pdf",
        "extract.pdf", uploader, str(uuid.uuid4()),
    )
    citation = ManufacturerCitation(
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        page=1,
        locator="page 1",
        quote="Factory is the manufacturer of Pump",
        claims=tuple(CitationClaim),
    )
    proposal = prepare_manufacturer_review(
        storage, company, search.report.run_id, search.report.candidates[0].record_id,
        LegalIdentity(legal_name="Factory LLC", country_code="RU",
                      identifier_scheme="INN", registration_id="1234567890"),
        (citation,), proposer, str(uuid.uuid4()),
    )
    return artifact, proposal


def test_exact_artifact_proposal_and_independent_pass_roundtrip(storage, monkeypatch):
    company = "manufacturer-review-" + uuid.uuid4().hex
    artifact, saved = setup_proposal(storage, monkeypatch, company=company)
    command = str(uuid.uuid4())
    values = dict(
        identity_status=ReviewStatus.PASS,
        role_status=ReviewStatus.PASS,
        official_origin_confirmed=True,
        identity_fields_confirmed=True,
        exact_product_link_confirmed=True,
        effective_until=datetime.now(UTC) + timedelta(days=30),
        rationale="Exact official artifact confirms the entity and product-specific role.",
        citation_indexes=(0,),
        reviewer_id="independent-reviewer",
        command_id=command,
    )
    decision = decide_manufacturer_review(
        storage, company, saved.proposal.proposal_id, **values
    )
    replay = decide_manufacturer_review(
        storage, company, saved.proposal.proposal_id, **values
    )
    with pytest.raises(ManufacturerReviewConflict):
        decide_manufacturer_review(
            storage,
            company,
            saved.proposal.proposal_id,
            **{**values, "reviewer_id": "different-reviewer"},
        )
    retained = read_proposal_artifact(
        storage, company, saved.proposal.proposal_id, artifact.artifact_id
    )
    assert decision.current_status is ReviewStatus.PASS and decision.created
    assert replay.decision == decision.decision and not replay.created
    assert read_manufacturer_decision(
        storage, company, saved.proposal.proposal_id
    ).current_status is ReviewStatus.PASS
    assert retained.content == PDF and retained.metadata.origin_status == "CLAIMED_BY_UPLOADER"
    assert list_manufacturer_proposals(storage, company)[0].decision_status is ReviewStatus.PASS
    with pytest.raises(ManufacturerReviewNotFound):
        read_proposal_artifact(
            storage, "other-" + company, saved.proposal.proposal_id, artifact.artifact_id
        )


@pytest.mark.parametrize("reviewer", ["operator", "uploader"])
def test_proposer_or_uploader_cannot_review(storage, monkeypatch, reviewer):
    company = "manufacturer-independent-" + uuid.uuid4().hex
    _, saved = setup_proposal(storage, monkeypatch, company=company)
    with pytest.raises(ManufacturerReviewIndependenceViolation):
        decide_manufacturer_review(
            storage, company, saved.proposal.proposal_id,
            ReviewStatus.UNKNOWN, ReviewStatus.UNKNOWN, False, False, False, None,
            "Evidence remains unconfirmed.", (0,), reviewer, str(uuid.uuid4()),
        )


def test_idempotency_conflicts_and_rows_are_immutable(storage, monkeypatch):
    company = "manufacturer-review-conflict-" + uuid.uuid4().hex
    artifact, saved = setup_proposal(storage, monkeypatch, company=company)
    with pytest.raises(ManufacturerReviewConflict):
        store_evidence_artifact(
            storage, company, PDF + b"changed", "Official extract",
            "https://example.test/extract.pdf", "extract.pdf", "uploader",
            artifact.command_id,
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            update(manufacturer_evidence_artifacts)
            .where(manufacturer_evidence_artifacts.c.artifact_id == artifact.artifact_id)
            .values(source_title="changed")
        )
    with pytest.raises(ManufacturerReviewNotFound):
        read_manufacturer_decision(storage, company, saved.proposal.proposal_id)


def test_list_rejects_directly_inserted_unsupported_pass(storage, monkeypatch):
    company = "manufacturer-list-guard-" + uuid.uuid4().hex
    _, saved = setup_proposal(storage, monkeypatch, company=company)
    now = datetime.now(UTC)
    payload = {
        "schema_version": "manufacturer-review-decision-v1",
        "decision_id": str(uuid.uuid4()),
        "command_id": str(uuid.uuid4()),
        "proposal_id": saved.proposal.proposal_id,
        "proposal_sha256": saved.proposal.proposal_sha256,
        "dossier_sha256": saved.proposal.dossier_sha256,
        "identity_status": "PASS",
        "role_status": "PASS",
        "official_origin_confirmed": False,
        "identity_fields_confirmed": True,
        "exact_product_link_confirmed": True,
        "effective_until": (now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "rationale": "Synthetic invalid PASS",
        "citation_indexes": [0],
        "reviewed_by": "reviewer",
        "reviewed_at": now.isoformat().replace("+00:00", "Z"),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    payload["decision_sha256"] = hashlib.sha256(canonical).hexdigest()
    with storage.transaction(company) as conn:
        conn.execute(
            insert(manufacturer_review_decisions).values(
                company_id=company,
                decision_id=payload["decision_id"],
                command_id=payload["command_id"],
                proposal_id=saved.proposal.proposal_id,
                proposal_sha256=saved.proposal.proposal_sha256,
                decision_sha256=payload["decision_sha256"],
                decision_canonical=canonical,
                decision=payload,
                reviewed_by="reviewer",
                reviewed_at=now,
                effective_until=now + timedelta(days=30),
            )
        )
    with pytest.raises(
        ManufacturerReviewSourceMismatch, match="MANUFACTURER_DECISION_EVIDENCE_CONFLICT"
    ):
        list_manufacturer_proposals(storage, company)


def test_concurrent_artifact_command_replays_without_unique_error(storage):
    company, command = "manufacturer-race-" + uuid.uuid4().hex, str(uuid.uuid4())

    def write():
        return store_evidence_artifact(
            storage, company, PDF, "Official extract", "https://example.test/extract.pdf",
            "extract.pdf", "uploader", command,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: write(), range(2)))
    assert first == second


def test_concurrent_terminal_decisions_return_conflict_not_database_error(storage, monkeypatch):
    company = "manufacturer-decision-race-" + uuid.uuid4().hex
    _, saved = setup_proposal(storage, monkeypatch, company=company)

    def decide(command: str):
        try:
            return decide_manufacturer_review(
                storage, company, saved.proposal.proposal_id,
                ReviewStatus.UNKNOWN, ReviewStatus.UNKNOWN, False, False, False, None,
                "Evidence remains unconfirmed.", (0,), "independent-reviewer", command,
            )
        except ManufacturerReviewConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, (str(uuid.uuid4()), str(uuid.uuid4()))))
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ManufacturerReviewConflict) for item in outcomes) == 1
