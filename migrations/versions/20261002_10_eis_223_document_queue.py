"""Immutable223document jobs and bounded attempt journal."""

from alembic import op

from procurement.storage.models import eis_223_document_attempts, eis_223_document_jobs

revision = "20261002_10"
down_revision = "20261002_09"
branch_labels = None
depends_on = None


def upgrade():
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for table in (eis_223_document_jobs, eis_223_document_attempts):
        name = table.name
        op.create_table(name, *[c.copy() for c in table.columns], *table.constraints)
        for index in table.indexes:
            op.create_index(index.name, name, [c.name for c in index.columns])
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
    op.execute("""CREATE FUNCTION check_eis_223_document_attempt() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE matches integer;
    BEGIN
      SELECT count(*) INTO matches FROM eis_223_notice_versions n,
        jsonb_array_elements(n.snapshot->'attachments') a
      WHERE n.company_id=NEW.company_id AND n.purchase_number=NEW.purchase_number
        AND n.version_number=NEW.version_number AND n.xml_sha256=NEW.notice_xml_sha256
        AND a->'content_uid'->>'value'=NEW.content_uid;
      IF matches <> 1 THEN RAISE EXCEPTION '223 attempt manifest mismatch'; END IF;
      IF NEW.status='RECEIVED' AND NOT EXISTS (SELECT 1 FROM eis_223_document_receipts r
        WHERE r.company_id=NEW.company_id AND r.purchase_number=NEW.purchase_number
        AND r.version_number=NEW.version_number AND r.notice_xml_sha256=NEW.notice_xml_sha256
        AND r.content_uid=NEW.content_uid) THEN
        RAISE EXCEPTION '223 received attempt requires exact receipt';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER eis_223_document_attempt_bound BEFORE INSERT ON "
        "eis_223_document_attempts FOR EACH ROW "
        "EXECUTE FUNCTION check_eis_223_document_attempt()"
    )


def downgrade():
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_223_document_jobs) OR "
        "EXISTS(SELECT 1 FROM eis_223_document_attempts) THEN RAISE EXCEPTION "
        "'223 document queue history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_223_document_attempts")
    op.drop_table("eis_223_document_jobs")
    op.execute("DROP FUNCTION check_eis_223_document_attempt()")
