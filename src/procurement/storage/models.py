"""SQLAlchemy Core schema for the PostgreSQL persistence boundary."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

# Independent public search-engine leads; snippets never confirm seller or price.
eis_supplier_serp_runs = Table(
    "eis_supplier_serp_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("source_index", Integer, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("report_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("source_bundle", LargeBinary),
    Column("source_bundle_sha256", String(64)),
    Column("source_bundle_byte_count", Integer),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_eis_supplier_serp_runs"),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_supplier_serp_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND "
        "cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$' AND "
        "run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        name="ck_eis_supplier_serp_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(report) = 'object' AND octet_length(report::text) <= 262144",
        name="ck_eis_supplier_serp_report_size",
    ),
    CheckConstraint(
        "COALESCE((report->>'policy_version' IN "
        "('eis-position-supplier-serp-v1','eis-position-supplier-serp-v2') AND "
        "report->>'run_id' = run_id AND "
        "report->'request'->'selection'->'notice'->>'purchase_number' = purchase_number AND "
        "(report->'request'->'selection'->'notice'->>'version_number')::int = version_number AND "
        "report->'request'->'selection'->'notice'->>'notice_xml_sha256' = notice_xml_sha256 AND "
        "(report->'request'->'selection'->>'source_index')::int = source_index AND "
        "(report->>'created_at')::timestamptz = created_at AND "
        "report->>'query_scope' = 'PUBLIC_POSITION_NAME_FIXED_SUPPLIER_TERMS' AND "
        "report->>'full_market_coverage' = 'UNKNOWN' AND "
        "report->>'supplier_identity' = 'UNKNOWN' AND report->>'price' = 'UNKNOWN' AND "
        "report->>'stock' = 'UNKNOWN' AND report->>'delivery' = 'UNKNOWN' AND "
        "report->>'technical' = 'UNKNOWN' AND report->>'quote' = 'UNKNOWN' AND "
        "report->>'participation' = 'UNKNOWN' AND "
        "((source_bundle IS NULL AND report->'source_bundle_sha256' = 'null'::jsonb "
        "AND report->'source_bundle_byte_count' = 'null'::jsonb) OR "
        "(source_bundle IS NOT NULL AND report->>'source_bundle_sha256' = source_bundle_sha256 "
        "AND (report->>'source_bundle_byte_count')::int = source_bundle_byte_count)) AND "
        "((report->>'status' = 'STARTED' AND report->'batch' = 'null'::jsonb AND "
        "report->'attempted_source_requests' = 'null'::jsonb AND source_bundle IS NULL) OR "
        "(report->>'status' = 'QUERY_NOT_COVERED' AND report->'batch' = 'null'::jsonb AND "
        "report->'query' = 'null'::jsonb AND (report->>'attempted_source_requests')::int = 0 "
        "AND source_bundle IS NULL) OR "
        "(report->>'status' IN ('COMPLETED','PARTIAL','UNAVAILABLE') AND "
        "report->'batch'->>'status' = report->>'status' AND "
        "report->'batch'->>'query' = report->>'query' AND "
        "report->'batch'->>'coverage' = 'UNKNOWN' AND "
        "(report->'batch'->>'supplierpage_requests')::int = 0 AND "
        "((report->>'policy_version' = 'eis-position-supplier-serp-v1' AND "
        "jsonb_array_length(report->'batch'->'attempts') = 3 AND "
        "(report->>'attempted_source_requests')::int BETWEEN 0 AND 3) OR "
        "(report->>'policy_version' = 'eis-position-supplier-serp-v2' AND "
        "jsonb_array_length(report->'batch'->'attempts') = 6 AND "
        "(report->>'attempted_source_requests')::int BETWEEN 0 AND 6))))), false)",
        name="ck_eis_supplier_serp_report_identity",
    ),
    CheckConstraint(
        "(source_bundle IS NULL AND source_bundle_sha256 IS NULL "
        "AND source_bundle_byte_count IS NULL) OR "
        "(source_bundle IS NOT NULL AND source_bundle_sha256 IS NOT NULL "
        "AND source_bundle_byte_count IS NOT NULL AND "
        "source_bundle_sha256 ~ '^[0-9a-f]{64}$' "
        "AND source_bundle_byte_count BETWEEN 1 AND 13631488 AND "
        "octet_length(source_bundle) = source_bundle_byte_count AND "
        "source_bundle_sha256 = encode(sha256(source_bundle), 'hex'))",
        name="ck_eis_supplier_serp_bundle",
    ),
)
Index(
    "ix_eis_supplier_serp_basis",
    eis_supplier_serp_runs.c.company_id,
    eis_supplier_serp_runs.c.cache_key,
    eis_supplier_serp_runs.c.created_at.desc(),
)
Index(
    "ix_eis_supplier_serp_budget",
    eis_supplier_serp_runs.c.company_id,
    eis_supplier_serp_runs.c.created_at.desc(),
)

# Public candidate page observations; declarations never establish quote or suitability.
eis_supplier_page_runs = Table(
    "eis_supplier_page_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("source_index", Integer, nullable=False),
    Column("parent_serp_run_id", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("rank", Integer, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("report_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("source_body", LargeBinary),
    Column("source_body_sha256", String(64)),
    Column("source_body_byte_count", Integer),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_eis_supplier_page_runs"),
    ForeignKeyConstraint(
        ["company_id", "parent_serp_run_id"],
        ["eis_supplier_serp_runs.company_id", "eis_supplier_serp_runs.run_id"],
        name="fk_eis_supplier_page_serp",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_supplier_page_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND "
        "rank BETWEEN 1 AND 50 AND "
        "engine IN ('BING','BRAVE','DUCKDUCKGO','MOJEEK','YANDEX','GOOGLE') AND "
        "run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND "
        "cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_supplier_page_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(report) = 'object' AND octet_length(report::text) <= 262144",
        name="ck_eis_supplier_page_size",
    ),
    CheckConstraint(
        "COALESCE((report->>'policy_version' = 'eis-position-supplier-page-v1' AND "
        "report->>'run_id' = run_id AND "
        "report->'request'->'position'->'selection'->'notice'->>'purchase_numbe"
        "r' = purchase_number AND "
        "(report->'request'->'position'->'selection'->'notice'->>'version_numbe"
        "r')::int = version_number AND "
        "report->'request'->'position'->'selection'->'notice'->>'notice_xml_sha"
        "256' = notice_xml_sha256 AND "
        "(report->'request'->'position'->'selection'->>'source_index')::int = source_index AND "
        "report->'request'->>'serp_run_id' = parent_serp_run_id AND "
        "report->'request'->>'engine' = engine AND (report->'request'->>'rank')::int = rank AND "
        "(report->'link'->>'rank')::int = rank AND "
        "report->>'parent_report_sha256' ~ '^[0-9a-f]{64}$' AND "
        "report->>'position_sha256' ~ '^[0-9a-f]{64}$' AND "
        "(report->>'created_at')::timestamptz = created_at AND "
        "report->>'supplier_identity' = 'UNKNOWN' AND report->>'price_comparabi"
        "lity' = 'UNKNOWN' AND "
        "report->>'tax' = 'UNKNOWN' AND report->>'stock' = 'UNKNOWN' AND "
        "report->>'delivery' = 'UNKNOWN' AND report->>'technical' = 'UNKNOWN' AND "
        "report->>'quote' = 'UNKNOWN' AND report->>'participation' = 'UNKNOWN' AND "
        "((source_body IS NULL AND report->'source_body_sha256' = 'null'::jsonb AND "
        "report->'source_body_byte_count' = 'null'::jsonb) OR "
        "(source_body IS NOT NULL AND report->>'source_body_sha256' = source_body_sha256 AND "
        "(report->>'source_body_byte_count')::int = source_body_byte_count)) AND "
        "((report->>'status' = 'STARTED' AND report->>'reason_code' = 'SOURCE_OUTCOME_UNKNOWN' AND "
        "report->'observation' = 'null'::jsonb AND report->'attempted_source_re"
        "quests' = 'null'::jsonb AND source_body IS NULL) OR "
        "(report->>'status' = 'COMPLETED' AND report->>'reason_code' = 'FIXED_P"
        "UBLIC_PAGE_OBSERVATION' AND "
        "jsonb_typeof(report->'observation') = 'object' AND "
        "report->'observation'->>'source_url' = report->'link'->>'url' AND "
        "(report->>'attempted_source_requests')::int BETWEEN 0 AND 3 AND "
        "(report->>'attempted_source_requests')::int = (report->'observation'->"
        ">'dispatch_count')::int AND "
        "report->'observation'->>'technical_status' = 'UNKNOWN' AND "
        "report->'observation'->>'quote_status' = 'UNKNOWN' AND "
        "report->'observation'->>'configured_cost_status' = 'UNKNOWN' AND "
        "report->'observation'->>'identity_status' = 'UNKNOWN' AND "
        "report->'observation'->'html_sha256' = report->'source_body_sha256' AND "
        "report->'observation'->'byte_count' = report->'source_body_byte_count'))), false)",
        name="ck_eis_supplier_page_report_identity",
    ),
    CheckConstraint(
        "(source_body IS NULL AND source_body_sha256 IS NULL AND source_body_by"
        "te_count IS NULL) OR "
        "(source_body IS NOT NULL AND source_body_sha256 IS NOT NULL AND "
        "source_body_byte_count IS NOT NULL AND source_body_sha256 ~ '^[0-9a-f]{64}$' AND "
        "source_body_byte_count BETWEEN 1 AND 2097152 AND octet_length(source_b"
        "ody) = source_body_byte_count AND "
        "source_body_sha256 = encode(sha256(source_body), 'hex'))",
        name="ck_eis_supplier_page_body",
    ),
)
Index(
    "ix_eis_supplier_page_basis",
    eis_supplier_page_runs.c.company_id,
    eis_supplier_page_runs.c.cache_key,
    eis_supplier_page_runs.c.created_at.desc(),
)
Index(
    "ix_eis_supplier_page_budget",
    eis_supplier_page_runs.c.company_id,
    eis_supplier_page_runs.c.created_at.desc(),
)

# Source0 details derived from one retained product, without duplicating its HTML.
eis_supplier_product_reports = Table(
    "eis_supplier_product_reports",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("source_index", Integer, nullable=False),
    Column("parent_product_run_id", Text, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("report_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_eis_supplier_product_reports"),
    UniqueConstraint("company_id", "cache_key", name="uq_eis_supplier_product_cache"),
    ForeignKeyConstraint(
        ["company_id", "parent_product_run_id"],
        ["eis_supplier_catalog_runs.company_id", "eis_supplier_catalog_runs.run_id"],
        name="fk_eis_supplier_product_parent",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_supplier_product_notice",
    ),
    CheckConstraint(
        "btrim(company_id)<>'' AND source_index BETWEEN 1 AND 25 AND "
        "cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$' AND "
        "run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        name="ck_eis_supplier_product_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(report)='object' AND octet_length(report::text)<=262144",
        name="ck_eis_supplier_product_size",
    ),
    CheckConstraint(
        "(report->>'policy_version'='eis-position-supplier-product-v1' AND "
        "report->>'scope'='PUBLIC_POSITION_AND_SAVED_PRODUCT' AND "
        "report->>'run_id'=run_id AND (report->>'created_at')::timestamptz=created_at AND "
        "report->'request'->>'product_run_id'=parent_product_run_id AND "
        "report->'position'->'selection'->'notice'->>'purchase_number'=purchase_number AND "
        "(report->'position'->'selection'->'notice'->>'version_number')::int=version_number AND "
        "report->'position'->'selection'->'notice'->>'notice_xml_sha256'=notice_xml_sha256 AND "
        "(report->'position'->'selection'->>'source_index')::int=source_index AND "
        "report->'request'->'catalog'->'page'->'position'->'selection'="
        "report->'position'->'selection' AND "
        "report->>'parent_product_report_sha256' ~ '^[0-9a-f]{64}$' AND "
        "report->>'position_sha256' ~ '^[0-9a-f]{64}$' AND "
        "report->>'source_body_sha256' ~ '^[0-9a-f]{64}$' AND "
        "report->'details'->>'html_sha256'=report->>'source_body_sha256') IS TRUE",
        name="ck_eis_supplier_product_binding",
    ),
    CheckConstraint(
        "(report->>'technical'='UNKNOWN' AND report->>'price_comparability'='UNKNOWN' AND "
        "report->>'unit_cost'='UNKNOWN' AND report->>'party_total'='UNKNOWN' AND "
        "report->>'quote'='UNKNOWN' AND report->>'profit'='UNKNOWN' AND "
        "report->>'participation'='UNKNOWN' AND "
        "report->>'specification_completeness'='UNKNOWN' AND "
        "report->>'source_requests'='0' AND report->>'jobs_created'='0' AND "
        "jsonb_typeof(report->'rows')='array' AND jsonb_array_length(report->'rows')<=24 AND "
        "(report->>'row_count')::int=jsonb_array_length(report->'rows')) IS TRUE",
        name="ck_eis_supplier_product_unknown",
    ),
)

eis_requirement_review_proposals = Table(
    "eis_requirement_review_proposals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("request_key", String(64), nullable=False),
    Column("product_run_id", Text, nullable=False),
    Column("proposal", JSONB, nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("prepared_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "proposal_id", name="pk_eis_requirement_review_proposals"),
    UniqueConstraint("company_id", "request_key", name="uq_eis_requirement_review_proposal_key"),
    ForeignKeyConstraint(
        ["company_id", "product_run_id"],
        ["eis_supplier_product_reports.company_id", "eis_supplier_product_reports.run_id"],
        name="fk_eis_requirement_review_product",
    ),
    CheckConstraint(
        "(btrim(company_id)<>'' AND btrim(prepared_by)<>'' AND "
        "request_key ~ '^[0-9a-f]{64}$' AND proposal_sha256 ~ '^[0-9a-f]{64}$' AND "
        "proposal_id ~ '^[0-9a-f-]{36}$' AND jsonb_typeof(proposal)='object' AND "
        "octet_length(proposal::text)<=393216 AND proposal->>'company_id'=company_id AND "
        "proposal->>'proposal_id'=proposal_id AND proposal->>'proposal_sha256'=proposal_sha256 AND "
        "proposal->>'prepared_by'=prepared_by AND "
        "(proposal->>'prepared_at')::timestamptz=prepared_at AND "
        "proposal->'preview'->'product'->>'run_id'=product_run_id) IS TRUE",
        name="ck_eis_requirement_review_proposal",
    ),
)

eis_requirement_review_decisions = Table(
    "eis_requirement_review_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("decision_id", Text, nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "decision_id", name="pk_eis_requirement_review_decisions"),
    UniqueConstraint("company_id", "proposal_id", name="uq_eis_requirement_review_decision"),
    ForeignKeyConstraint(
        ["company_id", "proposal_id"],
        [
            "eis_requirement_review_proposals.company_id",
            "eis_requirement_review_proposals.proposal_id",
        ],
        name="fk_eis_requirement_review_proposal",
    ),
    CheckConstraint(
        "(btrim(company_id)<>'' AND btrim(reviewed_by)<>'' AND "
        "request_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$' AND "
        "decision_id ~ '^[0-9a-f-]{36}$' AND jsonb_typeof(decision)='object' AND "
        "octet_length(decision::text)<=393216 AND decision->>'company_id'=company_id AND "
        "decision->>'decision_id'=decision_id AND decision->>'decision_sha256'=decision_sha256 AND "
        "decision->>'reviewed_by'=reviewed_by AND "
        "(decision->>'reviewed_at')::timestamptz=reviewed_at AND "
        "decision->'request'->>'proposal_id'=proposal_id) IS TRUE",
        name="ck_eis_requirement_review_decision",
    ),
)

# Bounded site search and selected product reads, rooted in an exact page snapshot.
eis_supplier_catalog_runs = Table(
    "eis_supplier_catalog_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("source_index", Integer, nullable=False),
    Column("parent_page_run_id", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("parent_search_run_id", Text),
    Column("product_index", Integer),
    Column("report", JSONB, nullable=False),
    Column("report_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("source_body", LargeBinary),
    Column("source_body_sha256", String(64)),
    Column("source_body_byte_count", Integer),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_eis_supplier_catalog_runs"),
    ForeignKeyConstraint(
        ["company_id", "parent_page_run_id"],
        ["eis_supplier_page_runs.company_id", "eis_supplier_page_runs.run_id"],
        name="fk_eis_supplier_catalog_page",
    ),
    ForeignKeyConstraint(
        ["company_id", "parent_search_run_id"],
        ["eis_supplier_catalog_runs.company_id", "eis_supplier_catalog_runs.run_id"],
        name="fk_eis_supplier_catalog_search",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_supplier_catalog_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND "
        "cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$' AND "
        "run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND "
        "((stage='SEARCH' AND parent_search_run_id IS NULL AND product_index IS NULL) OR "
        "(stage='PRODUCT' AND parent_search_run_id IS NOT NULL AND product"
        "_index IS NOT NULL AND product_index BETWEEN 1 AND 10))",
        name="ck_eis_supplier_catalog_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(report)='object' AND octet_length(report::text)<=262144",
        name="ck_eis_supplier_catalog_size",
    ),
    CheckConstraint(
        "COALESCE((report->>'policy_version'='eis-position-supplier-catalog-v1' AND "
        "report->>'run_id'=run_id AND report->>'stage'=stage AND "
        "report->'request'->>'page_run_id'=parent_page_run_id AND "
        "report->'request'->'page'->'position'->'selection'->'notice'->>'p"
        "urchase_number'=purchase_number AND "
        "(report->'request'->'page'->'position'->'selection'->'notice'->>'"
        "version_number')::int=version_number AND "
        "report->'request'->'page'->'position'->'selection'->'notice'->>'n"
        "otice_xml_sha256'=notice_xml_sha256 AND "
        "(report->'request'->'page'->'position'->'selection'->>'source_ind"
        "ex')::int=source_index AND "
        "report->>'parent_page_report_sha256' ~ '^[0-9a-f]{64}$' AND repor"
        "t->>'position_sha256' ~ '^[0-9a-f]{64}$' AND "
        "(report->>'created_at')::timestamptz=created_at AND "
        "report->>'supplier_identity'='UNKNOWN' AND report->>'price_compar"
        "ability'='UNKNOWN' AND "
        "report->>'tax'='UNKNOWN' AND report->>'stock'='UNKNOWN' AND repor"
        "t->>'delivery'='UNKNOWN' AND "
        "report->>'technical'='UNKNOWN' AND report->>'quote'='UNKNOWN' AND"
        " report->>'participation'='UNKNOWN' AND "
        "((stage='SEARCH' AND jsonb_typeof(report->'search_spec')='object'"
        " AND report->'selected_link'='null'::jsonb AND "
        "report->'parent_search_report_sha256'='null'::jsonb AND report->'"
        "request'->'search_run_id'='null'::jsonb AND report->'request'->'p"
        "roduct_index'='null'::jsonb) OR "
        "(stage='PRODUCT' AND report->'search_spec'='null'::jsonb AND repo"
        "rt->'links'='null'::jsonb AND "
        "report->'request'->>'search_run_id'=parent_search_run_id AND (rep"
        "ort->'request'->>'product_index')::int=product_index AND "
        "(report->'selected_link'->>'index')::int=product_index AND report"
        "->>'parent_search_report_sha256' ~ '^[0-9a-f]{64}$')) AND "
        "((source_body IS NULL AND report->'source_body_sha256'='null'::js"
        "onb AND report->'source_body_byte_count'='null'::jsonb) OR "
        "(source_body IS NOT NULL AND report->>'source_body_sha256'=source"
        "_body_sha256 AND (report->>'source_body_byte_count')::int=source_"
        "body_byte_count)) AND "
        "((report->>'status'='STARTED' AND report->>'reason_code'='SOURCE_"
        "OUTCOME_UNKNOWN' AND "
        "report->'observation'='null'::jsonb AND report->'links'='null'::j"
        "sonb AND report->'attempted_source_requests'='null'::jsonb AND so"
        "urce_body IS NULL) OR "
        "(report->>'status'='COMPLETED' AND report->>'reason_code'='FIXED_"
        "CATALOG_OBSERVATION' AND "
        "jsonb_typeof(report->'observation')='object' AND (report->>'attem"
        "pted_source_requests')::int BETWEEN 0 AND 3 AND "
        "(report->>'attempted_source_requests')::int=(report->'observation"
        "'->>'dispatch_count')::int AND "
        "report->'observation'->>'source_url'=CASE WHEN stage='SEARCH' THE"
        "N report->'search_spec'->>'search_url' ELSE report->'selected_lin"
        "k'->>'url' END AND "
        "report->'observation'->>'technical_status'='UNKNOWN' AND report->"
        "'observation'->>'quote_status'='UNKNOWN' AND "
        "report->'observation'->>'configured_cost_status'='UNKNOWN' AND re"
        "port->'observation'->>'identity_status'='UNKNOWN' AND "
        "report->'observation'->'html_sha256'=report->'source_body_sha256'"
        " AND report->'observation'->'byte_count'=report->'source_body_byt"
        "e_count'))),false)",
        name="ck_eis_supplier_catalog_report_identity",
    ),
    CheckConstraint(
        "(source_body IS NULL AND source_body_sha256 IS NULL AND source_bo"
        "dy_byte_count IS NULL) OR "
        "(source_body IS NOT NULL AND source_body_sha256 IS NOT NULL AND s"
        "ource_body_byte_count IS NOT NULL AND "
        "source_body_sha256 ~ '^[0-9a-f]{64}$' AND source_body_byte_count "
        "BETWEEN 1 AND 2097152 AND "
        "octet_length(source_body)=source_body_byte_count AND source_body_"
        "sha256=encode(sha256(source_body),'hex'))",
        name="ck_eis_supplier_catalog_body",
    ),
)
Index(
    "ix_eis_supplier_catalog_basis",
    eis_supplier_catalog_runs.c.company_id,
    eis_supplier_catalog_runs.c.cache_key,
    eis_supplier_catalog_runs.c.created_at.desc(),
)
Index(
    "ix_eis_supplier_catalog_budget",
    eis_supplier_catalog_runs.c.company_id,
    eis_supplier_catalog_runs.c.created_at.desc(),
)


# Operator-selected source text; this association never approves requirements.
eis_position_fragment_associations = Table(
    "eis_position_fragment_associations",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("association_id", Text, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("source_index", Integer, nullable=False),
    Column("content_uid", String(32), nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("report", JSONB, nullable=False),
    Column("report_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "association_id", name="pk_eis_position_association"),
    UniqueConstraint("company_id", "cache_key", name="uq_eis_position_association_basis"),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_position_association_notice",
    ),
    ForeignKeyConstraint(
        ["company_id", "document_sha256"],
        ["eis_document_blobs.company_id", "eis_document_blobs.sha256"],
        name="fk_eis_position_association_document",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND "
        "content_uid ~ '^[0-9A-F]{32}$' AND document_sha256 ~ '^[0-9a-f]{64}$' AND "
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$' AND cache_key ~ '^[0-9a-f]{64}$' AND "
        "report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "association_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        name="ck_eis_position_association_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(report) = 'object' AND octet_length(report::text) <= 262144",
        name="ck_eis_position_association_size",
    ),
    CheckConstraint(
        "COALESCE((report->>'policy_version' = 'eis-position-fragment-association-v1' AND "
        "report->>'association_id' = association_id AND "
        "report->'request'->'position'->'selection'->'notice'->>'purchase_number' "
        "= purchase_number AND "
        "(report->'request'->'position'->'selection'->'notice'->>'version_number')::int "
        "= version_number AND "
        "report->'request'->'position'->'selection'->'notice'->>'notice_xml_sha256' "
        "= notice_xml_sha256 AND "
        "(report->'request'->'position'->'selection'->>'source_index')::int = source_index AND "
        "report->'request'->'document'->'notice' "
        "= report->'request'->'position'->'selection'->'notice' AND "
        "report->'request'->'document'->>'content_uid' = content_uid AND "
        "report->'request'->'document'->>'expected_document_sha256' = document_sha256 AND "
        "report->>'document_sha256' = document_sha256 AND "
        "report->'request'->>'analyzer_version' = 'eis-native-review-v1' AND "
        "(report->>'created_at')::timestamptz = created_at AND "
        "report->>'association_status' = 'OPERATOR_LINKED' AND "
        "report->>'requirement_status' = 'UNKNOWN' AND "
        "report->>'full_tspec_completeness' = 'UNKNOWN' AND "
        "report->>'technical' = 'UNKNOWN' AND report->>'quote' = 'UNKNOWN' AND "
        "report->>'participation' = 'UNKNOWN' AND "
        "(report->>'source_requests')::int = 0 AND (report->>'jobs_created')::int = 0 AND "
        "jsonb_typeof(report->'fragments') = 'array' AND "
        "jsonb_array_length(report->'fragments') BETWEEN 1 AND 10 AND "
        "(report->>'selected_characters')::int BETWEEN 1 AND 16000), false)",
        name="ck_eis_position_association_report_identity",
    ),
)

# One explicitly requested category snapshot, bound to one exact saved EIS position.
eis_supplier_search_runs = Table(
    "eis_supplier_search_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("source_index", Integer, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("report_sha256", String(64), nullable=False),
    Column("source_content", LargeBinary),
    Column("source_sha256", String(64)),
    Column("source_byte_count", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_eis_supplier_search_runs"),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_supplier_search_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND "
        "cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        name="ck_eis_supplier_search_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(report) = 'object' AND octet_length(report::text) <= 262144",
        name="ck_eis_supplier_search_report_size",
    ),
    CheckConstraint(
        "COALESCE((report->>'policy_version' = 'eis-position-supplier-search-v1' AND "
        "report->>'run_id' = run_id AND "
        "report->'request'->'selection'->'notice'->>'purchase_number' = purchase_number AND "
        "(report->'request'->'selection'->'notice'->>'version_number')::int = version_number AND "
        "report->'request'->'selection'->'notice'->>'notice_xml_sha256' = notice_xml_sha256 AND "
        "(report->'request'->'selection'->>'source_index')::int = source_index AND "
        "(report->>'created_at')::timestamptz = created_at AND "
        "report->>'specification_completeness' = 'UNKNOWN' AND "
        "report->>'position_document_association' = 'UNKNOWN' AND "
        "report->>'quote' = 'UNKNOWN' AND report->>'technical' = 'UNKNOWN' AND "
        "report->>'profit' = 'UNKNOWN' AND report->>'participation' = 'UNKNOWN' AND "
        "((report->>'status' IN ('STARTED','QUERY_NOT_COVERED','SOURCE_ERROR') "
        "AND source_content IS NULL "
        "AND report->'observation' = 'null'::jsonb) OR "
        "(report->>'status' = 'COMPLETED' AND source_content IS NOT NULL AND "
        "report->'observation'->>'source_sha256' = source_sha256 AND "
        "(report->'observation'->>'byte_count')::int = source_byte_count))), false)",
        name="ck_eis_supplier_search_report_identity",
    ),
    CheckConstraint(
        "(source_content IS NULL AND source_sha256 IS NULL AND source_byte_count IS NULL) OR "
        "(source_content IS NOT NULL AND source_sha256 IS NOT NULL "
        "AND source_byte_count IS NOT NULL AND source_sha256 ~ '^[0-9a-f]{64}$' AND "
        "source_byte_count BETWEEN 1 AND 2097152 AND "
        "octet_length(source_content) = source_byte_count AND "
        "source_sha256 = encode(sha256(source_content), 'hex'))",
        name="ck_eis_supplier_search_blob_size",
    ),
)
Index(
    "ix_eis_supplier_search_cache",
    eis_supplier_search_runs.c.company_id,
    eis_supplier_search_runs.c.cache_key,
    eis_supplier_search_runs.c.created_at.desc(),
)

# Explicit decisions over complete retained transport; never a source checkpoint.
eis_notice_projection_batches = Table(
    "eis_notice_projection_batches",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("batch_id", Text, nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("archive_sha256s", JSONB, nullable=False),
    Column("occurrence_count", Integer, nullable=False),
    Column("pair_count", Integer, nullable=False),
    Column("projected_count", Integer, nullable=False),
    Column("replayed_count", Integer, nullable=False),
    Column("held_count", Integer, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("audit_event_id", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "batch_id", name="pk_eis_notice_projection_batches"),
    UniqueConstraint("company_id", "receipt_id", "parser_version", name="uq_eis_projection_basis"),
    ForeignKeyConstraint(
        ["company_id", "receipt_id"],
        ["eis_notice_variant_receipts.company_id", "eis_notice_variant_receipts.receipt_id"],
        name="fk_eis_projection_receipt",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256"],
        [
            "eis_feed_windows.company_id",
            "eis_feed_windows.window_key",
            "eis_feed_windows.response_sha256",
        ],
        name="fk_eis_projection_window",
    ),
    ForeignKeyConstraint(
        ["company_id", "audit_event_id"],
        ["audit_events.company_id", "audit_events.event_id"],
        name="fk_eis_projection_audit",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(window_key) <> '' AND "
        "parser_version = 'eis-notice-projection-v1'",
        name="ck_eis_projection_text",
    ),
    CheckConstraint(
        "batch_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
        "AND payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_projection_identity",
    ),
    CheckConstraint(
        "occurrence_count BETWEEN 1 AND 2000 AND pair_count BETWEEN 1 AND occurrence_count "
        "AND projected_count >= 0 AND replayed_count >= 0 AND held_count >= 0 "
        "AND projected_count + replayed_count + held_count = pair_count "
        "AND jsonb_typeof(archive_sha256s) = 'array' "
        "AND jsonb_array_length(archive_sha256s) BETWEEN 1 AND 20",
        name="ck_eis_projection_counts",
    ),
)

eis_notice_projection_decisions = Table(
    "eis_notice_projection_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("batch_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("document_type", Text),
    Column("xml_sha256", String(64)),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    Column("input_sha256", String(64), nullable=False),
    Column("snapshot_sha256", String(64)),
    Column("snapshot", JSONB(none_as_null=True)),
    Column("archive_sha256", String(64)),
    Column("member_filename", Text),
    PrimaryKeyConstraint(
        "company_id",
        "batch_id",
        "purchase_number",
        "version_number",
        name="pk_eis_notice_projection_decisions",
    ),
    ForeignKeyConstraint(
        ["company_id", "batch_id"],
        ["eis_notice_projection_batches.company_id", "eis_notice_projection_batches.batch_id"],
        name="fk_eis_projection_decision_batch",
    ),
    CheckConstraint(
        "purchase_number ~ '^[0-9]{19,23}$' AND version_number >= 1 "
        "AND input_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_projection_decision_identity",
    ),
    CheckConstraint(
        "status IN ('PROJECTED', 'REPLAYED', 'HOLD') AND ((status = 'HOLD' "
        "AND reason IS NOT NULL AND btrim(reason) <> '' AND snapshot IS NULL "
        "AND snapshot_sha256 IS NULL) OR (status IN ('PROJECTED', 'REPLAYED') "
        "AND reason IS NULL AND snapshot IS NOT NULL AND snapshot_sha256 IS NOT NULL "
        "AND xml_sha256 IS NOT NULL AND document_type IS NOT NULL "
        "AND archive_sha256 IS NOT NULL AND member_filename IS NOT NULL))",
        name="ck_eis_projection_decision_status",
    ),
    CheckConstraint(
        "(xml_sha256 IS NULL OR xml_sha256 ~ '^[0-9a-f]{64}$') "
        "AND (snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$') "
        "AND (archive_sha256 IS NULL OR archive_sha256 ~ '^[0-9a-f]{64}$')",
        name="ck_eis_projection_decision_sha",
    ),
    CheckConstraint(
        "snapshot IS NULL OR (jsonb_typeof(snapshot) = 'object' "
        "AND octet_length(snapshot::text) <= 2097152 "
        "AND snapshot->>'purchase_number' IS NOT DISTINCT FROM purchase_number "
        "AND (snapshot->>'version_number')::integer IS NOT DISTINCT FROM version_number "
        "AND snapshot->>'document_type' IS NOT DISTINCT FROM document_type "
        "AND snapshot->>'xml_sha256' IS NOT DISTINCT FROM xml_sha256)",
        name="ck_eis_projection_decision_snapshot",
    ),
)
Index(
    "ix_eis_projection_decision_notice",
    eis_notice_projection_decisions.c.company_id,
    eis_notice_projection_decisions.c.purchase_number,
    eis_notice_projection_decisions.c.version_number,
)

# 223-FZ identifiers, lots and source shape have their own immutable projection.
eis_223_windows = Table(
    "eis_223_windows",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("prepared_sha256", String(64), nullable=False),
    Column("manifest_sha256", String(64), nullable=False),
    Column("archive_count", Integer, nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "window_key", "response_sha256", name="pk_eis_223_windows"),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_company"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$' "
        "OR window_key ~ '^getDocsIP/RI223/by-number/[0-9]{11}/purchaseNoticeKESMBO$'",
        name="ck_eis_223_window",
    ),
    CheckConstraint(
        "response_sha256 ~ '^[0-9a-f]{64}$' AND prepared_sha256 ~ '^[0-9a-f]{64}$' "
        "AND manifest_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_window_hashes",
    ),
    CheckConstraint(
        "archive_count BETWEEN 1 AND 8 AND record_count >= 1", name="ck_eis_223_counts"
    ),
)
eis_223_blobs = Table(
    "eis_223_blobs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    PrimaryKeyConstraint("company_id", "archive_sha256", name="pk_eis_223_blobs"),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_blob_company"),
    CheckConstraint("archive_sha256 = encode(sha256(content), 'hex')", name="ck_eis_223_blob_sha"),
    CheckConstraint("octet_length(content) BETWEEN 1 AND 16777216", name="ck_eis_223_blob_size"),
)
eis_223_archive_sources = Table(
    "eis_223_archive_sources",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("source_url", Text, nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "window_key",
        "response_sha256",
        "archive_sha256",
        name="pk_eis_223_archive_sources",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256"],
        [
            "eis_223_windows.company_id",
            "eis_223_windows.window_key",
            "eis_223_windows.response_sha256",
        ],
        name="fk_eis_223_archive_window",
    ),
    ForeignKeyConstraint(
        ["company_id", "archive_sha256"],
        ["eis_223_blobs.company_id", "eis_223_blobs.archive_sha256"],
        name="fk_eis_223_archive_blob",
    ),
)
eis_223_notice_versions = Table(
    "eis_223_notice_versions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("snapshot", JSONB, nullable=False),
    Column("search_keys", ARRAY(Text), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "purchase_number", "version_number", name="pk_eis_223_notice_versions"
    ),
    UniqueConstraint(
        "company_id",
        "purchase_number",
        "version_number",
        "xml_sha256",
        name="uq_eis_223_notice_xml",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256", "archive_sha256"],
        [
            "eis_223_archive_sources.company_id",
            "eis_223_archive_sources.window_key",
            "eis_223_archive_sources.response_sha256",
            "eis_223_archive_sources.archive_sha256",
        ],
        name="fk_eis_223_notice_source",
    ),
    CheckConstraint(
        "purchase_number ~ '^[0-9]{11}$' AND version_number >= 1", name="ck_eis_223_identity"
    ),
    CheckConstraint("xml_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_223_xml_sha"),
    CheckConstraint(
        "COALESCE((jsonb_typeof(snapshot) = 'object' AND snapshot->>'law' = '223' "
        "AND snapshot->>'document_type' IN "
        "('purchaseNoticeAESMBO','purchaseNoticeZKESMBO','purchaseNotice','purchaseNoticeKESMBO') "
        "AND snapshot->>'document_type' = split_part(window_key, '/', 5) "
        "AND snapshot->>'purchase_number' = purchase_number "
        "AND (split_part(window_key, '/', 3) <> 'by-number' "
        "OR purchase_number = split_part(window_key, '/', 4)) "
        "AND (snapshot->>'version_number')::integer = version_number "
        "AND snapshot->>'xml_sha256' = xml_sha256), false)",
        name="ck_eis_223_snapshot_identity",
    ),
)
Index("ix_eis_223_search_keys", eis_223_notice_versions.c.search_keys, postgresql_using="gin")

eis_223_schema_checks = Table(
    "eis_223_schema_checks",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("schema_release", Text, nullable=False),
    Column("tree_sha256", String(64), nullable=False),
    Column("validator_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "version_number",
        "xml_sha256",
        "schema_release",
        "tree_sha256",
        "validator_version",
        name="pk_eis_223_schema_checks",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number", "xml_sha256"],
        [
            "eis_223_notice_versions.company_id",
            "eis_223_notice_versions.purchase_number",
            "eis_223_notice_versions.version_number",
            "eis_223_notice_versions.xml_sha256",
        ],
        name="fk_eis_223_schema_xml",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND status IN ('PASS','FAIL') "
        "AND schema_release IN ('16.2','16.3')",
        name="ck_eis_223_schema_scope",
    ),
    CheckConstraint(
        "tree_sha256 ~ '^[0-9a-f]{64}$' AND validator_version ~ '^[A-Za-z0-9_.-]{1,80}$'",
        name="ck_eis_223_schema_digest",
    ),
    CheckConstraint(
        (
            "COALESCE(((schema_release = '16.2' AND tree_sha256 = "
            "'44cb86105da216b5f53071d5a1f652d09d83f877d611379d693c99a669a32520' AND "
            "report->>'root_sha256' = "
            "'712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b' AND "
            "report->>'package_sha256' = "
            "'b7fc0e8ab81fde9e05e43fc8a83d675f7c49514c4548294cafc7d50cc0b74ae0') OR "
            "(schema_release = '16.3' AND tree_sha256 = "
            "'2aa76beed7df0f8ea004bf67609da629c9f91ad9b887d50f04f1369af96baff0' AND "
            "report->>'root_sha256' = "
            "'c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411' AND "
            "report->>'package_sha256' = "
            "'664facfa081008adb11a6df4373d1abe488927492ab8d618b9bc0b48cd1249ef')) AND "
            "(report->>'checked_at')::timestamptz = checked_at,false)"
        ),
        name="ck_eis_223_schema_policy",
    ),
    CheckConstraint(
        (
            "COALESCE((jsonb_typeof(report) = 'object' AND report->>'purchase_number' = "
            "purchase_number AND (report->>'version_number')::integer = version_number "
            "AND report->>'xml_sha256' = xml_sha256 AND report->>'schema_release' = "
            "schema_release AND report->>'tree_sha256' = tree_sha256 AND "
            "report->>'validator_version' = validator_version AND report->>'status' = "
            "status AND jsonb_typeof(report->'diagnostics') = 'array' AND "
            "jsonb_array_length(report->'diagnostics') BETWEEN 0 AND 4 AND ((status = "
            "'PASS' AND jsonb_array_length(report->'diagnostics') = 0) OR (status = "
            "'FAIL' AND jsonb_array_length(report->'diagnostics') > 0))), false)"
        ),
        name="ck_eis_223_schema_report",
    ),
)

# Immutable official region evidence and bounded operator-approved refresh plans.
eis_223_region_catalogs = Table(
    "eis_223_region_catalogs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("catalog_sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("regions", JSONB, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "catalog_sha256", name="pk_eis_223_region_catalogs"),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_region_catalog_company"),
    CheckConstraint(
        "catalog_sha256 ~ '^[0-9a-f]{64}$' AND "
        "catalog_sha256 = encode(sha256(content), 'hex') AND "
        "response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_region_catalog_hashes",
    ),
    CheckConstraint(
        "octet_length(content) BETWEEN 1 AND 67108864",
        name="ck_eis_223_region_catalog_size",
    ),
    CheckConstraint(
        "source_url ~ '^https://(int[.])?zakupki[.]gov[.]ru/'",
        name="ck_eis_223_region_catalog_source",
    ),
    CheckConstraint(
        "jsonb_typeof(regions) = 'object' AND "
        "jsonb_array_length(jsonb_path_query_array(regions, '$.keyvalue()')) BETWEEN 1 AND 99 "
        "AND NOT jsonb_path_exists(regions, "
        "'$.* ? (@.type() != \"string\")') "
        "AND NOT jsonb_path_exists(regions, "
        "'$.keyvalue() ? (!(@.key like_regex \"^(0[1-9]|[1-9][0-9])$\"))')",
        name="ck_eis_223_region_catalog_regions",
    ),
)

eis_223_region_catalog_checks = Table(
    "eis_223_region_catalog_checks",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("catalog_sha256", String(64)),
    Column("response_sha256", String(64)),
    Column("http_status", Integer),
    Column("rejected_content", LargeBinary),
    Column("reason", Text),
    PrimaryKeyConstraint("company_id", "attempt_id", name="pk_eis_223_region_catalog_checks"),
    ForeignKeyConstraint(
        ["company_id", "catalog_sha256"],
        ["eis_223_region_catalogs.company_id", "eis_223_region_catalogs.catalog_sha256"],
        name="fk_eis_223_region_check_catalog",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(attempt_id) <> '' AND length(attempt_id) <= 100",
        name="ck_eis_223_region_check_identity",
    ),
    CheckConstraint(
        "(status = 'ACCEPTED' AND catalog_sha256 IS NOT NULL AND "
        "response_sha256 IS NOT NULL AND response_sha256 = catalog_sha256 AND "
        "http_status IS NOT NULL AND http_status = 200 AND reason IS NULL "
        "AND rejected_content IS NULL) OR "
        "(status IN ('FAILED','REVIEW_REQUIRED') AND catalog_sha256 IS NULL AND "
        "reason IS NOT NULL AND btrim(reason) <> '')",
        name="ck_eis_223_region_check_outcome",
    ),
    CheckConstraint(
        "response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_region_check_hash",
    ),
    CheckConstraint(
        "http_status IS NULL OR http_status BETWEEN 100 AND 599",
        name="ck_eis_223_region_check_http",
    ),
    CheckConstraint(
        "rejected_content IS NULL OR (octet_length(rejected_content) BETWEEN 1 AND 524288 "
        "AND response_sha256 IS NOT NULL AND response_sha256 = "
        "encode(sha256(rejected_content), 'hex'))",
        name="ck_eis_223_region_check_body",
    ),
)
Index(
    "ix_eis_223_region_check_latest",
    eis_223_region_catalog_checks.c.company_id,
    eis_223_region_catalog_checks.c.checked_at.desc(),
    eis_223_region_catalog_checks.c.attempt_id.desc(),
)

eis_223_region_waves = Table(
    "eis_223_region_waves",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("wave_id", Text, nullable=False),
    Column("catalog_sha256", String(64), nullable=False),
    Column("start_day", Date, nullable=False),
    Column("end_day", Date, nullable=False),
    Column("target_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "wave_id", name="pk_eis_223_region_waves"),
    ForeignKeyConstraint(
        ["company_id", "catalog_sha256"],
        ["eis_223_region_catalogs.company_id", "eis_223_region_catalogs.catalog_sha256"],
        name="fk_eis_223_region_wave_catalog",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(wave_id) <> '' AND length(wave_id) <= 100",
        name="ck_eis_223_region_wave_identity",
    ),
    CheckConstraint(
        "start_day <= end_day AND target_count BETWEEN 1 AND 990",
        name="ck_eis_223_region_wave_bounds",
    ),
)

eis_223_region_targets = Table(
    "eis_223_region_targets",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("wave_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    PrimaryKeyConstraint("company_id", "wave_id", "window_key", name="pk_eis_223_region_targets"),
    ForeignKeyConstraint(
        ["company_id", "wave_id"],
        ["eis_223_region_waves.company_id", "eis_223_region_waves.wave_id"],
        name="fk_eis_223_region_target_wave",
    ),
    UniqueConstraint("company_id", "wave_id", "ordinal", name="uq_eis_223_region_target_ordinal"),
    CheckConstraint("ordinal >= 0", name="ck_eis_223_region_target_ordinal"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
        "[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/"
        "(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|"
        "purchaseRejection|purchaseLotCancellation)$'",
        name="ck_eis_223_region_target_scope",
    ),
)

# Official 44-FZ archive intake is deliberately separate from the HTML pilot.
eis_223_sync_attempts = Table(
    "eis_223_sync_attempts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("response_sha256", String(64), nullable=True),
    Column("checkpoint_response_sha256", String(64), nullable=True),
    Column("reason", Text, nullable=True),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "attempt_id", name="pk_eis_223_sync_attempts"),
    ForeignKeyConstraint(
        ["company_id", "window_key", "checkpoint_response_sha256"],
        [
            "eis_223_windows.company_id",
            "eis_223_windows.window_key",
            "eis_223_windows.response_sha256",
        ],
        name="fk_eis_223_attempt_checkpoint",
    ),
    CheckConstraint(
        "(status = 'SYNCED' AND checkpoint_response_sha256 IS NOT NULL "
        "AND checkpoint_response_sha256 IS NOT DISTINCT FROM response_sha256) "
        "OR (status <> 'SYNCED' AND checkpoint_response_sha256 IS NULL)",
        name="ck_eis_223_attempt_checkpoint",
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_attempt_company"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
        "[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$'",
        name="ck_eis_223_attempt_scope",
    ),
    CheckConstraint(
        "status IN ('SYNCED','NO_DATA','PREPARING','SERVICE_ERROR','FAILED')",
        name="ck_eis_223_attempt_status",
    ),
    CheckConstraint(
        "response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_attempt_sha",
    ),
    CheckConstraint(
        "status = 'FAILED' OR response_sha256 IS NOT NULL",
        name="ck_eis_223_attempt_evidence",
    ),
    CheckConstraint(
        "reason IS NULL OR reason ~ '^[A-Z0-9_]{1,80}$'", name="ck_eis_223_attempt_reason"
    ),
)
Index(
    "ix_eis_223_attempt_recent",
    eis_223_sync_attempts.c.company_id,
    eis_223_sync_attempts.c.window_key,
    eis_223_sync_attempts.c.checked_at,
)

# Whole-purchase cancellation evidence has GUID identity, never notice versions.
eis_223_event_windows = Table(
    "eis_223_event_windows",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("prepared_sha256", String(64), nullable=False),
    Column("manifest_sha256", String(64), nullable=False),
    Column("archive_count", Integer, nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "window_key", "response_sha256", name="pk_eis_223_event_event_windows"
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_event_company"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseRejection$'",
        name="ck_eis_223_event_window",
    ),
    CheckConstraint(
        "response_sha256 ~ '^[0-9a-f]{64}$' AND prepared_sha256 ~ '^[0-9a-f]{64}$' "
        "AND manifest_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_event_window_hashes",
    ),
    CheckConstraint(
        "archive_count BETWEEN 1 AND 2 AND record_count >= 1", name="ck_eis_223_event_counts"
    ),
)
eis_223_event_archive_sources = Table(
    "eis_223_event_archive_sources",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("source_url", Text, nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "window_key",
        "response_sha256",
        "archive_sha256",
        name="pk_eis_223_event_event_archive_sources",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256"],
        [
            "eis_223_event_windows.company_id",
            "eis_223_event_windows.window_key",
            "eis_223_event_windows.response_sha256",
        ],
        name="fk_eis_223_event_archive_window",
    ),
    ForeignKeyConstraint(
        ["company_id", "archive_sha256"],
        ["eis_223_blobs.company_id", "eis_223_blobs.archive_sha256"],
        name="fk_eis_223_event_archive_blob",
    ),
)
eis_223_events = Table(
    "eis_223_events",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("event_guid", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("snapshot", JSONB, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "event_guid", "xml_sha256", name="pk_eis_223_events"),
    UniqueConstraint(
        "company_id", "purchase_number", "event_guid", "xml_sha256", name="uq_eis_223_event_target"
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256", "archive_sha256"],
        [
            "eis_223_event_archive_sources.company_id",
            "eis_223_event_archive_sources.window_key",
            "eis_223_event_archive_sources.response_sha256",
            "eis_223_event_archive_sources.archive_sha256",
        ],
        name="fk_eis_223_event_source",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND purchase_number ~ '^[0-9]{11}$' "
        "AND event_guid ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' "
        "AND xml_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_event_identity",
    ),
    CheckConstraint(
        "COALESCE((jsonb_typeof(snapshot) = 'object' "
        "AND snapshot->>'event_type' = 'purchaseRejection' "
        "AND snapshot->>'purchase_number' = purchase_number "
        "AND snapshot->>'xml_sha256' = xml_sha256 "
        "AND snapshot->'event_guid'->>'value' = event_guid), false)",
        name="ck_eis_223_event_snapshot",
    ),
)
Index(
    "ix_eis_223_event_target",
    eis_223_events.c.company_id,
    eis_223_events.c.purchase_number,
    eis_223_events.c.event_guid,
)

eis_223_event_schema_checks = Table(
    "eis_223_event_schema_checks",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("event_guid", Text, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("schema_release", Text, nullable=False),
    Column("tree_sha256", String(64), nullable=False),
    Column("validator_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "event_guid",
        "xml_sha256",
        "schema_release",
        "tree_sha256",
        "validator_version",
        name="pk_eis_223_event_event_schema_checks",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "event_guid", "xml_sha256"],
        [
            "eis_223_events.company_id",
            "eis_223_events.purchase_number",
            "eis_223_events.event_guid",
            "eis_223_events.xml_sha256",
        ],
        name="fk_eis_223_event_schema_xml",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND status IN ('PASS','FAIL') "
        "AND schema_release IN ('16.2','16.3')",
        name="ck_eis_223_event_schema_scope",
    ),
    CheckConstraint(
        "tree_sha256 ~ '^[0-9a-f]{64}$' AND validator_version ~ '^[A-Za-z0-9_.-]{1,80}$'",
        name="ck_eis_223_event_schema_digest",
    ),
    CheckConstraint(
        (
            "COALESCE(((schema_release = '16.2' AND tree_sha256 = "
            "'44cb86105da216b5f53071d5a1f652d09d83f877d611379d693c99a669a32520' AND "
            "report->>'root_sha256' = "
            "'712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b' AND "
            "report->>'package_sha256' = "
            "'b7fc0e8ab81fde9e05e43fc8a83d675f7c49514c4548294cafc7d50cc0b74ae0') OR "
            "(schema_release = '16.3' AND tree_sha256 = "
            "'2aa76beed7df0f8ea004bf67609da629c9f91ad9b887d50f04f1369af96baff0' AND "
            "report->>'root_sha256' = "
            "'c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411' AND "
            "report->>'package_sha256' = "
            "'664facfa081008adb11a6df4373d1abe488927492ab8d618b9bc0b48cd1249ef')) AND "
            "(report->>'checked_at')::timestamptz = checked_at,false)"
        ),
        name="ck_eis_223_event_schema_policy",
    ),
    CheckConstraint(
        (
            "COALESCE((jsonb_typeof(report) = 'object' AND report->>'purchase_number' = "
            "purchase_number AND report->>'event_guid' = event_guid "
            "AND report->>'xml_sha256' = xml_sha256 AND report->>'schema_release' = "
            "schema_release AND report->>'tree_sha256' = tree_sha256 AND "
            "report->>'validator_version' = validator_version AND report->>'status' = "
            "status AND jsonb_typeof(report->'diagnostics') = 'array' AND "
            "jsonb_array_length(report->'diagnostics') BETWEEN 0 AND 4 AND ((status = "
            "'PASS' AND jsonb_array_length(report->'diagnostics') = 0) OR (status = "
            "'FAIL' AND jsonb_array_length(report->'diagnostics') > 0))), false)"
        ),
        name="ck_eis_223_event_schema_report",
    ),
)

eis_223_event_sync_attempts = Table(
    "eis_223_event_sync_attempts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("response_sha256", String(64), nullable=True),
    Column("checkpoint_response_sha256", String(64), nullable=True),
    Column("reason", Text, nullable=True),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "attempt_id", name="pk_eis_223_event_event_sync_attempts"),
    ForeignKeyConstraint(
        ["company_id", "window_key", "checkpoint_response_sha256"],
        [
            "eis_223_event_windows.company_id",
            "eis_223_event_windows.window_key",
            "eis_223_event_windows.response_sha256",
        ],
        name="fk_eis_223_event_attempt_checkpoint",
    ),
    CheckConstraint(
        "(status = 'SYNCED' AND checkpoint_response_sha256 IS NOT NULL "
        "AND checkpoint_response_sha256 IS NOT DISTINCT FROM response_sha256) "
        "OR (status <> 'SYNCED' AND checkpoint_response_sha256 IS NULL)",
        name="ck_eis_223_event_attempt_checkpoint",
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_event_attempt_company"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
        "[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/purchaseRejection$'",
        name="ck_eis_223_event_attempt_scope",
    ),
    CheckConstraint(
        "status IN ('SYNCED','NO_DATA','PREPARING','SERVICE_ERROR','FAILED')",
        name="ck_eis_223_event_attempt_status",
    ),
    CheckConstraint(
        "response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_event_attempt_sha",
    ),
    CheckConstraint(
        "status = 'FAILED' OR response_sha256 IS NOT NULL",
        name="ck_eis_223_event_attempt_evidence",
    ),
    CheckConstraint(
        "reason IS NULL OR reason ~ '^[A-Z0-9_]{1,80}$'", name="ck_eis_223_event_attempt_reason"
    ),
)
Index(
    "ix_eis_223_event_attempt_recent",
    eis_223_event_sync_attempts.c.company_id,
    eis_223_event_sync_attempts.c.window_key,
    eis_223_event_sync_attempts.c.checked_at,
)


eis_223_lot_event_windows = Table(
    "eis_223_lot_event_windows",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("prepared_sha256", String(64), nullable=False),
    Column("manifest_sha256", String(64), nullable=False),
    Column("archive_count", Integer, nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "window_key", "response_sha256", name="pk_eis_223_lot_event_event_windows"
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_lot_event_company"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseLotCancellation$'",
        name="ck_eis_223_lot_event_window",
    ),
    CheckConstraint(
        "response_sha256 ~ '^[0-9a-f]{64}$' AND prepared_sha256 ~ '^[0-9a-f]{64}$' "
        "AND manifest_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_lot_event_window_hashes",
    ),
    CheckConstraint(
        "archive_count BETWEEN 1 AND 2 AND record_count >= 1", name="ck_eis_223_lot_event_counts"
    ),
)
eis_223_lot_event_archive_sources = Table(
    "eis_223_lot_event_archive_sources",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("source_url", Text, nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "window_key",
        "response_sha256",
        "archive_sha256",
        name="pk_eis_223_lot_event_event_archive_sources",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256"],
        [
            "eis_223_lot_event_windows.company_id",
            "eis_223_lot_event_windows.window_key",
            "eis_223_lot_event_windows.response_sha256",
        ],
        name="fk_eis_223_lot_event_archive_window",
    ),
    ForeignKeyConstraint(
        ["company_id", "archive_sha256"],
        ["eis_223_blobs.company_id", "eis_223_blobs.archive_sha256"],
        name="fk_eis_223_lot_event_archive_blob",
    ),
)
eis_223_lot_events = Table(
    "eis_223_lot_events",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("event_guid", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("snapshot", JSONB, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "event_guid", "xml_sha256", name="pk_eis_223_lot_events"),
    UniqueConstraint(
        "company_id",
        "purchase_number",
        "event_guid",
        "xml_sha256",
        name="uq_eis_223_lot_event_target",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256", "archive_sha256"],
        [
            "eis_223_lot_event_archive_sources.company_id",
            "eis_223_lot_event_archive_sources.window_key",
            "eis_223_lot_event_archive_sources.response_sha256",
            "eis_223_lot_event_archive_sources.archive_sha256",
        ],
        name="fk_eis_223_lot_event_source",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND purchase_number ~ '^[0-9]{11}$' "
        "AND event_guid ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' "
        "AND xml_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_lot_event_identity",
    ),
    CheckConstraint(
        "COALESCE((jsonb_typeof(snapshot) = 'object' "
        "AND snapshot->>'event_type' = 'purchaseLotCancellation' "
        "AND snapshot->>'purchase_number' = purchase_number "
        "AND snapshot->>'xml_sha256' = xml_sha256 "
        "AND snapshot->'event_guid'->>'value' = event_guid), false)",
        name="ck_eis_223_lot_event_snapshot",
    ),
)
Index(
    "ix_eis_223_lot_event_target",
    eis_223_lot_events.c.company_id,
    eis_223_lot_events.c.purchase_number,
    eis_223_lot_events.c.event_guid,
)

eis_223_lot_event_schema_checks = Table(
    "eis_223_lot_event_schema_checks",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("event_guid", Text, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("schema_release", Text, nullable=False),
    Column("tree_sha256", String(64), nullable=False),
    Column("validator_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "event_guid",
        "xml_sha256",
        "schema_release",
        "tree_sha256",
        "validator_version",
        name="pk_eis_223_lot_event_event_schema_checks",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "event_guid", "xml_sha256"],
        [
            "eis_223_lot_events.company_id",
            "eis_223_lot_events.purchase_number",
            "eis_223_lot_events.event_guid",
            "eis_223_lot_events.xml_sha256",
        ],
        name="fk_eis_223_lot_event_schema_xml",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND status IN ('PASS','FAIL') "
        "AND schema_release IN ('16.2','16.3')",
        name="ck_eis_223_lot_event_schema_scope",
    ),
    CheckConstraint(
        "tree_sha256 ~ '^[0-9a-f]{64}$' AND validator_version ~ '^[A-Za-z0-9_.-]{1,80}$'",
        name="ck_eis_223_lot_event_schema_digest",
    ),
    CheckConstraint(
        (
            "COALESCE(((schema_release = '16.2' AND tree_sha256 = "
            "'44cb86105da216b5f53071d5a1f652d09d83f877d611379d693c99a669a32520' AND "
            "report->>'root_sha256' = "
            "'712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b' AND "
            "report->>'package_sha256' = "
            "'b7fc0e8ab81fde9e05e43fc8a83d675f7c49514c4548294cafc7d50cc0b74ae0') OR "
            "(schema_release = '16.3' AND tree_sha256 = "
            "'2aa76beed7df0f8ea004bf67609da629c9f91ad9b887d50f04f1369af96baff0' AND "
            "report->>'root_sha256' = "
            "'c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411' AND "
            "report->>'package_sha256' = "
            "'664facfa081008adb11a6df4373d1abe488927492ab8d618b9bc0b48cd1249ef')) AND "
            "(report->>'checked_at')::timestamptz = checked_at,false)"
        ),
        name="ck_eis_223_lot_event_schema_policy",
    ),
    CheckConstraint(
        (
            "COALESCE((jsonb_typeof(report) = 'object' AND report->>'purchase_number' = "
            "purchase_number AND report->>'event_guid' = event_guid "
            "AND report->>'xml_sha256' = xml_sha256 AND report->>'schema_release' = "
            "schema_release AND report->>'tree_sha256' = tree_sha256 AND "
            "report->>'validator_version' = validator_version AND report->>'status' = "
            "status AND jsonb_typeof(report->'diagnostics') = 'array' AND "
            "jsonb_array_length(report->'diagnostics') BETWEEN 0 AND 4 AND ((status = "
            "'PASS' AND jsonb_array_length(report->'diagnostics') = 0) OR (status = "
            "'FAIL' AND jsonb_array_length(report->'diagnostics') > 0))), false)"
        ),
        name="ck_eis_223_lot_event_schema_report",
    ),
)

eis_223_lot_event_sync_attempts = Table(
    "eis_223_lot_event_sync_attempts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("response_sha256", String(64), nullable=True),
    Column("checkpoint_response_sha256", String(64), nullable=True),
    Column("reason", Text, nullable=True),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "attempt_id", name="pk_eis_223_lot_event_event_sync_attempts"
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "checkpoint_response_sha256"],
        [
            "eis_223_lot_event_windows.company_id",
            "eis_223_lot_event_windows.window_key",
            "eis_223_lot_event_windows.response_sha256",
        ],
        name="fk_eis_223_lot_event_attempt_checkpoint",
    ),
    CheckConstraint(
        "(status = 'SYNCED' AND checkpoint_response_sha256 IS NOT NULL "
        "AND checkpoint_response_sha256 IS NOT DISTINCT FROM response_sha256) "
        "OR (status <> 'SYNCED' AND checkpoint_response_sha256 IS NULL)",
        name="ck_eis_223_lot_event_attempt_checkpoint",
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_223_lot_event_attempt_company"),
    CheckConstraint(
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
        "[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseLotCancellation$'",
        name="ck_eis_223_lot_event_attempt_scope",
    ),
    CheckConstraint(
        "status IN ('SYNCED','NO_DATA','PREPARING','SERVICE_ERROR','FAILED')",
        name="ck_eis_223_lot_event_attempt_status",
    ),
    CheckConstraint(
        "response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_223_lot_event_attempt_sha",
    ),
    CheckConstraint(
        "status = 'FAILED' OR response_sha256 IS NOT NULL",
        name="ck_eis_223_lot_event_attempt_evidence",
    ),
    CheckConstraint(
        "reason IS NULL OR reason ~ '^[A-Z0-9_]{1,80}$'", name="ck_eis_223_lot_event_attempt_reason"
    ),
)
Index(
    "ix_eis_223_lot_event_attempt_recent",
    eis_223_lot_event_sync_attempts.c.company_id,
    eis_223_lot_event_sync_attempts.c.window_key,
    eis_223_lot_event_sync_attempts.c.checked_at,
)


# Official 44-FZ archive intake is deliberately separate from the HTML pilot.
# Every row is tenant-scoped and immutable; one notice version has one XML digest.
eis_feed_windows = Table(
    "eis_feed_windows",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("manifest_sha256", String(64), nullable=False),
    Column("archive_count", Integer, nullable=False),
    Column("notice_count", Integer, nullable=False),
    Column("intake_kind", Text, nullable=False, server_default="LEGACY_CANONICAL"),
    Column("coverage", Text, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "window_key", "response_sha256", name="pk_eis_feed_windows"),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_feed_windows_company"),
    CheckConstraint("btrim(window_key) <> ''", name="ck_eis_feed_windows_key"),
    CheckConstraint("response_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_feed_windows_response_sha"),
    CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_feed_windows_manifest_sha"),
    CheckConstraint("archive_count BETWEEN 1 AND 1000", name="ck_eis_feed_windows_archive_count"),
    CheckConstraint("notice_count >= 0", name="ck_eis_feed_windows_notice_count"),
    CheckConstraint(
        "intake_kind IN ('LEGACY_CANONICAL', 'VARIANT_TRANSPORT')",
        name="ck_eis_feed_windows_intake_kind",
    ),
    CheckConstraint("coverage = 'UNKNOWN'", name="ck_eis_feed_windows_coverage"),
)

eis_feed_archives = Table(
    "eis_feed_archives",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("record_count", Integer, nullable=False),
    PrimaryKeyConstraint(
        "company_id", "window_key", "response_sha256", "archive_sha256", name="pk_eis_feed_archives"
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256"],
        [
            "eis_feed_windows.company_id",
            "eis_feed_windows.window_key",
            "eis_feed_windows.response_sha256",
        ],
        name="fk_eis_feed_archive_window",
    ),
    CheckConstraint("archive_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_feed_archives_sha"),
    CheckConstraint(
        "archive_sha256 = encode(sha256(content), 'hex')", name="ck_eis_feed_archives_content_sha"
    ),
    CheckConstraint(
        "octet_length(content) BETWEEN 1 AND 52428800", name="ck_eis_feed_archives_size"
    ),
    CheckConstraint("record_count >= 0", name="ck_eis_feed_archives_record_count"),
)

eis_feed_archive_sources = Table(
    "eis_feed_archive_sources",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("prepared_response_sha256", String(64), nullable=False),
    Column("source_url", Text, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "window_key",
        "response_sha256",
        "archive_sha256",
        name="pk_eis_feed_archive_sources",
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256", "archive_sha256"],
        [
            "eis_feed_archives.company_id",
            "eis_feed_archives.window_key",
            "eis_feed_archives.response_sha256",
            "eis_feed_archives.archive_sha256",
        ],
        name="fk_eis_feed_archive_source_archive",
    ),
    CheckConstraint(
        "prepared_response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_feed_archive_sources_prepared_sha",
    ),
    CheckConstraint("btrim(source_url) <> ''", name="ck_eis_feed_archive_sources_url"),
)

eis_sync_targets = Table(
    "eis_sync_targets",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("planned_by", Text, nullable=False),
    Column("planned_at", DateTime(timezone=True), nullable=False),
    Column("coverage", Text, nullable=False),
    PrimaryKeyConstraint("company_id", "window_key", name="pk_eis_sync_targets"),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_sync_targets_company"),
    CheckConstraint("btrim(window_key) <> ''", name="ck_eis_sync_targets_window"),
    CheckConstraint("btrim(planned_by) <> ''", name="ck_eis_sync_targets_actor"),
    CheckConstraint("coverage = 'UNKNOWN'", name="ck_eis_sync_targets_coverage"),
)

eis_sync_attempts = Table(
    "eis_sync_attempts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("reason_code", Text, nullable=True),
    Column("source_response_sha256", String(64), nullable=True),
    Column("attempted_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "attempt_id", name="pk_eis_sync_attempts"),
    ForeignKeyConstraint(
        ["company_id", "window_key"],
        ["eis_sync_targets.company_id", "eis_sync_targets.window_key"],
        name="fk_eis_sync_attempt_target",
    ),
    CheckConstraint("btrim(actor_id) <> ''", name="ck_eis_sync_attempts_actor"),
    CheckConstraint(
        "outcome IN ('SYNCED', 'SKIPPED', 'NO_DATA', 'PREPARING', 'SERVICE_ERROR', 'FAILED')",
        name="ck_eis_sync_attempts_outcome",
    ),
    CheckConstraint(
        "reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
        name="ck_eis_sync_attempts_reason",
    ),
    CheckConstraint(
        "source_response_sha256 IS NULL OR source_response_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_sync_attempts_response_sha",
    ),
    CheckConstraint(
        "outcome <> 'NO_DATA' OR source_response_sha256 IS NOT NULL",
        name="ck_eis_sync_attempts_no_data_evidence",
    ),
    CheckConstraint(
        "outcome <> 'FAILED' OR reason_code IS NOT NULL",
        name="ck_eis_sync_attempts_failure_reason",
    ),
)
Index(
    "ix_eis_sync_attempts_window_time",
    eis_sync_attempts.c.company_id,
    eis_sync_attempts.c.window_key,
    eis_sync_attempts.c.attempted_at.desc(),
)

eis_notice_versions = Table(
    "eis_notice_versions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("source_member", Text, nullable=False),
    Column("document_type", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("deadline", DateTime(timezone=True), nullable=True),
    Column("nmck_rub", Numeric, nullable=True),
    Column("lot_parse_status", Text, nullable=False),
    Column("lot_items", JSONB, nullable=False),
    Column("attachments", JSONB, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "purchase_number", "version_number", name="pk_eis_notice_versions"
    ),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256", "archive_sha256"],
        [
            "eis_feed_archives.company_id",
            "eis_feed_archives.window_key",
            "eis_feed_archives.response_sha256",
            "eis_feed_archives.archive_sha256",
        ],
        name="fk_eis_notice_archive",
    ),
    CheckConstraint("purchase_number ~ '^[0-9]{19,23}$'", name="ck_eis_notice_number"),
    CheckConstraint("version_number >= 1", name="ck_eis_notice_version"),
    CheckConstraint("xml_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_notice_xml_sha"),
    CheckConstraint("btrim(title) <> ''", name="ck_eis_notice_title"),
    CheckConstraint(
        "document_type IN ('epNotificationEF2020', 'epNotificationEZK2020', "
        "'epNotificationEOK2020')",
        name="ck_eis_notice_type",
    ),
    CheckConstraint("nmck_rub IS NULL OR nmck_rub >= 0", name="ck_eis_notice_nmck"),
    CheckConstraint("lot_parse_status IN ('PARSED', 'UNKNOWN')", name="ck_eis_notice_lot_status"),
    CheckConstraint("jsonb_typeof(lot_items) = 'array'", name="ck_eis_notice_lot_items"),
    CheckConstraint("jsonb_typeof(attachments) = 'array'", name="ck_eis_notice_attachments"),
)
Index("ix_eis_notice_versions_title", eis_notice_versions.c.company_id, eis_notice_versions.c.title)

# Evidence-only ledger; these receipts never authorize canonical source intake.
eis_notice_variant_receipts = Table(
    "eis_notice_variant_receipts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("manifest_sha256", String(64), nullable=False),
    Column("diagnosis_sha256", String(64), nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("prepared_response_sha256", String(64), nullable=False),
    Column("archive_sha256s", JSONB, nullable=False),
    Column("archive_count", Integer, nullable=False),
    Column("occurrence_count", Integer, nullable=False),
    Column("variant_count", Integer, nullable=False),
    Column("evidence", JSONB, nullable=False),
    Column("retention_audit_event_id", Text, nullable=False),
    Column("diagnosis_audit_event_id", Text, nullable=False),
    Column("ledger_audit_event_id", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("inventory_status", Text, nullable=False),
    Column("canonical_admission", Text, nullable=False),
    Column("coverage", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("receipt_sha256", String(64), nullable=False),
    PrimaryKeyConstraint("company_id", "receipt_id", name="pk_eis_notice_variant_receipts"),
    UniqueConstraint(
        "company_id", "manifest_sha256", "diagnosis_sha256", name="uq_eis_variant_receipt_basis"
    ),
    ForeignKeyConstraint(
        ["company_id", "retention_audit_event_id"],
        ["audit_events.company_id", "audit_events.event_id"],
        name="fk_eis_variant_receipt_retention_audit",
    ),
    ForeignKeyConstraint(
        ["company_id", "diagnosis_audit_event_id"],
        ["audit_events.company_id", "audit_events.event_id"],
        name="fk_eis_variant_receipt_diagnosis_audit",
    ),
    ForeignKeyConstraint(
        ["company_id", "ledger_audit_event_id"],
        ["audit_events.company_id", "audit_events.event_id"],
        name="fk_eis_variant_receipt_ledger_audit",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(window_key) <> ''", name="ck_eis_variant_receipt_text"
    ),
    CheckConstraint(
        "receipt_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        name="ck_eis_variant_receipt_id",
    ),
    CheckConstraint(
        "manifest_sha256 ~ '^[0-9a-f]{64}$' AND diagnosis_sha256 ~ '^[0-9a-f]{64}$' AND "
        "response_sha256 ~ '^[0-9a-f]{64}$' AND prepared_response_sha256 ~ '^[0-9a-f]{64}$' AND "
        "receipt_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_variant_receipt_sha",
    ),
    CheckConstraint(
        "archive_count BETWEEN 1 AND 20 AND occurrence_count BETWEEN 1 AND 2000 AND "
        "variant_count BETWEEN 1 AND occurrence_count AND "
        "jsonb_typeof(archive_sha256s) = 'array' AND "
        "jsonb_array_length(archive_sha256s) = archive_count",
        name="ck_eis_variant_receipt_counts",
    ),
    CheckConstraint(
        "schema_version = 'eis-notice-variant-ledger-v1' AND inventory_status = 'COMPLETE' AND "
        "canonical_admission = 'NOT_ENABLED' AND coverage = 'UNKNOWN'",
        name="ck_eis_variant_receipt_policy",
    ),
    CheckConstraint(
        "jsonb_typeof(evidence) = 'object' AND "
        "evidence->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "evidence->>'window_key' IS NOT DISTINCT FROM window_key AND "
        "evidence->>'manifest_sha256' IS NOT DISTINCT FROM manifest_sha256 AND "
        "evidence->>'response_sha256' IS NOT DISTINCT FROM response_sha256 AND "
        "evidence->>'prepared_response_sha256' IS NOT DISTINCT FROM prepared_response_sha256 AND "
        "evidence->'archive_sha256s' IS NOT DISTINCT FROM archive_sha256s AND "
        "evidence->>'status' IS NOT DISTINCT FROM 'RETAINED' AND "
        "evidence->'complete_set' IS NOT DISTINCT FROM 'true'::jsonb AND "
        "octet_length(evidence::text) <= 131072",
        name="ck_eis_variant_receipt_evidence",
    ),
)
Index(
    "ix_eis_variant_receipts_window",
    eis_notice_variant_receipts.c.company_id,
    eis_notice_variant_receipts.c.window_key,
)

eis_notice_variants = Table(
    "eis_notice_variants",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("document_type", Text, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("facts", JSONB, nullable=False),
    Column("facts_sha256", String(64), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "version_number",
        "document_type",
        "xml_sha256",
        name="pk_eis_notice_variants",
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_variants_company"),
    CheckConstraint(
        "purchase_number ~ '^[0-9]{19,23}$' AND version_number >= 1",
        name="ck_eis_variants_number_version",
    ),
    CheckConstraint(
        "document_type IN ('epNotificationEF2020', 'epNotificationEZK2020', "
        "'epNotificationEOK2020')",
        name="ck_eis_variants_type",
    ),
    CheckConstraint(
        "xml_sha256 ~ '^[0-9a-f]{64}$' AND facts_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_variants_sha",
    ),
    CheckConstraint(
        "jsonb_typeof(facts) = 'object' AND "
        "facts->>'purchase_number' IS NOT DISTINCT FROM purchase_number AND "
        "(facts->>'version_number')::integer IS NOT DISTINCT FROM version_number AND "
        "facts->>'document_type' IS NOT DISTINCT FROM document_type AND "
        "facts->>'xml_sha256' IS NOT DISTINCT FROM xml_sha256 AND "
        "octet_length(facts::text) <= 4096",
        name="ck_eis_variants_facts",
    ),
)

eis_notice_variant_origins = Table(
    "eis_notice_variant_origins",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("archive_ordinal", Integer, nullable=False),
    Column("member_filename", Text, nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("document_type", Text, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "receipt_id",
        "archive_ordinal",
        "member_filename",
        name="pk_eis_notice_variant_origins",
    ),
    ForeignKeyConstraint(
        ["company_id", "receipt_id"],
        ["eis_notice_variant_receipts.company_id", "eis_notice_variant_receipts.receipt_id"],
        name="fk_eis_variant_origin_receipt",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number", "document_type", "xml_sha256"],
        [
            "eis_notice_variants.company_id",
            "eis_notice_variants.purchase_number",
            "eis_notice_variants.version_number",
            "eis_notice_variants.document_type",
            "eis_notice_variants.xml_sha256",
        ],
        name="fk_eis_variant_origin_variant",
    ),
    CheckConstraint(
        "archive_ordinal BETWEEN 0 AND 19 AND archive_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_variant_origin_archive",
    ),
    CheckConstraint(
        "char_length(member_filename) BETWEEN 4 AND 255 AND strpos(member_filename, '/') = 0 AND "
        "strpos(member_filename, chr(92)) = 0 AND right(lower(member_filename), 4) = '.xml'",
        name="ck_eis_variant_origin_member",
    ),
)
Index(
    "ix_eis_variant_origins_notice",
    eis_notice_variant_origins.c.company_id,
    eis_notice_variant_origins.c.purchase_number,
    eis_notice_variant_origins.c.version_number,
)

# Corrected, bounded derivations never overwrite the admitted source snapshot.
eis_notice_position_projections = Table(
    "eis_notice_position_projections",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("position_set", JSONB, nullable=False),
    Column("projection_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "version_number",
        "parser_version",
        name="pk_eis_position_projection",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_position_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(parser_version) <> ''", name="ck_eis_position_text"
    ),
    CheckConstraint(
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$' AND projection_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_eis_position_sha",
    ),
    CheckConstraint(
        "jsonb_typeof(position_set) = 'object' AND position_set->>'law' = '44' AND "
        "position_set->>'purchase_number' IS NOT DISTINCT FROM purchase_number AND "
        "(position_set->>'version_number')::integer IS NOT DISTINCT FROM version_number AND "
        "position_set->>'notice_xml_sha256' IS NOT DISTINCT FROM notice_xml_sha256 AND "
        "position_set->'native_tables' = '[]'::jsonb AND "
        "position_set->>'review_status' = 'UNKNOWN' AND "
        "position_set->>'specification_completeness' = 'UNKNOWN'",
        name="ck_eis_position_identity",
    ),
)

# Rebuildable lexical evidence; original notice versions remain immutable.
eis_notice_search_keys = Table(
    "eis_notice_search_keys",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("keys", ARRAY(Text), nullable=False),
    Column("key_version", Text, nullable=False),
    PrimaryKeyConstraint(
        "company_id", "purchase_number", "version_number", name="pk_eis_search_keys"
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_search_keys_notice",
    ),
    CheckConstraint("key_version = 'eis-lexical-v1'", name="ck_eis_search_key_version"),
)
Index("ix_eis_search_keys_gin", eis_notice_search_keys.c["keys"], postgresql_using="gin")

eis_document_jobs = Table(
    "eis_document_jobs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "purchase_number", "version_number", name="pk_eis_document_jobs"
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_notice_versions.company_id",
            "eis_notice_versions.purchase_number",
            "eis_notice_versions.version_number",
        ],
        name="fk_eis_document_job_notice",
    ),
    CheckConstraint("notice_xml_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_document_job_sha"),
    CheckConstraint("btrim(created_by) <> ''", name="ck_eis_document_job_actor"),
)

eis_document_blobs = Table(
    "eis_document_blobs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("byte_count", Integer, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "sha256", name="pk_eis_document_blobs"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_document_blob_sha"),
    CheckConstraint(
        "byte_count BETWEEN 1 AND 20971520 AND byte_count = octet_length(content)",
        name="ck_eis_document_blob_size",
    ),
)

eis_document_analyses = Table(
    "eis_document_analyses",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("filename", Text, nullable=False),
    Column("analyzer_version", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("analyzed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "sha256", "filename", "analyzer_version", name="pk_eis_document_analyses"
    ),
    ForeignKeyConstraint(
        ["company_id", "sha256"],
        ["eis_document_blobs.company_id", "eis_document_blobs.sha256"],
        name="fk_eis_document_analysis_blob",
    ),
    CheckConstraint(
        "analyzer_version IN ('eis-native-v1', 'eis-native-v2-xls', 'eis-native-v3-doc', "
        "'eis-native-review-v1')",
        name="ck_eis_document_analyzer",
    ),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_eis_document_analysis_payload"),
)

eis_223_document_jobs = Table(
    "eis_223_document_jobs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "version_number",
        "notice_xml_sha256",
        name="pk_eis_223_document_jobs",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number", "notice_xml_sha256"],
        [
            "eis_223_notice_versions.company_id",
            "eis_223_notice_versions.purchase_number",
            "eis_223_notice_versions.version_number",
            "eis_223_notice_versions.xml_sha256",
        ],
        name="fk_eis_223_document_job_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(created_by) <> ''", name="ck_eis_223_document_job_scope"
    ),
)
Index(
    "ix_eis_223_document_jobs_due",
    eis_223_document_jobs.c.company_id,
    eis_223_document_jobs.c.created_at,
    eis_223_document_jobs.c.purchase_number,
)

eis_223_document_attempts = Table(
    "eis_223_document_attempts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("content_uid", String(32), nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text, nullable=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "attempt_id", name="pk_eis_223_document_attempts"),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number", "notice_xml_sha256"],
        [
            "eis_223_document_jobs.company_id",
            "eis_223_document_jobs.purchase_number",
            "eis_223_document_jobs.version_number",
            "eis_223_document_jobs.notice_xml_sha256",
        ],
        name="fk_eis_223_document_attempt_job",
    ),
    CheckConstraint(
        "content_uid ~ '^[0-9A-F]{32}$' AND "
        "((status='RECEIVED' AND reason IS NULL) OR "
        "(status='FAILED' AND reason ~ '^[A-Z][A-Z0-9_]{0,79}$')) IS TRUE",
        name="ck_eis_223_document_attempt_status",
    ),
)
Index(
    "ix_eis_223_document_attempts_uid",
    eis_223_document_attempts.c.company_id,
    eis_223_document_attempts.c.purchase_number,
    eis_223_document_attempts.c.version_number,
    eis_223_document_attempts.c.content_uid,
    eis_223_document_attempts.c.observed_at,
)

eis_223_document_receipts = Table(
    "eis_223_document_receipts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("notice_xml_sha256", String(64), nullable=False),
    Column("content_uid", String(32), nullable=False),
    Column("filename", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("source_locator", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("analysis", JSONB, nullable=False),
    Column("analyzer_version", Text, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "purchase_number",
        "version_number",
        "notice_xml_sha256",
        "content_uid",
        name="pk_eis_223_document_receipts",
    ),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number", "notice_xml_sha256"],
        [
            "eis_223_notice_versions.company_id",
            "eis_223_notice_versions.purchase_number",
            "eis_223_notice_versions.version_number",
            "eis_223_notice_versions.xml_sha256",
        ],
        name="fk_eis_223_receipt_notice",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND content_uid ~ '^[0-9A-F]{32}$'",
        name="ck_eis_223_receipt_scope",
    ),
    CheckConstraint(
        "sha256 = encode(sha256(content), 'hex') AND octet_length(content) BETWEEN 1 AND 20971520",
        name="ck_eis_223_receipt_bytes",
    ),
    CheckConstraint(
        "COALESCE(jsonb_typeof(analysis)='object' AND analysis->>'sha256'=sha256 "
        "AND (analysis->>'byte_count')::integer=octet_length(content) "
        "AND analysis->>'filename'=filename AND analysis->>'url'=source_url "
        "AND analysis->>'status' IN ('PASS','FAIL','UNKNOWN') "
        "AND analysis->>'document_role'='UNKNOWN' "
        "AND analyzer_version='eis-native-v3-doc', false)",
        name="ck_eis_223_receipt_analysis",
    ),
)

eis_document_observations = Table(
    "eis_document_observations",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("observation_id", Text, nullable=False),
    Column("content_uid", String(32), nullable=False),
    Column("sha256", String(64), nullable=True),
    Column("fetch_status", Text, nullable=False),
    Column("reason_code", Text, nullable=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "observation_id", name="pk_eis_document_observations"),
    ForeignKeyConstraint(
        ["company_id", "purchase_number", "version_number"],
        [
            "eis_document_jobs.company_id",
            "eis_document_jobs.purchase_number",
            "eis_document_jobs.version_number",
        ],
        name="fk_eis_document_observation_job",
    ),
    ForeignKeyConstraint(
        ["company_id", "sha256"],
        ["eis_document_blobs.company_id", "eis_document_blobs.sha256"],
        name="fk_eis_document_observation_blob",
    ),
    CheckConstraint("content_uid ~ '^[0-9A-F]{32}$'", name="ck_eis_document_observation_uid"),
    CheckConstraint(
        "((fetch_status IN ('RECEIVED','SIZE_MISMATCH') AND sha256 IS NOT NULL "
        "AND reason_code IS NULL) OR (fetch_status = 'FAILED' AND sha256 IS NULL "
        "AND reason_code ~ '^[A-Z][A-Z0-9_]{0,79}$')) IS TRUE",
        name="ck_eis_document_observation_status",
    ),
)
Index(
    "ix_eis_document_observations_notice",
    eis_document_observations.c.company_id,
    eis_document_observations.c.purchase_number,
    eis_document_observations.c.version_number,
    eis_document_observations.c.observed_at,
)

eis_procedure_events = Table(
    "eis_procedure_events",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("document_type", Text, nullable=False),
    Column("document_id", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("recovery_stage", Text, nullable=True),
    Column("xml_sha256", String(64), nullable=False),
    Column("source_member", Text, nullable=False),
    Column("locator", Text, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("window_key", Text, nullable=False),
    Column("response_sha256", String(64), nullable=False),
    Column("archive_sha256", String(64), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "document_type", "document_id", name="pk_eis_events"),
    ForeignKeyConstraint(
        ["company_id", "window_key", "response_sha256", "archive_sha256"],
        [
            "eis_feed_archives.company_id",
            "eis_feed_archives.window_key",
            "eis_feed_archives.response_sha256",
            "eis_feed_archives.archive_sha256",
        ],
        name="fk_eis_event_archive",
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_eis_event_company"),
    CheckConstraint("length(document_id) BETWEEN 1 AND 200", name="ck_eis_event_id"),
    CheckConstraint("purchase_number ~ '^[0-9]{19,23}$'", name="ck_eis_event_number"),
    CheckConstraint("xml_sha256 ~ '^[0-9a-f]{64}$'", name="ck_eis_event_sha"),
    CheckConstraint(
        "parser_version IN ('eis-procedure-event-v1','eis-companion-document-v1')",
        name="ck_eis_event_parser",
    ),
    CheckConstraint(
        "btrim(source_member) <> '' AND btrim(locator) <> ''", name="ck_eis_event_source"
    ),
    CheckConstraint(
        "((document_type = 'epNotificationCancel' AND recovery_stage IS NULL) OR "
        "(document_type = 'epNotificationCancelFailure' AND "
        "recovery_stage IN ('NP','AP','CW','FO','CO')) OR "
        "(document_type IN ('epClarificationDoc','epProtocolEOK2020FirstSections',"
        "'epProtocolEOK2020SecondSections','epProtocolEOK2020Final',"
        "'fcsPlacementResult','fcsProposalsResult') AND recovery_stage IS NULL)) IS TRUE",
        name="ck_eis_event_type_stage",
    ),
    CheckConstraint(
        "((document_type IN ('epNotificationCancel','epNotificationCancelFailure') AND "
        "parser_version = 'eis-procedure-event-v1') OR "
        "(document_type IN ('epClarificationDoc','epProtocolEOK2020FirstSections',"
        "'epProtocolEOK2020SecondSections','epProtocolEOK2020Final',"
        "'fcsPlacementResult','fcsProposalsResult') AND "
        "parser_version = 'eis-companion-document-v1' AND "
        "document_id = 'sha256:' || xml_sha256)) IS TRUE",
        name="ck_eis_event_family",
    ),
)
Index(
    "ix_eis_events_purchase",
    eis_procedure_events.c.company_id,
    eis_procedure_events.c.purchase_number,
    eis_procedure_events.c.published_at,
)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_AI_TRANSFER_RAW_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SOURCING_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_SOURCING_SOURCE_BYTES = 20 * 1024 * 1024

ai_transfer_requests = Table(
    "ai_transfer_requests",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("request", JSONB, nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "transfer_id", name="pk_ai_transfer_requests"),
    UniqueConstraint("company_id", "transfer_id", "payload_sha256", name="uq_ai_transfer_payload"),
    ForeignKeyConstraint(
        ["company_id", "source_document_id", "source_sha256"],
        ["documents.company_id", "documents.document_id", "documents.sha256"],
        name="fk_ai_transfer_source",
    ),
    CheckConstraint("chunk_count BETWEEN 1 AND 9999", name="ck_ai_transfer_chunk_count"),
    CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ai_transfer_payload_sha256"),
    CheckConstraint("btrim(prepared_by) <> ''", name="ck_ai_transfer_preparer"),
    CheckConstraint(
        "(jsonb_typeof(request) = 'object' AND "
        "jsonb_typeof(request->'chunks') = 'array' AND "
        "request->>'schema_version' = 'persisted-ai-transfer-request-v1' AND "
        "request->>'company_id' = company_id AND request->>'transfer_id' = transfer_id AND "
        "request->>'source_document_id' = source_document_id AND "
        "request->>'source_sha256' = source_sha256 AND "
        "request->>'payload_sha256' = payload_sha256 AND "
        "request->>'prepared_by' = prepared_by AND "
        "(request->>'prepared_at')::timestamptz = created_at AND "
        "request->>'source_binding' = 'VERIFIED_PERSISTED_SOURCE' AND "
        "request->>'document_role' = 'TENDER_REQUIREMENTS' AND "
        "request->>'retention' = 'RAW_RESPONSE_30_DAYS_V1' AND "
        "request->>'execution' = 'ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1') IS TRUE",
        name="ck_ai_transfer_request_identity",
    ),
)

ai_transfer_chunks = Table(
    "ai_transfer_chunks",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("chunk_id", Text, nullable=False),
    Column("request_body_json", Text, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("chunk", JSONB, nullable=False),
    PrimaryKeyConstraint("company_id", "transfer_id", "ordinal", name="pk_ai_transfer_chunks"),
    UniqueConstraint("company_id", "transfer_id", "chunk_id", name="uq_ai_transfer_chunk_id"),
    UniqueConstraint(
        "company_id",
        "transfer_id",
        "payload_sha256",
        "ordinal",
        "chunk_id",
        "request_sha256",
        name="uq_ai_transfer_chunk_dispatch_binding",
    ),
    ForeignKeyConstraint(
        ["company_id", "transfer_id", "payload_sha256"],
        [
            "ai_transfer_requests.company_id",
            "ai_transfer_requests.transfer_id",
            "ai_transfer_requests.payload_sha256",
        ],
        name="fk_ai_transfer_chunk_request",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_chunk_ordinal"),
    CheckConstraint(
        "chunk_id = 'chunk-' || lpad(ordinal::text, 4, '0')", name="ck_ai_transfer_chunk_id"
    ),
    CheckConstraint(
        "request_sha256 = encode(sha256(convert_to(request_body_json, 'UTF8')), 'hex')",
        name="ck_ai_transfer_chunk_body_digest",
    ),
    CheckConstraint(
        "(jsonb_typeof(chunk) = 'object' AND chunk->>'chunk_id' = chunk_id AND "
        "chunk->>'request_body_json' = request_body_json AND "
        "chunk->>'request_sha256' = request_sha256 AND "
        "jsonb_typeof(chunk->'source_block_ids') = 'array') IS TRUE",
        name="ck_ai_transfer_chunk_identity",
    ),
)

ai_transfer_approvals = Table(
    "ai_transfer_approvals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("approval", JSONB, nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "transfer_id", name="pk_ai_transfer_approvals"),
    UniqueConstraint(
        "company_id",
        "transfer_id",
        "request_payload_sha256",
        name="uq_ai_transfer_approval_exact",
    ),
    ForeignKeyConstraint(
        ["company_id", "transfer_id", "request_payload_sha256"],
        [
            "ai_transfer_requests.company_id",
            "ai_transfer_requests.transfer_id",
            "ai_transfer_requests.payload_sha256",
        ],
        name="fk_ai_transfer_approval_request",
    ),
    CheckConstraint("btrim(approved_by) <> ''", name="ck_ai_transfer_approver"),
    CheckConstraint(
        "expires_at = approved_at + interval '15 minutes'", name="ck_ai_transfer_approval_expiry"
    ),
    CheckConstraint(
        "(jsonb_typeof(approval) = 'object' AND "
        "approval->>'schema_version' = 'persisted-ai-transfer-approval-v1' AND "
        "approval->>'company_id' = company_id AND approval->>'transfer_id' = transfer_id AND "
        "approval->>'request_payload_sha256' = request_payload_sha256 AND "
        "approval->>'status' = 'APPROVED' AND approval->>'approved_by' = approved_by AND "
        "(approval->>'approved_at')::timestamptz = approved_at AND "
        "(approval->>'expires_at')::timestamptz = expires_at) IS TRUE",
        name="ck_ai_transfer_approval_identity",
    ),
)

ai_transfer_execution_admissions = Table(
    "ai_transfer_execution_admissions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("approval_expires_at", DateTime(timezone=True), nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("admission", JSONB, nullable=False),
    Column("admitted_by", Text, nullable=False),
    Column("admitted_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "execution_id", name="pk_ai_transfer_execution_admissions"),
    UniqueConstraint("company_id", "transfer_id", name="uq_ai_transfer_execution_transfer"),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "transfer_id",
        "request_payload_sha256",
        "payload_sha256",
        name="uq_ai_transfer_execution_binding",
    ),
    ForeignKeyConstraint(
        ["company_id", "transfer_id", "request_payload_sha256"],
        [
            "ai_transfer_requests.company_id",
            "ai_transfer_requests.transfer_id",
            "ai_transfer_requests.payload_sha256",
        ],
        name="fk_ai_transfer_admission_request",
    ),
    ForeignKeyConstraint(
        ["company_id", "transfer_id", "request_payload_sha256"],
        [
            "ai_transfer_approvals.company_id",
            "ai_transfer_approvals.transfer_id",
            "ai_transfer_approvals.request_payload_sha256",
        ],
        name="fk_ai_transfer_admission_approval",
    ),
    CheckConstraint(
        "request_payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_admission_payload_sha256",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ai_transfer_admission_event_sha256"
    ),
    CheckConstraint("chunk_count BETWEEN 1 AND 9999", name="ck_ai_transfer_admission_chunks"),
    CheckConstraint(
        "approval_expires_at = approved_at + interval '15 minutes'",
        name="ck_ai_transfer_admission_approval_window",
    ),
    CheckConstraint("btrim(execution_id) <> ''", name="ck_ai_transfer_admission_execution_id"),
    CheckConstraint("btrim(approved_by) <> ''", name="ck_ai_transfer_admission_approver"),
    CheckConstraint("btrim(admitted_by) <> ''", name="ck_ai_transfer_admission_actor"),
    CheckConstraint(
        "(jsonb_typeof(admission) = 'object' AND "
        "admission->>'schema_version' IS NOT DISTINCT FROM "
        "'ai-transfer-execution-admission-v1' AND "
        "admission->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "admission->>'execution_id' IS NOT DISTINCT FROM execution_id AND "
        "admission->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND "
        "admission->>'request_payload_sha256' IS NOT DISTINCT FROM "
        "request_payload_sha256 AND "
        "admission->>'approved_by' IS NOT DISTINCT FROM approved_by AND "
        "(admission->>'approved_at')::timestamptz IS NOT DISTINCT FROM approved_at AND "
        "(admission->>'approval_expires_at')::timestamptz IS NOT DISTINCT FROM "
        "approval_expires_at AND "
        "(admission->>'chunk_count')::integer IS NOT DISTINCT FROM chunk_count AND "
        "admission->>'status' IS NOT DISTINCT FROM 'ADMITTED' AND "
        "admission->>'execution_policy' IS NOT DISTINCT FROM "
        "'ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1' AND "
        "admission->>'admitted_by' IS NOT DISTINCT FROM admitted_by AND "
        "(admission->>'admitted_at')::timestamptz IS NOT DISTINCT FROM admitted_at AND "
        "admission->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256) IS TRUE",
        name="ck_ai_transfer_admission_identity",
    ),
)

ai_transfer_dispatch_claims = Table(
    "ai_transfer_dispatch_claims",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("admission_payload_sha256", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("chunk_id", Text, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("claim", JSONB, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("claim_status", Text, nullable=False),
    Column("delivery_state", Text, nullable=False),
    Column("claimed_by", Text, nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "execution_id", "ordinal", name="pk_ai_transfer_dispatch_claims"
    ),
    UniqueConstraint("company_id", "claim_id", name="uq_ai_transfer_dispatch_claim_id"),
    UniqueConstraint(
        "company_id",
        "transfer_id",
        "ordinal",
        name="uq_ai_transfer_dispatch_transfer_ordinal",
    ),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "transfer_id",
        "ordinal",
        "claim_id",
        "chunk_id",
        "request_sha256",
        "payload_sha256",
        name="uq_ai_transfer_dispatch_claim_receipt_binding",
    ),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "transfer_id",
        "ordinal",
        "claim_id",
        "payload_sha256",
        name="uq_ai_transfer_claim_materialization_binding",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "request_payload_sha256",
            "admission_payload_sha256",
        ],
        [
            "ai_transfer_execution_admissions.company_id",
            "ai_transfer_execution_admissions.execution_id",
            "ai_transfer_execution_admissions.transfer_id",
            "ai_transfer_execution_admissions.request_payload_sha256",
            "ai_transfer_execution_admissions.payload_sha256",
        ],
        name="fk_ai_transfer_claim_admission",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "transfer_id",
            "request_payload_sha256",
            "ordinal",
            "chunk_id",
            "request_sha256",
        ],
        [
            "ai_transfer_chunks.company_id",
            "ai_transfer_chunks.transfer_id",
            "ai_transfer_chunks.payload_sha256",
            "ai_transfer_chunks.ordinal",
            "ai_transfer_chunks.chunk_id",
            "ai_transfer_chunks.request_sha256",
        ],
        name="fk_ai_transfer_claim_chunk",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_dispatch_ordinal"),
    CheckConstraint("btrim(claim_id) <> ''", name="ck_ai_transfer_dispatch_claim_id"),
    CheckConstraint("attempt = 1", name="ck_ai_transfer_dispatch_attempt"),
    CheckConstraint("claim_status = 'PERMANENTLY_CLAIMED'", name="ck_ai_transfer_dispatch_status"),
    CheckConstraint("delivery_state = 'DELIVERY_UNKNOWN'", name="ck_ai_transfer_dispatch_delivery"),
    CheckConstraint("btrim(claimed_by) <> ''", name="ck_ai_transfer_dispatch_actor"),
    CheckConstraint(
        "request_payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_dispatch_payload_sha256",
    ),
    CheckConstraint(
        "request_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_dispatch_request_sha256",
    ),
    CheckConstraint(
        "admission_payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_dispatch_admission_sha256",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ai_transfer_dispatch_event_sha256"
    ),
    CheckConstraint(
        "(jsonb_typeof(claim) = 'object' AND "
        "claim->>'schema_version' IS NOT DISTINCT FROM 'ai-transfer-dispatch-claim-v1' AND "
        "claim->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "claim->>'claim_id' IS NOT DISTINCT FROM claim_id AND "
        "claim->>'execution_id' IS NOT DISTINCT FROM execution_id AND "
        "claim->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND "
        "claim->>'request_payload_sha256' IS NOT DISTINCT FROM request_payload_sha256 AND "
        "claim->>'admission_payload_sha256' IS NOT DISTINCT FROM "
        "admission_payload_sha256 AND "
        "(claim->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND "
        "claim->>'chunk_id' IS NOT DISTINCT FROM chunk_id AND "
        "claim->>'request_sha256' IS NOT DISTINCT FROM request_sha256 AND "
        "(claim->>'attempt')::integer IS NOT DISTINCT FROM attempt AND "
        "claim->>'claim_status' IS NOT DISTINCT FROM claim_status AND "
        "claim->>'delivery_state' IS NOT DISTINCT FROM delivery_state AND "
        "claim->>'claimed_by' IS NOT DISTINCT FROM claimed_by AND "
        "(claim->>'claimed_at')::timestamptz IS NOT DISTINCT FROM claimed_at AND "
        "claim->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256) IS TRUE",
        name="ck_ai_transfer_dispatch_identity",
    ),
)

ai_transfer_dispatch_receipts = Table(
    "ai_transfer_dispatch_receipts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("chunk_id", Text, nullable=False),
    Column("claim_payload_sha256", String(64), nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempted", Boolean, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("http_status", Integer, nullable=True),
    Column("capture_complete", Boolean, nullable=False),
    Column("captured_byte_count", Integer, nullable=False),
    Column("response_body_sha256", String(64), nullable=True),
    Column("provider_response_id", String(500), nullable=True),
    Column("provider_model", String(500), nullable=True),
    Column("assistant_content_sha256", String(64), nullable=True),
    Column("assistant_content_byte_count", Integer, nullable=True),
    Column("validator_version", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("receipt", JSONB, nullable=False),
    Column("recorded_by", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "execution_id", "ordinal", name="pk_ai_transfer_dispatch_receipts"
    ),
    UniqueConstraint("company_id", "receipt_id", name="uq_ai_transfer_dispatch_receipt_id"),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "transfer_id",
        "ordinal",
        "claim_id",
        "chunk_id",
        "claim_payload_sha256",
        "receipt_id",
        "payload_sha256",
        "request_sha256",
        "capture_complete",
        "response_body_sha256",
        "captured_byte_count",
        "finished_at",
        name="uq_ai_transfer_dispatch_receipt_raw_binding",
    ),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "transfer_id",
        "ordinal",
        "claim_id",
        "receipt_id",
        "payload_sha256",
        name="uq_ai_transfer_receipt_materialization_binding",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "chunk_id",
            "request_sha256",
            "claim_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_claims.company_id",
            "ai_transfer_dispatch_claims.execution_id",
            "ai_transfer_dispatch_claims.transfer_id",
            "ai_transfer_dispatch_claims.ordinal",
            "ai_transfer_dispatch_claims.claim_id",
            "ai_transfer_dispatch_claims.chunk_id",
            "ai_transfer_dispatch_claims.request_sha256",
            "ai_transfer_dispatch_claims.payload_sha256",
        ],
        name="fk_ai_transfer_receipt_exact_claim",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_receipt_ordinal"),
    CheckConstraint("btrim(receipt_id) <> ''", name="ck_ai_transfer_receipt_id"),
    CheckConstraint("btrim(claim_id) <> ''", name="ck_ai_transfer_receipt_claim_id"),
    CheckConstraint("btrim(recorded_by) <> ''", name="ck_ai_transfer_receipt_actor"),
    CheckConstraint(
        "claim_payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_receipt_claim_sha256",
    ),
    CheckConstraint(
        "request_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_receipt_request_sha256",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ai_transfer_receipt_event_sha256"
    ),
    CheckConstraint(
        "response_body_sha256 IS NULL OR response_body_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_receipt_response_sha256",
    ),
    CheckConstraint(
        "assistant_content_sha256 IS NULL OR assistant_content_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_receipt_content_sha256",
    ),
    CheckConstraint(
        "outcome IN ('SUCCESS', 'FAILED', 'DELIVERY_UNKNOWN')",
        name="ck_ai_transfer_receipt_outcome",
    ),
    CheckConstraint("status = 'TERMINAL'", name="ck_ai_transfer_receipt_status"),
    CheckConstraint(
        "reason IN ('VALIDATED_RESPONSE', 'REDIRECT_REJECTED', "
        "'HTTP_STATUS_REJECTED', 'MALFORMED_RESPONSE_JSON', "
        "'INVALID_PROVIDER_ENVELOPE', 'MODEL_MISMATCH', "
        "'INVALID_WIRE_RESPONSE', 'TIMEOUT', 'NETWORK_ERROR', "
        "'RESPONSE_TOO_LARGE', 'INCOMPLETE_RESPONSE', "
        "'COMPRESSED_RESPONSE', 'APPROVAL_EXPIRED_BEFORE_DISPATCH')",
        name="ck_ai_transfer_receipt_reason",
    ),
    CheckConstraint(
        "validator_version = 'ai-transfer-transport-validator-v1'",
        name="ck_ai_transfer_receipt_validator",
    ),
    CheckConstraint(
        "http_status IS NULL OR http_status BETWEEN 100 AND 599",
        name="ck_ai_transfer_receipt_http_status",
    ),
    CheckConstraint("captured_byte_count >= 0", name="ck_ai_transfer_receipt_captured_bytes"),
    CheckConstraint(
        "assistant_content_byte_count IS NULL OR assistant_content_byte_count >= 1",
        name="ck_ai_transfer_receipt_content_bytes",
    ),
    CheckConstraint(
        "capture_complete = (response_body_sha256 IS NOT NULL)",
        name="ck_ai_transfer_receipt_capture_digest",
    ),
    CheckConstraint(
        "(provider_response_id IS NULL OR "
        "(btrim(provider_response_id) <> '' AND "
        "provider_response_id !~ '[[:cntrl:]]')) AND "
        "(provider_model IS NULL OR "
        "(btrim(provider_model) <> '' AND provider_model !~ '[[:cntrl:]]'))",
        name="ck_ai_transfer_receipt_provider_text",
    ),
    CheckConstraint(
        "(provider_response_id IS NULL) = (provider_model IS NULL)",
        name="ck_ai_transfer_receipt_provider_pair",
    ),
    CheckConstraint(
        "(assistant_content_sha256 IS NULL) = (assistant_content_byte_count IS NULL)",
        name="ck_ai_transfer_receipt_content_pair",
    ),
    CheckConstraint(
        "attempted = (started_at IS NOT NULL AND finished_at IS NOT NULL) AND "
        "(started_at IS NULL OR finished_at >= started_at) AND "
        "(finished_at IS NULL OR recorded_at >= finished_at)",
        name="ck_ai_transfer_receipt_chronology",
    ),
    CheckConstraint(
        "((outcome = 'SUCCESS') = (reason = 'VALIDATED_RESPONSE') AND "
        "(outcome = 'DELIVERY_UNKNOWN') = "
        "(reason IN ('TIMEOUT', 'NETWORK_ERROR', 'RESPONSE_TOO_LARGE', "
        "'INCOMPLETE_RESPONSE', 'COMPRESSED_RESPONSE')) AND "
        "((outcome = 'SUCCESS' AND attempted AND http_status = 200 AND "
        "capture_complete AND captured_byte_count >= 1 AND "
        "response_body_sha256 IS NOT NULL AND "
        "provider_response_id IS NOT NULL AND provider_model IS NOT NULL AND "
        "assistant_content_sha256 IS NOT NULL AND "
        "assistant_content_byte_count IS NOT NULL) OR "
        "(outcome = 'DELIVERY_UNKNOWN' AND attempted AND NOT capture_complete AND "
        "response_body_sha256 IS NULL AND provider_response_id IS NULL AND "
        "provider_model IS NULL AND assistant_content_sha256 IS NULL AND "
        "assistant_content_byte_count IS NULL) OR "
        "(outcome = 'FAILED' AND reason = 'REDIRECT_REJECTED' AND attempted AND "
        "http_status BETWEEN 300 AND 399 AND NOT capture_complete AND "
        "captured_byte_count = 0 AND response_body_sha256 IS NULL AND "
        "provider_response_id IS NULL AND provider_model IS NULL AND "
        "assistant_content_sha256 IS NULL AND "
        "assistant_content_byte_count IS NULL) OR "
        "(outcome = 'FAILED' AND reason = 'HTTP_STATUS_REJECTED' AND attempted AND "
        "http_status IS NOT NULL AND http_status <> 200 AND "
        "NOT (http_status BETWEEN 300 AND 399) AND "
        "capture_complete AND response_body_sha256 IS NOT NULL AND "
        "provider_response_id IS NULL AND provider_model IS NULL AND "
        "assistant_content_sha256 IS NULL AND "
        "assistant_content_byte_count IS NULL) OR "
        "(outcome = 'FAILED' AND reason IN "
        "('MALFORMED_RESPONSE_JSON', 'INVALID_PROVIDER_ENVELOPE') AND attempted AND "
        "http_status = 200 AND capture_complete AND "
        "response_body_sha256 IS NOT NULL AND provider_response_id IS NULL AND "
        "provider_model IS NULL AND assistant_content_sha256 IS NULL AND "
        "assistant_content_byte_count IS NULL) OR "
        "(outcome = 'FAILED' AND reason IN "
        "('MODEL_MISMATCH', 'INVALID_WIRE_RESPONSE') AND attempted AND "
        "http_status = 200 AND capture_complete AND "
        "response_body_sha256 IS NOT NULL AND provider_response_id IS NOT NULL AND "
        "provider_model IS NOT NULL AND assistant_content_sha256 IS NULL AND "
        "assistant_content_byte_count IS NULL) OR "
        "(outcome = 'FAILED' AND reason = 'APPROVAL_EXPIRED_BEFORE_DISPATCH' AND "
        "NOT attempted AND http_status IS NULL AND NOT capture_complete AND "
        "captured_byte_count = 0 AND response_body_sha256 IS NULL AND "
        "provider_response_id IS NULL AND provider_model IS NULL AND "
        "assistant_content_sha256 IS NULL AND "
        "assistant_content_byte_count IS NULL))) IS TRUE",
        name="ck_ai_transfer_receipt_terminal_semantics",
    ),
    CheckConstraint(
        "(jsonb_typeof(receipt) = 'object' AND "
        "receipt ?& ARRAY['schema_version', 'company_id', 'transfer_id', "
        "'execution_id', 'ordinal', 'claim_id', 'chunk_id', "
        "'claim_payload_sha256', 'receipt_id', "
        "'outcome', 'reason', 'status', 'attempted', 'request_sha256', 'http_status', "
        "'capture_complete', 'captured_byte_count', 'response_body_sha256', "
        "'provider_response_id', 'provider_model', 'assistant_content_sha256', "
        "'assistant_content_byte_count', 'validator_version', 'started_at', "
        "'finished_at', 'recorded_by', 'recorded_at', 'payload_sha256'] AND "
        "receipt - ARRAY['schema_version', 'company_id', 'transfer_id', "
        "'execution_id', 'ordinal', 'claim_id', 'chunk_id', "
        "'claim_payload_sha256', 'receipt_id', "
        "'outcome', 'reason', 'status', 'attempted', 'request_sha256', 'http_status', "
        "'capture_complete', 'captured_byte_count', 'response_body_sha256', "
        "'provider_response_id', 'provider_model', 'assistant_content_sha256', "
        "'assistant_content_byte_count', 'validator_version', 'started_at', "
        "'finished_at', 'recorded_by', 'recorded_at', 'payload_sha256'] = '{}'::jsonb AND "
        "receipt->>'schema_version' IS NOT DISTINCT FROM "
        "'ai-transfer-dispatch-receipt-v1' AND "
        "receipt->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "receipt->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND "
        "receipt->>'execution_id' IS NOT DISTINCT FROM execution_id AND "
        "(receipt->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND "
        "receipt->>'claim_id' IS NOT DISTINCT FROM claim_id AND "
        "receipt->>'chunk_id' IS NOT DISTINCT FROM chunk_id AND "
        "receipt->>'claim_payload_sha256' IS NOT DISTINCT FROM claim_payload_sha256 AND "
        "receipt->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND "
        "receipt->>'outcome' IS NOT DISTINCT FROM outcome AND "
        "receipt->>'reason' IS NOT DISTINCT FROM reason AND "
        "receipt->>'status' IS NOT DISTINCT FROM status AND "
        "(receipt->>'attempted')::boolean IS NOT DISTINCT FROM attempted AND "
        "receipt->>'request_sha256' IS NOT DISTINCT FROM request_sha256 AND "
        "(receipt->>'http_status')::integer IS NOT DISTINCT FROM http_status AND "
        "(receipt->>'capture_complete')::boolean IS NOT DISTINCT FROM capture_complete AND "
        "(receipt->>'captured_byte_count')::integer IS NOT DISTINCT FROM "
        "captured_byte_count AND "
        "receipt->>'response_body_sha256' IS NOT DISTINCT FROM response_body_sha256 AND "
        "receipt->>'provider_response_id' IS NOT DISTINCT FROM provider_response_id AND "
        "receipt->>'provider_model' IS NOT DISTINCT FROM provider_model AND "
        "receipt->>'assistant_content_sha256' IS NOT DISTINCT FROM "
        "assistant_content_sha256 AND "
        "(receipt->>'assistant_content_byte_count')::integer IS NOT DISTINCT FROM "
        "assistant_content_byte_count AND "
        "receipt->>'validator_version' IS NOT DISTINCT FROM validator_version AND "
        "(receipt->>'started_at')::timestamptz IS NOT DISTINCT FROM started_at AND "
        "(receipt->>'finished_at')::timestamptz IS NOT DISTINCT FROM finished_at AND "
        "receipt->>'recorded_by' IS NOT DISTINCT FROM recorded_by AND "
        "(receipt->>'recorded_at')::timestamptz IS NOT DISTINCT FROM recorded_at AND "
        "receipt->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256) IS TRUE",
        name="ck_ai_transfer_receipt_identity",
    ),
)

ai_transfer_raw_responses = Table(
    "ai_transfer_raw_responses",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("raw_response_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("chunk_id", Text, nullable=False),
    Column("claim_payload_sha256", String(64), nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("receipt_payload_sha256", String(64), nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("capture_complete", Boolean, nullable=False),
    Column("response_body_sha256", String(64), nullable=False),
    Column("response_byte_count", Integer, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("algorithm", Text, nullable=False),
    Column("key_id", Text, nullable=False),
    Column("body_aad_sha256", String(64), nullable=False),
    Column("metadata_sha256", String(64), nullable=False),
    Column("wrap_aad_sha256", String(64), nullable=False),
    Column("envelope_sha256", String(64), nullable=False),
    Column("metadata", JSONB, nullable=False),
    PrimaryKeyConstraint("company_id", "raw_response_id", name="pk_ai_transfer_raw_responses"),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "ordinal",
        name="uq_ai_transfer_raw_response_receipt",
    ),
    UniqueConstraint(
        "company_id",
        "raw_response_id",
        "receipt_id",
        "response_body_sha256",
        "response_byte_count",
        "received_at",
        "expires_at",
        "schema_version",
        "algorithm",
        "key_id",
        "body_aad_sha256",
        "metadata_sha256",
        "wrap_aad_sha256",
        "envelope_sha256",
        name="uq_ai_transfer_raw_metadata_binding",
    ),
    UniqueConstraint(
        "company_id",
        "raw_response_id",
        "receipt_id",
        "metadata_sha256",
        name="uq_ai_transfer_raw_materialization_binding",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "chunk_id",
            "claim_payload_sha256",
            "receipt_id",
            "receipt_payload_sha256",
            "request_sha256",
            "capture_complete",
            "response_body_sha256",
            "response_byte_count",
            "received_at",
        ],
        [
            "ai_transfer_dispatch_receipts.company_id",
            "ai_transfer_dispatch_receipts.execution_id",
            "ai_transfer_dispatch_receipts.transfer_id",
            "ai_transfer_dispatch_receipts.ordinal",
            "ai_transfer_dispatch_receipts.claim_id",
            "ai_transfer_dispatch_receipts.chunk_id",
            "ai_transfer_dispatch_receipts.claim_payload_sha256",
            "ai_transfer_dispatch_receipts.receipt_id",
            "ai_transfer_dispatch_receipts.payload_sha256",
            "ai_transfer_dispatch_receipts.request_sha256",
            "ai_transfer_dispatch_receipts.capture_complete",
            "ai_transfer_dispatch_receipts.response_body_sha256",
            "ai_transfer_dispatch_receipts.captured_byte_count",
            "ai_transfer_dispatch_receipts.finished_at",
        ],
        name="fk_ai_transfer_raw_exact_receipt",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint(
        "ordinal BETWEEN 1 AND 9999",
        name="ck_ai_transfer_raw_ordinal",
    ),
    CheckConstraint("capture_complete", name="ck_ai_transfer_raw_complete_capture"),
    CheckConstraint(
        f"response_byte_count BETWEEN 0 AND {MAX_AI_TRANSFER_RAW_RESPONSE_BYTES}",
        name="ck_ai_transfer_raw_response_bytes",
    ),
    CheckConstraint(
        "expires_at = received_at + interval '720 hours'",
        name="ck_ai_transfer_raw_expiry",
    ),
    CheckConstraint(
        "schema_version = 'ai-transfer-raw-metadata-v1'",
        name="ck_ai_transfer_raw_schema",
    ),
    CheckConstraint(
        "algorithm = 'AES-256-GCM+TENANT-KEK-V1'",
        name="ck_ai_transfer_raw_algorithm",
    ),
    CheckConstraint(
        "btrim(raw_response_id) <> '' AND raw_response_id !~ '[[:cntrl:]]' AND "
        "btrim(key_id) <> '' AND key_id !~ '[[:cntrl:]]'",
        name="ck_ai_transfer_raw_safe_text",
    ),
    CheckConstraint(
        "claim_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "receipt_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "request_sha256 ~ '^[0-9a-f]{64}$' AND "
        "response_body_sha256 ~ '^[0-9a-f]{64}$' AND "
        "body_aad_sha256 ~ '^[0-9a-f]{64}$' AND "
        "metadata_sha256 ~ '^[0-9a-f]{64}$' AND "
        "wrap_aad_sha256 ~ '^[0-9a-f]{64}$' AND "
        "envelope_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_raw_digests",
    ),
    CheckConstraint(
        "(jsonb_typeof(metadata) = 'object' AND "
        "metadata ?& ARRAY['schema_version', 'company_id', 'raw_response_id', "
        "'transfer_id', 'execution_id', 'ordinal', 'claim_id', 'chunk_id', "
        "'claim_payload_sha256', 'receipt_id', 'receipt_payload_sha256', "
        "'request_sha256', 'response_body_sha256', 'response_byte_count', "
        "'received_at', 'expires_at', 'algorithm', 'key_id', "
        "'body_aad_sha256', 'metadata_sha256'] AND "
        "metadata - ARRAY['schema_version', 'company_id', 'raw_response_id', "
        "'transfer_id', 'execution_id', 'ordinal', 'claim_id', 'chunk_id', "
        "'claim_payload_sha256', 'receipt_id', 'receipt_payload_sha256', "
        "'request_sha256', 'response_body_sha256', 'response_byte_count', "
        "'received_at', 'expires_at', 'algorithm', 'key_id', "
        "'body_aad_sha256', 'metadata_sha256'] = '{}'::jsonb AND "
        "metadata->>'schema_version' IS NOT DISTINCT FROM schema_version AND "
        "metadata->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "metadata->>'raw_response_id' IS NOT DISTINCT FROM raw_response_id AND "
        "metadata->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND "
        "metadata->>'execution_id' IS NOT DISTINCT FROM execution_id AND "
        "(metadata->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND "
        "metadata->>'claim_id' IS NOT DISTINCT FROM claim_id AND "
        "metadata->>'chunk_id' IS NOT DISTINCT FROM chunk_id AND "
        "metadata->>'claim_payload_sha256' IS NOT DISTINCT FROM claim_payload_sha256 AND "
        "metadata->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND "
        "metadata->>'receipt_payload_sha256' IS NOT DISTINCT FROM "
        "receipt_payload_sha256 AND "
        "metadata->>'request_sha256' IS NOT DISTINCT FROM request_sha256 AND "
        "metadata->>'response_body_sha256' IS NOT DISTINCT FROM "
        "response_body_sha256 AND "
        "(metadata->>'response_byte_count')::integer IS NOT DISTINCT FROM "
        "response_byte_count AND "
        "(metadata->>'received_at')::timestamptz IS NOT DISTINCT FROM received_at AND "
        "(metadata->>'expires_at')::timestamptz IS NOT DISTINCT FROM expires_at AND "
        "metadata->>'algorithm' IS NOT DISTINCT FROM algorithm AND "
        "metadata->>'key_id' IS NOT DISTINCT FROM key_id AND "
        "metadata->>'body_aad_sha256' IS NOT DISTINCT FROM body_aad_sha256 AND "
        "metadata->>'metadata_sha256' IS NOT DISTINCT FROM metadata_sha256) IS TRUE",
        name="ck_ai_transfer_raw_metadata_identity",
    ),
)

ai_transfer_raw_response_blobs = Table(
    "ai_transfer_raw_response_blobs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("raw_response_id", Text, nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("response_body_sha256", String(64), nullable=False),
    Column("response_byte_count", Integer, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("metadata_schema_version", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("algorithm", Text, nullable=False),
    Column("key_id", Text, nullable=False),
    Column("body_aad_sha256", String(64), nullable=False),
    Column("metadata_sha256", String(64), nullable=False),
    Column("wrap_aad_sha256", String(64), nullable=False),
    Column("envelope_sha256", String(64), nullable=False),
    Column("body_nonce", LargeBinary, nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("wrapping_nonce", LargeBinary, nullable=False),
    Column("wrapped_dek", LargeBinary, nullable=False),
    PrimaryKeyConstraint("company_id", "raw_response_id", name="pk_ai_transfer_raw_response_blobs"),
    ForeignKeyConstraint(
        [
            "company_id",
            "raw_response_id",
            "receipt_id",
            "response_body_sha256",
            "response_byte_count",
            "received_at",
            "expires_at",
            "metadata_schema_version",
            "algorithm",
            "key_id",
            "body_aad_sha256",
            "metadata_sha256",
            "wrap_aad_sha256",
            "envelope_sha256",
        ],
        [
            "ai_transfer_raw_responses.company_id",
            "ai_transfer_raw_responses.raw_response_id",
            "ai_transfer_raw_responses.receipt_id",
            "ai_transfer_raw_responses.response_body_sha256",
            "ai_transfer_raw_responses.response_byte_count",
            "ai_transfer_raw_responses.received_at",
            "ai_transfer_raw_responses.expires_at",
            "ai_transfer_raw_responses.schema_version",
            "ai_transfer_raw_responses.algorithm",
            "ai_transfer_raw_responses.key_id",
            "ai_transfer_raw_responses.body_aad_sha256",
            "ai_transfer_raw_responses.metadata_sha256",
            "ai_transfer_raw_responses.wrap_aad_sha256",
            "ai_transfer_raw_responses.envelope_sha256",
        ],
        name="fk_ai_transfer_raw_blob_exact_metadata",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint(
        "schema_version = 'ai-transfer-raw-envelope-v1'",
        name="ck_ai_transfer_raw_blob_schema",
    ),
    CheckConstraint(
        "octet_length(body_nonce) = 12 AND octet_length(wrapping_nonce) = 12 AND "
        "body_nonce <> wrapping_nonce",
        name="ck_ai_transfer_raw_blob_nonces",
    ),
    CheckConstraint(
        "octet_length(ciphertext) = response_byte_count + 16",
        name="ck_ai_transfer_raw_blob_ciphertext",
    ),
    CheckConstraint(
        "octet_length(wrapped_dek) = 48",
        name="ck_ai_transfer_raw_blob_wrapped_dek",
    ),
)

ai_transfer_raw_response_deletion_receipts = Table(
    "ai_transfer_raw_response_deletion_receipts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("raw_response_id", Text, nullable=False),
    Column("deletion_receipt_id", Text, nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("response_body_sha256", String(64), nullable=False),
    Column("response_byte_count", Integer, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("metadata_schema_version", Text, nullable=False),
    Column("algorithm", Text, nullable=False),
    Column("key_id", Text, nullable=False),
    Column("body_aad_sha256", String(64), nullable=False),
    Column("metadata_sha256", String(64), nullable=False),
    Column("wrap_aad_sha256", String(64), nullable=False),
    Column("envelope_sha256", String(64), nullable=False),
    Column("reason", Text, nullable=False),
    Column("deleted_by", Text, nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("deletion_receipt", JSONB, nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "raw_response_id",
        name="pk_ai_transfer_raw_response_deletion_receipts",
    ),
    UniqueConstraint(
        "company_id",
        "deletion_receipt_id",
        name="uq_ai_transfer_raw_deletion_receipt_id",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "raw_response_id",
            "receipt_id",
            "response_body_sha256",
            "response_byte_count",
            "received_at",
            "expires_at",
            "metadata_schema_version",
            "algorithm",
            "key_id",
            "body_aad_sha256",
            "metadata_sha256",
            "wrap_aad_sha256",
            "envelope_sha256",
        ],
        [
            "ai_transfer_raw_responses.company_id",
            "ai_transfer_raw_responses.raw_response_id",
            "ai_transfer_raw_responses.receipt_id",
            "ai_transfer_raw_responses.response_body_sha256",
            "ai_transfer_raw_responses.response_byte_count",
            "ai_transfer_raw_responses.received_at",
            "ai_transfer_raw_responses.expires_at",
            "ai_transfer_raw_responses.schema_version",
            "ai_transfer_raw_responses.algorithm",
            "ai_transfer_raw_responses.key_id",
            "ai_transfer_raw_responses.body_aad_sha256",
            "ai_transfer_raw_responses.metadata_sha256",
            "ai_transfer_raw_responses.wrap_aad_sha256",
            "ai_transfer_raw_responses.envelope_sha256",
        ],
        name="fk_ai_transfer_raw_deletion_exact_metadata",
    ),
    CheckConstraint(
        "btrim(deletion_receipt_id) <> '' AND "
        "deletion_receipt_id !~ '[[:cntrl:]]' AND "
        "btrim(deleted_by) <> '' AND deleted_by !~ '[[:cntrl:]]'",
        name="ck_ai_transfer_raw_deletion_safe_text",
    ),
    CheckConstraint(
        "reason = 'RETENTION_EXPIRED'",
        name="ck_ai_transfer_raw_deletion_reason",
    ),
    CheckConstraint(
        "deleted_at >= expires_at",
        name="ck_ai_transfer_raw_deletion_expired",
    ),
    CheckConstraint(
        "response_body_sha256 ~ '^[0-9a-f]{64}$' AND "
        "body_aad_sha256 ~ '^[0-9a-f]{64}$' AND "
        "metadata_sha256 ~ '^[0-9a-f]{64}$' AND "
        "wrap_aad_sha256 ~ '^[0-9a-f]{64}$' AND "
        "envelope_sha256 ~ '^[0-9a-f]{64}$' AND "
        "payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_transfer_raw_deletion_digests",
    ),
    CheckConstraint(
        "(jsonb_typeof(deletion_receipt) = 'object' AND "
        "deletion_receipt ?& ARRAY['schema_version', 'company_id', "
        "'raw_response_id', 'deletion_receipt_id', 'receipt_id', "
        "'response_body_sha256', 'response_byte_count', 'received_at', "
        "'expires_at', 'metadata_schema_version', 'algorithm', 'key_id', "
        "'body_aad_sha256', 'metadata_sha256', 'wrap_aad_sha256', "
        "'envelope_sha256', 'reason', 'deleted_by', 'deleted_at', "
        "'payload_sha256'] AND "
        "deletion_receipt - ARRAY['schema_version', 'company_id', "
        "'raw_response_id', 'deletion_receipt_id', 'receipt_id', "
        "'response_body_sha256', 'response_byte_count', 'received_at', "
        "'expires_at', 'metadata_schema_version', 'algorithm', 'key_id', "
        "'body_aad_sha256', 'metadata_sha256', 'wrap_aad_sha256', "
        "'envelope_sha256', 'reason', 'deleted_by', 'deleted_at', "
        "'payload_sha256'] = '{}'::jsonb AND "
        "deletion_receipt->>'schema_version' IS NOT DISTINCT FROM "
        "'ai-transfer-raw-deletion-receipt-v1' AND "
        "deletion_receipt->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "deletion_receipt->>'raw_response_id' IS NOT DISTINCT FROM raw_response_id AND "
        "deletion_receipt->>'deletion_receipt_id' IS NOT DISTINCT FROM "
        "deletion_receipt_id AND "
        "deletion_receipt->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND "
        "deletion_receipt->>'response_body_sha256' IS NOT DISTINCT FROM "
        "response_body_sha256 AND "
        "(deletion_receipt->>'response_byte_count')::integer IS NOT DISTINCT FROM "
        "response_byte_count AND "
        "(deletion_receipt->>'received_at')::timestamptz IS NOT DISTINCT FROM "
        "received_at AND "
        "(deletion_receipt->>'expires_at')::timestamptz IS NOT DISTINCT FROM "
        "expires_at AND "
        "deletion_receipt->>'metadata_schema_version' IS NOT DISTINCT FROM "
        "metadata_schema_version AND "
        "deletion_receipt->>'algorithm' IS NOT DISTINCT FROM algorithm AND "
        "deletion_receipt->>'key_id' IS NOT DISTINCT FROM key_id AND "
        "deletion_receipt->>'body_aad_sha256' IS NOT DISTINCT FROM body_aad_sha256 AND "
        "deletion_receipt->>'metadata_sha256' IS NOT DISTINCT FROM metadata_sha256 AND "
        "deletion_receipt->>'wrap_aad_sha256' IS NOT DISTINCT FROM wrap_aad_sha256 AND "
        "deletion_receipt->>'envelope_sha256' IS NOT DISTINCT FROM envelope_sha256 AND "
        "deletion_receipt->>'reason' IS NOT DISTINCT FROM reason AND "
        "deletion_receipt->>'deleted_by' IS NOT DISTINCT FROM deleted_by AND "
        "(deletion_receipt->>'deleted_at')::timestamptz IS NOT DISTINCT FROM "
        "deleted_at AND "
        "deletion_receipt->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256) "
        "IS TRUE",
        name="ck_ai_transfer_raw_deletion_identity",
    ),
)

case_versions = Table(
    "case_versions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "case_id", "version", name="pk_case_versions"),
    CheckConstraint("company_id <> ''", name="ck_case_versions_company_id_nonempty"),
    CheckConstraint("version >= 1", name="ck_case_versions_version_positive"),
    CheckConstraint(
        "input_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_case_versions_input_sha256",
    ),
)
Index(
    "ix_case_versions_company_case_created",
    case_versions.c.company_id,
    case_versions.c.case_id,
    case_versions.c.created_at,
)
Index(
    "ix_case_versions_company_input_sha256",
    case_versions.c.company_id,
    case_versions.c.input_sha256,
)

sourcing_runs = Table(
    "sourcing_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("source_sha256", String(64), nullable=True),
    Column("source_content", LargeBinary, nullable=True),
    Column("result", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_sourcing_runs"),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_sourcing_runs_case_version",
    ),
    CheckConstraint("company_id <> ''", name="ck_sourcing_runs_company_nonempty"),
    CheckConstraint("run_id <> ''", name="ck_sourcing_runs_id_nonempty"),
    CheckConstraint("case_id <> ''", name="ck_sourcing_runs_case_nonempty"),
    CheckConstraint("case_version >= 1", name="ck_sourcing_runs_version_positive"),
    CheckConstraint("status IN ('COMPLETED', 'SOURCE_ERROR')", name="ck_sourcing_runs_status"),
    CheckConstraint(
        f"((status = 'COMPLETED' AND source_sha256 ~ '^[0-9a-f]{{64}}$' "
        "AND source_sha256 = encode(sha256(source_content), 'hex') "
        f"AND octet_length(source_content) BETWEEN 1 AND {MAX_SOURCING_SNAPSHOT_BYTES}) "
        "OR (status = 'SOURCE_ERROR' AND source_sha256 IS NULL AND source_content IS NULL))",
        name="ck_sourcing_runs_source_shape",
    ),
    CheckConstraint("jsonb_typeof(result) = 'object'", name="ck_sourcing_runs_result_object"),
    CheckConstraint(
        "result->>'company_id' IS NOT DISTINCT FROM company_id",
        name="ck_sourcing_runs_result_company",
    ),
    CheckConstraint(
        "result->>'run_id' IS NOT DISTINCT FROM run_id", name="ck_sourcing_runs_result_id"
    ),
    CheckConstraint(
        "result->>'case_id' IS NOT DISTINCT FROM case_id", name="ck_sourcing_runs_result_case"
    ),
    CheckConstraint(
        "(result->>'case_version')::integer IS NOT DISTINCT FROM case_version",
        name="ck_sourcing_runs_result_version",
    ),
    CheckConstraint(
        "result->>'status' IS NOT DISTINCT FROM status", name="ck_sourcing_runs_result_status"
    ),
    CheckConstraint(
        "(result->>'created_at')::timestamptz IS NOT DISTINCT FROM created_at",
        name="ck_sourcing_runs_result_created",
    ),
    CheckConstraint(
        "((status = 'COMPLETED' AND result->>'source_sha256' IS NOT DISTINCT FROM source_sha256 "
        "AND (result->>'source_byte_size')::integer IS NOT DISTINCT FROM "
        "octet_length(source_content)) OR (status = 'SOURCE_ERROR' AND "
        "result->'source_sha256' = 'null'::jsonb AND "
        "result->'source_byte_size' = 'null'::jsonb))",
        name="ck_sourcing_runs_result_source",
    ),
)
Index(
    "ix_sourcing_runs_company_case_created",
    sourcing_runs.c.company_id,
    sourcing_runs.c.case_id,
    sourcing_runs.c.case_version,
    sourcing_runs.c.created_at,
    sourcing_runs.c.run_id,
)

sourcing_run_sources = Table(
    "sourcing_run_sources",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("source_sha256", String(64), nullable=True),
    Column("source_content", LargeBinary, nullable=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("error_code", Text, nullable=True),
    PrimaryKeyConstraint("company_id", "run_id", "ordinal", name="pk_sourcing_run_sources"),
    ForeignKeyConstraint(
        ["company_id", "run_id"],
        ["sourcing_runs.company_id", "sourcing_runs.run_id"],
        name="fk_sourcing_run_sources_run",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_sourcing_run_sources_ordinal"),
    CheckConstraint("btrim(source_name) <> ''", name="ck_sourcing_run_sources_name"),
    CheckConstraint("source_url ~ '^https://[^[:space:]]+$'", name="ck_sourcing_run_sources_url"),
    CheckConstraint(
        "source_kind IN ('MANUFACTURER_CATALOG', 'SUPPLIER_CATALOG')",
        name="ck_sourcing_run_sources_kind",
    ),
    CheckConstraint(
        "media_type IN ('text/html', 'application/pdf')",
        name="ck_sourcing_run_sources_media_type",
    ),
    CheckConstraint(
        "status IN ('COMPLETED', 'SOURCE_ERROR')",
        name="ck_sourcing_run_sources_status",
    ),
    CheckConstraint(
        "((status = 'COMPLETED' AND source_sha256 ~ '^[0-9a-f]{64}$' "
        "AND source_sha256 = encode(sha256(source_content), 'hex') "
        f"AND octet_length(source_content) BETWEEN 1 AND {MAX_SOURCING_SOURCE_BYTES} "
        "AND error_code IS NULL) OR (status = 'SOURCE_ERROR' AND source_sha256 IS NULL "
        "AND source_content IS NULL AND error_code ~ '^[A-Z][A-Z0-9_]{1,63}$'))",
        name="ck_sourcing_run_sources_shape",
    ),
)

documents = Table(
    "documents",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("document_id", Text, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("document_role", Text, nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("extraction", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "document_id", name="pk_documents"),
    UniqueConstraint("company_id", "document_id", "sha256", name="uq_documents_exact_source"),
    CheckConstraint("company_id <> ''", name="ck_documents_company_id_nonempty"),
    CheckConstraint("document_id <> ''", name="ck_documents_document_id_nonempty"),
    CheckConstraint(
        "original_filename <> ''",
        name="ck_documents_original_filename_nonempty",
    ),
    CheckConstraint("media_type <> ''", name="ck_documents_media_type_nonempty"),
    CheckConstraint(
        "document_role IN ('UNKNOWN', 'TENDER_REQUIREMENTS', 'SUPPLIER_QUOTE', "
        "'APPLICATION_ATTACHMENT')",
        name="ck_documents_role_allowed",
    ),
    CheckConstraint(
        f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
        name="ck_documents_byte_size",
    ),
    CheckConstraint(
        "octet_length(content) = byte_size",
        name="ck_documents_content_size",
    ),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_documents_sha256"),
    CheckConstraint(
        "jsonb_typeof(extraction) = 'object'",
        name="ck_documents_extraction_object",
    ),
)
Index(
    "ix_documents_company_created",
    documents.c.company_id,
    documents.c.created_at,
    documents.c.document_id,
)
Index(
    "ix_documents_company_sha256",
    documents.c.company_id,
    documents.c.sha256,
)

reviewed_requirement_set_proposals = Table(
    "reviewed_requirement_set_proposals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("set_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_document_sha256", String(64), nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("proposal", JSONB, nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("prepared_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "set_id", name="pk_reviewed_requirement_set_proposals"),
    UniqueConstraint(
        "company_id",
        "set_id",
        "proposal_sha256",
        name="uq_reviewed_requirement_set_proposal_exact",
    ),
    ForeignKeyConstraint(
        ["company_id", "source_document_id", "source_document_sha256"],
        ["documents.company_id", "documents.document_id", "documents.sha256"],
        name="fk_reviewed_requirement_set_source",
    ),
    CheckConstraint("company_id <> ''", name="ck_reviewed_requirement_set_company_nonempty"),
    CheckConstraint("set_id <> ''", name="ck_reviewed_requirement_set_id_nonempty"),
    CheckConstraint("prepared_by <> ''", name="ck_reviewed_requirement_set_preparer_nonempty"),
    CheckConstraint(
        "proposal_sha256 ~ '^[0-9a-f]{64}$' AND source_document_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_reviewed_requirement_set_digests",
    ),
    CheckConstraint("jsonb_typeof(proposal) = 'object'", name="ck_requirement_set_proposal_object"),
    CheckConstraint(
        "proposal->>'schema_version' IS NOT DISTINCT FROM "
        "'reviewed-requirement-set-proposal-v1' AND "
        "proposal->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "proposal->>'set_id' IS NOT DISTINCT FROM set_id AND "
        "proposal->>'source_document_id' IS NOT DISTINCT FROM source_document_id AND "
        "proposal->>'source_document_sha256' IS NOT DISTINCT FROM source_document_sha256 AND "
        "proposal->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
        "proposal->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND "
        "(proposal->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at",
        name="ck_reviewed_requirement_set_proposal_identity",
    ),
)

reviewed_requirement_set_decisions = Table(
    "reviewed_requirement_set_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("set_id", Text, nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "set_id", name="pk_reviewed_requirement_set_decisions"),
    UniqueConstraint(
        "company_id",
        "set_id",
        "proposal_sha256",
        "decision_sha256",
        name="uq_reviewed_requirement_set_decision_exact",
    ),
    ForeignKeyConstraint(
        ["company_id", "set_id", "proposal_sha256"],
        [
            "reviewed_requirement_set_proposals.company_id",
            "reviewed_requirement_set_proposals.set_id",
            "reviewed_requirement_set_proposals.proposal_sha256",
        ],
        name="fk_reviewed_requirement_set_decision_proposal",
    ),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')", name="ck_requirement_set_decision_status"
    ),
    CheckConstraint("reviewed_by <> ''", name="ck_requirement_set_reviewer_nonempty"),
    CheckConstraint(
        "proposal_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_requirement_set_decision_digests",
    ),
    CheckConstraint("jsonb_typeof(decision) = 'object'", name="ck_requirement_set_decision_object"),
    CheckConstraint(
        "decision->>'schema_version' IS NOT DISTINCT FROM "
        "'reviewed-requirement-set-decision-v1' AND "
        "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "decision->>'set_id' IS NOT DISTINCT FROM set_id AND "
        "decision->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
        "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "decision->>'status' IS NOT DISTINCT FROM status AND "
        "decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by AND "
        "(decision->>'reviewed_at')::timestamptz IS NOT DISTINCT FROM reviewed_at",
        name="ck_reviewed_requirement_set_decision_identity",
    ),
)

case_requirement_set_bindings = Table(
    "case_requirement_set_bindings",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("binding_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("set_id", Text, nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("binding_sha256", String(64), nullable=False),
    Column("binding", JSONB, nullable=False),
    Column("bound_by", Text, nullable=False),
    Column("bound_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "binding_id", name="pk_case_requirement_set_bindings"),
    UniqueConstraint(
        "company_id", "case_id", "case_version", name="uq_case_requirement_set_binding_version"
    ),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_case_requirement_set_binding_case",
    ),
    ForeignKeyConstraint(
        ["company_id", "set_id", "proposal_sha256", "decision_sha256"],
        [
            "reviewed_requirement_set_decisions.company_id",
            "reviewed_requirement_set_decisions.set_id",
            "reviewed_requirement_set_decisions.proposal_sha256",
            "reviewed_requirement_set_decisions.decision_sha256",
        ],
        name="fk_case_requirement_set_binding_decision",
    ),
    CheckConstraint("company_id <> ''", name="ck_case_requirement_set_company_nonempty"),
    CheckConstraint("binding_id <> ''", name="ck_case_requirement_set_binding_nonempty"),
    CheckConstraint("case_id <> '' AND case_version >= 1", name="ck_case_requirement_set_case"),
    CheckConstraint("set_id <> ''", name="ck_case_requirement_set_id_nonempty"),
    CheckConstraint("bound_by <> ''", name="ck_case_requirement_set_binder_nonempty"),
    CheckConstraint(
        "proposal_sha256 ~ '^[0-9a-f]{64}$' AND "
        "decision_sha256 ~ '^[0-9a-f]{64}$' AND "
        "binding_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_case_requirement_set_digests",
    ),
    CheckConstraint(
        "jsonb_typeof(binding) = 'object'", name="ck_case_requirement_set_binding_object"
    ),
    CheckConstraint(
        "binding->>'schema_version' IS NOT DISTINCT FROM 'case-requirement-set-binding-v1' AND "
        "binding->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "binding->>'binding_id' IS NOT DISTINCT FROM binding_id AND "
        "binding->>'case_id' IS NOT DISTINCT FROM case_id AND "
        "(binding->>'case_version')::integer IS NOT DISTINCT FROM case_version AND "
        "binding->>'set_id' IS NOT DISTINCT FROM set_id AND "
        "binding->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
        "binding->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "binding->>'binding_sha256' IS NOT DISTINCT FROM binding_sha256 AND "
        "binding->>'bound_by' IS NOT DISTINCT FROM bound_by AND "
        "(binding->>'bound_at')::timestamptz IS NOT DISTINCT FROM bound_at",
        name="ck_case_requirement_set_binding_identity",
    ),
)

server_offer_proposals = Table(
    "server_offer_proposals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("offer_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("requirement_set_binding_id", Text, nullable=False),
    Column("requirement_set_binding_sha256", String(64), nullable=False),
    Column("sourcing_run_id", Text, nullable=False),
    Column("lead_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_document_sha256", String(64), nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("proposal", JSONB, nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("prepared_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "offer_id", name="pk_server_offer_proposals"),
    UniqueConstraint(
        "company_id", "offer_id", "proposal_sha256", name="uq_server_offer_proposal_exact"
    ),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_server_offer_case_version",
    ),
    ForeignKeyConstraint(
        ["company_id", "requirement_set_binding_id"],
        ["case_requirement_set_bindings.company_id", "case_requirement_set_bindings.binding_id"],
        name="fk_server_offer_requirement_binding",
    ),
    ForeignKeyConstraint(
        ["company_id", "sourcing_run_id"],
        ["sourcing_runs.company_id", "sourcing_runs.run_id"],
        name="fk_server_offer_sourcing_run",
    ),
    ForeignKeyConstraint(
        ["company_id", "source_document_id", "source_document_sha256"],
        ["documents.company_id", "documents.document_id", "documents.sha256"],
        name="fk_server_offer_source_document",
    ),
    CheckConstraint("btrim(company_id) <> ''", name="ck_server_offer_company"),
    CheckConstraint("btrim(offer_id) <> ''", name="ck_server_offer_id"),
    CheckConstraint("btrim(case_id) <> '' AND case_version >= 1", name="ck_server_offer_case"),
    CheckConstraint("btrim(lead_id) <> ''", name="ck_server_offer_lead"),
    CheckConstraint(
        "requirement_set_binding_sha256 ~ '^[0-9a-f]{64}$' AND "
        "source_document_sha256 ~ '^[0-9a-f]{64}$' AND "
        "proposal_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_server_offer_digests",
    ),
    CheckConstraint("jsonb_typeof(proposal) = 'object'", name="ck_server_offer_object"),
    CheckConstraint(
        "proposal->>'schema_version' = 'server-offer-proposal-v1' AND "
        "proposal->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "proposal->>'offer_id' IS NOT DISTINCT FROM offer_id AND "
        "proposal->>'case_id' IS NOT DISTINCT FROM case_id AND "
        "(proposal->>'case_version')::integer IS NOT DISTINCT FROM case_version AND "
        "proposal->>'requirement_set_binding_id' IS NOT DISTINCT FROM "
        "requirement_set_binding_id AND "
        "proposal->>'requirement_set_binding_sha256' IS NOT DISTINCT FROM "
        "requirement_set_binding_sha256 AND "
        "proposal->>'sourcing_run_id' IS NOT DISTINCT FROM sourcing_run_id AND "
        "proposal->>'lead_id' IS NOT DISTINCT FROM lead_id AND "
        "proposal->>'source_document_id' IS NOT DISTINCT FROM source_document_id AND "
        "proposal->>'source_document_sha256' IS NOT DISTINCT FROM source_document_sha256 AND "
        "proposal->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
        "proposal->>'technical_status' = 'UNKNOWN' AND "
        "proposal->>'review_status' = 'PENDING_REVIEW' AND "
        "proposal->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND "
        "(proposal->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at",
        name="ck_server_offer_identity",
    ),
)
Index(
    "ix_server_offer_case",
    server_offer_proposals.c.company_id,
    server_offer_proposals.c.case_id,
    server_offer_proposals.c.case_version,
    server_offer_proposals.c.prepared_at,
    server_offer_proposals.c.offer_id,
)

server_offer_review_decisions = Table(
    "server_offer_review_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("offer_id", Text, nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("requirement_set_id", Text, nullable=False),
    Column("requirement_set_proposal_sha256", String(64), nullable=False),
    Column("requirement_set_decision_sha256", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "offer_id", name="pk_server_offer_review_decisions"),
    UniqueConstraint(
        "company_id",
        "offer_id",
        "proposal_sha256",
        "decision_sha256",
        name="uq_server_offer_review_exact",
    ),
    ForeignKeyConstraint(
        ["company_id", "offer_id", "proposal_sha256"],
        [
            "server_offer_proposals.company_id",
            "server_offer_proposals.offer_id",
            "server_offer_proposals.proposal_sha256",
        ],
        name="fk_server_offer_review_proposal",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "requirement_set_id",
            "requirement_set_proposal_sha256",
            "requirement_set_decision_sha256",
        ],
        [
            "reviewed_requirement_set_decisions.company_id",
            "reviewed_requirement_set_decisions.set_id",
            "reviewed_requirement_set_decisions.proposal_sha256",
            "reviewed_requirement_set_decisions.decision_sha256",
        ],
        name="fk_server_offer_review_requirement_decision",
    ),
    CheckConstraint("status IN ('PASS', 'FAIL', 'UNKNOWN')", name="ck_server_offer_review_status"),
    CheckConstraint("btrim(reviewed_by) <> ''", name="ck_server_offer_review_reviewer"),
    CheckConstraint(
        "proposal_sha256 ~ '^[0-9a-f]{64}$' AND "
        "requirement_set_proposal_sha256 ~ '^[0-9a-f]{64}$' AND "
        "requirement_set_decision_sha256 ~ '^[0-9a-f]{64}$' AND "
        "decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_server_offer_review_digests",
    ),
    CheckConstraint("jsonb_typeof(decision) = 'object'", name="ck_server_offer_review_object"),
    CheckConstraint(
        "decision->>'schema_version' = 'server-offer-review-decision-v1' AND "
        "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "decision->>'offer_id' IS NOT DISTINCT FROM offer_id AND "
        "decision->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
        "decision->>'requirement_set_id' IS NOT DISTINCT FROM requirement_set_id AND "
        "decision->>'requirement_set_proposal_sha256' IS NOT DISTINCT FROM "
        "requirement_set_proposal_sha256 AND "
        "decision->>'requirement_set_decision_sha256' IS NOT DISTINCT FROM "
        "requirement_set_decision_sha256 AND "
        "decision->>'status' IS NOT DISTINCT FROM status AND "
        "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by AND "
        "(decision->>'reviewed_at')::timestamptz IS NOT DISTINCT FROM reviewed_at",
        name="ck_server_offer_review_identity",
    ),
)

server_offer_economics_packages = Table(
    "server_offer_economics_packages",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("economics_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("case_input_sha256", String(64), nullable=False),
    Column("offer_id", Text, nullable=False),
    Column("offer_proposal_sha256", String(64), nullable=False),
    Column("offer_review_decision_sha256", String(64), nullable=False),
    Column("package_sha256", String(64), nullable=False),
    Column("package", JSONB, nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("prepared_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "economics_id", name="pk_server_offer_economics"),
    UniqueConstraint(
        "company_id", "case_id", "case_version", name="uq_server_offer_economics_case"
    ),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_server_offer_economics_case",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "offer_id",
            "offer_proposal_sha256",
            "offer_review_decision_sha256",
        ],
        [
            "server_offer_review_decisions.company_id",
            "server_offer_review_decisions.offer_id",
            "server_offer_review_decisions.proposal_sha256",
            "server_offer_review_decisions.decision_sha256",
        ],
        name="fk_server_offer_economics_review",
    ),
    CheckConstraint("btrim(economics_id) <> ''", name="ck_server_offer_economics_id"),
    CheckConstraint("btrim(prepared_by) <> ''", name="ck_server_offer_economics_preparer"),
    CheckConstraint(
        "case_input_sha256 ~ '^[0-9a-f]{64}$' AND "
        "offer_proposal_sha256 ~ '^[0-9a-f]{64}$' AND "
        "offer_review_decision_sha256 ~ '^[0-9a-f]{64}$' AND "
        "package_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_server_offer_economics_digests",
    ),
    CheckConstraint("jsonb_typeof(package) = 'object'", name="ck_server_offer_economics_object"),
    CheckConstraint(
        "package->>'schema_version' = 'server-offer-economics-package-v1' AND "
        "package->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "package->>'economics_id' IS NOT DISTINCT FROM economics_id AND "
        "package->>'case_id' IS NOT DISTINCT FROM case_id AND "
        "(package->>'case_version')::integer IS NOT DISTINCT FROM case_version AND "
        "package->>'case_input_sha256' IS NOT DISTINCT FROM case_input_sha256 AND "
        "package->>'offer_id' IS NOT DISTINCT FROM offer_id AND "
        "package->>'offer_proposal_sha256' IS NOT DISTINCT FROM offer_proposal_sha256 AND "
        "package->>'offer_review_decision_sha256' IS NOT DISTINCT FROM "
        "offer_review_decision_sha256 AND "
        "package->>'package_sha256' IS NOT DISTINCT FROM package_sha256 AND "
        "package->>'scenario_status' = 'COMPLETE' AND "
        "package->>'recommendation_status' = 'UNKNOWN' AND "
        "package->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND "
        "(package->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at",
        name="ck_server_offer_economics_identity",
    ),
)

document_search_indexes = Table(
    "document_search_indexes",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("search_index_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_document_sha256", String(64), nullable=False),
    Column("entry", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "search_index_id", name="pk_document_search_indexes"),
    ForeignKeyConstraint(
        ["company_id", "source_document_id"],
        ["documents.company_id", "documents.document_id"],
        name="fk_document_search_indexes_source",
    ),
    CheckConstraint("company_id <> ''", name="ck_document_search_company_nonempty"),
    CheckConstraint("search_index_id <> ''", name="ck_document_search_id_nonempty"),
    CheckConstraint(
        "source_document_id <> ''",
        name="ck_document_search_source_nonempty",
    ),
    CheckConstraint(
        "source_document_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_search_source_sha256",
    ),
    CheckConstraint("jsonb_typeof(entry) = 'object'", name="ck_document_search_entry_object"),
    CheckConstraint(
        "entry->>'company_id' = company_id",
        name="ck_document_search_entry_company",
    ),
    CheckConstraint(
        "entry->>'document_id' = source_document_id",
        name="ck_document_search_entry_document",
    ),
    CheckConstraint(
        "entry->>'source_sha256' = source_document_sha256",
        name="ck_document_search_entry_sha256",
    ),
    CheckConstraint(
        "entry->>'extraction_status' IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_document_search_entry_status",
    ),
    CheckConstraint(
        "jsonb_typeof(entry->'extraction_reasons') = 'array'",
        name="ck_document_search_entry_reasons",
    ),
    CheckConstraint(
        "jsonb_typeof(entry->'native_blocks') = 'array'",
        name="ck_document_search_entry_blocks",
    ),
)
Index(
    "ix_document_search_company_source_created",
    document_search_indexes.c.company_id,
    document_search_indexes.c.source_document_id,
    document_search_indexes.c.created_at,
    document_search_indexes.c.search_index_id,
)
Index(
    "ix_document_search_company_created",
    document_search_indexes.c.company_id,
    document_search_indexes.c.created_at,
)

model_brand_catalogs = Table(
    "model_brand_catalogs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("catalog_id", Text, nullable=False),
    Column("catalog", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "catalog_id", name="pk_model_brand_catalogs"),
    CheckConstraint("company_id <> ''", name="ck_model_brand_company_nonempty"),
    CheckConstraint("catalog_id <> ''", name="ck_model_brand_catalog_id_nonempty"),
    CheckConstraint("jsonb_typeof(catalog) = 'object'", name="ck_model_brand_object"),
    CheckConstraint(
        "catalog->>'schema_version' = 'model-brand-catalog-v1'",
        name="ck_model_brand_schema_version",
    ),
    CheckConstraint(
        "catalog->>'company_id' = company_id",
        name="ck_model_brand_catalog_company",
    ),
    CheckConstraint(
        "catalog->>'catalog_id' = catalog_id",
        name="ck_model_brand_catalog_identity",
    ),
    CheckConstraint(
        "jsonb_typeof(catalog->'entries') = 'array'",
        name="ck_model_brand_entries_array",
    ),
)
Index(
    "ix_model_brand_company_created",
    model_brand_catalogs.c.company_id,
    model_brand_catalogs.c.created_at,
    model_brand_catalogs.c.catalog_id,
)

model_brand_source_artifacts = Table(
    "model_brand_source_artifacts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("artifact_id", Text, nullable=False),
    Column("source_title", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint(
        "company_id",
        "artifact_id",
        name="pk_model_brand_source_artifacts",
    ),
    CheckConstraint("company_id <> ''", name="ck_model_brand_artifact_company_nonempty"),
    CheckConstraint("artifact_id <> ''", name="ck_model_brand_artifact_id_nonempty"),
    CheckConstraint("source_title <> ''", name="ck_model_brand_artifact_title_nonempty"),
    CheckConstraint(
        "source_url ~ '^https://'",
        name="ck_model_brand_artifact_url_https",
    ),
    CheckConstraint(
        "original_filename <> ''",
        name="ck_model_brand_artifact_filename_nonempty",
    ),
    CheckConstraint(
        "media_type = 'application/pdf'",
        name="ck_model_brand_artifact_media_type_pdf",
    ),
    CheckConstraint(
        f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
        name="ck_model_brand_artifact_byte_size",
    ),
    CheckConstraint(
        "octet_length(content) = byte_size",
        name="ck_model_brand_artifact_content_size",
    ),
    CheckConstraint(
        "sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_model_brand_artifact_sha256",
    ),
)
Index(
    "ix_model_brand_artifact_company_sha256",
    model_brand_source_artifacts.c.company_id,
    model_brand_source_artifacts.c.sha256,
)

model_brand_review_proposals = Table(
    "model_brand_review_proposals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("catalog_id", Text, nullable=False),
    Column("proposal", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "proposal_id", name="pk_model_brand_review_proposals"),
    CheckConstraint("company_id <> ''", name="ck_model_brand_review_company_nonempty"),
    CheckConstraint("proposal_id <> ''", name="ck_model_brand_review_id_nonempty"),
    CheckConstraint("catalog_id <> ''", name="ck_model_brand_review_catalog_nonempty"),
    CheckConstraint("jsonb_typeof(proposal) = 'object'", name="ck_model_brand_review_object"),
    CheckConstraint(
        "proposal->>'schema_version' = 'model-brand-review-proposal-v1'",
        name="ck_model_brand_review_schema",
    ),
    CheckConstraint(
        "proposal->>'company_id' = company_id AND proposal->>'proposal_id' = proposal_id",
        name="ck_model_brand_review_identity",
    ),
    CheckConstraint(
        "proposal->>'catalog_id' = catalog_id",
        name="ck_model_brand_review_catalog_identity",
    ),
)
Index(
    "ix_model_brand_review_company_created",
    model_brand_review_proposals.c.company_id,
    model_brand_review_proposals.c.created_at,
    model_brand_review_proposals.c.proposal_id,
)

model_brand_review_decisions = Table(
    "model_brand_review_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("decided_by", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("catalog_id", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "proposal_id", name="pk_model_brand_review_decisions"),
    ForeignKeyConstraint(
        ["company_id", "proposal_id"],
        ["model_brand_review_proposals.company_id", "model_brand_review_proposals.proposal_id"],
        name="fk_model_brand_review_decision_proposal",
    ),
    CheckConstraint(
        "status IN ('APPROVED', 'REJECTED')",
        name="ck_model_brand_review_decision_status",
    ),
    CheckConstraint("decided_by <> ''", name="ck_model_brand_review_decider_nonempty"),
    CheckConstraint("reason <> ''", name="ck_model_brand_review_reason_nonempty"),
    CheckConstraint(
        "(status = 'APPROVED' AND catalog_id IS NOT NULL) OR "
        "(status = 'REJECTED' AND catalog_id IS NULL)",
        name="ck_model_brand_review_decision_catalog",
    ),
)

document_completeness_reviews = Table(
    "document_completeness_reviews",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("review_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_document_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    Column("snapshot", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "review_id", name="pk_document_completeness_reviews"),
    UniqueConstraint(
        "company_id",
        "review_id",
        "evidence_sha256",
        name="uq_completeness_review_evidence_binding",
    ),
    ForeignKeyConstraint(
        ["company_id", "source_document_id"],
        ["documents.company_id", "documents.document_id"],
        name="fk_completeness_review_source_document",
    ),
    CheckConstraint("company_id <> ''", name="ck_completeness_review_company_nonempty"),
    CheckConstraint("review_id <> ''", name="ck_completeness_review_id_nonempty"),
    CheckConstraint(
        "source_document_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_completeness_review_source_sha256",
    ),
    CheckConstraint(
        "evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_completeness_review_evidence_sha256",
    ),
    CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_completeness_review_snapshot"),
    CheckConstraint(
        "snapshot->>'schema_version' = 'document-completeness-review-v1'",
        name="ck_completeness_review_schema",
    ),
    CheckConstraint(
        "snapshot->>'company_id' = company_id AND snapshot->>'review_id' = review_id",
        name="ck_completeness_review_identity",
    ),
    CheckConstraint(
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_document_sha256' = source_document_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256",
        name="ck_completeness_review_source_identity",
    ),
)
Index(
    "ix_completeness_review_company_created",
    document_completeness_reviews.c.company_id,
    document_completeness_reviews.c.created_at,
    document_completeness_reviews.c.review_id,
)

document_completeness_review_decisions = Table(
    "document_completeness_review_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("review_id", Text, nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("decided_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "review_id", name="pk_document_completeness_review_decisions"
    ),
    ForeignKeyConstraint(
        ["company_id", "review_id", "evidence_sha256"],
        [
            "document_completeness_reviews.company_id",
            "document_completeness_reviews.review_id",
            "document_completeness_reviews.evidence_sha256",
        ],
        name="fk_completeness_decision_review",
    ),
    CheckConstraint(
        "evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_completeness_decision_evidence_sha256",
    ),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_completeness_decision_status",
    ),
    CheckConstraint("decided_by <> ''", name="ck_completeness_decider_nonempty"),
    CheckConstraint("jsonb_typeof(decision) = 'object'", name="ck_completeness_decision_object"),
    CheckConstraint(
        "decision->>'schema_version' = 'document-completeness-decision-v1' AND "
        "decision->>'company_id' = company_id AND decision->>'review_id' = review_id AND "
        "decision->>'evidence_sha256' = evidence_sha256 AND decision->>'status' = status",
        name="ck_completeness_decision_identity",
    ),
)

document_set_evidence_manifests = Table(
    "document_set_evidence_manifests",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("manifest_id", Text, nullable=False),
    Column("scope", Text, nullable=False),
    Column("member_count", Integer, nullable=False),
    Column("completeness_status", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    Column("manifest", JSONB, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "manifest_id", name="pk_document_set_evidence_manifests"),
    UniqueConstraint(
        "company_id",
        "manifest_id",
        "evidence_sha256",
        name="uq_document_set_evidence_binding",
    ),
    CheckConstraint("company_id <> ''", name="ck_document_set_company_nonempty"),
    CheckConstraint("manifest_id <> ''", name="ck_document_set_id_nonempty"),
    CheckConstraint("scope <> ''", name="ck_document_set_scope_nonempty"),
    CheckConstraint("member_count BETWEEN 2 AND 10", name="ck_document_set_member_count"),
    CheckConstraint(
        "completeness_status = 'UNKNOWN'",
        name="ck_document_set_status_unknown",
    ),
    CheckConstraint(
        "reason = 'MULTI_DOCUMENT_REVIEW_REQUIRED'",
        name="ck_document_set_reason_review_required",
    ),
    CheckConstraint(
        "evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_evidence_sha256",
    ),
    CheckConstraint("created_by <> ''", name="ck_document_set_creator_nonempty"),
    CheckConstraint("jsonb_typeof(manifest) = 'object'", name="ck_document_set_manifest_object"),
    CheckConstraint(
        "manifest->>'schema_version' IS NOT DISTINCT FROM "
        "'document-set-evidence-manifest-v1' AND "
        "manifest->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "manifest->>'manifest_id' IS NOT DISTINCT FROM manifest_id AND "
        "manifest->>'scope' IS NOT DISTINCT FROM scope AND "
        "manifest->>'completeness_status' IS NOT DISTINCT FROM completeness_status AND "
        "manifest->>'reason' IS NOT DISTINCT FROM reason AND "
        "manifest->>'evidence_sha256' IS NOT DISTINCT FROM evidence_sha256 AND "
        "manifest->>'created_by' IS NOT DISTINCT FROM created_by AND "
        "(manifest->>'created_at')::timestamptz IS NOT DISTINCT FROM created_at AND "
        "jsonb_typeof(manifest->'members') = 'array' AND "
        "jsonb_array_length(manifest->'members') = member_count",
        name="ck_document_set_manifest_identity",
    ),
)
Index(
    "ix_document_set_evidence_company_created",
    document_set_evidence_manifests.c.company_id,
    document_set_evidence_manifests.c.created_at,
    document_set_evidence_manifests.c.manifest_id,
)

document_set_evidence_members = Table(
    "document_set_evidence_members",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("manifest_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_document_sha256", String(64), nullable=False),
    Column("completeness_review_id", Text, nullable=False),
    Column("completeness_review_evidence_sha256", String(64), nullable=False),
    Column("mapper_version", Text, nullable=False),
    Column("mapper_min_confidence", Float, nullable=False),
    Column("member", JSONB, nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "manifest_id",
        "ordinal",
        name="pk_document_set_evidence_members",
    ),
    UniqueConstraint(
        "company_id",
        "manifest_id",
        "source_document_id",
        name="uq_document_set_source_document",
    ),
    UniqueConstraint(
        "company_id",
        "manifest_id",
        "completeness_review_id",
        name="uq_document_set_review",
    ),
    ForeignKeyConstraint(
        ["company_id", "manifest_id"],
        [
            "document_set_evidence_manifests.company_id",
            "document_set_evidence_manifests.manifest_id",
        ],
        name="fk_document_set_member_manifest",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "completeness_review_id",
            "completeness_review_evidence_sha256",
        ],
        [
            "document_completeness_reviews.company_id",
            "document_completeness_reviews.review_id",
            "document_completeness_reviews.evidence_sha256",
        ],
        name="fk_document_set_member_review",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_document_set_member_ordinal"),
    CheckConstraint(
        "source_document_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_member_source_sha256",
    ),
    CheckConstraint(
        "completeness_review_evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_member_review_sha256",
    ),
    CheckConstraint(
        "mapper_min_confidence BETWEEN 0 AND 1",
        name="ck_document_set_member_confidence",
    ),
    CheckConstraint("jsonb_typeof(member) = 'object'", name="ck_document_set_member_object"),
    CheckConstraint(
        "(member->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND "
        "member->>'source_document_id' IS NOT DISTINCT FROM source_document_id AND "
        "member->>'source_document_sha256' IS NOT DISTINCT FROM source_document_sha256 AND "
        "member->>'completeness_review_id' IS NOT DISTINCT FROM completeness_review_id AND "
        "member->>'completeness_review_evidence_sha256' IS NOT DISTINCT FROM "
        "completeness_review_evidence_sha256 AND "
        "member->>'mapper_version' IS NOT DISTINCT FROM mapper_version AND "
        "(member->>'mapper_min_confidence')::double precision IS NOT DISTINCT FROM "
        "mapper_min_confidence",
        name="ck_document_set_member_identity",
    ),
)

document_set_completeness_decisions = Table(
    "document_set_completeness_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("manifest_id", Text, nullable=False),
    Column("manifest_evidence_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("decided_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "manifest_id",
        name="pk_document_set_completeness_decisions",
    ),
    ForeignKeyConstraint(
        ["company_id", "manifest_id", "manifest_evidence_sha256"],
        [
            "document_set_evidence_manifests.company_id",
            "document_set_evidence_manifests.manifest_id",
            "document_set_evidence_manifests.evidence_sha256",
        ],
        name="fk_document_set_decision_manifest",
    ),
    CheckConstraint(
        "manifest_evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_decision_manifest_sha256",
    ),
    CheckConstraint(
        "decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_decision_sha256",
    ),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_document_set_decision_status",
    ),
    CheckConstraint("decided_by <> ''", name="ck_document_set_decider_nonempty"),
    CheckConstraint(
        "jsonb_typeof(decision) = 'object' AND jsonb_typeof(decision->'members') = 'array'",
        name="ck_document_set_decision_object",
    ),
    CheckConstraint(
        "decision->>'schema_version' IS NOT DISTINCT FROM "
        "'document-set-completeness-decision-v1' AND "
        "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "decision->>'manifest_id' IS NOT DISTINCT FROM manifest_id AND "
        "decision->>'manifest_evidence_sha256' IS NOT DISTINCT FROM "
        "manifest_evidence_sha256 AND "
        "decision->>'status' IS NOT DISTINCT FROM status AND "
        "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "decision->>'decided_by' IS NOT DISTINCT FROM decided_by AND "
        "(decision->>'decided_at')::timestamptz IS NOT DISTINCT FROM created_at",
        name="ck_document_set_decision_identity",
    ),
)

document_set_completeness_member_attestations = Table(
    "document_set_completeness_member_attestations",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("manifest_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("review_id", Text, nullable=False),
    Column("review_evidence_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("assessment", Text, nullable=False),
    Column("attestation", JSONB, nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "manifest_id",
        "ordinal",
        name="pk_document_set_member_attestations",
    ),
    ForeignKeyConstraint(
        ["company_id", "manifest_id"],
        [
            "document_set_completeness_decisions.company_id",
            "document_set_completeness_decisions.manifest_id",
        ],
        name="fk_document_set_attestation_decision",
    ),
    ForeignKeyConstraint(
        ["company_id", "manifest_id", "ordinal"],
        [
            "document_set_evidence_members.company_id",
            "document_set_evidence_members.manifest_id",
            "document_set_evidence_members.ordinal",
        ],
        name="fk_document_set_attestation_member",
    ),
    ForeignKeyConstraint(
        ["company_id", "review_id"],
        [
            "document_completeness_review_decisions.company_id",
            "document_completeness_review_decisions.review_id",
        ],
        name="fk_document_set_attestation_review_decision",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_document_set_attestation_ordinal"),
    CheckConstraint(
        "review_evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_attestation_review_sha256",
    ),
    CheckConstraint(
        "decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_document_set_attestation_decision_sha256",
    ),
    CheckConstraint(
        "assessment IN ('REVIEWED_IN_SCOPE', 'UNRESOLVED')",
        name="ck_document_set_attestation_assessment",
    ),
    CheckConstraint(
        "jsonb_typeof(attestation) = 'object'",
        name="ck_document_set_attestation_object",
    ),
    CheckConstraint(
        "(attestation->'reference'->>'member_ordinal')::integer "
        "IS NOT DISTINCT FROM ordinal AND "
        "attestation->'reference'->>'review_id' IS NOT DISTINCT FROM review_id AND "
        "attestation->'reference'->>'review_evidence_sha256' IS NOT DISTINCT FROM "
        "review_evidence_sha256 AND "
        "attestation->'reference'->>'decision_sha256' IS NOT DISTINCT FROM "
        "decision_sha256 AND "
        "attestation->>'assessment' IS NOT DISTINCT FROM assessment",
        name="ck_document_set_attestation_identity",
    ),
)

case_document_evidence_bindings = Table(
    "case_document_evidence_bindings",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("binding_id", Text, nullable=False),
    Column("manifest_id", Text, nullable=False),
    Column("manifest_evidence_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("binding_sha256", String(64), nullable=False),
    Column("binding", JSONB, nullable=False),
    Column("bound_by", Text, nullable=False),
    Column("bound_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "binding_id",
        name="pk_case_document_evidence_bindings",
    ),
    ForeignKeyConstraint(
        ["company_id", "manifest_id", "manifest_evidence_sha256"],
        [
            "document_set_evidence_manifests.company_id",
            "document_set_evidence_manifests.manifest_id",
            "document_set_evidence_manifests.evidence_sha256",
        ],
        name="fk_case_evidence_binding_manifest",
    ),
    ForeignKeyConstraint(
        ["company_id", "manifest_id"],
        [
            "document_set_completeness_decisions.company_id",
            "document_set_completeness_decisions.manifest_id",
        ],
        name="fk_case_evidence_binding_decision",
    ),
    CheckConstraint("company_id <> ''", name="ck_case_evidence_company_nonempty"),
    CheckConstraint("binding_id <> ''", name="ck_case_evidence_binding_nonempty"),
    CheckConstraint("manifest_id <> ''", name="ck_case_evidence_manifest_nonempty"),
    CheckConstraint(
        "manifest_evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_case_evidence_manifest_sha256",
    ),
    CheckConstraint(
        "decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_case_evidence_decision_sha256",
    ),
    CheckConstraint(
        "binding_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_case_evidence_binding_sha256",
    ),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_case_evidence_status",
    ),
    CheckConstraint("bound_by <> ''", name="ck_case_evidence_binder_nonempty"),
    CheckConstraint(
        "jsonb_typeof(binding) = 'object'",
        name="ck_case_evidence_binding_object",
    ),
    CheckConstraint(
        "binding->>'schema_version' IS NOT DISTINCT FROM "
        "'case-document-evidence-binding-v1' AND "
        "binding->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "binding->>'binding_id' IS NOT DISTINCT FROM binding_id AND "
        "binding->>'manifest_id' IS NOT DISTINCT FROM manifest_id AND "
        "binding->>'manifest_evidence_sha256' IS NOT DISTINCT FROM "
        "manifest_evidence_sha256 AND "
        "binding->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "binding->>'status' IS NOT DISTINCT FROM status AND "
        "binding->>'bound_by' IS NOT DISTINCT FROM bound_by AND "
        "(binding->>'bound_at')::timestamptz IS NOT DISTINCT FROM bound_at AND "
        "binding->>'binding_sha256' IS NOT DISTINCT FROM binding_sha256 AND "
        "created_at IS NOT DISTINCT FROM bound_at",
        name="ck_case_evidence_binding_identity",
    ),
    Index(
        "ix_case_evidence_company_created",
        "company_id",
        "created_at",
        "binding_id",
    ),
)

document_ai_requirement_runs = Table(
    "document_ai_requirement_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    Column("snapshot", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_document_ai_requirement_runs"),
    UniqueConstraint(
        "company_id",
        "run_id",
        "evidence_sha256",
        name="uq_ai_requirement_run_evidence_binding",
    ),
    ForeignKeyConstraint(
        ["company_id", "source_document_id"],
        ["documents.company_id", "documents.document_id"],
        name="fk_ai_requirement_run_source_document",
    ),
    CheckConstraint("company_id <> ''", name="ck_ai_requirement_run_company_nonempty"),
    CheckConstraint("run_id <> ''", name="ck_ai_requirement_run_id_nonempty"),
    CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ai_requirement_run_source_sha256"),
    CheckConstraint(
        "evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_requirement_run_evidence_sha256",
    ),
    CheckConstraint(
        "(jsonb_typeof(snapshot) = 'object' AND ("
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','report',"
        "'completeness_status','submitted_by','submitted_at','evidence_sha256'] AND "
        "snapshot - ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','report',"
        "'completeness_status','submitted_by','submitted_at','evidence_sha256'] = '{}'::jsonb) OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','result',"
        "'completeness_status','prepared_by','materialized_by','materialized_at',"
        "'evidence_sha256'] AND snapshot - ARRAY['schema_version','origin',"
        "'company_id','run_id','source_document_id','source_sha256','extraction',"
        "'result','completeness_status','prepared_by','materialized_by',"
        "'materialized_at','evidence_sha256'] = '{}'::jsonb) OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3' AND "
        "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','result',"
        "'completeness_status','prepared_by','aggregated_by','aggregated_at',"
        "'evidence_sha256'] AND snapshot - ARRAY['schema_version','origin',"
        "'company_id','run_id','source_document_id','source_sha256','extraction',"
        "'result','completeness_status','prepared_by','aggregated_by',"
        "'aggregated_at','evidence_sha256'] = '{}'::jsonb))) IS TRUE",
        name="ck_ai_requirement_run_snapshot_shape",
    ),
    CheckConstraint(
        "(((snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "snapshot->>'origin' = 'IMPORTED_REPORT' AND "
        "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "snapshot->>'origin' = 'SERVER_MANAGED_TRANSFER' AND "
        "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN' AND "
        "snapshot->>'prepared_by' = snapshot->'result'->>'prepared_by' AND "
        "snapshot->>'materialized_by' = snapshot->'result'->>'materialized_by' AND "
        "(snapshot->>'materialized_at')::timestamptz IS NOT DISTINCT FROM "
        "(snapshot->'result'->>'materialized_at')::timestamptz)) OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3' AND "
        "snapshot->>'origin' = 'SERVER_MANAGED_TRANSFER_BATCH' AND "
        "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN' AND "
        "snapshot->>'prepared_by' = snapshot->'result'->>'prepared_by' AND "
        "snapshot->>'aggregated_by' = snapshot->'result'->>'aggregated_by' AND "
        "(snapshot->>'aggregated_at')::timestamptz IS NOT DISTINCT FROM "
        "(snapshot->'result'->>'aggregated_at')::timestamptz))) IS TRUE",
        name="ck_ai_requirement_run_snapshot_identity",
    ),
    CheckConstraint(
        "((snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND "
        "jsonb_typeof(snapshot->'report') = 'object') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND "
        "jsonb_typeof(snapshot->'result') = 'object' AND "
        "snapshot->'result'->>'company_id' = company_id AND "
        "btrim(coalesce(snapshot->'result'->>'result_id', '')) <> '') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND "
        "jsonb_typeof(snapshot->'result') = 'object' AND "
        "snapshot->'result'->>'company_id' = company_id AND "
        "btrim(coalesce(snapshot->'result'->>'batch_result_id', '')) <> '')) IS TRUE",
        name="ck_ai_requirement_run_payload_objects",
    ),
)
Index(
    "ix_ai_requirement_run_company_created",
    document_ai_requirement_runs.c.company_id,
    document_ai_requirement_runs.c.created_at,
    document_ai_requirement_runs.c.run_id,
)

ai_transfer_requirement_materializations = Table(
    "ai_transfer_requirement_materializations",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("materialization_id", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("raw_response_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("claim_payload_sha256", String(64), nullable=False),
    Column("receipt_payload_sha256", String(64), nullable=False),
    Column("raw_metadata_sha256", String(64), nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("result_id", Text, nullable=True),
    Column("result_payload_sha256", String(64), nullable=True),
    Column("run_id", Text, nullable=True),
    Column("run_evidence_sha256", String(64), nullable=True),
    Column("materialized_by", Text, nullable=False),
    Column("materialized_at", DateTime(timezone=True), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("materialization", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "materialization_id",
        name="pk_ai_transfer_requirement_materializations",
    ),
    UniqueConstraint(
        "company_id",
        "execution_id",
        "parser_version",
        name="uq_ai_transfer_requirement_materialization_execution_parser",
    ),
    UniqueConstraint(
        "company_id",
        "result_id",
        name="uq_ai_transfer_requirement_materialization_result",
    ),
    UniqueConstraint(
        "company_id",
        "raw_response_id",
        "parser_version",
        name="uq_ai_transfer_requirement_materialization_raw",
    ),
    UniqueConstraint(
        "company_id",
        "receipt_id",
        "parser_version",
        name="uq_ai_transfer_requirement_materialization_receipt",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "claim_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_claims.company_id",
            "ai_transfer_dispatch_claims.execution_id",
            "ai_transfer_dispatch_claims.transfer_id",
            "ai_transfer_dispatch_claims.ordinal",
            "ai_transfer_dispatch_claims.claim_id",
            "ai_transfer_dispatch_claims.payload_sha256",
        ],
        name="fk_ai_transfer_materialization_exact_claim",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "receipt_id",
            "receipt_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_receipts.company_id",
            "ai_transfer_dispatch_receipts.execution_id",
            "ai_transfer_dispatch_receipts.transfer_id",
            "ai_transfer_dispatch_receipts.ordinal",
            "ai_transfer_dispatch_receipts.claim_id",
            "ai_transfer_dispatch_receipts.receipt_id",
            "ai_transfer_dispatch_receipts.payload_sha256",
        ],
        name="fk_ai_transfer_materialization_exact_receipt",
    ),
    ForeignKeyConstraint(
        ["company_id", "raw_response_id", "receipt_id", "raw_metadata_sha256"],
        [
            "ai_transfer_raw_responses.company_id",
            "ai_transfer_raw_responses.raw_response_id",
            "ai_transfer_raw_responses.receipt_id",
            "ai_transfer_raw_responses.metadata_sha256",
        ],
        name="fk_ai_transfer_materialization_exact_raw",
    ),
    ForeignKeyConstraint(
        ["company_id", "run_id", "run_evidence_sha256"],
        [
            "document_ai_requirement_runs.company_id",
            "document_ai_requirement_runs.run_id",
            "document_ai_requirement_runs.evidence_sha256",
        ],
        name="fk_ai_transfer_materialization_exact_run",
    ),
    CheckConstraint("ordinal = 1", name="ck_ai_transfer_materialization_first_ordinal"),
    CheckConstraint(
        "parser_version = 'ai-transfer-requirement-parser-v1'",
        name="ck_ai_transfer_materialization_schema",
    ),
    CheckConstraint(
        "status IN ('MATERIALIZED', 'REJECTED') AND "
        "reason IN ('MATERIALIZED', 'UNSUPPORTED_MULTI_CHUNK', 'INVALID_CANDIDATE_EVIDENCE')",
        name="ck_ai_transfer_materialization_status",
    ),
    CheckConstraint(
        "((status = 'MATERIALIZED' AND reason = 'MATERIALIZED' AND "
        "result_id IS NOT NULL AND result_payload_sha256 IS NOT NULL AND "
        "run_id IS NOT NULL AND run_evidence_sha256 IS NOT NULL) OR "
        "(status = 'REJECTED' AND reason <> 'MATERIALIZED' AND "
        "result_id IS NULL AND result_payload_sha256 IS NULL AND "
        "run_id IS NULL AND run_evidence_sha256 IS NULL)) IS TRUE",
        name="ck_ai_transfer_materialization_outputs",
    ),
    CheckConstraint(
        "btrim(materialization_id) <> '' AND materialization_id !~ '[[:cntrl:]]' AND "
        "btrim(transfer_id) <> '' AND transfer_id !~ '[[:cntrl:]]' AND "
        "btrim(execution_id) <> '' AND execution_id !~ '[[:cntrl:]]' AND "
        "btrim(claim_id) <> '' AND claim_id !~ '[[:cntrl:]]' AND "
        "btrim(receipt_id) <> '' AND receipt_id !~ '[[:cntrl:]]' AND "
        "btrim(raw_response_id) <> '' AND raw_response_id !~ '[[:cntrl:]]' AND "
        "btrim(materialized_by) <> '' AND materialized_by !~ '[[:cntrl:]]' AND "
        "(result_id IS NULL OR (btrim(result_id) <> '' AND result_id !~ '[[:cntrl:]]')) AND "
        "(run_id IS NULL OR (btrim(run_id) <> '' AND run_id !~ '[[:cntrl:]]'))",
        name="ck_ai_transfer_materialization_safe_text",
    ),
    CheckConstraint(
        "request_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "claim_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "receipt_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "raw_metadata_sha256 ~ '^[0-9a-f]{64}$' AND "
        "payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "(result_payload_sha256 IS NULL OR result_payload_sha256 ~ '^[0-9a-f]{64}$') AND "
        "(run_evidence_sha256 IS NULL OR run_evidence_sha256 ~ '^[0-9a-f]{64}$')",
        name="ck_ai_transfer_materialization_digests",
    ),
    CheckConstraint(
        "(jsonb_typeof(materialization) = 'object' AND materialization ?& ARRAY["
        "'schema_version','company_id','materialization_id','transfer_id','execution_id',"
        "'ordinal','claim_id','receipt_id','raw_response_id','request_payload_sha256',"
        "'claim_payload_sha256','receipt_payload_sha256','raw_metadata_sha256',"
        "'parser_version','status','reason','result_id','result_payload_sha256','run_id',"
        "'run_evidence_sha256','materialized_by','materialized_at','payload_sha256'] AND "
        "materialization - ARRAY['schema_version','company_id','materialization_id',"
        "'transfer_id','execution_id','ordinal','claim_id','receipt_id','raw_response_id',"
        "'request_payload_sha256','claim_payload_sha256','receipt_payload_sha256',"
        "'raw_metadata_sha256','parser_version','status','reason','result_id',"
        "'result_payload_sha256','run_id','run_evidence_sha256','materialized_by',"
        "'materialized_at','payload_sha256'] = '{}'::jsonb AND "
        "materialization->>'schema_version' IS NOT DISTINCT FROM "
        "'ai-transfer-requirement-materialization-v1' AND "
        "materialization->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "materialization->>'materialization_id' IS NOT DISTINCT FROM materialization_id AND "
        "materialization->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND "
        "materialization->>'execution_id' IS NOT DISTINCT FROM execution_id AND "
        "(materialization->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND "
        "materialization->>'claim_id' IS NOT DISTINCT FROM claim_id AND "
        "materialization->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND "
        "materialization->>'raw_response_id' IS NOT DISTINCT FROM raw_response_id AND "
        "materialization->>'request_payload_sha256' IS NOT DISTINCT FROM "
        "request_payload_sha256 AND "
        "materialization->>'claim_payload_sha256' IS NOT DISTINCT FROM "
        "claim_payload_sha256 AND "
        "materialization->>'receipt_payload_sha256' IS NOT DISTINCT FROM "
        "receipt_payload_sha256 AND "
        "materialization->>'raw_metadata_sha256' IS NOT DISTINCT FROM raw_metadata_sha256 AND "
        "materialization->>'parser_version' IS NOT DISTINCT FROM parser_version AND "
        "materialization->>'status' IS NOT DISTINCT FROM status AND "
        "materialization->>'reason' IS NOT DISTINCT FROM reason AND "
        "materialization->>'result_id' IS NOT DISTINCT FROM result_id AND "
        "materialization->>'result_payload_sha256' IS NOT DISTINCT FROM result_payload_sha256 AND "
        "materialization->>'run_id' IS NOT DISTINCT FROM run_id AND "
        "materialization->>'run_evidence_sha256' IS NOT DISTINCT FROM run_evidence_sha256 AND "
        "materialization->>'materialized_by' IS NOT DISTINCT FROM materialized_by AND "
        "(materialization->>'materialized_at')::timestamptz IS NOT DISTINCT FROM "
        "materialized_at AND "
        "materialization->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256 AND "
        "created_at IS NOT DISTINCT FROM materialized_at) IS TRUE",
        name="ck_ai_transfer_materialization_identity",
    ),
)

ai_transfer_requirement_chunk_results = Table(
    "ai_transfer_requirement_chunk_results",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("result_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("claim_payload_sha256", String(64), nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("receipt_payload_sha256", String(64), nullable=False),
    Column("raw_response_id", Text, nullable=False),
    Column("raw_metadata_sha256", String(64), nullable=False),
    Column("result_payload_sha256", String(64), nullable=False),
    Column("result", JSONB, nullable=False),
    Column("materialized_by", Text, nullable=False),
    Column("materialized_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "execution_id",
        "ordinal",
        "parser_version",
        name="pk_ai_transfer_requirement_chunk_results",
    ),
    UniqueConstraint("company_id", "result_id", name="uq_ai_transfer_requirement_chunk_result_id"),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "claim_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_claims.company_id",
            "ai_transfer_dispatch_claims.execution_id",
            "ai_transfer_dispatch_claims.transfer_id",
            "ai_transfer_dispatch_claims.ordinal",
            "ai_transfer_dispatch_claims.claim_id",
            "ai_transfer_dispatch_claims.payload_sha256",
        ],
        name="fk_ai_transfer_chunk_result_exact_claim",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "receipt_id",
            "receipt_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_receipts.company_id",
            "ai_transfer_dispatch_receipts.execution_id",
            "ai_transfer_dispatch_receipts.transfer_id",
            "ai_transfer_dispatch_receipts.ordinal",
            "ai_transfer_dispatch_receipts.claim_id",
            "ai_transfer_dispatch_receipts.receipt_id",
            "ai_transfer_dispatch_receipts.payload_sha256",
        ],
        name="fk_ai_transfer_chunk_result_exact_receipt",
    ),
    ForeignKeyConstraint(
        ["company_id", "raw_response_id", "receipt_id", "raw_metadata_sha256"],
        [
            "ai_transfer_raw_responses.company_id",
            "ai_transfer_raw_responses.raw_response_id",
            "ai_transfer_raw_responses.receipt_id",
            "ai_transfer_raw_responses.metadata_sha256",
        ],
        name="fk_ai_transfer_chunk_result_exact_raw",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_chunk_result_ordinal"),
    CheckConstraint(
        "parser_version = 'ai-transfer-requirement-parser-v1'",
        name="ck_ai_transfer_chunk_result_parser",
    ),
    CheckConstraint(
        "result_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "result->>'payload_sha256' = result_payload_sha256 AND "
        "result->>'company_id' = company_id AND "
        "result->>'execution_id' = execution_id AND "
        "(result->>'ordinal')::integer = ordinal AND "
        "result->>'transfer_id' = transfer_id AND result->>'result_id' = result_id AND "
        "result->>'claim_id' = claim_id AND result->>'receipt_id' = receipt_id AND "
        "result->>'raw_response_id' = raw_response_id AND "
        "result->>'request_payload_sha256' = request_payload_sha256 AND "
        "result->>'claim_payload_sha256' = claim_payload_sha256 AND "
        "result->>'receipt_payload_sha256' = receipt_payload_sha256 AND "
        "result->>'raw_metadata_sha256' = raw_metadata_sha256 AND "
        "result->>'materialized_by' = materialized_by AND "
        "(result->>'materialized_at')::timestamptz IS NOT DISTINCT FROM materialized_at AND "
        "created_at IS NOT DISTINCT FROM materialized_at",
        name="ck_ai_transfer_chunk_result_identity",
    ),
)

ai_transfer_requirement_chunk_rejections = Table(
    "ai_transfer_requirement_chunk_rejections",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("rejection_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("claim_payload_sha256", String(64), nullable=False),
    Column("receipt_id", Text, nullable=False),
    Column("receipt_payload_sha256", String(64), nullable=False),
    Column("raw_response_id", Text, nullable=False),
    Column("raw_metadata_sha256", String(64), nullable=False),
    Column("reason", Text, nullable=False),
    Column("rejection", JSONB, nullable=False),
    Column("rejected_by", Text, nullable=False),
    Column("rejected_at", DateTime(timezone=True), nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "execution_id",
        "ordinal",
        "parser_version",
        name="pk_ai_transfer_requirement_chunk_rejections",
    ),
    UniqueConstraint(
        "company_id", "rejection_id", name="uq_ai_transfer_requirement_chunk_rejection_id"
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "claim_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_claims.company_id",
            "ai_transfer_dispatch_claims.execution_id",
            "ai_transfer_dispatch_claims.transfer_id",
            "ai_transfer_dispatch_claims.ordinal",
            "ai_transfer_dispatch_claims.claim_id",
            "ai_transfer_dispatch_claims.payload_sha256",
        ],
        name="fk_ai_transfer_chunk_rejection_exact_claim",
    ),
    ForeignKeyConstraint(
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "receipt_id",
            "receipt_payload_sha256",
        ],
        [
            "ai_transfer_dispatch_receipts.company_id",
            "ai_transfer_dispatch_receipts.execution_id",
            "ai_transfer_dispatch_receipts.transfer_id",
            "ai_transfer_dispatch_receipts.ordinal",
            "ai_transfer_dispatch_receipts.claim_id",
            "ai_transfer_dispatch_receipts.receipt_id",
            "ai_transfer_dispatch_receipts.payload_sha256",
        ],
        name="fk_ai_transfer_chunk_rejection_exact_receipt",
    ),
    ForeignKeyConstraint(
        ["company_id", "raw_response_id", "receipt_id", "raw_metadata_sha256"],
        [
            "ai_transfer_raw_responses.company_id",
            "ai_transfer_raw_responses.raw_response_id",
            "ai_transfer_raw_responses.receipt_id",
            "ai_transfer_raw_responses.metadata_sha256",
        ],
        name="fk_ai_transfer_chunk_rejection_exact_raw",
    ),
    CheckConstraint("ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_chunk_rejection_ordinal"),
    CheckConstraint(
        "parser_version = 'ai-transfer-requirement-parser-v1'",
        name="ck_ai_transfer_chunk_rejection_parser",
    ),
    CheckConstraint(
        "reason = 'INVALID_CANDIDATE_EVIDENCE' AND "
        "payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "rejection->>'schema_version' = 'ai-transfer-requirement-chunk-rejection-v1' AND "
        "rejection->>'company_id' = company_id AND rejection->>'rejection_id' = rejection_id AND "
        "rejection->>'execution_id' = execution_id AND "
        "(rejection->>'ordinal')::integer = ordinal AND "
        "rejection->>'transfer_id' = transfer_id AND rejection->>'claim_id' = claim_id AND "
        "rejection->>'receipt_id' = receipt_id AND "
        "rejection->>'raw_response_id' = raw_response_id AND "
        "rejection->>'request_payload_sha256' = request_payload_sha256 AND "
        "rejection->>'claim_payload_sha256' = claim_payload_sha256 AND "
        "rejection->>'receipt_payload_sha256' = receipt_payload_sha256 AND "
        "rejection->>'raw_metadata_sha256' = raw_metadata_sha256 AND "
        "rejection->>'parser_version' = parser_version AND rejection->>'reason' = reason AND "
        "rejection->>'rejected_by' = rejected_by AND "
        "(rejection->>'rejected_at')::timestamptz IS NOT DISTINCT FROM rejected_at AND "
        "rejection->>'payload_sha256' = payload_sha256 AND "
        "created_at IS NOT DISTINCT FROM rejected_at",
        name="ck_ai_transfer_chunk_rejection_identity",
    ),
)

ai_transfer_requirement_batch_results = Table(
    "ai_transfer_requirement_batch_results",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("execution_id", Text, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("transfer_id", Text, nullable=False),
    Column("batch_result_id", Text, nullable=False),
    Column("request_payload_sha256", String(64), nullable=False),
    Column("batch_payload_sha256", String(64), nullable=False),
    Column("run_id", Text, nullable=False),
    Column("run_evidence_sha256", String(64), nullable=False),
    Column("result", JSONB, nullable=False),
    Column("aggregated_by", Text, nullable=False),
    Column("aggregated_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id",
        "execution_id",
        "parser_version",
        name="pk_ai_transfer_requirement_batch_results",
    ),
    UniqueConstraint(
        "company_id", "batch_result_id", name="uq_ai_transfer_requirement_batch_result_id"
    ),
    ForeignKeyConstraint(
        ["company_id", "run_id", "run_evidence_sha256"],
        [
            "document_ai_requirement_runs.company_id",
            "document_ai_requirement_runs.run_id",
            "document_ai_requirement_runs.evidence_sha256",
        ],
        name="fk_ai_transfer_batch_result_exact_run",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint(
        "parser_version = 'ai-transfer-requirement-parser-v1'",
        name="ck_ai_transfer_batch_result_parser",
    ),
    CheckConstraint(
        "batch_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "result->>'payload_sha256' = batch_payload_sha256 AND "
        "result->>'company_id' = company_id AND result->>'execution_id' = execution_id AND "
        "result->>'transfer_id' = transfer_id AND "
        "result->>'batch_result_id' = batch_result_id AND "
        "result->>'request_payload_sha256' = request_payload_sha256 AND "
        "result->>'aggregated_by' = aggregated_by AND "
        "(result->>'aggregated_at')::timestamptz IS NOT DISTINCT FROM aggregated_at AND "
        "created_at IS NOT DISTINCT FROM aggregated_at",
        name="ck_ai_transfer_batch_result_identity",
    ),
)

document_ai_requirement_review_decisions = Table(
    "document_ai_requirement_review_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "company_id", "run_id", name="pk_document_ai_requirement_review_decisions"
    ),
    ForeignKeyConstraint(
        ["company_id", "run_id", "evidence_sha256"],
        [
            "document_ai_requirement_runs.company_id",
            "document_ai_requirement_runs.run_id",
            "document_ai_requirement_runs.evidence_sha256",
        ],
        name="fk_ai_requirement_decision_run_evidence",
    ),
    CheckConstraint(
        "evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_ai_requirement_decision_evidence_sha256",
    ),
    CheckConstraint("reviewed_by <> ''", name="ck_ai_requirement_decision_reviewer_nonempty"),
    CheckConstraint(
        "(jsonb_typeof(decision) = 'object' AND "
        "decision ?& ARRAY['schema_version','company_id','run_id','evidence_sha256',"
        "'candidate_decisions','reviewed_by','reviewed_at','completeness_status']) IS TRUE",
        name="ck_ai_requirement_decision_shape",
    ),
    CheckConstraint(
        "(decision->>'schema_version' = 'persisted-ai-requirement-review-v1' AND "
        "decision->>'company_id' = company_id AND decision->>'run_id' = run_id AND "
        "decision->>'evidence_sha256' = evidence_sha256 AND "
        "decision->>'reviewed_by' = reviewed_by AND "
        "decision->>'completeness_status' = 'UNKNOWN' AND "
        "jsonb_typeof(decision->'candidate_decisions') = 'array') IS TRUE",
        name="ck_ai_requirement_decision_identity",
    ),
)

document_bundles = Table(
    "document_bundles",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("bundle_id", Text, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("document_role", Text, nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("result", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "bundle_id", name="pk_document_bundles"),
    CheckConstraint("company_id <> ''", name="ck_document_bundles_company_id_nonempty"),
    CheckConstraint("bundle_id <> ''", name="ck_document_bundles_id_nonempty"),
    CheckConstraint(
        "original_filename <> ''",
        name="ck_document_bundles_original_filename_nonempty",
    ),
    CheckConstraint(
        "media_type IN ('application/zip', 'application/x-zip-compressed')",
        name="ck_document_bundles_media_type_allowed",
    ),
    CheckConstraint(
        "document_role IN ('UNKNOWN', 'TENDER_REQUIREMENTS', 'SUPPLIER_QUOTE')",
        name="ck_document_bundles_role_allowed",
    ),
    CheckConstraint(
        f"byte_size BETWEEN 1 AND {MAX_DOCUMENT_BYTES}",
        name="ck_document_bundles_byte_size",
    ),
    CheckConstraint(
        "octet_length(content) = byte_size",
        name="ck_document_bundles_content_size",
    ),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_bundles_sha256"),
    CheckConstraint(
        "jsonb_typeof(result) = 'object'",
        name="ck_document_bundles_result_object",
    ),
    CheckConstraint(
        "result ? 'source_document_id' AND result->>'source_document_id' = bundle_id",
        name="ck_document_bundles_result_source_id",
    ),
    CheckConstraint(
        "result ? 'source_sha256' AND result->>'source_sha256' = sha256",
        name="ck_document_bundles_result_source_sha256",
    ),
    CheckConstraint(
        "result ? 'status' AND result->>'status' IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_document_bundles_result_status",
    ),
    CheckConstraint(
        "result ? 'members' AND jsonb_typeof(result->'members') = 'array'",
        name="ck_document_bundles_result_members_array",
    ),
)
Index(
    "ix_document_bundles_company_created",
    document_bundles.c.company_id,
    document_bundles.c.created_at,
    document_bundles.c.bundle_id,
)
Index(
    "ix_document_bundles_company_sha256",
    document_bundles.c.company_id,
    document_bundles.c.sha256,
)

document_bundle_member_ocr_derivatives = Table(
    "document_bundle_member_ocr_derivatives",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("ocr_id", Text, nullable=False),
    Column("source_bundle_id", Text, nullable=False),
    Column("member_index", Integer, nullable=False),
    Column("archive_path", Text, nullable=False),
    Column("source_member_sha256", String(64), nullable=False),
    Column("engine", Text, nullable=False),
    Column("threshold", Numeric(3, 2), nullable=False),
    Column("status", Text, nullable=False),
    Column("result", JSONB, nullable=False),
    Column("mean_confidence", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint(
        "company_id",
        "ocr_id",
        name="pk_document_bundle_member_ocr_derivatives",
    ),
    ForeignKeyConstraint(
        ["company_id", "source_bundle_id"],
        ["document_bundles.company_id", "document_bundles.bundle_id"],
        name="fk_bundle_member_ocr_source_bundle",
    ),
    CheckConstraint("company_id <> ''", name="ck_bundle_member_ocr_company_nonempty"),
    CheckConstraint("ocr_id <> ''", name="ck_bundle_member_ocr_id_nonempty"),
    CheckConstraint(
        "source_bundle_id <> ''",
        name="ck_bundle_member_ocr_source_bundle_nonempty",
    ),
    CheckConstraint("member_index >= 0", name="ck_bundle_member_ocr_index_nonnegative"),
    CheckConstraint("archive_path <> ''", name="ck_bundle_member_ocr_path_nonempty"),
    CheckConstraint(
        "char_length(archive_path) <= 512",
        name="ck_bundle_member_ocr_path_length",
    ),
    CheckConstraint(
        "source_member_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_bundle_member_ocr_source_sha256",
    ),
    CheckConstraint("engine <> ''", name="ck_bundle_member_ocr_engine_nonempty"),
    CheckConstraint("threshold BETWEEN 0 AND 1", name="ck_bundle_member_ocr_threshold"),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_bundle_member_ocr_status_allowed",
    ),
    CheckConstraint(
        "jsonb_typeof(result) = 'object'",
        name="ck_bundle_member_ocr_result_object",
    ),
    CheckConstraint(
        "result ? 'source_document_id' AND "
        "result->>'source_document_id' = source_bundle_id || ':member:' || member_index::text",
        name="ck_bundle_member_ocr_result_source_id",
    ),
    CheckConstraint(
        "result ? 'source_sha256' AND result->>'source_sha256' = source_member_sha256",
        name="ck_bundle_member_ocr_result_source_sha256",
    ),
    CheckConstraint(
        "result ? 'engine' AND result->>'engine' = engine",
        name="ck_bundle_member_ocr_result_engine",
    ),
    CheckConstraint(
        "result ? 'status' AND result->>'status' = status",
        name="ck_bundle_member_ocr_result_status",
    ),
    CheckConstraint(
        "mean_confidence IS NULL OR (mean_confidence BETWEEN 0 AND 1)",
        name="ck_bundle_member_ocr_mean_confidence",
    ),
)
Index(
    "ix_bundle_member_ocr_company_source_created",
    document_bundle_member_ocr_derivatives.c.company_id,
    document_bundle_member_ocr_derivatives.c.source_bundle_id,
    document_bundle_member_ocr_derivatives.c.member_index,
    document_bundle_member_ocr_derivatives.c.created_at,
    document_bundle_member_ocr_derivatives.c.ocr_id,
)
Index(
    "ix_bundle_member_ocr_company_created",
    document_bundle_member_ocr_derivatives.c.company_id,
    document_bundle_member_ocr_derivatives.c.created_at,
)

document_docx_media_ocr_derivatives = Table(
    "document_docx_media_ocr_derivatives",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("ocr_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("media_index", Integer, nullable=False),
    Column("archive_path", Text, nullable=False),
    Column("source_document_sha256", String(64), nullable=False),
    Column("source_media_sha256", String(64), nullable=False),
    Column("media_type", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("threshold", Numeric(3, 2), nullable=False),
    Column("status", Text, nullable=False),
    Column("result", JSONB, nullable=False),
    Column("mean_confidence", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint(
        "company_id",
        "ocr_id",
        name="pk_document_docx_media_ocr_derivatives",
    ),
    ForeignKeyConstraint(
        ["company_id", "source_document_id"],
        ["documents.company_id", "documents.document_id"],
        name="fk_docx_media_ocr_source_document",
    ),
    CheckConstraint("company_id <> ''", name="ck_docx_media_ocr_company_nonempty"),
    CheckConstraint("ocr_id <> ''", name="ck_docx_media_ocr_id_nonempty"),
    CheckConstraint(
        "source_document_id <> ''",
        name="ck_docx_media_ocr_source_document_nonempty",
    ),
    CheckConstraint("media_index >= 0", name="ck_docx_media_ocr_index_nonnegative"),
    CheckConstraint("archive_path <> ''", name="ck_docx_media_ocr_path_nonempty"),
    CheckConstraint(
        "char_length(archive_path) <= 512",
        name="ck_docx_media_ocr_path_length",
    ),
    CheckConstraint(
        "source_document_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_docx_media_ocr_document_sha256",
    ),
    CheckConstraint(
        "source_media_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_docx_media_ocr_media_sha256",
    ),
    CheckConstraint(
        "media_type IN ('image/jpeg', 'image/png')",
        name="ck_docx_media_ocr_media_type",
    ),
    CheckConstraint("engine <> ''", name="ck_docx_media_ocr_engine_nonempty"),
    CheckConstraint("threshold BETWEEN 0 AND 1", name="ck_docx_media_ocr_threshold"),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_docx_media_ocr_status_allowed",
    ),
    CheckConstraint(
        "jsonb_typeof(result) = 'object'",
        name="ck_docx_media_ocr_result_object",
    ),
    CheckConstraint(
        "result ? 'source_document_id' AND "
        "result->>'source_document_id' = source_document_id || ':media:' || media_index::text",
        name="ck_docx_media_ocr_result_source_id",
    ),
    CheckConstraint(
        "result ? 'source_sha256' AND result->>'source_sha256' = source_media_sha256",
        name="ck_docx_media_ocr_result_source_sha256",
    ),
    CheckConstraint(
        "result ? 'engine' AND result->>'engine' = engine",
        name="ck_docx_media_ocr_result_engine",
    ),
    CheckConstraint(
        "result ? 'threshold' AND (result->>'threshold')::numeric = threshold",
        name="ck_docx_media_ocr_result_threshold",
    ),
    CheckConstraint(
        "result ? 'status' AND result->>'status' = status",
        name="ck_docx_media_ocr_result_status",
    ),
    CheckConstraint(
        "mean_confidence IS NULL OR (mean_confidence BETWEEN 0 AND 1)",
        name="ck_docx_media_ocr_mean_confidence",
    ),
)
Index(
    "ix_docx_media_ocr_company_source_created",
    document_docx_media_ocr_derivatives.c.company_id,
    document_docx_media_ocr_derivatives.c.source_document_id,
    document_docx_media_ocr_derivatives.c.media_index,
    document_docx_media_ocr_derivatives.c.created_at,
    document_docx_media_ocr_derivatives.c.ocr_id,
)
Index(
    "ix_docx_media_ocr_company_created",
    document_docx_media_ocr_derivatives.c.company_id,
    document_docx_media_ocr_derivatives.c.created_at,
)

document_ocr_derivatives = Table(
    "document_ocr_derivatives",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("ocr_id", Text, nullable=False),
    Column("source_document_id", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("threshold", Numeric(3, 2), nullable=False),
    Column("status", Text, nullable=False),
    Column("result", JSONB, nullable=False),
    Column("mean_confidence", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "ocr_id", name="pk_document_ocr_derivatives"),
    ForeignKeyConstraint(
        ["company_id", "source_document_id"],
        ["documents.company_id", "documents.document_id"],
        name="fk_ocr_derivatives_source_document",
    ),
    CheckConstraint("company_id <> ''", name="ck_ocr_company_id_nonempty"),
    CheckConstraint("ocr_id <> ''", name="ck_ocr_ocr_id_nonempty"),
    CheckConstraint("source_document_id <> ''", name="ck_ocr_source_document_id_nonempty"),
    CheckConstraint("engine <> ''", name="ck_ocr_engine_nonempty"),
    CheckConstraint("threshold BETWEEN 0 AND 1", name="ck_ocr_threshold_range"),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_ocr_status_allowed",
    ),
    CheckConstraint(
        "jsonb_typeof(result) = 'object'",
        name="ck_ocr_result_object",
    ),
    CheckConstraint(
        "mean_confidence IS NULL OR (mean_confidence BETWEEN 0 AND 1)",
        name="ck_ocr_mean_confidence_range",
    ),
)
Index(
    "ix_ocr_company_source_created",
    document_ocr_derivatives.c.company_id,
    document_ocr_derivatives.c.source_document_id,
    document_ocr_derivatives.c.created_at,
    document_ocr_derivatives.c.ocr_id,
)
Index(
    "ix_ocr_company_created",
    document_ocr_derivatives.c.company_id,
    document_ocr_derivatives.c.created_at,
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("event_id", Text, nullable=False),
    Column("company_id", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("object_type", Text, nullable=True),
    Column("object_id", Text, nullable=True),
    Column("object_version", Integer, nullable=True),
    Column("basis", JSONB, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "event_id", name="pk_audit_events"),
    CheckConstraint("company_id <> ''", name="ck_audit_events_company_id_nonempty"),
    CheckConstraint(
        "object_version IS NULL OR object_version >= 1",
        name="ck_audit_events_object_version_positive",
    ),
)
Index(
    "ix_audit_events_company_occurred",
    audit_events.c.company_id,
    audit_events.c.occurred_at,
    audit_events.c.event_id,
)
Index(
    "ix_audit_events_company_object",
    audit_events.c.company_id,
    audit_events.c.object_type,
    audit_events.c.object_id,
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("key_id", Text, nullable=False),
    Column("company_id", Text, nullable=False),
    Column("key_digest", String(64), nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("access_role", Text, nullable=False, server_default="OPERATOR"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "key_id", name="pk_api_keys"),
    CheckConstraint("company_id <> ''", name="ck_api_keys_company_id_nonempty"),
    UniqueConstraint("key_digest", name="uq_api_keys_key_digest"),
    CheckConstraint("key_digest ~ '^[0-9a-f]{64}$'", name="ck_api_keys_key_digest"),
    CheckConstraint(
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'MANUFACTURER_REVIEWER', "
        "'COMPLETENESS_REVIEWER', "
        "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER', "
        "'PARTICIPATION_APPROVER', 'APPLICATION_REVIEWER', "
        "'APPLICATION_SUBMISSION_APPROVER', "
        "'APPLICATION_SUBMISSION_EXECUTOR', 'AUDITOR')",
        name="ck_api_keys_access_role",
    ),
)
Index("ix_api_keys_company_enabled", api_keys.c.company_id, api_keys.c.enabled)

write_receipts = Table(
    "write_receipts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("response", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint(
        "company_id",
        "operation",
        "idempotency_key",
        name="pk_write_receipts",
    ),
    CheckConstraint("company_id <> ''", name="ck_write_receipts_company_id_nonempty"),
    CheckConstraint(
        "request_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_write_receipts_request_sha256",
    ),
)
Index(
    "ix_write_receipts_company_created",
    write_receipts.c.company_id,
    write_receipts.c.created_at,
)

evaluations = Table(
    "evaluations",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("evaluation_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("engine_version", Text, nullable=False),
    Column("recommendation", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("company_id", "evaluation_id", name="pk_evaluations"),
    CheckConstraint("company_id <> ''", name="ck_evaluations_company_id_nonempty"),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_evaluations_case_version",
    ),
    CheckConstraint("case_version >= 1", name="ck_evaluations_case_version_positive"),
    CheckConstraint(
        "input_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_evaluations_input_sha256",
    ),
)
Index(
    "ix_evaluations_company_case",
    evaluations.c.company_id,
    evaluations.c.case_id,
    evaluations.c.case_version,
    evaluations.c.created_at,
)

participation_decisions = Table(
    "participation_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("decision_id", Text, nullable=False),
    Column("evaluation_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("evaluation_evidence_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("decided_by", Text, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "decision_id", name="pk_participation_decisions"),
    UniqueConstraint("company_id", "evaluation_id", name="uq_participation_decisions_evaluation"),
    ForeignKeyConstraint(
        ["company_id", "evaluation_id"],
        ["evaluations.company_id", "evaluations.evaluation_id"],
        name="fk_participation_decisions_evaluation",
    ),
    CheckConstraint("company_id <> ''", name="ck_participation_decisions_company"),
    CheckConstraint("case_version >= 1", name="ck_participation_decisions_version"),
    CheckConstraint(
        "evaluation_evidence_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_participation_decisions_digests",
    ),
    CheckConstraint("status IN ('APPROVED', 'REJECTED')", name="ck_participation_decisions_status"),
    CheckConstraint(
        "jsonb_typeof(decision) = 'object'",
        name="ck_participation_decisions_object",
    ),
    CheckConstraint(
        "decision->>'schema_version' = 'participation-decision-v1' AND "
        "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "decision->>'decision_id' IS NOT DISTINCT FROM decision_id AND "
        "decision->>'evaluation_id' IS NOT DISTINCT FROM evaluation_id AND "
        "decision->>'evaluation_evidence_sha256' IS NOT DISTINCT FROM "
        "evaluation_evidence_sha256 AND "
        "decision->>'case_id' IS NOT DISTINCT FROM case_id AND "
        "(decision->>'case_version')::integer IS NOT DISTINCT FROM case_version AND "
        "decision->>'status' IS NOT DISTINCT FROM status AND "
        "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "decision->>'decided_by' IS NOT DISTINCT FROM decided_by AND "
        "(decision->>'decided_at')::timestamptz IS NOT DISTINCT FROM decided_at AND "
        "decision->'external_action_authorized' = 'false'::jsonb",
        name="ck_participation_decisions_identity",
    ),
)
Index(
    "ix_participation_decisions_company_case",
    participation_decisions.c.company_id,
    participation_decisions.c.case_id,
    participation_decisions.c.case_version,
)

application_packages = Table(
    "application_packages",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("package_id", Text, nullable=False),
    Column("participation_decision_id", Text, nullable=False),
    Column("participation_decision_sha256", String(64), nullable=False),
    Column("evaluation_id", Text, nullable=False),
    Column("case_id", Text, nullable=False),
    Column("case_version", Integer, nullable=False),
    Column("case_input_sha256", String(64), nullable=False),
    Column("package_sha256", String(64), nullable=False),
    Column("package", JSONB, nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("prepared_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "package_id", name="pk_application_packages"),
    UniqueConstraint(
        "company_id",
        "participation_decision_id",
        name="uq_application_packages_participation_decision",
    ),
    ForeignKeyConstraint(
        ["company_id", "participation_decision_id"],
        ["participation_decisions.company_id", "participation_decisions.decision_id"],
        name="fk_application_packages_participation_decision",
    ),
    ForeignKeyConstraint(
        ["company_id", "case_id", "case_version"],
        ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
        name="fk_application_packages_case",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(package_id) <> '' AND "
        "btrim(participation_decision_id) <> '' AND btrim(evaluation_id) <> '' AND "
        "btrim(case_id) <> '' AND btrim(prepared_by) <> ''",
        name="ck_application_packages_text",
    ),
    CheckConstraint("case_version >= 1", name="ck_application_packages_version"),
    CheckConstraint(
        "participation_decision_sha256 ~ '^[0-9a-f]{64}$' AND "
        "case_input_sha256 ~ '^[0-9a-f]{64}$' AND "
        "package_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_application_packages_digests",
    ),
    CheckConstraint("jsonb_typeof(package) = 'object'", name="ck_application_packages_object"),
    CheckConstraint(
        "package->>'schema_version' = 'application-package-v1' AND "
        "package->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "package->>'package_id' IS NOT DISTINCT FROM package_id AND "
        "package->>'participation_decision_id' IS NOT DISTINCT FROM "
        "participation_decision_id AND "
        "package->>'participation_decision_sha256' IS NOT DISTINCT FROM "
        "participation_decision_sha256 AND "
        "package->>'evaluation_id' IS NOT DISTINCT FROM evaluation_id AND "
        "package->>'case_id' IS NOT DISTINCT FROM case_id AND "
        "(package->>'case_version')::integer IS NOT DISTINCT FROM case_version AND "
        "package->>'case_input_sha256' IS NOT DISTINCT FROM case_input_sha256 AND "
        "package->>'package_sha256' IS NOT DISTINCT FROM package_sha256 AND "
        "package->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND "
        "(package->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at AND "
        "package->>'review_status' = 'PENDING_REVIEW' AND "
        "package->>'coverage_status' = 'UNKNOWN' AND "
        "package->'external_action_authorized' = 'false'::jsonb",
        name="ck_application_packages_identity",
    ),
)
Index(
    "ix_application_packages_company_case",
    application_packages.c.company_id,
    application_packages.c.case_id,
    application_packages.c.case_version,
)

application_package_reviews = Table(
    "application_package_reviews",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("package_id", Text, nullable=False),
    Column("package_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "package_id", name="pk_application_package_reviews"),
    ForeignKeyConstraint(
        ["company_id", "package_id"],
        ["application_packages.company_id", "application_packages.package_id"],
        name="fk_application_package_reviews_package",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(package_id) <> '' AND btrim(reviewed_by) <> ''",
        name="ck_application_package_reviews_text",
    ),
    CheckConstraint(
        "package_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_application_package_reviews_digests",
    ),
    CheckConstraint(
        "status IN ('PASS', 'FAIL', 'UNKNOWN')",
        name="ck_application_package_reviews_status",
    ),
    CheckConstraint(
        "jsonb_typeof(decision) = 'object'",
        name="ck_application_package_reviews_object",
    ),
    CheckConstraint(
        "decision->>'schema_version' = 'application-review-decision-v1' AND "
        "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "decision->>'package_id' IS NOT DISTINCT FROM package_id AND "
        "decision->>'package_sha256' IS NOT DISTINCT FROM package_sha256 AND "
        "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "decision->>'status' IS NOT DISTINCT FROM status AND "
        "decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by AND "
        "(decision->>'reviewed_at')::timestamptz IS NOT DISTINCT FROM reviewed_at AND "
        "decision->'external_action_authorized' = 'false'::jsonb",
        name="ck_application_package_reviews_identity",
    ),
)

application_submission_intents = Table(
    "application_submission_intents",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("package_id", Text, nullable=False),
    Column("action_id", Text, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("intent", JSONB, nullable=False),
    Column("prepared_by", Text, nullable=False),
    Column("prepared_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "package_id", name="pk_application_submission_intents"),
    UniqueConstraint("company_id", "action_id", name="uq_application_submission_intents_action"),
    ForeignKeyConstraint(
        ["company_id", "package_id"],
        ["application_package_reviews.company_id", "application_package_reviews.package_id"],
        name="fk_application_submission_intents_review",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(package_id) <> '' AND "
        "btrim(action_id) <> '' AND btrim(prepared_by) <> ''",
        name="ck_application_submission_intents_text",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_application_submission_intents_sha"
    ),
    CheckConstraint(
        "jsonb_typeof(intent) = 'object' AND "
        "intent->>'schema_version' = 'application-submission-intent-v1' AND "
        "intent->>'package_id' IS NOT DISTINCT FROM package_id AND "
        "intent->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND "
        "intent->'request'->>'action_id' IS NOT DISTINCT FROM action_id AND "
        "intent->'request'->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "intent->'request'->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256 AND "
        "(intent->'request'->>'created_at')::timestamptz IS NOT DISTINCT FROM prepared_at",
        name="ck_application_submission_intents_identity",
    ),
)

application_submission_approvals = Table(
    "application_submission_approvals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("action_id", Text, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("decided_by", Text, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "action_id", name="pk_application_submission_approvals"),
    ForeignKeyConstraint(
        ["company_id", "action_id"],
        ["application_submission_intents.company_id", "application_submission_intents.action_id"],
        name="fk_application_submission_approvals_intent",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(action_id) <> '' AND btrim(decided_by) <> ''",
        name="ck_application_submission_approvals_text",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_application_submission_approvals_sha",
    ),
    CheckConstraint(
        "status IN ('APPROVED', 'REJECTED')", name="ck_application_submission_approvals_status"
    ),
    CheckConstraint(
        "jsonb_typeof(decision) = 'object' AND "
        "decision->>'schema_version' = 'application-submission-approval-v1' AND "
        "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "decision->>'action_id' IS NOT DISTINCT FROM action_id AND "
        "decision->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256 AND "
        "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
        "decision->>'status' IS NOT DISTINCT FROM status AND "
        "decision->>'decided_by' IS NOT DISTINCT FROM decided_by AND "
        "(decision->>'decided_at')::timestamptz IS NOT DISTINCT FROM decided_at AND "
        "decision->'external_action_performed' = 'false'::jsonb",
        name="ck_application_submission_approvals_identity",
    ),
)

application_submission_admissions = Table(
    "application_submission_admissions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("action_id", Text, nullable=False),
    Column("package_id", Text, nullable=False),
    Column("admission_id", Text, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("approval_decision_sha256", String(64), nullable=False),
    Column("admission_sha256", String(64), nullable=False),
    Column("admission", JSONB, nullable=False),
    Column("admitted_by", Text, nullable=False),
    Column("admitted_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "action_id", name="pk_application_submission_admissions"),
    UniqueConstraint("company_id", "admission_id", name="uq_application_submission_admissions_id"),
    ForeignKeyConstraint(
        ["company_id", "action_id"],
        [
            "application_submission_approvals.company_id",
            "application_submission_approvals.action_id",
        ],
        name="fk_application_submission_admissions_approval",
    ),
    CheckConstraint(
        "btrim(company_id) <> '' AND btrim(action_id) <> '' AND "
        "btrim(package_id) <> '' AND btrim(admission_id) <> '' AND "
        "btrim(admitted_by) <> ''",
        name="ck_application_submission_admissions_text",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$' AND "
        "approval_decision_sha256 ~ '^[0-9a-f]{64}$' AND "
        "admission_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_application_submission_admissions_sha",
    ),
    CheckConstraint(
        "jsonb_typeof(admission) = 'object' AND "
        "admission->>'schema_version' = 'application-submission-admission-v1' AND "
        "admission->>'company_id' IS NOT DISTINCT FROM company_id AND "
        "admission->>'action_id' IS NOT DISTINCT FROM action_id AND "
        "admission->>'package_id' IS NOT DISTINCT FROM package_id AND "
        "admission->>'admission_id' IS NOT DISTINCT FROM admission_id AND "
        "admission->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256 AND "
        "admission->>'approval_decision_sha256' IS NOT DISTINCT FROM approval_decision_sha256 AND "
        "admission->>'admission_sha256' IS NOT DISTINCT FROM admission_sha256 AND "
        "admission->>'admitted_by' IS NOT DISTINCT FROM admitted_by AND "
        "(admission->>'admitted_at')::timestamptz IS NOT DISTINCT FROM admitted_at AND "
        "admission->>'status' = 'ADMITTED_NO_DISPATCH' AND "
        "admission->'external_action_performed' = 'false'::jsonb",
        name="ck_application_submission_admissions_identity",
    ),
)

# Bounded immutable EAEU manufacturer searches. The final result is separate from
# the durable STARTED attempt so a process failure remains explicitly UNKNOWN.
manufacturer_search_runs = Table(
    "manufacturer_search_runs",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("command_id", Text, nullable=False),
    Column("query", String(80), nullable=False),
    Column("parser_revision", Text, nullable=False),
    Column("request_body", LargeBinary, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_manufacturer_search_runs"),
    UniqueConstraint("company_id", "command_id", name="uq_manufacturer_search_command"),
    CheckConstraint(
        "btrim(company_id)<>'' AND run_id ~ '^[0-9a-f-]{36}$' "
        "AND command_id ~ '^[0-9a-f-]{36}$' AND char_length(query) BETWEEN 1 AND 80 "
        "AND parser_revision='eaeu-registry-parser-v1' AND octet_length(request_body)<=1024 "
        "AND request_sha256=encode(sha256(request_body),'hex')",
        name="ck_manufacturer_search_runs_values",
    ),
)
Index(
    "ix_manufacturer_search_runs_company_created",
    manufacturer_search_runs.c.company_id,
    manufacturer_search_runs.c.created_at,
)

manufacturer_search_attempts = Table(
    "manufacturer_search_attempts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "attempt_id", name="pk_manufacturer_search_attempts"),
    UniqueConstraint("company_id", "run_id", name="uq_manufacturer_search_attempt_run"),
    UniqueConstraint(
        "company_id", "attempt_id", "run_id", name="uq_manufacturer_search_attempt_identity"
    ),
    ForeignKeyConstraint(
        ["company_id", "run_id"],
        ["manufacturer_search_runs.company_id", "manufacturer_search_runs.run_id"],
        name="fk_manufacturer_search_attempt_run",
    ),
    CheckConstraint(
        "attempt_id ~ '^[0-9a-f-]{36}$' AND status='STARTED'",
        name="ck_manufacturer_search_attempt_values",
    ),
)

manufacturer_search_results = Table(
    "manufacturer_search_results",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("attempt_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason_code", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("response_body", LargeBinary),
    Column("response_sha256", String(64)),
    Column("response_byte_size", Integer),
    Column("matched_count", Integer),
    Column("candidate_count", Integer, nullable=False),
    PrimaryKeyConstraint("company_id", "run_id", name="pk_manufacturer_search_results"),
    UniqueConstraint("company_id", "attempt_id", name="uq_manufacturer_search_result_attempt"),
    ForeignKeyConstraint(
        ["company_id", "attempt_id", "run_id"],
        [
            "manufacturer_search_attempts.company_id",
            "manufacturer_search_attempts.attempt_id",
            "manufacturer_search_attempts.run_id",
        ],
        name="fk_manufacturer_search_result_attempt",
    ),
    CheckConstraint(
        "((status='COMPLETED' AND reason_code='VERIFIED_RESPONSE' "
        "AND response_body IS NOT NULL AND response_sha256 ~ '^[0-9a-f]{64}$' "
        "AND response_byte_size=octet_length(response_body) "
        "AND response_sha256=encode(sha256(response_body),'hex') "
        "AND response_byte_size BETWEEN 1 AND 524288 AND matched_count>=0 "
        "AND candidate_count BETWEEN 0 AND 10 AND candidate_count<=matched_count) OR "
        "(status='SOURCE_ERROR' AND reason_code='SOURCE_UNAVAILABLE_OR_CHANGED' "
        "AND matched_count IS NULL AND candidate_count=0 AND "
        "((response_body IS NULL AND response_sha256 IS NULL "
        "AND response_byte_size IS NULL) OR (response_body IS NOT NULL "
        "AND response_sha256 ~ '^[0-9a-f]{64}$' "
        "AND response_byte_size=octet_length(response_body) "
        "AND response_sha256=encode(sha256(response_body),'hex') "
        "AND response_byte_size BETWEEN 0 AND 524288))))",
        name="ck_manufacturer_search_result_bounds",
    ),
)

manufacturer_evidence_artifacts = Table(
    "manufacturer_evidence_artifacts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("artifact_id", Text, nullable=False),
    Column("command_id", Text, nullable=False),
    Column("source_title", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("uploaded_by", Text, nullable=False),
    Column("uploaded_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "artifact_id", name="pk_manufacturer_evidence_artifacts"),
    UniqueConstraint("company_id", "command_id", name="uq_manufacturer_evidence_command"),
    CheckConstraint(
        "btrim(company_id)<>'' AND artifact_id ~ '^[0-9a-f-]{36}$' "
        "AND command_id ~ '^[0-9a-f-]{36}$' AND source_url ~ '^https://' "
        "AND media_type='application/pdf' AND byte_size BETWEEN 1 AND 2097152 "
        "AND byte_size=octet_length(content) AND sha256=encode(sha256(content),'hex') "
        "AND btrim(uploaded_by)<>''",
        name="ck_manufacturer_evidence_values",
    ),
)

manufacturer_review_proposals = Table(
    "manufacturer_review_proposals",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("command_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("record_id", String(24), nullable=False),
    Column("dossier_sha256", String(64), nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("proposal_canonical", LargeBinary, nullable=False),
    Column("proposal", JSONB, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("proposed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "proposal_id", name="pk_manufacturer_review_proposals"),
    UniqueConstraint("company_id", "command_id", name="uq_manufacturer_review_proposal_command"),
    ForeignKeyConstraint(
        ["company_id", "run_id"],
        ["manufacturer_search_runs.company_id", "manufacturer_search_runs.run_id"],
        name="fk_manufacturer_review_proposal_run",
    ),
    CheckConstraint(
        "proposal_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$' "
        "AND record_id ~ '^[0-9a-f]{24}$' AND dossier_sha256 ~ '^[0-9a-f]{64}$' "
        "AND proposal_sha256=encode(sha256(proposal_canonical),'hex') "
        "AND jsonb_typeof(proposal)='object' AND octet_length(proposal_canonical)<=65536 "
        "AND proposal->>'proposal_id' IS NOT DISTINCT FROM proposal_id "
        "AND proposal->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 "
        "AND proposal->>'dossier_sha256' IS NOT DISTINCT FROM dossier_sha256 "
        "AND proposal->>'proposed_by' IS NOT DISTINCT FROM proposed_by",
        name="ck_manufacturer_review_proposal_values",
    ),
)

manufacturer_review_decisions = Table(
    "manufacturer_review_decisions",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("decision_id", Text, nullable=False),
    Column("command_id", Text, nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("proposal_sha256", String(64), nullable=False),
    Column("decision_sha256", String(64), nullable=False),
    Column("decision_canonical", LargeBinary, nullable=False),
    Column("decision", JSONB, nullable=False),
    Column("reviewed_by", Text, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    Column("effective_until", DateTime(timezone=True)),
    PrimaryKeyConstraint("company_id", "decision_id", name="pk_manufacturer_review_decisions"),
    UniqueConstraint("company_id", "proposal_id", name="uq_manufacturer_review_decision_proposal"),
    UniqueConstraint("company_id", "command_id", name="uq_manufacturer_review_decision_command"),
    ForeignKeyConstraint(
        ["company_id", "proposal_id"],
        ["manufacturer_review_proposals.company_id", "manufacturer_review_proposals.proposal_id"],
        name="fk_manufacturer_review_decision_proposal",
    ),
    CheckConstraint(
        "decision_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$' "
        "AND proposal_sha256 ~ '^[0-9a-f]{64}$' "
        "AND decision_sha256=encode(sha256(decision_canonical),'hex') "
        "AND jsonb_typeof(decision)='object' AND octet_length(decision_canonical)<=65536 "
        "AND decision->>'decision_id' IS NOT DISTINCT FROM decision_id "
        "AND decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 "
        "AND decision->>'proposal_id' IS NOT DISTINCT FROM proposal_id "
        "AND decision->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 "
        "AND decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by",
        name="ck_manufacturer_review_decision_values",
    ),
)

manufacturer_rfq_drafts = Table(
    "manufacturer_rfq_drafts",
    metadata,
    Column("company_id", Text, nullable=False),
    Column("draft_id", Text, nullable=False),
    Column("command_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("record_id", String(24), nullable=False),
    Column("proposal_id", Text, nullable=False),
    Column("decision_id", Text, nullable=False),
    Column("manual_inputs_sha256", String(64), nullable=False),
    Column("draft_sha256", String(64), nullable=False),
    Column("draft_canonical", LargeBinary, nullable=False),
    Column("text_sha256", String(64), nullable=False),
    Column("text_content", LargeBinary, nullable=False),
    Column("draft", JSONB, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("company_id", "draft_id", name="pk_manufacturer_rfq_drafts"),
    UniqueConstraint("company_id", "command_id", name="uq_manufacturer_rfq_command"),
    ForeignKeyConstraint(
        ["company_id", "proposal_id"],
        ["manufacturer_review_proposals.company_id", "manufacturer_review_proposals.proposal_id"],
        name="fk_manufacturer_rfq_proposal",
    ),
    ForeignKeyConstraint(
        ["company_id", "decision_id"],
        ["manufacturer_review_decisions.company_id", "manufacturer_review_decisions.decision_id"],
        name="fk_manufacturer_rfq_decision",
    ),
    CheckConstraint(
        "draft_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$' "
        "AND record_id ~ '^[0-9a-f]{24}$' AND manual_inputs_sha256 ~ '^[0-9a-f]{64}$' "
        "AND draft_sha256=encode(sha256(draft_canonical),'hex') "
        "AND text_sha256=encode(sha256(text_content),'hex') "
        "AND octet_length(draft_canonical)<=262144 AND octet_length(text_content)<=131072 "
        "AND jsonb_typeof(draft)='object' AND draft->>'draft_id' IS NOT DISTINCT FROM draft_id "
        "AND draft->>'command_id' IS NOT DISTINCT FROM command_id "
        "AND draft->>'run_id' IS NOT DISTINCT FROM run_id "
        "AND draft->>'proposal_id' IS NOT DISTINCT FROM proposal_id "
        "AND draft->>'decision_id' IS NOT DISTINCT FROM decision_id "
        "AND draft->>'manual_inputs_sha256' IS NOT DISTINCT FROM manual_inputs_sha256 "
        "AND draft->>'draft_sha256' IS NOT DISTINCT FROM draft_sha256 "
        "AND draft->>'text_sha256' IS NOT DISTINCT FROM text_sha256 "
        "AND draft->>'created_by' IS NOT DISTINCT FROM created_by "
        "AND draft->>'status'='DRAFT_NO_DISPATCH'",
        name="ck_manufacturer_rfq_draft_values",
    ),
)
