"""Immutable tenant-scoped manufacturer searches backed by retained EAEU bytes."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, insert, select, text
from sqlalchemy.engine import Connection

from procurement.sources.eaeu_registry import EAEU_REGISTRY_URL, parse_eaeu_registry_response
from procurement.sources.manufacturer_search import (
    ManufacturerCandidate,
    capture_manufacturer_search,
    normalized_manufacturer_query,
)
from procurement.storage.models import audit_events
from procurement.storage.models import manufacturer_search_attempts as attempts
from procurement.storage.models import manufacturer_search_results as results
from procurement.storage.models import manufacturer_search_runs as runs
from procurement.storage.repository import PostgresStorage

SCHEMA_VERSION: Literal["manufacturer-search-v1"] = "manufacturer-search-v1"
SOURCE: Literal["EAEU_PRODUCTS"] = "EAEU_PRODUCTS"
PARSER_REVISION = "eaeu-registry-parser-v1"
COOLDOWN = timedelta(minutes=15)
DAILY_LIMIT = 20


class ManufacturerSearchConflict(ValueError):
    """An idempotency command was reused with a different query."""


class ManufacturerSearchRateLimited(ValueError):
    """The tenant cooldown or UTC daily reservation budget is exhausted."""


class ManufacturerSearchNotFound(LookupError):
    """The requested retained run or candidate is unavailable or invalid."""


class ManufacturerSearchReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["manufacturer-search-v1"] = SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    command_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    query: str = Field(min_length=1, max_length=80)
    source: Literal["EAEU_PRODUCTS"] = SOURCE
    source_url: Literal[EAEU_REGISTRY_URL] = EAEU_REGISTRY_URL
    status: Literal["STARTED", "COMPLETED", "SOURCE_ERROR"]
    reason_code: Literal[
        "SOURCE_OUTCOME_UNKNOWN", "VERIFIED_RESPONSE", "SOURCE_UNAVAILABLE_OR_CHANGED"
    ]
    created_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_byte_size: int | None = Field(default=None, ge=0, le=512 * 1024)
    matched_count: int | None = Field(default=None, ge=0)
    candidates: tuple[ManufacturerCandidate, ...] = Field(max_length=10, default=())

    @model_validator(mode="after")
    def consistent(self) -> ManufacturerSearchReport:
        for identity in (self.run_id, self.command_id):
            if str(uuid.UUID(identity)) != identity:
                raise ValueError("MANUFACTURER_SEARCH_UUID_INVALID")
        if self.status == "STARTED":
            if any(
                value is not None
                for value in (
                    self.finished_at,
                    self.response_sha256,
                    self.response_byte_size,
                    self.matched_count,
                )
            ) or self.candidates or self.reason_code != "SOURCE_OUTCOME_UNKNOWN":
                raise ValueError("MANUFACTURER_STARTED_RESULT_CONFLICT")
        elif self.finished_at is None:
            raise ValueError("MANUFACTURER_FINAL_TIME_MISSING")
        elif self.status == "COMPLETED":
            if (
                self.response_sha256 is None
                or self.response_byte_size is None
                or self.matched_count is None
                or self.reason_code != "VERIFIED_RESPONSE"
            ):
                raise ValueError("MANUFACTURER_COMPLETED_EVIDENCE_MISSING")
        elif self.matched_count is not None or self.candidates:
            raise ValueError("MANUFACTURER_ERROR_RESULT_CONFLICT")
        return self


class SavedManufacturerSearch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    report: ManufacturerSearchReport
    created: bool = Field(strict=True)
    source_requests: int = Field(strict=True, ge=0, le=1)

    @model_validator(mode="after")
    def actual_io(self) -> SavedManufacturerSearch:
        if self.source_requests != (1 if self.created and self.report.status != "STARTED" else 0):
            raise ValueError("MANUFACTURER_SOURCE_REQUEST_COUNT_CONFLICT")
        return self


class ManufacturerSearchSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: str
    query: str
    status: Literal["STARTED", "COMPLETED", "SOURCE_ERROR"]
    created_at: AwareDatetime
    finished_at: AwareDatetime | None
    candidate_count: int = Field(ge=0, le=10)
    matched_count: int | None = Field(default=None, ge=0)


class ManufacturerCandidateProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: Literal["EAEU_PRODUCTS"] = SOURCE
    source_url: Literal[EAEU_REGISTRY_URL] = EAEU_REGISTRY_URL
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_index: int = Field(ge=1, le=10)
    field_locators: dict[str, str]


class ManufacturerCandidateDossier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: str
    candidate: ManufacturerCandidate
    provenance: ManufacturerCandidateProvenance
    verified_from_retained_response: Literal[True] = True


def _uuid(value: str, code: str) -> str:
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError(code) from error
    if parsed != value:
        raise ValueError(code)
    return value


def _validity(expiry: date | None, as_of: date) -> tuple[str, str]:
    if expiry is not None and expiry < as_of:
        return "FAIL", "EXPIRED"
    if expiry is None:
        return "UNKNOWN", "EXPIRY_UNKNOWN"
    return "UNKNOWN", "CURRENT_STATUS_UNVERIFIED"


def _candidate(source: object, *, as_of: date) -> ManufacturerCandidate:
    item = source
    expiry = item.document_expires_on  # type: ignore[attr-defined]
    validity, reason = _validity(expiry, as_of)
    return ManufacturerCandidate(
        **item.model_dump(exclude={"suitability"}),  # type: ignore[attr-defined]
        document_validity=validity,
        document_validity_reason=reason,
    )


def _audit(
    conn: Connection,
    company_id: str,
    actor_id: str,
    event_type: str,
    run_id: str,
    basis: dict[str, object],
    occurred_at: datetime,
) -> None:
    conn.execute(
        insert(audit_events).values(
            event_id=str(uuid.uuid4()),
            company_id=company_id,
            actor_id=actor_id,
            event_type=event_type,
            object_type="MANUFACTURER_SEARCH",
            object_id=run_id,
            object_version=1,
            basis=basis,
            occurred_at=occurred_at,
        )
    )


def _report(conn: Connection, company_id: str, run_id: str) -> ManufacturerSearchReport:
    row = conn.execute(
        select(
            runs.c.run_id,
            runs.c.command_id,
            runs.c.query,
            runs.c.parser_revision,
            runs.c.request_body,
            runs.c.request_sha256,
            runs.c.created_at,
            results.c.status,
            results.c.reason_code,
            results.c.observed_at,
            results.c.finished_at,
            results.c.response_sha256,
            results.c.response_byte_size,
            results.c.matched_count,
            results.c.candidate_count,
            func.octet_length(results.c.response_body).label("actual_response_bytes"),
        ).select_from(
            runs.outerjoin(
                results,
                and_(
                    runs.c.company_id == results.c.company_id,
                    runs.c.run_id == results.c.run_id,
                ),
            )
        ).where(and_(runs.c.company_id == company_id, runs.c.run_id == run_id))
    ).mappings().one_or_none()
    if row is None:
        raise ManufacturerSearchNotFound("MANUFACTURER_SEARCH_NOT_FOUND")
    try:
        normalized, expected_request = normalized_manufacturer_query(row["query"])
    except ValueError as error:
        raise ManufacturerSearchNotFound("MANUFACTURER_RETAINED_EVIDENCE_INVALID") from error
    if (
        row["parser_revision"] != PARSER_REVISION
        or normalized != row["query"]
        or bytes(row["request_body"]) != expected_request
        or hashlib.sha256(expected_request).hexdigest() != row["request_sha256"]
    ):
        raise ManufacturerSearchNotFound("MANUFACTURER_RETAINED_EVIDENCE_INVALID")
    common = dict(
        run_id=row["run_id"],
        command_id=row["command_id"],
        query=row["query"],
        created_at=row["created_at"],
        request_sha256=row["request_sha256"],
    )
    if row["finished_at"] is None:
        return ManufacturerSearchReport(
            **common, status="STARTED", reason_code="SOURCE_OUTCOME_UNKNOWN"
        )
    if row["actual_response_bytes"] != row["response_byte_size"] or (
        row["response_byte_size"] is not None and row["response_byte_size"] > 512 * 1024
    ):
        raise ManufacturerSearchNotFound("MANUFACTURER_RETAINED_EVIDENCE_INVALID")
    raw = conn.scalar(
        select(results.c.response_body).where(
            and_(results.c.company_id == company_id, results.c.run_id == run_id)
        )
    )
    raw = bytes(raw) if raw is not None else None
    digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    if digest != row["response_sha256"] or (
        raw is not None and len(raw) != row["response_byte_size"]
    ):
        raise ManufacturerSearchNotFound("MANUFACTURER_RETAINED_EVIDENCE_INVALID")
    candidates: tuple[ManufacturerCandidate, ...] = ()
    if row["status"] == "COMPLETED":
        try:
            parsed = parse_eaeu_registry_response(
                raw,
                query=row["query"],
                request_body=row["request_body"],
                observed_at=row["observed_at"],
            )
        except ValueError as error:
            raise ManufacturerSearchNotFound("MANUFACTURER_RETAINED_EVIDENCE_INVALID") from error
        if (
            parsed.response_sha256 != row["response_sha256"]
            or parsed.matched_count != row["matched_count"]
            or len(parsed.candidates) != row["candidate_count"]
        ):
            raise ManufacturerSearchNotFound("MANUFACTURER_RETAINED_EVIDENCE_INVALID")
        as_of = row["finished_at"].astimezone(UTC).date()
        candidates = tuple(_candidate(item, as_of=as_of) for item in parsed.candidates)
    return ManufacturerSearchReport(
        **common,
        status=row["status"],
        reason_code=row["reason_code"],
        finished_at=row["finished_at"],
        response_sha256=row["response_sha256"],
        response_byte_size=row["response_byte_size"],
        matched_count=row["matched_count"],
        candidates=candidates,
    )


def start_search(
    storage: PostgresStorage,
    company_id: str,
    query: str,
    actor_id: str,
    command_id: str,
) -> SavedManufacturerSearch:
    """Reserve first, commit STARTED, then perform one source request and append its result."""
    if not actor_id.strip() or len(actor_id) > 200:
        raise ValueError("MANUFACTURER_ACTOR_MISSING")
    _uuid(command_id, "MANUFACTURER_COMMAND_ID_INVALID")
    normalized, request_body = normalized_manufacturer_query(query)
    request_sha = hashlib.sha256(request_body).hexdigest()
    now = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    with storage.transaction(company_id) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": company_id + "/manufacturer-search"},
        )
        replay = conn.execute(
            select(runs.c.run_id, runs.c.query, runs.c.request_sha256).where(
                and_(runs.c.company_id == company_id, runs.c.command_id == command_id)
            )
        ).mappings().one_or_none()
        if replay is not None:
            if replay["query"] != normalized or replay["request_sha256"] != request_sha:
                raise ManufacturerSearchConflict("MANUFACTURER_COMMAND_CONFLICT")
            return SavedManufacturerSearch(
                report=_report(conn, company_id, replay["run_id"]), created=False, source_requests=0
            )
        latest = conn.scalar(
            select(func.max(runs.c.created_at)).where(runs.c.company_id == company_id)
        )
        if latest is not None and latest > now - COOLDOWN:
            raise ManufacturerSearchRateLimited("MANUFACTURER_SEARCH_COOLDOWN")
        day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
        count = conn.scalar(
            select(func.count()).select_from(runs).where(
                and_(runs.c.company_id == company_id, runs.c.created_at >= day_start)
            )
        )
        if count >= DAILY_LIMIT:
            raise ManufacturerSearchRateLimited("MANUFACTURER_SEARCH_DAILY_LIMIT")
        conn.execute(
            insert(runs).values(
                company_id=company_id,
                run_id=run_id,
                command_id=command_id,
                query=normalized,
                parser_revision=PARSER_REVISION,
                request_body=request_body,
                request_sha256=request_sha,
                created_at=now,
            )
        )
        attempt_id = str(uuid.uuid4())
        conn.execute(
            insert(attempts).values(
                company_id=company_id,
                attempt_id=attempt_id,
                run_id=run_id,
                status="STARTED",
                started_at=now,
            )
        )
        _audit(
            conn,
            company_id,
            actor_id,
            "manufacturer_search.started",
            run_id,
            {"command_id": command_id, "query": normalized, "attempt_id": attempt_id},
            now,
        )

    capture = capture_manufacturer_search(normalized)
    if (
        capture.query != normalized
        or capture.request_body != request_body
        or capture.request_sha256 != request_sha
    ):
        raise ValueError("MANUFACTURER_CAPTURE_REQUEST_CONFLICT")
    finished_at = datetime.now(UTC)
    with storage.transaction(company_id) as conn:
        conn.execute(
            insert(results).values(
                company_id=company_id,
                run_id=run_id,
                attempt_id=attempt_id,
                status=capture.status,
                reason_code=capture.reason_code,
                observed_at=capture.observed_at,
                finished_at=finished_at,
                response_body=capture.response_body,
                response_sha256=capture.response_sha256,
                response_byte_size=(
                    len(capture.response_body) if capture.response_body is not None else None
                ),
                matched_count=capture.matched_count,
                candidate_count=len(capture.candidates),
            )
        )
        _audit(
            conn,
            company_id,
            actor_id,
            "manufacturer_search.finished",
            run_id,
            {
                "attempt_id": attempt_id,
                "status": capture.status,
                "reason_code": capture.reason_code,
                "response_sha256": capture.response_sha256,
            },
            finished_at,
        )
        report = _report(conn, company_id, run_id)
    return SavedManufacturerSearch(report=report, created=True, source_requests=1)


def read_search(
    storage: PostgresStorage, company_id: str, run_id: str
) -> SavedManufacturerSearch:
    _uuid(run_id, "MANUFACTURER_RUN_ID_INVALID")
    with storage.transaction(company_id, consistent_read=True) as conn:
        return SavedManufacturerSearch(
            report=_report(conn, company_id, run_id), created=False, source_requests=0
        )


def list_saved_searches(
    storage: PostgresStorage, company_id: str, *, limit: int = 20
) -> tuple[ManufacturerSearchSummary, ...]:
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("MANUFACTURER_LIST_LIMIT_INVALID")
    with storage.transaction(company_id, consistent_read=True) as conn:
        rows = conn.execute(
            select(
                runs.c.run_id,
                runs.c.query,
                runs.c.created_at,
                results.c.status,
                results.c.finished_at,
                results.c.candidate_count,
                results.c.matched_count,
            )
            .select_from(
                runs.outerjoin(
                    results,
                    and_(
                        runs.c.company_id == results.c.company_id,
                        runs.c.run_id == results.c.run_id,
                    ),
                )
            )
            .where(runs.c.company_id == company_id)
            .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
            .limit(limit)
        ).mappings().all()
    return tuple(
        ManufacturerSearchSummary(
            run_id=row["run_id"],
            query=row["query"],
            status=row["status"] or "STARTED",
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            candidate_count=row["candidate_count"] or 0,
            matched_count=row["matched_count"],
        )
        for row in rows
    )


def read_candidate(
    storage: PostgresStorage, company_id: str, run_id: str, record_id: str
) -> ManufacturerCandidateDossier:
    saved = read_search(storage, company_id, run_id)
    if saved.report.status != "COMPLETED" or saved.report.response_sha256 is None:
        raise ManufacturerSearchNotFound("MANUFACTURER_CANDIDATE_NOT_FOUND")
    found = next((item for item in saved.report.candidates if item.record_id == record_id), None)
    if found is None:
        raise ManufacturerSearchNotFound("MANUFACTURER_CANDIDATE_NOT_FOUND")
    # Validity is evaluated again at read time; an immutable source date can become expired.
    validity, reason = _validity(found.document_expires_on, datetime.now(UTC).date())
    found = found.model_copy(
        update={"document_validity": validity, "document_validity_reason": reason}
    )
    prefix = f"result[{found.source_record_index - 1}]"
    return ManufacturerCandidateDossier(
        run_id=run_id,
        candidate=found,
        provenance=ManufacturerCandidateProvenance(
            response_sha256=saved.report.response_sha256,
            source_record_index=found.source_record_index,
            field_locators={
                "record_id": prefix + "._id.$oid",
                "registry_number": prefix + ".registrynumber",
                "product_name": prefix + ".goodsname",
                "manufacturer_name": prefix + ".name",
                "document_expires_on": prefix + ".expertactenddate",
            },
        ),
    )
