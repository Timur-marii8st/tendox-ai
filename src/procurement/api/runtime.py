"""Environment-based ASGI application factory."""

from __future__ import annotations

import os

from fastapi import FastAPI
from sqlalchemy import create_engine

from procurement.api.app import create_app
from procurement.api.postgres import PostgresAuthenticator, PostgresCaseService
from procurement.documents.ai_transfer_keys import local_pilot_tenant_kek_provider_from_env
from procurement.documents.paddle_ocr import PaddleOcrRunner
from procurement.storage import PostgresStorage


def create_runtime_app() -> FastAPI:
    """Build the API from ``DATABASE_URL`` without module-level DB connections."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(database_url, pool_pre_ping=True)
    storage = PostgresStorage(
        engine,
        raw_key_provider=local_pilot_tenant_kek_provider_from_env(),
    )
    return create_app(
        PostgresCaseService(storage),
        PostgresAuthenticator(storage),
        ocr_runner=PaddleOcrRunner(),
        eis_index_storage=storage,
        eis_number_token=os.environ.get("EIS_GETDOCS_IP_TOKEN"),
        profile_storage=storage,
    )
