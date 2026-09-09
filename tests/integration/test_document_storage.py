"""PostgreSQL checks for immutable tenant-scoped source documents."""

from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError

from procurement.storage import (
    DocumentConflict,
    IdempotencyConflict,
    PostgresStorage,
)
from procurement.storage.models import MAX_DOCUMENT_BYTES, documents


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is not set; PostgreSQL integration tests are skipped")
    return value


@pytest.fixture(scope="session", autouse=True)
def migrated_database(database_url: str) -> None:
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if admin_url:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
        command.upgrade(config, "head")


@pytest.fixture(scope="session")
def storage(database_url: str) -> PostgresStorage:
    engine = create_engine(database_url, pool_pre_ping=True)
    yield PostgresStorage(engine)
    engine.dispose()


def _store(
    storage: PostgresStorage,
    tenant: str,
    *,
    key: str,
    digest: str,
    document_id: str | None = None,
):
    return storage.store_document(
        tenant,
        "document-parser",
        "technical-requirements.pdf",
        "application/pdf",
        b"%PDF-1.7 synthetic source",
        {
            "status": "UNKNOWN",
            "reasons": ["OCR_REQUIRED"],
            "source_units_total": 1,
            "source_units_extracted": 0,
            "characters_extracted": 0,
        },
        key,
        digest,
        document_id=document_id,
    )


def test_document_roundtrip_is_tenant_scoped_and_audited(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"

    stored = _store(storage, tenant, key="document-once", digest="1" * 64)

    assert storage.get_document(tenant, stored.document_id) == stored
    assert storage.get_document(other, stored.document_id) is None
    assert stored.byte_size == len(stored.content)
    assert stored.sha256 == hashlib.sha256(stored.content).hexdigest()
    events = storage.list_audit_events(
        tenant,
        object_type="source_document",
        object_id=stored.document_id,
    )
    assert len(events) == 1
    assert events[0].event_type == "document.stored"
    assert events[0].actor_id == "document-parser"
    assert events[0].basis["sha256"] == stored.sha256
    assert storage.list_audit_events(
        other,
        object_type="source_document",
        object_id=stored.document_id,
    ) == []


def test_document_idempotency_replays_and_rejects_digest_or_identity_reuse(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    document_id = f"document-{uuid.uuid4()}"
    first = _store(
        storage,
        tenant,
        key="same-upload",
        digest="2" * 64,
        document_id=document_id,
    )

    replay = _store(storage, tenant, key="same-upload", digest="2" * 64)
    assert replay == first
    with pytest.raises(IdempotencyConflict):
        _store(storage, tenant, key="same-upload", digest="3" * 64)
    with pytest.raises(DocumentConflict):
        _store(
            storage,
            tenant,
            key="another-upload",
            digest="4" * 64,
            document_id=document_id,
        )


def test_same_document_request_is_serialized_under_concurrency(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"

    def save() -> object:
        return _store(storage, tenant, key="concurrent-document", digest="5" * 64)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda _: save(), range(2))

    assert first == second
    with storage.transaction(tenant) as connection:
        count = connection.execute(select(func.count()).select_from(documents)).scalar_one()
    assert count == 1


def test_document_rows_are_append_only_and_hidden_by_rls(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    stored = _store(storage, tenant, key="immutable-document", digest="6" * 64)

    with storage.transaction(other) as connection:
        assert connection.execute(select(func.count()).select_from(documents)).scalar_one() == 0
        assert connection.execute(
            select(documents.c.document_id).where(
                documents.c.document_id == stored.document_id
            )
        ).scalar_one_or_none() is None
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            documents.update()
            .where(documents.c.document_id == stored.document_id)
            .values(original_filename="tampered.pdf")
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            documents.delete().where(documents.c.document_id == stored.document_id)
        )


def test_document_size_and_json_envelope_are_validated(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    common = {
        "company_id": tenant,
        "actor_id": "parser",
        "original_filename": "source.pdf",
        "media_type": "application/pdf",
        "extraction": {"status": "UNKNOWN", "segments": []},
        "idempotency_key": "invalid-size",
        "request_sha256": "7" * 64,
    }
    with pytest.raises(ValueError, match="must not be empty"):
        storage.store_document(content=b"", **common)
    with pytest.raises(ValueError, match="exceeds"):
        storage.store_document(content=b"x" * (MAX_DOCUMENT_BYTES + 1), **common)
    with pytest.raises(ValueError, match="typed extraction schema"):
        storage.store_document(
            content=b"valid",
            **(common | {"extraction": {"invalid": {1, 2}}}),
        )


def test_database_rejects_mismatched_declared_size(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            documents.insert().values(
                company_id=tenant,
                document_id=f"invalid-{uuid.uuid4()}",
                original_filename="source.pdf",
                media_type="application/pdf",
                byte_size=99,
                sha256="8" * 64,
                content=b"short",
                extraction={"status": "UNKNOWN"},
            )
        )
