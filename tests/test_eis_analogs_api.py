"""Read-only authenticated analog retrieval never accepts caller tenant or bad refs."""

from importlib import import_module

import pytest

from procurement.access import AccessRole
from procurement.sources.eis_analogs import AnalogRequest, build_analog_report
from test_eis_analogs import notice
from test_eis_document_jobs_api import send

PATH = "/v1/tender-discovery/eis-analog-candidates"
TARGET = notice()
BODY = AnalogRequest(target=TARGET.notice, source_index=1, query="бумага").model_dump(mode="json")


def test_authenticated_read_uses_principal_no_store_and_exact_request(monkeypatch):
    calls = []

    def read(storage, company, request, *, now):
        calls.append((company, request))
        return build_analog_report(request, TARGET, (), now=now, selection_truncated=False)

    monkeypatch.setattr(import_module("procurement.api.app"), "read_analog_candidates", read)
    assert send("POST", PATH, body=BODY, token="invalid").status_code == 401
    assert not calls
    response = send("POST", PATH, body=BODY, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls[0][0] == "tenant-a" and calls[0][1].target == TARGET.notice
    assert response.json()["competition_prediction"] == "UNKNOWN"


@pytest.mark.parametrize(
    "updates",
    [
        {"company_id": "other"},
        {"source_index": 26},
        {"source_index": True},
        {"target": dict(BODY["target"], notice_xml_sha256="bad")},
        {"query": ""},
    ],
)
def test_invalid_request_does_not_read(monkeypatch, updates):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid input read storage")

    monkeypatch.setattr(import_module("procurement.api.app"), "read_analog_candidates", forbidden)
    assert send("POST", PATH, body=BODY | updates).status_code == 422


def test_resource_or_source_hold_failure_is_not_empty_success(monkeypatch):
    def failed(*args, **kwargs):
        raise ValueError("ANALOG_NOTICE_PAYLOAD_LIMIT")

    monkeypatch.setattr(import_module("procurement.api.app"), "read_analog_candidates", failed)
    response = send("POST", PATH, body=BODY)
    assert (
        response.status_code == 422 and response.json()["detail"] == "ANALOG_NOTICE_PAYLOAD_LIMIT"
    )


def test_database_timeout_returns_safe_retryable_failure(monkeypatch):
    from sqlalchemy.exc import OperationalError

    def failed(*args, **kwargs):
        raise OperationalError("private-sql", {}, Exception("private-connection"))

    monkeypatch.setattr(import_module("procurement.api.app"), "read_analog_candidates", failed)
    response = send("POST", PATH, body=BODY)
    assert response.status_code == 503 and response.json()["detail"] == "analog_read_unavailable"
