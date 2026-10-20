"""HTTP boundary for creating a case version from exact document evidence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import (
    CaseEvidenceNotFound,
    InvalidCaseEvidence,
    Principal,
    VersionConflict,
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
    document_gate_check_from_binding,
)
from procurement.documents.completeness_review import CompletenessReviewRecord
from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import DocumentRole
from procurement.domain.cases import (
    CaseAssessment,
    GateCheck,
    GateKind,
    ProcurementCase,
    case_input_digest,
)
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)
TENANT = "demo-company"
PAPER_CASE = Path(__file__).parent.parent / "examples" / "paper_case.json"
OPERATOR_HEADERS = {"Authorization": "Bearer operator-token", "Idempotency-Key": "case-key-1"}


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


def _case_draft(case_id: str) -> dict[str, Any]:
    payload = json.loads(PAPER_CASE.read_text(encoding="utf-8"))
    payload["case_id"] = case_id
    payload["version"] = 1
    payload["company_id"] = TENANT
    payload["profile"]["company_id"] = TENANT
    if payload.get("selected_quote") is not None:
        payload["selected_quote"]["company_id"] = TENANT
    payload["assessment"] = None
    return payload


class _Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "operator-token": Principal(
                company_id=TENANT,
                actor_id="case-operator",
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


class _FakeCaseFromEvidenceService:
    def __init__(self) -> None:
        self.evidence = _evidence()
        self.decision = _decision(self.evidence)
        self.cases: dict[tuple[str, str, int], ProcurementCase] = {}
        self.receipts: dict[tuple[str, str], tuple[str, tuple[str, int]]] = {}

    async def create_case_from_evidence(
        self,
        *,
        company_id: str,
        actor_id: str,
        case: ProcurementCase,
        binding_id: str,
        manifest_evidence_sha256: str,
        decision_sha256: str,
        other_checks: tuple[GateCheck, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        key = (company_id, idempotency_key)
        if key in self.receipts:
            known_digest, identity = self.receipts[key]
            if known_digest != request_digest:
                raise VersionConflict("changed idempotent replay")
            return self.cases[identity]
        if binding_id != "binding-1":
            raise CaseEvidenceNotFound("unknown binding")
        if manifest_evidence_sha256 != self.evidence.manifest.evidence_sha256:
            raise InvalidCaseEvidence("stale manifest evidence")
        if decision_sha256 != self.decision.decision_sha256:
            raise InvalidCaseEvidence("stale terminal decision")
        if case.assessment is not None:
            raise InvalidCaseEvidence("assessment is server-owned")
        if any(check.kind is GateKind.DOCUMENT for check in other_checks):
            raise InvalidCaseEvidence("DOCUMENT check is server-derived")
        try:
            binding = build_case_document_evidence_binding(
                self.evidence,
                self.decision,
                company_id=company_id,
                binding_id=binding_id,
                bound_by=actor_id,
                bound_at=NOW,
            )
            document_check = document_gate_check_from_binding(binding)
            assessment = CaseAssessment(
                reviewer_id=actor_id,
                assessed_at=NOW,
                input_digest=case_input_digest(case),
                checks=(document_check, *other_checks),
            )
            full = ProcurementCase.model_validate(
                case.model_dump(mode="python")
                | {"assessment": assessment.model_dump(mode="python")}
            )
        except ValueError as error:
            raise InvalidCaseEvidence("case cannot be built from evidence") from error
        identity = (company_id, full.case_id, full.version)
        if identity in self.cases:
            raise VersionConflict("case version already exists")
        self.cases[identity] = full
        self.receipts[key] = (request_digest, identity)
        return full


@pytest.fixture
def app():
    return create_app(_FakeCaseFromEvidenceService(), _Authenticator())


def call(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def _payload(case_id: str, fake: _FakeCaseFromEvidenceService) -> dict[str, Any]:
    return {
        "case": _case_draft(case_id),
        "binding_id": "binding-1",
        "manifest_evidence_sha256": fake.evidence.manifest.evidence_sha256,
        "decision_sha256": fake.decision.decision_sha256,
        "other_checks": [],
    }


def test_case_created_with_server_derived_document_gate(app: object) -> None:
    fake = _FakeCaseFromEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    created = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json=_payload("case-1", fake),
        headers=OPERATOR_HEADERS,
    )
    assert created.status_code == 201, created.text
    assert created.headers["Cache-Control"] == "no-store"
    body = created.json()
    assert body["case_id"] == "case-1"
    assert body["assessment"]["reviewer_id"] == "case-operator"
    kinds = [check["kind"] for check in body["assessment"]["checks"]]
    assert kinds == ["document"]
    document_check = body["assessment"]["checks"][0]
    assert document_check["status"] == "PASS"
    assert document_check["evidence"]
    assert body["assessment"]["input_digest"]


def test_exact_replay_returns_same_case_and_changed_replay_conflicts(app: object) -> None:
    fake = _FakeCaseFromEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    first = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json=_payload("case-1", fake),
        headers=OPERATOR_HEADERS,
    )
    assert first.status_code == 201
    second = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json=_payload("case-1", fake),
        headers=OPERATOR_HEADERS,
    )
    assert second.status_code == 201
    assert second.json() == first.json()
    tampered = _payload("case-2", fake)
    conflict = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json=tampered,
        headers=OPERATOR_HEADERS,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "version_conflict"


def test_roles_and_tenant_are_enforced(app: object) -> None:
    fake = _FakeCaseFromEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    auditor = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json=_payload("case-1", fake),
        headers={"Authorization": "Bearer auditor-token", "Idempotency-Key": "case-key-9"},
    )
    assert auditor.status_code == 403
    assert (
        call(
            bound_app, "POST", "/v1/cases/from-evidence", json=_payload("case-1", fake)
        ).status_code
        == 401
    )
    mismatch = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json=_payload("case-1", fake),
        headers={"Authorization": "Bearer other-token", "Idempotency-Key": "case-key-8"},
    )
    assert mismatch.status_code == 403


def test_unknown_and_stale_evidence_are_rejected(app: object) -> None:
    fake = _FakeCaseFromEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    unknown = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json={**_payload("case-1", fake), "binding_id": "no-such-binding"},
        headers=OPERATOR_HEADERS,
    )
    assert unknown.status_code == 404
    stale = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json={**_payload("case-2", fake), "manifest_evidence_sha256": "0" * 64},
        headers={**OPERATOR_HEADERS, "Idempotency-Key": "case-key-3"},
    )
    assert stale.status_code == 422
    assert stale.json()["detail"] == "invalid_case_evidence"


def test_caller_owned_assessment_and_document_check_are_rejected(app: object) -> None:
    fake = _FakeCaseFromEvidenceService()
    bound_app = create_app(fake, _Authenticator())
    draft = _case_draft("case-1")
    draft["assessment"] = {
        "reviewer_id": "case-operator",
        "assessed_at": "2026-09-18T12:00:00+00:00",
        "input_digest": "0" * 64,
        "checks": [],
    }
    with_assessment = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json={**_payload("case-1", fake), "case": draft},
        headers=OPERATOR_HEADERS,
    )
    assert with_assessment.status_code == 422
    with_document = call(
        bound_app,
        "POST",
        "/v1/cases/from-evidence",
        json={
            **_payload("case-2", fake),
            "other_checks": [
                {
                    "kind": "document",
                    "status": "PASS",
                    "reason": "caller supplied",
                    "evidence": [],
                }
            ],
        },
        headers={**OPERATOR_HEADERS, "Idempotency-Key": "case-key-4"},
    )
    assert with_document.status_code == 422


def test_malformed_requests_are_rejected(app: object) -> None:
    assert (
        call(
            app,
            "POST",
            "/v1/cases/from-evidence",
            content=b"{}",
            headers={**OPERATOR_HEADERS, "Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        call(
            app,
            "POST",
            "/v1/cases/from-evidence",
            json={"case": {}, "binding_id": "x"},
            headers=OPERATOR_HEADERS,
        ).status_code
        == 422
    )
