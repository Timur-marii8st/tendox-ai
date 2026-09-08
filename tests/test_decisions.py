"""Recommendations require a validated case, not scalar caller assertions."""

from decimal import Decimal

import pytest

from case_support import AT, paper_case, reviewed
from procurement.domain.cases import ProcurementCase
from procurement.domain.decisions import GateStatus, RecommendationDecision, recommend


def failed_case() -> ProcurementCase:
    case = paper_case()
    assert case.assessment is not None
    checks = list(case.assessment.checks)
    checks[0] = checks[0].model_copy(
        update={"status": GateStatus.FAIL, "reason": "blocking evidence"}
    )
    return case.model_copy(
        update={"assessment": case.assessment.model_copy(update={"checks": tuple(checks)})}
    )


def test_green_score_does_not_override_failed_gate() -> None:
    result = recommend(failed_case(), generated_at=AT)
    assert result.decision is RecommendationDecision.DO_NOT_PARTICIPATE
    assert "legal: blocking evidence" in result.reasons


def test_no_quote_means_analysis_not_participation() -> None:
    case = reviewed(paper_case().model_copy(update={"selected_quote": None}))
    assert recommend(case, generated_at=AT).decision is RecommendationDecision.NEEDS_ANALYSIS


def test_profitable_confirmed_case_is_recommended_with_price_floor() -> None:
    result = recommend(paper_case(), generated_at=AT)
    assert result.decision is RecommendationDecision.PARTICIPATE
    assert result.minimum_bid_price == Decimal("1235000.00")


def test_empty_gates_do_not_mean_pass() -> None:
    case = paper_case()
    assert case.assessment is not None
    case = case.model_copy(update={"assessment": case.assessment.model_copy(update={"checks": ()})})
    assert recommend(case, generated_at=AT).decision is RecommendationDecision.NEEDS_ANALYSIS


def test_card_color_follows_decision_even_with_high_rating() -> None:
    assert recommend(failed_case(), generated_at=AT).color == "red"


def test_legacy_scalar_assertions_cannot_authorize_participation() -> None:
    with pytest.raises(TypeError):
        recommend(gate_statuses=(GateStatus.PASS,), confirmed_quote_count=1, generated_at=AT)
