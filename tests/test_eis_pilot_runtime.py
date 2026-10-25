"""Discovery pilot access stays separate from personal business access."""

import asyncio

import httpx
import pytest

from procurement.api.discovery_runtime import EIS_PILOT_TOKEN_ENV, create_discovery_app

TOKEN = "p" * 32


def _request(path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    app = create_discovery_app()

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path, headers=headers)

    return asyncio.run(send())


def test_runtime_refuses_to_start_without_a_long_local_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EIS_PILOT_TOKEN_ENV, raising=False)

    with pytest.raises(RuntimeError, match=EIS_PILOT_TOKEN_ENV):
        create_discovery_app()


def test_discovery_routes_require_the_exact_local_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EIS_PILOT_TOKEN_ENV, TOKEN)

    assert _request("/v1/tender-discovery/runs").status_code == 401
    assert (
        _request("/v1/tender-discovery/runs", {"Authorization": "Bearer " + "x" * 32}).status_code
        == 401
    )


def test_runtime_keeps_only_discovery_and_safe_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EIS_PILOT_TOKEN_ENV, TOKEN)

    assert _request("/health").json() == {"status": "ok"}
    assert _request("/v1/cases").status_code == 404
    app = create_discovery_app()
    # FastAPI can retain a lazy _IncludedRouter without a direct path. Expand
    # API paths through its public schema and retain explicit non-schema routes.
    paths = set(app.openapi()["paths"]) | {
        route.path for route in app.routes if hasattr(route, "path")
    }
    assert all(
        path.startswith(
            (
                "/v1/tender-discovery/",
                "/v1/company-profile",
                "/v1/procurement-comparison",
                "/v1/beta-procurement/",
            )
        )
        or path in {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect"}
        for path in paths
    )


@pytest.mark.parametrize("path", ["/v1/company-profile", "/v1/procurement-comparison/catalog"])
def test_pilot_and_missing_credentials_cannot_access_personal_routes(monkeypatch, path):
    monkeypatch.setenv(EIS_PILOT_TOKEN_ENV, TOKEN)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for headers in (None, {"Authorization": "Bearer " + TOKEN}):
        response = _request(path, headers)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"


def test_pilot_cannot_read_or_save_personal_beta_quotes(monkeypatch):
    monkeypatch.setenv(EIS_PILOT_TOKEN_ENV, TOKEN)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_discovery_app()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ("quote/read", "quote/save", "shortlist"):
                response = await client.post(
                    "/v1/beta-procurement/" + path,
                    json={},
                    headers={"Authorization": "Bearer " + TOKEN},
                )
                assert response.status_code == 401
                assert response.headers["cache-control"] == "no-store"

    asyncio.run(run())
