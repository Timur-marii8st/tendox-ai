"""Persist exact application submission intents and independent approvals.

Revision ID: 20260921_04
Revises: 20260921_03
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import (
    application_submission_approvals,
    application_submission_intents,
)

revision: str = "20260921_04"
down_revision: str | None = "20260921_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
ROLES = (
    "'OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
    "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER', "
    "'PARTICIPATION_APPROVER', 'APPLICATION_REVIEWER', "
)


def upgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN (" + ROLES + "'APPLICATION_SUBMISSION_APPROVER', 'AUDITOR')",
    )
    for table in (application_submission_intents, application_submission_approvals):
        op.create_table(
            table.name, *[column.copy() for column in table.columns], *table.constraints
        )
        name = table.name
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({TENANT})")
        op.execute(f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({TENANT})")
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
        )
        op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
            f"THEN GRANT SELECT, INSERT ON {name} TO procurement_app; END IF; END $$"
        )


def downgrade() -> None:
    op.drop_table("application_submission_approvals")
    op.drop_table("application_submission_intents")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN (" + ROLES + "'AUDITOR')",
    )
