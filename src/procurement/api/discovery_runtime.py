"""Local-only API runtime with an optional EIS read index.

The pilot token serves discovery only. Personal PostgreSQL operators can read their
tenant's discovery index and separately authorize profiles/comparisons.
"""

import os
import secrets
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine
from starlette.responses import JSONResponse
from starlette.routing import compile_path

from procurement.access import AccessRole
from procurement.api.app import create_app
from procurement.api.company_profile import company_profile_router
from procurement.api.comparison import comparison_router
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.api.postgres import PostgresAuthenticator
from procurement.storage.repository import PostgresStorage

EIS_PILOT_TOKEN_ENV = "EIS_PILOT_TOKEN"
EIS_PILOT_COMPANY_ENV = "EIS_PILOT_COMPANY"
_MIN_TOKEN_LENGTH = 32
_SAFE_ROUTE_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect"})
_PERSONAL_READ_GETS = tuple(
    compile_path("/v1/tender-discovery/" + path)[0]
    for path in (
        "runs",
        "runs/{run_id}",
        "runs/{run_id}/artifacts/{digest}",
        "gosplan/search",
        "gosplan/detail/{law}/{number}",
        "eis-index",
        "eis-protocols",
        "eis-223-index",
        "eis-223-coverage",
        "eis-223-documents/{number}",
        "eis-refresh-requests/{request_id}",
        "eis-document-jobs/{purchase_number}",
        "eis-document-jobs/{purchase_number}/{content_uid}/analysis",
        "eis-document-jobs/{purchase_number}/evidence",
    )
)
_PERSONAL_READ_POSTS = frozenset(
    {
        "/v1/tender-discovery/eis-public-unit-price/read",
        "/v1/tender-discovery/eis-navigation/read",
        "/v1/tender-discovery/eis-mixed-comparison",
        "/v1/tender-discovery/eis-comparison",
        "/v1/tender-discovery/eis-223-comparison",
    }
)


class _LocalPilotAuthenticator:
    """Keep pilot identity separate from optional personal PostgreSQL operators."""

    def __init__(self, token: str, company_id: str, storage: PostgresStorage | None = None) -> None:
        self._token = token
        self._personal = PostgresAuthenticator(storage) if storage is not None else None
        self._principal = Principal(
            company_id=company_id,
            actor_id="local-eis-operator",
            access_role=AccessRole.OPERATOR,
        )

    async def authenticate(self, credential: str) -> Principal | None:
        if secrets.compare_digest(credential, self._token):
            return self._principal
        if self._personal is not None:
            try:
                principal = await self._personal.authenticate(credential)
            except Exception:
                return None
            if principal is not None and principal.access_role == AccessRole.OPERATOR:
                return principal
        return None


def _pilot_token_from_env() -> str:
    token = os.environ.get(EIS_PILOT_TOKEN_ENV)
    if token is None or len(token) < _MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"{EIS_PILOT_TOKEN_ENV} must contain at least {_MIN_TOKEN_LENGTH} characters"
        )
    return token


def create_discovery_app() -> FastAPI:
    """Build the isolated EIS discovery API with a local bearer token.

    The returned app exposes discovery, personal profile/comparison, health and
    documentation routes. Its placeholder ``CaseService`` is never
    reachable because all routes that could use it are removed.
    """
    token = _pilot_token_from_env()
    company_id = os.environ.get(EIS_PILOT_COMPANY_ENV, "local-eis-supplier")
    if not company_id.strip():
        raise RuntimeError(f"{EIS_PILOT_COMPANY_ENV} must not be blank")
    database_url = os.environ.get("DATABASE_URL")
    engine = create_engine(database_url, pool_pre_ping=True) if database_url else None
    storage = PostgresStorage(engine) if engine is not None else None
    authenticator = cast(Authenticator, _LocalPilotAuthenticator(token, company_id, storage))
    app = create_app(
        cast(CaseService, object()),
        authenticator,
        eis_index_storage=storage,
        eis_number_token=os.environ.get("EIS_GETDOCS_IP_TOKEN"),
    )
    if engine is not None:
        app.state.eis_index_engine = engine
    from procurement.api.supplier_captcha import install_captcha_routes

    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", "").startswith("/v1/tender-discovery/")
        or getattr(route, "path", "") in _SAFE_ROUTE_PATHS
    ]
    install_captcha_routes(app, authenticator, storage)
    personal_authenticator = PostgresAuthenticator(storage) if storage is not None else None
    personal_bearer = HTTPBearer(auto_error=False)

    async def personal_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(personal_bearer)],
    ) -> Principal:
        principal = None
        if (
            credentials is not None
            and credentials.scheme.lower() == "bearer"
            and not secrets.compare_digest(credentials.credentials, token)
            and personal_authenticator is not None
        ):
            try:
                principal = await personal_authenticator.authenticate(credentials.credentials)
            except Exception:
                principal = None
        if principal is None:
            raise HTTPException(
                401,
                "invalid_credentials",
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        return principal

    from procurement.api.beta_procurement import beta_procurement_router

    app.include_router(beta_procurement_router(storage, personal_principal))

    async def indexed_read_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(personal_bearer)],
    ) -> Principal:
        principal = None
        if credentials is not None and credentials.scheme.lower() == "bearer":
            principal = await authenticator.authenticate(credentials.credentials)
        if principal is None:
            raise HTTPException(
                401,
                "invalid_credentials",
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        return principal

    async def gosplan_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(personal_bearer)],
    ) -> Principal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "invalid_credentials", headers={"Cache-Control": "no-store"})
        if secrets.compare_digest(credentials.credentials, token):
            return await indexed_read_principal(credentials)
        return await personal_principal(credentials)

    # Included routers are lazy in the pinned FastAPI. The route allowlist above
    # removes these wrappers; mount cached reads after filtering, like profiles.
    from procurement.api.gosplan_search import gosplan_search_router
    from procurement.api.public_unit_price import public_unit_price_router
    from procurement.api.tender_navigation import tender_navigation_router

    if not any(
        getattr(route, "path", "") == "/v1/tender-discovery/eis-navigation/read"
        for route in app.router.routes
    ):
        app.include_router(tender_navigation_router(storage, indexed_read_principal))
    if not any(
        getattr(route, "path", "") == "/v1/tender-discovery/eis-public-unit-price/read"
        for route in app.router.routes
    ):
        app.include_router(public_unit_price_router(storage, indexed_read_principal))
    app.include_router(gosplan_search_router(gosplan_principal))

    app.include_router(company_profile_router(storage, personal_principal))
    app.include_router(comparison_router(storage, personal_principal))

    @app.middleware("http")
    async def personal_discovery_reads_only(request, call_next):
        # Personal discovery access adds reads, never pilot jobs/source/browser actions.
        if (
            request.url.path.startswith("/v1/tender-discovery/")
            and not (
                request.method in {"GET", "HEAD"}
                and any(pattern.fullmatch(request.url.path) for pattern in _PERSONAL_READ_GETS)
            )
            and not (request.method == "POST" and request.url.path in _PERSONAL_READ_POSTS)
        ):
            authorization = request.headers.get("authorization", "")
            scheme, _, credential = authorization.partition(" ")
            if scheme.lower() != "bearer" or not secrets.compare_digest(credential, token):
                personal = (
                    await authenticator.authenticate(credential)
                    if scheme.lower() == "bearer"
                    else None
                )
                return JSONResponse(
                    {
                        "detail": "discovery_action_requires_pilot"
                        if personal
                        else "invalid_credentials"
                    },
                    status_code=403 if personal else 401,
                    headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
                )
        return await call_next(request)

    return app
