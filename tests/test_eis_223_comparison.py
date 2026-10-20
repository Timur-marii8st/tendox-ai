"""Synthetic comparisons must never imply profit, admission or full coverage."""

from datetime import UTC, datetime
from importlib import import_module

import pytest
from pydantic import ValidationError

from procurement.access import AccessRole
from procurement.sources.eis_223_archive import parse_notice223_xml
from procurement.sources.eis_223_documents import manifest223
from procurement.sources.eis_analysis import analyze_document
from procurement.storage.eis_223_comparison import (
    Comparison223Request,
    Comparison223Result,
    Comparison223Row,
    comparison223_documents,
    get_comparison223,
)
from procurement.storage.eis_223_documents import Document223Status, Document223StatusItem
from test_eis_223_archive import URL, xml
from test_eis_223_documents import docx_bytes
from test_eis_document_jobs_api import send


def sample():
    notice = parse_notice223_xml(xml(), source_member="notice.xml")
    manifest = manifest223(notice)
    status = Document223Status(
        manifest=manifest,
        checked_at=datetime.now(UTC),
        version_status="CURRENT_KNOWN_VERSION",
        blocked_reasons=(),
        documents=(),
        download_status="INCOMPLETE",
    )
    return notice, status


def request():
    _, status = sample()
    ref = status.manifest.notice
    other = ref.model_copy(update={"purchase_number": "32600000002"})
    return Comparison223Request(notices=(ref, other))


@pytest.mark.parametrize("kind", ["one", "four", "duplicate", "tenant", "wrong_law", "digest"])
def test_request_is_bounded_and_exact(kind):
    body = request().model_dump(mode="json")
    if kind == "one":
        body["notices"] = body["notices"][:1]
    elif kind == "four":
        body["notices"] *= 2
    elif kind == "duplicate":
        body["notices"][1]["purchase_number"] = body["notices"][0]["purchase_number"]
    elif kind == "tenant":
        body["company_id"] = "other"
    elif kind == "wrong_law":
        body["notices"][0]["purchase_number"] = "1" * 19
    else:
        body["notices"][0]["notice_xml_sha256"] = "not-sha"
    with pytest.raises(ValidationError):
        Comparison223Request.model_validate(body)


def test_preview_marks_truncation_preserves_provenance_and_never_reviews_conditions():
    _, status = sample()
    analysis = analyze_document(docx_bytes(), "ТЗ.docx", URL)
    long = analysis.snippets[0].model_copy(update={"text": "x" * 601})
    analysis = analysis.model_copy(update={"snippets": (long,) * 19})
    status = status.model_copy(
        update={
            "documents": (
                Document223StatusItem(
                    reference=status.manifest.documents[0], received=True, analysis=analysis
                ),
                Document223StatusItem(
                    reference=status.manifest.documents[0], received=False, analysis=None
                ),
            )
        }
    )
    received, missing = comparison223_documents(status)
    assert received.snippets_total == 19 and len(received.snippets) == 18
    assert received.preview_truncated and len(received.snippets[0].text) == 600
    assert received.snippets[0].provenance == long.provenance
    assert received.sha256 == analysis.sha256 and received.review_status == "UNKNOWN"
    assert missing.sha256 is None and missing.extraction_status == "UNKNOWN"


def test_naive_clock_rejected_before_storage():
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        get_comparison223(None, "tenant-a", request(), now=datetime(2026, 10, 2))


def test_readonly_route_accepts_auditor_scopes_from_auth_and_no_store(monkeypatch):
    notice, status = sample()
    row = Comparison223Row(
        notice=notice,
        source_window="synthetic",
        source_response_sha256="a" * 64,
        archive_sha256="b" * 64,
        source_schema_status="UNKNOWN",
        source_schema_checks=(),
        readiness_status="NEEDS_ANALYSIS",
        blocking_reasons=(),
        reasons=(),
        download_status=status.download_status,
        queue_status=status.queue_status,
        documents=(),
    )
    result = Comparison223Result(checked_at=datetime.now(UTC), rows=(row, row))
    calls = []

    def read(storage, company, payload):
        calls.append((company, payload))
        return result

    monkeypatch.setattr(import_module("procurement.api.app"), "get_comparison223", read)
    path = "/v1/tender-discovery/eis-223-comparison"
    payload = request().model_dump(mode="json")
    assert send("POST", path, body=payload, token="bad").status_code == 401
    response = send("POST", path, body=payload, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", request())]
    assert response.json()["profit_order_status"] == "UNKNOWN"
    assert send("POST", path, body={**payload, "company_id": "other"}).status_code == 422
    assert send("GET", path).status_code == 405


@pytest.mark.parametrize("error,code", [(LookupError("missing"), 404), (ValueError("bad"), 409)])
def test_inaccessible_or_conflicting_source_fails_whole_request(monkeypatch, error, code):
    def read(*args):
        raise error

    monkeypatch.setattr(import_module("procurement.api.app"), "get_comparison223", read)
    response = send("POST", "/v1/tender-discovery/eis-223-comparison", body=request().model_dump())
    assert response.status_code == code
    assert "rows" not in response.json()
