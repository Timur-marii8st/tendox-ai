"""Append-only tenant journal for the bounded region50 AESMBO refresh."""

from alembic import op
from sqlalchemy import CheckConstraint

from procurement.storage.models import eis_223_sync_attempts

revision = "20261002_05"
down_revision = "20261002_04"
branch_labels = None
depends_on = None


def upgrade():
    table = eis_223_sync_attempts
    name = table.name
    constraints = [c for c in table.constraints if c.name != "ck_eis_223_attempt_scope"]
    constraints.append(
        CheckConstraint(
            "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
            "[+]03:00/purchaseNoticeAESMBO$'",
            name="ck_eis_223_attempt_scope",
        )
    )
    op.create_table(name, *[column.copy() for column in table.columns], *constraints)
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
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
    op.create_index("ix_eis_223_attempt_recent", name, ["company_id", "window_key", "checked_at"])


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_sync_attempts) "
        "THEN RAISE EXCEPTION '223 source history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_223_sync_attempts")
