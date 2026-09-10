"""Add immutable tenant-scoped OCR derivative storage.

Revision ID: 20260909_02
Revises: 20260909_01
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260909_02"
down_revision = "20260909_01"
branch_labels = None
depends_on = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "document_ocr_derivatives",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("ocr_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
            name="fk_ocr_derivatives_source_document",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_ocr_company_id_nonempty"),
        sa.CheckConstraint("ocr_id <> ''", name="ck_ocr_ocr_id_nonempty"),
        sa.CheckConstraint(
            "source_document_id <> ''",
            name="ck_ocr_source_document_id_nonempty",
        ),
        sa.CheckConstraint("engine <> ''", name="ck_ocr_engine_nonempty"),
        sa.CheckConstraint("threshold BETWEEN 0 AND 1", name="ck_ocr_threshold_range"),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_ocr_status_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object'",
            name="ck_ocr_result_object",
        ),
        sa.CheckConstraint(
            "mean_confidence IS NULL OR (mean_confidence BETWEEN 0 AND 1)",
            name="ck_ocr_mean_confidence_range",
        ),
        sa.PrimaryKeyConstraint("company_id", "ocr_id", name="pk_document_ocr_derivatives"),
    )
    op.create_index(
        "ix_ocr_company_source_created",
        "document_ocr_derivatives",
        ["company_id", "source_document_id", "created_at", "ocr_id"],
    )
    op.create_index(
        "ix_ocr_company_created",
        "document_ocr_derivatives",
        ["company_id", "created_at"],
    )

    op.execute(
        "CREATE TRIGGER document_ocr_derivatives_immutable "
        "BEFORE UPDATE OR DELETE ON document_ocr_derivatives "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE document_ocr_derivatives ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_ocr_derivatives FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY document_ocr_derivatives_select_tenant ON document_ocr_derivatives "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        "CREATE POLICY document_ocr_derivatives_insert_tenant ON document_ocr_derivatives "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute("REVOKE ALL ON TABLE document_ocr_derivatives FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_ocr_derivatives TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("document_ocr_derivatives")
