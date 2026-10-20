from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx

from case_support import AT
from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import (
    ApplicationSubmissionConflict,
    InvalidApplicationSubmission,
    Principal,
)
from procurement.documents.application_review import ApplicationReviewRecord
from procurement.documents.application_submission import (
    ApplicationSubmissionApproval,
    ApplicationSubmissionIntent,
    ApplicationSubmissionRecord,
    SubmissionApprovalStatus,
    build_submission_approval,
    build_submission_intent,
)
from test_application_review import _decide, _record


class Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        users = {
            "operator": ("operator-c", AccessRole.OPERATOR),
            "approver": ("approver-b", AccessRole.APPLICATION_SUBMISSION_APPROVER),
            "self": ("operator-c", AccessRole.APPLICATION_SUBMISSION_APPROVER),
            "auditor": ("auditor-a", AccessRole.AUDITOR),
            "foreign": ("approver-z", AccessRole.APPLICATION_SUBMISSION_APPROVER),
        }
        if credential not in users:
            return None
        actor, role = users[credential]
        return Principal(
            company_id="other-company" if credential == "foreign" else "demo-company",
            actor_id=actor,
            access_role=role,
        )


class Service:
    def __init__(self) -> None:
        package = _record()
        self.evidence = ApplicationReviewRecord(evidence=package, decision=_decide(package))
        self.intent: ApplicationSubmissionIntent | None = None
        self.decision: ApplicationSubmissionApproval | None = None

    async def get_application_submission(
        self, *, company_id: str, package_id: str
    ) -> ApplicationSubmissionRecord | None:
        if company_id != "demo-company" or package_id != "package-1":
            return None
        return ApplicationSubmissionRecord(
            evidence=self.evidence, intent=self.intent, decision=self.decision
        )

    async def prepare_application_submission(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        package_sha256: str,
        review_decision_sha256: str,
        destination: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationSubmissionIntent:
        del idempotency_key, request_digest
        package = self.evidence.evidence.package
        review = self.evidence.decision
        assert package is not None and review is not None
        if self.intent is not None:
            raise ApplicationSubmissionConflict
        if (
            company_id != package.company_id
            or package_id != package.package_id
            or package_sha256 != package.package_sha256
            or review_decision_sha256 != review.decision_sha256
        ):
            raise InvalidApplicationSubmission
        try:
            self.intent = build_submission_intent(
                self.evidence,
                action_id="action-1",
                destination=destination,
                prepared_by=actor_id,
                prepared_at=AT + timedelta(minutes=4),
            )
        except ValueError as error:
            raise InvalidApplicationSubmission from error
        return self.intent

    async def decide_application_submission(
        self,
        *,
        company_id: str,
        actor_id: str,
        action_id: str,
        payload_sha256: str,
        status: SubmissionApprovalStatus,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationSubmissionApproval:
        del idempotency_key, request_digest
        if self.decision is not None:
            raise ApplicationSubmissionConflict
        if (
            self.intent is None
            or company_id != self.intent.request.company_id
            or action_id != self.intent.request.action_id
            or payload_sha256 != self.intent.request.payload_sha256
        ):
            raise InvalidApplicationSubmission
        try:
            self.decision = build_submission_approval(
                ApplicationSubmissionRecord(evidence=self.evidence, intent=self.intent),
                status=status,
                reason=reason,
                decided_by=actor_id,
                decided_at=AT + timedelta(minutes=5),
            )
        except ValueError as error:
            raise InvalidApplicationSubmission from error
        return self.decision


def call(service: Service, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(service, Authenticator()))  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_submission_api_separates_operator_approver_and_exact_digest() -> None:
    service = Service()
    path = "/v1/application-packages/package-1/submission"
    package = service.evidence.evidence.package
    review = service.evidence.decision
    assert package is not None and review is not None
    body = {
        "package_sha256": package.package_sha256,
        "review_decision_sha256": review.decision_sha256,
        "destination": "https://zakupki.example/submit/123",
    }
    assert (
        call(service, "GET", path, headers={"Authorization": "Bearer foreign"}).status_code == 404
    )
    assert (
        call(
            service,
            "POST",
            path,
            headers={"Authorization": "Bearer approver", "Idempotency-Key": "wrong-role"},
            json=body,
        ).status_code
        == 403
    )
    created = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "prepare-1"},
        json=body,
    )
    assert created.status_code == 201
    assert created.json()["request"]["payload"]["attachments"][0]["document_sha256"] == "b" * 64
    action = created.json()["request"]
    approval = path + "/approval"
    decision_body = {
        "action_id": action["action_id"],
        "payload_sha256": "f" * 64,
        "status": "APPROVED",
        "reason": "Сверено",
    }
    assert (
        call(
            service,
            "POST",
            approval,
            headers={"Authorization": "Bearer approver", "Idempotency-Key": "wrong-sha"},
            json=decision_body,
        ).status_code
        == 422
    )
    decision_body["payload_sha256"] = action["payload_sha256"]
    assert (
        call(
            service,
            "POST",
            approval,
            headers={"Authorization": "Bearer self", "Idempotency-Key": "self"},
            json=decision_body,
        ).status_code
        == 422
    )
    approved = call(
        service,
        "POST",
        approval,
        headers={"Authorization": "Bearer approver", "Idempotency-Key": "approve-1"},
        json=decision_body,
    )
    assert approved.status_code == 201
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["external_action_performed"] is False
    assert (
        call(
            service,
            "POST",
            approval,
            headers={"Authorization": "Bearer auditor", "Idempotency-Key": "audit"},
            json=decision_body,
        ).status_code
        == 403
    )
    assert (
        call(service, "GET", path, headers={"Authorization": "Bearer auditor"}).json()["decision"][
            "decision_sha256"
        ]
        == approved.json()["decision_sha256"]
    )
