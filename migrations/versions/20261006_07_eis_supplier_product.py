"""Immutable source0 product terms alongside an exact public EIS position."""

from alembic import op

revision = "20261006_07"
down_revision = "20261006_06"
branch_labels = None
depends_on = None

TABLE_DDL = (
    "CREATE TABLE eis_supplier_product_reports (\n\tcompany_id TEXT NOT "
    "NULL, \n\trun_id TEXT NOT NULL, \n\tcache_key VARCHAR(64) NOT NULL, \n"
    "\tpurchase_number TEXT NOT NULL, \n\tversion_number INTEGER NOT NULL"
    ", \n\tnotice_xml_sha256 VARCHAR(64) NOT NULL, \n\tsource_index INTEGE"
    "R NOT NULL, \n\tparent_product_run_id TEXT NOT NULL, \n\treport JSONB"
    " NOT NULL, \n\treport_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIM"
    "ESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_eis_supplier_prod"
    "uct_reports PRIMARY KEY (company_id, run_id), \n\tCONSTRAINT uq_eis"
    "_supplier_product_cache UNIQUE (company_id, cache_key), \n\tCONSTRA"
    "INT fk_eis_supplier_product_parent FOREIGN KEY(company_id, parent"
    "_product_run_id) REFERENCES eis_supplier_catalog_runs (company_id"
    ", run_id), \n\tCONSTRAINT fk_eis_supplier_product_notice FOREIGN KE"
    "Y(company_id, purchase_number, version_number) REFERENCES eis_not"
    "ice_versions (company_id, purchase_number, version_number), \n\tCON"
    "STRAINT ck_eis_supplier_product_identity CHECK (btrim(company_id)"
    "<>'' AND source_index BETWEEN 1 AND 25 AND cache_key ~ '^[0-9a-f]"
    "{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND notice_xml_sha256"
    " ~ '^[0-9a-f]{64}$' AND run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-"
    "f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'), \n\tCONSTRAINT ck_eis_supplier_p"
    "roduct_size CHECK (jsonb_typeof(report)='object' AND octet_length"
    "(report::text)<=262144), \n\tCONSTRAINT ck_eis_supplier_product_bin"
    "ding CHECK ((report->>'policy_version'='eis-position-supplier-pro"
    "duct-v1' AND report->>'scope'='PUBLIC_POSITION_AND_SAVED_PRODUCT'"
    " AND report->>'run_id'=run_id AND (report->>'created_at')::timest"
    "amptz=created_at AND report->'request'->>'product_run_id'=parent_"
    "product_run_id AND report->'position'->'selection'->'notice'->>'p"
    "urchase_number'=purchase_number AND (report->'position'->'selecti"
    "on'->'notice'->>'version_number')::int=version_number AND report-"
    ">'position'->'selection'->'notice'->>'notice_xml_sha256'=notice_x"
    "ml_sha256 AND (report->'position'->'selection'->>'source_index'):"
    ":int=source_index AND report->'request'->'catalog'->'page'->'posi"
    "tion'->'selection'=report->'position'->'selection' AND report->>'"
    "parent_product_report_sha256' ~ '^[0-9a-f]{64}$' AND report->>'po"
    "sition_sha256' ~ '^[0-9a-f]{64}$' AND report->>'source_body_sha25"
    "6' ~ '^[0-9a-f]{64}$' AND report->'details'->>'html_sha256'=repor"
    "t->>'source_body_sha256') IS TRUE), \n\tCONSTRAINT ck_eis_supplier_"
    "product_unknown CHECK ((report->>'technical'='UNKNOWN' AND report"
    "->>'price_comparability'='UNKNOWN' AND report->>'unit_cost'='UNKN"
    "OWN' AND report->>'party_total'='UNKNOWN' AND report->>'quote'='U"
    "NKNOWN' AND report->>'profit'='UNKNOWN' AND report->>'participati"
    "on'='UNKNOWN' AND report->>'specification_completeness'='UNKNOWN'"
    " AND report->>'source_requests'='0' AND report->>'jobs_created'='"
    "0' AND jsonb_typeof(report->'rows')='array' AND jsonb_array_lengt"
    "h(report->'rows')<=24 AND (report->>'row_count')::int=jsonb_array"
    "_length(report->'rows')) IS TRUE)\n)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    op.execute(TABLE_DDL)
    name = "eis_supplier_product_reports"
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
    op.execute("""CREATE FUNCTION check_eis_supplier_product_parent() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM eis_supplier_catalog_runs p
        WHERE p.company_id=NEW.company_id AND p.run_id=NEW.parent_product_run_id
        AND p.stage='PRODUCT' AND p.report->>'status'='COMPLETED'
        AND p.report->'observation'->>'status'='COMPLETED'
        AND p.source_body IS NOT NULL AND p.source_body_byte_count BETWEEN 1 AND 2097152
        AND p.source_body_sha256=NEW.report->>'source_body_sha256'
        AND p.report_sha256=NEW.report->>'parent_product_report_sha256'
        AND p.report->>'position_sha256'=NEW.report->>'position_sha256'
        AND p.report->'request'=NEW.report->'request'->'catalog'
        AND p.report->'observation'->>'final_url'=NEW.report->'details'->>'source_url'
        AND p.purchase_number=NEW.purchase_number AND p.version_number=NEW.version_number
        AND p.notice_xml_sha256=NEW.notice_xml_sha256 AND p.source_index=NEW.source_index
      ) THEN RAISE EXCEPTION 'product details require exact retained product'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER {name}_parent BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_supplier_product_parent()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_supplier_product_reports) "
        "THEN RAISE EXCEPTION 'product detail history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_supplier_product_reports")
    op.execute("DROP FUNCTION check_eis_supplier_product_parent()")
