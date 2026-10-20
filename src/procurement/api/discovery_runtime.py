"""Local-only API runtime with an optional EIS read index.

Business persistence routes stay removed. The optional PostgreSQL index serves
tenant-scoped EIS search and exact-notice document jobs in this pilot.
"""

from __future__ import annotations

import os
import secrets
from typing import cast

from fastapi import FastAPI
from sqlalchemy import create_engine

from procurement.access import AccessRole
from procurement.api.app import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.storage.repository import PostgresStorage

EIS_PILOT_TOKEN_ENV = "EIS_PILOT_TOKEN"
EIS_PILOT_COMPANY_ENV = "EIS_PILOT_COMPANY"
_MIN_TOKEN_LENGTH = 32
_SAFE_ROUTE_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect"})


class _LocalPilotAuthenticator:
    """Authenticate the one local pilot operator without a database."""

    def __init__(self, token: str, company_id: str) -> None:
        self._token = token
        self._principal = Principal(
            company_id=company_id,
            actor_id="local-eis-operator",
            access_role=AccessRole.OPERATOR,
        )

    async def authenticate(self, credential: str) -> Principal | None:
        if not secrets.compare_digest(credential, self._token):
            return None
        return self._principal


def _pilot_token_from_env() -> str:
    token = os.environ.get(EIS_PILOT_TOKEN_ENV)
    if token is None or len(token) < _MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"{EIS_PILOT_TOKEN_ENV} must contain at least {_MIN_TOKEN_LENGTH} characters"
        )
    return token


def create_discovery_app() -> FastAPI:
    """Build the isolated EIS discovery API with a local bearer token.

    The returned app exposes only ``/v1/tender-discovery/*``, ``/health`` and
    FastAPI documentation routes.  Its placeholder ``CaseService`` is never
    reachable because all routes that could use it are removed.
    """
    token = _pilot_token_from_env()
    company_id = os.environ.get(EIS_PILOT_COMPANY_ENV, "local-eis-supplier")
    if not company_id.strip():
        raise RuntimeError(f"{EIS_PILOT_COMPANY_ENV} must not be blank")
    database_url = os.environ.get("DATABASE_URL")
    engine = create_engine(database_url, pool_pre_ping=True) if database_url else None
    authenticator = cast(Authenticator, _LocalPilotAuthenticator(token, company_id))
    storage = PostgresStorage(engine) if engine is not None else None
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
    return app
