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
from procurement.documents.application_submission_execution import (
    ApplicationSubmissionAdmission,
    ApplicationSubmissionExecutionRecord,
    build_submission_admission,
)
from test_application_submission_execution import BYTES, _approved


class Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        users = {
            "executor": ("executor-a", AccessRole.APPLICATION_SUBMISSION_EXECUTOR),
            "approver": ("approver-b", AccessRole.APPLICATION_SUBMISSION_APPROVER),
            "operator": ("operator-c", AccessRole.OPERATOR),
            "auditor": ("auditor-a", AccessRole.AUDITOR),
            "foreign": ("executor-z", AccessRole.APPLICATION_SUBMISSION_EXECUTOR),
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
        self.submission = _approved()
        self.admission: ApplicationSubmissionAdmission | None = None

    async def get_application_submission_execution(
        self,
        *,
        company_id: str,
        package_id: str,
    ) -> ApplicationSubmissionExecutionRecord | None:
        intent = self.submission.intent
        assert intent is not None
        if company_id != intent.request.company_id or package_id != intent.package_id:
            return None
        return ApplicationSubmissionExecutionRecord(
            submission=self.submission,
            admission=self.admission,
        )

    async def claim_application_submission(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        action_id: str,
        payload_sha256: str,
        approval_decision_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationSubmissionAdmission:
        del idempotency_key, request_digest
        intent = self.submission.intent
        decision = self.submission.decision
        assert intent is not None and decision is not None
        if self.admission is not None:
            raise ApplicationSubmissionConflict
        if (
            company_id != intent.request.company_id
            or package_id != intent.package_id
            or action_id != intent.request.action_id
            or payload_sha256 != intent.request.payload_sha256
            or approval_decision_sha256 != decision.decision_sha256
        ):
            raise InvalidApplicationSubmission
        try:
            self.admission = build_submission_admission(
                self.submission,
                attachment_bytes={"application-document": BYTES},
                admission_id="admission-1",
                admitted_by=actor_id,
                admitted_at=AT + timedelta(minutes=6),
            )
        except ValueError as error:
            raise InvalidApplicationSubmission from error
        return self.admission


def call(service: Service, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(service, Authenticator()))  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_admission_api_requires_executor_and_exact_approval() -> None:
    service = Service()
    path = "/v1/application-packages/package-1/submission/admission"
    intent = service.submission.intent
    decision = service.submission.decision
    assert intent is not None and decision is not None
    body = {
        "action_id": intent.request.action_id,
        "payload_sha256": intent.request.payload_sha256,
        "approval_decision_sha256": decision.decision_sha256,
    }
    assert (
        call(service, "GET", path, headers={"Authorization": "Bearer operator"}).status_code == 403
    )
    assert (
        call(service, "GET", path, headers={"Authorization": "Bearer foreign"}).status_code == 404
    )
    assert (
        call(service, "GET", path, headers={"Authorization": "Bearer executor"}).json()["admission"]
        is None
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
    wrong = body | {"approval_decision_sha256": "0" * 64}
    assert (
        call(
            service,
            "POST",
            path,
            headers={"Authorization": "Bearer executor", "Idempotency-Key": "wrong-sha"},
            json=wrong,
        ).status_code
        == 422
    )
    admitted = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer executor", "Idempotency-Key": "claim-1"},
        json=body,
    )
    assert admitted.status_code == 201
    assert admitted.json()["status"] == "ADMITTED_NO_DISPATCH"
    assert admitted.json()["external_action_performed"] is False
    assert (
        call(
            service,
            "POST",
            path,
            headers={"Authorization": "Bearer executor", "Idempotency-Key": "claim-2"},
            json=body,
        ).status_code
        == 409
    )
    assert (
        call(service, "GET", path, headers={"Authorization": "Bearer auditor"}).json()["admission"][
            "admission_sha256"
        ]
        == admitted.json()["admission_sha256"]
    )
