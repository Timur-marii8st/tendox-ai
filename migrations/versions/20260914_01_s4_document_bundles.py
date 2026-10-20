"""Add immutable tenant-scoped ZIP bundle snapshots.

Revision ID: 20260914_01
Revises: 20260913_01
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260914_01"
down_revision = "20260913_01"
branch_labels = None
depends_on = None

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "document_bundles",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("bundle_id", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("document_role", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "company_id <> ''",
            name="ck_document_bundles_company_id_nonempty",
        ),
        sa.CheckConstraint("bundle_id <> ''", name="ck_document_bundles_id_nonempty"),
        sa.CheckConstraint(
            "original_filename <> ''",
            name="ck_document_bundles_original_filename_nonempty",
        ),
        sa.CheckConstraint(
            "media_type IN ('application/zip', 'application/x-zip-compressed')",
            name="ck_document_bundles_media_type_allowed",
        ),
        sa.CheckConstraint(
            "document_role IN ('UNKNOWN', 'TENDER_REQUIREMENTS', 'SUPPLIER_QUOTE')",
            name="ck_document_bundles_role_allowed",
        ),
        sa.CheckConstraint(
            f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
            name="ck_document_bundles_byte_size",
        ),
        sa.CheckConstraint(
            "octet_length(content) = byte_size",
            name="ck_document_bundles_content_size",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_bundles_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object'",
            name="ck_document_bundles_result_object",
        ),
        sa.CheckConstraint(
            "result ? 'source_document_id' AND result->>'source_document_id' = bundle_id",
            name="ck_document_bundles_result_source_id",
        ),
        sa.CheckConstraint(
            "result ? 'source_sha256' AND result->>'source_sha256' = sha256",
            name="ck_document_bundles_result_source_sha256",
        ),
        sa.CheckConstraint(
            "result ? 'status' AND result->>'status' IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_document_bundles_result_status",
        ),
        sa.CheckConstraint(
            "result ? 'members' AND jsonb_typeof(result->'members') = 'array'",
            name="ck_document_bundles_result_members_array",
        ),
        sa.PrimaryKeyConstraint("company_id", "bundle_id", name="pk_document_bundles"),
    )
    op.create_index(
        "ix_document_bundles_company_created",
        "document_bundles",
        ["company_id", "created_at", "bundle_id"],
    )
    op.create_index(
        "ix_document_bundles_company_sha256",
        "document_bundles",
        ["company_id", "sha256"],
    )

    op.execute(
        "CREATE TRIGGER document_bundles_immutable "
        "BEFORE UPDATE OR DELETE ON document_bundles "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE document_bundles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_bundles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY document_bundles_select_tenant ON document_bundles "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        "CREATE POLICY document_bundles_insert_tenant ON document_bundles "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute("REVOKE ALL ON TABLE document_bundles FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_bundles TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("document_bundles")
