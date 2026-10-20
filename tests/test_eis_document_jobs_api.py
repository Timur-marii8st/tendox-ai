"""Exact document jobs require a tenant-bound operator and never run HTTP on GET."""

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from typing import cast

import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.storage.eis_document_store import (
    DocumentCollectionStatus,
    DocumentSelectionRequest,
    DocumentSelectionResult,
    NoticeDocumentRef,
)
from procurement.storage.eis_evidence_bridge import (
    EisEvidenceBridge,
    calculate_eis_preliminary_estimate,
)
from procurement.storage.repository import PostgresStorage

REF = NoticeDocumentRef(
    purchase_number="0848300054826000154", version_number=1, notice_xml_sha256="a" * 64
)
STATUS = DocumentCollectionStatus(
    notice=REF,
    current_version_number=1,
    current_xml_sha256="a" * 64,
    version_status="CURRENT_KNOWN_VERSION",
    requested=True,
    listed_count=0,
    received_count=0,
    pending_count=0,
    download_status="UNKNOWN_MANIFEST",
    extraction_status="UNKNOWN",
    documents=(),
)


class Auth:
    def __init__(self, role: AccessRole) -> None:
        self.role = role

    async def authenticate(self, credential: str) -> Principal | None:
        return (
            Principal(company_id="tenant-a", actor_id="operator", access_role=self.role)
            if credential == "test"
            else None
        )


def send(
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    token: str = "test",
    role: AccessRole = AccessRole.OPERATOR,
) -> httpx.Response:
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, Auth(role)),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(
                method, path, json=body, headers={"Authorization": f"Bearer {token}"}
            )

    return asyncio.run(run())


def test_job_auth_role_and_exact_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    module = import_module("procurement.api.app")
    calls = []

    def plan(
        storage: object, company: str, ref: NoticeDocumentRef, *, actor_id: str
    ) -> DocumentCollectionStatus:
        calls.append((company, ref, actor_id))
        return STATUS

    monkeypatch.setattr(module, "plan_document_job", plan)
    path = "/v1/tender-discovery/eis-document-jobs"
    assert send("POST", path, body=REF.model_dump(), token="invalid").status_code == 401
    assert send("POST", path, body=REF.model_dump(), role=AccessRole.AUDITOR).status_code == 403
    assert (
        send("POST", path, body={**REF.model_dump(), "company_id": "tenant-b"}).status_code == 422
    )
    response = send("POST", path, body=REF.model_dump())
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", REF, "operator")]
    assert response.json()["review_status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "error,status",
    [
        (LookupError("NOTICE_NOT_FOUND"), 404),
        (ValueError("NOTICE_VERSION_STALE"), 409),
        (ValueError("DOCUMENT_SET_RESOURCE_LIMIT"), 422),
    ],
)
def test_job_failure_remains_explicit(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status: int
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(import_module("procurement.api.app"), "plan_document_job", failed)
    assert (
        send("POST", "/v1/tender-discovery/eis-document-jobs", body=REF.model_dump()).status_code
        == status
    )


def test_status_get_uses_stored_analysis_and_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def read(storage: object, company: str, ref: NoticeDocumentRef) -> DocumentCollectionStatus:
        calls.append((company, ref))
        return STATUS

    monkeypatch.setattr(import_module("procurement.api.app"), "get_document_status", read)
    path = (
        f"/v1/tender-discovery/eis-document-jobs/{REF.purchase_number}"
        f"?version_number=1&notice_xml_sha256={REF.notice_xml_sha256}"
    )
    response = send("GET", path, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and calls == [("tenant-a", REF)]
    assert response.json()["download_status"] == "UNKNOWN_MANIFEST"


@pytest.mark.parametrize(
    "kind", ["status", "analysis", "evidence", "estimate", "comparison", "mixed", "source"]
)
def test_source_hold_remains_explicit_and_uncacheable(monkeypatch, kind):
    names = {
        "status": "get_document_status",
        "analysis": "get_document_analysis",
        "evidence": "get_eis_evidence_bridge",
        "estimate": "estimate_eis_notice",
        "comparison": "get_eis_comparison",
        "mixed": "get_mixed_comparison",
        "source": "get_source_estimate",
    }

    def blocked(*args, **kwargs):
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")

    monkeypatch.setattr(import_module("procurement.api.app"), names[kind], blocked)
    costs = {
        "goods": "1",
        "expenses": "1",
        "vat_rate": "0.20",
        "basis": "Synthetic",
        "costs_complete_ack": True,
    }
    ref = REF.model_dump()
    second = {**ref, "purchase_number": "0848300054826000155"}
    paths = {
        "status": ("GET", "", None),
        "analysis": ("GET", "/synthetic/analysis", None),
        "evidence": ("GET", "/evidence", None),
        "estimate": ("POST", "/estimate", costs),
    }
    if kind in paths:
        method, suffix, body = paths[kind]
        path = f"/v1/tender-discovery/eis-document-jobs/{REF.purchase_number}{suffix}"
        path += f"?version_number=1&notice_xml_sha256={REF.notice_xml_sha256}"
    else:
        method = "POST"
        path = (
            "/v1/tender-discovery/eis-"
            + {
                "comparison": "comparison",
                "mixed": "mixed-comparison",
                "source": "source-estimate",
            }[kind]
        )
        body = (
            {"notices": [ref, second]}
            if kind == "comparison"
            else (
                {"notices": [{"law": "44", **r} for r in (ref, second)]}
                if kind == "mixed"
                else {"notice": {"law": "44", **ref}, "costs": costs}
            )
        )
    response = send(method, path, body=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "NOTICE_VARIANT_REVIEW_REQUIRED"}
    assert response.headers["cache-control"] == "no-store"


def test_top_document_selection_is_operator_only_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def select_jobs(
        storage: object, company: str, request: DocumentSelectionRequest, *, actor_id: str
    ) -> DocumentSelectionResult:
        calls.append((company, request.max_candidates, actor_id))
        return DocumentSelectionResult(
            query=request.query,
            compared_at=datetime.now(UTC),
            inspected_current_notices=10,
            matched_count=6,
            eligible_count=0,
            jobs=(),
            rejected=(),
        )

    monkeypatch.setattr(import_module("procurement.api.app"), "plan_top_document_jobs", select_jobs)
    path = "/v1/tender-discovery/eis-document-selection"
    assert send("POST", path, body={"query": "бумага"}, role=AccessRole.AUDITOR).status_code == 403
    assert send("POST", path, body={"query": "бумага", "max_candidates": 6}).status_code == 422
    response = send("POST", path, body={"query": "бумага"})
    assert response.status_code == 200 and calls == [("tenant-a", 3, "operator")]
    assert response.json()["selection_kind"] == "PRELIMINARY"


def test_read_evidence_bridge_is_scoped_read_only_and_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    bridge = EisEvidenceBridge(
        checked_at=datetime.now(UTC),
        notice=REF,
        title="Поставка бумаги",
        source_member="notice.xml",
        document_type="epNotificationEF2020",
        published_at=None,
        deadline=None,
        nmck_rub=None,
        nmck_provenance=None,
        lot_parse_status="UNKNOWN",
        lot_items=(),
        collection=STATUS,
        documents=(),
        application_status="UNKNOWN",
        application_reasons=("DEADLINE_UNKNOWN",),
        economic_status="UNKNOWN",
        economic_missing=("SUPPLIER_QUOTE_MISSING",),
        review_gaps=("SOURCE_MANIFEST_COVERAGE_UNVERIFIED",),
    )

    def read(storage: object, company: str, ref: NoticeDocumentRef) -> EisEvidenceBridge:
        calls.append((company, ref))
        return bridge

    monkeypatch.setattr(import_module("procurement.api.app"), "get_eis_evidence_bridge", read)
    path = (
        f"/v1/tender-discovery/eis-document-jobs/{REF.purchase_number}/evidence"
        f"?version_number=1&notice_xml_sha256={REF.notice_xml_sha256}"
    )
    assert send("GET", path, token="bad").status_code == 401
    response = send("GET", path, role=AccessRole.AUDITOR)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", REF)]
    assert response.json()["requirement_status"] == "UNKNOWN"
    assert response.json()["economic_status"] == "UNKNOWN"


def test_read_evidence_bridge_missing_tenant_or_bad_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args: object) -> None:
        raise LookupError("NOTICE_NOT_FOUND")

    monkeypatch.setattr(import_module("procurement.api.app"), "get_eis_evidence_bridge", missing)
    path = (
        f"/v1/tender-discovery/eis-document-jobs/{REF.purchase_number}/evidence"
        f"?version_number=1&notice_xml_sha256={REF.notice_xml_sha256}"
    )
    assert send("GET", path).status_code == 404
    assert send("GET", path.replace("a" * 64, "BAD")).status_code == 422


def test_preliminary_estimate_requires_operator_exact_costs_and_current_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("procurement.api.app")
    calls = []
    body = {
        "goods": "100.00",
        "expenses": "20.00",
        "vat_rate": "0.20",
        "basis": "Предварительная цена от поставщика",
        "costs_complete_ack": True,
    }
    bridge = EisEvidenceBridge(
        checked_at=datetime.now(UTC),
        notice=REF,
        title="Бумага",
        source_member="notice.xml",
        document_type="epNotificationEF2020",
        published_at=None,
        deadline=None,
        nmck_rub=None,
        nmck_provenance=None,
        lot_parse_status="UNKNOWN",
        lot_items=(),
        collection=STATUS,
        documents=(),
        application_status="UNKNOWN",
        application_reasons=("DEADLINE_UNKNOWN",),
        economic_status="UNKNOWN",
        economic_missing=("SUPPLIER_QUOTE_MISSING",),
        review_gaps=("REQUIREMENTS_NOT_APPROVED",),
    )

    def estimate(storage: object, company: str, ref: NoticeDocumentRef, costs: object):
        calls.append((company, ref, costs))
        return calculate_eis_preliminary_estimate(bridge, costs)

    monkeypatch.setattr(module, "estimate_eis_notice", estimate)
    path = (
        f"/v1/tender-discovery/eis-document-jobs/{REF.purchase_number}/estimate"
        f"?version_number=1&notice_xml_sha256={REF.notice_xml_sha256}"
    )
    assert send("POST", path, body=body, token="bad").status_code == 401
    assert send("POST", path, body=body, role=AccessRole.AUDITOR).status_code == 403
    assert send("POST", path, body={**body, "goods": 1.2}).status_code == 422
    response = send("POST", path, body=body)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["estimate"]["status"] == "UNKNOWN"
    assert response.json()["preliminary_guidance"] == "NEEDS_ANALYSIS"
    assert calls[0][0:2] == ("tenant-a", REF)

    def stale(*args: object) -> None:
        raise ValueError("NOTICE_VERSION_STALE")

    monkeypatch.setattr(module, "estimate_eis_notice", stale)
    assert send("POST", path, body=body).status_code == 409


def test_comparison_is_bounded_read_only_tenant_scoped_and_no_store(monkeypatch) -> None:
    from procurement.storage.eis_comparison import EisComparisonRequest, build_eis_comparison
    from test_eis_comparison import NOW, two_bridges

    bridges = two_bridges()
    calls = []

    def compare(storage, company, payload):
        calls.append((company, payload))
        return build_eis_comparison(payload, bridges, now=NOW)

    monkeypatch.setattr(import_module("procurement.api.app"), "get_eis_comparison", compare)
    path = "/v1/tender-discovery/eis-comparison"
    request = EisComparisonRequest(notices=tuple(item.notice for item in bridges))
    payload = request.model_dump(mode="json")
    assert send("POST", path, body=payload, token="bad").status_code == 401
    assert send("POST", path, body={**payload, "company_id": "tenant-b"}).status_code == 422
    assert (
        send("POST", path, body={"notices": [bridges[0].notice.model_dump()] * 2}).status_code
        == 422
    )
    response = send("POST", path, body=payload, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", request)]
    assert response.json()["profit_order_status"] == "UNKNOWN"

    def missing(*_):
        raise LookupError("NOTICE_NOT_FOUND")

    monkeypatch.setattr(import_module("procurement.api.app"), "get_eis_comparison", missing)
    assert send("POST", path, body=payload).status_code == 404
