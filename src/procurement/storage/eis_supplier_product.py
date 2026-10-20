"""Immutable source-zero product details bound to one saved catalog product."""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Text, and_, cast, func, insert, select
from sqlalchemy.engine import Connection

from procurement.sources.eis_characteristic_compare import SavedPosition
from procurement.sources.eis_supplier_product import (
    POLICY_VERSION,
    SavedSupplierProduct,
    SupplierProductReport,
    SupplierProductRequest,
    build_supplier_product_report,
)
from procurement.sources.supplier_product_details import parse_supplier_product_details
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_supplier_catalog import (
    MAX_REPORT_BYTES,
    SupplierCatalogReport,
    _digest,
)
from procurement.storage.eis_supplier_catalog import (
    _context as _catalog_context,
)
from procurement.storage.eis_supplier_page import (
    MAX_BODY_BYTES,
    _position_basis,
    _tenant_lease,
    _write,
)
from procurement.storage.eis_supplier_search import _position
from procurement.storage.models import eis_supplier_catalog_runs as catalog_runs
from procurement.storage.models import eis_supplier_product_reports as runs
from procurement.storage.repository import PostgresStorage

_PRODUCT_SLOT = threading.BoundedSemaphore(1)


@contextmanager
def _product_slot() -> Iterator[None]:
    if not _PRODUCT_SLOT.acquire(blocking=False):
        raise ValueError("SUPPLIER_PRODUCT_BUSY")
    try:
        yield
    finally:
        _PRODUCT_SLOT.release()


def _product_parent(
    conn: Connection,
    company: str,
    request: SupplierProductRequest,
    *,
    body: bool,
) -> tuple[SupplierCatalogReport, str, bytes | None, SavedPosition, str]:
    position = _position(conn, company, request.catalog.page.position)
    position_sha = _position_basis(position)
    _, page_sha, _, context_position_sha, search_sha, selected_link = _catalog_context(
        conn, company, request.catalog, page_body=False
    )
    meta = (
        conn.execute(
            select(
                catalog_runs.c.report_sha256,
                catalog_runs.c.created_at,
                catalog_runs.c.source_body_sha256,
                catalog_runs.c.source_body_byte_count,
                func.octet_length(cast(catalog_runs.c.report, Text)).label("report_size"),
                func.octet_length(catalog_runs.c.source_body).label("body_size"),
            ).where(
                catalog_runs.c.company_id == company,
                catalog_runs.c.run_id == request.product_run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if meta is None:
        raise LookupError("SUPPLIER_PRODUCT_PARENT_NOT_FOUND")
    if meta["report_size"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_PRODUCT_PARENT_LIMIT")
    payload = conn.scalar(
        select(catalog_runs.c.report).where(
            catalog_runs.c.company_id == company,
            catalog_runs.c.run_id == request.product_run_id,
        )
    )
    parent_sha = _digest(payload)
    if parent_sha != meta["report_sha256"]:
        raise ValueError("SUPPLIER_PRODUCT_PARENT_DIGEST_CONFLICT")
    report = SupplierCatalogReport.model_validate(payload)
    if (
        report.run_id != request.product_run_id
        or report.request != request.catalog
        or report.stage != "PRODUCT"
        or report.status != "COMPLETED"
        or report.position_sha256 != position_sha
        or context_position_sha != position_sha
        or report.parent_page_report_sha256 != page_sha
        or report.parent_search_report_sha256 != search_sha
        or report.selected_link != selected_link
        or report.created_at != meta["created_at"]
        or report.observation is None
        or report.observation.status != "COMPLETED"
        or report.source_body_sha256 is None
        or report.source_body_byte_count is None
        or not 1 <= report.source_body_byte_count <= MAX_BODY_BYTES
        or report.source_body_sha256 != meta["source_body_sha256"]
        or report.source_body_byte_count != meta["source_body_byte_count"]
        or report.source_body_byte_count != meta["body_size"]
    ):
        raise ValueError("SUPPLIER_PRODUCT_PARENT_EVIDENCE_CONFLICT")
    content = (
        conn.scalar(
            select(catalog_runs.c.source_body).where(
                catalog_runs.c.company_id == company,
                catalog_runs.c.run_id == request.product_run_id,
            )
        )
        if body
        else None
    )
    if body and (
        not isinstance(content, bytes)
        or hashlib.sha256(content).hexdigest() != report.source_body_sha256
    ):
        raise ValueError("SUPPLIER_PRODUCT_PARENT_EVIDENCE_CONFLICT")
    return report, parent_sha, content, position, position_sha


def _key(request: SupplierProductRequest, parent_sha: str, position_sha: str, body_sha: str) -> str:
    return _digest(
        {
            "policy": POLICY_VERSION,
            "request": request.model_dump(mode="json"),
            "parent": parent_sha,
            "position": position_sha,
            "body": body_sha,
        }
    )


def _cached(
    conn: Connection,
    company: str,
    key: str,
    request: SupplierProductRequest,
    parent_sha: str,
    position_sha: str,
    body_sha: str,
    expected_url: str,
) -> SupplierProductReport | None:
    scope = and_(runs.c.company_id == company, runs.c.cache_key == key)
    meta = (
        conn.execute(
            select(
                runs.c.run_id,
                runs.c.report_sha256,
                runs.c.created_at,
                func.octet_length(cast(runs.c.report, Text)).label("size"),
            ).where(scope)
        )
        .mappings()
        .one_or_none()
    )
    if meta is None:
        return None
    if meta["size"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_PRODUCT_EVIDENCE_CONFLICT")
    payload = conn.scalar(select(runs.c.report).where(scope))
    report = SupplierProductReport.model_validate(payload)
    if (
        _digest(payload) != meta["report_sha256"]
        or report.run_id != meta["run_id"]
        or report.created_at != meta["created_at"]
        or report.request != request
        or report.parent_product_report_sha256 != parent_sha
        or report.position_sha256 != position_sha
        or _position_basis(report.position) != position_sha
        or report.source_body_sha256 != body_sha
        or report.details.source_url != expected_url
    ):
        raise ValueError("SUPPLIER_PRODUCT_EVIDENCE_CONFLICT")
    return report


def _save(
    conn: Connection,
    company: str,
    key: str,
    report: SupplierProductReport,
    actor: str,
) -> None:
    payload = report.model_dump(mode="json")
    ref = report.position.selection.notice
    conn.execute(
        insert(runs).values(
            company_id=company,
            run_id=report.run_id,
            cache_key=key,
            purchase_number=ref.purchase_number,
            version_number=ref.version_number,
            notice_xml_sha256=ref.notice_xml_sha256,
            source_index=report.position.selection.source_index,
            parent_product_run_id=report.request.product_run_id,
            report=payload,
            report_sha256=_digest(payload),
            created_at=report.created_at,
        )
    )
    _audit(
        conn,
        company,
        actor,
        ref,
        "EIS_SUPPLIER_PRODUCT_SAVED",
        {"run_id": report.run_id, "policy_version": POLICY_VERSION},
    )


def read_supplier_product(
    storage: PostgresStorage, company: str, request: SupplierProductRequest
) -> SavedSupplierProduct:
    with storage.transaction(company, consistent_read=True) as conn:
        parent, parent_sha, _, _, position_sha = _product_parent(conn, company, request, body=False)
        assert parent.source_body_sha256 is not None
        key = _key(request, parent_sha, position_sha, parent.source_body_sha256)
        report = _cached(
            conn,
            company,
            key,
            request,
            parent_sha,
            position_sha,
            parent.source_body_sha256,
            parent.observation.final_url if parent.observation is not None else "",
        )
        if report is None:
            raise LookupError("SUPPLIER_PRODUCT_NOT_FOUND")
        return SavedSupplierProduct(report=report, created=False)


def prepare_supplier_product(
    storage: PostgresStorage,
    company: str,
    request: SupplierProductRequest,
    *,
    actor_id: str,
) -> SavedSupplierProduct:
    if not actor_id.strip():
        raise ValueError("SUPPLIER_PRODUCT_REQUEST_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        parent, parent_sha, _, _, position_sha = _product_parent(conn, company, request, body=False)
        assert parent.source_body_sha256 is not None
        body_sha = parent.source_body_sha256
        key = _key(request, parent_sha, position_sha, body_sha)
        cached = _cached(
            conn,
            company,
            key,
            request,
            parent_sha,
            position_sha,
            body_sha,
            parent.observation.final_url if parent.observation is not None else "",
        )
        if cached is not None:
            return SavedSupplierProduct(report=cached, created=False)
    with _product_slot(), _tenant_lease(storage, company), _write(storage, company) as conn:
        parent2, parent_sha2, _, _, position_sha2 = _product_parent(
            conn, company, request, body=False
        )
        if (parent_sha2, position_sha2, parent2.source_body_sha256) != (
            parent_sha,
            position_sha,
            body_sha,
        ):
            raise ValueError("SUPPLIER_PRODUCT_SOURCE_CHANGED")
        expected_url = parent2.observation.final_url if parent2.observation is not None else ""
        cached = _cached(
            conn,
            company,
            key,
            request,
            parent_sha,
            position_sha,
            body_sha,
            expected_url,
        )
        if cached is not None:
            return SavedSupplierProduct(report=cached, created=False)
        parent3, parent_sha3, content, position3, position_sha3 = _product_parent(
            conn, company, request, body=True
        )
        if (parent_sha3, position_sha3, parent3.source_body_sha256) != (
            parent_sha,
            position_sha,
            body_sha,
        ):
            raise ValueError("SUPPLIER_PRODUCT_SOURCE_CHANGED")
        position = position3
        if not isinstance(content, bytes) or parent3.observation is None:
            raise ValueError("SUPPLIER_PRODUCT_PARENT_EVIDENCE_CONFLICT")
        details = parse_supplier_product_details(parent3.observation.final_url, content)
        report = build_supplier_product_report(
            request,
            position,
            details,
            parent_product_report_sha256=parent_sha,
            position_sha256=position_sha,
            source_body_sha256=body_sha,
            run_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC),
        )
        _save(conn, company, key, report, actor_id)
        return SavedSupplierProduct(report=report, created=True)
