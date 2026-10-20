from procurement.documents import (
    ServerOfferEconomicsRecord,
    build_server_offer_economics_package,
    materialize_case_from_server_offer_economics,
)
from procurement.domain.cases import GateKind, evaluate_case
from procurement.domain.decisions import GateStatus, RecommendationDecision
from test_server_offer_economics import PREPARED_AT, economics_evidence, scenarios


def record() -> ServerOfferEconomicsRecord:
    evidence = economics_evidence()
    package = build_server_offer_economics_package(
        evidence,
        economics_id="economics-1",
        scenarios=scenarios(),
        prepared_by="economics-operator",
        prepared_at=PREPARED_AT,
    )
    return ServerOfferEconomicsRecord(evidence=evidence, package=package)


def test_materializes_next_case_with_exact_quote_scenarios_and_only_technical_gate() -> None:
    source = record()
    result = materialize_case_from_server_offer_economics(source)
    assert result.version == source.evidence.case.version + 1
    assert result.selected_quote is not None
    assert result.selected_quote.quote_id == source.package.offer_id  # type: ignore[union-attr]
    assert result.scenarios == source.package.scenario_set  # type: ignore[union-attr]
    assert result.assessment is not None
    assert len(result.assessment.checks) == 1
    assert result.assessment.checks[0].kind is GateKind.TECHNICAL
    assert result.assessment.checks[0].status is GateStatus.PASS
    assert evaluate_case(result, at=PREPARED_AT).decision is RecommendationDecision.NEEDS_ANALYSIS


def test_refuses_materialization_without_package() -> None:
    source = record()
    without = source.model_copy(update={"package": None})
    try:
        materialize_case_from_server_offer_economics(without)
    except ValueError as error:
        assert "requires" in str(error)
    else:
        raise AssertionError("missing package must fail")
