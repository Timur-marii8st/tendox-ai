"""Add immutable tenant-scoped document discovery indexes.

Revision ID: 20260915_02
Revises: 20260915_01
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_02"
down_revision = "20260915_01"
branch_labels = None
depends_on = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "document_search_indexes",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("search_index_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_document_sha256", sa.String(length=64), nullable=False),
        sa.Column("entry", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_document_id"],
            ["documents.company_id", "documents.document_id"],
            name="fk_document_search_indexes_source",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_document_search_company_nonempty"),
        sa.CheckConstraint("search_index_id <> ''", name="ck_document_search_id_nonempty"),
        sa.CheckConstraint(
            "source_document_id <> ''",
            name="ck_document_search_source_nonempty",
        ),
        sa.CheckConstraint(
            "source_document_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_search_source_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(entry) = 'object'",
            name="ck_document_search_entry_object",
        ),
        sa.CheckConstraint(
            "entry->>'company_id' = company_id",
            name="ck_document_search_entry_company",
        ),
        sa.CheckConstraint(
            "entry->>'document_id' = source_document_id",
            name="ck_document_search_entry_document",
        ),
        sa.CheckConstraint(
            "entry->>'source_sha256' = source_document_sha256",
            name="ck_document_search_entry_sha256",
        ),
        sa.CheckConstraint(
            "entry->>'extraction_status' IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_document_search_entry_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(entry->'extraction_reasons') = 'array'",
            name="ck_document_search_entry_reasons",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(entry->'native_blocks') = 'array'",
            name="ck_document_search_entry_blocks",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "search_index_id",
            name="pk_document_search_indexes",
        ),
    )
    op.create_index(
        "ix_document_search_company_source_created",
        "document_search_indexes",
        ["company_id", "source_document_id", "created_at", "search_index_id"],
    )
    op.create_index(
        "ix_document_search_company_created",
        "document_search_indexes",
        ["company_id", "created_at"],
    )
    op.execute(
        "CREATE TRIGGER document_search_indexes_immutable "
        "BEFORE UPDATE OR DELETE ON document_search_indexes "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE document_search_indexes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_search_indexes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY document_search_select_tenant ON document_search_indexes "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        "CREATE POLICY document_search_insert_tenant ON document_search_indexes "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute("REVOKE ALL ON TABLE document_search_indexes FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_search_indexes TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("document_search_indexes")
