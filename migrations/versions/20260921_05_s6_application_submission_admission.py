"""Persist one permanent no-dispatch claim for an exact approved application.

Revision ID: 20260921_05
Revises: 20260921_04
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import application_submission_admissions

revision: str = "20260921_05"
down_revision: str | None = "20260921_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "application_submission_admissions"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
ROLES = (
    "'OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
    "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER', "
    "'PARTICIPATION_APPROVER', 'APPLICATION_REVIEWER', "
    "'APPLICATION_SUBMISSION_APPROVER', "
)


def upgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN (" + ROLES + "'APPLICATION_SUBMISSION_EXECUTOR', 'AUDITOR')",
    )
    op.create_table(
        TABLE,
        *[column.copy() for column in application_submission_admissions.columns],
        *application_submission_admissions.constraints,
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(
        f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
        f"THEN GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table(TABLE)
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN (" + ROLES + "'AUDITOR')",
    )
