"""Сквозная проверка нового пути: привязка → кейс → recommendation.

Фиксирует, что server-derived DOCUMENT-проверка ведёт себя как обычная
проверка в `evaluate_case`: PASS наследует решение ручного baseline, FAIL
блокирует кандидата через hard gate, UNKNOWN не превращается в допуск.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

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
    evaluate_case,
)
from procurement.domain.decisions import GateStatus, RecommendationDecision
from procurement.domain.provenance import Extractor, Provenance

PAPER_CASE = Path(__file__).parent.parent / "examples" / "paper_case.json"
AT = datetime.fromisoformat("2026-09-18T12:00:00+03:00")
OTHER_KINDS = (
    GateKind.LEGAL,
    GateKind.PARTICIPANT,
    GateKind.TECHNICAL,
    GateKind.COMPANY_POLICY,
    GateKind.LOGISTICS,
)


def _record(number: int, *, status: CompletenessStatus = CompletenessStatus.PASS):
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
        company_id="demo-company",
        review_id=f"review-{number}",
        source_document_id=document_id,
        source_document_sha256=str(number) * 64,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        extraction=extraction,
        created_by="operator-a",
        created_at=AT,
    )
    if status is CompletenessStatus.FAIL:
        block_decisions = (
            CompletenessBlockDecision(
                unmapped_index=0,
                disposition=UnmappedDisposition.MATERIAL_REQUIREMENT,
                rationale="material requirement remains unstructured",
            ),
        )
    else:
        block_decisions = (
            CompletenessBlockDecision(
                unmapped_index=0,
                disposition=UnmappedDisposition.NON_REQUIREMENT,
                rationale="residual text is informational",
            ),
        )
    decision = build_completeness_review_decision(
        snapshot,
        status=status,
        scope="entire native document",
        reason="reviewed",
        block_decisions=block_decisions,
        decided_by="single-reviewer",
        decided_at=AT,
        review_reference=f"single-{number}",
    )
    return CompletenessReviewRecord(snapshot=snapshot, decision=decision)


def _evidence(statuses=(CompletenessStatus.PASS, CompletenessStatus.PASS)):
    records = tuple(
        _record(number, status=status) for number, status in enumerate(statuses, start=1)
    )
    manifest = build_document_set_evidence_manifest(
        tuple(record.snapshot for record in records),
        company_id="demo-company",
        manifest_id="manifest-1",
        scope="declared tender package",
        created_by="operator-b",
        created_at=AT,
    )
    return build_document_set_review_evidence(manifest, records)


def _attestations(evidence):
    return tuple(
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


def _terminal(evidence, status: CompletenessStatus):
    if status is CompletenessStatus.UNKNOWN:
        return build_document_set_review_decision(
            evidence,
            attestations=_attestations(evidence),
            inventory_assessment=DocumentSetInventoryAssessment.UNRESOLVED,
            inventory_rationale="inventory not proven",
            cross_document_assessment=DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES,
            cross_document_rationale="compared together",
            reviewer_findings=(),
            status=status,
            reason="incomplete package",
            decided_by="package-reviewer",
            decided_at=AT,
        )
    return build_document_set_review_decision(
        evidence,
        attestations=_attestations(evidence),
        inventory_assessment=DocumentSetInventoryAssessment.CONFIRMED_FOR_DECLARED_SCOPE,
        inventory_rationale="all files present",
        cross_document_assessment=DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES,
        cross_document_rationale="compared together",
        reviewer_findings=(),
        status=status,
        reason="complete for scope",
        decided_by="package-reviewer",
        decided_at=AT,
    )


def _binding_for(status: CompletenessStatus):
    if status is CompletenessStatus.FAIL:
        evidence = _evidence(
            statuses=(CompletenessStatus.FAIL, CompletenessStatus.PASS),
        )
    else:
        evidence = _evidence()
    return build_case_document_evidence_binding(
        evidence,
        _terminal(evidence, status),
        company_id="demo-company",
        binding_id=f"binding-{status.value.lower()}",
        bound_by="case-operator",
        bound_at=AT,
    )


def _draft_payload() -> dict[str, Any]:
    payload = json.loads(PAPER_CASE.read_text(encoding="utf-8"))
    payload["assessment"] = None
    return payload


def _manual_pass(kind: GateKind) -> GateCheck:
    return GateCheck(
        kind=kind,
        status=GateStatus.PASS,
        reason="Синтетическая ручная проверка e2e",
        evidence=(
            Provenance(
                document_id="SYNTHETIC-e2e",
                locator="synthetic check",
                extractor=Extractor.MANUAL,
                confidence=1.0,
            ),
        ),
    )


def _case_with(document_check: GateCheck) -> ProcurementCase:
    draft = ProcurementCase.model_validate(_draft_payload())
    assessment = CaseAssessment(
        reviewer_id="e2e-reviewer",
        assessed_at=AT,
        input_digest=case_input_digest(draft),
        checks=(document_check, *(_manual_pass(kind) for kind in OTHER_KINDS)),
    )
    return ProcurementCase.model_validate(
        draft.model_dump(mode="python") | {"assessment": assessment.model_dump(mode="python")}
    )


def test_evidence_pass_matches_manual_pass_baseline() -> None:
    derived = _case_with(document_gate_check_from_binding(_binding_for(CompletenessStatus.PASS)))
    baseline = _case_with(_manual_pass(GateKind.DOCUMENT))
    assert derived.assessment is not None
    assert derived.assessment.input_digest == case_input_digest(
        ProcurementCase.model_validate({**derived.model_dump(mode="python"), "assessment": None})
    )
    assert evaluate_case(derived, at=AT).decision is RecommendationDecision.PARTICIPATE
    assert evaluate_case(derived, at=AT) == evaluate_case(baseline, at=AT)


def test_evidence_fail_blocks_candidate_through_hard_gate() -> None:
    derived = _case_with(document_gate_check_from_binding(_binding_for(CompletenessStatus.FAIL)))
    recommendation = evaluate_case(derived, at=AT)
    assert recommendation.decision is RecommendationDecision.DO_NOT_PARTICIPATE
    assert any(reason.startswith("document:") for reason in recommendation.reasons)


def test_evidence_unknown_never_becomes_pass() -> None:
    derived = _case_with(document_gate_check_from_binding(_binding_for(CompletenessStatus.UNKNOWN)))
    recommendation = evaluate_case(derived, at=AT)
    assert recommendation.decision is RecommendationDecision.NEEDS_ANALYSIS
    assert any("document:" in reason for reason in recommendation.reasons)
