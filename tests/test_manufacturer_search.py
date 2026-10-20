"""Manufacturer search remains bounded and conservative before persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from procurement.sources.manufacturer_search import (
    ManufacturerSourceCapture,
    normalized_manufacturer_query,
)
from procurement.storage.manufacturer_search import ManufacturerSearchReport

NOW = datetime(2026, 10, 6, tzinfo=UTC)


def test_query_is_normalized_and_exact_request_is_hashable() -> None:
    query, body = normalized_manufacturer_query("  насос   промышленный ")
    assert query == "насос промышленный"
    assert json.loads(body) == {
        "$and": [
            {"goodsname": {"$regex": "насос", "$options": "i"}},
            {"goodsname": {"$regex": "промышленный", "$options": "i"}},
        ]
    }
    assert len(body) < 1024


@pytest.mark.parametrize("query", ["", "a b c d e f", "x" * 81, "a\nb"])
def test_query_rejects_out_of_contract_values(query: str) -> None:
    with pytest.raises(ValueError):
        normalized_manufacturer_query(query)


def test_capture_rejects_hash_and_size_mismatch() -> None:
    body = b"{}"
    with pytest.raises(ValueError, match="REQUEST_DIGEST"):
        ManufacturerSourceCapture(
            query="насос",
            observed_at=NOW,
            request_body=body,
            request_sha256="0" * 64,
            status="SOURCE_ERROR",
            reason_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        )
    with pytest.raises(ValueError):
        ManufacturerSourceCapture(
            query="насос",
            observed_at=NOW,
            request_body=body,
            request_sha256=hashlib.sha256(body).hexdigest(),
            status="SOURCE_ERROR",
            reason_code="SOURCE_UNAVAILABLE_OR_CHANGED",
            response_body=b"x" * (512 * 1024 + 1),
            response_sha256=hashlib.sha256(b"x" * (512 * 1024 + 1)).hexdigest(),
        )


def test_started_is_unknown_and_cannot_claim_empty() -> None:
    report = ManufacturerSearchReport(
        run_id="00000000-0000-0000-0000-000000000001",
        command_id="00000000-0000-0000-0000-000000000002",
        query="насос",
        status="STARTED",
        reason_code="SOURCE_OUTCOME_UNKNOWN",
        created_at=NOW,
        request_sha256="a" * 64,
    )
    assert report.matched_count is None and report.candidates == ()
    with pytest.raises(ValueError, match="STARTED_RESULT_CONFLICT"):
        ManufacturerSearchReport.model_validate({**report.model_dump(), "matched_count": 0})


def test_source_error_is_never_an_empty_completed_search() -> None:
    report = ManufacturerSearchReport(
        run_id="00000000-0000-0000-0000-000000000001",
        command_id="00000000-0000-0000-0000-000000000002",
        query="насос",
        status="SOURCE_ERROR",
        reason_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        created_at=NOW,
        finished_at=NOW,
        request_sha256="a" * 64,
    )
    assert report.matched_count is None
    with pytest.raises(ValueError, match="ERROR_RESULT_CONFLICT"):
        ManufacturerSearchReport.model_validate({**report.model_dump(), "matched_count": 0})
