"""End-to-end HTTP checks through the real PostgreSQL adapters."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pypdf import PdfWriter
from sqlalchemy import create_engine, text

from procurement.api import create_app
from procurement.api.postgres import PostgresAuthenticator, PostgresCaseService
from procurement.storage import PostgresStorage

PAPER_CASE = Path(__file__).parents[2] / "examples" / "paper_case.json"


@pytest.fixture(scope="module")
def database_urls() -> tuple[str, str]:
    runtime = os.environ.get("DATABASE_URL")
    admin = os.environ.get("DATABASE_ADMIN_URL")
    if not runtime or not admin:
        pytest.skip("DATABASE_URL and DATABASE_ADMIN_URL are required")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin.replace("%", "%%"))
    command.upgrade(config, "head")
    return runtime, admin


def _request(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def _case_payload(company_id: str, case_id: str) -> dict[str, Any]:
    payload = json.loads(PAPER_CASE.read_text(encoding="utf-8"))
    payload["company_id"] = company_id
    payload["case_id"] = case_id
    payload["profile"]["company_id"] = company_id
    payload["selected_quote"]["company_id"] = company_id
    return payload


def _provision_key(admin_url: str, company_id: str, actor_id: str) -> str:
    secret = f"integration-{uuid.uuid4()}"
    engine = create_engine(admin_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(key_id, company_id, key_digest, actor_id, enabled) "
                    "VALUES (:key_id, :company_id, :key_digest, :actor_id, true)"
                ),
                {
                    "key_id": str(uuid.uuid4()),
                    "company_id": company_id,
                    "key_digest": hashlib.sha256(secret.encode()).hexdigest(),
                    "actor_id": actor_id,
                },
            )
    finally:
        engine.dispose()
    return secret


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_real_api_auth_rls_idempotency_and_atomic_evaluation(
    database_urls: tuple[str, str],
) -> None:
    runtime_url, admin_url = database_urls
    company_a = f"tenant-{uuid.uuid4()}"
    company_b = f"tenant-{uuid.uuid4()}"
    case_id = f"case-{uuid.uuid4()}"
    token_a = _provision_key(admin_url, company_a, "operator-a")
    token_b = _provision_key(admin_url, company_b, "operator-b")
    engine = create_engine(runtime_url, pool_pre_ping=True)
    try:
        storage = PostgresStorage(engine)
        app = create_app(PostgresCaseService(storage), PostgresAuthenticator(storage))
        auth_a = {"Authorization": f"Bearer {token_a}"}
        auth_b = {"Authorization": f"Bearer {token_b}"}
        payload = _case_payload(company_a, case_id)

        first = _request(
            app,
            "POST",
            "/v1/cases",
            headers={**auth_a, "Idempotency-Key": "create-1"},
            json=payload,
        )
        replay = _request(
            app,
            "POST",
            "/v1/cases",
            headers={**auth_a, "Idempotency-Key": "create-1"},
            json=payload,
        )
        conflict = _request(
            app,
            "POST",
            "/v1/cases",
            headers={**auth_a, "Idempotency-Key": "create-2"},
            json=payload,
        )

        assert first.status_code == replay.status_code == 201
        assert first.json() == replay.json()
        assert conflict.status_code == 409
        assert _request(
            app,
            "GET",
            f"/v1/cases/{case_id}/versions/1",
            headers=auth_b,
        ).status_code == 404
        malformed_cursor = _request(
            app,
            "GET",
            "/v1/cases?cursor=not-a-real-cursor",
            headers=auth_a,
        )
        assert malformed_cursor.status_code == 422
        assert malformed_cursor.json() == {"detail": "validation_error"}

        evaluation_path = f"/v1/cases/{case_id}/versions/1/evaluations"
        latest_evaluation_path = f"{evaluation_path}/latest"
        no_evaluation = _request(app, "GET", latest_evaluation_path, headers=auth_a)
        assert no_evaluation.status_code == 404
        evaluation_headers = {**auth_a, "Idempotency-Key": "evaluate-1"}
        evaluation_body = {"effective_at": "2026-09-08T12:00:00+03:00"}
        evaluated = _request(
            app,
            "POST",
            evaluation_path,
            headers=evaluation_headers,
            json=evaluation_body,
        )
        evaluated_replay = _request(
            app,
            "POST",
            evaluation_path,
            headers=evaluation_headers,
            json=evaluation_body,
        )

        assert evaluated.status_code == evaluated_replay.status_code == 201
        assert evaluated.json() == evaluated_replay.json()
        evaluation_id = evaluated.json()["evaluation_id"]
        assert evaluated.json()["audit_event_id"] == evaluation_id
        latest = _request(app, "GET", latest_evaluation_path, headers=auth_a)
        cross_tenant_latest = _request(app, "GET", latest_evaluation_path, headers=auth_b)
        missing_latest = _request(
            app,
            "GET",
            "/v1/cases/missing/versions/1/evaluations/latest",
            headers=auth_b,
        )
        assert latest.status_code == 200
        assert latest.json() == evaluated.json()
        assert cross_tenant_latest.status_code == missing_latest.status_code == 404
        assert cross_tenant_latest.json() == missing_latest.json() == {"detail": "not_found"}
        assert len(storage.list_audit_events(company_a, object_id=case_id)) == 1
        assert storage.list_audit_events(company_b, object_id=case_id) == []

        document_headers = {**auth_a, "Idempotency-Key": "document-1"}
        document_file = {"file": ("scan.pdf", _blank_pdf(), "application/pdf")}
        uploaded = _request(
            app,
            "POST",
            "/v1/documents",
            headers=document_headers,
            files=document_file,
        )
        uploaded_replay = _request(
            app,
            "POST",
            "/v1/documents",
            headers=document_headers,
            files=document_file,
        )
        assert uploaded.status_code == uploaded_replay.status_code == 201
        assert uploaded.json() == uploaded_replay.json()
        document_id = uploaded.json()["document_id"]
        assert uploaded.json()["extraction"]["status"] == "UNKNOWN"
        assert "content" not in uploaded.json()
        assert _request(
            app,
            "GET",
            f"/v1/documents/{document_id}",
            headers=auth_b,
        ).status_code == 404
        assert len(storage.list_audit_events(company_a, object_id=document_id)) == 1
    finally:
        engine.dispose()
