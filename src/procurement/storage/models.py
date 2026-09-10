"""SQLAlchemy Core schema for the PostgreSQL persistence boundary."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

case_versions = Table(
    "case_versions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "case_id", "version", name="pk_case_versions"),
    CheckConstraint("company_id <> ''", name="ck_case_versions_company_id_nonempty"),
    CheckConstraint("version >= 1", name="ck_case_versions_version_positive"),
    CheckConstraint(
        "input_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_case_versions_input_sha256",
    ),
)
Index(
    "ix_case_versions_company_case_created",
    case_versions.c.company_id,
    case_versions.c.case_id,
    case_versions.c.created_at,
)
Index(
    "ix_case_versions_company_input_sha256",
    case_versions.c.company_id,
    case_versions.c.input_sha256,
)

documents = Table(
    "documents",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("document_id", Text, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("extraction", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "document_id", name="pk_documents"),
    CheckConstraint("company_id <> ''", name="ck_documents_company_id_nonempty"),
    CheckConstraint("document_id <> ''", name="ck_documents_document_id_nonempty"),
    CheckConstraint(
        "original_filename <> ''",
        name="ck_documents_original_filename_nonempty",
    ),
    CheckConstraint("media_type <> ''", name="ck_documents_media_type_nonempty"),
    CheckConstraint(
        f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
        name="ck_documents_byte_size",
    ),
    CheckConstraint(
        "octet_length(content) = byte_size",
        name="ck_documents_content_size",
    ),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_documents_sha256"),
    CheckConstraint(
        "jsonb_typeof(extraction) = 'object'",
        name="ck_documents_extraction_object",
    ),
)
Index(
    "ix_documents_company_created",
    documents.c.company_id,
    documents.c.created_at,
    documents.c.document_id,
)
Index(
    "ix_documents_company_sha256",
    documents.c.company_id,
    documents.c.sha256,
)

document_ocr_derivatives = Table(
    "document_ocr_derivatives",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("ocr_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("threshold", Numeric(3, 2), nullable=False),
    Column("status", Text, nullable=False),
    Column("result", JSONB, nullable=False),
    Column("mean_confidence", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "ocr_id", name="pk_document_ocr_derivatives"),
    ForeignKeyConstraint(
        ["company_id", "source_document_id"],
        ["documents.company_id", "documents.document_id"],
        name="fk_ocr_derivatives_source_document",
    ),
    CheckConstraint("company_id <> ''", name="ck_ocr_company_id_nonempty"),
    CheckConstraint("ocr_id <> ''", name="ck_ocr_ocr_id_nonempty"),
    CheckConstraint("source_document_id <> ''", name="ck_ocr_source_document_id_nonempty"),
    CheckConstraint("engine <> ''", name="ck_ocr_engine_nonempty"),
    CheckConstraint("threshold BETWEEN 0 AND 1", name="ck_ocr_threshold_range"),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_ocr_status_allowed",
    ),
    CheckConstraint(
        "jsonb_typeof(result) = 'object'",
        name="ck_ocr_result_object",
    ),
    CheckConstraint(
        "mean_confidence IS NULL OR (mean_confidence BETWEEN 0 AND 1)",
        name="ck_ocr_mean_confidence_range",
    ),
)
Index(
    "ix_ocr_company_source_created",
    document_ocr_derivatives.c.company_id,
    document_ocr_derivatives.c.source_document_id,
    document_ocr_derivatives.c.created_at,
    document_ocr_derivatives.c.ocr_id,
)
Index(
    "ix_ocr_company_created",
    document_ocr_derivatives.c.company_id,
    document_ocr_derivatives.c.created_at,
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("event_id", Text, nullable=False),
    Column("company_id", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("object_type", Text, nullable=True),
    Column("object_id", Text, nullable=True),
    Column("object_version", Integer, nullable=True),
    Column("basis", JSONB, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "event_id", name="pk_audit_events"),
    CheckConstraint("company_id <> ''", name="ck_audit_events_company_id_nonempty"),
    CheckConstraint(
        "object_version IS NULL OR object_version >= 1",
        name="ck_audit_events_object_version_positive",
    ),
)
Index(
    "ix_audit_events_company_occurred",
    audit_events.c.company_id,
    audit_events.c.occurred_at,
    audit_events.c.event_id,
)
Index(
    "ix_audit_events_company_object",
    audit_events.c.company_id,
    audit_events.c.object_type,
    audit_events.c.object_id,
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("key_id", Text, nullable=False),
    Column("company_id", Text, nullable=False),
    Column("key_digest", String(64), nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "key_id", name="pk_api_keys"),
    CheckConstraint("company_id <> ''", name="ck_api_keys_company_id_nonempty"),
    UniqueConstraint("key_digest", name="uq_api_keys_key_digest"),
    CheckConstraint("key_digest ~ '^[0-9a-f]{64}$'", name="ck_api_keys_key_digest"),
)
Index("ix_api_keys_company_enabled", api_keys.c.company_id, api_keys.c.enabled)

write_receipts = Table(
    "write_receipts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("response", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint(
        "company_id",
        "operation",
        "idempotency_key",
        name="pk_write_receipts",
    ),
    CheckConstraint("company_id <> ''", name="ck_write_receipts_company_id_nonempty"),
    CheckConstraint(
        "request_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_write_receipts_request_sha256",
    ),
)
Index(
    "ix_write_receipts_company_created",
    write_receipts.c.company_id,
    write_receipts.c.created_at,
)

evaluations = Table(
    "evaluations",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("evaluation_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("engine_version", Text, nullable=False),
    Column("recommendation", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "evaluation_id", name="pk_evaluations"),
    CheckConstraint("company_id <> ''", name="ck_evaluations_company_id_nonempty"),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_evaluations_case_version",
    ),
    CheckConstraint("case_version >= 1", name="ck_evaluations_case_version_positive"),
    CheckConstraint(
        "input_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_evaluations_input_sha256",
    ),
)
Index(
    "ix_evaluations_company_case",
    evaluations.c.company_id,
    evaluations.c.case_id,
    evaluations.c.case_version,
    evaluations.c.created_at,
)
