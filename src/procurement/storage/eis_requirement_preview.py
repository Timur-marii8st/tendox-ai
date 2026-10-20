"""Read-only binding of one saved product to one retained DOCX table."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from procurement.sources.eis_requirement_preview import (
    RequirementPreview,
    RequirementPreviewRequest,
    build_requirement_preview,
    canonical_sha,
)
from procurement.sources.eis_requirement_table import build_eis_requirement_table
from procurement.storage.eis_document_review import _cached as _review_cached
from procurement.storage.eis_document_review import _source as _review_source
from procurement.storage.eis_supplier_product import _cached as _product_cached
from procurement.storage.eis_supplier_product import _key as _product_key
from procurement.storage.eis_supplier_product import _product_parent
from procurement.storage.repository import PostgresStorage

MAX_PREVIEW_BYTES = 256 * 1024


def read_requirement_preview_connection(
    conn: Connection, company: str, request: RequirementPreviewRequest
) -> RequirementPreview:
    parent, parent_sha, _, _, position_sha = _product_parent(
        conn, company, request.product, body=False
    )
    if parent.source_body_sha256 is None or parent.observation is None:
        raise ValueError("REQUIREMENT_PREVIEW_PRODUCT_EVIDENCE_CONFLICT")
    key = _product_key(request.product, parent_sha, position_sha, parent.source_body_sha256)
    product = _product_cached(
        conn,
        company,
        key,
        request.product,
        parent_sha,
        position_sha,
        parent.source_body_sha256,
        parent.observation.final_url,
    )
    if product is None:
        raise LookupError("REQUIREMENT_PREVIEW_PRODUCT_NOT_FOUND")
    attachment, observation_id, observed_at = _review_source(conn, company, request.document)
    cached = _review_cached(
        conn,
        company,
        request.document.expected_document_sha256,
        attachment.filename,
    )
    if cached is None:
        raise LookupError("REQUIREMENT_PREVIEW_ANALYSIS_NOT_FOUND")
    analysis, analyzed_at = cached
    table = build_eis_requirement_table(analysis, request.table_index)
    result = build_requirement_preview(
        request=request,
        product=product,
        product_report_sha256=canonical_sha(product),
        analysis_sha256=canonical_sha(analysis),
        document_observation_id=observation_id,
        observed_at=observed_at,
        analyzed_at=analyzed_at,
        filename=attachment.filename,
        table=table,
        approved_requirement_status="UNKNOWN",
        document_role="UNKNOWN",
        position_association="UNKNOWN",
        full_tspec_completeness="UNKNOWN",
        technical="UNKNOWN",
        participation="UNKNOWN",
        source_requests=0,
        jobs_created=0,
        database_writes=0,
    )
    if len(result.model_dump_json().encode()) > MAX_PREVIEW_BYTES:
        raise ValueError("REQUIREMENT_PREVIEW_LIMIT")
    return result


def read_requirement_preview(
    storage: PostgresStorage, company: str, request: RequirementPreviewRequest
) -> RequirementPreview:
    """Return a deterministic source-zero preview from already saved evidence."""

    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        return read_requirement_preview_connection(conn, company, request)
