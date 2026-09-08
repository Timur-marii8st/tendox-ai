"""Environment-based ASGI application factory."""

from __future__ import annotations

import os

from fastapi import FastAPI
from sqlalchemy import create_engine

from procurement.api.app import create_app
from procurement.api.postgres import PostgresAuthenticator, PostgresCaseService
from procurement.storage import PostgresStorage


def create_runtime_app() -> FastAPI:
    """Build the API from ``DATABASE_URL`` without module-level DB connections."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(database_url, pool_pre_ping=True)
    storage = PostgresStorage(engine)
    return create_app(PostgresCaseService(storage), PostgresAuthenticator(storage))
