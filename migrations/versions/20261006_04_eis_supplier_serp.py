"""Immutable exact-position public search-engine attempts and captured DOM."""

from alembic import op

TABLE_DDL = (
    "\nCREATE TABLE eis_supplier_serp_runs (\n\tcompany_id TEXT NOT NULL, \n\tru"
    "n_id TEXT NOT NULL, \n\tcache_key VARCHAR(64) NOT NULL, \n\tpurchase_numbe"
    "r TEXT NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tnotice_xml_sha25"
    "6 VARCHAR(64) NOT NULL, \n\tsource_index INTEGER NOT NULL, \n\treport JSON"
    "B NOT NULL, \n\treport_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTA"
    "MP WITH TIME ZONE NOT NULL, \n\tsource_bundle BYTEA, \n\tsource_bundle_sha"
    "256 VARCHAR(64), \n\tsource_bundle_byte_count INTEGER, \n\tCONSTRAINT pk_e"
    "is_supplier_serp_runs PRIMARY KEY (company_id, run_id), \n\tCONSTRAINT f"
    "k_eis_supplier_serp_notice FOREIGN KEY(company_id, purchase_number, ve"
    "rsion_number) REFERENCES eis_notice_versions (company_id, purchase_num"
    "ber, version_number), \n\tCONSTRAINT ck_eis_supplier_serp_identity CHECK"
    " (btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND cache_"
    "key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND notice"
    "_xml_sha256 ~ '^[0-9a-f]{64}$' AND run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-"
    "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'), \n\tCONSTRAINT ck_eis_supplier_"
    "serp_report_size CHECK (jsonb_typeof(report) = 'object' AND octet_leng"
    "th(report::text) <= 262144), \n\tCONSTRAINT ck_eis_supplier_serp_report_"
    "identity CHECK (COALESCE((report->>'policy_version' = 'eis-position-su"
    "pplier-serp-v1' AND report->>'run_id' = run_id AND report->'request'->"
    "'selection'->'notice'->>'purchase_number' = purchase_number AND (repor"
    "t->'request'->'selection'->'notice'->>'version_number')::int = version"
    "_number AND report->'request'->'selection'->'notice'->>'notice_xml_sha"
    "256' = notice_xml_sha256 AND (report->'request'->'selection'->>'source"
    "_index')::int = source_index AND (report->>'created_at')::timestamptz "
    "= created_at AND report->>'query_scope' = 'PUBLIC_POSITION_NAME_FIXED_"
    "SUPPLIER_TERMS' AND report->>'full_market_coverage' = 'UNKNOWN' AND re"
    "port->>'supplier_identity' = 'UNKNOWN' AND report->>'price' = 'UNKNOWN"
    "' AND report->>'stock' = 'UNKNOWN' AND report->>'delivery' = 'UNKNOWN'"
    " AND report->>'technical' = 'UNKNOWN' AND report->>'quote' = 'UNKNOWN'"
    " AND report->>'participation' = 'UNKNOWN' AND ((source_bundle IS NULL "
    "AND report->'source_bundle_sha256' = 'null'::jsonb AND report->'source"
    "_bundle_byte_count' = 'null'::jsonb) OR (source_bundle IS NOT NULL AND"
    " report->>'source_bundle_sha256' = source_bundle_sha256 AND (report->>"
    "'source_bundle_byte_count')::int = source_bundle_byte_count)) AND ((re"
    "port->>'status' = 'STARTED' AND report->'batch' = 'null'::jsonb AND re"
    "port->'attempted_source_requests' = 'null'::jsonb AND source_bundle IS"
    " NULL) OR (report->>'status' = 'QUERY_NOT_COVERED' AND report->'batch'"
    " = 'null'::jsonb AND report->'query' = 'null'::jsonb AND (report->>'at"
    "tempted_source_requests')::int = 0 AND source_bundle IS NULL) OR (repo"
    "rt->>'status' IN ('COMPLETED','PARTIAL','UNAVAILABLE') AND report->'ba"
    "tch'->>'status' = report->>'status' AND report->'batch'->>'query' = re"
    "port->>'query' AND report->'batch'->>'coverage' = 'UNKNOWN' AND (repor"
    "t->'batch'->>'supplierpage_requests')::int = 0 AND jsonb_array_length("
    "report->'batch'->'attempts') = 3 AND (report->>'attempted_source_reque"
    "sts')::int BETWEEN 0 AND 3))), false)), \n\tCONSTRAINT ck_eis_supplier_s"
    "erp_bundle CHECK ((source_bundle IS NULL AND source_bundle_sha256 IS N"
    "ULL AND source_bundle_byte_count IS NULL) OR (source_bundle IS NOT NUL"
    "L AND source_bundle_sha256 IS NOT NULL AND source_bundle_byte_count IS"
    " NOT NULL AND source_bundle_sha256 ~ '^[0-9a-f]{64}$' AND source_bundl"
    "e_byte_count BETWEEN 1 AND 8388608 AND octet_length(source_bundle) = s"
    "ource_bundle_byte_count AND source_bundle_sha256 = encode(sha256(sourc"
    "e_bundle), 'hex')))\n)\n\n"
)
INDEX_DDL = (
    (
        "CREATE INDEX ix_eis_supplier_serp_basis ON eis_supplier_serp_runs (com"
        "pany_id, cache_key, created_at DESC)"
    ),
    (
        "CREATE INDEX ix_eis_supplier_serp_budget ON eis_supplier_serp_runs (co"
        "mpany_id, created_at DESC)"
    ),
)

revision = "20261006_04"
down_revision = "20261006_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    name = "eis_supplier_serp_runs"
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    op.execute(TABLE_DDL)
    for statement in INDEX_DDL:
        op.execute(statement)
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
    op.execute("""CREATE FUNCTION check_eis_supplier_serp_notice() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM eis_notice_versions n WHERE n.company_id=NEW.company_id
        AND n.purchase_number=NEW.purchase_number AND n.version_number=NEW.version_number
        AND n.xml_sha256=NEW.notice_xml_sha256) THEN
        RAISE EXCEPTION 'supplier search requires exact XML';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER eis_supplier_serp_notice_bound BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_supplier_serp_notice()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_supplier_serp_runs) "
        "THEN RAISE EXCEPTION 'supplier search history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_supplier_serp_runs")
    op.execute("DROP FUNCTION check_eis_supplier_serp_notice()")
