"""HTTP boundary for persisted case-document-evidence bindings."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import (
    CaseEvidenceConflict,
    CaseEvidenceNotFound,
    InvalidCaseEvidence,
    Principal,
)
from procurement.documents import (
    CompletenessBlockDecision,
    CompletenessStatus,
    ConstituentDecisionRef,
    DocumentSetCrossAssessment,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAssessment,
    DocumentSetMemberAttestation,
    ExtractionResult,
    ExtractionStatus,
    UnmappedDisposition,
    build_case_document_evidence_binding,
    build_completeness_review_decision,
    build_completeness_review_snapshot,
    build_document_set_evidence_manifest,
    build_document_set_review_decision,
    build_document_set_review_evidence,
)
from procurement.documents.completeness_review import CompletenessReviewRecord
from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import DocumentRole
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)
TENANT = "demo-company"
OPERATOR_HEADERS = {"Authorization": "Bearer operator-token", "Idempotency-Key": "binding-key-1"}


def _record(number: int):
    document_id = f"document-{number}"
    warranty = f"Гарантия не менее {number + 12} месяцев"
    neutral = f"Раздел общих условий процедуры {number}"
    extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(
            ExtractedBlock(
                text=warranty,
                provenance=Provenance(
                    document_id=document_id,
                    locator=f"paragraph {number}-1",
                    extractor=Extractor.NATIVE_DOCX,
                    confidence=1.0,
                ),
            ),
            ExtractedBlock(
                text=neutral,
                provenance=Provenance(
                    document_id=document_id,
                    locator=f"paragraph {number}-2",
                    extractor=Extractor.NATIVE_DOCX,
                    confidence=1.0,
                ),
            ),
        ),
        source_units_total=2,
        source_units_extracted=2,
        characters_extracted=len(warranty) + len(neutral),
    )
    snapshot = build_completeness_review_snapshot(
        company_id=TENANT,
        review_id=f"review-{number}",
        source_document_id=document_id,
        source_document_sha256=str(number) * 64,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        extraction=extraction,
        created_by="operator-a",
        created_at=NOW,
    )
    decision = build_completeness_review_decision(
        snapshot,
        status=CompletenessStatus.PASS,
        scope="entire native document",
        reason="reviewed",
        block_decisions=(
            CompletenessBlockDecision(
                unmapped_index=0,
                disposition=UnmappedDisposition.NON_REQUIREMENT,
                rationale="residual text is informational",
            ),
        ),
        decided_by="single-reviewer",
        decided_at=NOW,
        review_reference=f"single-{number}",
    )
    return CompletenessReviewRecord(snapshot=snapshot, decision=decision)


def _evidence():
    records = (_record(1), _record(2))
    manifest = build_document_set_evidence_manifest(
        tuple(record.snapshot for record in records),
        company_id=TENANT,
        manifest_id="manifest-1",
        scope="declared tender package",
        created_by="operator-b",
        created_at=NOW,
    )
    return build_document_set_review_evidence(manifest, records)


def _decision(evidence):
    attestations = tuple(
        DocumentSetMemberAttestation(
            reference=ConstituentDecisionRef(
                member_ordinal=item.member.ordinal,
                review_id=item.member.completeness_review_id,
                review_evidence_sha256=item.member.completeness_review_evidence_sha256,
                decision_sha256=item.decision_sha256,
            ),
            assessment=DocumentSetMemberAssessment.REVIEWED_IN_SCOPE,
            rationale="reviewed in scope",
        )
        for item in evidence.constituents
    )
    return build_document_set_review_decision(
        evidence,
        attestations=attestations,
        inventory_assessment=DocumentSetInventoryAssessment.CONFIRMED_FOR_DECLARED_SCOPE,
        inventory_rationale="all files present",
        cross_document_assessment=DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES,
        cross_document_rationale="compared together",
        reviewer_findings=(),
        status=CompletenessStatus.PASS,
        reason="complete for scope",
        decided_by="package-reviewer",
        decided_at=NOW,
    )


class _Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "operator-token": Principal(
                company_id=TENANT,
                actor_id="case-operator",
                access_role=AccessRole.OPERATOR,
            ),
            "self-operator-token": Principal(
                company_id=TENANT,
                actor_id="package-reviewer",
                access_role=AccessRole.OPERATOR,
            ),
            "auditor-token": Principal(
                company_id=TENANT,
                actor_id="auditor-a",
                access_role=AccessRole.AUDITOR,
            ),
            "other-token": Principal(
                company_id="other-company",
                actor_id="operator-b",
                access_role=AccessRole.OPERATOR,
            ),
        }.get(credential)


class _FakeCaseEvidenceService:
    def __init__(self) -> None:
        self.evidence = _evidence()
        self.decision = _decision(self.evidence)
        self.bindings: dict[tuple[str, str], object] = {}
        self.receipts: dict[tuple[str, str], tuple[str, str]] = {}

    async def store_case_document_evidence_binding(
        self,
        *,
        company_id: str,
        actor_id: str,
        binding_id: str,
        manifest_id: str,
        manifest_evidence_sha256: str,
        decision_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ):
        key = (company_id, idempotency_key)
        if key in self.receipts:
            known_digest, known_binding = self.receipts[key]
            if known_digest != request_digest:
                raise CaseEvidenceConflict("changed idempotent replay")
            return self.bindings[(company_id, known_binding)]
        if manifest_id != self.evidence.manifest.manifest_id:
            raise CaseEvidenceNotFound("unknown manifest")
        if manifest_evidence_sha256 != self.evidence.manifest.evidence_sha256:
            raise InvalidCaseEvidence("stale manifest evidence")
        if decision_sha256 != self.decision.decision_sha256:
            raise InvalidCaseEvidence("stale terminal decision")
        try:
            binding = build_case_document_evidence_binding(
                self.evidence,
                self.decision,
                company_id=company_id,
                binding_id=binding_id,
                bound_by=actor_id,
                bound_at=NOW,
            )
        except ValueError as error:
            raise InvalidCaseEvidence("exact evidence cannot be bound") from error
        self.bindings[(company_id, binding_id)] = binding
        self.receipts[key] = (request_digest, binding_id)
        return binding

    async def get_case_document_evidence_binding(self, *, company_id: str, binding_id: str):
        return self.bindings.get((company_id, binding_id))


@pytest.fixture
def app():
    return create_app(_FakeCaseEvidenceService(), _Authenticator())


def call(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def _payload(service: _FakeCaseEvidenceService) -> dict[str, str]:
    return {
        "manifest_id": service.evidence.manifest.manifest_id,
        "manifest_evidence_sha256": service.evidence.manifest.evidence_sha256,
        "decision_sha256": service.decision.decision_sha256,
    }


def test_empty_payload_is_rejected(app: object) -> None:
    created = call(
        app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json={},
        headers=OPERATOR_HEADERS,
    )
    assert created.status_code == 422
    assert created.json()["detail"] == "invalid_case_evidence"


def test_binding_roundtrip_is_exact_and_idempotent(app: object) -> None:
    fake = _FakeCaseEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    first = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=_payload(fake),
        headers=OPERATOR_HEADERS,
    )
    assert first.status_code == 201, first.text
    assert first.headers["Cache-Control"] == "no-store"
    body = first.json()
    assert body["manifest_id"] == "manifest-1"
    assert body["decision_sha256"] == fake.decision.decision_sha256
    assert body["status"] == "PASS"
    assert body["bound_by"] == "case-operator"
    second = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=_payload(fake),
        headers=OPERATOR_HEADERS,
    )
    assert second.status_code == 201
    assert second.json()["binding_id"] == body["binding_id"]
    fetched = call(
        bound_app,
        "GET",
        f"/v1/case-document-evidence-bindings/{body['binding_id']}",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert fetched.status_code == 200
    assert fetched.headers["Cache-Control"] == "no-store"
    assert fetched.json() == body


def test_changed_replay_conflicts(app: object) -> None:
    fake = _FakeCaseEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    payload = _payload(fake)
    first = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=payload,
        headers=OPERATOR_HEADERS,
    )
    assert first.status_code == 201
    tampered = dict(payload, decision_sha256="0" * 64)
    second = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=tampered,
        headers=OPERATOR_HEADERS,
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "case_evidence_conflict"


def test_roles_and_tenant_isolation(app: object) -> None:
    fake = _FakeCaseEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    created = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=_payload(fake),
        headers=OPERATOR_HEADERS,
    )
    binding_id = created.json()["binding_id"]
    auditor_post = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=_payload(fake),
        headers={"Authorization": "Bearer auditor-token", "Idempotency-Key": "binding-key-2"},
    )
    assert auditor_post.status_code == 403
    assert auditor_post.json()["detail"] == "operator_required"
    anonymous = call(bound_app, "POST", "/v1/case-document-evidence-bindings", json=_payload(fake))
    assert anonymous.status_code == 401
    foreign = call(
        bound_app,
        "GET",
        f"/v1/case-document-evidence-bindings/{binding_id}",
        headers={"Authorization": "Bearer other-token"},
    )
    assert foreign.status_code == 404
    missing = call(
        bound_app,
        "GET",
        "/v1/case-document-evidence-bindings/does-not-exist",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert missing.status_code == 404
    auditor_get = call(
        bound_app,
        "GET",
        f"/v1/case-document-evidence-bindings/{binding_id}",
        headers={"Authorization": "Bearer auditor-token"},
    )
    assert auditor_get.status_code == 200


def test_unknown_and_stale_evidence_are_rejected(app: object) -> None:
    fake = _FakeCaseEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    unknown = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json={
            "manifest_id": "no-such-manifest",
            "manifest_evidence_sha256": "0" * 64,
            "decision_sha256": "0" * 64,
        },
        headers=OPERATOR_HEADERS,
    )
    assert unknown.status_code == 404
    stale_manifest = dict(_payload(fake), manifest_evidence_sha256="0" * 64)
    rejected_manifest = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=stale_manifest,
        headers={**OPERATOR_HEADERS, "Idempotency-Key": "binding-key-3"},
    )
    assert rejected_manifest.status_code == 422
    assert rejected_manifest.json()["detail"] == "invalid_case_evidence"
    stale_decision = dict(_payload(fake), decision_sha256="1" * 64)
    rejected_decision = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=stale_decision,
        headers={**OPERATOR_HEADERS, "Idempotency-Key": "binding-key-4"},
    )
    assert rejected_decision.status_code == 422


def test_binder_equal_to_decider_is_rejected(app: object) -> None:
    fake = _FakeCaseEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    rejected = call(
        bound_app,
        "POST",
        "/v1/case-document-evidence-bindings",
        json=_payload(fake),
        headers={"Authorization": "Bearer self-operator-token", "Idempotency-Key": "binding-key-5"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "invalid_case_evidence"


def test_malformed_requests_are_rejected(app: object) -> None:
    assert (
        call(
            app,
            "POST",
            "/v1/case-document-evidence-bindings",
            content=b"{}",
            headers={**OPERATOR_HEADERS, "Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        call(
            app,
            "POST",
            "/v1/case-document-evidence-bindings",
            content=b"x" * (16 * 1024 + 1),
            headers={**OPERATOR_HEADERS, "Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        call(
            app,
            "POST",
            "/v1/case-document-evidence-bindings",
            content=b'{"manifest_id": "m", "manifest_id": "m", '
            b'"manifest_evidence_sha256": "'
            + b"0" * 64
            + b'", "decision_sha256": "'
            + b"0" * 64
            + b'"}',
            headers={**OPERATOR_HEADERS, "Content-Type": "application/json"},
        ).status_code
        == 422
    )
    assert (
        call(
            app,
            "POST",
            "/v1/case-document-evidence-bindings",
            json={
                "manifest_id": "manifest-1",
                "manifest_evidence_sha256": "not-a-digest",
                "decision_sha256": "0" * 64,
            },
            headers=OPERATOR_HEADERS,
        ).status_code
        == 422
    )
