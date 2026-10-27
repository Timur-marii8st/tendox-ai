"""Immutable owner-aware positions for exact223 source versions."""

from alembic import op

from procurement.storage.models import eis_223_position_projections

revision = "20261027_02"
down_revision = "20261027_01"
branch_labels = None
depends_on = None


def upgrade():
    table = eis_223_position_projections
    name = table.name
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    op.execute("SET LOCAL statement_timeout='5s'")
    op.execute("SET LOCAL lock_timeout='2s'")
    op.create_table(name, *[c.copy() for c in table.columns], *table.constraints)
    for statement in (
        f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({tenant})",
        f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({tenant})",
        f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()",
        f"REVOKE ALL ON TABLE {name} FROM PUBLIC",
        f"GRANT SELECT, INSERT ON {name} TO procurement_app",
    ):
        op.execute(statement)


def downgrade():
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_223_position_projections) "
        "THEN RAISE EXCEPTION '223 position history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_223_position_projections")
