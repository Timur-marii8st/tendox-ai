"""Add immutable tenant-scoped model-brand source artifacts.

Revision ID: 20260916_02
Revises: 20260916_01
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_02"
down_revision: str | None = "20260916_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def upgrade() -> None:
    op.create_table(
        "model_brand_source_artifacts",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "artifact_id",
            name="pk_model_brand_source_artifacts",
        ),
        sa.CheckConstraint(
            "company_id <> ''",
            name="ck_model_brand_artifact_company_nonempty",
        ),
        sa.CheckConstraint(
            "artifact_id <> ''",
            name="ck_model_brand_artifact_id_nonempty",
        ),
        sa.CheckConstraint(
            "source_title <> ''",
            name="ck_model_brand_artifact_title_nonempty",
        ),
        sa.CheckConstraint(
            "source_url ~ '^https://'",
            name="ck_model_brand_artifact_url_https",
        ),
        sa.CheckConstraint(
            "original_filename <> ''",
            name="ck_model_brand_artifact_filename_nonempty",
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'",
            name="ck_model_brand_artifact_media_type_pdf",
        ),
        sa.CheckConstraint(
            f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
            name="ck_model_brand_artifact_byte_size",
        ),
        sa.CheckConstraint(
            "octet_length(content) = byte_size",
            name="ck_model_brand_artifact_content_size",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_model_brand_artifact_sha256",
        ),
    )
    op.create_index(
        "ix_model_brand_artifact_company_sha256",
        "model_brand_source_artifacts",
        ["company_id", "sha256"],
    )
    op.execute(
        "CREATE TRIGGER model_brand_source_artifacts_immutable "
        "BEFORE UPDATE OR DELETE ON model_brand_source_artifacts "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE model_brand_source_artifacts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_brand_source_artifacts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY model_brand_source_artifacts_select_tenant
        ON model_brand_source_artifacts FOR SELECT
        USING (company_id = nullif(current_setting('app.company_id', true), ''))
        """
    )
    op.execute(
        """
        CREATE POLICY model_brand_source_artifacts_insert_tenant
        ON model_brand_source_artifacts FOR INSERT
        WITH CHECK (company_id = nullif(current_setting('app.company_id', true), ''))
        """
    )
    op.execute("REVOKE ALL ON TABLE model_brand_source_artifacts FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON model_brand_source_artifacts TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_brand_artifact_company_sha256",
        table_name="model_brand_source_artifacts",
    )
    op.drop_table("model_brand_source_artifacts")
