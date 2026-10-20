"""Actual HTTP and PostgreSQL preserve an RFQ draft without any external dispatch."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from test_manufacturer_directory_pg import setup
from test_manufacturer_directory_pg import storage as storage_fixture

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Principal
from procurement.storage.manufacturer_review import read_manufacturer_decision

storage = storage_fixture


def test_rfq_http_exact_binding_roles_replay_and_download(storage, monkeypatch):
    company = "manufacturer-rfq-http-" + uuid4().hex
    search, candidate, _, _, proposal = setup(storage, monkeypatch, company=company)
    decision = read_manufacturer_decision(storage, company, proposal.proposal.proposal_id)

    class Auth:
        async def authenticate(self, token):
            if token not in ("operator", "auditor", "foreign"):
                return None
            return Principal(
                company_id="other-" + company if token == "foreign" else company,
                actor_id=token,
                access_role=AccessRole.OPERATOR if token == "operator" else AccessRole.AUDITOR,
            )

    command = {
        "command_id": str(uuid4()),
        "run_id": search.report.run_id,
        "record_id": candidate.record_id,
        "proposal_id": proposal.proposal.proposal_id,
        "decision_id": decision.decision.decision_id,
        "quantity": "12.500",
        "unit_raw": "комплект",
        "quantity_basis_raw": "Тестовый ручной расчёт",
        "requirements": ["Приложить паспорт изделия"],
        "delivery_address_raw": "Тестовый адрес",
        "desired_delivery_raw": "В течение 30 дней",
        "reply_due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    app = create_app(object(), Auth(), eis_index_storage=storage)
    headers = {"Authorization": "Bearer operator"}

    def forbidden(*args, **kwargs):
        raise AssertionError("RFQ preparation must not access external sources")

    monkeypatch.setattr(
        "procurement.storage.manufacturer_search.capture_manufacturer_search", forbidden
    )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            path = "/v1/manufacturer-rfq"
            assert (await client.post(path, json=command)).status_code == 401
            assert (
                await client.post(
                    path,
                    json=command,
                    headers={"Authorization": "Bearer auditor"},
                )
            ).status_code == 403
            for change in (
                {"actor_id": "injected"},
                {"recipient_email": "external@example.test"},
                {"quantity": 1.25},
                {"quantity": True},
                {"quantity": "NaN"},
                {"quantity": "1e1000000"},
                {"reply_due_at": "2027-01-01T00:00:00"},
                {"decision_id": str(uuid4())},
            ):
                response = await client.post(path, json={**command, **change}, headers=headers)
                assert response.status_code == 422, response.text
            created = await client.post(path, json=command, headers=headers)
            assert created.status_code == 200, created.text
            saved = created.json()
            assert saved["current_status"] == "PASS"
            draft = saved["draft"]
            assert draft["status"] == "DRAFT_NO_DISPATCH" and draft["quantity"] == "12.5"
            assert draft["contact"] == draft["quote"] == draft["participation"] == "UNKNOWN"
            assert draft["quantity_input"]["provenance"]["actor_id"] == "operator"
            replay = await client.post(path, json=command, headers=headers)
            assert replay.status_code == 200 and not replay.json()["created"]
            assert replay.json()["draft"] == draft
            changed = await client.post(path, json={**command, "quantity": "13"}, headers=headers)
            assert changed.status_code == 409
            read_path = path + "/" + draft["draft_id"]
            assert (
                await client.get(read_path, headers={"Authorization": "Bearer foreign"})
            ).status_code == 404
            document = await client.get(
                read_path + "/text", headers={"Authorization": "Bearer auditor"}
            )
            assert document.status_code == 200, document.text
            assert document.content == draft["text"].encode("utf-8")
            assert (
                hashlib.sha256(document.content).hexdigest() == document.headers["x-content-sha256"]
            )
            assert document.headers["cache-control"] == "no-store"
            assert document.headers["x-manufacturer-applicability"] == "PASS"
            assert "Черновик запроса" in document.text
            assert "/v1/manufacturer-rfq/send" not in app.openapi()["paths"]

    asyncio.run(check())
