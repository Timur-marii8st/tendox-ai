from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx

from case_support import AT, paper_case
from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import InvalidParticipationDecision, Principal
from procurement.documents import (
    ParticipationDecision,
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    build_participation_decision,
    build_participation_evaluation_evidence,
)
from procurement.domain.cases import case_input_digest, evaluate_case


class Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        roles = {
            "approver": ("approver-a", AccessRole.PARTICIPATION_APPROVER),
            "self": ("operator-a", AccessRole.PARTICIPATION_APPROVER),
            "operator": ("operator-b", AccessRole.OPERATOR),
            "auditor": ("auditor-a", AccessRole.AUDITOR),
            "foreign": ("approver-b", AccessRole.PARTICIPATION_APPROVER),
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
        self.case = paper_case()
        recommendation = evaluate_case(self.case, at=AT)
        evidence = build_participation_evaluation_evidence(
            company_id=self.case.company_id,
            evaluation_id="evaluation-1",
            case_id=self.case.case_id,
            case_version=self.case.version,
            effective_at=AT,
            case_input_sha256=case_input_digest(self.case),
            engine_version="test-engine",
            recommendation=recommendation,
            evaluated_by="operator-a",
            evaluated_at=AT,
        )
        self.record = ParticipationDecisionRecord(evidence=evidence)

    async def get_participation_decision(
        self, *, company_id: str, evaluation_id: str
    ) -> ParticipationDecisionRecord | None:
        if company_id != self.case.company_id or evaluation_id != "evaluation-1":
            return None
        return self.record

    async def decide_participation(
        self,
        *,
        company_id: str,
        actor_id: str,
        evaluation_id: str,
        evaluation_evidence_sha256: str,
        status: ParticipationDecisionStatus,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ParticipationDecision:
        del idempotency_key, request_digest
        if (
            company_id != self.case.company_id
            or evaluation_id != self.record.evidence.evaluation_id
            or evaluation_evidence_sha256 != self.record.evidence.evidence_sha256
        ):
            raise InvalidParticipationDecision
        try:
            decision = build_participation_decision(
                self.record.evidence,
                decision_id="decision-1",
                status=status,
                current_recommendation=evaluate_case(self.case, at=AT + timedelta(minutes=1)),
                reason=reason,
                decided_by=actor_id,
                decided_at=AT + timedelta(minutes=1),
            )
        except ValueError as error:
            raise InvalidParticipationDecision from error
        self.record = ParticipationDecisionRecord(
            evidence=self.record.evidence, decision=decision
        )
        return decision


def call(service: Service, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(service, Authenticator()))  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_participation_decision_requires_dedicated_role_and_exact_evidence() -> None:
    service = Service()
    path = "/v1/evaluations/evaluation-1/participation-decision"
    operator = call(service, "GET", path, headers={"Authorization": "Bearer operator"})
    assert operator.status_code == 403
    loaded = call(service, "GET", path, headers={"Authorization": "Bearer approver"})
    assert loaded.status_code == 200
    evidence_sha = loaded.json()["evidence"]["evidence_sha256"]
    decided = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer approver", "Idempotency-Key": "decision-1"},
        json={
            "evaluation_evidence_sha256": evidence_sha,
            "status": "APPROVED",
            "reason": "Все основания проверены независимо",
        },
    )
    assert decided.status_code == 201
    assert decided.json()["external_action_authorized"] is False


def test_participation_decision_blocks_self_approval_and_cross_tenant_reads() -> None:
    service = Service()
    path = "/v1/evaluations/evaluation-1/participation-decision"
    evidence_sha = service.record.evidence.evidence_sha256
    self_approval = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer self", "Idempotency-Key": "decision-self"},
        json={
            "evaluation_evidence_sha256": evidence_sha,
            "status": "APPROVED",
            "reason": "Нельзя согласовать собственную оценку",
        },
    )
    assert self_approval.status_code == 422
    foreign = call(service, "GET", path, headers={"Authorization": "Bearer foreign"})
    assert foreign.status_code == 404
    auditor_write = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer auditor", "Idempotency-Key": "decision-audit"},
        json={
            "evaluation_evidence_sha256": evidence_sha,
            "status": "REJECTED",
            "reason": "Read only",
        },
    )
    assert auditor_write.status_code == 403
