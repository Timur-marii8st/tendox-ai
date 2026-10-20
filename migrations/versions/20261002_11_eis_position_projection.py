"""Immutable tenant source position projections; preserve original EIS versions."""

from alembic import op

from procurement.storage.models import eis_notice_position_projections

revision = "20261002_11"
down_revision = "20261002_10"
branch_labels = None
depends_on = None


def upgrade():
    table = eis_notice_position_projections
    name = table.name
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
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
    op.execute("""CREATE FUNCTION check_eis_position_projection() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM eis_notice_versions n WHERE n.company_id=NEW.company_id
        AND n.purchase_number=NEW.purchase_number AND n.version_number=NEW.version_number
        AND n.xml_sha256=NEW.notice_xml_sha256) THEN
        RAISE EXCEPTION 'position projection requires exact XML';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER eis_position_projection_bound BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_position_projection()"
    )


def downgrade():
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_notice_position_projections) "
        "THEN RAISE EXCEPTION 'position projection history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_notice_position_projections")
    op.execute("DROP FUNCTION check_eis_position_projection()")
