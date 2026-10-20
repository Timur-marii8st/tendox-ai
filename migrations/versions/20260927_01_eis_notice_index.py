"""Immutable tenant-scoped intake of official EIS hourly auction archives.

Revision ID: 20260927_01
Revises: 20260921_05
Create Date: 2026-09-27
"""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import (
    eis_feed_archives,
    eis_feed_windows,
    eis_notice_versions,
)

revision: str = "20260927_01"
down_revision: str | None = "20260921_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
TABLES = (eis_feed_windows, eis_feed_archives, eis_notice_versions)


def upgrade() -> None:
    for table in TABLES:
        name = table.name
        op.create_table(
            name,
            *[column.copy() for column in table.columns],
            *table.constraints,
        )
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
    op.create_index("ix_eis_notice_versions_title", "eis_notice_versions", ["company_id", "title"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table.name)
