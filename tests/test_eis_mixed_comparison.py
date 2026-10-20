"""Synthetic law routing, authentication and unknown economics contracts."""

from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import import_module

import pytest
from pydantic import ValidationError

from procurement.access import AccessRole
from procurement.storage import eis_mixed_comparison as mixed
from procurement.storage.eis_223_comparison import Comparison223Row
from procurement.storage.eis_comparison import comparison44_row
from test_eis_223_comparison import sample as sample223
from test_eis_comparison import two_bridges
from test_eis_document_jobs_api import send

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def request():
    first = two_bridges()[0].notice.model_dump()
    second = sample223()[1].manifest.notice.model_dump()
    return mixed.MixedComparisonRequest.model_validate(
        {
            "notices": [
                {"law": "44", **first},
                {"law": "223", **second},
            ]
        }
    )


@pytest.mark.parametrize(
    "change", ["one", "four", "duplicate", "law", "swap", "tenant", "nested_tenant", "sha"]
)
def test_exact_law_refs_bounds_and_no_tenant_payload(change):
    payload = request().model_dump(mode="json")
    if change == "one":
        payload["notices"] = payload["notices"][:1]
    elif change == "four":
        payload["notices"] *= 2
    elif change == "duplicate":
        payload["notices"][1] = {**payload["notices"][0], "version_number": 9}
    elif change == "law":
        payload["notices"][0]["law"] = "94"
    elif change == "swap":
        payload["notices"][0]["law"] = "223"
    elif change == "tenant":
        payload["company_id"] = "other"
    elif change == "nested_tenant":
        payload["notices"][0]["company_id"] = "other"
    else:
        payload["notices"][1]["notice_xml_sha256"] = "bad"
    with pytest.raises(ValidationError):
        mixed.MixedComparisonRequest.model_validate(payload)


def row223():
    notice, status = sample223()
    return Comparison223Row(
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


def result():
    bridge = two_bridges()[0].model_copy(update={"checked_at": NOW})
    return mixed.MixedComparisonResult(
        checked_at=NOW,
        rows=(
            mixed.Mixed44Row(
                **comparison44_row(bridge).model_dump(),
                source_window="synthetic",
                source_response_sha256="a" * 64,
                archive_sha256="b" * 64,
            ),
            mixed.Mixed223Row(**row223().model_dump()),
        ),
    )


def test_one_shared_snapshot_input_order_and_no_archive_parser(monkeypatch):
    class Connection:
        def execute(self, _):
            return self

        def mappings(self):
            return self

        def one(self):
            return {
                "window_key": "synthetic",
                "response_sha256": "a" * 64,
                "archive_sha256": "b" * 64,
            }

    connection = Connection()
    transactions = []
    reads = []

    class Storage:
        @contextmanager
        def transaction(self, company, *, consistent_read):
            transactions.append((company, consistent_read))
            yield connection

    def read44(conn, company, ref, *, now, include_competition_criteria):
        assert conn is connection and now == NOW and company == "tenant-a"
        assert include_competition_criteria is False
        reads.append("44")
        return two_bridges()[0].model_copy(update={"checked_at": now})

    def read223(conn, company, ref, *, now):
        assert conn is connection and now == NOW and company == "tenant-a"
        reads.append("223")
        return row223()

    monkeypatch.setattr(mixed, "read_eis_evidence_bridge", read44)
    monkeypatch.setattr(mixed, "read_comparison223_row", read223)
    payload = request().model_copy(update={"notices": tuple(reversed(request().notices))})
    compared = mixed.get_mixed_comparison(Storage(), "tenant-a", payload, now=NOW)
    assert transactions == [("tenant-a", True)] and reads == ["223", "44"]
    assert [r.law for r in compared.rows] == reads
    assert compared.profit_order_status == compared.economic_comparability == "UNKNOWN"
    serialized = compared.model_dump(mode="json")
    assert mixed.MixedComparisonResult.model_validate(serialized) == compared


def test_naive_clock_fails_before_storage():
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        mixed.get_mixed_comparison(None, "tenant-a", request(), now=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        mixed.MixedComparisonResult.model_validate(
            {**result().model_dump(), "checked_at": datetime(2026, 10, 2)}
        )


def test_auditor_read_route_scopes_from_auth_no_store(monkeypatch):
    calls = []

    def read(storage, company, payload):
        calls.append((company, payload))
        return result()

    monkeypatch.setattr(import_module("procurement.api.app"), "get_mixed_comparison", read)
    path = "/v1/tender-discovery/eis-mixed-comparison"
    body = request().model_dump(mode="json")
    assert send("POST", path, body=body, token="invalid").status_code == 401
    response = send("POST", path, body=body, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", request())]
    assert response.json()["economic_comparability"] == "UNKNOWN"
    assert send("POST", path, body={**body, "company_id": "other"}).status_code == 422
    assert send("GET", path).status_code == 405


@pytest.mark.parametrize(
    "error,status", [(LookupError("missing"), 404), (ValueError("secret"), 409)]
)
def test_missing_conflicting_source_has_no_partial_result_or_raw_error(monkeypatch, error, status):
    def read(*args):
        raise error

    monkeypatch.setattr(import_module("procurement.api.app"), "get_mixed_comparison", read)
    response = send(
        "POST", "/v1/tender-discovery/eis-mixed-comparison", body=request().model_dump()
    )
    assert response.status_code == status
    assert "rows" not in response.json() and "secret" not in response.text
