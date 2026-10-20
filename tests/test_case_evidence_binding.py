"""Явная привязка terminal document-set решения к заготовке кейса."""

from datetime import UTC, datetime

import pytest

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
    canonical_json_sha256,
    document_gate_check_from_binding,
)
from procurement.documents.case_evidence import CaseDocumentEvidenceBinding
from procurement.documents.completeness_review import CompletenessReviewRecord
from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import DocumentRole
from procurement.domain.cases import GateKind
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)


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
        company_id="tenant-a",
        review_id=f"review-{number}",
        source_document_id=document_id,
        source_document_sha256=str(number) * 64,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        extraction=extraction,
        created_by="operator-a",
        created_at=NOW,
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
        decided_at=NOW,
        review_reference=f"single-{number}",
    )
    return CompletenessReviewRecord(snapshot=snapshot, decision=decision)


def _evidence(statuses=(CompletenessStatus.PASS, CompletenessStatus.PASS)):
    records = tuple(
        _record(number, status=status) for number, status in enumerate(statuses, start=1)
    )
    manifest = build_document_set_evidence_manifest(
        tuple(record.snapshot for record in records),
        company_id="tenant-a",
        manifest_id="manifest-1",
        scope="declared tender package",
        created_by="operator-b",
        created_at=NOW,
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


def _decide(evidence, **updates):
    values = {
        "attestations": _attestations(evidence),
        "inventory_assessment": DocumentSetInventoryAssessment.CONFIRMED_FOR_DECLARED_SCOPE,
        "inventory_rationale": "all files present",
        "cross_document_assessment": DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES,
        "cross_document_rationale": "compared together",
        "reviewer_findings": (),
        "status": CompletenessStatus.PASS,
        "reason": "complete for scope",
        "decided_by": "package-reviewer",
        "decided_at": NOW,
    }
    values.update(updates)
    return build_document_set_review_decision(evidence, **values)


def _bind(evidence, decision, **updates):
    values = {
        "company_id": "tenant-a",
        "binding_id": "case-binding-1",
        "bound_by": "case-operator",
        "bound_at": NOW,
    }
    values.update(updates)
    return build_case_document_evidence_binding(evidence, decision, **values)


def test_pass_binding_preserves_exact_digests() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    binding = _bind(evidence, decision)
    assert binding.status is CompletenessStatus.PASS
    assert binding.manifest_id == evidence.manifest.manifest_id
    assert binding.manifest_evidence_sha256 == evidence.manifest.evidence_sha256
    assert binding.decision_sha256 == decision.decision_sha256
    assert binding.member_count == 2
    assert binding.member_review_ids == ("review-1", "review-2")
    assert len(binding.binding_sha256) == 64


def test_fail_decision_binding_preserves_fail() -> None:
    evidence = _evidence(
        statuses=(CompletenessStatus.FAIL, CompletenessStatus.PASS),
    )
    decision = _decide(evidence, status=CompletenessStatus.FAIL)
    binding = _bind(evidence, decision)
    assert binding.status is CompletenessStatus.FAIL


def test_unknown_decision_binding_preserves_unknown() -> None:
    evidence = _evidence()
    decision = _decide(
        evidence,
        status=CompletenessStatus.UNKNOWN,
        inventory_assessment=DocumentSetInventoryAssessment.UNRESOLVED,
        inventory_rationale="inventory not proven",
    )
    binding = _bind(evidence, decision)
    assert binding.status is CompletenessStatus.UNKNOWN


def test_tenant_mismatch_rejected() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    with pytest.raises(ValueError, match="tenant"):
        _bind(evidence, decision, company_id="tenant-b")


def test_stale_decision_digest_rejected() -> None:
    evidence = _evidence()
    other_records = tuple(_record(number) for number in (3, 4))
    other_manifest = build_document_set_evidence_manifest(
        tuple(record.snapshot for record in other_records),
        company_id="tenant-a",
        manifest_id="manifest-1",
        scope="declared tender package",
        created_by="operator-b",
        created_at=NOW,
    )
    other_evidence = build_document_set_review_evidence(other_manifest, other_records)
    other = _decide(other_evidence, decided_by="other-reviewer")
    with pytest.raises(ValueError, match=r"exact evidence|stale|match"):
        build_case_document_evidence_binding(
            evidence,
            other,
            company_id="tenant-a",
            binding_id="case-binding-1",
            bound_by="case-operator",
            bound_at=NOW,
        )
    assert other.decision_sha256 != _decide(evidence).decision_sha256


def test_binder_must_differ_from_decider() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    with pytest.raises(ValueError, match="differ"):
        _bind(evidence, decision, bound_by="package-reviewer")


def test_naive_bound_at_rejected() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    with pytest.raises(ValueError, match="timezone"):
        _bind(evidence, decision, bound_at=datetime(2026, 9, 18, 12, 0, 0))


def test_blank_binding_id_rejected() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    with pytest.raises(ValueError, match=r"blank|ID"):
        _bind(evidence, decision, binding_id="   ")


def test_binding_digest_tamper_rejected() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    binding = _bind(evidence, decision)
    with pytest.raises(ValueError, match="digest"):
        CaseDocumentEvidenceBinding.model_validate(
            {**binding.model_dump(mode="python"), "binding_sha256": "0" * 64}
        )


def test_decision_for_other_manifest_rejected() -> None:
    evidence = _evidence()
    other_records = tuple(_record(number) for number in (1, 2))
    other_manifest = build_document_set_evidence_manifest(
        tuple(record.snapshot for record in other_records),
        company_id="tenant-a",
        manifest_id="manifest-2",
        scope="declared tender package",
        created_by="operator-b",
        created_at=NOW,
    )
    other_evidence = build_document_set_review_evidence(other_manifest, other_records)
    other_decision = _decide(other_evidence)
    with pytest.raises(ValueError, match=r"manifest"):
        build_case_document_evidence_binding(
            evidence,
            other_decision,
            company_id="tenant-a",
            binding_id="case-binding-1",
            bound_by="case-operator",
            bound_at=NOW,
        )


def test_binding_digest_is_canonical() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    binding = _bind(evidence, decision)
    payload = binding.model_dump(mode="json", exclude={"binding_sha256"})
    assert canonical_json_sha256(payload) == binding.binding_sha256


def _bound(status: CompletenessStatus = CompletenessStatus.PASS):
    if status is CompletenessStatus.FAIL:
        evidence = _evidence(
            statuses=(CompletenessStatus.FAIL, CompletenessStatus.PASS),
        )
        decision = _decide(evidence, status=CompletenessStatus.FAIL)
    elif status is CompletenessStatus.UNKNOWN:
        evidence = _evidence()
        decision = _decide(
            evidence,
            status=CompletenessStatus.UNKNOWN,
            inventory_assessment=DocumentSetInventoryAssessment.UNRESOLVED,
            inventory_rationale="inventory not proven",
        )
    else:
        evidence = _evidence()
        decision = _decide(evidence)
    return _bind(evidence, decision)


def test_document_gate_inherits_pass_with_exact_provenance() -> None:
    check = document_gate_check_from_binding(_bound())
    assert check.kind is GateKind.DOCUMENT
    assert check.status is GateStatus.PASS
    assert check.reason.strip()
    (provenance,) = check.evidence
    assert provenance.document_id == "manifest-1"
    assert "terminal decision" in provenance.locator
    assert len(provenance.locator.split()[-1]) == 64
    assert provenance.extractor is Extractor.MANUAL
    assert provenance.confidence == 1.0


def test_document_gate_fail_keeps_hard_gate_evidence() -> None:
    check = document_gate_check_from_binding(_bound(CompletenessStatus.FAIL))
    assert check.kind is GateKind.DOCUMENT
    assert check.status is GateStatus.FAIL
    assert check.evidence


def test_document_gate_unknown_stays_unknown() -> None:
    check = document_gate_check_from_binding(_bound(CompletenessStatus.UNKNOWN))
    assert check.status is GateStatus.UNKNOWN


def test_document_gate_is_deterministic() -> None:
    binding = _bound()
    assert document_gate_check_from_binding(binding) == document_gate_check_from_binding(binding)


def test_document_gate_rejects_tampered_binding() -> None:
    binding = _bound()
    with pytest.raises(ValueError, match="digest"):
        document_gate_check_from_binding(binding.model_copy(update={"binding_sha256": "0" * 64}))
