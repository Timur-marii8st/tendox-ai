"""Published EAEU manufacturer collection retains provenance and fails closed."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from procurement.sources.eaeu_manufacturers import (
    EAEU_MANUFACTURERS_URL,
    _request_body,
    parse_manufacturer_response,
    search_eaeu_manufacturers,
)
from procurement.sources.eaeu_registry import RegistryFetchStatus, RegistrySourceError

NOW = datetime(2026, 9, 21, tzinfo=UTC)
RECORD = {
    "_id": {"$oid": "676c5c9ef333c7063df7702e"},
    "identitycode": "400051810",
    "name": "ОАО ГЗСиУ",
    "statemember": "02",
}


def _content(records: list[dict[str, object]], matched: int) -> bytes:
    return json.dumps({"result": records, "matchedDocuments": matched}, ensure_ascii=False).encode()


def test_company_lookup_has_exact_response_evidence() -> None:
    body = _request_body(("ГЗСиУ",))
    content = _content([RECORD], 1)
    result = parse_manufacturer_response(
        content, query="ГЗСиУ", request_body=body, observed_at=NOW
    )
    assert result.fetch_status is RegistryFetchStatus.COMPLETED
    assert result.source_url == EAEU_MANUFACTURERS_URL
    assert result.response_sha256 == hashlib.sha256(content).hexdigest()
    assert result.request_sha256 == hashlib.sha256(body).hexdigest()
    assert result.candidates[0].identity_code == "400051810"
    assert result.candidates[0].suitability == "UNKNOWN"


def test_empty_verified_response_remains_distinct_from_failure() -> None:
    result = parse_manufacturer_response(
        _content([], 0), query="unknown", request_body=b"{}", observed_at=NOW
    )
    assert result.matched_count == 0
    assert result.candidates == ()


@pytest.mark.parametrize(
    "record",
    [{**RECORD, "identitycode": ""}, {**RECORD, "_id": {"$oid": "invalid"}}],
)
def test_malformed_record_is_not_silently_omitted(record: dict[str, object]) -> None:
    with pytest.raises(RegistrySourceError):
        parse_manufacturer_response(
            _content([record], 1), query="ГЗСиУ", request_body=b"{}", observed_at=NOW
        )


def test_company_query_escapes_regex() -> None:
    assert json.loads(_request_body(("a.*",))) == {
        "name": {"$regex": r"a\.\*", "$options": "i"}
    }


def test_http_failure_is_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> httpx.Client:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("procurement.sources.eaeu_manufacturers.httpx.Client", unavailable)
    result = search_eaeu_manufacturers("ГЗСиУ")
    assert result.fetch_status is RegistryFetchStatus.SOURCE_ERROR
    assert result.matched_count is None
    assert result.response_sha256 is None
