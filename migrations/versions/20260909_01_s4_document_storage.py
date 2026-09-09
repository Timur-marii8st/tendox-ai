"""Add immutable tenant-scoped source document storage.

Revision ID: 20260909_01
Revises: 20260908_01
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260909_01"
down_revision = "20260908_01"
branch_labels = None
depends_on = None

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "extraction",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_documents_company_id_nonempty"),
        sa.CheckConstraint("document_id <> ''", name="ck_documents_document_id_nonempty"),
        sa.CheckConstraint(
            "original_filename <> ''",
            name="ck_documents_original_filename_nonempty",
        ),
        sa.CheckConstraint("media_type <> ''", name="ck_documents_media_type_nonempty"),
        sa.CheckConstraint(
            f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
            name="ck_documents_byte_size",
        ),
        sa.CheckConstraint(
            "octet_length(content) = byte_size",
            name="ck_documents_content_size",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_documents_sha256"),
        sa.CheckConstraint(
            "jsonb_typeof(extraction) = 'object'",
            name="ck_documents_extraction_object",
        ),
        sa.PrimaryKeyConstraint("company_id", "document_id", name="pk_documents"),
    )
    op.create_index(
        "ix_documents_company_created",
        "documents",
        ["company_id", "created_at", "document_id"],
    )
    op.create_index(
        "ix_documents_company_sha256",
        "documents",
        ["company_id", "sha256"],
    )

    op.execute(
        "CREATE TRIGGER documents_immutable BEFORE UPDATE OR DELETE ON documents "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY documents_select_tenant ON documents "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        "CREATE POLICY documents_insert_tenant ON documents "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute("REVOKE ALL ON TABLE documents FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON documents TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("documents")
