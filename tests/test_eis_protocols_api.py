"""Exact tenant-bound historical read is authenticated and never calls source/queue."""

from importlib import import_module

import pytest

from procurement.access import AccessRole
from procurement.storage.eis_protocols import EisHistoricalProtocolReport
from test_eis_document_jobs_api import REF, send

PATH = "/v1/tender-discovery/eis-protocols?" + "&".join(
    f"{key}={value}" for key, value in REF.model_dump().items()
)


def test_authenticated_read_binds_principal_and_exact_ref(monkeypatch):
    calls = []

    def reader(storage, company, ref, *, now):
        calls.append((company, ref))
        return EisHistoricalProtocolReport(
            company_id=company,
            notice=ref,
            checked_at=now,
            application_status="UNKNOWN",
            reasons=(),
            metadata_documents=0,
            uninterpreted_document_types=(),
            documents=(),
        )

    monkeypatch.setattr(import_module("procurement.api.app"), "read_historical_protocols", reader)
    assert send("GET", PATH, token="invalid").status_code == 401
    assert not calls
    response = send("GET", PATH, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", REF)]
    assert response.json()["notice_version_link"] == "UNKNOWN"
    assert response.json()["source_requests"] == 0


@pytest.mark.parametrize(
    "path",
    [
        "/v1/tender-discovery/eis-protocols",
        PATH.replace("version_number=1", "version_number=0"),
        PATH.replace("notice_xml_sha256=" + "a" * 64, "notice_xml_sha256=bad"),
    ],
)
def test_invalid_ref_never_reads_storage(monkeypatch, path):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid request read storage")

    monkeypatch.setattr(
        import_module("procurement.api.app"), "read_historical_protocols", forbidden
    )
    assert send("GET", path).status_code == 422


def test_integrity_failure_is_explicit_not_empty_success(monkeypatch):
    def failed(*args, **kwargs):
        raise ValueError("PROTOCOL_ARCHIVE_SHA_MISMATCH")

    monkeypatch.setattr(import_module("procurement.api.app"), "read_historical_protocols", failed)
    response = send("GET", PATH)
    assert response.status_code == 422
    assert response.json()["detail"] == "PROTOCOL_ARCHIVE_SHA_MISMATCH"
