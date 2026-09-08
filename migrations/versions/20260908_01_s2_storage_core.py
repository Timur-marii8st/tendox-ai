"""Create the tenant-isolated S2 persistence core.

Revision ID: 20260908_01
Revises: None
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260908_01"
down_revision = None
branch_labels = None
depends_on = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"
IMMUTABLE_TABLES = ("case_versions", "audit_events", "write_receipts", "evaluations")
TENANT_TABLES = (*IMMUTABLE_TABLES, "api_keys")


def _enable_rls(table: str, *, update_allowed: bool = False) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_select_tenant ON {table} "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE POLICY {table}_insert_tenant ON {table} "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    if update_allowed:
        op.execute(
            f"CREATE POLICY {table}_update_tenant ON {table} FOR UPDATE "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )


def upgrade() -> None:
    op.create_table(
        "case_versions",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name="ck_case_versions_version_positive"),
        sa.CheckConstraint("company_id <> ''", name="ck_case_versions_company_id_nonempty"),
        sa.CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_case_versions_input_sha256"
        ),
        sa.PrimaryKeyConstraint("company_id", "case_id", "version", name="pk_case_versions"),
    )
    op.create_index(
        "ix_case_versions_company_case_created",
        "case_versions",
        ["company_id", "case_id", "created_at"],
    )
    op.create_index(
        "ix_case_versions_company_input_sha256",
        "case_versions",
        ["company_id", "input_sha256"],
    )

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=True),
        sa.Column("object_id", sa.Text(), nullable=True),
        sa.Column("object_version", sa.Integer(), nullable=True),
        sa.Column("basis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "object_version IS NULL OR object_version >= 1",
            name="ck_audit_events_object_version_positive",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_audit_events_company_id_nonempty"),
        sa.PrimaryKeyConstraint("company_id", "event_id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_company_occurred",
        "audit_events",
        ["company_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_audit_events_company_object",
        "audit_events",
        ["company_id", "object_type", "object_id"],
    )

    op.create_table(
        "api_keys",
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("key_digest ~ '^[0-9a-f]{64}$'", name="ck_api_keys_key_digest"),
        sa.CheckConstraint("company_id <> ''", name="ck_api_keys_company_id_nonempty"),
        sa.PrimaryKeyConstraint("company_id", "key_id", name="pk_api_keys"),
        sa.UniqueConstraint("key_digest", name="uq_api_keys_key_digest"),
    )
    op.create_index("ix_api_keys_company_enabled", "api_keys", ["company_id", "enabled"])

    op.create_table(
        "write_receipts",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_write_receipts_request_sha256",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_write_receipts_company_id_nonempty"),
        sa.PrimaryKeyConstraint(
            "company_id", "operation", "idempotency_key", name="pk_write_receipts"
        ),
    )
    op.create_index(
        "ix_write_receipts_company_created",
        "write_receipts",
        ["company_id", "created_at"],
    )

    op.create_table(
        "evaluations",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("evaluation_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("recommendation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("case_version >= 1", name="ck_evaluations_case_version_positive"),
        sa.CheckConstraint("company_id <> ''", name="ck_evaluations_company_id_nonempty"),
        sa.CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evaluations_input_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "case_id", "case_version"],
            ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
            name="fk_evaluations_case_version",
        ),
        sa.PrimaryKeyConstraint("company_id", "evaluation_id", name="pk_evaluations"),
    )
    op.create_index(
        "ix_evaluations_company_case",
        "evaluations",
        ["company_id", "case_id", "case_version", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_immutable_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '42501';
        END;
        $$
        """
    )
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
        )

    for table in TENANT_TABLES:
        _enable_rls(table, update_allowed=table == "api_keys")

    op.execute(
        """
        CREATE FUNCTION authenticate_api_key(p_key_digest text)
        RETURNS TABLE(company_id text, actor_id text, key_id text)
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, pg_temp
        SET row_security = off
        AS $$
            SELECT k.company_id, k.actor_id, k.key_id
            FROM public.api_keys AS k
            WHERE k.key_digest = p_key_digest AND k.enabled
            LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION authenticate_api_key(text) FROM PUBLIC")
    for table in TENANT_TABLES:
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON case_versions TO procurement_app;
                GRANT SELECT, INSERT ON audit_events TO procurement_app;
                GRANT SELECT, INSERT ON write_receipts TO procurement_app;
                GRANT SELECT, INSERT ON evaluations TO procurement_app;
                GRANT EXECUTE ON FUNCTION authenticate_api_key(text) TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION authenticate_api_key(text)")
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION reject_immutable_mutation()")
