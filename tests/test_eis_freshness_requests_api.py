"""Queueing a read requires operator; status is tenant-scoped and read-only."""

from datetime import UTC, datetime
from importlib import import_module

import pytest

from procurement.access import AccessRole
from procurement.storage.eis_freshness_requests import (
    EisRefreshRequest,
    EisRefreshRequestPayload,
    _status,
    request_targets,
)
from test_eis_document_jobs_api import send

NOW = datetime(2026, 10, 1, 10, 15, tzinfo=UTC)
PAYLOAD = {"query": "бумага", "regions": ["50"]}
PATH = "/v1/tender-discovery/eis-refresh-requests"


def test_refresh_operator_auth_and_no_network_get(monkeypatch):
    from datetime import timedelta

    payload = EisRefreshRequestPayload.model_validate(PAYLOAD)
    request = EisRefreshRequest(
        request_id="00000000-0000-0000-0000-000000000001",
        company_id="tenant-a",
        payload=payload,
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        window_keys=tuple(item.selection.window_key for item in request_targets(payload, NOW)),
    )
    result = _status(request, {}, NOW)
    calls = []

    def plan(storage, company, body, *, actor_id, now):
        calls.append((company, body, actor_id))
        return result

    def read(storage, company, request_id, *, now):
        assert company == "tenant-a" and request_id == request.request_id
        return result

    module = import_module("procurement.api.app")
    monkeypatch.setattr(module, "plan_refresh_request", plan)
    monkeypatch.setattr(module, "get_refresh_status", read)
    assert send("POST", PATH, body=PAYLOAD, token="invalid").status_code == 401
    assert send("POST", PATH, body=PAYLOAD, role=AccessRole.AUDITOR).status_code == 403
    assert send("POST", PATH, body={**PAYLOAD, "company_id": "other"}).status_code == 422
    response = send("POST", PATH, body=PAYLOAD)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", payload, "operator")]
    assert send("GET", f"{PATH}/{request.request_id}", role=AccessRole.AUDITOR).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error,code",
    [(ValueError("REFRESH_REQUEST_RATE_LIMIT"), 429), (ValueError("REFRESH_QUEUE_FULL"), 429)],
)
def test_limit_is_exposed_without_dispatch(monkeypatch, error, code):
    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(import_module("procurement.api.app"), "plan_refresh_request", failed)
    response = send("POST", PATH, body=PAYLOAD)
    assert response.status_code == code and response.headers["Retry-After"] == "60"


def test_unknown_request_is_404(monkeypatch):
    def missing(*args, **kwargs):
        raise LookupError("REFRESH_REQUEST_NOT_FOUND")

    monkeypatch.setattr(import_module("procurement.api.app"), "get_refresh_status", missing)
    assert send("GET", f"{PATH}/unknown").status_code == 404
