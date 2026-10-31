"""Gosplan access requires an authenticated principal and a shared quota."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.api.gosplan_search import _reserve, _secret, gosplan_search_router
from procurement.sources.gosplan_search import SearchPage


def test_quota_is_shared_between_tenants_and_fail_closed(tmp_path):
    path = tmp_path / "quota.sqlite"
    now = datetime(2026, 10, 29, tzinfo=UTC)
    _reserve(path, "tenant-a", now)
    _reserve(path, "tenant-b", now)
    with pytest.raises(ValueError, match="RATE_LIMITED"):
        _reserve(path, "tenant-c", now)
    _reserve(path, "tenant-c", now + timedelta(seconds=2))
    with pytest.raises(ValueError, match="QUOTA_CLOCK_INVALID"):
        _reserve(path, "tenant-a", now - timedelta(seconds=5))
    assert path.stat().st_mode & 0o777 == 0o600


def test_concurrent_quota_reservations_cannot_exceed_shared_burst(tmp_path):
    path = tmp_path / "quota.sqlite"
    now = datetime(2026, 10, 29, tzinfo=UTC)

    def attempt(index):
        try:
            _reserve(path, f"tenant-{index}", now)
            return True
        except (ValueError, OSError):
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(attempt, range(10)))
    assert sum(results) == 2


def test_tenant_hourly_quota_does_not_block_another_tenant(tmp_path):
    path = tmp_path / "quota.sqlite"
    now = datetime(2026, 10, 29, tzinfo=UTC)
    for index in range(120):
        _reserve(path, "tenant-a", now + timedelta(seconds=index * 2))
    with pytest.raises(ValueError, match="RATE_LIMITED"):
        _reserve(path, "tenant-a", now + timedelta(seconds=241))
    _reserve(path, "tenant-b", now + timedelta(seconds=241))


def test_secret_and_quota_refuse_symlinks_or_open_permissions(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("test-only-secret")
    secret.chmod(0o600)
    assert _secret(secret) == "test-only-secret"
    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises(OSError):
        _secret(link)
    secret.chmod(0o644)
    with pytest.raises(ValueError, match="SECRET_PERMISSIONS_INVALID"):
        _secret(secret)
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="QUOTA_DIRECTORY_INVALID"):
        _reserve(tmp_path / "quota", "tenant", datetime.now(UTC))


def test_router_authentication_and_source_failure_are_explicit(monkeypatch):
    from procurement.api import gosplan_search as module

    async def auth(authorization: str = Header(default="")):
        if authorization != "Bearer good":
            raise HTTPException(401)
        return Principal(company_id="tenant-a", actor_id="actor", access_role=AccessRole.OPERATOR)

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

    monkeypatch.setattr(module, "_run", run)
    app = FastAPI()
    app.include_router(gosplan_search_router(auth))
    with TestClient(app) as client:
        assert (
            client.get("/v1/tender-discovery/gosplan/search?law=44&query=бумага").status_code == 401
        )
        response = client.get(
            "/v1/tender-discovery/gosplan/search?law=44&query=бумага",
            headers={"Authorization": "Bearer good"},
        )
        assert response.status_code == 200 and response.json()["coverage"] == "UNKNOWN"
        assert response.headers["cache-control"] == "no-store"
        assert seen == ["tenant-a"]
        monkeypatch.setattr(
            module, "_run", lambda *args: (_ for _ in ()).throw(ValueError("RATE_LIMITED"))
        )
        response = client.get(
            "/v1/tender-discovery/gosplan/search?law=44&query=бумага",
            headers={"Authorization": "Bearer good"},
        )
        assert response.status_code == 429 and response.headers["cache-control"] == "no-store"


def test_discovery_runtime_exposes_authorized_search(monkeypatch):
    from procurement.api import gosplan_search as module
    from procurement.api.discovery_runtime import create_discovery_app

    monkeypatch.setenv("EIS_PILOT_TOKEN", "p" * 32)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        module,
        "_run",
        lambda company, law, query, number, offset: SearchPage(
            law=law,
            query=query,
            observed_at=datetime.now(UTC),
            response_sha256="a" * 64,
            items=(),
            may_have_more=False,
        ),
    )
    with TestClient(create_discovery_app()) as client:
        path = "/v1/tender-discovery/gosplan/search?law=44&query=test"
        assert client.get(path).status_code == 401
        result = client.get(path, headers={"Authorization": "Bearer " + "p" * 32})
        assert result.status_code == 200
        assert result.json()["coverage"] == "UNKNOWN"


@pytest.mark.parametrize("law", ["44", "223"])
def test_upstream_503_is_safely_reported_without_response_or_key(monkeypatch, law):
    from procurement.api import gosplan_search as module
    from procurement.sources.gosplan_search import search_page

    async def auth():
        return Principal(company_id="tenant-a", actor_id="actor", access_role=AccessRole.OPERATOR)

    def fake_upstream(request):
        assert request.headers["apikey"] == "synthetic-secret"
        return httpx.Response(503, text="synthetic-secret private upstream error")

    def run(company, selected_law, query, number, offset):
        with httpx.Client(transport=httpx.MockTransport(fake_upstream)) as client:
            return search_page(
                client,
                "synthetic-secret",
                selected_law,
                query=query,
                offset=offset,
                now=datetime.now(UTC),
            )

    monkeypatch.setattr(module, "_run", run)
    app = FastAPI()
    app.include_router(gosplan_search_router(auth))
    with TestClient(app) as client:
        response = client.get(f"/v1/tender-discovery/gosplan/search?law={law}&query=paper")
    assert response.status_code == 503
    assert response.json() == {"detail": "gosplan_source_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-secret" not in response.text


@pytest.mark.parametrize("law", ["44", "223"])
def test_search_api_rejects_offset_over_provider_limit_before_run(monkeypatch, law):
    from procurement.api import gosplan_search as module

    async def auth():
        return Principal(company_id="tenant-a", actor_id="actor", access_role=AccessRole.OPERATOR)

    seen = []

    def run(company, law, query, number, offset):
        seen.append(offset)
        return SearchPage(
            law=law,
            query=query,
            observed_at=datetime.now(UTC),
            response_sha256="a" * 64,
            items=(),
            may_have_more=False,
        )

    monkeypatch.setattr(module, "_run", run)
    app = FastAPI()
    app.include_router(gosplan_search_router(auth))
    with TestClient(app) as client:
        path = f"/v1/tender-discovery/gosplan/search?law={law}&query=test"
        assert client.get(path + "&offset=1000").status_code == 200
        assert client.get(path + "&offset=1001").status_code == 422
    assert seen == [1000]
