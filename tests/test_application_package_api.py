from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx

from case_support import AT, paper_case
from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import InvalidApplicationPackage, Principal
from procurement.documents import (
    ApplicationAttachment,
    ApplicationAttachmentInput,
    ApplicationDocumentRequirement,
    ApplicationPackage,
    ApplicationPackageEvidence,
    ApplicationPackageRecord,
    ApplicationRequirementKind,
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    build_application_package,
    build_participation_decision,
    build_participation_evaluation_evidence,
)
from procurement.domain.cases import case_input_digest, evaluate_case


class Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        roles = {
            "operator": ("operator-b", AccessRole.OPERATOR),
            "approver": ("approver-a", AccessRole.PARTICIPATION_APPROVER),
            "auditor": ("auditor-a", AccessRole.AUDITOR),
            "foreign": ("operator-c", AccessRole.OPERATOR),
        }
        identity = roles.get(credential)
        if identity is None:
            return None
        actor, role = identity
        return Principal(
            company_id="other-company" if credential == "foreign" else "demo-company",
            actor_id=actor,
            access_role=role,
        )


class Service:
    def __init__(self) -> None:
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
        decision = build_participation_decision(
            evaluation,
            decision_id="decision-1",
            status=ParticipationDecisionStatus.APPROVED,
            current_recommendation=evaluate_case(case, at=AT + timedelta(minutes=1)),
            reason="Независимая проверка завершена",
            decided_by="approver-a",
            decided_at=AT + timedelta(minutes=1),
        )
        self.evidence = ApplicationPackageEvidence(
            case=case,
            participation=ParticipationDecisionRecord(
                evidence=evaluation,
                decision=decision,
            ),
        )
        self.package: ApplicationPackage | None = None

    async def get_application_package(
        self, *, company_id: str, participation_decision_id: str
    ) -> ApplicationPackageRecord | None:
        if (
            company_id != self.evidence.case.company_id
            or participation_decision_id != "decision-1"
        ):
            return None
        return ApplicationPackageRecord(evidence=self.evidence, package=self.package)

    async def store_application_package(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        participation_decision_id: str,
        participation_decision_sha256: str,
        proposed_price_ex_vat: Decimal,
        requirements: tuple[ApplicationDocumentRequirement, ...],
        attachments: tuple[ApplicationAttachmentInput, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationPackage:
        del idempotency_key, request_digest
        decision = self.evidence.participation.decision
        assert decision is not None
        if (
            company_id != self.evidence.case.company_id
            or participation_decision_id != decision.decision_id
            or participation_decision_sha256 != decision.decision_sha256
        ):
            raise InvalidApplicationPackage
        resolved = tuple(
            ApplicationAttachment(
                **item.model_dump(mode="python"),
                original_filename="application.pdf",
                media_type="application/pdf",
            )
            for item in attachments
        )
        try:
            self.package = build_application_package(
                self.evidence,
                package_id=package_id,
                proposed_price_ex_vat=proposed_price_ex_vat,
                requirements=requirements,
                attachments=resolved,
                current_recommendation=evaluate_case(
                    self.evidence.case, at=AT + timedelta(minutes=2)
                ),
                prepared_by=actor_id,
                prepared_at=AT + timedelta(minutes=2),
            )
        except ValueError as error:
            raise InvalidApplicationPackage from error
        return self.package


def call(service: Service, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(service, Authenticator()))  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def payload(service: Service) -> dict[str, object]:
    decision = service.evidence.participation.decision
    assert decision is not None
    return {
        "participation_decision_sha256": decision.decision_sha256,
        "proposed_price_ex_vat": "1300000.00",
        "requirements": [
            {
                "ordinal": 1,
                "kind": ApplicationRequirementKind.FORM.value,
                "title": "Форма заявки",
                "source_document_id": "tender-document-1",
                "source_document_sha256": "1" * 64,
                "source_locator": "Раздел 4, форма 1",
            }
        ],
        "attachments": [
            {
                "ordinal": 1,
                "requirement_ordinals": [1],
                "document_id": "application-document-1",
                "document_sha256": "2" * 64,
                "submission_filename": "application.pdf",
            }
        ],
    }


def test_operator_prepares_exact_pending_package_without_external_authority() -> None:
    service = Service()
    path = "/v1/participation-decisions/decision-1/application-package"
    evidence = call(
        service, "GET", path, headers={"Authorization": "Bearer operator"}
    )
    assert evidence.status_code == 200
    assert evidence.json()["package"] is None
    stored = call(
        service,
        "POST",
        path,
        headers={
            "Authorization": "Bearer operator",
            "Idempotency-Key": "package-1",
        },
        json=payload(service),
    )
    assert stored.status_code == 201
    assert stored.json()["review_status"] == "PENDING_REVIEW"
    assert stored.json()["coverage_status"] == "UNKNOWN"
    assert stored.json()["external_action_authorized"] is False
    assert stored.json()["prepared_by"] == "operator-b"


def test_application_package_access_and_exact_decision_are_fail_closed() -> None:
    service = Service()
    path = "/v1/participation-decisions/decision-1/application-package"
    approver = call(
        service, "GET", path, headers={"Authorization": "Bearer approver"}
    )
    assert approver.status_code == 403
    auditor = call(service, "GET", path, headers={"Authorization": "Bearer auditor"})
    assert auditor.status_code == 200
    auditor_write = call(
        service,
        "POST",
        path,
        headers={
            "Authorization": "Bearer auditor",
            "Idempotency-Key": "package-audit",
        },
        json=payload(service),
    )
    assert auditor_write.status_code == 403
    foreign = call(service, "GET", path, headers={"Authorization": "Bearer foreign"})
    assert foreign.status_code == 404
    invalid = payload(service)
    invalid["participation_decision_sha256"] = "f" * 64
    rejected = call(
        service,
        "POST",
        path,
        headers={
            "Authorization": "Bearer operator",
            "Idempotency-Key": "package-invalid",
        },
        json=invalid,
    )
    assert rejected.status_code == 422
    non_exact_money = payload(service)
    non_exact_money["proposed_price_ex_vat"] = 1300000.00
    rejected_float = call(
        service,
        "POST",
        path,
        headers={
            "Authorization": "Bearer operator",
            "Idempotency-Key": "package-float",
        },
        json=non_exact_money,
    )
    assert rejected_float.status_code == 422
