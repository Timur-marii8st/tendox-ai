"""Keep exact READY response and archive URL provenance for EIS imports.

Revision ID: 20260927_02
Revises: 20260927_01
Create Date: 2026-09-27
"""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import eis_feed_archive_sources

revision: str = "20260927_02"
down_revision: str | None = "20260927_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    table = eis_feed_archive_sources
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


def downgrade() -> None:
    op.drop_table(eis_feed_archive_sources.name)
