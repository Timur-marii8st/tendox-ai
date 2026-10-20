from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from case_support import paper_case
from procurement.documents import (
    ServerOfferEconomicsEvidence,
    ServerOfferEconomicsRecord,
    ServerOfferOperatingCostsInput,
    ServerOfferReviewRecord,
    ServerOfferScenarioInput,
    build_server_offer_economics_package,
)
from procurement.domain.cases import ProcurementCase
from procurement.domain.compliance import Verdict
from procurement.domain.economics import ScenarioKind
from test_server_offer_review import decide, evidence

PREPARED_AT = datetime(2026, 9, 22, tzinfo=UTC)


def exact_case() -> ProcurementCase:
    payload = paper_case().model_dump(mode="python")
    payload["company_id"] = "tenant-a"
    payload["case_id"] = "case-1"
    payload["version"] = 1
    payload["profile"]["company_id"] = "tenant-a"
    if payload["selected_quote"] is not None:
        payload["selected_quote"]["company_id"] = "tenant-a"
    return ProcurementCase.model_validate(payload)


def costs(value: str = "0") -> ServerOfferOperatingCostsInput:
    return ServerOfferOperatingCostsInput(
        packaging=value,
        logistics=value,
        loading_unloading=value,
        storage=value,
        installation=value,
        payroll_travel=value,
        subcontracting=value,
        insurance=value,
        finance=value,
        bank_guarantee=value,
        platform_fees=value,
        taxes=value,
        certification=value,
        warranty=value,
        risk_reserve=value,
        penalty_reserve=value,
        other=value,
    )


def scenarios() -> tuple[ServerOfferScenarioInput, ...]:
    return tuple(
        ServerOfferScenarioInput(
            kind=kind,
            contract_revenue="1000",
            costs=costs("10" if kind is ScenarioKind.CONSERVATIVE else "0"),
            assumptions=(f"explicit {kind.value} assumptions",),
        )
        for kind in ScenarioKind
    )


def review_record() -> ServerOfferReviewRecord:
    source = evidence()
    return ServerOfferReviewRecord(evidence=source, decision=decide(source))


def economics_evidence() -> ServerOfferEconomicsEvidence:
    return ServerOfferEconomicsEvidence(case=exact_case(), offer_review=review_record())


def test_builds_complete_three_scenario_package_from_pass_offer() -> None:
    result = build_server_offer_economics_package(
        economics_evidence(),
        economics_id="economics-1",
        scenarios=scenarios(),
        prepared_by="economics-operator",
        prepared_at=PREPARED_AT,
    )
    assert result.scenario_status == "COMPLETE"
    assert result.recommendation_status is Verdict.UNKNOWN
    assert result.scenario_set.is_complete
    assert all(
        scenario.economics.costs.goods == Decimal("100")
        for scenario in result.scenario_set.scenarios
    )
    assert all(
        scenario.economics.nds_rate == Decimal("0.20")
        for scenario in result.scenario_set.scenarios
    )
    assert ServerOfferEconomicsRecord(
        evidence=economics_evidence(), package=result
    ).package == result


def test_all_non_goods_costs_must_be_explicit_and_float_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ServerOfferOperatingCostsInput.model_validate({"logistics": "0"})
    payload = costs().model_dump(mode="python")
    payload["logistics"] = 1.5
    with pytest.raises(ValidationError, match="Decimal"):
        ServerOfferOperatingCostsInput.model_validate(payload)


def test_rejects_wrong_order_excess_revenue_and_reviewer_as_preparer() -> None:
    source = economics_evidence()
    reversed_scenarios = tuple(reversed(scenarios()))
    with pytest.raises(ValueError, match="ordered"):
        build_server_offer_economics_package(
            source,
            economics_id="economics-1",
            scenarios=reversed_scenarios,
            prepared_by="economics-operator",
            prepared_at=PREPARED_AT,
        )
    too_high = list(scenarios())
    too_high[0] = too_high[0].model_copy(update={"contract_revenue": Decimal("999999999")})
    with pytest.raises(ValueError, match="cannot exceed"):
        build_server_offer_economics_package(
            source,
            economics_id="economics-1",
            scenarios=tuple(too_high),
            prepared_by="economics-operator",
            prepared_at=PREPARED_AT,
        )
    with pytest.raises(ValueError, match="must differ"):
        build_server_offer_economics_package(
            source,
            economics_id="economics-1",
            scenarios=scenarios(),
            prepared_by="offer-reviewer",
            prepared_at=PREPARED_AT,
        )


def test_expired_quote_cannot_seed_economics() -> None:
    with pytest.raises(ValueError, match="valid"):
        build_server_offer_economics_package(
            economics_evidence(),
            economics_id="economics-1",
            scenarios=scenarios(),
            prepared_by="economics-operator",
            prepared_at=datetime(2026, 10, 20, tzinfo=UTC),
        )
