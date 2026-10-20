"""Exact selector API authenticates before reading bounded untrusted JSON."""

import json
from pathlib import Path

import pytest

from procurement.access import AccessRole
from procurement.api import app as api
from procurement.sources.eis_position_association import (
    AssociationDetailRequest,
    AssociationListRequest,
    AssociationListResult,
    AssociationMetadata,
    AssociationReadScope,
    SavedAssociation,
)
from test_eis_supplier_search_api import send as supplier_send

SAVE = "/v1/tender-discovery/eis-position-association/save"
READ = "/v1/tender-discovery/eis-position-association/read"
LIST = "/v1/tender-discovery/eis-position-association/list"
DETAIL = "/v1/tender-discovery/eis-position-association/detail"
FIXTURE = Path(__file__).resolve().parent / "fixtures/eis-position-association.json"


def saved():
    return SavedAssociation.model_validate_json(FIXTURE.read_bytes())


def send(path, body, **kwargs):
    return supplier_send(path, body, **kwargs)


def body():
    return json.dumps({"request": saved().report.request.model_dump(mode="json")}).encode()


def test_save_actor_tenant_and_source0_auditor_read(monkeypatch):
    calls = []

    def save(storage, company, request, *, actor_id):
        calls.append((company, actor_id, request))
        return saved().model_copy(update={"created": True})

    monkeypatch.setattr(api, "save_position_fragment_association", save)
    monkeypatch.setattr(api, "read_position_fragment_association", lambda *args: saved())
    response = send(SAVE, body())
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert calls[0] == ("tenant-a", "actor-a", saved().report.request)
    response = send(READ, body(), role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.json()["created"] is False


@pytest.mark.parametrize(
    "kind",
    ["auth", "role", "extra", "text", "duplicate", "nonfinite", "oversize", "bool", "revision"],
)
def test_invalid_input_never_reads_source_or_writes(monkeypatch, kind):
    calls = []
    monkeypatch.setattr(api, "save_position_fragment_association", lambda *a, **k: calls.append(1))
    payload = json.loads(body())
    raw = body()
    kwargs = {}
    expected = 422
    if kind == "auth":
        kwargs["authorization"] = None
        expected = 401
    elif kind == "role":
        kwargs["role"] = AccessRole.AUDITOR
        expected = 403
    elif kind == "extra":
        payload["company_id"] = "foreign"
    elif kind == "text":
        payload["request"]["fragments"][0]["text"] = "injected"
    elif kind == "duplicate":
        raw = b'{"request":{},"request":{}}'
    elif kind == "nonfinite":
        raw = b'{"request":NaN}'
    elif kind == "oversize":
        raw = b" " * 4097
        expected = 413
    elif kind == "bool":
        payload["request"]["fragments"][0]["character_start"] = True
    else:
        payload["request"]["analyzer_version"] = "eis-native-v3"
    if kind not in {"duplicate", "nonfinite", "oversize"}:
        raw = json.dumps(payload).encode()
    response = send(SAVE, raw, **kwargs)
    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store" and calls == []


@pytest.mark.parametrize(
    "error,status",
    [
        (ValueError("NOTICE_VERSION_STALE"), 409),
        (ValueError("POSITION_ASSOCIATION_BUSY"), 409),
        (LookupError("private dsn"), 404),
        (RuntimeError("private dsn"), 503),
    ],
)
def test_safe_source_errors_never_expose_private_details(monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(api, "read_position_fragment_association", fail)
    response = send(READ, body())
    assert response.status_code == status and response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


def test_foreign_child_result_rejected_and_schema_fully_inline(monkeypatch):
    wrong = saved().model_copy(update={"created": True})
    monkeypatch.setattr(api, "read_position_fragment_association", lambda *a, **k: wrong)
    assert send(READ, body()).status_code == 503
    schema = json.dumps(api.EIS_POSITION_ASSOCIATION_OPENAPI_SCHEMA)
    assert '"$ref"' not in schema and '"$defs"' not in schema


def scope():
    report = saved().report
    return AssociationReadScope(
        position=report.request.position,
        document=report.request.document,
        analyzer_version=report.request.analyzer_version,
    )


def test_list_and_detail_forward_exact_scope_for_auditor(monkeypatch):
    calls = []
    list_request = AssociationListRequest(scope=scope(), limit=20)
    item = AssociationMetadata(
        association_id=saved().report.association_id,
        created_at=saved().report.created_at,
        linked_by=saved().report.linked_by,
        fragment_count=len(saved().report.fragments),
        selected_characters=saved().report.selected_characters,
    )
    list_result = AssociationListResult(
        request=list_request, items=(item,), next_cursor=None
    )

    def list_associations(storage, company, request):
        calls.append(("list", company, request))
        return list_result

    def detail(storage, company, request):
        calls.append(("detail", company, request))
        return saved()

    monkeypatch.setattr(api, "list_position_fragment_associations", list_associations)
    monkeypatch.setattr(api, "read_position_fragment_association_detail", detail)
    response = send(
        LIST,
        json.dumps({"request": list_request.model_dump(mode="json")}).encode(),
        role=AccessRole.AUDITOR,
    )
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    detail_request = AssociationDetailRequest(
        scope=scope(), association_id=saved().report.association_id
    )
    response = send(
        DETAIL,
        json.dumps({"request": detail_request.model_dump(mode="json")}).encode(),
        role=AccessRole.AUDITOR,
    )
    assert response.status_code == 200
    assert calls == [
        ("list", "tenant-a", list_request),
        ("detail", "tenant-a", detail_request),
    ]


@pytest.mark.parametrize("path", [LIST, DETAIL])
def test_restore_routes_reject_untrusted_body_before_dispatch(monkeypatch, path):
    calls = []
    monkeypatch.setattr(
        api, "list_position_fragment_associations", lambda *a, **k: calls.append(1)
    )
    monkeypatch.setattr(
        api, "read_position_fragment_association_detail", lambda *a, **k: calls.append(1)
    )
    for raw, expected in (
        (b'{"request":{},"request":{}}', 422),
        (b'{"request":NaN}', 422),
        (b" " * 4097, 413),
    ):
        response = send(path, raw)
        assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
    assert calls == []


def test_restore_schemas_are_inline_and_foreign_detail_is_redacted(monkeypatch):
    monkeypatch.setattr(
        api,
        "read_position_fragment_association_detail",
        lambda *a, **k: (_ for _ in ()).throw(LookupError("private tenant")),
    )
    request = AssociationDetailRequest(
        scope=scope(), association_id=saved().report.association_id
    )
    response = send(
        DETAIL, json.dumps({"request": request.model_dump(mode="json")}).encode()
    )
    assert response.status_code == 404 and "private" not in response.text
    schemas = (
        api.EIS_POSITION_ASSOCIATION_LIST_OPENAPI_SCHEMA,
        api.EIS_POSITION_ASSOCIATION_DETAIL_OPENAPI_SCHEMA,
    )
    assert all('"$ref"' not in json.dumps(value) for value in schemas)


def test_list_rejects_valid_typed_result_for_another_request(monkeypatch):
    requested = AssociationListRequest(scope=scope(), limit=1)
    foreign = AssociationListRequest(scope=scope(), limit=2)
    wrong = AssociationListResult(request=foreign, items=(), next_cursor=None)
    monkeypatch.setattr(api, "list_position_fragment_associations", lambda *a: wrong)
    response = send(
        LIST, json.dumps({"request": requested.model_dump(mode="json")}).encode()
    )
    assert response.status_code == 503
