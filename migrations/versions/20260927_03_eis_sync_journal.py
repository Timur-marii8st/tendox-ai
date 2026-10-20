"""Persist planned EIS date windows and immutable attempt evidence.

Revision ID: 20260927_03
Revises: 20260927_02
Create Date: 2026-09-27
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Table

from procurement.storage.models import eis_sync_attempts, eis_sync_targets

revision: str = "20260927_03"
down_revision: str | None = "20260927_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def _create_immutable_tenant_table(table: Table) -> None:
    name = table.name
    op.create_table(name, *[column.copy() for column in table.columns], *table.constraints)
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


def upgrade() -> None:
    _create_immutable_tenant_table(eis_sync_targets)
    _create_immutable_tenant_table(eis_sync_attempts)
    op.create_index(
        "ix_eis_sync_attempts_window_time",
        "eis_sync_attempts",
        ["company_id", "window_key", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_eis_sync_attempts_window_time", table_name="eis_sync_attempts")
    op.drop_table("eis_sync_attempts")
    op.drop_table("eis_sync_targets")
