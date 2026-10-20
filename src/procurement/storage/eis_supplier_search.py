"""Exact-position supplier observations; immutable, bounded, never quotes or admission."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Text, and_, func, insert, select, text
from sqlalchemy.engine import Connection

from procurement.sources.catalog_routes import servermall_covers
from procurement.sources.eis_223_archive import TextFact
from procurement.sources.eis_characteristic_compare import PositionSelection, SavedPosition
from procurement.sources.eis_supplier_catalog import (
    SupplierCatalogCapture,
    SupplierCatalogObservation,
    SupplierCatalogSourceError,
    observe_servermall_hpe_gen12,
)
from procurement.storage.eis_characteristic_compare import read_saved_position_connection
from procurement.storage.eis_document_store import _audit, _latest
from procurement.storage.models import eis_supplier_search_runs as runs
from procurement.storage.repository import PostgresStorage

POLICY: Literal["eis-position-supplier-search-v1"] = "eis-position-supplier-search-v1"
MAX_REPORT_BYTES = 256 * 1024
REFRESH_COOLDOWN = timedelta(minutes=15)


class SupplierSearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    selection: PositionSelection

    @field_validator("selection", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if isinstance(value, dict):
            notice = value.get("notice")
            if isinstance(notice, dict) and type(notice.get("version_number")) is not int:
                raise ValueError("SUPPLIER_SEARCH_VERSION_INVALID")
        return value


class SupplierSearchReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_version: Literal["eis-position-supplier-search-v1"] = POLICY
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    request: SupplierSearchRequest
    position_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_name: TextFact
    query: Literal["сервер", "hpe", "dl360", "dl380"] | None
    query_scope: Literal["FIXED_CATEGORY_ROUTE_FROM_POSITION_NAME"] = (
        "FIXED_CATEGORY_ROUTE_FROM_POSITION_NAME"
    )
    status: Literal["STARTED", "COMPLETED", "QUERY_NOT_COVERED", "SOURCE_ERROR"]
    reason_code: Literal[
        "FIXED_CATEGORY_SNAPSHOT",
        "CATEGORY_NOT_SUPPORTED",
        "CATALOG_UNAVAILABLE_OR_CHANGED",
        "SOURCE_OUTCOME_UNKNOWN",
    ]
    created_at: AwareDatetime
    observation: SupplierCatalogObservation | None
    attempted_source_requests: int | None = Field(strict=True, ge=0, le=1)
    specification_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    position_document_association: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    profit: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> SupplierSearchReport:
        if str(uuid.UUID(self.run_id)) != self.run_id:
            raise ValueError("SUPPLIER_SEARCH_RUN_ID_INVALID")
        if (
            self.position_name.provenance.document_id
            != self.request.selection.notice.notice_xml_sha256
        ):
            raise ValueError("SUPPLIER_SEARCH_POSITION_PROVENANCE_CONFLICT")
        if self.query != _query(self.position_name.value):
            raise ValueError("SUPPLIER_SEARCH_QUERY_CONFLICT")
        if self.status == "COMPLETED":
            if (
                self.observation is None
                or self.query is None
                or self.observation.query != self.query
                or self.reason_code != "FIXED_CATEGORY_SNAPSHOT"
                or self.attempted_source_requests != 1
            ):
                raise ValueError("SUPPLIER_SEARCH_RESULT_CONFLICT")
        elif self.observation is not None:
            raise ValueError("SUPPLIER_SEARCH_RESULT_CONFLICT")
        elif self.status == "STARTED":
            if (
                self.query is None
                or self.attempted_source_requests is not None
                or self.reason_code != "SOURCE_OUTCOME_UNKNOWN"
            ):
                raise ValueError("SUPPLIER_SEARCH_RESULT_CONFLICT")
        elif self.status == "QUERY_NOT_COVERED":
            if (
                self.query is not None
                or self.attempted_source_requests != 0
                or self.reason_code != "CATEGORY_NOT_SUPPORTED"
            ):
                raise ValueError("SUPPLIER_SEARCH_RESULT_CONFLICT")
        elif (
            self.query is None
            or self.attempted_source_requests != 1
            or self.reason_code != "CATALOG_UNAVAILABLE_OR_CHANGED"
        ):
            raise ValueError("SUPPLIER_SEARCH_RESULT_CONFLICT")
        return self


class SavedSupplierSearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    report: SupplierSearchReport
    created: bool = Field(strict=True)
    source_requests: int = Field(strict=True, ge=0, le=1)
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def actual_io(self) -> SavedSupplierSearch:
        expected = self.report.attempted_source_requests if self.created else 0
        if self.source_requests != expected:
            raise ValueError("SUPPLIER_SEARCH_IO_CONFLICT")
        return self


def _query(name: str | None) -> str | None:
    """Conservative routing only; no specification/BOM matching or user URLs."""
    if not name or len(name) > 400 or not servermall_covers(name):
        return None
    if re.search(
        r"\b(?:работ[а-яё]*|услуг[а-яё]*|ремонт[а-яё]*|обслуживан[а-яё]*|помещен[а-яё]*|аренд[а-яё]*|лицензи[а-яё]*)\b",
        name,
        re.I,
    ):
        return None
    if not re.search(
        r"\b(?:сервер(?:а|ов|ы|ом|ам|ами|е|у|ах)?|hpe|proliant|dl360|dl380)\b|\bсерверн(?:ое|ого|ому|ым)\s+оборудован",
        name,
        re.I,
    ):
        return None
    for term in ("dl360", "dl380", "hpe"):
        if re.search(rf"\b{term}\b", name, re.I):
            return term
    return "hpe"


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _position(conn: Connection, company: str, request: SupplierSearchRequest) -> SavedPosition:
    started = monotonic()

    def budget() -> None:
        remaining = int((15 - (monotonic() - started)) * 1000)
        if remaining <= 0:
            raise ValueError("SUPPLIER_SEARCH_TIME_LIMIT")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout='{min(remaining, 5000)}ms'")

    budget()
    conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
    conn.exec_driver_sql("SET LOCAL jit=off")
    saved = read_saved_position_connection(conn, company, request.selection, budget=budget)
    ref = request.selection.notice
    budget()
    if _latest(conn, company, ref.purchase_number) != (ref.version_number, ref.notice_xml_sha256):
        raise ValueError("NOTICE_VERSION_STALE")
    return saved


def _basis(saved: SavedPosition) -> tuple[str, str]:
    position_sha = _digest(saved.model_dump(mode="json"))
    return position_sha, _digest({"policy": POLICY, "position": position_sha})


def _cached(
    conn: Connection, company: str, request: SupplierSearchRequest, saved: SavedPosition, key: str
) -> SupplierSearchReport | None:
    scope = and_(runs.c.company_id == company, runs.c.cache_key == key)
    meta = (
        conn.execute(
            select(
                runs.c.run_id,
                runs.c.report_sha256,
                runs.c.created_at,
                runs.c.source_sha256,
                runs.c.source_byte_count,
                func.octet_length(runs.c.report.cast(Text)).label("payload_bytes"),
                func.octet_length(runs.c.source_content).label("blob_bytes"),
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
    if meta["payload_bytes"] > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_SEARCH_REPORT_LIMIT")
    if meta["blob_bytes"] is not None and not 0 < meta["blob_bytes"] <= 2 * 1024**2:
        raise ValueError("SUPPLIER_SEARCH_BLOB_LIMIT")
    payload = conn.scalar(select(runs.c.report).where(scope, runs.c.run_id == meta["run_id"]))
    if _digest(payload) != meta["report_sha256"]:
        raise ValueError("SUPPLIER_SEARCH_DIGEST_CONFLICT")
    result = SupplierSearchReport.model_validate(payload)
    position_sha, _ = _basis(saved)
    if (
        result.request != request
        or result.position_sha256 != position_sha
        or result.position_name != saved.position.name
        or result.run_id != meta["run_id"]
        or result.created_at != meta["created_at"]
    ):
        raise ValueError("SUPPLIER_SEARCH_EVIDENCE_CONFLICT")
    observation = result.observation
    if observation is None:
        if any(
            meta[field] is not None
            for field in ("source_sha256", "source_byte_count", "blob_bytes")
        ):
            raise ValueError("SUPPLIER_SEARCH_EVIDENCE_CONFLICT")
    elif (
        observation.source_sha256 != meta["source_sha256"]
        or observation.byte_count != meta["source_byte_count"]
        or observation.byte_count != meta["blob_bytes"]
    ):
        raise ValueError("SUPPLIER_SEARCH_EVIDENCE_CONFLICT")
    # Blob SHA was checked by PostgreSQL on immutable insert; read never hydrates bytea.
    return result


def read_supplier_search(
    storage: PostgresStorage, company: str, request: SupplierSearchRequest
) -> SavedSupplierSearch:
    """Read latest exact-basis outcome; never hide a failed refresh with older success."""
    with storage.transaction(company, consistent_read=True) as conn:
        saved = _position(conn, company, request)
        _, key = _basis(saved)
        report = _cached(conn, company, request, saved, key)
        if report is None:
            raise LookupError("SUPPLIER_SEARCH_NOT_FOUND")
        return SavedSupplierSearch(report=report, created=False, source_requests=0)


def _append(
    storage: PostgresStorage,
    company: str,
    request: SupplierSearchRequest,
    *,
    actor_id: str,
    report: SupplierSearchReport,
    position_sha: str,
    key: str,
    capture: SupplierCatalogCapture | None,
) -> None:
    payload = report.model_dump(mode="json")
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_SEARCH_REPORT_LIMIT")
    with storage.transaction(company) as conn:
        # Serialize the short append with ordinary tenant writes. Source I/O
        # is complete; guards see any committed import/projection/hold now.
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company},
        )
        current = _position(conn, company, request)
        if _basis(current) != (position_sha, key):
            raise ValueError("SUPPLIER_SEARCH_POSITION_CHANGED")
        conn.execute(
            insert(runs).values(
                company_id=company,
                run_id=report.run_id,
                cache_key=key,
                purchase_number=request.selection.notice.purchase_number,
                version_number=request.selection.notice.version_number,
                notice_xml_sha256=request.selection.notice.notice_xml_sha256,
                source_index=request.selection.source_index,
                report=payload,
                report_sha256=_digest(payload),
                source_content=capture.content if capture else None,
                source_sha256=capture.observation.source_sha256 if capture else None,
                source_byte_count=capture.observation.byte_count if capture else None,
                created_at=report.created_at,
            )
        )
        _audit(
            conn,
            company,
            actor_id,
            request.selection.notice,
            "EIS_SUPPLIER_SEARCH_SAVED",
            {
                "run_id": report.run_id,
                "source_index": request.selection.source_index,
                "report_sha256": _digest(payload),
                "status": report.status,
                "attempted_source_requests": report.attempted_source_requests,
                "policy_version": POLICY,
            },
        )


def prepare_supplier_search(
    storage: PostgresStorage,
    company: str,
    request: SupplierSearchRequest,
    *,
    actor_id: str,
    refresh: bool = False,
) -> SavedSupplierSearch:
    """Explicit bounded GET outside DB transactions; append only after rechecking basis."""
    if not actor_id.strip() or type(refresh) is not bool:
        raise ValueError("SUPPLIER_SEARCH_REQUEST_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        saved = _position(conn, company, request)
        position_sha, key = _basis(saved)
        cached = _cached(conn, company, request, saved, key)
        if cached is not None and not refresh:
            return SavedSupplierSearch(report=cached, created=False, source_requests=0)
    # A per-search session lease, not the broad tenant import lock. No transaction
    # or tenant context remains open while reading the supplier's public page.
    with storage._engine.connect() as lease:
        lock_key = "supplier-search/" + company + "/" + key
        acquired = lease.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": lock_key}
        )
        lease.commit()
        if not acquired:
            raise ValueError("SUPPLIER_SEARCH_BUSY")
        try:
            with storage.transaction(company, consistent_read=True) as conn:
                current = _position(conn, company, request)
                if _basis(current) != (position_sha, key):
                    raise ValueError("SUPPLIER_SEARCH_POSITION_CHANGED")
                cached = _cached(conn, company, request, current, key)
                if cached is not None:
                    if not refresh:
                        return SavedSupplierSearch(report=cached, created=False, source_requests=0)
                    if datetime.now(UTC) - cached.created_at < REFRESH_COOLDOWN:
                        raise ValueError("SUPPLIER_SEARCH_REFRESH_COOLDOWN")
            query = _query(saved.position.name.value)
            capture: SupplierCatalogCapture | None = None
            status, reason, attempted = "QUERY_NOT_COVERED", "CATEGORY_NOT_SUPPORTED", 0
            if query is not None:
                started_report = SupplierSearchReport(
                    run_id=str(uuid.uuid4()),
                    request=request,
                    position_sha256=position_sha,
                    position_name=saved.position.name,
                    query=query,
                    status="STARTED",
                    reason_code="SOURCE_OUTCOME_UNKNOWN",
                    created_at=datetime.now(UTC),
                    observation=None,
                    attempted_source_requests=None,
                )
                _append(
                    storage,
                    company,
                    request,
                    actor_id=actor_id,
                    report=started_report,
                    position_sha=position_sha,
                    key=key,
                    capture=None,
                )
                attempted = 1
                try:
                    capture = observe_servermall_hpe_gen12(query)
                    status, reason = "COMPLETED", "FIXED_CATEGORY_SNAPSHOT"
                except (SupplierCatalogSourceError, ValueError, RecursionError):
                    status, reason = "SOURCE_ERROR", "CATALOG_UNAVAILABLE_OR_CHANGED"
            report = SupplierSearchReport(
                run_id=str(uuid.uuid4()),
                request=request,
                position_sha256=position_sha,
                position_name=saved.position.name,
                query=query,
                status=status,
                reason_code=reason,
                created_at=datetime.now(UTC),
                observation=capture.observation if capture else None,
                attempted_source_requests=attempted,
            )
            payload = report.model_dump(mode="json")
            if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
                raise ValueError("SUPPLIER_SEARCH_REPORT_LIMIT")
            _append(
                storage,
                company,
                request,
                actor_id=actor_id,
                report=report,
                position_sha=position_sha,
                key=key,
                capture=capture,
            )
            return SavedSupplierSearch(report=report, created=True, source_requests=attempted)
        finally:
            lease.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": lock_key}
            )
            lease.commit()
