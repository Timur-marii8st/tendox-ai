"""Persist independent exact application-package review decisions.

Revision ID: 20260921_03
Revises: 20260921_02
Create Date: 2026-09-21
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_03"
down_revision: str | None = "20260921_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "application_package_reviews"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
BASE_ROLES = (
    "'OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
    "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER', "
    "'PARTICIPATION_APPROVER', "
)


def upgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN (" + BASE_ROLES + "'APPLICATION_REVIEWER', 'AUDITOR')",
    )
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("package_id", sa.Text(), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision", postgresql.JSONB(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "package_id", name="pk_application_package_reviews"),
        sa.ForeignKeyConstraint(["company_id", "package_id"], ["application_packages.company_id", "application_packages.package_id"], name="fk_application_package_reviews_package"),
        sa.CheckConstraint("btrim(company_id) <> '' AND btrim(package_id) <> '' AND btrim(reviewed_by) <> ''", name="ck_application_package_reviews_text"),
        sa.CheckConstraint("package_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'", name="ck_application_package_reviews_digests"),
        sa.CheckConstraint("status IN ('PASS', 'FAIL', 'UNKNOWN')", name="ck_application_package_reviews_status"),
        sa.CheckConstraint("jsonb_typeof(decision) = 'object'", name="ck_application_package_reviews_object"),
        sa.CheckConstraint("decision->>'schema_version' = 'application-review-decision-v1' AND decision->>'company_id' IS NOT DISTINCT FROM company_id AND decision->>'package_id' IS NOT DISTINCT FROM package_id AND decision->>'package_sha256' IS NOT DISTINCT FROM package_sha256 AND decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND decision->>'status' IS NOT DISTINCT FROM status AND decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by AND (decision->>'reviewed_at')::timestamptz IS NOT DISTINCT FROM reviewed_at AND decision->'external_action_authorized' = 'false'::jsonb", name="ck_application_package_reviews_identity"),
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
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN (" + BASE_ROLES + "'AUDITOR')",
    )
