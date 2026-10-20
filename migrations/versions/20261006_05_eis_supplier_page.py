"""Immutable exact-position public candidate page observations and captured HTML."""

from alembic import op

TABLE_DDL = (
    "\nCREATE TABLE eis_supplier_page_runs (\n\tcompany_id TEXT NOT NULL, \n\tru"
    "n_id TEXT NOT NULL, \n\tcache_key VARCHAR(64) NOT NULL, \n\tpurchase_numbe"
    "r TEXT NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tnotice_xml_sha25"
    "6 VARCHAR(64) NOT NULL, \n\tsource_index INTEGER NOT NULL, \n\tparent_serp"
    "_run_id TEXT NOT NULL, \n\tengine TEXT NOT NULL, \n\trank INTEGER NOT NULL"
    ", \n\treport JSONB NOT NULL, \n\treport_sha256 VARCHAR(64) NOT NULL, \n\tcre"
    "ated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsource_body BYTEA, \n\tsour"
    "ce_body_sha256 VARCHAR(64), \n\tsource_body_byte_count INTEGER, \n\tCONSTR"
    "AINT pk_eis_supplier_page_runs PRIMARY KEY (company_id, run_id), \n\tCON"
    "STRAINT fk_eis_supplier_page_serp FOREIGN KEY(company_id, parent_serp_"
    "run_id) REFERENCES eis_supplier_serp_runs (company_id, run_id), \n\tCONS"
    "TRAINT fk_eis_supplier_page_notice FOREIGN KEY(company_id, purchase_nu"
    "mber, version_number) REFERENCES eis_notice_versions (company_id, purc"
    "hase_number, version_number), \n\tCONSTRAINT ck_eis_supplier_page_identi"
    "ty CHECK (btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AN"
    "D rank BETWEEN 1 AND 50 AND engine IN ('BING','YANDEX','GOOGLE') AND r"
    "un_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    "$' AND cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}"
    "$' AND notice_xml_sha256 ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT ck_eis_supp"
    "lier_page_size CHECK (jsonb_typeof(report) = 'object' AND octet_length"
    "(report::text) <= 262144), \n\tCONSTRAINT ck_eis_supplier_page_report_id"
    "entity CHECK (COALESCE((report->>'policy_version' = 'eis-position-supp"
    "lier-page-v1' AND report->>'run_id' = run_id AND report->'request'->'p"
    "osition'->'selection'->'notice'->>'purchase_number' = purchase_number "
    "AND (report->'request'->'position'->'selection'->'notice'->>'version_n"
    "umber')::int = version_number AND report->'request'->'position'->'sele"
    "ction'->'notice'->>'notice_xml_sha256' = notice_xml_sha256 AND (report"
    "->'request'->'position'->'selection'->>'source_index')::int = source_i"
    "ndex AND report->'request'->>'serp_run_id' = parent_serp_run_id AND re"
    "port->'request'->>'engine' = engine AND (report->'request'->>'rank')::"
    "int = rank AND (report->'link'->>'rank')::int = rank AND report->>'par"
    "ent_report_sha256' ~ '^[0-9a-f]{64}$' AND report->>'position_sha256' ~"
    " '^[0-9a-f]{64}$' AND (report->>'created_at')::timestamptz = created_a"
    "t AND report->>'supplier_identity' = 'UNKNOWN' AND report->>'price_com"
    "parability' = 'UNKNOWN' AND report->>'tax' = 'UNKNOWN' AND report->>'s"
    "tock' = 'UNKNOWN' AND report->>'delivery' = 'UNKNOWN' AND report->>'te"
    "chnical' = 'UNKNOWN' AND report->>'quote' = 'UNKNOWN' AND report->>'pa"
    "rticipation' = 'UNKNOWN' AND ((source_body IS NULL AND report->'source"
    "_body_sha256' = 'null'::jsonb AND report->'source_body_byte_count' = '"
    "null'::jsonb) OR (source_body IS NOT NULL AND report->>'source_body_sh"
    "a256' = source_body_sha256 AND (report->>'source_body_byte_count')::in"
    "t = source_body_byte_count)) AND ((report->>'status' = 'STARTED' AND r"
    "eport->>'reason_code' = 'SOURCE_OUTCOME_UNKNOWN' AND report->'observat"
    "ion' = 'null'::jsonb AND report->'attempted_source_requests' = 'null':"
    ":jsonb AND source_body IS NULL) OR (report->>'status' = 'COMPLETED' AN"
    "D report->>'reason_code' = 'FIXED_PUBLIC_PAGE_OBSERVATION' AND jsonb_t"
    "ypeof(report->'observation') = 'object' AND report->'observation'->>'s"
    "ource_url' = report->'link'->>'url' AND (report->>'attempted_source_re"
    "quests')::int BETWEEN 0 AND 3 AND (report->>'attempted_source_requests"
    "')::int = (report->'observation'->>'dispatch_count')::int AND report->"
    "'observation'->>'technical_status' = 'UNKNOWN' AND report->'observatio"
    "n'->>'quote_status' = 'UNKNOWN' AND report->'observation'->>'configure"
    "d_cost_status' = 'UNKNOWN' AND report->'observation'->>'identity_statu"
    "s' = 'UNKNOWN' AND report->'observation'->'html_sha256' = report->'sou"
    "rce_body_sha256' AND report->'observation'->'byte_count' = report->'so"
    "urce_body_byte_count'))), false)), \n\tCONSTRAINT ck_eis_supplier_page_b"
    "ody CHECK ((source_body IS NULL AND source_body_sha256 IS NULL AND sou"
    "rce_body_byte_count IS NULL) OR (source_body IS NOT NULL AND source_bo"
    "dy_sha256 IS NOT NULL AND source_body_byte_count IS NOT NULL AND sourc"
    "e_body_sha256 ~ '^[0-9a-f]{64}$' AND source_body_byte_count BETWEEN 1 "
    "AND 2097152 AND octet_length(source_body) = source_body_byte_count AND"
    " source_body_sha256 = encode(sha256(source_body), 'hex')))\n)\n\n"
)
INDEX_DDL = (
    (
        "CREATE INDEX ix_eis_supplier_page_basis ON eis_supplier_page_runs (com"
        "pany_id, cache_key, created_at DESC)"
    ),
    (
        "CREATE INDEX ix_eis_supplier_page_budget ON eis_supplier_page_runs (co"
        "mpany_id, created_at DESC)"
    ),
)

revision = "20261006_05"
down_revision = "20261006_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    name = "eis_supplier_page_runs"
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
    op.execute("""CREATE FUNCTION check_eis_supplier_page_parent() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM eis_notice_versions n WHERE n.company_id=NEW.company_id
        AND n.purchase_number=NEW.purchase_number AND n.version_number=NEW.version_number
        AND n.xml_sha256=NEW.notice_xml_sha256) THEN
        RAISE EXCEPTION 'supplier page requires exact XML';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM eis_supplier_serp_runs p
        CROSS JOIN LATERAL jsonb_array_elements(p.report->'batch'->'attempts') AS a
        CROSS JOIN LATERAL jsonb_array_elements(a->'links') AS l
        WHERE p.company_id=NEW.company_id AND p.run_id=NEW.parent_serp_run_id
        AND p.purchase_number=NEW.purchase_number AND p.version_number=NEW.version_number
        AND p.notice_xml_sha256=NEW.notice_xml_sha256 AND p.source_index=NEW.source_index
        AND p.report_sha256=NEW.report->>'parent_report_sha256'
        AND p.report->>'position_sha256'=NEW.report->>'position_sha256'
        AND a->>'engine'=NEW.engine AND (l->>'rank')::int=NEW.rank
        AND l=NEW.report->'link') THEN
        RAISE EXCEPTION 'supplier page requires exact parent SERP link';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        f"CREATE TRIGGER eis_supplier_page_parent_bound BEFORE INSERT ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION check_eis_supplier_page_parent()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM eis_supplier_page_runs) "
        "THEN RAISE EXCEPTION 'supplier search history must be preserved'; END IF; END $$"
    )
    op.drop_table("eis_supplier_page_runs")
    op.execute("DROP FUNCTION check_eis_supplier_page_parent()")
