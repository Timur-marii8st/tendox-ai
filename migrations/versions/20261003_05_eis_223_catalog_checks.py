"""Immutable observations of the bounded official public region selector."""

from alembic import op
from sqlalchemy import text

from procurement.storage.models import eis_223_region_catalog_checks

revision = "20261003_05"
down_revision = "20261003_04"
branch_labels = None
depends_on = None


def upgrade():
    table = eis_223_region_catalog_checks
    name = table.name
    op.create_table(name, *[c.copy() for c in table.columns], *table.constraints)
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    op.execute(f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({tenant})")
    op.execute(f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({tenant})")
    op.execute(
        f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.create_index(
        "ix_eis_223_region_check_latest",
        name,
        ["company_id", text("checked_at DESC"), text("attempt_id DESC")],
    )
    op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
        f"THEN GRANT SELECT, INSERT ON {name} TO procurement_app; END IF; END $$"
    )


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_region_catalog_checks) "
        "THEN RAISE EXCEPTION '223 catalog observation history must be preserved'; "
        "END IF; END $$"
    )
    op.drop_table("eis_223_region_catalog_checks")
