"""Exact tenant immutable native document receipts for 223; no 44 identifier reuse."""

from alembic import op

from procurement.storage.models import eis_223_document_receipts

revision = "20261002_09"
down_revision = "20261002_08"
branch_labels = None
depends_on = None


def upgrade():
    table = eis_223_document_receipts
    name = table.name
    op.create_table(name, *[c.copy() for c in table.columns], *table.constraints)
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
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
    op.execute("""CREATE FUNCTION check_eis_223_receipt_manifest()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE matches integer; uids integer;
    BEGIN
      SELECT count(*) INTO uids FROM eis_223_notice_versions n,
        jsonb_array_elements(n.snapshot->'attachments') a
      WHERE n.company_id=NEW.company_id AND n.purchase_number=NEW.purchase_number
        AND n.version_number=NEW.version_number AND n.xml_sha256=NEW.notice_xml_sha256
        AND a->'content_uid'->>'value'=NEW.content_uid;
      SELECT count(*) INTO matches FROM eis_223_notice_versions n,
        jsonb_array_elements(n.snapshot->'attachments') a
      WHERE n.company_id=NEW.company_id AND n.purchase_number=NEW.purchase_number
        AND n.version_number=NEW.version_number AND n.xml_sha256=NEW.notice_xml_sha256
        AND a->'content_uid'->>'value'=NEW.content_uid
        AND a->'filename'->>'value'=NEW.filename
        AND a->'url'->>'value'=NEW.source_url
        AND a->'url'->'provenance'->>'locator'=NEW.source_locator;
      IF matches <> 1 OR uids <> 1 THEN
        RAISE EXCEPTION '223 receipt manifest mismatch';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER {name}_manifest BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_223_receipt_manifest()"
    )


def downgrade():
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_223_document_receipts) THEN "
        "RAISE EXCEPTION '223 document evidence must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_223_document_receipts")
    op.execute("DROP FUNCTION check_eis_223_receipt_manifest()")
