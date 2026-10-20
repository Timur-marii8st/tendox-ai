"""Fail-closed review of an exact multi-document evidence manifest."""

import json
from datetime import UTC, date, datetime

import pytest

from procurement.documents import (
    CompletenessStatus,
    ConstituentDecisionRef,
    DocumentSetCrossAssessment,
    DocumentSetFinding,
    DocumentSetFindingKind,
    DocumentSetFindingOrigin,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAssessment,
    DocumentSetMemberAttestation,
    DocumentSetSourceBlockRef,
    ExtractionResult,
    ExtractionStatus,
    build_completeness_review_decision,
    build_completeness_review_snapshot,
    build_document_set_evidence_manifest,
    build_document_set_review_decision,
    build_document_set_review_evidence,
    canonical_json_sha256,
)
from procurement.documents.completeness_review import (
    CompletenessReviewRecord,
    CompletenessReviewSnapshot,
)
from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import DocumentRole
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def _record(number: int, *, deadline: date | None = None) -> CompletenessReviewRecord:
    document_id = f"document-{number}"
    text = f"Гарантия не менее {number + 12} месяцев"
    extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(
            ExtractedBlock(
                text=text,
                provenance=Provenance(
                    document_id=document_id,
                    locator=f"paragraph {number}",
                    extractor=Extractor.NATIVE_DOCX,
                    confidence=1.0,
                ),
            ),
        ),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=len(text),
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
    if deadline is not None:
        mapping = snapshot.mapping.model_copy(update={"delivery_deadline": deadline})
        payload = snapshot.model_dump(mode="json", exclude={"evidence_sha256"})
        payload["mapping"] = mapping.model_dump(mode="json")
        payload["evidence_sha256"] = canonical_json_sha256(payload)
        snapshot = CompletenessReviewSnapshot.model_validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
    decision = build_completeness_review_decision(
        snapshot,
        status=CompletenessStatus.PASS,
        scope="entire native document",
        reason="all requirements reviewed",
        block_decisions=(),
        decided_by="single-reviewer",
        decided_at=NOW,
        review_reference=f"single-{number}",
    )
    return CompletenessReviewRecord(snapshot=snapshot, decision=decision)


def _evidence(*, deadlines: tuple[date | None, date | None] = (None, None)):
    records = (_record(1, deadline=deadlines[0]), _record(2, deadline=deadlines[1]))
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
            rationale="reviewed in the declared package scope",
        )
        for item in evidence.constituents
    )


def _decide(evidence, **updates):
    attestations = updates.pop("attestations", None)
    values = {
        "attestations": _attestations(evidence) if attestations is None else attestations,
        "inventory_assessment": DocumentSetInventoryAssessment.CONFIRMED_FOR_DECLARED_SCOPE,
        "inventory_rationale": "all declared package files are present",
        "cross_document_assessment": DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES,
        "cross_document_rationale": "documents were compared together",
        "reviewer_findings": (),
        "status": CompletenessStatus.PASS,
        "reason": "complete for the exact declared scope",
        "decided_by": "package-reviewer",
        "decided_at": NOW,
    }
    values.update(updates)
    return build_document_set_review_decision(evidence, **values)


def test_exact_attestations_allow_only_scoped_pass() -> None:
    evidence = _evidence()
    decision = _decide(evidence)
    assert decision.status is CompletenessStatus.PASS
    assert decision.scope == evidence.manifest.scope
    assert len(decision.decision_sha256) == 64
    with pytest.raises(ValueError, match="every manifest member"):
        _decide(evidence, attestations=_attestations(evidence)[:1])
    stale = _attestations(evidence)[0].model_copy(
        update={
            "reference": _attestations(evidence)[0].reference.model_copy(
                update={"decision_sha256": "0" * 64}
            )
        }
    )
    with pytest.raises(ValueError, match="exact constituent"):
        _decide(evidence, attestations=(stale, _attestations(evidence)[1]))


def test_different_deadlines_create_non_overridable_unknown() -> None:
    evidence = _evidence(deadlines=(date(2026, 10, 1), date(2026, 10, 2)))
    assert len(evidence.server_findings) == 1
    with pytest.raises(ValueError, match="requested status"):
        _decide(evidence)
    decision = _decide(
        evidence,
        cross_document_assessment=DocumentSetCrossAssessment.OPEN_ISSUES,
        status=CompletenessStatus.UNKNOWN,
        reason="different deadlines need clarification",
    )
    assert decision.status is CompletenessStatus.UNKNOWN
    assert decision.findings[0].origin is DocumentSetFindingOrigin.SERVER


def test_confirmed_material_omission_requires_source_evidence_and_forces_fail() -> None:
    evidence = _evidence()
    finding = DocumentSetFinding(
        finding_id="missing-appendix",
        kind=DocumentSetFindingKind.CONFIRMED_MATERIAL_OMISSION,
        evidence=(DocumentSetSourceBlockRef(member_ordinal=1, extraction_block_index=0),),
        rationale="the cited mandatory appendix is absent",
        origin=DocumentSetFindingOrigin.REVIEWER,
    )
    decision = _decide(
        evidence,
        reviewer_findings=(finding,),
        cross_document_assessment=DocumentSetCrossAssessment.OPEN_ISSUES,
        status=CompletenessStatus.FAIL,
        reason="material evidence is missing",
    )
    assert decision.status is CompletenessStatus.FAIL
    with pytest.raises(ValueError, match="outside the snapshot"):
        _decide(
            evidence,
            reviewer_findings=(
                finding.model_copy(
                    update={
                        "evidence": (
                            DocumentSetSourceBlockRef(
                                member_ordinal=1,
                                extraction_block_index=99,
                            ),
                        )
                    }
                ),
            ),
            cross_document_assessment=DocumentSetCrossAssessment.OPEN_ISSUES,
            status=CompletenessStatus.FAIL,
        )


def test_self_review_missing_decision_and_order_substitution_are_rejected() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="independent"):
        _decide(evidence, decided_by="operator-a")
    incomplete = evidence.model_copy(
        update={
            "constituents": (
                evidence.constituents[0].model_copy(
                    update={
                        "review": CompletenessReviewRecord(
                            snapshot=evidence.constituents[0].review.snapshot
                        ),
                        "decision_sha256": None,
                    }
                ),
                evidence.constituents[1],
            )
        }
    )
    with pytest.raises(ValueError, match="terminal decision"):
        _decide(incomplete, attestations=_attestations(evidence))
    with pytest.raises(ValueError, match="exact constituent"):
        _decide(evidence, attestations=tuple(reversed(_attestations(evidence))))


def test_derived_digest_and_server_findings_cannot_be_removed_or_forged() -> None:
    evidence = _evidence(deadlines=(date(2026, 10, 1), date(2026, 10, 2)))
    forged_digest = evidence.model_copy(
        update={
            "constituents": (
                evidence.constituents[0].model_copy(update={"decision_sha256": "0" * 64}),
                evidence.constituents[1],
            )
        }
    )
    with pytest.raises(ValueError, match="projections"):
        _decide(forged_digest, attestations=_attestations(forged_digest))
    removed_server_finding = evidence.model_copy(update={"server_findings": ()})
    with pytest.raises(ValueError, match="projections"):
        _decide(removed_server_finding)


def test_tenant_and_strict_nested_values_cannot_be_bypassed() -> None:
    evidence = _evidence()
    manifest_payload = evidence.manifest.model_dump(mode="json", exclude={"evidence_sha256"})
    manifest_payload["company_id"] = "tenant-b"
    manifest_payload["evidence_sha256"] = canonical_json_sha256(manifest_payload)
    cross_tenant_manifest = evidence.manifest.model_validate_json(
        json.dumps(manifest_payload, ensure_ascii=False)
    )
    with pytest.raises(ValueError, match="tenant"):
        build_document_set_review_evidence(
            cross_tenant_manifest,
            tuple(item.review for item in evidence.constituents),
        )

    attestations = _attestations(evidence)
    forged = attestations[0].model_copy(update={"assessment": "UNRESOLVED"})
    with pytest.warns(UserWarning, match="serialized value"), pytest.raises(ValueError):
        _decide(evidence, attestations=(forged, attestations[1]))
