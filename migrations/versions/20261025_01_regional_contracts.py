"""Official contract evidence and bounded indexed regional history."""

from alembic import op

revision = "20261025_01"
down_revision = "20261023_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("""CREATE TABLE eis_contract_evidence (
        company_id TEXT NOT NULL CHECK(btrim(company_id)<>''),
        sha256 VARCHAR(64) NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
        kind TEXT NOT NULL CHECK(kind IN ('ZIP','SOAP','JSON','HTML')),
        content BYTEA NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 8388608),
        PRIMARY KEY(company_id,sha256),
        CHECK(sha256=encode(sha256(content),'hex'))
    )""")
    op.execute("""CREATE TABLE eis_contract_observations (
        company_id TEXT NOT NULL CHECK(btrim(company_id)<>''),
        receipt_id VARCHAR(64) NOT NULL CHECK(receipt_id ~ '^[0-9a-f]{64}$'),
        registry_number TEXT NOT NULL CHECK(registry_number ~ '^[0-9]{19,23}$'),
        checked_at TIMESTAMPTZ NOT NULL,
        region_key TEXT, product_key TEXT, procedure TEXT, unit TEXT, quantity NUMERIC,
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'
            AND octet_length(payload::text)<=262144),
        payload_sha256 VARCHAR(64) NOT NULL CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
        source_receipts JSONB NOT NULL CHECK(jsonb_typeof(source_receipts)='array'
            AND octet_length(source_receipts::text)<=32768),
        audit_event_id TEXT NOT NULL,
        PRIMARY KEY(company_id,receipt_id),
        FOREIGN KEY(company_id,audit_event_id) REFERENCES audit_events(company_id,event_id)
    )""")
    op.execute("""CREATE TABLE eis_contract_observation_sources (
        company_id TEXT NOT NULL, receipt_id VARCHAR(64) NOT NULL, sha256 VARCHAR(64) NOT NULL,
        PRIMARY KEY(company_id,receipt_id,sha256),
        FOREIGN KEY(company_id,receipt_id) REFERENCES
            eis_contract_observations(company_id,receipt_id),
        FOREIGN KEY(company_id,sha256) REFERENCES eis_contract_evidence(company_id,sha256)
    )""")
    op.execute(
        "CREATE INDEX ix_contract_market ON eis_contract_observations "
        "(company_id,region_key,product_key,procedure,unit,checked_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_contract_latest ON eis_contract_observations "
        "(company_id,registry_number,checked_at DESC,receipt_id DESC)"
    )
    tenant = "company_id = nullif(current_setting('app.company_id',true),'')"
    for table in (
        "eis_contract_evidence",
        "eis_contract_observations",
        "eis_contract_observation_sources",
    ):
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({tenant})",
            f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({tenant})",
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()",
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC",
            f"GRANT SELECT,INSERT ON {table} TO procurement_app",
        ):
            op.execute(statement)


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_contract_observations LIMIT 1)
        OR EXISTS(SELECT 1 FROM eis_contract_evidence LIMIT 1)
        THEN RAISE EXCEPTION 'contract history is not empty'; END IF; END $$""")
    for table in (
        "eis_contract_observation_sources",
        "eis_contract_observations",
        "eis_contract_evidence",
    ):
        op.drop_table(table)
