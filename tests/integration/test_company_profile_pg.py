"""Реальный PostgreSQL/runtime RLS и HTTP путь самостоятельного профиля."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from case_support import paper_case_at
from procurement.access import AccessRole
from procurement.api.app import create_app
from procurement.api.postgres import PostgresAuthenticator, PostgresCaseService
from procurement.domain.cases import case_input_digest
from procurement.domain.company_profile_snapshot import (
    ProfileFactInput,
    ProfileSaveCommand,
    ProfileSelectionCommand,
)
from procurement.storage.company_profile import (
    ProfileConflict,
    ProfileForbidden,
    read_profile,
    read_selection,
    save_profile,
    select_profile,
)
from procurement.storage.company_profile_schema import (
    company_profile_selections,
    company_profile_versions,
)
from procurement.storage.models import audit_events
from procurement.storage.repository import (
    ApiKeyRecord,
    IdempotencyConflict,
    PostgresStorage,
    api_key_digest,
)


@pytest.fixture(scope="module")
def stores():
    app_url, admin_url = os.environ.get("DATABASE_URL"), os.environ.get("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL URLs required")
    runtime, owner = make_url(app_url), make_url(admin_url)
    for url in (runtime, owner):
        assert url.host in {"127.0.0.1", "localhost", "::1"} and url.port is not None
        assert url.drivername in {"postgresql", "postgresql+psycopg"} and not url.query
        assert url.database in {"procurement_profile_test", "procurement_eis_test_20261005_s209"}
    assert (runtime.host, runtime.port, runtime.database) == (
        owner.host,
        owner.port,
        owner.database,
    )
    assert runtime.username == "procurement_app" and owner.username == "procurement_owner"
    app, admin = create_engine(app_url), create_engine(admin_url)
    yield PostgresStorage(app), PostgresStorage(admin)
    app.dispose()
    admin.dispose()


def command(version=0, **changes):
    return ProfileSaveCommand(
        expected_version=version,
        changes={
            path: ProfileFactInput(knowledge="KNOWN", value=value)
            for path, value in changes.items()
        },
    )


def tenant():
    return f"profile-test-{uuid.uuid4()}"


def test_partial_real_roundtrip_source_precision_and_old_version(stores):
    storage, _ = stores
    company = tenant()
    first = save_profile(
        storage,
        company,
        "synthetic-operator",
        AccessRole.OPERATOR,
        command(
            **{
                "identity.name": "ООО Пример",
                "geography.max_distance_km": "123456789.67",
                "geography.all_russia": False,
                "supplied_goods": (),
            }
        ),
        str(uuid.uuid4()),
    )
    reloaded = read_profile(storage, company)
    assert reloaded == first
    assert reloaded.facts["finance.min_contract_amount"].knowledge == "UNKNOWN"
    assert reloaded.facts["geography.max_distance_km"].value == "123456789.67"
    assert reloaded.facts["geography.all_russia"].value is False
    assert reloaded.facts["supplied_goods"].value == ()
    second = save_profile(
        storage,
        company,
        "synthetic-operator",
        AccessRole.OPERATOR,
        command(1, **{"identity.name": "ООО Обновлённый пример"}),
        str(uuid.uuid4()),
    )
    assert second.version == 2
    assert read_profile(storage, company, 1) == first
    assert (
        second.facts["geography.max_distance_km"].sources
        == first.facts["geography.max_distance_km"].sources
    )
    assert second.facts["identity.name"].sources != first.facts["identity.name"].sources


def test_retry_noop_and_conflict_atomic_audit(stores):
    storage, _ = stores
    company, key = tenant(), str(uuid.uuid4())
    cmd = command(**{"identity.name": "Пример"})
    first = save_profile(storage, company, "a", AccessRole.OPERATOR, cmd, key)
    assert save_profile(storage, company, "a", AccessRole.OPERATOR, cmd, key) == first
    with pytest.raises(IdempotencyConflict):
        save_profile(storage, company, "b", AccessRole.OPERATOR, cmd, key)
    noop = save_profile(
        storage,
        company,
        "a",
        AccessRole.OPERATOR,
        command(1, **{"identity.name": "Пример"}),
        str(uuid.uuid4()),
    )
    assert noop == first
    with pytest.raises(ProfileConflict):
        save_profile(storage, company, "a", AccessRole.OPERATOR, command(0), str(uuid.uuid4()))
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(company_profile_versions)) == 1
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.object_type == "COMPANY_PROFILE")
            )
            == 1
        )


def test_concurrent_edits_have_one_winner(stores):
    storage, _ = stores
    company = tenant()
    save_profile(storage, company, "a", AccessRole.OPERATOR, command(), str(uuid.uuid4()))

    def update(name):
        try:
            return save_profile(
                storage,
                company,
                name,
                AccessRole.OPERATOR,
                command(1, **{"identity.name": name}),
                str(uuid.uuid4()),
            ).version
        except ProfileConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ["first", "second"]), key=str) == [2, "conflict"]
    assert read_profile(storage, company).version == 2


def test_selection_pins_previous_version_and_is_idempotent(stores):
    storage, _ = stores
    company, key = tenant(), str(uuid.uuid4())
    first = save_profile(storage, company, "a", AccessRole.OPERATOR, command(), str(uuid.uuid4()))
    selection_command = ProfileSelectionCommand(version=1, snapshot_sha256=first.snapshot_sha256)
    selected = select_profile(storage, company, "a", AccessRole.OPERATOR, selection_command, key)
    save_profile(
        storage,
        company,
        "a",
        AccessRole.OPERATOR,
        command(1, **{"identity.name": "Новое название"}),
        str(uuid.uuid4()),
    )
    assert read_selection(storage, company).profile_ref.version == 1
    assert read_selection(storage, company, selected.selection_id) == selected
    assert (
        select_profile(storage, company, "a", AccessRole.OPERATOR, selection_command, key)
        == selected
    )
    with pytest.raises(ProfileConflict):
        select_profile(
            storage,
            company,
            "a",
            AccessRole.OPERATOR,
            ProfileSelectionCommand(version=1, snapshot_sha256="0" * 64),
            str(uuid.uuid4()),
        )


@pytest.mark.parametrize(
    "role", [role for role in AccessRole if role is not AccessRole.COMPANY_PROFILE_OWNER]
)
def test_existing_roles_never_apply_critical_settings(stores, role):
    storage, _ = stores
    with pytest.raises(ProfileForbidden):
        save_profile(
            storage,
            tenant(),
            "a",
            role,
            command(**{"finance.min_contract_amount": "0"}),
            str(uuid.uuid4()),
        )


def test_owner_critical_save_requires_exact_tenant_actor_version_and_value_confirmation(stores):
    storage, _ = stores
    company, actor = tenant(), "owner-a"
    first = command(**{"finance.min_contract_amount": "0"})
    confirmed = first.model_copy(
        update={"confirmation_sha256": first.confirmation_digest(company, actor)}
    )
    saved = save_profile(
        storage, company, actor, AccessRole.COMPANY_PROFILE_OWNER, confirmed, str(uuid.uuid4())
    )
    assert saved.critical_settings_status == "OWNER_AUTHORIZED"
    assert saved.policy_confirmation is not None
    assert saved.policy_confirmation.confirmed_by == actor
    with pytest.raises(ProfileForbidden):
        save_profile(
            storage,
            company,
            actor,
            AccessRole.COMPANY_PROFILE_OWNER,
            command(1, **{"finance.min_contract_amount": "1"}).model_copy(
                update={"confirmation_sha256": confirmed.confirmation_sha256}
            ),
            str(uuid.uuid4()),
        )
    with storage.transaction(company) as conn:
        audit = conn.execute(
            select(audit_events.c.basis).where(audit_events.c.event_id == saved.audit_event_id)
        ).scalar_one()
    assert audit["critical_settings_applied"] is True
    assert audit["policy_confirmation"]["confirmation_sha256"] == confirmed.confirmation_sha256
    later = save_profile(
        storage,
        company,
        "operator-b",
        AccessRole.OPERATOR,
        command(1, **{"identity.name": "Обычная правка"}),
        str(uuid.uuid4()),
    )
    assert later.created_by == "operator-b"
    assert later.policy_confirmation is not None
    assert later.policy_confirmation.confirmed_by == actor
    assert read_profile(storage, company, later.version) == later


def test_runtime_rls_and_immutable_history(stores):
    storage, _ = stores
    company, foreign = tenant(), tenant()
    first = save_profile(storage, company, "a", AccessRole.OPERATOR, command(), str(uuid.uuid4()))
    selected = select_profile(
        storage,
        company,
        "a",
        AccessRole.OPERATOR,
        ProfileSelectionCommand(version=1, snapshot_sha256=first.snapshot_sha256),
        str(uuid.uuid4()),
    )
    with storage.transaction(foreign) as conn:
        assert conn.scalar(select(func.count()).select_from(company_profile_versions)) == 0
        assert conn.scalar(select(func.count()).select_from(company_profile_selections)) == 0
        assert (
            conn.scalar(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user"))
            is False
        )
    with pytest.raises(DBAPIError), storage.transaction(foreign) as conn:
        # Exact source row is read in its own tenant and inserted under a foreign context.
        with storage.transaction(company) as source_conn:
            row = source_conn.execute(select(company_profile_selections)).mappings().one()
        conn.execute(company_profile_selections.insert().values(dict(row)))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(company_profile_versions.update().values(created_by="changed"))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            company_profile_selections.delete().where(
                company_profile_selections.c.selection_id == selected.selection_id
            )
        )


def test_existing_case_profile_and_digest_are_unchanged(stores):
    storage, _ = stores
    original = paper_case_at(datetime.now(UTC))
    company = original.company_id
    payload = original.model_dump(mode="python")
    payload["case_id"] = str(uuid.uuid4())
    original = type(original).model_validate(payload)
    before = case_input_digest(original)
    storage.save_case(company, original)
    previous = None
    with suppress(LookupError):
        previous = read_profile(storage, company)
    save_profile(
        storage,
        company,
        "a",
        AccessRole.OPERATOR,
        command(previous.version if previous else 0, **{"identity.name": str(uuid.uuid4())}),
        str(uuid.uuid4()),
    )
    restored = storage.get_case(company, original.case_id, original.version)
    assert restored == original and case_input_digest(restored) == before


def test_http_end_to_end_and_authentication(stores):
    storage, admin = stores
    company, foreign = tenant(), tenant()
    secrets = {"a": str(uuid.uuid4()), "foreign": str(uuid.uuid4()), "auditor": str(uuid.uuid4())}
    for name, secret in secrets.items():
        admin.register_api_key(
            ApiKeyRecord(
                key_id=str(uuid.uuid4()),
                company_id=foreign if name == "foreign" else company,
                actor_id=name,
                key_digest=api_key_digest(secret),
                access_role=AccessRole.AUDITOR if name == "auditor" else AccessRole.OPERATOR,
            )
        )
    app = create_app(
        PostgresCaseService(storage), PostgresAuthenticator(storage), profile_storage=storage
    )
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {secrets['a']}", "Idempotency-Key": str(uuid.uuid4())}
        assert client.get("/v1/company-profile").status_code == 401
        first = client.post(
            "/v1/company-profile/versions",
            json=command(**{"identity.name": "HTTP Пример"}).model_dump(mode="json"),
            headers=headers,
        )
        assert first.status_code == 201, first.text
        assert first.headers["cache-control"] == "no-store"
        first = first.json()
        assert client.get("/v1/company-profile", headers=headers).json() == first
        assert (
            client.get("/v1/company-profile/versions", headers=headers).json()["items"][0][
                "version"
            ]
            == 1
        )
        headers["Idempotency-Key"] = str(uuid.uuid4())
        second = client.post(
            "/v1/company-profile/versions",
            json=command(1, **{"identity.name": "HTTP Новый"}).model_dump(mode="json"),
            headers=headers,
        )
        assert second.status_code == 201
        assert client.get("/v1/company-profile/versions/1", headers=headers).json() == first
        assert (
            client.post(
                "/v1/company-profile/versions",
                json=command(1).model_dump(mode="json"),
                headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            ).status_code
            == 409
        )
        headers["Idempotency-Key"] = str(uuid.uuid4())
        selection = client.post(
            "/v1/company-profile/selections",
            json={"version": 1, "snapshot_sha256": first["snapshot_sha256"]},
            headers=headers,
        )
        assert selection.status_code == 201
        foreign_headers = {"Authorization": f"Bearer {secrets['foreign']}"}
        assert (
            client.get("/v1/company-profile/versions/1", headers=foreign_headers).status_code == 404
        )
        assert (
            client.get(
                f"/v1/company-profile/selections/{selection.json()['selection_id']}",
                headers=foreign_headers,
            ).status_code
            == 404
        )
        assert (
            client.get("/v1/company-profile/versions", headers=foreign_headers).json()["items"]
            == []
        )
        auditor = {**headers, "Authorization": f"Bearer {secrets['auditor']}"}
        assert client.get("/v1/company-profile", headers=auditor).status_code == 200
        assert (
            client.post(
                "/v1/company-profile/versions",
                json=command(2).model_dump(mode="json"),
                headers=auditor,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/company-profile/versions",
                json=command(2, **{"finance.min_contract_amount": "0"}).model_dump(mode="json"),
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/company-profile/versions",
                json={
                    "expected_version": 2,
                    "changes": {
                        "finance.min_contract_amount": {"knowledge": "KNOWN", "value": 0.1}
                    },
                },
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/company-profile/versions",
                json={"expected_version": 2, "company_id": foreign, "changes": {}},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/company-profile/versions",
                content=b"x" * 65537,
                headers={**headers, "Content-Type": "application/json"},
            ).status_code
            == 413
        )
