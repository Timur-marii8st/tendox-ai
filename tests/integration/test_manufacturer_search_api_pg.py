"""HTTP roundtrip against real PostgreSQL and server-captured registry evidence."""

import asyncio
from typing import cast
from uuid import uuid4

import httpx
from test_manufacturer_search_pg import _capture
from test_manufacturer_search_pg import storage as storage_fixture

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import CaseService, Principal
from procurement.storage import manufacturer_search as repository

storage = storage_fixture


def test_api_create_replay_list_read_candidate_and_foreign_tenant(storage, monkeypatch):
    company = "manufacturer-api-" + uuid4().hex
    calls = []

    class Auth:
        async def authenticate(self, token):
            if token in ("operator", "auditor", "foreign"):
                return Principal(
                    company_id=company if token != "foreign" else "other-" + company,
                    actor_id="test-" + token,
                    access_role=AccessRole.OPERATOR if token == "operator" else AccessRole.AUDITOR,
                )
            return None

    def capture(query):
        calls.append(query)
        return _capture(query)

    monkeypatch.setattr(repository, "capture_manufacturer_search", capture)
    app = create_app(cast(CaseService, object()), Auth(), eis_index_storage=storage)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            operator = {"Authorization": "Bearer operator"}
            payload = {"command_id": str(uuid4()), "query": "насос"}
            created = await client.post("/v1/manufacturer-search", json=payload, headers=operator)
            assert created.status_code == 200, created.text
            saved = created.json()
            assert saved["created"] and saved["source_requests"] == 1
            run_id = saved["report"]["run_id"]
            record_id = saved["report"]["candidates"][0]["record_id"]
            replay = await client.post("/v1/manufacturer-search", json=payload, headers=operator)
            assert replay.status_code == 200
            assert replay.json()["report"] == saved["report"]
            assert not replay.json()["created"] and replay.json()["source_requests"] == 0
            changed = await client.post(
                "/v1/manufacturer-search",
                json={**payload, "query": "сервер"},
                headers=operator,
            )
            assert changed.status_code == 409
            auditor = {"Authorization": "Bearer auditor"}
            summaries = await client.get("/v1/manufacturer-search", headers=auditor)
            assert summaries.status_code == 200 and summaries.json()[0]["candidate_count"] == 1
            for suffix in (run_id, f"{run_id}/candidates/{record_id}"):
                own = await client.get(f"/v1/manufacturer-search/{suffix}", headers=auditor)
                assert own.status_code == 200
                assert own.headers["cache-control"] == "no-store"
                foreign = await client.get(
                    f"/v1/manufacturer-search/{suffix}",
                    headers={"Authorization": "Bearer foreign"},
                )
                assert foreign.status_code == 404
            candidate = (
                await client.get(
                    f"/v1/manufacturer-search/{run_id}/candidates/{record_id}",
                    headers=auditor,
                )
            ).json()
            assert candidate["candidate"]["identity"] == "UNKNOWN"
            assert candidate["candidate"]["document_validity"] == "FAIL"
            assert (
                candidate["provenance"]["field_locators"]["manufacturer_name"] == "result[0].name"
            )
            assert calls == ["насос"]

    asyncio.run(check())
