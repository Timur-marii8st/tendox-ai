"""Invited users use their own company quota without widening beta access."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.sources.gosplan_search import SearchPage


def test_beta_search_uses_personal_company_not_shared_corpus(monkeypatch):
    pytest.importorskip("procurement.api.beta_access")
    from procurement.api import discovery_runtime, gosplan_search

    class Auth:
        def __init__(self, storage):
            self.storage = storage

        async def authenticate(self, credential):
            if credential == "bs_test":
                return Principal(
                    company_id="private-company",
                    actor_id="beta-user",
                    access_role=AccessRole.OPERATOR,
                )
            return None

    monkeypatch.setenv("EIS_PILOT_TOKEN", "p" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/test")
    monkeypatch.setattr(discovery_runtime, "BetaPersonalAuthenticator", Auth)
    monkeypatch.setattr(discovery_runtime, "public_corpus_company", lambda *args: "shared-corpus")
    seen = []

    def run(company, law, query, number, offset):
        seen.append(company)
        return SearchPage(
            law=law,
            query=query,
            observed_at=datetime.now(UTC),
            response_sha256="a" * 64,
            items=(),
            may_have_more=False,
        )

    monkeypatch.setattr(gosplan_search, "_run", run)
    with TestClient(discovery_runtime.create_discovery_app()) as client:
        headers = {"Authorization": "Bearer bs_test"}
        response = client.get(
            "/v1/tender-discovery/gosplan/search?law=44&query=paper", headers=headers
        )
        assert response.status_code == 200
        assert seen == ["private-company"]
        forbidden = client.post(
            "/v1/tender-discovery/eis-refresh-requests", headers=headers, json={}
        )
        assert forbidden.status_code == 403
