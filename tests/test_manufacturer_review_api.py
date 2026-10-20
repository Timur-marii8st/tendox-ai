"""Review commands reject ambiguous bodies before touching persisted evidence."""

import asyncio
import base64
from uuid import uuid4

import httpx
import pytest

from test_manufacturer_search_api import application


def test_bounded_upload_and_proposal_commands_reject_ambiguity(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid command must not touch storage")

    monkeypatch.setattr("procurement.api.manufacturer_review.store_evidence_artifact", forbidden)
    monkeypatch.setattr(
        "procurement.api.manufacturer_review.prepare_manufacturer_review", forbidden
    )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(application()), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer operator", "Content-Type": "application/json"}
            artifact = {
                "command_id": str(uuid4()),
                "source_title": "Claimed source",
                "source_url": "https://example.test/proof.pdf",
                "original_filename": "proof.pdf",
                "content_base64": base64.b64encode(b"%PDF-test").decode(),
            }
            for path, content, status in (
                ("artifacts", '{"command_id":"a","command_id":"b"}', 422),
                ("artifacts", "x" * (3 * 1024 * 1024 + 1), 413),
                ("proposals", "x" * 16385, 413),
                ("proposals", '{"run_id":"a","run_id":"b"}', 422),
            ):
                response = await client.post(
                    "/v1/manufacturer-review/" + path,
                    content=content,
                    headers=headers,
                )
                assert response.status_code == status
                assert response.headers["cache-control"] == "no-store"
            for field in ("company_id", "actor_id", "uploaded_by", "origin_status", "sha256"):
                response = await client.post(
                    "/v1/manufacturer-review/artifacts",
                    json={**artifact, field: "injected"},
                    headers=headers,
                )
                assert response.status_code == 422
            response = await client.post(
                "/v1/manufacturer-review/artifacts",
                json=artifact,
                headers={"Authorization": "Bearer auditor"},
            )
            assert response.status_code == 403
            response = await client.post(
                "/v1/manufacturer-review/artifacts",
                content=b"%PDF-test",
                headers={**headers, "Content-Type": "application/pdf"},
            )
            assert response.status_code == 415

    asyncio.run(check())


def test_openapi_documents_bounded_review_commands():
    paths = application().openapi()["paths"]
    for path in (
        "/v1/manufacturer-review/artifacts",
        "/v1/manufacturer-review/proposals",
        "/v1/manufacturer-review/proposals/{proposal_id}/decision",
    ):
        schema = paths[path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["additionalProperties"] is False
        assert "command_id" in schema["required"]
