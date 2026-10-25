"""Explicit source0 DOCX review capture and bounded reads of immutable text."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from sqlalchemy import Text, and_, cast, func, insert, select, text
from sqlalchemy.sql.elements import ColumnElement

from procurement.sources.eis_analysis import document_filename_requires_review
from procurement.sources.eis_document_review import (
    REVIEW_VERSION,
    ReviewDocumentAnalysis,
    ReviewDocumentPage,
    analyze_review_document,
    review_document_page,
)
from procurement.sources.eis_feed_archive import EisOfficialAttachment
from procurement.storage.eis_document_store import NoticeDocumentRef, _audit, _latest
from procurement.storage.eis_notice_hold import assert_notice_source_usable
from procurement.storage.models import (
    eis_document_analyses as analyses,
)
from procurement.storage.models import (
    eis_document_blobs as blobs,
)
from procurement.storage.models import (
    eis_document_observations as observations,
)
from procurement.storage.models import (
    eis_notice_versions as notices,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.storage.repository import PostgresStorage

MAX_REVIEW_BYTES = 4 * 1024**2
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ANALYSIS_BYTES = 2 * 1024**2
_ATTACHMENTS = TypeAdapter(tuple[EisOfficialAttachment, ...])


class ReviewDocumentRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    notice: NoticeDocumentRef
    content_uid: str = Field(pattern=r"^[0-9A-F]{32}$")
    expected_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("notice", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if isinstance(value, dict) and type(value.get("version_number")) is not int:
            raise ValueError("REVIEW_NOTICE_VERSION_INVALID")
        return value


class SavedReviewDocumentPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: ReviewDocumentRequest
    filename: str
    source_url: str
    source_locator: str
    observation_id: str
    observed_at: AwareDatetime
    analyzed_at: AwareDatetime
    analysis_created: bool
    page: ReviewDocumentPage
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0
    requirement_status: Literal["UNKNOWN"] = "UNKNOWN"
    document_role: Literal["UNKNOWN"] = "UNKNOWN"
    position_association: Literal["UNKNOWN"] = "UNKNOWN"
    full_tspec_completeness: Literal["UNKNOWN"] = "UNKNOWN"


def _source(
    conn: Connection, company: str, request: ReviewDocumentRequest
) -> tuple[EisOfficialAttachment, str, datetime]:
    ref = request.notice
    assert_notice_source_usable(conn, company, ref.purchase_number, ref.version_number)
    scope = and_(
        notices.c.company_id == company,
        notices.c.purchase_number == ref.purchase_number,
        notices.c.version_number == ref.version_number,
    )
    meta = conn.execute(
        select(
            notices.c.xml_sha256,
            func.octet_length(cast(notices.c.attachments, Text)),
        ).where(scope)
    ).one_or_none()
    if meta is None:
        raise LookupError("NOTICE_NOT_FOUND")
    if meta[0] != ref.notice_xml_sha256:
        raise ValueError("NOTICE_DIGEST_CONFLICT")
    if _latest(conn, company, ref.purchase_number) != (
        ref.version_number,
        ref.notice_xml_sha256,
    ):
        raise ValueError("NOTICE_VERSION_STALE")
    if meta[1] > MAX_MANIFEST_BYTES:
        raise ValueError("REVIEW_ATTACHMENT_MANIFEST_LIMIT")
    manifest = _ATTACHMENTS.validate_python(conn.scalar(select(notices.c.attachments).where(scope)))
    matches = [a for a in manifest if a.content_uid == request.content_uid]
    if len(matches) != 1:
        raise LookupError("DOCUMENT_ATTACHMENT_NOT_FOUND")
    attachment = matches[0]
    if attachment.reference_status == "UNKNOWN":
        raise ValueError("ATTACHMENT_REFERENCE_REQUIRES_REVIEW")
    if document_filename_requires_review(attachment.filename):
        raise ValueError("ATTACHMENT_FILENAME_REQUIRES_REVIEW")
    if not attachment.filename.lower().endswith(".docx"):
        raise ValueError("REVIEW_DOCUMENT_FORMAT_UNSUPPORTED")
    if not 0 < attachment.byte_count <= MAX_REVIEW_BYTES:
        raise ValueError("REVIEW_DOCUMENT_BYTES_LIMIT")
    observation = conn.execute(
        select(
            observations.c.observation_id,
            observations.c.observed_at,
            observations.c.fetch_status,
            observations.c.sha256,
        )
        .where(
            observations.c.company_id == company,
            observations.c.purchase_number == ref.purchase_number,
            observations.c.version_number == ref.version_number,
            observations.c.content_uid == request.content_uid,
        )
        .order_by(observations.c.observed_at.desc(), observations.c.observation_id.desc())
        .limit(1)
    ).one_or_none()
    if observation is None or observation.fetch_status != "RECEIVED":
        raise LookupError("DOCUMENT_RECEIPT_NOT_FOUND")
    if observation.sha256 != request.expected_document_sha256:
        raise ValueError("DOCUMENT_RECEIPT_DIGEST_CONFLICT")
    return attachment, observation.observation_id, observation.observed_at


def _cache_scope(company: str, digest: str, filename: str) -> ColumnElement[bool]:
    return and_(
        analyses.c.company_id == company,
        analyses.c.sha256 == digest,
        analyses.c.filename == filename,
        analyses.c.analyzer_version == REVIEW_VERSION,
    )


def _cached(
    conn: Connection, company: str, digest: str, filename: str
) -> tuple[ReviewDocumentAnalysis, datetime] | None:
    scope = _cache_scope(company, digest, filename)
    meta = conn.execute(
        select(func.octet_length(cast(analyses.c.payload, Text)), analyses.c.analyzed_at).where(
            scope
        )
    ).one_or_none()
    if meta is None:
        return None
    if meta[0] > MAX_ANALYSIS_BYTES:
        raise ValueError("REVIEW_ANALYSIS_PAYLOAD_LIMIT")
    result = ReviewDocumentAnalysis.model_validate(
        conn.scalar(select(analyses.c.payload).where(scope))
    )
    if result.sha256 != digest or result.filename != filename:
        raise ValueError("REVIEW_ANALYSIS_EVIDENCE_CONFLICT")
    return result, meta.analyzed_at


def prepare_review_document(
    storage: PostgresStorage,
    company: str,
    request: ReviewDocumentRequest,
    *,
    actor_id: str,
) -> SavedReviewDocumentPage:
    """One explicit append-only analysis; replay uses cache without bytea hydration."""
    if not actor_id.strip():
        raise ValueError("DOCUMENT_ACTOR_MISSING")
    with storage.transaction(company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company},
        )
        attachment, observation_id, observed_at = _source(conn, company, request)
        digest = request.expected_document_sha256
        cached = _cached(conn, company, digest, attachment.filename)
        created = cached is None
        if cached is None:
            blob_scope = and_(blobs.c.company_id == company, blobs.c.sha256 == digest)
            meta = conn.execute(
                select(blobs.c.byte_count, func.octet_length(blobs.c.content)).where(blob_scope)
            ).one_or_none()
            if meta is None:
                raise ValueError("DOCUMENT_BYTES_NOT_VERIFIABLE")
            if not 0 < meta[0] == meta[1] == attachment.byte_count <= MAX_REVIEW_BYTES:
                raise ValueError("REVIEW_DOCUMENT_BYTES_LIMIT")
            saved_bytes = conn.scalar(select(blobs.c.content).where(blob_scope))
            if saved_bytes is None:
                raise ValueError("DOCUMENT_BYTES_NOT_VERIFIABLE")
            content = bytes(saved_bytes)
            if len(content) != meta[0] or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("DOCUMENT_BYTES_NOT_VERIFIABLE")
            analysis = analyze_review_document(content, attachment.filename)
            if len(analysis.model_dump_json().encode()) > MAX_ANALYSIS_BYTES:
                raise ValueError("REVIEW_ANALYSIS_PAYLOAD_LIMIT")
            analyzed_at = datetime.now(UTC)
            conn.execute(
                insert(analyses).values(
                    company_id=company,
                    sha256=digest,
                    filename=attachment.filename,
                    analyzer_version=REVIEW_VERSION,
                    payload=analysis.model_dump(mode="json"),
                    analyzed_at=analyzed_at,
                )
            )
            _audit(
                conn,
                company,
                actor_id,
                request.notice,
                "EIS_DOCUMENT_REVIEW_PREPARED",
                {
                    "content_uid": request.content_uid,
                    "sha256": digest,
                    "filename": attachment.filename,
                    "analyzer_version": REVIEW_VERSION,
                    "observation_id": observation_id,
                    "requirement_status": "UNKNOWN",
                    "source_requests": 0,
                },
            )
        else:
            analysis, analyzed_at = cached
        return _result(
            request, attachment, observation_id, observed_at, analyzed_at, analysis, created, 0, 25
        )


def read_review_document_page(
    storage: PostgresStorage,
    company: str,
    request: ReviewDocumentRequest,
    *,
    offset: int = 0,
    limit: int = 25,
    character_offset: int = 0,
) -> SavedReviewDocumentPage:
    if type(offset) is not int or not 0 <= offset <= 999:
        raise ValueError("REVIEW_PAGE_INVALID")
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("REVIEW_PAGE_INVALID")
    if type(character_offset) is not int or not 0 <= character_offset <= 100000:
        raise ValueError("REVIEW_PAGE_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        attachment, observation_id, observed_at = _source(conn, company, request)
        cached = _cached(conn, company, request.expected_document_sha256, attachment.filename)
        if cached is None:
            raise LookupError("REVIEW_ANALYSIS_NOT_PREPARED")
        analysis, analyzed_at = cached
        return _result(
            request,
            attachment,
            observation_id,
            observed_at,
            analyzed_at,
            analysis,
            False,
            offset,
            limit,
            character_offset,
        )


def _result(
    request: ReviewDocumentRequest,
    attachment: EisOfficialAttachment,
    observation_id: str,
    observed_at: datetime,
    analyzed_at: datetime,
    analysis: ReviewDocumentAnalysis,
    created: bool,
    offset: int,
    limit: int,
    character_offset: int = 0,
) -> SavedReviewDocumentPage:
    if analysis.byte_count != attachment.byte_count:
        raise ValueError("REVIEW_ANALYSIS_EVIDENCE_CONFLICT")
    result = SavedReviewDocumentPage(
        request=request,
        filename=attachment.filename,
        source_url=attachment.url,
        source_locator=attachment.locator,
        observation_id=observation_id,
        observed_at=observed_at,
        analyzed_at=analyzed_at,
        analysis_created=created,
        page=review_document_page(analysis, offset, limit, character_offset=character_offset),
    )
    if len(result.model_dump_json().encode()) > 256 * 1024:
        raise ValueError("REVIEW_PAGE_RESPONSE_LIMIT")
    return result
