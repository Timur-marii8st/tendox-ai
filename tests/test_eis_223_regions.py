"""Regional scope admission, exact target identities and tenant read contract."""

import hashlib
from datetime import UTC, date, datetime
from importlib import import_module

import pytest

from procurement.access import AccessRole
from procurement.sources.eis_223_regions import REGION_SELECTOR_URL, inspect_region_catalog
from procurement.storage.eis_223_regions import (
    Eis223RegionalCoverage,
    plan_targets,
    target_from_key,
)
from procurement.storage.eis_223_sync import refresh_window_key
from test_eis_document_jobs_api import send

NOW = datetime(2026, 10, 3, 18, tzinfo=UTC)


def catalog_html(regions=("50", "77", "78")):
    entries = "".join(
        f'<li class="select-vars__item select-text" id="{code}000000000">Region {code}</li>'
        for code in regions
    )
    return (
        '<html><div id="modal-region"><div id="region-select">'
        '<ul class="select-vars select-overflow">'
        '<li class="select-vars__item select-text">Не выбран</li>'
        + entries
        + "</ul></div></div></html>"
    ).encode()


def inspect(content):
    return inspect_region_catalog(
        content,
        source_url=REGION_SELECTOR_URL,
        response_sha256=hashlib.sha256(content).hexdigest(),
        observed_at=NOW,
    )


def test_exact_public_kladr_mapping_keeps_scope_and_retained_body_hash():
    result = inspect(catalog_html(("01", "50", "77", "78", "99")))
    assert tuple(result.regions) == ("01", "50", "77", "78", "99")
    assert result.catalog_sha256 == result.response_sha256
    assert result.source_url == REGION_SELECTOR_URL


@pytest.mark.parametrize(
    "content",
    [
        b"<html>CAPTCHA</html>",
        catalog_html(("00",)),
        catalog_html(("50", "50")),
        catalog_html().replace(b"50000000000", b"50001000000"),
        catalog_html().replace(b"</li>", b""),
        catalog_html().split(b"</ul>")[0],
        catalog_html().replace(b'<div id="region-select">', b'<div id="other">'),
        catalog_html().replace(b' id="50000000000"', b""),
        b"\xff",
        b"x" * (512 * 1024 + 1),
    ],
    ids=[
        "blocked",
        "zero",
        "duplicate",
        "nonregional",
        "truncated",
        "between-rows",
        "wrong-container",
        "region-id-missing",
        "encoding",
        "oversized",
    ],
)
def test_changed_missing_duplicate_or_truncated_catalog_is_rejected(content):
    with pytest.raises(ValueError):
        inspect(content)


def test_matrix_is_single_parameterized_loader_interleaved_and_exact_roundtrip():
    targets = plan_targets(("01", "50", "77", "78", "99"), date(2026, 10, 2), date(2026, 10, 3))
    assert len(targets) == 50
    assert [t.region for t in targets[:10:2]] == ["01", "50", "77", "78", "99"]
    assert [t.day for t in targets[:2]] == [date(2026, 10, 3), date(2026, 10, 2)]
    assert len({refresh_window_key(t) for t in targets}) == 50
    assert all(target_from_key(refresh_window_key(t)) == t for t in targets)


def test_coverage_endpoint_is_tenant_scoped_read_only_no_store(monkeypatch):
    calls = []

    def read(storage, company, *, now):
        calls.append(company)
        return Eis223RegionalCoverage(company_id=company, checked_at=now)

    monkeypatch.setattr(import_module("procurement.api.app"), "read_region_coverage", read)
    path = "/v1/tender-discovery/eis-223-coverage"
    assert send("GET", path, token="invalid").status_code == 401
    response = send("GET", path + "?company_id=other", role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == ["tenant-a"]
    assert response.json()["reason"] == "OFFICIAL_REGION_CATALOG_MISSING"
    assert response.json()["coverage"] == response.json()["freshness"] == "UNKNOWN"
    assert send("POST", path, body={}).status_code == 405
