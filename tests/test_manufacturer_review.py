"""Independent manufacturer review cannot manufacture a PASS from weak evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from procurement.domain.manufacturer_review import (
    CitationClaim,
    LegalIdentity,
    ManufacturerCitation,
    ManufacturerReviewDecision,
    ManufacturerReviewProposal,
    ReviewStatus,
    StableManufacturerDossier,
    current_review_status,
    validate_decision,
)

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def proposal() -> ManufacturerReviewProposal:
    dossier = StableManufacturerDossier(
        run_id="00000000-0000-0000-0000-000000000001",
        record_id="6582fb75a4a4b05007bb2d05",
        response_sha256="a" * 64,
        source_record_index=1,
        registry_number="1",
        product_name="Насос",
        source_manufacturer_name="Завод",
        record_url="https://example.test/record",
        document_expires_on="2026-01-01",
    )
    citation = ManufacturerCitation(
        artifact_id="00000000-0000-0000-0000-000000000010",
        artifact_sha256="b" * 64,
        page=1,
        locator="page 1",
        quote="Official registry extract",
        claims=tuple(CitationClaim),
    )
    payload = {
        "schema_version": "manufacturer-review-proposal-v1",
        "proposal_id": "00000000-0000-0000-0000-000000000002",
        "command_id": "00000000-0000-0000-0000-000000000003",
        "dossier": dossier.model_dump(mode="json"),
        "dossier_sha256": digest(dossier.model_dump(mode="json")),
        "claimed_identity": LegalIdentity(
            legal_name="ООО Завод",
            country_code="RU",
            identifier_scheme="INN",
            registration_id="1234567890",
        ).model_dump(mode="json"),
        "citations": [citation.model_dump(mode="json")],
        "proposed_by": "operator",
        "proposed_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    payload["proposal_sha256"] = digest(payload)
    return ManufacturerReviewProposal.model_validate(payload)


def decision(**changes: object) -> ManufacturerReviewDecision:
    source = proposal()
    payload: dict[str, object] = {
        "schema_version": "manufacturer-review-decision-v1",
        "decision_id": "00000000-0000-0000-0000-000000000004",
        "command_id": "00000000-0000-0000-0000-000000000005",
        "proposal_id": source.proposal_id,
        "proposal_sha256": source.proposal_sha256,
        "dossier_sha256": source.dossier_sha256,
        "identity_status": "PASS",
        "role_status": "PASS",
        "official_origin_confirmed": True,
        "identity_fields_confirmed": True,
        "exact_product_link_confirmed": True,
        "effective_until": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "rationale": "Exact official extract confirms identity and product relationship.",
        "citation_indexes": [0],
        "reviewed_by": "reviewer",
        "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    payload.update(changes)
    payload["decision_sha256"] = digest(payload)
    return ManufacturerReviewDecision.model_validate(payload)


def test_complete_independent_evidence_can_receive_scoped_pass() -> None:
    source, result = proposal(), decision()
    validate_decision(source, result, artifact_uploaders={"uploader"})
    assert current_review_status(result, at=NOW) is ReviewStatus.PASS


@pytest.mark.parametrize("reviewer", ["operator", "uploader"])
def test_reviewer_must_be_independent(reviewer: str) -> None:
    source, result = proposal(), decision(reviewed_by=reviewer)
    with pytest.raises(ValueError, match="NOT_INDEPENDENT"):
        validate_decision(source, result, artifact_uploaders={"uploader"})


def test_missing_attestation_or_expiry_cannot_be_pass() -> None:
    source = proposal()
    for result in (
        decision(official_origin_confirmed=False),
        decision(effective_until=None),
        decision(exact_product_link_confirmed=False),
    ):
        with pytest.raises(ValueError, match="PASS_UNSUPPORTED"):
            validate_decision(source, result, artifact_uploaders={"uploader"})


def test_fail_precedes_missing_expiry_and_expiry_changes_current_status() -> None:
    failed = decision(identity_status="FAIL", role_status="UNKNOWN", effective_until=None)
    assert current_review_status(failed, at=NOW) is ReviewStatus.FAIL
    expired = decision(
        effective_until=(NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    )
    assert current_review_status(expired, at=NOW) is ReviewStatus.FAIL
    with pytest.raises(ValueError, match="NAIVE"):
        current_review_status(failed, at=datetime(2026, 10, 6))


def test_claims_are_canonical_and_booleans_are_strict() -> None:
    item = proposal().citations[0]
    assert list(item.claims) == sorted(item.claims, key=str)
    with pytest.raises(ValueError):
        decision(official_origin_confirmed=1)
