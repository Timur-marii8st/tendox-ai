"""Frozen explicit retained projection; transport never supplies a checkpoint."""

from alembic import op

revision = "20261004_03"
down_revision = "20261004_02"
branch_labels = None
depends_on = None
TABLES = ("eis_notice_projection_batches", "eis_notice_projection_decisions")

SCHEMA = (
    """CREATE TABLE eis_notice_projection_batches (
	company_id TEXT NOT NULL, 
	batch_id TEXT NOT NULL, 
	receipt_id TEXT NOT NULL, 
	window_key TEXT NOT NULL, 
	response_sha256 VARCHAR(64) NOT NULL, 
	parser_version TEXT NOT NULL, 
	archive_sha256s JSONB NOT NULL, 
	occurrence_count INTEGER NOT NULL, 
	pair_count INTEGER NOT NULL, 
	projected_count INTEGER NOT NULL, 
	replayed_count INTEGER NOT NULL, 
	held_count INTEGER NOT NULL, 
	payload_sha256 VARCHAR(64) NOT NULL, 
	audit_event_id TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_eis_notice_projection_batches PRIMARY KEY (company_id, batch_id), 
	CONSTRAINT uq_eis_projection_basis UNIQUE (company_id, receipt_id, parser_version), 
CONSTRAINT fk_eis_projection_receipt FOREIGN KEY(company_id, receipt_id) REFERENCES
    eis_notice_variant_receipts (company_id, receipt_id),
CONSTRAINT fk_eis_projection_window FOREIGN KEY(company_id, window_key, response_sha256)
    REFERENCES eis_feed_windows (company_id, window_key, response_sha256),
CONSTRAINT fk_eis_projection_audit FOREIGN KEY(company_id, audit_event_id) REFERENCES
    audit_events (company_id, event_id) DEFERRABLE INITIALLY DEFERRED,
CONSTRAINT ck_eis_projection_text CHECK (btrim(company_id) <> '' AND btrim(window_key) <> ''
    AND parser_version = 'eis-notice-projection-v1'),
CONSTRAINT ck_eis_projection_identity CHECK (batch_id ~
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND payload_sha256 ~
    '^[0-9a-f]{64}$'),
CONSTRAINT ck_eis_projection_counts CHECK (occurrence_count BETWEEN 1 AND 2000 AND
    pair_count BETWEEN 1 AND occurrence_count AND projected_count >= 0 AND replayed_count >=
    0 AND held_count >= 0 AND projected_count + replayed_count + held_count = pair_count AND
    jsonb_typeof(archive_sha256s) = 'array' AND jsonb_array_length(archive_sha256s) BETWEEN
    1 AND 20)
)""",
    """CREATE TABLE eis_notice_projection_decisions (
	company_id TEXT NOT NULL, 
	batch_id TEXT NOT NULL, 
	purchase_number TEXT NOT NULL, 
	version_number INTEGER NOT NULL, 
	document_type TEXT, 
	xml_sha256 VARCHAR(64), 
	status TEXT NOT NULL, 
	reason TEXT, 
	input_sha256 VARCHAR(64) NOT NULL, 
	snapshot_sha256 VARCHAR(64), 
	snapshot JSONB, 
	archive_sha256 VARCHAR(64), 
	member_filename TEXT, 
CONSTRAINT pk_eis_notice_projection_decisions PRIMARY KEY (company_id, batch_id,
    purchase_number, version_number),
CONSTRAINT fk_eis_projection_decision_batch FOREIGN KEY(company_id, batch_id) REFERENCES
    eis_notice_projection_batches (company_id, batch_id),
CONSTRAINT ck_eis_projection_decision_identity CHECK (purchase_number ~ '^[0-9]{19,23}$' AND
    version_number >= 1 AND input_sha256 ~ '^[0-9a-f]{64}$'),
CONSTRAINT ck_eis_projection_decision_status CHECK (status IN ('PROJECTED', 'REPLAYED',
    'HOLD') AND ((status = 'HOLD' AND reason IS NOT NULL AND btrim(reason) <> '' AND
    snapshot IS NULL AND snapshot_sha256 IS NULL) OR (status IN ('PROJECTED', 'REPLAYED')
    AND reason IS NULL AND snapshot IS NOT NULL AND snapshot_sha256 IS NOT NULL AND
    xml_sha256 IS NOT NULL AND document_type IS NOT NULL AND archive_sha256 IS NOT NULL AND
    member_filename IS NOT NULL))),
CONSTRAINT ck_eis_projection_decision_sha CHECK ((xml_sha256 IS NULL OR xml_sha256 ~
    '^[0-9a-f]{64}$') AND (snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$')
    AND (archive_sha256 IS NULL OR archive_sha256 ~ '^[0-9a-f]{64}$')),
CONSTRAINT ck_eis_projection_decision_snapshot CHECK (snapshot IS NULL OR
    (jsonb_typeof(snapshot) = 'object' AND octet_length(snapshot::text) <= 2097152 AND
    snapshot->>'purchase_number' IS NOT DISTINCT FROM purchase_number AND
    (snapshot->>'version_number')::integer IS NOT DISTINCT FROM version_number AND
    snapshot->>'document_type' IS NOT DISTINCT FROM document_type AND
    snapshot->>'xml_sha256' IS NOT DISTINCT FROM xml_sha256))
)""",
)
INDEXES = (
    """CREATE INDEX ix_eis_projection_decision_notice ON eis_notice_projection_decisions
    (company_id, purchase_number, version_number)""",
)


def upgrade():
    # An older bootstrap migration copies metadata; accept only the exact shape.
    op.execute(
        "ALTER TABLE eis_feed_windows ADD COLUMN IF NOT EXISTS intake_kind TEXT NOT NULL "
        "DEFAULT 'LEGACY_CANONICAL'"
    )
    op.execute(
        "DO $check$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_attribute a JOIN pg_attrdef d ON "
        "d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE "
        "a.attrelid='eis_feed_windows'::regclass AND a.attname='intake_kind' AND "
        "a.atttypid='text'::regtype AND a.attnotnull AND pg_get_expr(d.adbin,d.adrelid) = "
        "$$'LEGACY_CANONICAL'::text$$) THEN RAISE EXCEPTION 'unexpected intake kind column'; "
        "END IF; END $check$"
    )
    op.execute(
        "DO $check$ BEGIN IF EXISTS (SELECT 1 FROM pg_constraint WHERE "
        "conrelid='eis_feed_windows'::regclass AND conname='ck_eis_feed_windows_intake_kind' "
        "AND (NOT convalidated OR pg_get_constraintdef(oid) <> "
        "$$CHECK ((intake_kind = ANY (ARRAY['LEGACY_CANONICAL'::text, "
        "'VARIANT_TRANSPORT'::text])))$$)) THEN RAISE EXCEPTION "
        "'unexpected intake kind constraint'; END IF; END $check$"
    )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE "
        "conrelid='eis_feed_windows'::regclass AND conname='ck_eis_feed_windows_intake_kind') "
        "THEN ALTER TABLE eis_feed_windows ADD CONSTRAINT ck_eis_feed_windows_intake_kind "
        "CHECK (intake_kind IN ('LEGACY_CANONICAL', 'VARIANT_TRANSPORT')); END IF; END $$"
    )
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
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_feed_windows WHERE "
        "intake_kind='VARIANT_TRANSPORT') OR EXISTS (SELECT 1 FROM "
        "eis_notice_projection_batches) OR EXISTS (SELECT 1 FROM "
        "eis_notice_projection_decisions) THEN RAISE EXCEPTION 'notice projection history "
        "must be preserved'; END IF; END $$"
    )
    for name in reversed(TABLES):
        op.drop_table(name)
    op.drop_constraint("ck_eis_feed_windows_intake_kind", "eis_feed_windows", type_="check")
    op.drop_column("eis_feed_windows", "intake_kind")
