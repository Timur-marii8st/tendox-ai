"""Immutable exact-position multi-engine SERP observations with source0 replay."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Text, and_, cast, func, insert, select, text
from sqlalchemy.engine import Connection

from procurement.sources.eis_223_archive import TextFact
from procurement.sources.eis_characteristic_compare import SavedPosition
from procurement.sources.supplier_serp import (
    ENGINES,
    HISTORICAL_EXPANDED_ENGINES,
    SearchBatch,
    SearchEngine,
    SerpCapture,
    browser_transport_provenance,
    build_supplier_query,
    observe_supplier_serp,
)
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_supplier_search import SupplierSearchRequest, _position
from procurement.storage.models import eis_supplier_serp_runs as runs
from procurement.storage.repository import PostgresStorage, _require_tenant

HISTORICAL_POLICY = "eis-position-supplier-serp-v2"
POLICY: Literal["eis-position-supplier-serp-v1"] = "eis-position-supplier-serp-v1"
MAX_REPORT_BYTES = 256 * 1024
ACTIVE_MAX_BUNDLE_BYTES = 8 * 1024**2
MAX_BUNDLE_BYTES = 13 * 1024**2
DAILY_BUNDLE_BYTES = 64 * 1024**2
HOURLY_NEW_RUNS = 20
REFRESH_COOLDOWN = timedelta(minutes=15)


class SerpStorageModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupplierSerpReport(SerpStorageModel):
    policy_version: Literal["eis-position-supplier-serp-v1", "eis-position-supplier-serp-v2"] = (
        POLICY
    )
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    request: SupplierSearchRequest
    position_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_name: TextFact
    query: str | None = Field(default=None, max_length=240)
    query_scope: Literal["PUBLIC_POSITION_NAME_FIXED_SUPPLIER_TERMS"] = (
        "PUBLIC_POSITION_NAME_FIXED_SUPPLIER_TERMS"
    )
    status: Literal["STARTED", "QUERY_NOT_COVERED", "COMPLETED", "PARTIAL", "UNAVAILABLE"]
    reason_code: Literal[
        "SOURCE_OUTCOME_UNKNOWN",
        "PUBLIC_POSITION_NAME_UNAVAILABLE",
        "FIXED_MULTI_ENGINE_SERP",
        "ALL_ENGINES_UNAVAILABLE",
    ]
    created_at: AwareDatetime
    batch: SearchBatch | None
    attempted_source_requests: int | None = Field(default=None, ge=0, le=6, strict=True)
    source_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_bundle_byte_count: int | None = Field(
        default=None, ge=1, le=MAX_BUNDLE_BYTES, strict=True
    )
    full_market_coverage: Literal["UNKNOWN"] = "UNKNOWN"
    supplier_identity: Literal["UNKNOWN"] = "UNKNOWN"
    price: Literal["UNKNOWN"] = "UNKNOWN"
    stock: Literal["UNKNOWN"] = "UNKNOWN"
    delivery: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> SupplierSerpReport:
        try:
            if str(uuid.UUID(self.run_id)) != self.run_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("SUPPLIER_SERP_RUN_ID_INVALID") from error
        if self.position_name.provenance.document_id != (
            self.request.selection.notice.notice_xml_sha256
        ):
            raise ValueError("SUPPLIER_SERP_POSITION_PROVENANCE_CONFLICT")
        expected_engines = ENGINES if self.policy_version == POLICY else HISTORICAL_EXPANDED_ENGINES
        if (
            self.batch is not None
            and tuple(a.engine for a in self.batch.attempts) != expected_engines
        ):
            raise ValueError("SUPPLIER_SERP_POLICY_ENGINE_CONFLICT")
        if self.attempted_source_requests is not None and self.attempted_source_requests > len(
            expected_engines
        ):
            raise ValueError("SUPPLIER_SERP_POLICY_IO_CONFLICT")
        if (
            self.policy_version == POLICY
            and self.source_bundle_byte_count is not None
            and self.source_bundle_byte_count > ACTIVE_MAX_BUNDLE_BYTES
        ):
            raise ValueError("SUPPLIER_SERP_BUNDLE_LIMIT")
        bundle_present = self.source_bundle_sha256 is not None
        if bundle_present != (self.source_bundle_byte_count is not None):
            raise ValueError("SUPPLIER_SERP_BUNDLE_BINDING_INVALID")
        if self.status == "STARTED":
            valid = (
                self.query is not None
                and self.batch is None
                and self.attempted_source_requests is None
                and self.reason_code == "SOURCE_OUTCOME_UNKNOWN"
                and not bundle_present
            )
        elif self.status == "QUERY_NOT_COVERED":
            valid = (
                self.query is None
                and self.batch is None
                and self.attempted_source_requests == 0
                and self.reason_code == "PUBLIC_POSITION_NAME_UNAVAILABLE"
                and not bundle_present
            )
        else:
            attempts = (
                sum(a.browser_navigation_count for a in self.batch.attempts) if self.batch else -1
            )
            valid = (
                self.query is not None
                and self.batch is not None
                and self.batch.query == self.query
                and self.batch.status == self.status
                and self.attempted_source_requests == attempts
                and self.reason_code
                == (
                    "ALL_ENGINES_UNAVAILABLE"
                    if self.status == "UNAVAILABLE"
                    else "FIXED_MULTI_ENGINE_SERP"
                )
                and bundle_present
                == any(attempt.dom_sha256 is not None for attempt in self.batch.attempts)
            )
        if not valid:
            raise ValueError("SUPPLIER_SERP_RESULT_CONFLICT")
        return self


class SavedSupplierSerp(SerpStorageModel):
    report: SupplierSerpReport
    created: bool = Field(strict=True)
    source_requests: int = Field(ge=0, le=6, strict=True)
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def actual_io(self) -> SavedSupplierSerp:
        expected = self.report.attempted_source_requests if self.created else 0
        if self.source_requests != expected:
            raise ValueError("SUPPLIER_SERP_IO_CONFLICT")
        return self


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _basis(position: SavedPosition, policy: str = POLICY) -> tuple[str, str]:
    position_sha = _digest(position.model_dump(mode="json"))
    return position_sha, _digest({"policy": policy, "position": position_sha})


@contextmanager
def _tenant_lease(storage: PostgresStorage, company: str) -> Iterator[None]:
    key = _require_tenant(company)
    with storage._engine.connect() as lease:
        acquired = lease.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key}
        )
        lease.commit()
        if not acquired:
            raise ValueError("SUPPLIER_SERP_TENANT_BUSY")
        try:
            yield
        finally:
            lease.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key}
            )
            lease.commit()


@contextmanager
def _run_leases(storage: PostgresStorage, company: str, key: str) -> Iterator[None]:
    keys = (f"supplier-serp/global/{company}", f"supplier-serp/search/{company}/{key}")
    with storage._engine.connect() as lease:
        acquired: list[str] = []
        try:
            for value in keys:
                if not lease.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                    {"key": value},
                ):
                    raise ValueError("SUPPLIER_SERP_BUSY")
                acquired.append(value)
            lease.commit()
            yield
        finally:
            for value in reversed(acquired):
                lease.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": value},
                )
            lease.commit()


@contextmanager
def _consistent_write(storage: PostgresStorage, company: str) -> Iterator[Connection]:
    tenant = _require_tenant(company)
    engine = storage._engine.execution_options(isolation_level="REPEATABLE READ")
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.company_id', :company_id, true)"),
            {"company_id": tenant},
        )
        yield conn


def _cached(
    conn: Connection,
    company: str,
    request: SupplierSearchRequest,
    position: SavedPosition,
    key: str,
    *,
    policy: str = POLICY,
) -> SupplierSerpReport | None:
    scope = and_(runs.c.company_id == company, runs.c.cache_key == key)
    meta = (
        conn.execute(
            select(
                runs.c.run_id,
                runs.c.report_sha256,
                runs.c.created_at,
                runs.c.source_bundle_sha256,
                runs.c.source_bundle_byte_count,
                func.octet_length(cast(runs.c.report, Text)).label("payload_bytes"),
                func.octet_length(runs.c.source_bundle).label("blob_bytes"),
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
        raise ValueError("SUPPLIER_SERP_REPORT_LIMIT")
    payload = conn.scalar(select(runs.c.report).where(scope, runs.c.run_id == meta["run_id"]))
    if _digest(payload) != meta["report_sha256"]:
        raise ValueError("SUPPLIER_SERP_DIGEST_CONFLICT")
    report = SupplierSerpReport.model_validate(payload)
    position_sha, _ = _basis(position)
    if (
        report.policy_version != policy
        or report.request != request
        or report.position_sha256 != position_sha
        or report.position_name != position.position.name
        or report.run_id != meta["run_id"]
        or report.created_at != meta["created_at"]
        or report.source_bundle_sha256 != meta["source_bundle_sha256"]
        or report.source_bundle_byte_count != meta["source_bundle_byte_count"]
        or report.source_bundle_byte_count != meta["blob_bytes"]
    ):
        raise ValueError("SUPPLIER_SERP_EVIDENCE_CONFLICT")
    return report


def _bundle(capture: SerpCapture) -> bytes | None:
    if not any(content is not None for content in capture.contents):
        return None
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as zipped:
        for attempt, content in zip(capture.batch.attempts, capture.contents, strict=True):
            if content is None:
                continue
            if (
                len(content) != attempt.byte_count
                or hashlib.sha256(content).hexdigest() != attempt.dom_sha256
            ):
                raise ValueError("SUPPLIER_SERP_CAPTURE_CONFLICT")
            info = ZipInfo(f"{attempt.engine.value.lower()}.html", (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zipped.writestr(info, content)
    result = output.getvalue()
    if not 0 < len(result) <= ACTIVE_MAX_BUNDLE_BYTES:
        raise ValueError("SUPPLIER_SERP_BUNDLE_LIMIT")
    return result


def _append(
    conn: Connection,
    company: str,
    report: SupplierSerpReport,
    key: str,
    *,
    bundle: bytes | None,
    actor_id: str,
) -> None:
    bundle_sha = hashlib.sha256(bundle).hexdigest() if bundle else None
    bundle_count = len(bundle) if bundle else None
    if report.source_bundle_sha256 != bundle_sha or report.source_bundle_byte_count != bundle_count:
        raise ValueError("SUPPLIER_SERP_BUNDLE_BINDING_INVALID")
    payload = report.model_dump(mode="json")
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
        raise ValueError("SUPPLIER_SERP_REPORT_LIMIT")
    ref = report.request.selection.notice
    conn.execute(
        insert(runs).values(
            company_id=company,
            run_id=report.run_id,
            cache_key=key,
            purchase_number=ref.purchase_number,
            version_number=ref.version_number,
            notice_xml_sha256=ref.notice_xml_sha256,
            source_index=report.request.selection.source_index,
            report=payload,
            report_sha256=_digest(payload),
            created_at=report.created_at,
            source_bundle=bundle,
            source_bundle_sha256=bundle_sha,
            source_bundle_byte_count=bundle_count,
        )
    )
    _audit(
        conn,
        company,
        actor_id,
        ref,
        "EIS_SUPPLIER_SERP_SAVED",
        {
            "run_id": report.run_id,
            "source_index": report.request.selection.source_index,
            "status": report.status,
            "attempted_source_requests": report.attempted_source_requests,
            "policy_version": report.policy_version,
            **browser_transport_provenance(),
        },
    )


def _budgets_and_cooldowns(
    conn: Connection,
    company: str,
    now: datetime,
    recoveries: dict[SearchEngine, datetime] | None = None,
) -> tuple[SearchEngine, ...]:
    hour = now - timedelta(hours=1)
    day = now - timedelta(hours=24)
    started = conn.scalar(
        select(func.count())
        .select_from(runs)
        .where(
            runs.c.company_id == company,
            runs.c.created_at >= hour,
            runs.c.report["status"].astext == "STARTED",
        )
    )
    if int(started or 0) >= HOURLY_NEW_RUNS:
        raise ValueError("SUPPLIER_SERP_HOURLY_LIMIT")
    used = conn.scalar(
        select(func.coalesce(func.sum(runs.c.source_bundle_byte_count), 0)).where(
            runs.c.company_id == company,
            runs.c.created_at >= day,
        )
    )
    if int(used or 0) > DAILY_BUNDLE_BYTES - ACTIVE_MAX_BUNDLE_BYTES:
        raise ValueError("SUPPLIER_SERP_DAILY_BUNDLE_LIMIT")
    metadata = conn.execute(
        select(
            runs.c.run_id,
            runs.c.created_at,
            runs.c.report_sha256,
            func.octet_length(cast(runs.c.report, Text)).label("payload_bytes"),
        )
        .where(runs.c.company_id == company, runs.c.created_at >= hour)
        .where(runs.c.report["batch"].astext.is_not(None))
        .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
        .limit(HOURLY_NEW_RUNS * 2)
    ).all()
    if any(row.payload_bytes > MAX_REPORT_BYTES for row in metadata):
        raise ValueError("SUPPLIER_SERP_REPORT_LIMIT")
    cooldowns: set[SearchEngine] = set()
    for row in metadata:
        payload = conn.scalar(
            select(runs.c.report).where(runs.c.company_id == company, runs.c.run_id == row.run_id)
        )
        if _digest(payload) != row.report_sha256:
            raise ValueError("SUPPLIER_SERP_DIGEST_CONFLICT")
        report = SupplierSerpReport.model_validate(payload)
        if report.batch is None:
            continue
        for attempt in report.batch.attempts:
            duration = timedelta(hours=1) if attempt.status == "BLOCKED" else REFRESH_COOLDOWN
            recovered = (recoveries or {}).get(attempt.engine)
            if (
                attempt.status in {"BLOCKED", "RATE_LIMITED"}
                and now - row.created_at < duration
                and not (attempt.status == "BLOCKED" and recovered and recovered > row.created_at)
            ):
                cooldowns.add(attempt.engine)
    return tuple(engine for engine in ENGINES if engine in cooldowns)


def read_supplier_serp(
    storage: PostgresStorage, company: str, request: SupplierSearchRequest
) -> SavedSupplierSerp:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        position = _position(conn, company, request)
        _, key = _basis(position)
        report = _cached(conn, company, request, position, key)
        if report is None:
            _, historical_key = _basis(position, HISTORICAL_POLICY)
            report = _cached(
                conn, company, request, position, historical_key, policy=HISTORICAL_POLICY
            )
        if report is None:
            raise LookupError("SUPPLIER_SERP_NOT_FOUND")
        return SavedSupplierSerp(report=report, created=False, source_requests=0)


def prepare_supplier_serp(
    storage: PostgresStorage,
    company: str,
    request: SupplierSearchRequest,
    *,
    actor_id: str,
    refresh: bool = False,
) -> SavedSupplierSerp:
    if not actor_id.strip() or type(refresh) is not bool:
        raise ValueError("SUPPLIER_SERP_REQUEST_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        position = _position(conn, company, request)
        position_sha, key = _basis(position)
        cached = _cached(conn, company, request, position, key)
        if cached is not None and not refresh:
            return SavedSupplierSerp(report=cached, created=False, source_requests=0)
    with _run_leases(storage, company, key):
        now = datetime.now(UTC)
        query: str | None
        try:
            name = position.position.name.value
            if not isinstance(name, str):
                raise ValueError("PUBLIC_POSITION_INVALID")
            query = build_supplier_query(name)
        except ValueError:
            query = None
        with _tenant_lease(storage, company), _consistent_write(storage, company) as conn:
            current = _position(conn, company, request)
            if _basis(current) != (position_sha, key):
                raise ValueError("SUPPLIER_SERP_POSITION_CHANGED")
            cached = _cached(conn, company, request, current, key)
            recoveries: dict[SearchEngine, datetime] = {}
            if cached is not None and query is not None:
                from procurement.storage.supplier_captcha import recovery_receipts

                query_sha = hashlib.sha256(query.encode()).hexdigest()
                for receipt in recovery_receipts(conn, company, now):
                    if (
                        receipt.get("run_id") == cached.run_id
                        and receipt.get("position_sha256") == position_sha
                        and receipt.get("query_sha256") == query_sha
                        and receipt.get("engine") in {e.value for e in ENGINES}
                        and receipt["verified_at"] > cached.created_at
                    ):
                        recoveries[SearchEngine(receipt["engine"])] = receipt["verified_at"]
            if cached is not None:
                if not refresh:
                    return SavedSupplierSerp(report=cached, created=False, source_requests=0)
                if now - cached.created_at < REFRESH_COOLDOWN and not recoveries:
                    raise ValueError("SUPPLIER_SERP_REFRESH_COOLDOWN")
            # Withdrawing engines must not bypass an in-flight/recent archived observation.
            _, historical_key = _basis(current, HISTORICAL_POLICY)
            historical = _cached(
                conn, company, request, current, historical_key, policy=HISTORICAL_POLICY
            )
            if historical is not None and now - historical.created_at < REFRESH_COOLDOWN:
                raise ValueError("SUPPLIER_SERP_REFRESH_COOLDOWN")
            cooldowns = (
                _budgets_and_cooldowns(conn, company, now, recoveries) if query is not None else ()
            )
            if query is None:
                report = SupplierSerpReport(
                    run_id=str(uuid.uuid4()),
                    request=request,
                    position_sha256=position_sha,
                    position_name=current.position.name,
                    query=None,
                    status="QUERY_NOT_COVERED",
                    reason_code="PUBLIC_POSITION_NAME_UNAVAILABLE",
                    created_at=now,
                    batch=None,
                    attempted_source_requests=0,
                )
                _append(conn, company, report, key, bundle=None, actor_id=actor_id)
                return SavedSupplierSerp(report=report, created=True, source_requests=0)
            started = SupplierSerpReport(
                run_id=str(uuid.uuid4()),
                request=request,
                position_sha256=position_sha,
                position_name=current.position.name,
                query=query,
                status="STARTED",
                reason_code="SOURCE_OUTCOME_UNKNOWN",
                created_at=now,
                batch=None,
                attempted_source_requests=None,
            )
            _append(conn, company, started, key, bundle=None, actor_id=actor_id)
        capture = observe_supplier_serp(query, cooldowns=cooldowns, company_id=company)
        bundle = _bundle(capture)
        bundle_sha = hashlib.sha256(bundle).hexdigest() if bundle else None
        bundle_count = len(bundle) if bundle else None
        attempted = sum(a.browser_navigation_count for a in capture.batch.attempts)
        final_now = datetime.now(UTC)
        with _tenant_lease(storage, company), _consistent_write(storage, company) as conn:
            current = _position(conn, company, request)
            if _basis(current) != (position_sha, key):
                raise ValueError("SUPPLIER_SERP_POSITION_CHANGED")
            report = SupplierSerpReport(
                run_id=str(uuid.uuid4()),
                request=request,
                position_sha256=position_sha,
                position_name=current.position.name,
                query=query,
                status=capture.batch.status,
                reason_code=(
                    "ALL_ENGINES_UNAVAILABLE"
                    if capture.batch.status == "UNAVAILABLE"
                    else "FIXED_MULTI_ENGINE_SERP"
                ),
                created_at=final_now,
                batch=capture.batch,
                attempted_source_requests=attempted,
                source_bundle_sha256=bundle_sha,
                source_bundle_byte_count=bundle_count,
            )
            _append(conn, company, report, key, bundle=bundle, actor_id=actor_id)
            return SavedSupplierSerp(report=report, created=True, source_requests=attempted)
