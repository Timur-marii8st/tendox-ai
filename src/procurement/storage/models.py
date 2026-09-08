"""SQLAlchemy Core schema for the PostgreSQL persistence boundary."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

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
