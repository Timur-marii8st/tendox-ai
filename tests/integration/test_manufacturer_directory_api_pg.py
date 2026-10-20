"""The saved-search manufacturer directory is scoped and read-only over actual PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from test_manufacturer_review_pg import setup_proposal
from test_manufacturer_review_pg import storage as storage_fixture
from test_manufacturer_search_pg import _capture

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Principal
from procurement.domain.manufacturer_review import ReviewStatus
from procurement.storage.manufacturer_review import decide_manufacturer_review

storage = storage_fixture


def test_directory_http_review_binding_no_source_calls_and_foreign_tenant(storage, monkeypatch):
    company = "manufacturer-directory-http-" + uuid4().hex
    monkeypatch.setattr(
        "test_manufacturer_review_pg._capture",
        lambda query: _capture(query, expiry=(datetime.now(UTC) + timedelta(days=365)).date()),
    )
    _, saved = setup_proposal(storage, monkeypatch, company=company)
    proposal = saved.proposal

    class Auth:
        async def authenticate(self, token):
            if token not in ("auditor", "foreign"):
                return None
            return Principal(
                company_id=company if token == "auditor" else "other-" + company,
                actor_id=token,
                access_role=AccessRole.AUDITOR,
            )

    app = create_app(object(), Auth(), eis_index_storage=storage)
    path = "/v1/manufacturer-directory/" + proposal.dossier.run_id

    def forbidden(*args, **kwargs):
        raise AssertionError("reading directory must not fetch source")

    monkeypatch.setattr(
        "procurement.storage.manufacturer_search.capture_manufacturer_search", forbidden
    )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            assert (await client.get(path)).status_code == 401
            assert (
                await client.get(path, headers={"Authorization": "Bearer foreign"})
            ).status_code == 404
            headers = {"Authorization": "Bearer auditor"}
            pending = await client.get(path, headers=headers)
            assert pending.status_code == 200, pending.text
            assert pending.headers["cache-control"] == "no-store"
            assert pending.json()["overall_status"] == "UNKNOWN"
            assert pending.json()["groups"] == []
            decide_manufacturer_review(
                storage,
                company,
                proposal.proposal_id,
                identity_status=ReviewStatus.PASS,
                role_status=ReviewStatus.PASS,
                official_origin_confirmed=True,
                identity_fields_confirmed=True,
                exact_product_link_confirmed=True,
                effective_until=datetime.now(UTC) + timedelta(days=1),
                rationale="Independent synthetic review",
                citation_indexes=(0,),
                reviewer_id="directory-reviewer",
                command_id=str(uuid4()),
            )
            response = await client.get(path, headers=headers)
            assert response.status_code == 200, response.text
            directory = response.json()
            assert directory["overall_status"] == "PASS"
            assert directory["response_sha256"] == proposal.dossier.response_sha256
            assert directory["groups"][0]["proposal_ids"] == [proposal.proposal_id]
            assert (
                directory["records"][0]["review_evidence"][0]["dossier_sha256"]
                == proposal.dossier_sha256
            )
            for field in ("technical", "seller", "website", "quote", "participation"):
                assert directory[field] == "UNKNOWN"

    asyncio.run(check())
