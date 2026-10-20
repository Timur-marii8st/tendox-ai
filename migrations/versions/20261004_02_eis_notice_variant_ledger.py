"""Frozen immutable evidence-only notice variant schema; never canonical intake."""

from alembic import op

revision = "20261004_02"
down_revision = "20261004_01"
branch_labels = None
depends_on = None
TABLES = ("eis_notice_variant_receipts", "eis_notice_variants", "eis_notice_variant_origins")

SCHEMA = (
    """CREATE TABLE eis_notice_variant_receipts (
company_id TEXT NOT NULL,
receipt_id TEXT NOT NULL,
manifest_sha256 VARCHAR(64) NOT NULL,
diagnosis_sha256 VARCHAR(64) NOT NULL,
window_key TEXT NOT NULL,
response_sha256 VARCHAR(64) NOT NULL,
prepared_response_sha256 VARCHAR(64) NOT NULL,
archive_sha256s JSONB NOT NULL,
archive_count INTEGER NOT NULL,
occurrence_count INTEGER NOT NULL,
variant_count INTEGER NOT NULL,
evidence JSONB NOT NULL,
retention_audit_event_id TEXT NOT NULL,
diagnosis_audit_event_id TEXT NOT NULL,
ledger_audit_event_id TEXT NOT NULL,
schema_version TEXT NOT NULL,
inventory_status TEXT NOT NULL,
canonical_admission TEXT NOT NULL,
coverage TEXT NOT NULL,
observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
receipt_sha256 VARCHAR(64) NOT NULL,
CONSTRAINT pk_eis_notice_variant_receipts PRIMARY KEY (company_id, receipt_id),
CONSTRAINT uq_eis_variant_receipt_basis UNIQUE (company_id, manifest_sha256,
    diagnosis_sha256),
CONSTRAINT fk_eis_variant_receipt_retention_audit FOREIGN KEY(company_id,
    retention_audit_event_id) REFERENCES audit_events (company_id, event_id),
CONSTRAINT fk_eis_variant_receipt_diagnosis_audit FOREIGN KEY(company_id,
    diagnosis_audit_event_id) REFERENCES audit_events (company_id, event_id),
CONSTRAINT fk_eis_variant_receipt_ledger_audit FOREIGN KEY(company_id,
    ledger_audit_event_id) REFERENCES audit_events (company_id, event_id) DEFERRABLE
    INITIALLY DEFERRED,
CONSTRAINT ck_eis_variant_receipt_text CHECK (btrim(company_id) <> '' AND btrim(window_key)
    <> ''),
CONSTRAINT ck_eis_variant_receipt_id CHECK (receipt_id ~
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
CONSTRAINT ck_eis_variant_receipt_sha CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$' AND
    diagnosis_sha256 ~ '^[0-9a-f]{64}$' AND response_sha256 ~ '^[0-9a-f]{64}$' AND
    prepared_response_sha256 ~ '^[0-9a-f]{64}$' AND receipt_sha256 ~ '^[0-9a-f]{64}$'),
CONSTRAINT ck_eis_variant_receipt_counts CHECK (archive_count BETWEEN 1 AND 20 AND
    occurrence_count BETWEEN 1 AND 2000 AND variant_count BETWEEN 1 AND occurrence_count AND
    jsonb_typeof(archive_sha256s) = 'array' AND jsonb_array_length(archive_sha256s) =
    archive_count),
CONSTRAINT ck_eis_variant_receipt_policy CHECK (schema_version =
    'eis-notice-variant-ledger-v1' AND inventory_status = 'COMPLETE' AND canonical_admission
    = 'NOT_ENABLED' AND coverage = 'UNKNOWN'),
CONSTRAINT ck_eis_variant_receipt_evidence CHECK (jsonb_typeof(evidence) = 'object' AND
    evidence->>'company_id' IS NOT DISTINCT FROM company_id AND evidence->>'window_key' IS
    NOT DISTINCT FROM window_key AND evidence->>'manifest_sha256' IS NOT DISTINCT FROM
    manifest_sha256 AND evidence->>'response_sha256' IS NOT DISTINCT FROM response_sha256
    AND evidence->>'prepared_response_sha256' IS NOT DISTINCT FROM prepared_response_sha256
    AND evidence->'archive_sha256s' IS NOT DISTINCT FROM archive_sha256s AND
    evidence->>'status' IS NOT DISTINCT FROM 'RETAINED' AND evidence->'complete_set' IS NOT
    DISTINCT FROM 'true'::jsonb AND octet_length(evidence::text) <= 131072)
)""",
    """CREATE TABLE eis_notice_variants (
company_id TEXT NOT NULL,
purchase_number TEXT NOT NULL,
version_number INTEGER NOT NULL,
document_type TEXT NOT NULL,
xml_sha256 VARCHAR(64) NOT NULL,
facts JSONB NOT NULL,
facts_sha256 VARCHAR(64) NOT NULL,
CONSTRAINT pk_eis_notice_variants PRIMARY KEY (company_id, purchase_number, version_number,
    document_type, xml_sha256),
CONSTRAINT ck_eis_variants_company CHECK (btrim(company_id) <> ''),
CONSTRAINT ck_eis_variants_number_version CHECK (purchase_number ~ '^[0-9]{19,23}$' AND
    version_number >= 1),
CONSTRAINT ck_eis_variants_type CHECK (document_type IN ('epNotificationEF2020',
    'epNotificationEZK2020', 'epNotificationEOK2020')),
CONSTRAINT ck_eis_variants_sha CHECK (xml_sha256 ~ '^[0-9a-f]{64}$' AND facts_sha256 ~
    '^[0-9a-f]{64}$'),
CONSTRAINT ck_eis_variants_facts CHECK (jsonb_typeof(facts) = 'object' AND
    facts->>'purchase_number' IS NOT DISTINCT FROM purchase_number AND
    (facts->>'version_number')::integer IS NOT DISTINCT FROM version_number AND
    facts->>'document_type' IS NOT DISTINCT FROM document_type AND facts->>'xml_sha256' IS
    NOT DISTINCT FROM xml_sha256 AND octet_length(facts::text) <= 4096)
)""",
    """CREATE TABLE eis_notice_variant_origins (
company_id TEXT NOT NULL,
receipt_id TEXT NOT NULL,
archive_ordinal INTEGER NOT NULL,
member_filename TEXT NOT NULL,
archive_sha256 VARCHAR(64) NOT NULL,
purchase_number TEXT NOT NULL,
version_number INTEGER NOT NULL,
document_type TEXT NOT NULL,
xml_sha256 VARCHAR(64) NOT NULL,
CONSTRAINT pk_eis_notice_variant_origins PRIMARY KEY (company_id, receipt_id,
    archive_ordinal, member_filename),
CONSTRAINT fk_eis_variant_origin_receipt FOREIGN KEY(company_id, receipt_id) REFERENCES
    eis_notice_variant_receipts (company_id, receipt_id),
CONSTRAINT fk_eis_variant_origin_variant FOREIGN KEY(company_id, purchase_number,
    version_number, document_type, xml_sha256) REFERENCES eis_notice_variants (company_id,
    purchase_number, version_number, document_type, xml_sha256),
CONSTRAINT ck_eis_variant_origin_archive CHECK (archive_ordinal BETWEEN 0 AND 19 AND
    archive_sha256 ~ '^[0-9a-f]{64}$'),
CONSTRAINT ck_eis_variant_origin_member CHECK (char_length(member_filename) BETWEEN 4 AND
    255 AND strpos(member_filename, '/') = 0 AND strpos(member_filename, chr(92)) = 0 AND
    right(lower(member_filename), 4) = '.xml')
)""",
)
INDEXES = (
    """CREATE INDEX ix_eis_variant_receipts_window ON eis_notice_variant_receipts (company_id,
    window_key)""",
    """CREATE INDEX ix_eis_variant_origins_notice ON eis_notice_variant_origins (company_id,
    purchase_number, version_number)""",
)


def upgrade():
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for ddl in SCHEMA:
        op.execute(ddl)
    for name in TABLES:
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({tenant})")
        op.execute(f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({tenant})")
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
        )
        op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
            f"THEN GRANT SELECT, INSERT ON {name} TO procurement_app; END IF; END $$"
        )
    for ddl in INDEXES:
        op.execute(ddl)


def downgrade():
    op.execute("SET LOCAL row_security = off")
    condition = " OR ".join(f"EXISTS (SELECT 1 FROM {name})" for name in TABLES)
    op.execute(
        f"DO $$ BEGIN IF {condition} THEN RAISE EXCEPTION "
        "'notice variant evidence history must be preserved'; END IF; END $$"
    )
    for name in reversed(TABLES):
        op.drop_table(name)
