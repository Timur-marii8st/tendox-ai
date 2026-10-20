from datetime import UTC, datetime

from procurement.api import create_app
from procurement.documents import (
    ServerOfferEconomicsEvidence,
    ServerOfferEconomicsRecord,
    build_server_offer_economics_package,
    materialize_case_from_server_offer_economics,
)
from procurement.domain.cases import ProcurementCase
from procurement.domain.economics import ScenarioKind
from test_server_offer_api import _Authenticator, _call, _Service, payload
from test_server_offer_economics import exact_case


class _EconomicsService(_Service):
    def __init__(self) -> None:
        super().__init__()
        self.packages = {}

    async def get_server_offer_economics(
        self, *, company_id: str, case_id: str, case_version: int, offer_id: str
    ):
        review = await self.get_server_offer_review(company_id=company_id, offer_id=offer_id)
        if review is None:
            return None
        evidence = ServerOfferEconomicsEvidence(case=exact_case(), offer_review=review)
        return ServerOfferEconomicsRecord(
            evidence=evidence, package=self.packages.get((company_id, case_id, case_version))
        )

    async def store_server_offer_economics(self, **kwargs):
        record = await self.get_server_offer_economics(
            company_id=kwargs["company_id"],
            case_id=kwargs["case_id"],
            case_version=kwargs["case_version"],
            offer_id=kwargs["offer_id"],
        )
        assert record is not None
        package = build_server_offer_economics_package(
            record.evidence,
            economics_id=kwargs["economics_id"],
            scenarios=kwargs["scenarios"],
            prepared_by=kwargs["actor_id"],
            prepared_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        self.packages[(kwargs["company_id"], kwargs["case_id"], kwargs["case_version"])] = package
        return package

    async def materialize_case_from_server_offer_economics(self, **kwargs) -> ProcurementCase:
        record = await self.get_server_offer_economics(
            company_id=kwargs["company_id"],
            case_id=kwargs["case_id"],
            case_version=kwargs["case_version"],
            offer_id=kwargs["offer_id"],
        )
        assert record is not None and record.package is not None
        assert record.package.economics_id == kwargs["economics_id"]
        assert record.package.package_sha256 == kwargs["package_sha256"]
        return materialize_case_from_server_offer_economics(record)


def _costs() -> dict[str, str]:
    return {
        name: "0"
        for name in (
            "packaging", "logistics", "loading_unloading", "storage", "installation",
            "payroll_travel", "subcontracting", "insurance", "finance",
            "bank_guarantee", "platform_fees", "taxes", "certification", "warranty",
            "risk_reserve", "penalty_reserve", "other",
        )
    }


def _scenarios() -> list[dict[str, object]]:
    return [
        {
            "kind": kind.value,
            "contract_revenue": "1000",
            "costs": _costs(),
            "assumptions": [f"explicit {kind.value} assumptions"],
        }
        for kind in ScenarioKind
    ]


def _reviewed_offer(app: object) -> dict[str, object]:
    created = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/1/server-offer-proposals",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "offer-economics"},
        json=payload(),
    ).json()
    decided = _call(
        app,
        "POST",
        f"/v1/server-offer-proposals/{created['offer_id']}/review-decision",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "review-economics"},
        json={
            "proposal_sha256": created["proposal_sha256"],
            "requirement_decisions": [{
                "requirement_ordinal": 1, "status": "PASS", "reason": "exact BOM",
                "evidence": [{"kind": "BOM_LINE", "bom_line_ordinal": 1}],
            }],
            "bom_scope_assessment": "CONFIRMED_COMPLETE",
            "commercial_terms_assessment": "CONFIRMED",
            "reason": "offer passes",
        },
    ).json()
    return created | {"review_decision_sha256": decided["decision_sha256"]}


def test_operator_builds_complete_package_without_caller_recommendation() -> None:
    app = create_app(_EconomicsService(), _Authenticator())
    offer = _reviewed_offer(app)
    path = "/v1/cases/case-1/versions/1/server-offer-economics"
    evidence = _call(
        app,
        "GET",
        f"{path}?offer_id={offer['offer_id']}",
        headers={"Authorization": "Bearer operator"},
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["package"] is None

    created = _call(
        app,
        "POST",
        path,
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "economics-1"},
        json={
            "offer_id": offer["offer_id"],
            "offer_proposal_sha256": offer["proposal_sha256"],
            "offer_review_decision_sha256": offer["review_decision_sha256"],
            "scenarios": _scenarios(),
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["scenario_status"] == "COMPLETE"
    assert created.json()["recommendation_status"] == "UNKNOWN"
    first_goods = created.json()["scenario_set"]["scenarios"][0]["economics"]["costs"][
        "goods"
    ]
    assert first_goods == "1000.00"


def test_economics_is_operator_only_and_body_cannot_set_recommendation() -> None:
    app = create_app(_EconomicsService(), _Authenticator())
    denied = _call(
        app,
        "GET",
        "/v1/cases/case-1/versions/1/server-offer-economics?offer_id=x",
        headers={"Authorization": "Bearer reviewer"},
    )
    assert denied.status_code == 403
    invalid = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/1/server-offer-economics",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "invalid"},
        json={
            "offer_id": "offer-1",
            "offer_proposal_sha256": "a" * 64,
            "offer_review_decision_sha256": "b" * 64,
            "scenarios": _scenarios(),
            "recommendation_status": "PASS",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_server_offer_economics"


def test_operator_materializes_next_case_version_from_exact_package() -> None:
    app = create_app(_EconomicsService(), _Authenticator())
    offer = _reviewed_offer(app)
    path = "/v1/cases/case-1/versions/1/server-offer-economics"
    package = _call(
        app,
        "POST",
        path,
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "economics-next"},
        json={
            "offer_id": offer["offer_id"],
            "offer_proposal_sha256": offer["proposal_sha256"],
            "offer_review_decision_sha256": offer["review_decision_sha256"],
            "scenarios": _scenarios(),
        },
    ).json()
    response = _call(
        app,
        "POST",
        f"{path}/materialize",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "case-next"},
        json={
            "offer_id": offer["offer_id"],
            "economics_id": package["economics_id"],
            "package_sha256": package["package_sha256"],
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["version"] == 2
    assert result["selected_quote"]["quote_id"] == offer["offer_id"]
    assert [item["kind"] for item in result["scenarios"]["scenarios"]] == [
        "base", "realistic", "conservative"
    ]
    assert result["assessment"]["checks"] == [
        {
            "kind": "technical",
            "status": "PASS",
            "reason": f"exact server-offer review {offer['review_decision_sha256']}",
            "evidence": result["assessment"]["checks"][0]["evidence"],
        }
    ]


def test_case_materialization_rejects_caller_owned_assessment() -> None:
    app = create_app(_EconomicsService(), _Authenticator())
    response = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/1/server-offer-economics/materialize",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "case-invalid"},
        json={
            "offer_id": "offer-1",
            "economics_id": "economics-1",
            "package_sha256": "a" * 64,
            "assessment": {"checks": []},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_case_materialization"
