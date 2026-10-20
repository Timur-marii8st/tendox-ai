"""Immutable tenant-scoped official cancellation events.

Revision ID: 20260928_02
Revises: 20260928_01
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import eis_procedure_events

revision: str = "20260928_02"
down_revision: str | None = "20260928_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = eis_procedure_events
    name = table.name
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    op.create_table(name, *[column.copy() for column in table.columns], *table.constraints)
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({tenant})")
    op.execute(f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({tenant})")
    op.execute(
        f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
        f"THEN GRANT SELECT, INSERT ON {name} TO procurement_app; END IF; END $$"
    )
    op.create_index(
        "ix_eis_events_purchase", name, ["company_id", "purchase_number", "published_at"]
    )


def downgrade() -> None:
    # Explicit downgrade removes the new event table; never invoked by deployment.
    op.drop_table("eis_procedure_events")
