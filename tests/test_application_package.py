from datetime import timedelta

import pytest

from case_support import AT, paper_case
from procurement.documents.application_package import (
    ApplicationAttachment,
    ApplicationDocumentRequirement,
    ApplicationPackageEvidence,
    ApplicationRequirementKind,
    build_application_package,
)
from procurement.documents.participation_decision import (
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    build_participation_decision,
    build_participation_evaluation_evidence,
)
from procurement.domain.cases import case_input_digest, evaluate_case


def _evidence() -> ApplicationPackageEvidence:
    case = paper_case()
    evaluation = build_participation_evaluation_evidence(
        company_id=case.company_id,
        evaluation_id="evaluation-1",
        case_id=case.case_id,
        case_version=case.version,
        effective_at=AT,
        case_input_sha256=case_input_digest(case),
        engine_version="test-engine",
        recommendation=evaluate_case(case, at=AT),
        evaluated_by="operator-a",
        evaluated_at=AT,
    )
    decided_at = AT + timedelta(minutes=1)
    decision = build_participation_decision(
        evaluation,
        decision_id="decision-1",
        status=ParticipationDecisionStatus.APPROVED,
        current_recommendation=evaluate_case(case, at=decided_at),
        reason="Независимое решение",
        decided_by="approver-a",
        decided_at=decided_at,
    )
    return ApplicationPackageEvidence(
        case=case,
        participation=ParticipationDecisionRecord(
            evidence=evaluation,
            decision=decision,
        ),
    )


def _requirement() -> ApplicationDocumentRequirement:
    return ApplicationDocumentRequirement(
        ordinal=1,
        kind=ApplicationRequirementKind.DECLARATION,
        title="Декларация соответствия единым требованиям",
        source_document_id="tender-document",
        source_document_sha256="a" * 64,
        source_locator="раздел 5, пункт 2",
    )


def _attachment() -> ApplicationAttachment:
    return ApplicationAttachment(
        ordinal=1,
        requirement_ordinals=(1,),
        document_id="application-declaration",
        document_sha256="b" * 64,
        submission_filename="declaration.pdf",
        original_filename="signed-declaration.pdf",
        media_type="application/pdf",
    )


def test_application_package_is_pending_review_and_authorizes_no_action() -> None:
    evidence = _evidence()
    prepared_at = AT + timedelta(minutes=2)
    current = evaluate_case(evidence.case, at=prepared_at)
    assert current.minimum_bid_price is not None
    package = build_application_package(
        evidence,
        package_id="package-1",
        proposed_price_ex_vat=current.minimum_bid_price,
        requirements=(_requirement(),),
        attachments=(_attachment(),),
        current_recommendation=current,
        prepared_by="operator-b",
        prepared_at=prepared_at,
    )
    assert package.review_status == "PENDING_REVIEW"
    assert package.coverage_status.value == "UNKNOWN"
    assert package.external_action_authorized is False
    assert package.prepared_at.utcoffset() == timedelta(0)


def test_application_package_rejects_incomplete_declared_coverage() -> None:
    evidence = _evidence()
    prepared_at = AT + timedelta(minutes=2)
    with pytest.raises(ValueError, match="every declared requirement"):
        build_application_package(
            evidence,
            package_id="package-2",
            proposed_price_ex_vat=evidence.case.nmck_ex_vat,
            requirements=(_requirement(),),
            attachments=(
                _attachment().model_copy(update={"requirement_ordinals": (2,)}),
            ),
            current_recommendation=evaluate_case(evidence.case, at=prepared_at),
            prepared_by="operator-b",
            prepared_at=prepared_at,
        )


def test_application_package_enforces_price_floor() -> None:
    evidence = _evidence()
    prepared_at = AT + timedelta(minutes=2)
    current = evaluate_case(evidence.case, at=prepared_at)
    assert current.minimum_bid_price is not None
    with pytest.raises(ValueError, match="below price floor"):
        build_application_package(
            evidence,
            package_id="package-3",
            proposed_price_ex_vat=current.minimum_bid_price - 1,
            requirements=(_requirement(),),
            attachments=(_attachment(),),
            current_recommendation=current,
            prepared_by="operator-b",
            prepared_at=prepared_at,
        )
