from __future__ import annotations

import asyncio
import importlib
import io
from datetime import datetime, timedelta
from typing import Any
from zipfile import ZipFile

import httpx

from case_support import AT
from procurement.api import create_app
from procurement.documents.application_submission import ApplicationSubmissionRecord
from procurement.documents.application_submission_execution import (
    ApplicationSubmissionAdmission,
    ApplicationSubmissionExecutionRecord,
    build_submission_admission,
)
from test_application_review_api import Service as DocumentService
from test_application_submission_execution import BYTES, _approved
from test_application_submission_execution_api import Authenticator


class Service(DocumentService):
    def __init__(self) -> None:
        super().__init__()
        self.submission = _approved()
        self.admission: ApplicationSubmissionAdmission | None = None

    async def get_application_submission(
        self, *, company_id: str, package_id: str,
    ) -> ApplicationSubmissionRecord | None:
        intent = self.submission.intent
        assert intent is not None
        if company_id != intent.request.company_id or package_id != intent.package_id:
            return None
        return self.submission

    async def get_application_submission_execution(
        self, *, company_id: str, package_id: str,
    ) -> ApplicationSubmissionExecutionRecord | None:
        submission = await self.get_application_submission(
            company_id=company_id, package_id=package_id
        )
        if submission is None:
            return None
        return ApplicationSubmissionExecutionRecord(
            submission=submission, admission=self.admission
        )


def call(app: Any, path: str, **kwargs: Any) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, **kwargs)

    return asyncio.run(run())


def test_handoff_api_tenant_role_and_original_integrity(monkeypatch: Any) -> None:
    app_module = importlib.import_module("procurement.api.app")

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return (AT + timedelta(minutes=6)).astimezone(tz)

    service = Service()
    app = create_app(service, Authenticator())  # type: ignore[arg-type]
    monkeypatch.setattr(app_module, "datetime", FrozenDatetime)
    path = "/v1/application-packages/package-1/submission/handoff"
    assert call(app, path, headers={"Authorization": "Bearer operator"}).status_code == 403
    assert call(app, path, headers={"Authorization": "Bearer foreign"}).status_code == 404
    response = call(app, path, headers={"Authorization": "Bearer executor"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read("files/001-application.pdf") == b"exact application bytes"
    service.corrupt_content = True
    assert call(app, path, headers={"Authorization": "Bearer executor"}).status_code == 422
    service.corrupt_content = False
    service.admission = build_submission_admission(
        service.submission,
        attachment_bytes={"application-document": BYTES},
        admission_id="admission-1",
        admitted_by="executor-a",
        admitted_at=AT + timedelta(minutes=6),
    )
    assert call(app, path, headers={"Authorization": "Bearer executor"}).status_code == 409
