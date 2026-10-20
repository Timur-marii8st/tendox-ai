"""Immutable tenant category snapshots bound to exact EIS positions."""

from alembic import op

from procurement.storage.models import eis_supplier_search_runs

revision = "20261006_02"
down_revision = "20261006_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    table = eis_supplier_search_runs
    name = table.name
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    op.create_table(name, *[c.copy() for c in table.columns], *table.constraints)
    for index in table.indexes:
        index.create(op.get_bind())
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
    op.execute("""CREATE FUNCTION check_eis_supplier_search_notice() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM eis_notice_versions n WHERE n.company_id=NEW.company_id
        AND n.purchase_number=NEW.purchase_number AND n.version_number=NEW.version_number
        AND n.xml_sha256=NEW.notice_xml_sha256) THEN
        RAISE EXCEPTION 'supplier observation requires exact XML';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER eis_supplier_search_notice_bound BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_supplier_search_notice()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_supplier_search_runs) "
        "THEN RAISE EXCEPTION 'supplier source history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_supplier_search_runs")
    op.execute("DROP FUNCTION check_eis_supplier_search_notice()")
