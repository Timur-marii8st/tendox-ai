"""The official public registry adapter fails closed and retains response provenance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from procurement.sources.eaeu_registry import (
    EAEU_REGISTRY_URL,
    RegistryFetchStatus,
    RegistrySourceError,
    _request_body,
    _validated_query,
    parse_eaeu_registry_response,
    search_eaeu_registry,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)
RECORD = {
    "_id": {"$oid": "6582fb75a4a4b05007bb2d05"},
    "registrynumber": "000001234",
    "goodsname": "Насос промышленный НП-1",
    "name": "ООО Завод",
    "expertactenddate": "2027-12-31",
}


def _content(records: list[dict[str, object]], matched: int) -> bytes:
    return json.dumps({"result": records, "matchedDocuments": matched}, ensure_ascii=False).encode()


def test_parses_candidate_with_exact_response_evidence() -> None:
    body = _request_body(("насос",))
    content = _content([RECORD], 17)
    result = parse_eaeu_registry_response(
        content, query="насос", request_body=body, observed_at=NOW
    )

    assert result.fetch_status is RegistryFetchStatus.COMPLETED
    assert result.source_url == EAEU_REGISTRY_URL
    assert result.matched_count == 17
    assert result.response_sha256 == hashlib.sha256(content).hexdigest()
    assert result.request_sha256 == hashlib.sha256(body).hexdigest()
    assert result.candidates[0].source_record_index == 1
    assert result.candidates[0].manufacturer_name == "ООО Завод"
    assert result.candidates[0].record_url.endswith("/6582fb75a4a4b05007bb2d05")
    assert result.candidates[0].suitability == "UNKNOWN"


def test_empty_verified_response_is_distinct_from_source_error() -> None:
    result = parse_eaeu_registry_response(
        _content([], 0), query="насос", request_body=b"{}", observed_at=NOW
    )
    assert result.fetch_status is RegistryFetchStatus.COMPLETED
    assert result.candidates == ()
    assert result.matched_count == 0


@pytest.mark.parametrize(
    "record",
    [
        {**RECORD, "_id": {"$oid": "bad"}},
        {**RECORD, "goodsname": ""},
        {**RECORD, "expertactenddate": "not-a-date"},
    ],
)
def test_changed_record_is_not_silently_omitted(record: dict[str, object]) -> None:
    with pytest.raises(RegistrySourceError):
        parse_eaeu_registry_response(
            _content([record], 1), query="насос", request_body=b"{}", observed_at=NOW
        )


def test_query_escapes_regex_and_rejects_invalid_input() -> None:
    body = json.loads(_request_body(_validated_query("насос.*")))
    assert body == {"goodsname": {"$regex": r"насос\.\*", "$options": "i"}}
    for query in ("", "  ", "one two three four five six", "x" * 81, "a\nb"):
        with pytest.raises(ValueError):
            _validated_query(query)


def test_http_failure_returns_source_error_not_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> httpx.Client:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("procurement.sources.eaeu_registry.httpx.Client", unavailable)
    result = search_eaeu_registry("насос")
    assert result.fetch_status is RegistryFetchStatus.SOURCE_ERROR
    assert result.matched_count is None
    assert result.candidates == ()
    assert result.response_sha256 is None
    assert result.error_code == "SOURCE_UNAVAILABLE_OR_CHANGED"
