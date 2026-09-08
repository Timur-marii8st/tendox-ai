"""PostgreSQL-only integration checks for persistence and tenant isolation."""

from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from case_support import AT, paper_case
from procurement.domain.cases import ProcurementCase, case_input_digest, evaluate_case
from procurement.storage import (
    AuditEventRecord,
    CaseVersionConflict,
    IdempotencyConflict,
    PostgresStorage,
)
from procurement.storage.models import audit_events, case_versions


def _retarget_case(company_id: str, *, case_id: str | None = None) -> ProcurementCase:
    payload = paper_case().model_dump(mode="python")
    payload["company_id"] = company_id
    payload["case_id"] = case_id or f"case-{uuid.uuid4()}"
    payload["profile"]["company_id"] = company_id
    if payload["selected_quote"] is not None:
        payload["selected_quote"]["company_id"] = company_id
    return ProcurementCase.model_validate(payload)


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


def test_case_roundtrip_is_scoped_and_preserves_economics(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)

    storage.save_case(tenant, case)
    restored = storage.get_case(tenant, case.case_id, case.version)

    assert restored == case
    assert restored is not None and restored.scenarios == case.scenarios
    assert storage.get_case(other, case.case_id, case.version) is None
    assert storage.list_case_versions(other, case.case_id) == []
    assert storage.list_cases(other).items == ()


def test_case_versions_are_immutable_and_exact_replay_is_idempotent(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    assert storage.save_case(tenant, case) == case

    changed = case.model_copy(update={"nmck_ex_vat": case.nmck_ex_vat + 1})
    with pytest.raises(CaseVersionConflict):
        storage.save_case(tenant, changed)


def test_strict_create_replays_only_the_same_idempotency_request(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    digest = "1" * 64
    storage.save_case(
        tenant,
        case,
        idempotency_key="create-one",
        request_sha256=digest,
    )
    assert (
        storage.save_case(
            tenant,
            case,
            idempotency_key="create-one",
            request_sha256=digest,
        )
        == case
    )
    with pytest.raises(IdempotencyConflict):
        storage.save_case(
            tenant,
            case,
            idempotency_key="create-one",
            request_sha256="2" * 64,
        )
    with pytest.raises(CaseVersionConflict):
        storage.save_case(
            tenant,
            case,
            idempotency_key="create-two",
            request_sha256=digest,
        )


def test_same_idempotent_create_is_serialized_under_concurrency(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)

    def save() -> ProcurementCase:
        return storage.save_case(
            tenant,
            case,
            idempotency_key="concurrent-create",
            request_sha256="3" * 64,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: save(), range(2)))
    assert results == [case, case]


def test_latest_case_list_uses_cursor_and_never_crosses_tenant(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    first = _retarget_case(tenant, case_id="a-case")
    second = _retarget_case(tenant, case_id="b-case")
    storage.save_case(tenant, first)
    storage.save_case(tenant, first.model_copy(update={"version": 2}))
    storage.save_case(tenant, second)
    storage.save_case(other, _retarget_case(other, case_id="secret-case"))

    page_one = storage.list_cases(tenant, limit=1)
    page_two = storage.list_cases(tenant, limit=1, cursor=page_one.next_cursor)

    assert [(item.case_id, item.version) for item in page_one.items] == [("a-case", 2)]
    assert [(item.case_id, item.version) for item in page_two.items] == [("b-case", 1)]
    assert page_two.next_cursor is None


def test_audit_is_tenant_scoped_and_append_only(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    event = AuditEventRecord(
        event_id=f"event-{uuid.uuid4()}",
        company_id=tenant,
        actor_id="tester",
        event_type="case.saved",
        object_type="procurement_case",
        object_id="case-one",
        object_version=1,
        basis={"source": "integration-test"},
        occurred_at=datetime.now(UTC),
    )
    storage.append_audit(event)

    assert storage.list_audit_events(tenant) == [event]
    assert storage.list_audit_events(other) == []
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            audit_events.update()
            .where(audit_events.c.event_id == event.event_id)
            .values(event_type="tampered")
        )


def test_direct_sql_rls_cannot_read_guessed_other_tenant_rows(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    secret = _retarget_case(other)
    storage.save_case(other, secret)

    with storage.transaction(tenant) as connection:
        visible = connection.execute(select(func.count()).select_from(case_versions)).scalar_one()
        guessed = connection.execute(
            select(case_versions.c.payload).where(case_versions.c.case_id == secret.case_id)
        ).scalar_one_or_none()
    assert visible == 0
    assert guessed is None


def test_case_rows_cannot_be_updated_or_deleted(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)

    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            case_versions.update()
            .where(case_versions.c.case_id == case.case_id)
            .values(input_sha256="0" * 64)
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            case_versions.delete().where(case_versions.c.case_id == case.case_id)
        )


def test_evaluation_audit_and_receipt_are_atomic_and_replayable(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    recommendation = evaluate_case(case, at=AT)
    digest = case_input_digest(case)

    first = storage.record_evaluation(
        tenant,
        "reviewer",
        case.case_id,
        case.version,
        AT,
        digest,
        "domain-s1-v1",
        recommendation,
        "evaluate-once",
        "4" * 64,
    )
    replay = storage.record_evaluation(
        tenant,
        "reviewer",
        case.case_id,
        case.version,
        AT,
        digest,
        "domain-s1-v1",
        recommendation,
        "evaluate-once",
        "4" * 64,
    )

    assert replay == first
    assert first.engine_version == "domain-s1-v1"
    events = storage.list_audit_events(
        tenant,
        object_type="procurement_case",
        object_id=case.case_id,
    )
    assert len(events) == 1
    assert events[0].event_id == first.evaluation_id
    assert events[0].occurred_at == first.created_at
    assert events[0].basis["engine_version"] == "domain-s1-v1"


def test_runtime_connection_has_no_unscoped_api_key_read(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(text("SELECT key_digest FROM api_keys"))
    finally:
        engine.dispose()


def test_authentication_resolves_tenant_without_caller_claim(
    storage: PostgresStorage,
    database_url: str,
) -> None:
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if not admin_url:
        pytest.skip("DATABASE_ADMIN_URL is required to provision an authentication fixture")
    secret = f"secret-{uuid.uuid4()}"
    digest = hashlib.sha256(secret.encode()).hexdigest()
    tenant = f"tenant-{uuid.uuid4()}"
    key_id = f"key-{uuid.uuid4()}"
    admin_engine = create_engine(admin_url)
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(key_id, company_id, key_digest, actor_id, enabled) "
                    "VALUES (:key_id, :company_id, :key_digest, 'api-user', true)"
                ),
                {"key_id": key_id, "company_id": tenant, "key_digest": digest},
            )
    finally:
        admin_engine.dispose()

    principal = storage.authenticate_api_key(secret)
    assert principal is not None
    assert principal.company_id == tenant
    assert principal.actor_id == "api-user"
    assert storage.authenticate_api_key(f"wrong-{secret}") is None
