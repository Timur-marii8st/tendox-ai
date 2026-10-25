"""Immutable beta quote/cost declarations with tenant RLS and audit."""

from alembic import op

revision = "20261021_01"
down_revision = "20261015_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("""CREATE TABLE beta_quote_records (
      company_id TEXT NOT NULL, record_id TEXT NOT NULL,
      law TEXT NOT NULL, purchase_number TEXT NOT NULL, version_number INTEGER NOT NULL,
      xml_sha256 VARCHAR(64) NOT NULL, lot_index INTEGER NOT NULL,
      payload JSONB NOT NULL, payload_sha256 VARCHAR(64) NOT NULL,
      created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, audit_event_id TEXT NOT NULL,
      PRIMARY KEY(company_id,record_id),
      FOREIGN KEY(company_id,audit_event_id) REFERENCES audit_events(company_id,event_id),
      CHECK(company_id<>'' AND created_by<>'' AND version_number>=1),
      CHECK(xml_sha256 ~ '^[0-9a-f]{64}$' AND payload_sha256 ~ '^[0-9a-f]{64}$'),
      CHECK((law='44' AND lot_index=0) OR (law='223' AND lot_index>=1)),
      CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=32768)
    )""")
    op.execute(
        "CREATE INDEX ix_beta_quote_notice ON beta_quote_records "
        "(company_id,law,purchase_number,version_number,xml_sha256,lot_index,created_at DESC)"
    )
    tenant = "company_id = nullif(current_setting('app.company_id',true),'')"
    for sql in (
        "ALTER TABLE beta_quote_records ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE beta_quote_records FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY beta_quote_select ON beta_quote_records FOR SELECT USING ({tenant})",
        f"CREATE POLICY beta_quote_insert ON beta_quote_records FOR INSERT WITH CHECK ({tenant})",
        "CREATE TRIGGER beta_quote_immutable BEFORE UPDATE OR DELETE ON beta_quote_records "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()",
        "REVOKE ALL ON TABLE beta_quote_records FROM PUBLIC",
        "GRANT SELECT,INSERT ON beta_quote_records TO procurement_app",
    ):
        op.execute(sql)


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM beta_quote_records LIMIT 1)
      THEN RAISE EXCEPTION 'beta quote history is not empty'; END IF; END $$""")
    op.drop_table("beta_quote_records")
