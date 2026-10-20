from datetime import UTC, datetime

from procurement.api import create_app
from procurement.documents import materialize_case_hard_gate_assessment
from procurement.domain.cases import GateCheck, GateKind, ProcurementCase, case_input_digest
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Extractor, Provenance
from test_server_offer_api import _Authenticator, _call
from test_server_offer_economics_api import (
    _EconomicsService,
    _reviewed_offer,
    _scenarios,
)


class _HardGateService(_EconomicsService):
    def __init__(self) -> None:
        super().__init__()
        self.case_versions: dict[tuple[str, str, int], ProcurementCase] = {}

    async def materialize_case_from_server_offer_economics(self, **kwargs) -> ProcurementCase:
        case = await super().materialize_case_from_server_offer_economics(**kwargs)
        self.case_versions[(kwargs["company_id"], kwargs["case_id"], case.version)] = case
        return case

    async def materialize_case_hard_gate_assessment(self, **kwargs) -> ProcurementCase:
        source = self.case_versions[
            (kwargs["company_id"], kwargs["case_id"], kwargs["case_version"])
        ]
        assert case_input_digest(source) == kwargs["source_case_input_sha256"]
        checks = (
            *(
                GateCheck(
                    kind=item.kind,
                    status=item.status,
                    reason=item.reason,
                    evidence=tuple(reference.provenance() for reference in item.evidence),
                )
                for item in kwargs["decisions"]
            ),
            GateCheck(
                kind=GateKind.DOCUMENT,
                status=GateStatus.PASS,
                reason="terminal document-set review",
                evidence=(
                    Provenance(
                        document_id="manifest-1",
                        locator="terminal decision",
                        extractor=Extractor.MANUAL,
                    ),
                ),
            ),
        )
        result = materialize_case_hard_gate_assessment(
            source,
            checks,
            reviewer_id=kwargs["actor_id"],
            assessed_at=datetime(2026, 9, 23, tzinfo=UTC),
        )
        self.case_versions[(kwargs["company_id"], kwargs["case_id"], result.version)] = result
        return result

    async def get_case(
        self, *, company_id: str, case_id: str, version: int
    ) -> ProcurementCase | None:
        return self.case_versions.get((company_id, case_id, version))


def _source_case(app: object) -> tuple[dict[str, object], ProcurementCase]:
    offer = _reviewed_offer(app)
    economics_path = "/v1/cases/case-1/versions/1/server-offer-economics"
    package = _call(
        app,
        "POST",
        economics_path,
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "s90-economics"},
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
        f"{economics_path}/materialize",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "s90-source"},
        json={
            "offer_id": offer["offer_id"],
            "economics_id": package["economics_id"],
            "package_sha256": package["package_sha256"],
        },
    )
    assert response.status_code == 201, response.text
    return offer, ProcurementCase.model_validate(response.json())


def _decisions() -> list[dict[str, object]]:
    return [
        {
            "kind": kind.value,
            "status": "PASS",
            "reason": f"reviewed {kind.value}",
            "evidence": [{
                "document_id": f"evidence-{kind.value}",
                "document_sha256": "a" * 64,
                "locator": "paragraph 1",
            }],
        }
        for kind in GateKind
        if kind not in {GateKind.TECHNICAL, GateKind.DOCUMENT}
    ]


def test_operator_materializes_all_remaining_gates_without_replacing_technical() -> None:
    app = create_app(_HardGateService(), _Authenticator())
    _, source = _source_case(app)
    evidence = _call(
        app,
        "GET",
        f"/v1/cases/{source.case_id}/versions/{source.version}/hard-gate-assessments/evidence",
        headers={"Authorization": "Bearer operator"},
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["source_case_input_sha256"] == case_input_digest(source)
    response = _call(
        app,
        "POST",
        f"/v1/cases/{source.case_id}/versions/{source.version}/hard-gate-assessments/materialize",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "s90-gates"},
        json={
            "source_case_input_sha256": case_input_digest(source),
            "document_binding_id": "binding-1",
            "manifest_evidence_sha256": "b" * 64,
            "document_decision_sha256": "c" * 64,
            "decisions": _decisions(),
        },
    )
    assert response.status_code == 201, response.text
    result = ProcurementCase.model_validate(response.json())
    assert result.version == source.version + 1
    assert result.assessment is not None and source.assessment is not None
    assert tuple(item.kind for item in result.assessment.checks) == tuple(GateKind)
    assert result.assessment.checks[2] == source.assessment.checks[0]


def test_hard_gate_materialization_is_operator_only_and_requires_exact_five() -> None:
    app = create_app(_HardGateService(), _Authenticator())
    denied = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/2/hard-gate-assessments/materialize",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "s90-denied"},
        json={
            "source_case_input_sha256": "a" * 64,
            "document_binding_id": "binding-1",
            "manifest_evidence_sha256": "b" * 64,
            "document_decision_sha256": "c" * 64,
            "decisions": _decisions(),
        },
    )
    assert denied.status_code == 403
    invalid = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/2/hard-gate-assessments/materialize",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "s90-invalid"},
        json={
            "source_case_input_sha256": "a" * 64,
            "document_binding_id": "binding-1",
            "manifest_evidence_sha256": "b" * 64,
            "document_decision_sha256": "c" * 64,
            "decisions": _decisions()[:-1],
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_hard_gate_assessment"
