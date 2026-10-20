"""Add immutable OCR derivatives for linked images of stored DOCX documents.

Revision ID: 20260915_01
Revises: 20260914_02
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_01"
down_revision = "20260914_02"
branch_labels = None
depends_on = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "document_docx_media_ocr_derivatives",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("ocr_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("media_index", sa.Integer(), nullable=False),
        sa.Column("archive_path", sa.Text(), nullable=False),
        sa.Column("source_document_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_media_sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mean_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_document_id"],
            ["documents.company_id", "documents.document_id"],
            name="fk_docx_media_ocr_source_document",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_docx_media_ocr_company_nonempty"),
        sa.CheckConstraint("ocr_id <> ''", name="ck_docx_media_ocr_id_nonempty"),
        sa.CheckConstraint(
            "source_document_id <> ''",
            name="ck_docx_media_ocr_source_document_nonempty",
        ),
        sa.CheckConstraint(
            "media_index >= 0",
            name="ck_docx_media_ocr_index_nonnegative",
        ),
        sa.CheckConstraint("archive_path <> ''", name="ck_docx_media_ocr_path_nonempty"),
        sa.CheckConstraint(
            "char_length(archive_path) <= 512",
            name="ck_docx_media_ocr_path_length",
        ),
        sa.CheckConstraint(
            "source_document_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_docx_media_ocr_document_sha256",
        ),
        sa.CheckConstraint(
            "source_media_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_docx_media_ocr_media_sha256",
        ),
        sa.CheckConstraint(
            "media_type IN ('image/jpeg', 'image/png')",
            name="ck_docx_media_ocr_media_type",
        ),
        sa.CheckConstraint("engine <> ''", name="ck_docx_media_ocr_engine_nonempty"),
        sa.CheckConstraint(
            "threshold BETWEEN 0 AND 1",
            name="ck_docx_media_ocr_threshold",
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_docx_media_ocr_status_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object'",
            name="ck_docx_media_ocr_result_object",
        ),
        sa.CheckConstraint(
            "result ? 'source_document_id' AND "
            "result->>'source_document_id' = "
            "source_document_id || ':media:' || media_index::text",
            name="ck_docx_media_ocr_result_source_id",
        ),
        sa.CheckConstraint(
            "result ? 'source_sha256' AND "
            "result->>'source_sha256' = source_media_sha256",
            name="ck_docx_media_ocr_result_source_sha256",
        ),
        sa.CheckConstraint(
            "result ? 'engine' AND result->>'engine' = engine",
            name="ck_docx_media_ocr_result_engine",
        ),
        sa.CheckConstraint(
            "result ? 'threshold' AND (result->>'threshold')::numeric = threshold",
            name="ck_docx_media_ocr_result_threshold",
        ),
        sa.CheckConstraint(
            "result ? 'status' AND result->>'status' = status",
            name="ck_docx_media_ocr_result_status",
        ),
        sa.CheckConstraint(
            "mean_confidence IS NULL OR (mean_confidence BETWEEN 0 AND 1)",
            name="ck_docx_media_ocr_mean_confidence",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "ocr_id",
            name="pk_document_docx_media_ocr_derivatives",
        ),
    )
    op.create_index(
        "ix_docx_media_ocr_company_source_created",
        "document_docx_media_ocr_derivatives",
        ["company_id", "source_document_id", "media_index", "created_at", "ocr_id"],
    )
    op.create_index(
        "ix_docx_media_ocr_company_created",
        "document_docx_media_ocr_derivatives",
        ["company_id", "created_at"],
    )
    op.execute(
        "CREATE TRIGGER document_docx_media_ocr_derivatives_immutable "
        "BEFORE UPDATE OR DELETE ON document_docx_media_ocr_derivatives "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE document_docx_media_ocr_derivatives ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_docx_media_ocr_derivatives FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY docx_media_ocr_select_tenant "
        "ON document_docx_media_ocr_derivatives "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        "CREATE POLICY docx_media_ocr_insert_tenant "
        "ON document_docx_media_ocr_derivatives "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute("REVOKE ALL ON TABLE document_docx_media_ocr_derivatives FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_docx_media_ocr_derivatives
                TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("document_docx_media_ocr_derivatives")
