"""Personal profile + exact cached notices, real tenant RLS and no source writes."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from test_eis_document_queue_pg import admit
from test_eis_mixed_comparison_pg import admit223, counts
from test_eis_mixed_comparison_pg import storage as mixed_storage

from procurement.access import AccessRole
from procurement.api.app import create_app
from procurement.api.postgres import PostgresAuthenticator, PostgresCaseService
from procurement.domain.company_profile_snapshot import ProfileSaveCommand, ProfileSelectionCommand
from procurement.storage.company_profile import save_profile, select_profile
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.repository import ApiKeyRecord, PostgresStorage, api_key_digest
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import window


@pytest.mark.parametrize("factory", ["business", "discovery"])
def test_personal_exact_notice_comparison_rls_readonly(storage, monkeypatch, tmp_path, factory):
    company, foreign = "notice-profile-" + uuid4().hex, "foreign-" + uuid4().hex
    owner = create_engine(os.environ["DATABASE_ADMIN_URL"])
    admin = PostgresStorage(owner)
    tokens = {actor: uuid4().hex for actor in ("operator", "foreign", "auditor", "revoked")}
    pilot = "synthetic-notice-pilot-" + uuid4().hex
    for actor, token in {**tokens, "pilot": pilot}.items():
        key_id = uuid4().hex
        admin.register_api_key(
            ApiKeyRecord(
                key_id=key_id,
                company_id=foreign if actor == "foreign" else company,
                actor_id=actor,
                key_digest=api_key_digest(token),
                access_role=AccessRole.AUDITOR if actor == "auditor" else AccessRole.OPERATOR,
            )
        )
        if actor == "revoked":
            assert admin.set_api_key_enabled(company, key_id, enabled=False)
    profile = save_profile(
        storage,
        company,
        "operator",
        AccessRole.OPERATOR,
        ProfileSaveCommand(expected_version=0, changes={}),
        uuid4().hex,
    )
    selection = select_profile(
        storage,
        company,
        "operator",
        AccessRole.OPERATOR,
        ProfileSelectionCommand(version=1, snapshot_sha256=profile.snapshot_sha256),
        uuid4().hex,
    )
    ref44 = admit(storage, company, 0, listed=False, deadline="2020-01-01T10:00:00Z")
    ref223 = admit223(storage, company, xml(deadline="2020-01-01T10:00:00+03:00"))
    extra = window(
        zip_bytes(
            [
                (
                    f"notice-{index}.xml",
                    xml().replace(b"32600000001", f"3260000000{index}".encode()),
                )
                for index in range(2, 6)
            ]
        )
    )
    extra = extra.model_copy(update={"window_key": extra.window_key.replace("/50/", "/51/")})
    assert "/51/" in extra.window_key
    ingest_notice223_window(storage, company, extra, actor_id="test")
    five = [
        {
            "law": "223",
            "purchase_number": lead.notice.purchase_number,
            "version_number": lead.notice.version_number,
            "notice_xml_sha256": lead.notice.xml_sha256,
        }
        for lead in search_notice223_index(storage, company, "бумага").matched
    ]
    assert len(five) == 5
    body = {
        "selection_id": selection.selection_id,
        "profile_ref": {"version": 1, "snapshot_sha256": profile.snapshot_sha256},
        "notices": [{"law": "44", **ref44.model_dump()}, {"law": "223", **ref223.model_dump()}],
    }
    if factory == "discovery":
        from procurement.api.discovery_runtime import create_discovery_app

        monkeypatch.setenv("EIS_PILOT_TOKEN", pilot)
        monkeypatch.setenv("EIS_DISCOVERY_DB", str(tmp_path / "discovery.sqlite"))
        app = create_discovery_app()
    else:
        app = create_app(
            PostgresCaseService(storage), PostgresAuthenticator(storage), profile_storage=storage
        )
    before = counts(storage, company)
    path = "/v1/procurement-comparison/notices"
    with TestClient(app) as client:

        def send(payload=body, actor="operator"):
            return client.post(
                path, json=payload, headers={"Authorization": "Bearer " + tokens[actor]}
            )

        assert client.post(path, json=body).status_code == 401
        if factory == "discovery":
            assert (
                client.post(
                    path, json=body, headers={"Authorization": "Bearer " + pilot}
                ).status_code
                == 401
            )
        if factory == "discovery":
            search_path = "/v1/tender-discovery/eis-223-index?query=бумага"

            def search(actor):
                return client.get(search_path, headers={"Authorization": "Bearer " + tokens[actor]})

            personal_result = search("operator")
            assert personal_result.status_code == 200, personal_result.text
            assert any(
                r["notice"]["purchase_number"] == ref223.purchase_number
                for r in personal_result.json()["matched"]
            )
            foreign_result = search("foreign")
            assert foreign_result.status_code == 200 and foreign_result.json()["matched"] == []
            assert search("auditor").status_code == search("revoked").status_code == 401
            assert (
                client.get(
                    search_path, headers={"Authorization": "Bearer invalid-personal"}
                ).status_code
                == 401
            )
            assert (
                client.get(search_path, headers={"Authorization": "Bearer " + pilot}).status_code
                == 200
            )
            personal_headers = {"Authorization": "Bearer " + tokens["operator"]}

            def forbidden_source(*args, **kwargs):
                pytest.fail("personal discovery must not invoke external source")

            monkeypatch.setattr("procurement.api.app.search_public_eis", forbidden_source)
            assert (
                client.get(
                    "/v1/tender-discovery/eis-live?query=бумага", headers=personal_headers
                ).status_code
                == 403
            )
            readonly = client.post(
                "/v1/tender-discovery/eis-mixed-comparison",
                json={"notices": body["notices"]},
                headers=personal_headers,
            )
            assert readonly.status_code == 200, readonly.text
            assert (
                client.post(
                    "/v1/tender-discovery/eis-223-document-jobs",
                    json=ref223.model_dump(),
                    headers=personal_headers,
                ).status_code
                == 403
            )
        assert send(actor="auditor").status_code == 403
        assert send(actor="foreign").status_code == 404
        response = send()
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        five_response = send({**body, "notices": five})
        assert five_response.status_code == 200, five_response.text
        five_report = five_response.json()
        assert len(five_report["rows"]) == 5
        assert [r["notice_ref"] for r in five_report["rows"]] == five
        assert any(link["right_row"] == 4 for link in five_report["source"]["position_links"])
        assert len(five_report["source"]["position_links"]) <= 24
        assert all(
            link["equivalence"] == link["price_comparability"] == "UNKNOWN"
            for link in five_report["source"]["position_links"]
        )
        report = response.json()
        assert report["profile_ref"] == body["profile_ref"]
        assert [r["notice_ref"]["law"] for r in report["rows"]] == ["44", "223"]
        for row in report["rows"]:
            assert row["overall_status"] == "FAIL"
            checks = {c["check_id"]: c for c in row["checks"]}
            assert checks["submission"]["status"] == "FAIL"
            assert checks["economics"]["status"] == "UNKNOWN"
        assert (
            send({**body, "profile_ref": {"version": 1, "snapshot_sha256": "f" * 64}}).status_code
            == 409
        )
        assert send({**body, "selection_id": str(uuid4())}).status_code == 404
        conflict = {**body, "notices": [dict(ref) for ref in body["notices"]]}
        conflict["notices"][1]["notice_xml_sha256"] = "f" * 64
        assert send(conflict).status_code == 409
        missing = {**body, "notices": [dict(ref) for ref in body["notices"]]}
        missing["notices"][1]["purchase_number"] = "39999999999"
        assert send(missing).status_code == 404
    assert counts(storage, company) == before
    owner.dispose()


@pytest.fixture(scope="module")
def storage():
    yield from mixed_storage.__wrapped__()
