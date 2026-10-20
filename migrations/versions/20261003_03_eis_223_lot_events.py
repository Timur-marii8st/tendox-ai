"""Immutable GUID-based cancellation variants and exact source/quality checkpoints."""

from alembic import op
from sqlalchemy import CheckConstraint

from procurement.storage.models import (
    eis_223_lot_event_archive_sources,
    eis_223_lot_event_schema_checks,
    eis_223_lot_event_sync_attempts,
    eis_223_lot_event_windows,
    eis_223_lot_events,
)

revision = "20261003_03"
down_revision = "20261003_02"
branch_labels = None
depends_on = None
TABLES = (
    eis_223_lot_event_windows,
    eis_223_lot_event_archive_sources,
    eis_223_lot_events,
    eis_223_lot_event_schema_checks,
    eis_223_lot_event_sync_attempts,
)


def upgrade():
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for table in TABLES:
        name = table.name
        constraints = list(table.constraints)
        if name == "eis_223_lot_event_sync_attempts":
            constraints = [
                c for c in constraints if c.name != "ck_eis_223_lot_event_attempt_scope"
            ]
            constraints.append(
                CheckConstraint(
                    "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
                    "[+]03:00/purchaseLotCancellation$'",
                    name="ck_eis_223_lot_event_attempt_scope",
                )
            )
        op.create_table(name, *[c.copy() for c in table.columns], *constraints)
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
        for index in table.indexes:
            op.create_index(index.name, name, [c.name for c in index.columns])


def downgrade():
    op.execute("SET LOCAL row_security = off")
    condition = " OR ".join(f"EXISTS (SELECT 1 FROM {t.name})" for t in TABLES)
    op.execute(
        f"DO $$ BEGIN IF {condition} THEN RAISE EXCEPTION "
        "'223 lot cancellation history must be preserved'; END IF; END $$"
    )
    for table in reversed(TABLES):
        op.drop_table(table.name)
