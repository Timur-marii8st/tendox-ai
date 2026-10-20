"""Persist exact application-package proposals without external authorization.

Revision ID: 20260921_02
Revises: 20260921_01
Create Date: 2026-09-21
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_02"
down_revision: str | None = "20260921_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "application_packages"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.drop_constraint("ck_documents_role_allowed", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_role_allowed",
        "documents",
        "document_role IN ('UNKNOWN', 'TENDER_REQUIREMENTS', 'SUPPLIER_QUOTE', "
        "'APPLICATION_ATTACHMENT')",
    )
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("package_id", sa.Text(), nullable=False),
        sa.Column("participation_decision_id", sa.Text(), nullable=False),
        sa.Column("participation_decision_sha256", sa.String(64), nullable=False),
        sa.Column("evaluation_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("case_input_sha256", sa.String(64), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("package", postgresql.JSONB(), nullable=False),
        sa.Column("prepared_by", sa.Text(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "package_id", name="pk_application_packages"),
        sa.UniqueConstraint("company_id", "participation_decision_id", name="uq_application_packages_participation_decision"),
        sa.ForeignKeyConstraint(["company_id", "participation_decision_id"], ["participation_decisions.company_id", "participation_decisions.decision_id"], name="fk_application_packages_participation_decision"),
        sa.ForeignKeyConstraint(["company_id", "case_id", "case_version"], ["case_versions.company_id", "case_versions.case_id", "case_versions.version"], name="fk_application_packages_case"),
        sa.CheckConstraint("btrim(company_id) <> '' AND btrim(package_id) <> '' AND btrim(participation_decision_id) <> '' AND btrim(evaluation_id) <> '' AND btrim(case_id) <> '' AND btrim(prepared_by) <> ''", name="ck_application_packages_text"),
        sa.CheckConstraint("case_version >= 1", name="ck_application_packages_version"),
        sa.CheckConstraint("participation_decision_sha256 ~ '^[0-9a-f]{64}$' AND case_input_sha256 ~ '^[0-9a-f]{64}$' AND package_sha256 ~ '^[0-9a-f]{64}$'", name="ck_application_packages_digests"),
        sa.CheckConstraint("jsonb_typeof(package) = 'object'", name="ck_application_packages_object"),
        sa.CheckConstraint("package->>'schema_version' = 'application-package-v1' AND package->>'company_id' IS NOT DISTINCT FROM company_id AND package->>'package_id' IS NOT DISTINCT FROM package_id AND package->>'participation_decision_id' IS NOT DISTINCT FROM participation_decision_id AND package->>'participation_decision_sha256' IS NOT DISTINCT FROM participation_decision_sha256 AND package->>'evaluation_id' IS NOT DISTINCT FROM evaluation_id AND package->>'case_id' IS NOT DISTINCT FROM case_id AND (package->>'case_version')::integer IS NOT DISTINCT FROM case_version AND package->>'case_input_sha256' IS NOT DISTINCT FROM case_input_sha256 AND package->>'package_sha256' IS NOT DISTINCT FROM package_sha256 AND package->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND (package->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at AND package->>'review_status' = 'PENDING_REVIEW' AND package->>'coverage_status' = 'UNKNOWN' AND package->'external_action_authorized' = 'false'::jsonb", name="ck_application_packages_identity"),
    )
    op.create_index("ix_application_packages_company_case", TABLE, ["company_id", "case_id", "case_version"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()")
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') " f"THEN GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$")


def downgrade() -> None:
    op.drop_table(TABLE)
    op.drop_constraint("ck_documents_role_allowed", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_role_allowed",
        "documents",
        "document_role IN ('UNKNOWN', 'TENDER_REQUIREMENTS', 'SUPPLIER_QUOTE')",
    )
