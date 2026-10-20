"""Two-stage immutable supplier catalog observations bound to retained evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Text, and_, cast, func, insert, select
from sqlalchemy.engine import Connection

from procurement.sources.supplier_catalog import (
    CatalogLink,
    CatalogLinks,
    CatalogSearchSpec,
    build_catalog_search,
    enrich_catalog_product,
    parse_catalog_links,
)
from procurement.sources.supplier_page import PageObservation, observe_supplier_page
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_supplier_page import (
    DAILY_BODY_BYTES,
    MAX_BODY_BYTES,
    REFRESH_COOLDOWN,
    SupplierPageReport,
    SupplierPageRequest,
    _position_basis,
    _run_leases,
    _tenant_lease,
    _write,
)
from procurement.storage.eis_supplier_search import _position
from procurement.storage.models import eis_supplier_catalog_runs as runs
from procurement.storage.models import eis_supplier_page_runs as page_runs
from procurement.storage.repository import PostgresStorage

POLICY: Literal["eis-position-supplier-catalog-v1"] = "eis-position-supplier-catalog-v1"
MAX_REPORT_BYTES = 256 * 1024
HOURLY_NEW_RUNS = 30


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupplierCatalogRequest(Frozen):
    page: SupplierPageRequest
    page_run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    search_run_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    product_index: int | None = Field(default=None, ge=1, le=10, strict=True)

    @model_validator(mode="after")
    def valid(self) -> Self:
        for value in (self.page_run_id, self.search_run_id):
            if value is not None:
                try:
                    if str(uuid.UUID(value)) != value:
                        raise ValueError
                except ValueError as error:
                    raise ValueError("SUPPLIER_CATALOG_RUN_ID_INVALID") from error
        if (self.search_run_id is None) != (self.product_index is None):
            raise ValueError("SUPPLIER_CATALOG_STAGE_INVALID")
        return self

    @property
    def stage(self) -> Literal["SEARCH", "PRODUCT"]:
        return "SEARCH" if self.search_run_id is None else "PRODUCT"


class SupplierCatalogReport(Frozen):
    policy_version: Literal["eis-position-supplier-catalog-v1"] = POLICY
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    request: SupplierCatalogRequest
    parent_page_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    stage: Literal["SEARCH", "PRODUCT"]
    search_spec: CatalogSearchSpec | None
    selected_link: CatalogLink | None
    parent_search_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["STARTED", "COMPLETED"]
    reason_code: Literal["SOURCE_OUTCOME_UNKNOWN", "FIXED_CATALOG_OBSERVATION"]
    observation: PageObservation | None
    links: CatalogLinks | None
    attempted_source_requests: int | None = Field(default=None, ge=0, le=3, strict=True)
    source_body_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_body_byte_count: int | None = Field(default=None, ge=1, le=MAX_BODY_BYTES, strict=True)
    supplier_identity: Literal["UNKNOWN"] = "UNKNOWN"
    price_comparability: Literal["UNKNOWN"] = "UNKNOWN"
    tax: Literal["UNKNOWN"] = "UNKNOWN"
    stock: Literal["UNKNOWN"] = "UNKNOWN"
    delivery: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def valid(self) -> Self:
        try:
            if str(uuid.UUID(self.run_id)) != self.run_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("SUPPLIER_CATALOG_RUN_ID_INVALID") from error
        if self.stage != self.request.stage:
            raise ValueError("SUPPLIER_CATALOG_STAGE_INVALID")
        body = self.source_body_sha256 is not None
        if body != (self.source_body_byte_count is not None):
            raise ValueError("SUPPLIER_CATALOG_BODY_BINDING_INVALID")
        parent = (
            (
                self.search_spec is not None
                and self.selected_link is None
                and self.parent_search_report_sha256 is None
            )
            if self.stage == "SEARCH"
            else (
                self.search_spec is None
                and self.selected_link is not None
                and self.parent_search_report_sha256 is not None
            )
        )
        if self.status == "STARTED":
            ok = (
                parent
                and self.reason_code == "SOURCE_OUTCOME_UNKNOWN"
                and self.observation is None
                and self.links is None
                and self.attempted_source_requests is None
                and not body
            )
        else:
            ok = (
                parent
                and self.reason_code == "FIXED_CATALOG_OBSERVATION"
                and self.observation is not None
                and self.attempted_source_requests == self.observation.dispatch_count
                and body == (self.observation.html_sha256 is not None)
                and self.source_body_sha256 == self.observation.html_sha256
                and self.source_body_byte_count == self.observation.byte_count
                and (
                    (
                        self.stage == "SEARCH"
                        and self.search_spec is not None
                        and self.observation.source_url == self.search_spec.search_url
                        and (
                            (self.observation.status != "COMPLETED" and self.links is None)
                            or (
                                self.observation.status == "COMPLETED"
                                and self.source_body_sha256 is not None
                                and self.links is not None
                                and self.links.source_url == self.observation.final_url
                                and self.links.html_sha256 == self.source_body_sha256
                            )
                        )
                    )
                    or (
                        self.stage == "PRODUCT"
                        and self.links is None
                        and self.selected_link is not None
                        and self.observation.source_url == self.selected_link.url
                    )
                )
            )
        if not ok:
            raise ValueError("SUPPLIER_CATALOG_RESULT_CONFLICT")
        return self


class SavedSupplierCatalog(Frozen):
    report: SupplierCatalogReport
    created: bool = Field(strict=True)
    source_requests: int = Field(ge=0, le=3, strict=True)
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def io(self) -> Self:
        if self.source_requests != (self.report.attempted_source_requests if self.created else 0):
            raise ValueError("SUPPLIER_CATALOG_IO_CONFLICT")
        return self


def _digest(v: object) -> str:
    return hashlib.sha256(
        json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _page(
    conn: Connection, company: str, request: SupplierCatalogRequest, *, body: bool
) -> tuple[SupplierPageReport, str, bytes | None, str]:
    position = _position(conn, company, request.page.position)
    position_sha = _position_basis(position)
    meta = (
        conn.execute(
            select(
                page_runs.c.report_sha256,
                page_runs.c.created_at,
                page_runs.c.source_body_sha256,
                page_runs.c.source_body_byte_count,
                func.octet_length(cast(page_runs.c.report, Text)).label("size"),
                func.octet_length(page_runs.c.source_body).label("body_size"),
            ).where(page_runs.c.company_id == company, page_runs.c.run_id == request.page_run_id)
        )
        .mappings()
        .one_or_none()
    )
    if meta is None:
        raise LookupError("SUPPLIER_CATALOG_PAGE_NOT_FOUND")
    if meta["size"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_CATALOG_PARENT_LIMIT")
    payload = conn.scalar(
        select(page_runs.c.report).where(
            page_runs.c.company_id == company, page_runs.c.run_id == request.page_run_id
        )
    )
    sha = _digest(payload)
    if sha != meta["report_sha256"]:
        raise ValueError("SUPPLIER_CATALOG_PARENT_DIGEST_CONFLICT")
    report = SupplierPageReport.model_validate(payload)
    if (
        report.request != request.page
        or report.position_sha256 != position_sha
        or report.run_id != request.page_run_id
        or report.created_at != meta["created_at"]
        or report.status != "COMPLETED"
        or report.observation is None
        or report.observation.status != "COMPLETED"
        or report.source_body_byte_count is None
        or not 1 <= report.source_body_byte_count <= MAX_BODY_BYTES
        or report.source_body_sha256 != meta["source_body_sha256"]
        or report.source_body_byte_count != meta["source_body_byte_count"]
        or report.source_body_byte_count != meta["body_size"]
    ):
        raise ValueError("SUPPLIER_CATALOG_PARENT_EVIDENCE_CONFLICT")
    content = (
        conn.scalar(
            select(page_runs.c.source_body).where(
                page_runs.c.company_id == company, page_runs.c.run_id == request.page_run_id
            )
        )
        if body
        else None
    )
    if body and (
        not isinstance(content, bytes)
        or hashlib.sha256(content).hexdigest() != report.source_body_sha256
    ):
        raise ValueError("SUPPLIER_CATALOG_PARENT_EVIDENCE_CONFLICT")
    return report, sha, content, position_sha


def _search_parent(
    conn: Connection,
    company: str,
    request: SupplierCatalogRequest,
    position_sha: str,
    page_sha: str,
) -> tuple[SupplierCatalogReport, str, CatalogLink]:
    meta = (
        conn.execute(
            select(
                runs.c.report_sha256,
                runs.c.created_at,
                func.octet_length(cast(runs.c.report, Text)).label("size"),
            ).where(runs.c.company_id == company, runs.c.run_id == request.search_run_id)
        )
        .mappings()
        .one_or_none()
    )
    if meta is None:
        raise LookupError("SUPPLIER_CATALOG_SEARCH_NOT_FOUND")
    if meta["size"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_CATALOG_SEARCH_EVIDENCE_CONFLICT")
    payload = conn.scalar(
        select(runs.c.report).where(
            runs.c.company_id == company, runs.c.run_id == request.search_run_id
        )
    )
    sha = _digest(payload)
    if sha != meta["report_sha256"]:
        raise ValueError("SUPPLIER_CATALOG_SEARCH_EVIDENCE_CONFLICT")
    report = SupplierCatalogReport.model_validate(payload)
    if (
        report.stage != "SEARCH"
        or report.status != "COMPLETED"
        or report.request.page != request.page
        or report.request.page_run_id != request.page_run_id
        or report.position_sha256 != position_sha
        or report.parent_page_report_sha256 != page_sha
        or report.run_id != request.search_run_id
        or report.created_at != meta["created_at"]
        or report.links is None
        or report.observation is None
        or report.observation.status != "COMPLETED"
    ):
        raise ValueError("SUPPLIER_CATALOG_SEARCH_EVIDENCE_CONFLICT")
    link = next((x for x in report.links.links if x.index == request.product_index), None)
    if link is None:
        raise LookupError("SUPPLIER_CATALOG_PRODUCT_NOT_FOUND")
    return report, sha, link


def _key(
    r: SupplierCatalogRequest, page_sha: str, position_sha: str, search_sha: str | None
) -> str:
    return _digest(
        {
            "policy": POLICY,
            "request": r.model_dump(mode="json"),
            "page": page_sha,
            "position": position_sha,
            "search": search_sha,
        }
    )


def _cached(
    conn: Connection,
    company: str,
    key: str,
    request: SupplierCatalogRequest,
    page_sha: str,
    position_sha: str,
    search_sha: str | None,
    resolved_link: CatalogLink | None,
) -> SupplierCatalogReport | None:
    scope = and_(runs.c.company_id == company, runs.c.cache_key == key)
    meta = (
        conn.execute(
            select(
                runs.c.run_id,
                runs.c.report_sha256,
                runs.c.created_at,
                runs.c.source_body_sha256,
                runs.c.source_body_byte_count,
                func.octet_length(cast(runs.c.report, Text)).label("size"),
                func.octet_length(runs.c.source_body).label("body_size"),
            )
            .where(scope)
            .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if meta is None:
        return None
    if meta["size"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_CATALOG_EVIDENCE_CONFLICT")
    payload = conn.scalar(select(runs.c.report).where(scope, runs.c.run_id == meta["run_id"]))
    report = SupplierCatalogReport.model_validate(payload)
    if (
        _digest(payload) != meta["report_sha256"]
        or report.request != request
        or report.parent_page_report_sha256 != page_sha
        or report.position_sha256 != position_sha
        or report.parent_search_report_sha256 != search_sha
        or report.selected_link != resolved_link
        or report.run_id != meta["run_id"]
        or report.created_at != meta["created_at"]
        or report.source_body_sha256 != meta["source_body_sha256"]
        or report.source_body_byte_count != meta["source_body_byte_count"]
        or report.source_body_byte_count != meta["body_size"]
    ):
        raise ValueError("SUPPLIER_CATALOG_EVIDENCE_CONFLICT")
    return report


def _append(
    conn: Connection,
    company: str,
    report: SupplierCatalogReport,
    key: str,
    body: bytes | None,
    actor: str,
) -> None:
    sha = hashlib.sha256(body).hexdigest() if body else None
    count = len(body) if body else None
    if (sha, count) != (report.source_body_sha256, report.source_body_byte_count):
        raise ValueError("SUPPLIER_CATALOG_BODY_BINDING_INVALID")
    payload = report.model_dump(mode="json")
    ref = report.request.page.position.selection.notice
    conn.execute(
        insert(runs).values(
            company_id=company,
            run_id=report.run_id,
            cache_key=key,
            purchase_number=ref.purchase_number,
            version_number=ref.version_number,
            notice_xml_sha256=ref.notice_xml_sha256,
            source_index=report.request.page.position.selection.source_index,
            parent_page_run_id=report.request.page_run_id,
            stage=report.stage,
            parent_search_run_id=report.request.search_run_id,
            product_index=report.request.product_index,
            report=payload,
            report_sha256=_digest(payload),
            created_at=report.created_at,
            source_body=body,
            source_body_sha256=sha,
            source_body_byte_count=count,
        )
    )
    _audit(
        conn,
        company,
        actor,
        ref,
        "EIS_SUPPLIER_CATALOG_SAVED",
        {
            "run_id": report.run_id,
            "stage": report.stage,
            "status": report.status,
            "policy_version": POLICY,
        },
    )


def _budget(conn: Connection, company: str, now: datetime) -> None:
    page_count = (
        select(func.count())
        .select_from(page_runs)
        .where(
            page_runs.c.company_id == company,
            page_runs.c.created_at >= now - timedelta(hours=1),
            page_runs.c.report["status"].astext == "STARTED",
        )
    )
    cat_count = (
        select(func.count())
        .select_from(runs)
        .where(
            runs.c.company_id == company,
            runs.c.created_at >= now - timedelta(hours=1),
            runs.c.report["status"].astext == "STARTED",
        )
    )
    if int(conn.scalar(page_count) or 0) + int(conn.scalar(cat_count) or 0) >= HOURLY_NEW_RUNS:
        raise ValueError("SUPPLIER_CATALOG_HOURLY_LIMIT")
    page_bytes = select(func.coalesce(func.sum(page_runs.c.source_body_byte_count), 0)).where(
        page_runs.c.company_id == company, page_runs.c.created_at >= now - timedelta(hours=24)
    )
    cat_bytes = select(func.coalesce(func.sum(runs.c.source_body_byte_count), 0)).where(
        runs.c.company_id == company, runs.c.created_at >= now - timedelta(hours=24)
    )
    if (
        int(conn.scalar(page_bytes) or 0) + int(conn.scalar(cat_bytes) or 0)
        > DAILY_BODY_BYTES - MAX_BODY_BYTES
    ):
        raise ValueError("SUPPLIER_CATALOG_DAILY_BODY_LIMIT")


def _context(
    conn: Connection, company: str, request: SupplierCatalogRequest, *, page_body: bool
) -> tuple[SupplierPageReport, str, bytes | None, str, str | None, CatalogLink | None]:
    page, page_sha, content, position_sha = _page(conn, company, request, body=page_body)
    search_sha = None
    link = None
    if request.stage == "PRODUCT":
        _, search_sha, link = _search_parent(conn, company, request, position_sha, page_sha)
    return page, page_sha, content, position_sha, search_sha, link


def read_supplier_catalog(
    storage: PostgresStorage, company: str, request: SupplierCatalogRequest
) -> SavedSupplierCatalog:
    with storage.transaction(company, consistent_read=True) as conn:
        _, page_sha, _, position_sha, search_sha, link = _context(
            conn, company, request, page_body=False
        )
        key = _key(request, page_sha, position_sha, search_sha)
        report = _cached(conn, company, key, request, page_sha, position_sha, search_sha, link)
        if report is None:
            raise LookupError("SUPPLIER_CATALOG_NOT_FOUND")
        return SavedSupplierCatalog(report=report, created=False, source_requests=0)


def prepare_supplier_catalog(
    storage: PostgresStorage,
    company: str,
    request: SupplierCatalogRequest,
    *,
    actor_id: str,
    refresh: bool = False,
) -> SavedSupplierCatalog:
    if not actor_id.strip() or type(refresh) is not bool:
        raise ValueError("SUPPLIER_CATALOG_REQUEST_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        _, page_sha, _, position_sha, search_sha, link = _context(
            conn, company, request, page_body=False
        )
        key = _key(request, page_sha, position_sha, search_sha)
        cached = _cached(conn, company, key, request, page_sha, position_sha, search_sha, link)
        if cached is not None and not refresh:
            return SavedSupplierCatalog(report=cached, created=False, source_requests=0)
        spec = None
    with _run_leases(storage, company, key):
        now = datetime.now(UTC)
        with _tenant_lease(storage, company), _write(storage, company) as conn:
            page2, page_sha2, content2, position_sha2, search_sha2, link2 = _context(
                conn, company, request, page_body=False
            )
            if (page_sha2, position_sha2, search_sha2, link2) != (
                page_sha,
                position_sha,
                search_sha,
                link,
            ):
                raise ValueError("SUPPLIER_CATALOG_SOURCE_CHANGED")
            cached = _cached(conn, company, key, request, page_sha, position_sha, search_sha, link)
            if cached is not None:
                if not refresh:
                    return SavedSupplierCatalog(report=cached, created=False, source_requests=0)
                if now - cached.created_at < REFRESH_COOLDOWN:
                    raise ValueError("SUPPLIER_CATALOG_REFRESH_COOLDOWN")
            _budget(conn, company, now)
            if request.stage == "SEARCH":
                page2, hydrated_sha, content2, hydrated_position = _page(
                    conn, company, request, body=True
                )
                if hydrated_sha != page_sha or hydrated_position != position_sha:
                    raise ValueError("SUPPLIER_CATALOG_SOURCE_CHANGED")
                name = _position(conn, company, request.page.position).position.name.value
                spec = (
                    build_catalog_search(page2.observation.final_url, content2, name)
                    if page2.observation and isinstance(name, str) and content2
                    else None
                )
                if spec is None:
                    raise ValueError("SUPPLIER_CATALOG_SEARCH_UNSUPPORTED")
            started = SupplierCatalogReport(
                run_id=str(uuid.uuid4()),
                request=request,
                parent_page_report_sha256=page_sha,
                position_sha256=position_sha,
                created_at=now,
                stage=request.stage,
                search_spec=spec,
                selected_link=link,
                parent_search_report_sha256=search_sha,
                status="STARTED",
                reason_code="SOURCE_OUTCOME_UNKNOWN",
                observation=None,
                links=None,
                attempted_source_requests=None,
            )
            _append(conn, company, started, key, None, actor_id)
        if spec is None and link is None:
            raise ValueError("SUPPLIER_CATALOG_STAGE_INVALID")
        if spec is not None:
            target = spec.search_url
        else:
            assert link is not None
            target = link.url
        capture = observe_supplier_page(target, allowed_host="bumaga-s.ru")
        if request.stage == "PRODUCT":
            capture = enrich_catalog_product(capture)
        body = capture.content
        sha = hashlib.sha256(body).hexdigest() if body else None
        count = len(body) if body else None
        links = (
            parse_catalog_links(capture.observation.final_url, body)
            if (
                request.stage == "SEARCH"
                and capture.observation.status == "COMPLETED"
                and body is not None
            )
            else None
        )
        with _tenant_lease(storage, company), _write(storage, company) as conn:
            _, page_sha2, _, position_sha2, search_sha2, link2 = _context(
                conn, company, request, page_body=False
            )
            if (page_sha2, position_sha2, search_sha2, link2) != (
                page_sha,
                position_sha,
                search_sha,
                link,
            ):
                raise ValueError("SUPPLIER_CATALOG_SOURCE_CHANGED")
            report = SupplierCatalogReport(
                run_id=str(uuid.uuid4()),
                request=request,
                parent_page_report_sha256=page_sha,
                position_sha256=position_sha,
                created_at=datetime.now(UTC),
                stage=request.stage,
                search_spec=spec,
                selected_link=link,
                parent_search_report_sha256=search_sha,
                status="COMPLETED",
                reason_code="FIXED_CATALOG_OBSERVATION",
                observation=capture.observation,
                links=links,
                attempted_source_requests=capture.observation.dispatch_count,
                source_body_sha256=sha,
                source_body_byte_count=count,
            )
            _append(conn, company, report, key, body, actor_id)
            return SavedSupplierCatalog(
                report=report, created=True, source_requests=capture.observation.dispatch_count
            )
