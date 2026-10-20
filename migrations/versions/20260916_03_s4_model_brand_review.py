"""Add role-aware immutable model-brand review workflow.

Revision ID: 20260916_03
Revises: 20260916_02
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260916_03"
down_revision: str | None = "20260916_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def _rls_append_only(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_select_tenant ON {table} FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE POLICY {table}_insert_tenant ON {table} FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "access_role",
            sa.Text(),
            server_default="OPERATOR",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER')",
    )

    op.create_table(
        "model_brand_review_proposals",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("catalog_id", sa.Text(), nullable=False),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "company_id", "proposal_id", name="pk_model_brand_review_proposals"
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_model_brand_review_company_nonempty"),
        sa.CheckConstraint("proposal_id <> ''", name="ck_model_brand_review_id_nonempty"),
        sa.CheckConstraint("catalog_id <> ''", name="ck_model_brand_review_catalog_nonempty"),
        sa.CheckConstraint(
            "jsonb_typeof(proposal) = 'object'", name="ck_model_brand_review_object"
        ),
        sa.CheckConstraint(
            "proposal->>'schema_version' = 'model-brand-review-proposal-v1'",
            name="ck_model_brand_review_schema",
        ),
        sa.CheckConstraint(
            "proposal->>'company_id' = company_id AND proposal->>'proposal_id' = proposal_id",
            name="ck_model_brand_review_identity",
        ),
        sa.CheckConstraint(
            "proposal->>'catalog_id' = catalog_id", name="ck_model_brand_review_catalog_identity"
        ),
    )
    op.create_index(
        "ix_model_brand_review_company_created",
        "model_brand_review_proposals",
        ["company_id", "created_at", "proposal_id"],
    )
    op.create_table(
        "model_brand_review_decisions",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("catalog_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "company_id", "proposal_id", name="pk_model_brand_review_decisions"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "proposal_id"],
            ["model_brand_review_proposals.company_id", "model_brand_review_proposals.proposal_id"],
            name="fk_model_brand_review_decision_proposal",
        ),
        sa.CheckConstraint(
            "status IN ('APPROVED', 'REJECTED')", name="ck_model_brand_review_decision_status"
        ),
        sa.CheckConstraint("decided_by <> ''", name="ck_model_brand_review_decider_nonempty"),
        sa.CheckConstraint("reason <> ''", name="ck_model_brand_review_reason_nonempty"),
        sa.CheckConstraint(
            "(status = 'APPROVED' AND catalog_id IS NOT NULL) OR "
            "(status = 'REJECTED' AND catalog_id IS NULL)",
            name="ck_model_brand_review_decision_catalog",
        ),
    )
    for table in ("model_brand_review_proposals", "model_brand_review_decisions"):
        _rls_append_only(table)

    op.execute("DROP FUNCTION authenticate_api_key(text)")
    op.execute(
        """
        CREATE FUNCTION authenticate_api_key(p_key_digest text)
        RETURNS TABLE(company_id text, actor_id text, key_id text, access_role text)
        LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, pg_temp
        SET row_security = off
        AS $$
            SELECT k.company_id, k.actor_id, k.key_id, k.access_role
            FROM public.api_keys AS k
            WHERE k.key_digest = p_key_digest AND k.enabled
            LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION authenticate_api_key(text) FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON model_brand_review_proposals TO procurement_app;
                GRANT SELECT, INSERT ON model_brand_review_decisions TO procurement_app;
                GRANT EXECUTE ON FUNCTION authenticate_api_key(text) TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION authenticate_api_key(text)")
    op.execute(
        """
        CREATE FUNCTION authenticate_api_key(p_key_digest text)
        RETURNS TABLE(company_id text, actor_id text, key_id text)
        LANGUAGE sql SECURITY DEFINER STABLE
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
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT EXECUTE ON FUNCTION authenticate_api_key(text) TO procurement_app;
            END IF;
        END
        $$
        """
    )
    op.drop_table("model_brand_review_decisions")
    op.drop_index(
        "ix_model_brand_review_company_created", table_name="model_brand_review_proposals"
    )
    op.drop_table("model_brand_review_proposals")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.drop_column("api_keys", "access_role")
