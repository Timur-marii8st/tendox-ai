from datetime import datetime, timedelta

import pytest

from case_support import AT, paper_case
from procurement.documents.participation_decision import (
    ParticipationDecisionStatus,
    build_participation_decision,
    build_participation_evaluation_evidence,
)
from procurement.domain.cases import case_input_digest, evaluate_case
from procurement.domain.decisions import RecommendationDecision


def _evidence(at: datetime):
    case = paper_case()
    recommendation = evaluate_case(case, at=at)
    assert recommendation.decision is RecommendationDecision.PARTICIPATE
    return case, build_participation_evaluation_evidence(
        company_id=case.company_id,
        evaluation_id="evaluation-1",
        case_id=case.case_id,
        case_version=case.version,
        effective_at=at,
        case_input_sha256=case_input_digest(case),
        engine_version="test-engine",
        recommendation=recommendation,
        evaluated_by="operator-a",
        evaluated_at=at,
    )


def test_approved_decision_binds_exact_current_participate_evaluation() -> None:
    at = AT
    case, evidence = _evidence(at)
    decided_at = at + timedelta(minutes=1)
    decision = build_participation_decision(
        evidence,
        decision_id="decision-1",
        status=ParticipationDecisionStatus.APPROVED,
        current_recommendation=evaluate_case(case, at=decided_at),
        reason="Основания и экономика проверены человеком",
        decided_by="approver-a",
        decided_at=decided_at,
    )
    assert decision.status is ParticipationDecisionStatus.APPROVED
    assert decision.external_action_authorized is False
    assert evidence.effective_at.utcoffset() == timedelta(0)
    assert decision.decided_at.utcoffset() == timedelta(0)


def test_approval_rejects_self_review_and_stale_positive_evaluation() -> None:
    at = AT
    case, evidence = _evidence(at)
    with pytest.raises(ValueError, match="must differ"):
        build_participation_decision(
            evidence,
            decision_id="decision-1",
            status=ParticipationDecisionStatus.APPROVED,
            current_recommendation=evaluate_case(case, at=at),
            reason="self review",
            decided_by="operator-a",
            decided_at=at,
        )
    expired_at = case.tender.submission.closes_at + timedelta(seconds=1)
    with pytest.raises(ValueError, match="current PARTICIPATE"):
        build_participation_decision(
            evidence,
            decision_id="decision-2",
            status=ParticipationDecisionStatus.APPROVED,
            current_recommendation=evaluate_case(case, at=expired_at),
            reason="stale approval",
            decided_by="approver-a",
            decided_at=expired_at,
        )


def test_rejection_can_record_human_no_without_authorizing_action() -> None:
    at = AT
    case, evidence = _evidence(at)
    expired_at = case.tender.submission.closes_at + timedelta(seconds=1)
    decision = build_participation_decision(
        evidence,
        decision_id="decision-3",
        status=ParticipationDecisionStatus.REJECTED,
        current_recommendation=evaluate_case(case, at=expired_at),
        reason="К моменту решения срок закрыт",
        decided_by="approver-a",
        decided_at=expired_at,
    )
    assert decision.status is ParticipationDecisionStatus.REJECTED
    assert decision.external_action_authorized is False
