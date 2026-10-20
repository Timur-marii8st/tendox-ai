from datetime import timedelta

import pytest

from case_support import AT, paper_case
from procurement.documents.application_package import (
    ApplicationAttachment,
    ApplicationDocumentRequirement,
    ApplicationPackageEvidence,
    ApplicationPackageRecord,
    ApplicationRequirementKind,
    build_application_package,
)
from procurement.documents.application_review import (
    ApplicationAttachmentReview,
    ApplicationInventoryAssessment,
    ApplicationPriceAssessment,
    ApplicationRequirementReview,
    build_application_review_decision,
)
from procurement.documents.participation_decision import (
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    build_participation_decision,
    build_participation_evaluation_evidence,
)
from procurement.domain.cases import case_input_digest, evaluate_case
from procurement.domain.compliance import Verdict


def _record() -> ApplicationPackageRecord:
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
        reason="Проверено",
        decided_by="approver-a",
        decided_at=decided_at,
    )
    evidence = ApplicationPackageEvidence(
        case=case,
        participation=ParticipationDecisionRecord(evidence=evaluation, decision=decision),
    )
    prepared_at = AT + timedelta(minutes=2)
    package = build_application_package(
        evidence,
        package_id="package-1",
        proposed_price_ex_vat=case.nmck_ex_vat,
        requirements=(
            ApplicationDocumentRequirement(
                ordinal=1,
                kind=ApplicationRequirementKind.FORM,
                title="Форма заявки",
                source_document_id="tender-document",
                source_document_sha256="a" * 64,
                source_locator="раздел 4",
            ),
        ),
        attachments=(
            ApplicationAttachment(
                ordinal=1,
                requirement_ordinals=(1,),
                document_id="application-document",
                document_sha256="b" * 64,
                submission_filename="application.pdf",
                original_filename="application.pdf",
                media_type="application/pdf",
            ),
        ),
        current_recommendation=evaluate_case(case, at=prepared_at),
        prepared_by="operator-b",
        prepared_at=prepared_at,
    )
    return ApplicationPackageRecord(evidence=evidence, package=package)


def _positive_rows() -> tuple[
    tuple[ApplicationRequirementReview, ...], tuple[ApplicationAttachmentReview, ...]
]:
    return (
        (
            ApplicationRequirementReview(
                requirement_ordinal=1,
                status=Verdict.PASS,
                reason="Содержание и источник сверены",
                attachment_ordinals=(1,),
            ),
        ),
        (
            ApplicationAttachmentReview(
                attachment_ordinal=1,
                status=Verdict.PASS,
                reason="Файл и содержимое сверены",
            ),
        ),
    )


def _decide(
    record: ApplicationPackageRecord,
    *,
    requirements: tuple[ApplicationRequirementReview, ...] | None = None,
    attachments: tuple[ApplicationAttachmentReview, ...] | None = None,
    inventory: ApplicationInventoryAssessment = ApplicationInventoryAssessment.CONFIRMED_COMPLETE,
    price: ApplicationPriceAssessment = ApplicationPriceAssessment.CONFIRMED,
    reviewed_by: str = "reviewer-a",
    reviewed_at=AT + timedelta(minutes=3),
):
    positive_requirements, positive_attachments = _positive_rows()
    return build_application_review_decision(
        record,
        requirement_reviews=requirements or positive_requirements,
        attachment_reviews=attachments or positive_attachments,
        inventory_assessment=inventory,
        inventory_source_document_ids=("tender-document",),
        inventory_reason="Все разделы документации сопоставлены",
        price_assessment=price,
        price_reason="Цена и база НДС сверены",
        reason="Независимая проверка",
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )


def test_application_review_pass_is_exact_and_not_external_approval() -> None:
    record = _record()
    decision = _decide(record)
    assert decision.status is Verdict.PASS
    assert decision.deadline_gate is Verdict.PASS
    assert decision.price_gate is Verdict.PASS
    assert decision.package_sha256 == record.package.package_sha256  # type: ignore[union-attr]
    assert decision.external_action_authorized is False


def test_application_review_fail_dominates_and_unresolved_cannot_pass() -> None:
    record = _record()
    requirements, attachments = _positive_rows()
    failed = _decide(
        record,
        attachments=(attachments[0].model_copy(update={"status": Verdict.FAIL}),),
    )
    assert failed.status is Verdict.FAIL
    unresolved = _decide(
        record,
        inventory=ApplicationInventoryAssessment.UNRESOLVED,
    )
    assert unresolved.status is Verdict.UNKNOWN
    assert requirements[0].status is Verdict.PASS


def test_application_review_rejects_self_review_and_unrelated_refs() -> None:
    record = _record()
    with pytest.raises(ValueError, match="reviewer must differ"):
        _decide(record, reviewed_by="operator-b")
    with pytest.raises(ValueError, match="unrelated attachment"):
        _decide(
            record,
            requirements=(
                ApplicationRequirementReview(
                    requirement_ordinal=1,
                    status=Verdict.FAIL,
                    reason="Не тот файл",
                    attachment_ordinals=(2,),
                ),
            ),
        )


def test_application_review_stale_deadline_blocks_pass() -> None:
    record = _record()
    close = record.evidence.case.tender.submission.closes_at  # type: ignore[union-attr]
    decision = _decide(record, reviewed_at=close + timedelta(seconds=1))
    assert decision.deadline_gate is Verdict.FAIL
    assert decision.status is Verdict.FAIL
