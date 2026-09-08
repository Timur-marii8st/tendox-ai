"""Неполный или изменённый кейс не получает ложного допуска."""

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from case_support import AT, paper_case, reviewed
from procurement.domain.cases import GateCheck, GateKind, ProcurementCase, evaluate_case
from procurement.domain.decisions import GateStatus, RecommendationDecision


@pytest.mark.parametrize("kind", list(GateKind))
def test_missing_named_gate_requires_analysis(kind: GateKind) -> None:
    case = paper_case()
    assert case.assessment is not None
    checks = tuple(check for check in case.assessment.checks if check.kind is not kind)
    case = case.model_copy(
        update={
            "assessment": case.assessment.model_copy(update={"checks": checks}),
        }
    )
    result = evaluate_case(case, at=AT)
    assert result.decision is RecommendationDecision.NEEDS_ANALYSIS
    assert any(kind.value in reason for reason in result.reasons)


def test_unknown_gate_can_explain_missing_evidence() -> None:
    case = paper_case()
    assert case.assessment is not None
    checks = tuple(
        GateCheck(kind=c.kind, status=GateStatus.UNKNOWN, reason="source missing")
        if c.kind is GateKind.LEGAL
        else c
        for c in case.assessment.checks
    )
    case = case.model_copy(
        update={
            "assessment": case.assessment.model_copy(update={"checks": checks}),
        }
    )
    result = evaluate_case(case, at=AT)
    assert result.decision is RecommendationDecision.NEEDS_ANALYSIS
    assert "legal: source missing" in result.reasons


def test_known_gate_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        GateCheck(kind=GateKind.LEGAL, status=GateStatus.PASS, reason="unsupported")


def test_duplicate_gates_are_invalid() -> None:
    case = paper_case()
    assert case.assessment is not None
    changed = case.model_copy(
        update={
            "assessment": case.assessment.model_copy(
                update={"checks": (case.assessment.checks[0],) * 6},
            )
        }
    )
    with pytest.raises(ValidationError):
        evaluate_case(changed, at=AT)


@pytest.mark.parametrize("target", ["profile", "quote_company", "quote_tender"])
def test_cross_scope_input_is_invalid(target: str) -> None:
    payload = paper_case().model_dump(mode="python")
    if target == "profile":
        payload["profile"]["company_id"] = "another-company"
    elif target == "quote_company":
        payload["selected_quote"]["company_id"] = "another-company"
    else:
        payload["selected_quote"]["tender_id"] = "another-tender"
    with pytest.raises(ValidationError):
        ProcurementCase.model_validate(payload)


@pytest.mark.parametrize("target", ["profile", "quote", "tender", "scenario", "rating", "version"])
def test_modified_input_invalidates_existing_assessment(target: str) -> None:
    payload = paper_case().model_dump(mode="python")
    if target == "profile":
        payload["profile"]["version"] += 1
    elif target == "quote":
        payload["selected_quote"]["version"] += 1
    elif target == "tender":
        payload["tender"]["subject"] = "changed subject"
    elif target == "scenario":
        payload["scenarios"]["scenarios"][0]["economics"]["costs"]["other"] = Decimal(1)
    elif target == "rating":
        payload["rating"]["score"] = 99
        payload["rating"]["factors"][0]["points"] = 99
    else:
        payload["version"] += 1
    result = evaluate_case(ProcurementCase.model_validate(payload), at=AT)
    assert result.decision is RecommendationDecision.NEEDS_ANALYSIS


@pytest.mark.parametrize("future", [False, True])
def test_assessment_cannot_precede_quote_or_come_from_future(future: bool) -> None:
    case = paper_case()
    assert case.assessment is not None and case.selected_quote is not None
    assessed_at = (
        AT + timedelta(seconds=1)
        if future
        else case.selected_quote.issued_at - timedelta(seconds=1)
    )
    changed = case.model_copy(
        update={
            "assessment": case.assessment.model_copy(
                update={"assessed_at": assessed_at},
            )
        }
    )
    assert evaluate_case(changed, at=AT).decision is RecommendationDecision.NEEDS_ANALYSIS


def test_expired_quote_requires_analysis() -> None:
    case = paper_case()
    assert case.selected_quote is not None
    assert (
        evaluate_case(case, at=case.selected_quote.valid_until).decision
        is RecommendationDecision.NEEDS_ANALYSIS
    )


@pytest.mark.parametrize("missing", ["logistics", "taxes", "nds_rate"])
def test_reassessment_does_not_complete_missing_costs_or_tax(missing: str) -> None:
    payload = paper_case().model_dump(mode="python")
    economics = payload["scenarios"]["scenarios"][0]["economics"]
    if missing == "nds_rate":
        economics["nds_rate"] = None
    else:
        del economics["costs"][missing]
    case = reviewed(ProcurementCase.model_validate(payload))
    restored = ProcurementCase.model_validate_json(case.model_dump_json())
    assert evaluate_case(restored, at=AT).decision is RecommendationDecision.NEEDS_ANALYSIS


def test_complete_case_survives_serialization() -> None:
    case = paper_case()
    restored = ProcurementCase.model_validate_json(case.model_dump_json())
    assert evaluate_case(restored, at=AT) == evaluate_case(case, at=AT)
    assert evaluate_case(restored, at=AT).decision is RecommendationDecision.PARTICIPATE


def test_shelf_sales_are_not_silently_recommended() -> None:
    payload = paper_case().model_dump(mode="python")
    payload["channel"] = "shelf_sales"
    result = evaluate_case(reviewed(ProcurementCase.model_validate(payload)), at=AT)
    assert result.decision is RecommendationDecision.NEEDS_ANALYSIS


def test_supplier_vat_can_differ_from_revenue_vat() -> None:
    payload = paper_case().model_dump(mode="python")
    payload["selected_quote"]["nds_rate"] = Decimal("0.05")
    result = evaluate_case(reviewed(ProcurementCase.model_validate(payload)), at=AT)
    assert result.decision is RecommendationDecision.PARTICIPATE


def test_unrounded_margin_controls_financial_gate() -> None:
    payload = paper_case().model_dump(mode="python")
    payload["profile"]["finance"]["min_expected_profit"] = Decimal(0)
    payload["selected_quote"]["amount_ex_vat"] = Decimal("500000")
    for scenario in payload["scenarios"]["scenarios"]:
        economics = scenario["economics"]
        economics["contract_revenue"] = Decimal("1000000")
        for field in economics["costs"]["specified_cost_fields"]:
            economics["costs"][field] = Decimal(0)
        economics["costs"]["goods"] = Decimal("500000")
        economics["costs"]["other"] = Decimal("350010")
    result = evaluate_case(reviewed(ProcurementCase.model_validate(payload)), at=AT)
    assert result.realistic_margin == Decimal("0.1500")
    assert result.decision is RecommendationDecision.DO_NOT_PARTICIPATE


def test_price_floor_respects_minimum_contract_amount() -> None:
    payload = paper_case().model_dump(mode="python")
    payload["profile"]["finance"]["min_contract_amount"] = Decimal("1400000")
    result = evaluate_case(reviewed(ProcurementCase.model_validate(payload)), at=AT)
    assert result.minimum_bid_price == Decimal("1400000.00")


def test_copied_invalid_nested_money_is_revalidated() -> None:
    case = paper_case()
    assert case.selected_quote is not None
    changed = case.model_copy(
        update={
            "selected_quote": case.selected_quote.model_copy(
                update={"amount_ex_vat": 1.5},
            )
        }
    )
    with pytest.warns(UserWarning, match="serializer warnings"), pytest.raises(ValidationError):
        evaluate_case(changed, at=AT)
