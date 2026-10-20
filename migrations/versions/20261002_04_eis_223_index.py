"""Separate tenant metadata projection for verified 223-FZ AESMBO notices."""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import (
    eis_223_archive_sources,
    eis_223_blobs,
    eis_223_notice_versions,
    eis_223_windows,
)

revision: str = "20261002_04"
down_revision: str | None = "20261002_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
TABLES = (eis_223_windows, eis_223_blobs, eis_223_archive_sources, eis_223_notice_versions)
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    for table in TABLES:
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
    op.create_index(
        "ix_eis_223_search_keys", "eis_223_notice_versions", ["search_keys"], postgresql_using="gin"
    )


def downgrade() -> None:
    # Match other immutable source migrations: no silent deletion of source history.
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_windows) "
        "THEN RAISE EXCEPTION '223 source history must be preserved'; END IF; END $$"
    )
    for table in reversed(TABLES):
        op.drop_table(table.name)
