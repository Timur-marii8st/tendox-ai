"""Saved profile selection + saved case: real PostgreSQL/RLS and bearer authentication."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

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
from procurement.storage.company_profile import save_profile, select_profile
from procurement.storage.repository import ApiKeyRecord, PostgresStorage, api_key_digest


@pytest.mark.parametrize("runtime_factory", ["business", "discovery"])
def test_saved_profile_case_comparison_real_pg(monkeypatch, runtime_factory, tmp_path):
    custom_runtime = os.environ.get("COMPARISON_TEST_DATABASE_URL")
    custom_owner = os.environ.get("COMPARISON_TEST_DATABASE_ADMIN_URL")
    if custom_runtime or custom_owner:
        assert custom_runtime and custom_owner, "both isolated comparison URLs are required"
        runtime_url, owner_url = custom_runtime, custom_owner
    else:
        runtime_url = os.environ.get("DATABASE_URL")
        owner_url = os.environ.get("DATABASE_ADMIN_URL")
    if not runtime_url or not owner_url:
        pytest.skip("isolated comparison PostgreSQL URLs required")
    runtime_target, owner_target = make_url(runtime_url), make_url(owner_url)
    for url in (runtime_target, owner_target):
        assert url.host in {"localhost", "127.0.0.1", "::1"} and url.port is not None
        assert url.drivername in {"postgresql", "postgresql+psycopg"} and not url.query
        assert url.database in {"procurement_comparison_test", "procurement_eis_test_20261005_s209"}
    assert (runtime_target.host, runtime_target.port, runtime_target.database) == (
        owner_target.host,
        owner_target.port,
        owner_target.database,
    )
    assert runtime_target.username == "procurement_app"
    assert owner_target.username in {"procurement_owner", "postgres"}
    assert runtime_target.username != owner_target.username
    runtime, owner = create_engine(runtime_url), create_engine(owner_url)
    storage, admin = PostgresStorage(runtime), PostgresStorage(owner)
    company, foreign = f"comparison-{uuid4()}", f"foreign-{uuid4()}"
    credentials = {"operator": str(uuid4()), "foreign": str(uuid4()), "auditor": str(uuid4())}
    for actor, secret in credentials.items():
        admin.register_api_key(
            ApiKeyRecord(
                key_id=str(uuid4()),
                company_id=foreign if actor == "foreign" else company,
                actor_id=actor,
                key_digest=api_key_digest(secret),
                access_role=AccessRole.AUDITOR if actor == "auditor" else AccessRole.OPERATOR,
            )
        )
    first = save_profile(
        storage,
        company,
        "operator",
        AccessRole.OPERATOR,
        ProfileSaveCommand(expected_version=0, changes={}),
        str(uuid4()),
    )
    selection = select_profile(
        storage,
        company,
        "operator",
        AccessRole.OPERATOR,
        ProfileSelectionCommand(version=1, snapshot_sha256=first.snapshot_sha256),
        str(uuid4()),
    )
    save_profile(
        storage,
        company,
        "operator",
        AccessRole.OPERATOR,
        ProfileSaveCommand(
            expected_version=1,
            changes={"identity.name": ProfileFactInput(knowledge="KNOWN", value="New profile")},
        ),
        str(uuid4()),
    )
    cases = []
    for number in range(2):
        original = paper_case_at(datetime.now(UTC))
        case = original.model_copy(
            update={
                "company_id": company,
                "case_id": f"case-{number}",
                "selected_quote": None,
                "profile": original.profile.model_copy(update={"company_id": company}),
            }
        )
        storage.save_case(company, case)
        cases.append(case)
    if runtime_factory == "discovery":
        from procurement.api.discovery_runtime import create_discovery_app

        pilot_token = "synthetic-pilot-credential-00000000"
        # Even an accidentally registered pilot secret must not become personal access.
        admin.register_api_key(
            ApiKeyRecord(
                key_id=str(uuid4()),
                company_id=company,
                actor_id="pilot-collision",
                key_digest=api_key_digest(pilot_token),
                access_role=AccessRole.OPERATOR,
            )
        )
        monkeypatch.setenv("DATABASE_URL", runtime_url)
        monkeypatch.setenv("EIS_PILOT_TOKEN", pilot_token)
        monkeypatch.setenv("EIS_DISCOVERY_DB", str(tmp_path / "discovery.sqlite3"))
        app = create_discovery_app()
    else:
        app = create_app(
            PostgresCaseService(storage), PostgresAuthenticator(storage), profile_storage=storage
        )
    with TestClient(app) as client:
        path = "/v1/procurement-comparison"
        headers = {"Authorization": f"Bearer {credentials['operator']}"}
        assert client.get(path + "/catalog").status_code == 401
        if runtime_factory == "discovery":
            pilot_headers = {"Authorization": "Bearer " + pilot_token}
            for personal_path in ("/v1/company-profile", path + "/catalog"):
                denied = client.get(personal_path, headers=pilot_headers)
                assert denied.status_code == 401
                assert denied.headers["cache-control"] == "no-store"
            assert client.get("/v1/cases", headers=headers).status_code == 404
            assert client.get("/v1/tender-discovery/runs", headers=pilot_headers).status_code == 200
            assert client.get("/v1/tender-discovery/runs", headers=headers).status_code == 200
            profile = client.get("/v1/company-profile", headers=headers)
            assert profile.status_code == 200, profile.text
            assert profile.json()["company_id"] == company
        catalog = client.get(path + "/catalog", headers=headers)
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["profiles"][0]["ref"]["version"] == 1
        command = {
            "selection_id": selection.selection_id,
            "profile_ref": {"version": 1, "snapshot_sha256": first.snapshot_sha256},
            "case_refs": [
                {
                    "case_id": case.case_id,
                    "version": case.version,
                    "input_sha256": case_input_digest(case),
                }
                for case in cases
            ],
        }
        report = client.post(path, json=command, headers=headers)
        assert report.status_code == 200, report.text
        assert report.json()["profile_ref"]["version"] == 1
        assert report.json()["persistence"] == "EPHEMERAL"
        assert all(not row["economics"] for row in report.json()["rows"])
        assert (
            client.post(
                path, json=command, headers={"Authorization": f"Bearer {credentials['foreign']}"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                path, json=command, headers={"Authorization": f"Bearer {credentials['auditor']}"}
            ).status_code
            == 403
        )
        command["case_refs"][0]["input_sha256"] = "0" * 64
        assert client.post(path, json=command, headers=headers).status_code == 409
    runtime.dispose()
    owner.dispose()
