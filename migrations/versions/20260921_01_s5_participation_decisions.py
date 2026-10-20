"""Persist independent human decisions over exact positive evaluations.

Revision ID: 20260921_01
Revises: 20260920_06
Create Date: 2026-09-21
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_01"
down_revision: str | None = "20260920_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "participation_decisions"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def _role_constraint(*, include_participation: bool) -> str:
    roles = [
        "OPERATOR",
        "MODEL_BRAND_REVIEWER",
        "COMPLETENESS_REVIEWER",
        "AI_REQUIREMENTS_REVIEWER",
        "AI_TRANSFER_APPROVER",
    ]
    if include_participation:
        roles.append("PARTICIPATION_APPROVER")
    roles.append("AUDITOR")
    return "access_role IN (" + ", ".join(f"'{role}'" for role in roles) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role", "api_keys", _role_constraint(include_participation=True)
    )
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("decision_id", sa.Text(), nullable=False),
        sa.Column("evaluation_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("evaluation_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("decision", postgresql.JSONB(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "decision_id", name="pk_participation_decisions"),
        sa.UniqueConstraint("company_id", "evaluation_id", name="uq_participation_decisions_evaluation"),
        sa.ForeignKeyConstraint(["company_id", "evaluation_id"], ["evaluations.company_id", "evaluations.evaluation_id"], name="fk_participation_decisions_evaluation"),
        sa.CheckConstraint("btrim(company_id) <> '' AND btrim(decision_id) <> '' AND btrim(evaluation_id) <> '' AND btrim(case_id) <> '' AND btrim(decided_by) <> ''", name="ck_participation_decisions_text"),
        sa.CheckConstraint("case_version >= 1", name="ck_participation_decisions_version"),
        sa.CheckConstraint("evaluation_evidence_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'", name="ck_participation_decisions_digests"),
        sa.CheckConstraint("status IN ('APPROVED', 'REJECTED')", name="ck_participation_decisions_status"),
        sa.CheckConstraint("jsonb_typeof(decision) = 'object'", name="ck_participation_decisions_object"),
        sa.CheckConstraint("decision->>'schema_version' = 'participation-decision-v1' AND decision->>'company_id' IS NOT DISTINCT FROM company_id AND decision->>'decision_id' IS NOT DISTINCT FROM decision_id AND decision->>'evaluation_id' IS NOT DISTINCT FROM evaluation_id AND decision->>'evaluation_evidence_sha256' IS NOT DISTINCT FROM evaluation_evidence_sha256 AND decision->>'case_id' IS NOT DISTINCT FROM case_id AND (decision->>'case_version')::integer IS NOT DISTINCT FROM case_version AND decision->>'status' IS NOT DISTINCT FROM status AND decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND decision->>'decided_by' IS NOT DISTINCT FROM decided_by AND (decision->>'decided_at')::timestamptz IS NOT DISTINCT FROM decided_at AND decision->'external_action_authorized' = 'false'::jsonb", name="ck_participation_decisions_identity"),
    )
    op.create_index("ix_participation_decisions_company_case", TABLE, ["company_id", "case_id", "case_version"])
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
        "ck_api_keys_access_role", "api_keys", _role_constraint(include_participation=False)
    )
