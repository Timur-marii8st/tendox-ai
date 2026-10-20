"""Versioned six-engine SERP evidence; preserve all immutable legacy runs."""

from alembic import op

revision = "20261006_12"
down_revision = "20261006_11"
branch_labels = None
depends_on = None

CONSTRAINTS = (
    (
        "eis_supplier_serp_runs",
        "ck_eis_supplier_serp_bundle",
        "(source_bundle IS NULL AND source_bundle_sha256 IS NULL AND "
        "source_bundle_byte_count IS NULL) OR (source_bundle IS NOT NULL AND "
        "source_bundle_sha256 IS NOT NULL AND source_bundle_byte_count IS NOT NULL "
        "AND source_bundle_sha256 ~ '^[0-9a-f]{64}$' AND source_bundle_byte_count "
        "BETWEEN 1 AND 13631488 AND octet_length(source_bundle) = "
        "source_bundle_byte_count AND source_bundle_sha256 = "
        "encode(sha256(source_bundle), 'hex'))",
    ),
    (
        "eis_supplier_serp_runs",
        "ck_eis_supplier_serp_report_identity",
        "COALESCE((report->>'policy_version' IN "
        "('eis-position-supplier-serp-v1','eis-position-supplier-serp-v2') AND "
        "report->>'run_id' = run_id AND "
        "report->'request'->'selection'->'notice'->>'purchase_number' = "
        "purchase_number AND "
        "(report->'request'->'selection'->'notice'->>'version_number')::int = "
        "version_number AND "
        "report->'request'->'selection'->'notice'->>'notice_xml_sha256' = "
        "notice_xml_sha256 AND (report->'request'->'selection'->>'source_index')::int "
        "= source_index AND (report->>'created_at')::timestamptz = created_at AND "
        "report->>'query_scope' = 'PUBLIC_POSITION_NAME_FIXED_SUPPLIER_TERMS' AND "
        "report->>'full_market_coverage' = 'UNKNOWN' AND report->>'supplier_identity' "
        "= 'UNKNOWN' AND report->>'price' = 'UNKNOWN' AND report->>'stock' = "
        "'UNKNOWN' AND report->>'delivery' = 'UNKNOWN' AND report->>'technical' = "
        "'UNKNOWN' AND report->>'quote' = 'UNKNOWN' AND report->>'participation' = "
        "'UNKNOWN' AND ((source_bundle IS NULL AND report->'source_bundle_sha256' = "
        "'null'::jsonb AND report->'source_bundle_byte_count' = 'null'::jsonb) OR "
        "(source_bundle IS NOT NULL AND report->>'source_bundle_sha256' = "
        "source_bundle_sha256 AND (report->>'source_bundle_byte_count')::int = "
        "source_bundle_byte_count)) AND ((report->>'status' = 'STARTED' AND "
        "report->'batch' = 'null'::jsonb AND report->'attempted_source_requests' = "
        "'null'::jsonb AND source_bundle IS NULL) OR (report->>'status' = "
        "'QUERY_NOT_COVERED' AND report->'batch' = 'null'::jsonb AND report->'query' "
        "= 'null'::jsonb AND (report->>'attempted_source_requests')::int = 0 AND "
        "source_bundle IS NULL) OR (report->>'status' IN "
        "('COMPLETED','PARTIAL','UNAVAILABLE') AND report->'batch'->>'status' = "
        "report->>'status' AND report->'batch'->>'query' = report->>'query' AND "
        "report->'batch'->>'coverage' = 'UNKNOWN' AND "
        "(report->'batch'->>'supplierpage_requests')::int = 0 AND "
        "((report->>'policy_version' = 'eis-position-supplier-serp-v1' AND "
        "jsonb_array_length(report->'batch'->'attempts') = 3 AND "
        "(report->>'attempted_source_requests')::int BETWEEN 0 AND 3) OR "
        "(report->>'policy_version' = 'eis-position-supplier-serp-v2' AND "
        "jsonb_array_length(report->'batch'->'attempts') = 6 AND "
        "(report->>'attempted_source_requests')::int BETWEEN 0 AND 6))))), false)",
    ),
    (
        "eis_supplier_page_runs",
        "ck_eis_supplier_page_identity",
        "btrim(company_id) <> '' AND source_index BETWEEN 1 AND 25 AND rank BETWEEN 1 "
        "AND 50 AND engine IN "
        "('BING','BRAVE','DUCKDUCKGO','MOJEEK','YANDEX','GOOGLE') AND run_id ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND "
        "cache_key ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND "
        "notice_xml_sha256 ~ '^[0-9a-f]{64}$'",
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    for table, name, expression in CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression})")


def downgrade() -> None:
    # No destructive rollback of immutable evidence or downstream source bindings.
    raise RuntimeError("supplier SERP fallback evidence must be preserved")
