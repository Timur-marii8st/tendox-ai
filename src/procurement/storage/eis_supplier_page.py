"""Immutable observations of one exact public link from an exact SERP run."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Text, and_, cast, func, insert, select, text
from sqlalchemy.engine import Connection

from procurement.sources.eis_characteristic_compare import SavedPosition
from procurement.sources.supplier_page import PageObservation, observe_supplier_page
from procurement.sources.supplier_serp import SearchEngine, SerpLink
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_supplier_search import SupplierSearchRequest, _position
from procurement.storage.eis_supplier_serp import SupplierSerpReport
from procurement.storage.models import eis_supplier_catalog_runs as catalog_runs
from procurement.storage.models import eis_supplier_page_runs as runs
from procurement.storage.models import eis_supplier_serp_runs as serp_runs
from procurement.storage.repository import PostgresStorage, _require_tenant

POLICY: Literal["eis-position-supplier-page-v1"] = "eis-position-supplier-page-v1"
MAX_REPORT_BYTES = 256 * 1024
MAX_BODY_BYTES = 2 * 1024**2
DAILY_BODY_BYTES = 64 * 1024**2
HOURLY_NEW_RUNS = 30
REFRESH_COOLDOWN = timedelta(minutes=15)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupplierPageRequest(FrozenModel):
    position: SupplierSearchRequest
    serp_run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    engine: SearchEngine
    rank: int = Field(ge=1, le=50, strict=True)

    @model_validator(mode="after")
    def canonical(self) -> Self:
        try:
            if str(uuid.UUID(self.serp_run_id)) != self.serp_run_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("SUPPLIER_PAGE_SERP_ID_INVALID") from error
        return self


class SupplierPageReport(FrozenModel):
    policy_version: Literal["eis-position-supplier-page-v1"] = POLICY
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    request: SupplierPageRequest
    parent_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    link: SerpLink
    created_at: AwareDatetime
    status: Literal["STARTED", "COMPLETED"]
    reason_code: Literal["SOURCE_OUTCOME_UNKNOWN", "FIXED_PUBLIC_PAGE_OBSERVATION"]
    observation: PageObservation | None
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
    def consistent(self) -> Self:
        try:
            if str(uuid.UUID(self.run_id)) != self.run_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("SUPPLIER_PAGE_RUN_ID_INVALID") from error
        body = self.source_body_sha256 is not None
        if body != (self.source_body_byte_count is not None):
            raise ValueError("SUPPLIER_PAGE_BODY_BINDING_INVALID")
        if self.status == "STARTED":
            valid = (
                self.reason_code == "SOURCE_OUTCOME_UNKNOWN"
                and self.observation is None
                and self.attempted_source_requests is None
                and not body
            )
        else:
            valid = (
                self.reason_code == "FIXED_PUBLIC_PAGE_OBSERVATION"
                and self.observation is not None
                and self.observation.source_url == self.link.url
                and self.attempted_source_requests == self.observation.dispatch_count
                and body == (self.observation.html_sha256 is not None)
                and self.source_body_sha256 == self.observation.html_sha256
                and self.source_body_byte_count == self.observation.byte_count
            )
        if not valid:
            raise ValueError("SUPPLIER_PAGE_RESULT_CONFLICT")
        return self


class SavedSupplierPage(FrozenModel):
    report: SupplierPageReport
    created: bool = Field(strict=True)
    source_requests: int = Field(ge=0, le=3, strict=True)
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def io(self) -> Self:
        if self.source_requests != (self.report.attempted_source_requests if self.created else 0):
            raise ValueError("SUPPLIER_PAGE_IO_CONFLICT")
        return self


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _position_basis(position: SavedPosition) -> str:
    return _digest(position.model_dump(mode="json"))


def _key(request: SupplierPageRequest, parent_sha: str, position_sha: str) -> str:
    return _digest(
        {
            "policy": POLICY,
            "request": request.model_dump(mode="json"),
            "parent": parent_sha,
            "position": position_sha,
        }
    )


@contextmanager
def _tenant_lease(storage: PostgresStorage, company: str) -> Iterator[None]:
    key = _require_tenant(company)
    with storage._engine.connect() as conn:
        ok = conn.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key}
        )
        conn.commit()
        if not ok:
            raise ValueError("SUPPLIER_PAGE_TENANT_BUSY")
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": key})
            conn.commit()


@contextmanager
def _run_leases(storage: PostgresStorage, company: str, key: str) -> Iterator[None]:
    keys = (f"supplier-page/global/{company}", f"supplier-page/request/{company}/{key}")
    with storage._engine.connect() as conn:
        held = []
        try:
            for item in keys:
                if not conn.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": item}
                ):
                    raise ValueError("SUPPLIER_PAGE_BUSY")
                held.append(item)
            conn.commit()
            yield
        finally:
            for item in reversed(held):
                conn.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": item}
                )
            conn.commit()


@contextmanager
def _write(storage: PostgresStorage, company: str) -> Iterator[Connection]:
    with storage._engine.execution_options(isolation_level="REPEATABLE READ").begin() as conn:
        conn.execute(
            text("SELECT set_config('app.company_id',:company,true)"),
            {"company": _require_tenant(company)},
        )
        yield conn


def _parent(
    conn: Connection, company: str, request: SupplierPageRequest, position: SavedPosition
) -> tuple[SupplierSerpReport, str, SerpLink]:
    meta = (
        conn.execute(
            select(
                serp_runs.c.report_sha256,
                serp_runs.c.created_at,
                serp_runs.c.purchase_number,
                serp_runs.c.version_number,
                serp_runs.c.notice_xml_sha256,
                serp_runs.c.source_index,
                func.octet_length(cast(serp_runs.c.report, Text)).label("size"),
            ).where(serp_runs.c.company_id == company, serp_runs.c.run_id == request.serp_run_id)
        )
        .mappings()
        .one_or_none()
    )
    if meta is None:
        raise LookupError("SUPPLIER_PAGE_PARENT_NOT_FOUND")
    if meta["size"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_PAGE_PARENT_LIMIT")
    payload = conn.scalar(
        select(serp_runs.c.report).where(
            serp_runs.c.company_id == company, serp_runs.c.run_id == request.serp_run_id
        )
    )
    if _digest(payload) != meta["report_sha256"]:
        raise ValueError("SUPPLIER_PAGE_PARENT_DIGEST_CONFLICT")
    report = SupplierSerpReport.model_validate(payload)
    ref = request.position.selection.notice
    if (
        report.request != request.position
        or report.position_sha256 != _position_basis(position)
        or report.run_id != request.serp_run_id
        or report.created_at != meta["created_at"]
        or meta["purchase_number"] != ref.purchase_number
        or meta["version_number"] != ref.version_number
        or meta["notice_xml_sha256"] != ref.notice_xml_sha256
        or meta["source_index"] != request.position.selection.source_index
        or report.batch is None
    ):
        raise ValueError("SUPPLIER_PAGE_PARENT_EVIDENCE_CONFLICT")
    attempt = next((a for a in report.batch.attempts if a.engine == request.engine), None)
    link = next((x for x in attempt.links if x.rank == request.rank), None) if attempt else None
    if link is None:
        raise LookupError("SUPPLIER_PAGE_LINK_NOT_FOUND")
    return report, meta["report_sha256"], link


def _cached(
    conn: Connection,
    company: str,
    request: SupplierPageRequest,
    key: str,
    parent_sha: str,
    position_sha: str,
    link: SerpLink,
) -> SupplierPageReport | None:
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
        raise ValueError("SUPPLIER_PAGE_REPORT_LIMIT")
    payload = conn.scalar(select(runs.c.report).where(scope, runs.c.run_id == meta["run_id"]))
    if _digest(payload) != meta["report_sha256"]:
        raise ValueError("SUPPLIER_PAGE_DIGEST_CONFLICT")
    report = SupplierPageReport.model_validate(payload)
    if (
        report.request != request
        or report.parent_report_sha256 != parent_sha
        or report.position_sha256 != position_sha
        or report.link != link
        or report.run_id != meta["run_id"]
        or report.created_at != meta["created_at"]
        or report.source_body_sha256 != meta["source_body_sha256"]
        or report.source_body_byte_count != meta["source_body_byte_count"]
        or report.source_body_byte_count != meta["body_size"]
    ):
        raise ValueError("SUPPLIER_PAGE_EVIDENCE_CONFLICT")
    return report


def _append(
    conn: Connection,
    company: str,
    report: SupplierPageReport,
    key: str,
    body: bytes | None,
    actor_id: str,
) -> None:
    sha = hashlib.sha256(body).hexdigest() if body else None
    count = len(body) if body else None
    if (sha, count) != (report.source_body_sha256, report.source_body_byte_count):
        raise ValueError("SUPPLIER_PAGE_BODY_BINDING_INVALID")
    payload = report.model_dump(mode="json")
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_PAGE_REPORT_LIMIT")
    ref = report.request.position.selection.notice
    conn.execute(
        insert(runs).values(
            company_id=company,
            run_id=report.run_id,
            cache_key=key,
            purchase_number=ref.purchase_number,
            version_number=ref.version_number,
            notice_xml_sha256=ref.notice_xml_sha256,
            source_index=report.request.position.selection.source_index,
            parent_serp_run_id=report.request.serp_run_id,
            engine=report.request.engine.value,
            rank=report.request.rank,
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
        actor_id,
        ref,
        "EIS_SUPPLIER_PAGE_SAVED",
        {
            "run_id": report.run_id,
            "parent_serp_run_id": report.request.serp_run_id,
            "status": report.status,
            "policy_version": POLICY,
        },
    )


def _budget(conn: Connection, company: str, now: datetime) -> None:
    page_count = int(
        conn.scalar(
            select(func.count())
            .select_from(runs)
            .where(
                runs.c.company_id == company,
                runs.c.created_at >= now - timedelta(hours=1),
                runs.c.report["status"].astext == "STARTED",
            )
        )
        or 0
    )
    catalog_count = int(
        conn.scalar(
            select(func.count())
            .select_from(catalog_runs)
            .where(
                catalog_runs.c.company_id == company,
                catalog_runs.c.created_at >= now - timedelta(hours=1),
                catalog_runs.c.report["status"].astext == "STARTED",
            )
        )
        or 0
    )
    if page_count + catalog_count >= HOURLY_NEW_RUNS:
        raise ValueError("SUPPLIER_PAGE_HOURLY_LIMIT")
    used = int(
        conn.scalar(
            select(func.coalesce(func.sum(runs.c.source_body_byte_count), 0)).where(
                runs.c.company_id == company, runs.c.created_at >= now - timedelta(hours=24)
            )
        )
        or 0
    )
    used += int(
        conn.scalar(
            select(func.coalesce(func.sum(catalog_runs.c.source_body_byte_count), 0)).where(
                catalog_runs.c.company_id == company,
                catalog_runs.c.created_at >= now - timedelta(hours=24),
            )
        )
        or 0
    )
    if used > DAILY_BODY_BYTES - MAX_BODY_BYTES:
        raise ValueError("SUPPLIER_PAGE_DAILY_BODY_LIMIT")


def read_supplier_page(
    storage: PostgresStorage, company: str, request: SupplierPageRequest
) -> SavedSupplierPage:
    with storage.transaction(company, consistent_read=True) as conn:
        position = _position(conn, company, request.position)
        _, parent_sha, link = _parent(conn, company, request, position)
        position_sha = _position_basis(position)
        key = _key(request, parent_sha, position_sha)
        report = _cached(conn, company, request, key, parent_sha, position_sha, link)
        if report is None:
            raise LookupError("SUPPLIER_PAGE_NOT_FOUND")
        return SavedSupplierPage(report=report, created=False, source_requests=0)


def prepare_supplier_page(
    storage: PostgresStorage,
    company: str,
    request: SupplierPageRequest,
    *,
    actor_id: str,
    refresh: bool = False,
) -> SavedSupplierPage:
    if not actor_id.strip() or type(refresh) is not bool:
        raise ValueError("SUPPLIER_PAGE_REQUEST_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        position = _position(conn, company, request.position)
        _, parent_sha, link = _parent(conn, company, request, position)
        position_sha = _position_basis(position)
        key = _key(request, parent_sha, position_sha)
        cached = _cached(conn, company, request, key, parent_sha, position_sha, link)
        if cached is not None and not refresh:
            return SavedSupplierPage(report=cached, created=False, source_requests=0)
    with _run_leases(storage, company, key):
        now = datetime.now(UTC)
        with _tenant_lease(storage, company), _write(storage, company) as conn:
            current = _position(conn, company, request.position)
            _, current_parent_sha, current_link = _parent(conn, company, request, current)
            if (
                _position_basis(current) != position_sha
                or current_parent_sha != parent_sha
                or current_link != link
            ):
                raise ValueError("SUPPLIER_PAGE_SOURCE_CHANGED")
            cached = _cached(conn, company, request, key, parent_sha, position_sha, link)
            if cached is not None:
                if not refresh:
                    return SavedSupplierPage(report=cached, created=False, source_requests=0)
                if now - cached.created_at < REFRESH_COOLDOWN:
                    raise ValueError("SUPPLIER_PAGE_REFRESH_COOLDOWN")
            _budget(conn, company, now)
            started = SupplierPageReport(
                run_id=str(uuid.uuid4()),
                request=request,
                parent_report_sha256=parent_sha,
                position_sha256=position_sha,
                link=link,
                created_at=now,
                status="STARTED",
                reason_code="SOURCE_OUTCOME_UNKNOWN",
                observation=None,
                attempted_source_requests=None,
            )
            _append(conn, company, started, key, None, actor_id)
        capture = observe_supplier_page(link.url)
        body = capture.content
        sha = hashlib.sha256(body).hexdigest() if body else None
        count = len(body) if body else None
        with _tenant_lease(storage, company), _write(storage, company) as conn:
            current = _position(conn, company, request.position)
            _, current_parent_sha, current_link = _parent(conn, company, request, current)
            if (
                _position_basis(current) != position_sha
                or current_parent_sha != parent_sha
                or current_link != link
            ):
                raise ValueError("SUPPLIER_PAGE_SOURCE_CHANGED")
            report = SupplierPageReport(
                run_id=str(uuid.uuid4()),
                request=request,
                parent_report_sha256=parent_sha,
                position_sha256=position_sha,
                link=link,
                created_at=datetime.now(UTC),
                status="COMPLETED",
                reason_code="FIXED_PUBLIC_PAGE_OBSERVATION",
                observation=capture.observation,
                attempted_source_requests=capture.observation.dispatch_count,
                source_body_sha256=sha,
                source_body_byte_count=count,
            )
            _append(conn, company, report, key, body, actor_id)
            return SavedSupplierPage(
                report=report, created=True, source_requests=capture.observation.dispatch_count
            )
