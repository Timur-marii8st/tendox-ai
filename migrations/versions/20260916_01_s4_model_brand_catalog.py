"""Add immutable tenant-scoped reviewed model-brand catalogs.

Revision ID: 20260916_01
Revises: 20260915_02
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_01"
down_revision = "20260915_02"
branch_labels = None
depends_on = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        "model_brand_catalogs",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("catalog_id", sa.Text(), nullable=False),
        sa.Column("catalog", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_model_brand_company_nonempty"),
        sa.CheckConstraint("catalog_id <> ''", name="ck_model_brand_catalog_id_nonempty"),
        sa.CheckConstraint("jsonb_typeof(catalog) = 'object'", name="ck_model_brand_object"),
        sa.CheckConstraint(
            "catalog->>'schema_version' = 'model-brand-catalog-v1'",
            name="ck_model_brand_schema_version",
        ),
        sa.CheckConstraint(
            "catalog->>'company_id' = company_id",
            name="ck_model_brand_catalog_company",
        ),
        sa.CheckConstraint(
            "catalog->>'catalog_id' = catalog_id",
            name="ck_model_brand_catalog_identity",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(catalog->'entries') = 'array'",
            name="ck_model_brand_entries_array",
        ),
        sa.PrimaryKeyConstraint("company_id", "catalog_id", name="pk_model_brand_catalogs"),
    )
    op.create_index(
        "ix_model_brand_company_created",
        "model_brand_catalogs",
        ["company_id", "created_at", "catalog_id"],
    )
    op.execute(
        "CREATE TRIGGER model_brand_catalogs_immutable "
        "BEFORE UPDATE OR DELETE ON model_brand_catalogs "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute("ALTER TABLE model_brand_catalogs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_brand_catalogs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY model_brand_catalog_select_tenant ON model_brand_catalogs "
        f"FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        "CREATE POLICY model_brand_catalog_insert_tenant ON model_brand_catalogs "
        f"FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute("REVOKE ALL ON TABLE model_brand_catalogs FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON model_brand_catalogs TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("model_brand_catalogs")
