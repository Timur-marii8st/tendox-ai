"""Persist complete economics packages from PASS server offers.

Revision ID: 20260920_06
Revises: 20260920_05
Create Date: 2026-09-20
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_06"
down_revision: str | None = "20260920_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "server_offer_economics_packages"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("economics_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("case_input_sha256", sa.String(64), nullable=False),
        sa.Column("offer_id", sa.Text(), nullable=False),
        sa.Column("offer_proposal_sha256", sa.String(64), nullable=False),
        sa.Column("offer_review_decision_sha256", sa.String(64), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("package", postgresql.JSONB(), nullable=False),
        sa.Column("prepared_by", sa.Text(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "economics_id", name="pk_server_offer_economics"),
        sa.UniqueConstraint("company_id", "case_id", "case_version", name="uq_server_offer_economics_case"),
        sa.ForeignKeyConstraint(["company_id", "case_id", "case_version"], ["case_versions.company_id", "case_versions.case_id", "case_versions.version"], name="fk_server_offer_economics_case"),
        sa.ForeignKeyConstraint(["company_id", "offer_id", "offer_proposal_sha256", "offer_review_decision_sha256"], ["server_offer_review_decisions.company_id", "server_offer_review_decisions.offer_id", "server_offer_review_decisions.proposal_sha256", "server_offer_review_decisions.decision_sha256"], name="fk_server_offer_economics_review"),
        sa.CheckConstraint("btrim(economics_id) <> ''", name="ck_server_offer_economics_id"),
        sa.CheckConstraint("btrim(prepared_by) <> ''", name="ck_server_offer_economics_preparer"),
        sa.CheckConstraint("case_input_sha256 ~ '^[0-9a-f]{64}$' AND offer_proposal_sha256 ~ '^[0-9a-f]{64}$' AND offer_review_decision_sha256 ~ '^[0-9a-f]{64}$' AND package_sha256 ~ '^[0-9a-f]{64}$'", name="ck_server_offer_economics_digests"),
        sa.CheckConstraint("jsonb_typeof(package) = 'object'", name="ck_server_offer_economics_object"),
        sa.CheckConstraint("package->>'schema_version' = 'server-offer-economics-package-v1' AND package->>'company_id' IS NOT DISTINCT FROM company_id AND package->>'economics_id' IS NOT DISTINCT FROM economics_id AND package->>'case_id' IS NOT DISTINCT FROM case_id AND (package->>'case_version')::integer IS NOT DISTINCT FROM case_version AND package->>'case_input_sha256' IS NOT DISTINCT FROM case_input_sha256 AND package->>'offer_id' IS NOT DISTINCT FROM offer_id AND package->>'offer_proposal_sha256' IS NOT DISTINCT FROM offer_proposal_sha256 AND package->>'offer_review_decision_sha256' IS NOT DISTINCT FROM offer_review_decision_sha256 AND package->>'package_sha256' IS NOT DISTINCT FROM package_sha256 AND package->>'scenario_status' = 'COMPLETE' AND package->>'recommendation_status' = 'UNKNOWN' AND package->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND (package->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at", name="ck_server_offer_economics_identity"),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()")
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') " f"THEN GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$")


def downgrade() -> None:
    op.drop_table(TABLE)
