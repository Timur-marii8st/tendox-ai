"""Actual HTTP and PostgreSQL enforce independent manufacturer review."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from test_manufacturer_review_pg import PDF
from test_manufacturer_review_pg import storage as storage_fixture
from test_manufacturer_search_pg import _capture

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Principal
from procurement.storage import manufacturer_search as source
from procurement.storage.manufacturer_search import start_search

storage = storage_fixture


def test_upload_propose_independent_review_source_metadata_and_replay(storage, monkeypatch):
    company = "manufacturer-http-review-" + uuid4().hex

    class Auth:
        async def authenticate(self, token):
            roles = {
                "operator": AccessRole.OPERATOR,
                "reviewer": AccessRole.MANUFACTURER_REVIEWER,
                "self": AccessRole.MANUFACTURER_REVIEWER,
                "foreign": AccessRole.MANUFACTURER_REVIEWER,
                "auditor": AccessRole.AUDITOR,
            }
            if token in roles:
                return Principal(
                    company_id="foreign-" + company if token == "foreign" else company,
                    actor_id="operator" if token == "self" else token,
                    access_role=roles[token],
                )
            return None

    monkeypatch.setattr(source, "capture_manufacturer_search", _capture)
    saved = start_search(storage, company, "насос", "operator", str(uuid4()))
    app = create_app(object(), Auth(), eis_index_storage=storage)

    def headers(token):
        return {"Authorization": "Bearer " + token}

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            artifact_command = {
                "command_id": str(uuid4()),
                "source_title": "Synthetic official record",
                "source_url": "https://example.test/extract.pdf",
                "original_filename": "proof.pdf",
                "content_base64": base64.b64encode(PDF).decode(),
            }
            assert (
                await client.post(
                    "/v1/manufacturer-review/artifacts",
                    json=artifact_command,
                )
            ).status_code == 401
            uploaded = await client.post(
                "/v1/manufacturer-review/artifacts",
                json=artifact_command,
                headers=headers("operator"),
            )
            assert uploaded.status_code == 200, uploaded.text
            artifact = uploaded.json()
            assert "content" not in artifact and artifact["origin_status"] == "CLAIMED_BY_UPLOADER"
            replay = await client.post(
                "/v1/manufacturer-review/artifacts",
                json=artifact_command,
                headers=headers("operator"),
            )
            assert replay.json() == artifact
            proposal_command = {
                "command_id": str(uuid4()),
                "run_id": saved.report.run_id,
                "record_id": saved.report.candidates[0].record_id,
                "claimed_identity": {
                    "legal_name": "Factory LLC",
                    "country_code": "RU",
                    "identifier_scheme": "INN",
                    "registration_id": "1234567890",
                },
                "citations": [
                    {
                        "artifact_id": artifact["artifact_id"],
                        "artifact_sha256": artifact["sha256"],
                        "page": 1,
                        "locator": "page 1",
                        "quote": "Synthetic factory and product evidence",
                        "claims": [
                            "LEGAL_NAME",
                            "COUNTRY",
                            "IDENTIFIER_SCHEME",
                            "REGISTRATION_ID",
                            "MANUFACTURER_ROLE",
                        ],
                    }
                ],
            }
            proposed = await client.post(
                "/v1/manufacturer-review/proposals",
                json=proposal_command,
                headers=headers("operator"),
            )
            assert proposed.status_code == 200, proposed.text
            proposal = proposed.json()["proposal"]
            prefix = "/v1/manufacturer-review/proposals/" + proposal["proposal_id"]
            assert (
                await client.get(
                    "/v1/manufacturer-review/proposals",
                    headers=headers("reviewer"),
                )
            ).json()[0]["proposal_id"] == proposal["proposal_id"]
            assert (await client.get(prefix, headers=headers("foreign"))).status_code == 404
            path = prefix + "/artifacts/" + artifact["artifact_id"]
            assert (await client.get(path, headers=headers("operator"))).status_code == 403
            assert (await client.get(path, headers=headers("foreign"))).status_code == 404
            metadata = await client.get(path + "/metadata", headers=headers("reviewer"))
            assert metadata.status_code == 200 and metadata.json() == artifact
            document = await client.get(path, headers=headers("reviewer"))
            assert document.content == PDF
            assert document.headers["x-content-sha256"] == artifact["sha256"]
            assert document.headers["cache-control"] == "no-store"
            decision = {
                "command_id": str(uuid4()),
                "identity_status": "PASS",
                "role_status": "PASS",
                "official_origin_confirmed": True,
                "identity_fields_confirmed": True,
                "exact_product_link_confirmed": True,
                "effective_until": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                "rationale": "Independent synthetic evidence review",
                "citation_indexes": [0],
            }
            assert (
                await client.post(
                    prefix + "/decision",
                    json=decision,
                    headers=headers("operator"),
                )
            ).status_code == 403
            assert (
                await client.post(
                    prefix + "/decision",
                    json=decision,
                    headers=headers("self"),
                )
            ).status_code == 403
            for changed in (
                {"reviewed_by": "injected"},
                {"official_origin_confirmed": "true"},
                {"citation_indexes": [True]},
            ):
                assert (
                    await client.post(
                        prefix + "/decision",
                        json={**decision, **changed},
                        headers=headers("reviewer"),
                    )
                ).status_code == 422
            accepted = await client.post(
                prefix + "/decision",
                json=decision,
                headers=headers("reviewer"),
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["current_status"] == "PASS"
            replay = await client.post(
                prefix + "/decision",
                json=decision,
                headers=headers("reviewer"),
            )
            assert replay.status_code == 200 and not replay.json()["created"]
            assert replay.json()["decision"] == accepted.json()["decision"]
            read = await client.get(prefix + "/decision", headers=headers("auditor"))
            assert read.status_code == 200 and read.json()["current_status"] == "PASS"

    asyncio.run(check())
