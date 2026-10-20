"""Exact-notice document jobs and immutable, tenant-scoped native analysis."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import Table, and_, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_analysis import DocumentAnalysis, analyze_document
from procurement.sources.eis_document_sync import MAX_DOCUMENT_BYTES
from procurement.sources.eis_feed_archive import EisNoticeSnapshot, EisProcedureEvent
from procurement.sources.eis_procedure_state import resolve_procedure_state
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_hold import (
    EisNoticeSourceHold,
    assert_notice_source_usable,
    read_notice_source_hold_connection,
)
from procurement.storage.models import (
    audit_events,
    eis_document_analyses,
    eis_document_blobs,
    eis_document_jobs,
    eis_document_observations,
    eis_notice_versions,
    eis_procedure_events,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.engine import RowMapping
    from sqlalchemy.sql.elements import ColumnElement

    from procurement.storage.repository import PostgresStorage

ANALYZER_VERSION = "eis-native-v3-doc"
MAX_NOTICE_DOCUMENTS = 32
MAX_NOTICE_BYTES = 100 * 1024**2
_SNAPSHOT = TypeAdapter(EisNoticeSnapshot)
_FIELDS = frozenset(EisNoticeSnapshot.__dataclass_fields__)
_EVENT = TypeAdapter(EisProcedureEvent)
_EVENT_FIELDS = frozenset(EisProcedureEvent.__dataclass_fields__)


class NoticeDocumentRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    version_number: int = Field(ge=1)
    notice_xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentCollectionItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    content_uid: str
    filename: str
    source_url: str
    source_locator: str
    declared_byte_count: int
    received_byte_count: int | None = None
    sha256: str | None = None
    fetch_status: Literal["PENDING", "RECEIVED", "SIZE_MISMATCH", "FAILED"] = "PENDING"
    extraction_status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    reasons: tuple[str, ...] = ()
    requirement_candidate_count: int = 0
    condition_snippet_count: int = 0
    observed_at: datetime | None = None


class DocumentCollectionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    notice: NoticeDocumentRef
    current_version_number: int
    current_xml_sha256: str
    version_status: Literal["CURRENT_KNOWN_VERSION", "STALE"]
    requested: bool
    listed_count: int
    received_count: int
    pending_count: int
    analysis_pending_count: int = Field(default=0, ge=0)
    download_status: Literal[
        "NOT_REQUESTED", "UNKNOWN_MANIFEST", "QUEUED", "INCOMPLETE", "COMPLETE_LISTED_SET"
    ]
    extraction_status: Literal["EXTRACTED", "UNKNOWN"]
    review_status: Literal["UNKNOWN"] = "UNKNOWN"
    source_manifest_coverage: Literal["UNKNOWN"] = "UNKNOWN"
    analyzer_version: str = ANALYZER_VERSION
    documents: tuple[DocumentCollectionItem, ...]
    read_gate: EisDocumentReadGate | None = None


class EisDocumentReadGate(BaseModel):
    """A decision to save source I/O, never an admission or completeness verdict."""

    model_config = ConfigDict(frozen=True)
    checked_at: datetime
    notice: NoticeDocumentRef
    blocked_reasons: tuple[
        Literal[
            "NOTICE_VERSION_STALE",
            "DEADLINE_EXPIRED",
            "PROCEDURE_BLOCKED",
            "NOTICE_VARIANT_REVIEW_REQUIRED",
        ],
        ...,
    ]
    evidence: tuple[str, ...]
    source_hold: EisNoticeSourceHold | None = None


def _procedure_events(
    connection: Connection, company_id: str, number: str
) -> tuple[EisProcedureEvent, ...]:
    return tuple(
        _EVENT.validate_python({key: row[key] for key in _EVENT_FIELDS})
        for row in connection.execute(
            select(eis_procedure_events)
            .where(
                eis_procedure_events.c.company_id == company_id,
                eis_procedure_events.c.purchase_number == number,
            )
            .order_by(eis_procedure_events.c.xml_sha256)
        ).mappings()
    )


def _build_read_gate(
    notice: EisNoticeSnapshot,
    ref: NoticeDocumentRef,
    latest: tuple[int, str],
    events: tuple[EisProcedureEvent, ...],
    now: datetime,
    variant_hold: EisNoticeSourceHold | None = None,
) -> EisDocumentReadGate:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DOCUMENT_WORKER_INPUT_INVALID")
    procedure = resolve_procedure_state(events, purchase_number=ref.purchase_number, now=now)
    reasons: list[
        Literal[
            "NOTICE_VERSION_STALE",
            "DEADLINE_EXPIRED",
            "PROCEDURE_BLOCKED",
            "NOTICE_VARIANT_REVIEW_REQUIRED",
        ]
    ] = []
    evidence = [
        f"XML {notice.xml_sha256}; файл {notice.source_member}; версия {notice.version_number}."
    ]
    if latest != (ref.version_number, ref.notice_xml_sha256):
        reasons.append("NOTICE_VERSION_STALE")
        evidence.append(f"Последняя известная версия {latest[0]}; XML {latest[1]}.")
    if notice.deadline is not None and notice.deadline <= now:
        reasons.append("DEADLINE_EXPIRED")
        evidence.append(
            f"{notice.document_type}/notificationInfo/procedureInfo/collectingInfo/endDT: "
            f"{notice.deadline.isoformat()}."
        )
    if procedure.application_status == "FAIL":
        reasons.append("PROCEDURE_BLOCKED")
        evidence.extend(procedure.reasons)
    if variant_hold is not None and variant_hold.status != "NO_HOLD":
        reasons.append("NOTICE_VARIANT_REVIEW_REQUIRED")
        evidence.append(
            "Evidence-only source variants require review; "
            f"status={variant_hold.status}; variants={variant_hold.variant_count}; "
            f"origins={variant_hold.origin_count}; receipts={len(variant_hold.receipt_ids)}."
        )
    return EisDocumentReadGate(
        checked_at=now,
        notice=ref,
        blocked_reasons=tuple(reasons),
        evidence=tuple(evidence),
        source_hold=variant_hold if variant_hold and variant_hold.status != "NO_HOLD" else None,
    )


def document_read_gate(
    storage: PostgresStorage,
    company_id: str,
    ref: NoticeDocumentRef,
    *,
    actor_id: str,
    now: datetime,
) -> EisDocumentReadGate:
    """Recheck known source state and retain an idempotent exact-source skip audit."""
    if not actor_id.strip() or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DOCUMENT_WORKER_INPUT_INVALID")
    with storage.transaction(company_id) as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company_id},
        )
        notice = _load_notice_raw(connection, company_id, ref)
        if (
            connection.execute(
                select(eis_document_jobs).where(_where_ref(eis_document_jobs, company_id, ref))
            ).first()
            is None
        ):
            raise LookupError("DOCUMENT_JOB_NOT_FOUND")
        latest = _latest(connection, company_id, ref.purchase_number)
        gate = _build_read_gate(
            notice,
            ref,
            latest,
            _procedure_events(connection, company_id, ref.purchase_number),
            now,
            read_notice_source_hold_connection(
                connection, company_id, ref.purchase_number, ref.version_number
            ),
        )
        if gate.blocked_reasons:
            basis = gate.model_dump(mode="json")
            # Exclude check time from identity: repeated reads of the same source
            # decision keep its first audit. New XML/event evidence gets a new ID.
            identity = json.dumps(
                {
                    "company_id": company_id,
                    **{key: value for key, value in basis.items() if key != "checked_at"},
                },
                sort_keys=True,
                ensure_ascii=True,
            )
            connection.execute(
                pg_insert(audit_events)
                .values(
                    event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
                    company_id=company_id,
                    actor_id=actor_id,
                    event_type="EIS_DOCUMENT_READ_BLOCKED",
                    object_type="EIS_NOTICE_DOCUMENTS",
                    object_id=ref.purchase_number,
                    object_version=ref.version_number,
                    basis=basis,
                    occurred_at=now,
                )
                .on_conflict_do_nothing(index_elements=["company_id", "event_id"])
            )
    return gate


class DocumentSelectionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str = Field(min_length=1, max_length=120)
    max_candidates: int = Field(default=3, ge=1, le=5)


class DocumentSelectionRejection(BaseModel):
    notice: NoticeDocumentRef
    reason: str


class DocumentSelectionResult(BaseModel):
    query: str
    compared_at: datetime
    inspected_current_notices: int
    matched_count: int
    eligible_count: int
    selection_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    jobs: tuple[DocumentCollectionStatus, ...]
    rejected: tuple[DocumentSelectionRejection, ...]


def plan_top_document_jobs(
    storage: PostgresStorage, company_id: str, request: DocumentSelectionRequest, *, actor_id: str
) -> DocumentSelectionResult:
    if not actor_id.strip():
        raise ValueError("DOCUMENT_ACTOR_MISSING")
    now = datetime.now(UTC)
    result = search_eis_index(
        storage,
        company_id,
        request.query,
        now=now,
        limit=request.max_candidates,
        require_documents=True,
        exclude_failed=True,
    )
    jobs = []
    rejected = []
    for lead in result.matched:
        ref = NoticeDocumentRef(
            purchase_number=lead.purchase_number,
            version_number=lead.version_number,
            notice_xml_sha256=lead.xml_sha256,
        )
        try:
            jobs.append(plan_document_job(storage, company_id, ref, actor_id=actor_id))
        except ValueError as error:
            rejected.append(DocumentSelectionRejection(notice=ref, reason=str(error)))
    with storage.transaction(company_id) as connection:
        selection_id = str(uuid.uuid4())
        connection.execute(
            insert(audit_events).values(
                event_id=selection_id,
                company_id=company_id,
                actor_id=actor_id,
                event_type="EIS_DOCUMENT_SELECTION_PLANNED",
                object_type="EIS_DOCUMENT_SELECTION",
                object_id=selection_id,
                object_version=None,
                occurred_at=datetime.now(UTC),
                basis={
                    **request.model_dump(),
                    "compared_at": now.isoformat(),
                    "eligible_count": result.eligible_count,
                    "selection_kind": "PRELIMINARY",
                    "selected": [
                        {
                            "purchase_number": lead.purchase_number,
                            "version_number": lead.version_number,
                            "xml_sha256": lead.xml_sha256,
                            "match_quality": lead.match_quality,
                            "matched_terms": list(lead.matched_terms),
                            "match_locator": lead.match_locator,
                        }
                        for lead in result.matched
                    ],
                    "rejected": [item.model_dump() for item in rejected],
                },
            )
        )
    return DocumentSelectionResult(
        query=request.query,
        compared_at=now,
        inspected_current_notices=result.inspected_current_notices,
        matched_count=result.matched_count,
        eligible_count=result.eligible_count,
        jobs=tuple(jobs),
        rejected=tuple(rejected),
    )


def _where_ref(table: Table, company_id: str, ref: NoticeDocumentRef) -> ColumnElement[bool]:
    # Kept local to avoid widening the main business repository interface.
    return and_(
        table.c.company_id == company_id,
        table.c.purchase_number == ref.purchase_number,
        table.c.version_number == ref.version_number,
    )


def _load_notice_raw(
    connection: Connection, company_id: str, ref: NoticeDocumentRef
) -> EisNoticeSnapshot:
    row = (
        connection.execute(
            select(eis_notice_versions).where(_where_ref(eis_notice_versions, company_id, ref))
        )
        .mappings()
        .first()
    )
    if row is None:
        raise LookupError("NOTICE_NOT_FOUND")
    if row["xml_sha256"] != ref.notice_xml_sha256:
        raise ValueError("NOTICE_DIGEST_CONFLICT")
    return _SNAPSHOT.validate_python({key: row[key] for key in _FIELDS})


def load_notice(
    connection: Connection, company_id: str, ref: NoticeDocumentRef
) -> EisNoticeSnapshot:
    """Load an admitted notice only when no same-or-newer variant evidence exists."""
    assert_notice_source_usable(connection, company_id, ref.purchase_number, ref.version_number)
    return _load_notice_raw(connection, company_id, ref)


def _latest(connection: Connection, company_id: str, number: str) -> tuple[int, str]:
    row = connection.execute(
        select(eis_notice_versions.c.version_number, eis_notice_versions.c.xml_sha256)
        .where(
            and_(
                eis_notice_versions.c.company_id == company_id,
                eis_notice_versions.c.purchase_number == number,
            )
        )
        .order_by(eis_notice_versions.c.version_number.desc())
        .limit(1)
    ).one()
    return row[0], row[1]


def _audit(
    connection: Connection,
    company_id: str,
    actor_id: str,
    ref: NoticeDocumentRef,
    event: str,
    basis: dict[str, object],
) -> None:
    connection.execute(
        insert(audit_events).values(
            event_id=str(uuid.uuid4()),
            company_id=company_id,
            actor_id=actor_id,
            event_type=event,
            object_type="EIS_NOTICE_DOCUMENTS",
            object_id=ref.purchase_number,
            object_version=ref.version_number,
            basis={**ref.model_dump(), **basis},
            occurred_at=datetime.now(UTC),
        )
    )


def plan_document_job(
    storage: PostgresStorage, company_id: str, ref: NoticeDocumentRef, *, actor_id: str
) -> DocumentCollectionStatus:
    if not actor_id.strip():
        raise ValueError("DOCUMENT_ACTOR_MISSING")
    with storage.transaction(company_id) as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company_id},
        )
        notice = load_notice(connection, company_id, ref)
        if _latest(connection, company_id, ref.purchase_number)[0] != ref.version_number:
            raise ValueError("NOTICE_VERSION_STALE")
        if (
            len(notice.attachments) > MAX_NOTICE_DOCUMENTS
            or sum(item.byte_count for item in notice.attachments) > MAX_NOTICE_BYTES
            or any(item.byte_count > MAX_DOCUMENT_BYTES for item in notice.attachments)
        ):
            raise ValueError("DOCUMENT_SET_RESOURCE_LIMIT")
        created = connection.execute(
            pg_insert(eis_document_jobs)
            .values(
                company_id=company_id,
                **ref.model_dump(),
                created_by=actor_id,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing()
            .returning(eis_document_jobs.c.purchase_number)
        ).first()
        if created:
            _audit(
                connection,
                company_id,
                actor_id,
                ref,
                "EIS_DOCUMENT_JOB_PLANNED",
                {"listed_count": len(notice.attachments), "review_status": "UNKNOWN"},
            )
    return get_document_status(storage, company_id, ref)


def _cached_analysis(
    connection: Connection, company_id: str, digest: str, filename: str, url: str
) -> DocumentAnalysis | None:
    payload = connection.execute(
        select(eis_document_analyses.c.payload).where(
            and_(
                eis_document_analyses.c.company_id == company_id,
                eis_document_analyses.c.sha256 == digest,
                eis_document_analyses.c.filename == filename,
                eis_document_analyses.c.analyzer_version == ANALYZER_VERSION,
            )
        )
    ).scalar_one_or_none()
    if payload is None:
        return None
    result = DocumentAnalysis.model_validate(payload)
    if result.sha256 != digest or result.filename != filename:
        raise ValueError("DOCUMENT_ANALYSIS_EVIDENCE_CONFLICT")
    return result.model_copy(update={"url": url})


def _observations(
    connection: Connection, company_id: str, ref: NoticeDocumentRef
) -> dict[str, RowMapping]:
    rows = connection.execute(
        select(eis_document_observations, eis_document_blobs.c.byte_count)
        .outerjoin(
            eis_document_blobs,
            and_(
                eis_document_blobs.c.company_id == eis_document_observations.c.company_id,
                eis_document_blobs.c.sha256 == eis_document_observations.c.sha256,
            ),
        )
        .where(_where_ref(eis_document_observations, company_id, ref))
        .distinct(eis_document_observations.c.content_uid)
        .order_by(
            eis_document_observations.c.content_uid,
            eis_document_observations.c.observed_at.desc(),
            eis_document_observations.c.observation_id.desc(),
        )
    ).mappings()
    return {row["content_uid"]: row for row in rows}


def get_document_status(
    storage: PostgresStorage,
    company_id: str,
    ref: NoticeDocumentRef,
    *,
    now: datetime | None = None,
) -> DocumentCollectionStatus:
    with storage.transaction(company_id, consistent_read=True) as connection:
        return read_document_status(connection, company_id, ref, now=now)


def read_document_status(
    connection: Connection,
    company_id: str,
    ref: NoticeDocumentRef,
    *,
    now: datetime | None = None,
) -> DocumentCollectionStatus:
    """Read in the caller's tenant snapshot; no source or analysis writes."""
    notice = load_notice(connection, company_id, ref)
    version, digest = _latest(connection, company_id, ref.purchase_number)
    requested = (
        connection.execute(
            select(eis_document_jobs.c.purchase_number).where(
                _where_ref(eis_document_jobs, company_id, ref)
            )
        ).first()
        is not None
    )
    observations = _observations(connection, company_id, ref)
    read_gate = (
        _build_read_gate(
            notice,
            ref,
            (version, digest),
            _procedure_events(connection, company_id, ref.purchase_number),
            now or datetime.now(UTC),
        )
        if requested
        else None
    )
    documents = []
    for item in notice.attachments:
        row = observations.get(item.content_uid)
        analysis = (
            _cached_analysis(connection, company_id, str(row["sha256"]), item.filename, item.url)
            if row and row["fetch_status"] == "RECEIVED"
            else None
        )
        documents.append(
            DocumentCollectionItem(
                content_uid=item.content_uid,
                filename=item.filename,
                source_url=item.url,
                source_locator=item.locator,
                declared_byte_count=item.byte_count,
                received_byte_count=row["byte_count"] if row else None,
                sha256=row["sha256"] if row else None,
                fetch_status=row["fetch_status"] if row else "PENDING",
                extraction_status=analysis.status if analysis else "UNKNOWN",
                reasons=(
                    analysis.reasons
                    if analysis
                    else (
                        str(
                            row["reason_code"]
                            or (
                                "DECLARED_SIZE_MISMATCH"
                                if row["fetch_status"] == "SIZE_MISMATCH"
                                else "ANALYSIS_NOT_AVAILABLE"
                            )
                        ),
                    )
                    if row
                    else ()
                ),
                requirement_candidate_count=len(analysis.requirement_candidates) if analysis else 0,
                condition_snippet_count=len(analysis.snippets) if analysis else 0,
                observed_at=row["observed_at"] if row else None,
            )
        )
    received = sum(item.fetch_status == "RECEIVED" for item in documents)
    pending = sum(item.fetch_status != "RECEIVED" for item in documents)
    return DocumentCollectionStatus(
        notice=ref,
        current_version_number=version,
        current_xml_sha256=digest,
        version_status="CURRENT_KNOWN_VERSION" if version == ref.version_number else "STALE",
        requested=requested,
        listed_count=len(documents),
        received_count=received,
        pending_count=pending,
        analysis_pending_count=sum(
            item.fetch_status == "RECEIVED" and item.reasons == ("ANALYSIS_NOT_AVAILABLE",)
            for item in documents
        ),
        download_status=(
            "NOT_REQUESTED"
            if not requested
            else "UNKNOWN_MANIFEST"
            if not documents
            else "COMPLETE_LISTED_SET"
            if received == len(documents)
            else "INCOMPLETE"
            if observations
            else "QUEUED"
        ),
        extraction_status="EXTRACTED"
        if documents
        and all(
            item.fetch_status == "RECEIVED" and item.extraction_status == "PASS"
            for item in documents
        )
        else "UNKNOWN",
        documents=tuple(documents),
        read_gate=read_gate,
        analyzer_version=ANALYZER_VERSION,
    )


def reanalyze_received_document(
    storage: PostgresStorage,
    company_id: str,
    ref: NoticeDocumentRef,
    content_uid: str,
    *,
    actor_id: str,
) -> bool:
    """Append a new parser-version analysis of verified bytes; never fetch or overwrite."""
    if not actor_id.strip():
        raise ValueError("DOCUMENT_ACTOR_MISSING")
    with storage.transaction(company_id) as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company_id},
        )
        notice = load_notice(connection, company_id, ref)
        if _latest(connection, company_id, ref.purchase_number) != (
            ref.version_number,
            ref.notice_xml_sha256,
        ):
            raise ValueError("NOTICE_VERSION_STALE")
        if (
            connection.execute(
                select(eis_document_jobs).where(_where_ref(eis_document_jobs, company_id, ref))
            ).first()
            is None
        ):
            raise LookupError("DOCUMENT_JOB_NOT_FOUND")
        attachment = next(
            (item for item in notice.attachments if item.content_uid == content_uid), None
        )
        observation = _observations(connection, company_id, ref).get(content_uid)
        if attachment is None or observation is None or observation["fetch_status"] != "RECEIVED":
            raise LookupError("DOCUMENT_RECEIPT_NOT_FOUND")
        digest = str(observation["sha256"])
        if (
            _cached_analysis(connection, company_id, digest, attachment.filename, attachment.url)
            is not None
        ):
            return False
        row = (
            connection.execute(
                select(eis_document_blobs).where(
                    eis_document_blobs.c.company_id == company_id,
                    eis_document_blobs.c.sha256 == digest,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError("DOCUMENT_BYTES_NOT_VERIFIABLE")
        content = bytes(row["content"])
        if (
            len(content) != row["byte_count"]
            or len(content) != attachment.byte_count
            or hashlib.sha256(content).hexdigest() != digest
            or not content
            or len(content) > MAX_DOCUMENT_BYTES
        ):
            raise ValueError("DOCUMENT_BYTES_NOT_VERIFIABLE")
        analysis = analyze_document(content, attachment.filename, attachment.url)
        connection.execute(
            insert(eis_document_analyses).values(
                company_id=company_id,
                sha256=digest,
                filename=attachment.filename,
                analyzer_version=ANALYZER_VERSION,
                payload=analysis.model_dump(mode="json"),
                analyzed_at=datetime.now(UTC),
            )
        )
        _audit(
            connection,
            company_id,
            actor_id,
            ref,
            "EIS_DOCUMENT_REANALYZED",
            {
                "content_uid": content_uid,
                "sha256": digest,
                "filename": attachment.filename,
                "analyzer_version": ANALYZER_VERSION,
                "extraction_status": analysis.status,
            },
        )
    return True


def record_document_outcome(
    storage: PostgresStorage,
    company_id: str,
    ref: NoticeDocumentRef,
    content_uid: str,
    *,
    actor_id: str,
    content: bytes | None = None,
    failure_code: str | None = None,
) -> bool:
    """Retain bytes and analysis atomically; replay never reruns the extractor."""
    if not actor_id.strip() or (content is None) == (failure_code is None):
        raise ValueError("DOCUMENT_OUTCOME_INVALID")
    with storage.transaction(company_id) as connection:
        # One per-tenant intake lock also serializes source version admission.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company_id},
        )
        notice = load_notice(connection, company_id, ref)
        if (
            connection.execute(
                select(eis_document_jobs).where(_where_ref(eis_document_jobs, company_id, ref))
            ).first()
            is None
        ):
            raise LookupError("DOCUMENT_JOB_NOT_FOUND")
        attachment = next(
            (item for item in notice.attachments if item.content_uid == content_uid), None
        )
        if attachment is None:
            raise ValueError("DOCUMENT_NOT_IN_MANIFEST")
        previous = _observations(connection, company_id, ref).get(content_uid)
        digest = hashlib.sha256(content).hexdigest() if content is not None else None
        if previous and previous["fetch_status"] == "RECEIVED":
            if digest is not None and previous["sha256"] != digest:
                raise ValueError("DOCUMENT_CONTENT_CONFLICT")
            return False
        status = "FAILED"
        if content is not None:
            if not content or len(content) > MAX_DOCUMENT_BYTES:
                raise ValueError("DOCUMENT_BYTES_RESOURCE_LIMIT")
            status = "RECEIVED" if len(content) == attachment.byte_count else "SIZE_MISMATCH"
            connection.execute(
                pg_insert(eis_document_blobs)
                .values(
                    company_id=company_id,
                    sha256=digest,
                    content=content,
                    byte_count=len(content),
                    received_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing()
            )
            if status == "RECEIVED" and digest is not None:
                analysis = _cached_analysis(
                    connection, company_id, digest, attachment.filename, attachment.url
                )
                if analysis is None:
                    analysis = analyze_document(content, attachment.filename, attachment.url)
                    connection.execute(
                        insert(eis_document_analyses).values(
                            company_id=company_id,
                            sha256=digest,
                            filename=attachment.filename,
                            analyzer_version=ANALYZER_VERSION,
                            payload=analysis.model_dump(mode="json"),
                            analyzed_at=datetime.now(UTC),
                        )
                    )
        connection.execute(
            insert(eis_document_observations).values(
                company_id=company_id,
                purchase_number=ref.purchase_number,
                version_number=ref.version_number,
                observation_id=str(uuid.uuid4()),
                content_uid=content_uid,
                sha256=digest,
                fetch_status=status,
                reason_code=failure_code,
                observed_at=datetime.now(UTC),
            )
        )
        _audit(
            connection,
            company_id,
            actor_id,
            ref,
            "EIS_DOCUMENT_OBSERVED",
            {
                "content_uid": content_uid,
                "sha256": digest,
                "fetch_status": status,
                "analyzer_version": ANALYZER_VERSION,
                "reason_code": failure_code,
            },
        )
    return True


def get_document_analysis(
    storage: PostgresStorage, company_id: str, ref: NoticeDocumentRef, content_uid: str
) -> DocumentAnalysis:
    with storage.transaction(company_id, consistent_read=True) as connection:
        notice = load_notice(connection, company_id, ref)
        attachment = next(
            (item for item in notice.attachments if item.content_uid == content_uid), None
        )
        row = _observations(connection, company_id, ref).get(content_uid)
        if attachment is None or row is None or row["fetch_status"] != "RECEIVED":
            raise LookupError("DOCUMENT_ANALYSIS_NOT_FOUND")
        analysis = _cached_analysis(
            connection, company_id, str(row["sha256"]), attachment.filename, attachment.url
        )
        if analysis is None:
            raise LookupError("DOCUMENT_ANALYSIS_NOT_FOUND")
        return analysis
