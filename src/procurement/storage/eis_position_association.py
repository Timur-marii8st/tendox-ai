"""Tenant-scoped immutable storage for exact position-to-DOCX fragment links."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, Text, and_, cast, func, insert, or_, select, text
from sqlalchemy.engine import Connection

from procurement.sources.eis_characteristic_compare import SavedPosition
from procurement.sources.eis_document_review import ReviewDocumentAnalysis
from procurement.sources.eis_position_association import (
    AssociationCursor,
    AssociationDetailRequest,
    AssociationListRequest,
    AssociationListResult,
    AssociationMetadata,
    AssociationReadScope,
    AssociationRequest,
    PositionFragmentAssociationReport,
    SavedAssociation,
    build_position_fragment_association,
)
from procurement.storage.eis_document_review import _cached as review_cached
from procurement.storage.eis_document_review import _source as review_source
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_supplier_search import _position
from procurement.storage.models import eis_position_fragment_associations as associations
from procurement.storage.repository import PostgresStorage, _require_tenant

MAX_REPORT_BYTES = 256 * 1024


@contextmanager
def _consistent_write(storage: PostgresStorage, company: str) -> Iterator[Connection]:
    """Use one writable repeatable-read snapshot with the ordinary exact RLS tenant."""
    tenant = _require_tenant(company)
    engine = storage._engine.execution_options(isolation_level="REPEATABLE READ")
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.company_id', :company_id, true)"),
            {"company_id": tenant},
        )
        yield conn


@contextmanager
def _tenant_lease(storage: PostgresStorage, company: str) -> Iterator[None]:
    key = _require_tenant(company)
    with storage._engine.connect() as lease:
        acquired = lease.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key}
        )
        lease.commit()
        if not acquired:
            raise ValueError("POSITION_ASSOCIATION_BUSY")
        try:
            yield
        finally:
            lease.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key}
            )
            lease.commit()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _evidence(
    conn: Connection, company: str, request: AssociationRequest | AssociationReadScope
) -> tuple[SavedPosition, ReviewDocumentAnalysis, str, datetime, datetime, str, str]:
    position = _position(conn, company, request.position)
    attachment, observation_id, observed_at = review_source(conn, company, request.document)
    cached = review_cached(
        conn,
        company,
        request.document.expected_document_sha256,
        attachment.filename,
    )
    if cached is None:
        raise LookupError("POSITION_ASSOCIATION_ANALYSIS_NOT_PREPARED")
    analysis, analyzed_at = cached
    if analysis.review_version != request.analyzer_version:
        raise ValueError("POSITION_ASSOCIATION_ANALYZER_MISMATCH")
    position_sha = _digest(position.model_dump(mode="json"))
    analysis_digest = _digest(analysis.model_dump(mode="json"))
    cache_key = _digest(
        {
            "policy": "eis-position-fragment-association-v1",
            "request": request.model_dump(mode="json"),
            "position_sha256": position_sha,
            "analysis_digest": analysis_digest,
            "observation_id": observation_id,
            "observed_at": observed_at.isoformat(),
            "analyzed_at": analyzed_at.isoformat(),
        }
    )
    return (
        position,
        analysis,
        observation_id,
        observed_at,
        analyzed_at,
        position_sha,
        cache_key,
    )


def _saved(
    conn: Connection,
    company: str,
    request: AssociationRequest,
    *,
    position: SavedPosition,
    analysis: ReviewDocumentAnalysis,
    observation_id: str,
    observed_at: datetime,
    analyzed_at: datetime,
    position_sha: str,
    cache_key: str,
) -> PositionFragmentAssociationReport | None:
    scope = and_(associations.c.company_id == company, associations.c.cache_key == cache_key)
    meta = conn.execute(
        select(
            associations.c.association_id,
            associations.c.report_sha256,
            associations.c.created_at,
            func.octet_length(cast(associations.c.report, Text)),
        ).where(scope)
    ).one_or_none()
    if meta is None:
        return None
    if meta[3] > MAX_REPORT_BYTES:
        raise ValueError("POSITION_ASSOCIATION_REPORT_LIMIT")
    payload = conn.scalar(select(associations.c.report).where(scope))
    if _digest(payload) != meta.report_sha256:
        raise ValueError("POSITION_ASSOCIATION_DIGEST_CONFLICT")
    report = PositionFragmentAssociationReport.model_validate(payload)
    if (
        report.association_id != meta.association_id
        or report.created_at != meta.created_at
        or report.request != request
        or report.position_sha256 != position_sha
        or report.position_name != position.position.name
        or report.analysis_sha256 != _digest(analysis.model_dump(mode="json"))
        or report.document_sha256 != analysis.sha256
        or report.filename != analysis.filename
        or report.observation_id != observation_id
        or report.observed_at != observed_at
        or report.analyzed_at != analyzed_at
    ):
        raise ValueError("POSITION_ASSOCIATION_EVIDENCE_CONFLICT")
    rebuilt = build_position_fragment_association(
        request,
        position,
        analysis,
        position_sha256=position_sha,
        observation_id=observation_id,
        observed_at=observed_at,
        analyzed_at=analyzed_at,
        linked_by=report.linked_by,
        now=report.created_at,
        association_id=report.association_id,
    )
    if rebuilt != report:
        raise ValueError("POSITION_ASSOCIATION_EVIDENCE_CONFLICT")
    return report


def _read_scope(company: str, scope: AssociationReadScope):
    ref = scope.position.selection.notice
    return and_(
        associations.c.company_id == company,
        associations.c.purchase_number == ref.purchase_number,
        associations.c.version_number == ref.version_number,
        associations.c.notice_xml_sha256 == ref.notice_xml_sha256,
        associations.c.source_index == scope.position.selection.source_index,
        associations.c.content_uid == scope.document.content_uid,
        associations.c.document_sha256 == scope.document.expected_document_sha256,
    )


def _current_read_scope(
    company: str,
    scope: AssociationReadScope,
    *,
    position_sha: str,
    analysis: ReviewDocumentAnalysis,
    observation_id: str,
    observed_at: datetime,
    analyzed_at: datetime,
):
    report = associations.c.report
    return and_(
        _read_scope(company, scope),
        report["position_sha256"].astext == position_sha,
        report["analysis_sha256"].astext == _digest(analysis.model_dump(mode="json")),
        report["document_sha256"].astext == analysis.sha256,
        report["filename"].astext == analysis.filename,
        report["observation_id"].astext == observation_id,
        cast(report["observed_at"].astext, DateTime(timezone=True)) == observed_at,
        cast(report["analyzed_at"].astext, DateTime(timezone=True)) == analyzed_at,
    )


def _read_bound_report(
    conn: Connection,
    company: str,
    scope: AssociationReadScope,
    association_id: str,
    *,
    position: SavedPosition,
    analysis: ReviewDocumentAnalysis,
    observation_id: str,
    observed_at: datetime,
    analyzed_at: datetime,
    position_sha: str,
) -> PositionFragmentAssociationReport:
    row_scope = and_(
        _read_scope(company, scope), associations.c.association_id == association_id
    )
    meta = conn.execute(
        select(
            associations.c.report_sha256,
            associations.c.created_at,
            func.octet_length(cast(associations.c.report, Text)),
        ).where(row_scope)
    ).one_or_none()
    if meta is None:
        raise LookupError("POSITION_ASSOCIATION_NOT_FOUND")
    if meta[2] > MAX_REPORT_BYTES:
        raise ValueError("POSITION_ASSOCIATION_REPORT_LIMIT")
    payload = conn.scalar(select(associations.c.report).where(row_scope))
    if _digest(payload) != meta.report_sha256:
        raise ValueError("POSITION_ASSOCIATION_DIGEST_CONFLICT")
    report = PositionFragmentAssociationReport.model_validate(payload)
    if (
        report.association_id != association_id
        or report.created_at != meta.created_at
        or report.request.position != scope.position
        or report.request.document != scope.document
        or report.request.analyzer_version != scope.analyzer_version
        or report.position_sha256 != position_sha
        or report.position_name != position.position.name
        or report.analysis_sha256 != _digest(analysis.model_dump(mode="json"))
        or report.document_sha256 != analysis.sha256
        or report.filename != analysis.filename
        or report.observation_id != observation_id
        or report.observed_at != observed_at
        or report.analyzed_at != analyzed_at
    ):
        raise ValueError("POSITION_ASSOCIATION_EVIDENCE_CONFLICT")
    rebuilt = build_position_fragment_association(
        report.request,
        position,
        analysis,
        position_sha256=position_sha,
        observation_id=observation_id,
        observed_at=observed_at,
        analyzed_at=analyzed_at,
        linked_by=report.linked_by,
        now=report.created_at,
        association_id=report.association_id,
    )
    if rebuilt != report:
        raise ValueError("POSITION_ASSOCIATION_EVIDENCE_CONFLICT")
    return report


def save_position_fragment_association(
    storage: PostgresStorage,
    company: str,
    request: AssociationRequest,
    *,
    actor_id: str,
    now: datetime | None = None,
) -> SavedAssociation:
    if not actor_id.strip():
        raise ValueError("POSITION_ASSOCIATION_ACTOR_MISSING")
    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("POSITION_ASSOCIATION_TIME_INVALID")
    with _tenant_lease(storage, company), _consistent_write(storage, company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
        evidence = _evidence(conn, company, request)
        position, analysis, observation_id, observed_at, analyzed_at, position_sha, key = evidence
        replay = _saved(
            conn,
            company,
            request,
            position=position,
            analysis=analysis,
            observation_id=observation_id,
            observed_at=observed_at,
            analyzed_at=analyzed_at,
            position_sha=position_sha,
            cache_key=key,
        )
        if replay is not None:
            return SavedAssociation(report=replay, created=False)
        report = build_position_fragment_association(
            request,
            position,
            analysis,
            position_sha256=position_sha,
            observation_id=observation_id,
            observed_at=observed_at,
            analyzed_at=analyzed_at,
            linked_by=actor_id,
            now=created_at,
            association_id=str(uuid.uuid4()),
        )
        payload = report.model_dump(mode="json")
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
            raise ValueError("POSITION_ASSOCIATION_REPORT_LIMIT")
        ref = request.position.selection.notice
        conn.execute(
            insert(associations).values(
                company_id=company,
                association_id=report.association_id,
                cache_key=key,
                purchase_number=ref.purchase_number,
                version_number=ref.version_number,
                notice_xml_sha256=ref.notice_xml_sha256,
                source_index=request.position.selection.source_index,
                content_uid=request.document.content_uid,
                document_sha256=request.document.expected_document_sha256,
                report=payload,
                report_sha256=_digest(payload),
                created_at=created_at,
            )
        )
        _audit(
            conn,
            company,
            actor_id,
            ref,
            "EIS_POSITION_FRAGMENTS_LINKED",
            {
                "association_id": report.association_id,
                "source_index": request.position.selection.source_index,
                "content_uid": request.document.content_uid,
                "document_sha256": request.document.expected_document_sha256,
                "selected_characters": report.selected_characters,
                "fragment_count": len(report.fragments),
                "policy_version": report.policy_version,
                "source_requests": 0,
                "jobs_created": 0,
            },
        )
        return SavedAssociation(report=report, created=True)


def read_position_fragment_association(
    storage: PostgresStorage, company: str, request: AssociationRequest
) -> SavedAssociation:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        evidence = _evidence(conn, company, request)
        position, analysis, observation_id, observed_at, analyzed_at, position_sha, key = evidence
        report = _saved(
            conn,
            company,
            request,
            position=position,
            analysis=analysis,
            observation_id=observation_id,
            observed_at=observed_at,
            analyzed_at=analyzed_at,
            position_sha=position_sha,
            cache_key=key,
        )
        if report is None:
            raise LookupError("POSITION_ASSOCIATION_NOT_FOUND")
        return SavedAssociation(report=report, created=False)


def list_position_fragment_associations(
    storage: PostgresStorage, company: str, request: AssociationListRequest
) -> AssociationListResult:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        evidence = _evidence(conn, company, request.scope)
        position, analysis, observation_id, observed_at, analyzed_at, position_sha, _ = evidence
        scope = _current_read_scope(
            company,
            request.scope,
            position_sha=position_sha,
            analysis=analysis,
            observation_id=observation_id,
            observed_at=observed_at,
            analyzed_at=analyzed_at,
        )
        if request.cursor is not None:
            cursor_exists = conn.scalar(
                select(func.count()).select_from(associations).where(
                    scope,
                    associations.c.association_id == request.cursor.association_id,
                )
            )
            if cursor_exists != 1:
                raise LookupError("POSITION_ASSOCIATION_NOT_FOUND")
            cursor_report = _read_bound_report(
                conn,
                company,
                request.scope,
                request.cursor.association_id,
                position=position,
                analysis=analysis,
                observation_id=observation_id,
                observed_at=observed_at,
                analyzed_at=analyzed_at,
                position_sha=position_sha,
            )
            if cursor_report.created_at != request.cursor.created_at:
                raise ValueError("POSITION_ASSOCIATION_CURSOR_INVALID")
            scope = and_(
                scope,
                or_(
                    associations.c.created_at < request.cursor.created_at,
                    and_(
                        associations.c.created_at == request.cursor.created_at,
                        associations.c.association_id < request.cursor.association_id,
                    ),
                ),
            )
        rows = conn.execute(
            select(
                associations.c.association_id,
                associations.c.created_at,
                func.octet_length(cast(associations.c.report, Text)).label("payload_bytes"),
            )
            .where(scope)
            .order_by(associations.c.created_at.desc(), associations.c.association_id.desc())
            .limit(request.limit + 1)
        ).all()
        if any(row.payload_bytes > MAX_REPORT_BYTES for row in rows):
            raise ValueError("POSITION_ASSOCIATION_REPORT_LIMIT")
        has_more = len(rows) > request.limit
        page_rows = rows[: request.limit]
        reports = tuple(
            _read_bound_report(
                conn,
                company,
                request.scope,
                row.association_id,
                position=position,
                analysis=analysis,
                observation_id=observation_id,
                observed_at=observed_at,
                analyzed_at=analyzed_at,
                position_sha=position_sha,
            )
            for row in page_rows
        )
        items = tuple(
            AssociationMetadata(
                association_id=report.association_id,
                created_at=report.created_at,
                linked_by=report.linked_by,
                fragment_count=len(report.fragments),
                selected_characters=report.selected_characters,
            )
            for report in reports
        )
        next_cursor = (
            AssociationCursor(
                created_at=items[-1].created_at,
                association_id=items[-1].association_id,
            )
            if has_more
            else None
        )
        return AssociationListResult(request=request, items=items, next_cursor=next_cursor)


def read_position_fragment_association_detail(
    storage: PostgresStorage, company: str, request: AssociationDetailRequest
) -> SavedAssociation:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        evidence = _evidence(conn, company, request.scope)
        position, analysis, observation_id, observed_at, analyzed_at, position_sha, _ = evidence
        current_scope = _current_read_scope(
            company,
            request.scope,
            position_sha=position_sha,
            analysis=analysis,
            observation_id=observation_id,
            observed_at=observed_at,
            analyzed_at=analyzed_at,
        )
        current = conn.scalar(
            select(func.count()).select_from(associations).where(
                current_scope,
                associations.c.association_id == request.association_id,
            )
        )
        if current != 1:
            raise LookupError("POSITION_ASSOCIATION_NOT_FOUND")
        report = _read_bound_report(
            conn,
            company,
            request.scope,
            request.association_id,
            position=position,
            analysis=analysis,
            observation_id=observation_id,
            observed_at=observed_at,
            analyzed_at=analyzed_at,
            position_sha=position_sha,
        )
        return SavedAssociation(report=report, created=False)
