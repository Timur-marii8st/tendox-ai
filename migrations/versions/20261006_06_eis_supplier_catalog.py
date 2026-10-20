"""Immutable bounded supplier site search and product observations."""

from alembic import op

TABLE_DDL = (
    "\nCREATE TABLE eis_supplier_catalog_runs (\n\tcompany_id TEXT NOT NU"
    "LL, \n\trun_id TEXT NOT NULL, \n\tcache_key VARCHAR(64) NOT NULL, \n\tp"
    "urchase_number TEXT NOT NULL, \n\tversion_number INTEGER NOT NULL, "
    "\n\tnotice_xml_sha256 VARCHAR(64) NOT NULL, \n\tsource_index INTEGER "
    "NOT NULL, \n\tparent_page_run_id TEXT NOT NULL, \n\tstage TEXT NOT NU"
    "LL, \n\tparent_search_run_id TEXT, \n\tproduct_index INTEGER, \n\trepor"
    "t JSONB NOT NULL, \n\treport_sha256 VARCHAR(64) NOT NULL, \n\tcreated"
    "_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsource_body BYTEA, \n\tsou"
    "rce_body_sha256 VARCHAR(64), \n\tsource_body_byte_count INTEGER, \n\t"
    "CONSTRAINT pk_eis_supplier_catalog_runs PRIMARY KEY (company_id, "
    "run_id), \n\tCONSTRAINT fk_eis_supplier_catalog_page FOREIGN KEY(co"
    "mpany_id, parent_page_run_id) REFERENCES eis_supplier_page_runs ("
    "company_id, run_id), \n\tCONSTRAINT fk_eis_supplier_catalog_search "
    "FOREIGN KEY(company_id, parent_search_run_id) REFERENCES eis_supp"
    "lier_catalog_runs (company_id, run_id), \n\tCONSTRAINT fk_eis_suppl"
    "ier_catalog_notice FOREIGN KEY(company_id, purchase_number, versi"
    "on_number) REFERENCES eis_notice_versions (company_id, purchase_n"
    "umber, version_number), \n\tCONSTRAINT ck_eis_supplier_catalog_iden"
    "tity CHECK (btrim(company_id) <> '' AND source_index BETWEEN 1 AN"
    "D 25 AND cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a"
    "-f]{64}$' AND notice_xml_sha256 ~ '^[0-9a-f]{64}$' AND run_id ~ '"
    "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' A"
    "ND ((stage='SEARCH' AND parent_search_run_id IS NULL AND product_"
    "index IS NULL) OR (stage='PRODUCT' AND parent_search_run_id IS NO"
    "T NULL AND product_index IS NOT NULL AND product_index BETWEEN 1 "
    "AND 10))), \n\tCONSTRAINT ck_eis_supplier_catalog_size CHECK (jsonb"
    "_typeof(report)='object' AND octet_length(report::text)<=262144),"
    " \n\tCONSTRAINT ck_eis_supplier_catalog_report_identity CHECK (COAL"
    "ESCE((report->>'policy_version'='eis-position-supplier-catalog-v1"
    "' AND report->>'run_id'=run_id AND report->>'stage'=stage AND rep"
    "ort->'request'->>'page_run_id'=parent_page_run_id AND report->'re"
    "quest'->'page'->'position'->'selection'->'notice'->>'purchase_num"
    "ber'=purchase_number AND (report->'request'->'page'->'position'->"
    "'selection'->'notice'->>'version_number')::int=version_number AND"
    " report->'request'->'page'->'position'->'selection'->'notice'->>'"
    "notice_xml_sha256'=notice_xml_sha256 AND (report->'request'->'pag"
    "e'->'position'->'selection'->>'source_index')::int=source_index A"
    "ND report->>'parent_page_report_sha256' ~ '^[0-9a-f]{64}$' AND re"
    "port->>'position_sha256' ~ '^[0-9a-f]{64}$' AND (report->>'create"
    "d_at')::timestamptz=created_at AND report->>'supplier_identity'='"
    "UNKNOWN' AND report->>'price_comparability'='UNKNOWN' AND report-"
    ">>'tax'='UNKNOWN' AND report->>'stock'='UNKNOWN' AND report->>'de"
    "livery'='UNKNOWN' AND report->>'technical'='UNKNOWN' AND report->"
    ">'quote'='UNKNOWN' AND report->>'participation'='UNKNOWN' AND ((s"
    "tage='SEARCH' AND jsonb_typeof(report->'search_spec')='object' AN"
    "D report->'selected_link'='null'::jsonb AND report->'parent_searc"
    "h_report_sha256'='null'::jsonb AND report->'request'->'search_run"
    "_id'='null'::jsonb AND report->'request'->'product_index'='null':"
    ":jsonb) OR (stage='PRODUCT' AND report->'search_spec'='null'::jso"
    "nb AND report->'links'='null'::jsonb AND report->'request'->>'sea"
    "rch_run_id'=parent_search_run_id AND (report->'request'->>'produc"
    "t_index')::int=product_index AND (report->'selected_link'->>'inde"
    "x')::int=product_index AND report->>'parent_search_report_sha256'"
    " ~ '^[0-9a-f]{64}$')) AND ((source_body IS NULL AND report->'sour"
    "ce_body_sha256'='null'::jsonb AND report->'source_body_byte_count"
    "'='null'::jsonb) OR (source_body IS NOT NULL AND report->>'source"
    "_body_sha256'=source_body_sha256 AND (report->>'source_body_byte_"
    "count')::int=source_body_byte_count)) AND ((report->>'status'='ST"
    "ARTED' AND report->>'reason_code'='SOURCE_OUTCOME_UNKNOWN' AND re"
    "port->'observation'='null'::jsonb AND report->'links'='null'::jso"
    "nb AND report->'attempted_source_requests'='null'::jsonb AND sour"
    "ce_body IS NULL) OR (report->>'status'='COMPLETED' AND report->>'"
    "reason_code'='FIXED_CATALOG_OBSERVATION' AND jsonb_typeof(report-"
    ">'observation')='object' AND (report->>'attempted_source_requests"
    "')::int BETWEEN 0 AND 3 AND (report->>'attempted_source_requests'"
    ")::int=(report->'observation'->>'dispatch_count')::int AND report"
    "->'observation'->>'source_url'=CASE WHEN stage='SEARCH' THEN repo"
    "rt->'search_spec'->>'search_url' ELSE report->'selected_link'->>'"
    "url' END AND report->'observation'->>'technical_status'='UNKNOWN'"
    " AND report->'observation'->>'quote_status'='UNKNOWN' AND report-"
    ">'observation'->>'configured_cost_status'='UNKNOWN' AND report->'"
    "observation'->>'identity_status'='UNKNOWN' AND report->'observati"
    "on'->'html_sha256'=report->'source_body_sha256' AND report->'obse"
    "rvation'->'byte_count'=report->'source_body_byte_count'))),false)"
    "), \n\tCONSTRAINT ck_eis_supplier_catalog_body CHECK ((source_body "
    "IS NULL AND source_body_sha256 IS NULL AND source_body_byte_count"
    " IS NULL) OR (source_body IS NOT NULL AND source_body_sha256 IS N"
    "OT NULL AND source_body_byte_count IS NOT NULL AND source_body_sh"
    "a256 ~ '^[0-9a-f]{64}$' AND source_body_byte_count BETWEEN 1 AND "
    "2097152 AND octet_length(source_body)=source_body_byte_count AND "
    "source_body_sha256=encode(sha256(source_body),'hex')))\n)\n\n"
)
INDEX_DDL = (
    "CREATE INDEX ix_eis_supplier_catalog_basis ON eis_supplier_catalog_runs "
    "(company_id, cache_key, created_at DESC)",
    "CREATE INDEX ix_eis_supplier_catalog_budget ON eis_supplier_catalog_runs "
    "(company_id, created_at DESC)",
)

revision = "20261006_06"
down_revision = "20261006_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    name = "eis_supplier_catalog_runs"
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
    op.execute("""CREATE FUNCTION check_eis_supplier_catalog_parent() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM eis_notice_versions n WHERE n.company_id=NEW.company_id
        AND n.purchase_number=NEW.purchase_number AND n.version_number=NEW.version_number
        AND n.xml_sha256=NEW.notice_xml_sha256) THEN
        RAISE EXCEPTION 'catalog requires exact XML';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM eis_supplier_page_runs p WHERE p.company_id=NEW.company_id
        AND p.run_id=NEW.parent_page_run_id AND p.report->>'status'='COMPLETED'
        AND p.report->'observation'->>'status'='COMPLETED' AND p.source_body IS NOT NULL
        AND p.purchase_number=NEW.purchase_number AND p.version_number=NEW.version_number
        AND p.notice_xml_sha256=NEW.notice_xml_sha256 AND p.source_index=NEW.source_index
        AND p.report_sha256=NEW.report->>'parent_page_report_sha256'
        AND p.report->>'position_sha256'=NEW.report->>'position_sha256'
        AND p.report->'request'=NEW.report->'request'->'page'
        AND (NEW.stage='PRODUCT' OR
          (p.source_body_sha256=NEW.report->'search_spec'->>'html_sha256'
           AND p.report->'observation'->>'final_url'=NEW.report->'search_spec'->>'source_url'))
      ) THEN RAISE EXCEPTION 'catalog requires exact root page'; END IF;
      IF NEW.stage='PRODUCT' AND NOT EXISTS(SELECT 1 FROM eis_supplier_catalog_runs p
        CROSS JOIN LATERAL jsonb_array_elements(p.report->'links'->'links') AS l
        WHERE p.company_id=NEW.company_id AND p.run_id=NEW.parent_search_run_id
        AND p.stage='SEARCH' AND p.report->>'status'='COMPLETED'
        AND p.report->'observation'->>'status'='COMPLETED' AND p.source_body IS NOT NULL
        AND p.report->'links'->>'status'='FOUND'
        AND p.parent_page_run_id=NEW.parent_page_run_id
        AND p.purchase_number=NEW.purchase_number AND p.version_number=NEW.version_number
        AND p.notice_xml_sha256=NEW.notice_xml_sha256 AND p.source_index=NEW.source_index
        AND p.report_sha256=NEW.report->>'parent_search_report_sha256'
        AND p.report->>'position_sha256'=NEW.report->>'position_sha256'
        AND p.report->'request'->'page'=NEW.report->'request'->'page'
        AND (l->>'index')::int=NEW.product_index
        AND l=NEW.report->'selected_link'
        AND l->>'html_sha256'=p.source_body_sha256
      ) THEN RAISE EXCEPTION 'catalog requires exact search product'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER eis_supplier_catalog_parent_bound BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_supplier_catalog_parent()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_supplier_catalog_runs) "
        "THEN RAISE EXCEPTION 'catalog history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_supplier_catalog_runs")
    op.execute("DROP FUNCTION check_eis_supplier_catalog_parent()")
