"""Immutable full-XSD observations bound to exact 223 XML bytes."""

from alembic import op

from procurement.storage.models import eis_223_schema_checks

revision = "20261002_08"
down_revision = "20261002_07"
branch_labels = None
depends_on = None


def upgrade():
    # Older source migrations use current metadata when creating a fresh test database.
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conr"
        "elid='eis_223_notice_versions'::regclass AND conname='uq_eis_223_"
        "notice_xml') THEN ALTER TABLE eis_223_notice_versions ADD CONSTRA"
        "INT uq_eis_223_notice_xml UNIQUE(company_id,purchase_number,versi"
        "on_number,xml_sha256); END IF; END $$"
    )
    table = eis_223_schema_checks
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
    op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='proc"
        "urement_app') THEN GRANT SELECT, INSERT ON eis_223_schema_checks "
        "TO procurement_app; END IF; END $$"
    )


def downgrade():
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_223_schema_checks) THEN R"
        "AISE EXCEPTION '223 schema evidence must be preserved'; END IF; E"
        "ND $$"
    )
    op.drop_table("eis_223_schema_checks")
    op.drop_constraint("uq_eis_223_notice_xml", "eis_223_notice_versions", type_="unique")
