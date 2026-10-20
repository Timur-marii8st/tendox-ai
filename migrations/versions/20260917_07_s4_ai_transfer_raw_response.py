"""Persist encrypted AI transfer response bytes with exact 30-day retention.

Revision ID: 20260917_07
Revises: 20260917_06
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_07"
down_revision: str | None = "20260917_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METADATA_TABLE = "ai_transfer_raw_responses"
BLOB_TABLE = "ai_transfer_raw_response_blobs"
DELETION_TABLE = "ai_transfer_raw_response_deletion_receipts"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
        "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER', 'AUDITOR')",
    )
    op.create_unique_constraint(
        "uq_ai_transfer_dispatch_receipt_raw_binding",
        "ai_transfer_dispatch_receipts",
        [
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
        ],
    )
    op.execute(
        """
CREATE TABLE ai_transfer_raw_responses (
    company_id TEXT NOT NULL,
    raw_response_id TEXT NOT NULL,
    transfer_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    claim_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    claim_payload_sha256 VARCHAR(64) NOT NULL,
    receipt_id TEXT NOT NULL,
    receipt_payload_sha256 VARCHAR(64) NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    capture_complete BOOLEAN NOT NULL,
    response_body_sha256 VARCHAR(64) NOT NULL,
    response_byte_count INTEGER NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    schema_version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    key_id TEXT NOT NULL,
    body_aad_sha256 VARCHAR(64) NOT NULL,
    metadata_sha256 VARCHAR(64) NOT NULL,
    wrap_aad_sha256 VARCHAR(64) NOT NULL,
    envelope_sha256 VARCHAR(64) NOT NULL,
    metadata JSONB NOT NULL,
    CONSTRAINT pk_ai_transfer_raw_responses
        PRIMARY KEY (company_id, raw_response_id),
    CONSTRAINT uq_ai_transfer_raw_response_receipt
        UNIQUE (company_id, execution_id, ordinal),
    CONSTRAINT uq_ai_transfer_raw_metadata_binding UNIQUE (
        company_id, raw_response_id, receipt_id, response_body_sha256,
        response_byte_count, received_at, expires_at, schema_version,
        algorithm, key_id, body_aad_sha256, metadata_sha256,
        wrap_aad_sha256, envelope_sha256),
    CONSTRAINT fk_ai_transfer_raw_exact_receipt FOREIGN KEY (
        company_id, execution_id, transfer_id, ordinal, claim_id, chunk_id,
        claim_payload_sha256, receipt_id, receipt_payload_sha256,
        request_sha256, capture_complete, response_body_sha256,
        response_byte_count, received_at)
        REFERENCES ai_transfer_dispatch_receipts (
        company_id, execution_id, transfer_id, ordinal, claim_id, chunk_id,
        claim_payload_sha256, receipt_id, payload_sha256, request_sha256,
        capture_complete, response_body_sha256, captured_byte_count, finished_at)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_ai_transfer_raw_first_ordinal CHECK (ordinal = 1),
    CONSTRAINT ck_ai_transfer_raw_complete_capture CHECK (capture_complete),
    CONSTRAINT ck_ai_transfer_raw_response_bytes CHECK (
        response_byte_count BETWEEN 0 AND 4194304),
    CONSTRAINT ck_ai_transfer_raw_expiry CHECK (
        expires_at = received_at + interval '720 hours'),
    CONSTRAINT ck_ai_transfer_raw_schema CHECK (
        schema_version = 'ai-transfer-raw-metadata-v1'),
    CONSTRAINT ck_ai_transfer_raw_algorithm CHECK (
        algorithm = 'AES-256-GCM+TENANT-KEK-V1'),
    CONSTRAINT ck_ai_transfer_raw_safe_text CHECK (
        btrim(raw_response_id) <> '' AND raw_response_id !~ '[[:cntrl:]]' AND
        btrim(key_id) <> '' AND key_id !~ '[[:cntrl:]]'),
    CONSTRAINT ck_ai_transfer_raw_digests CHECK (
        claim_payload_sha256 ~ '^[0-9a-f]{64}$' AND
        receipt_payload_sha256 ~ '^[0-9a-f]{64}$' AND
        request_sha256 ~ '^[0-9a-f]{64}$' AND
        response_body_sha256 ~ '^[0-9a-f]{64}$' AND
        body_aad_sha256 ~ '^[0-9a-f]{64}$' AND
        metadata_sha256 ~ '^[0-9a-f]{64}$' AND
        wrap_aad_sha256 ~ '^[0-9a-f]{64}$' AND
        envelope_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_raw_metadata_identity CHECK (
        (jsonb_typeof(metadata) = 'object' AND
         metadata ?& ARRAY[
            'schema_version', 'company_id', 'raw_response_id', 'transfer_id',
            'execution_id', 'ordinal', 'claim_id', 'chunk_id',
            'claim_payload_sha256', 'receipt_id', 'receipt_payload_sha256',
            'request_sha256', 'response_body_sha256', 'response_byte_count',
            'received_at', 'expires_at', 'algorithm', 'key_id',
            'body_aad_sha256', 'metadata_sha256'] AND
         metadata - ARRAY[
            'schema_version', 'company_id', 'raw_response_id', 'transfer_id',
            'execution_id', 'ordinal', 'claim_id', 'chunk_id',
            'claim_payload_sha256', 'receipt_id', 'receipt_payload_sha256',
            'request_sha256', 'response_body_sha256', 'response_byte_count',
            'received_at', 'expires_at', 'algorithm', 'key_id',
            'body_aad_sha256', 'metadata_sha256'] = '{}'::jsonb AND
         metadata->>'schema_version' IS NOT DISTINCT FROM schema_version AND
         metadata->>'company_id' IS NOT DISTINCT FROM company_id AND
         metadata->>'raw_response_id' IS NOT DISTINCT FROM raw_response_id AND
         metadata->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND
         metadata->>'execution_id' IS NOT DISTINCT FROM execution_id AND
         (metadata->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND
         metadata->>'claim_id' IS NOT DISTINCT FROM claim_id AND
         metadata->>'chunk_id' IS NOT DISTINCT FROM chunk_id AND
         metadata->>'claim_payload_sha256' IS NOT DISTINCT FROM
            claim_payload_sha256 AND
         metadata->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND
         metadata->>'receipt_payload_sha256' IS NOT DISTINCT FROM
            receipt_payload_sha256 AND
         metadata->>'request_sha256' IS NOT DISTINCT FROM request_sha256 AND
         metadata->>'response_body_sha256' IS NOT DISTINCT FROM
            response_body_sha256 AND
         (metadata->>'response_byte_count')::integer IS NOT DISTINCT FROM
            response_byte_count AND
         (metadata->>'received_at')::timestamptz IS NOT DISTINCT FROM received_at AND
         (metadata->>'expires_at')::timestamptz IS NOT DISTINCT FROM expires_at AND
         metadata->>'algorithm' IS NOT DISTINCT FROM algorithm AND
         metadata->>'key_id' IS NOT DISTINCT FROM key_id AND
         metadata->>'body_aad_sha256' IS NOT DISTINCT FROM body_aad_sha256 AND
         metadata->>'metadata_sha256' IS NOT DISTINCT FROM metadata_sha256)
        IS TRUE)
)
"""
    )
    op.execute(
        """
CREATE TABLE ai_transfer_raw_response_blobs (
    company_id TEXT NOT NULL,
    raw_response_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    response_body_sha256 VARCHAR(64) NOT NULL,
    response_byte_count INTEGER NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata_schema_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    key_id TEXT NOT NULL,
    body_aad_sha256 VARCHAR(64) NOT NULL,
    metadata_sha256 VARCHAR(64) NOT NULL,
    wrap_aad_sha256 VARCHAR(64) NOT NULL,
    envelope_sha256 VARCHAR(64) NOT NULL,
    body_nonce BYTEA NOT NULL,
    ciphertext BYTEA NOT NULL,
    wrapping_nonce BYTEA NOT NULL,
    wrapped_dek BYTEA NOT NULL,
    CONSTRAINT pk_ai_transfer_raw_response_blobs
        PRIMARY KEY (company_id, raw_response_id),
    CONSTRAINT fk_ai_transfer_raw_blob_exact_metadata FOREIGN KEY (
        company_id, raw_response_id, receipt_id, response_body_sha256,
        response_byte_count, received_at, expires_at, metadata_schema_version,
        algorithm, key_id, body_aad_sha256, metadata_sha256,
        wrap_aad_sha256, envelope_sha256)
        REFERENCES ai_transfer_raw_responses (
        company_id, raw_response_id, receipt_id, response_body_sha256,
        response_byte_count, received_at, expires_at, schema_version,
        algorithm, key_id, body_aad_sha256, metadata_sha256,
        wrap_aad_sha256, envelope_sha256) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_ai_transfer_raw_blob_schema CHECK (
        schema_version = 'ai-transfer-raw-envelope-v1'),
    CONSTRAINT ck_ai_transfer_raw_blob_nonces CHECK (
        octet_length(body_nonce) = 12 AND
        octet_length(wrapping_nonce) = 12 AND
        body_nonce <> wrapping_nonce),
    CONSTRAINT ck_ai_transfer_raw_blob_ciphertext CHECK (
        octet_length(ciphertext) = response_byte_count + 16),
    CONSTRAINT ck_ai_transfer_raw_blob_wrapped_dek CHECK (
        octet_length(wrapped_dek) = 48)
)
"""
    )
    op.execute(
        """
CREATE TABLE ai_transfer_raw_response_deletion_receipts (
    company_id TEXT NOT NULL,
    raw_response_id TEXT NOT NULL,
    deletion_receipt_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    response_body_sha256 VARCHAR(64) NOT NULL,
    response_byte_count INTEGER NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata_schema_version TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    key_id TEXT NOT NULL,
    body_aad_sha256 VARCHAR(64) NOT NULL,
    metadata_sha256 VARCHAR(64) NOT NULL,
    wrap_aad_sha256 VARCHAR(64) NOT NULL,
    envelope_sha256 VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    deleted_by TEXT NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    deletion_receipt JSONB NOT NULL,
    CONSTRAINT pk_ai_transfer_raw_response_deletion_receipts
        PRIMARY KEY (company_id, raw_response_id),
    CONSTRAINT uq_ai_transfer_raw_deletion_receipt_id
        UNIQUE (company_id, deletion_receipt_id),
    CONSTRAINT fk_ai_transfer_raw_deletion_exact_metadata FOREIGN KEY (
        company_id, raw_response_id, receipt_id, response_body_sha256,
        response_byte_count, received_at, expires_at, metadata_schema_version,
        algorithm, key_id, body_aad_sha256, metadata_sha256,
        wrap_aad_sha256, envelope_sha256)
        REFERENCES ai_transfer_raw_responses (
        company_id, raw_response_id, receipt_id, response_body_sha256,
        response_byte_count, received_at, expires_at, schema_version,
        algorithm, key_id, body_aad_sha256, metadata_sha256,
        wrap_aad_sha256, envelope_sha256),
    CONSTRAINT ck_ai_transfer_raw_deletion_safe_text CHECK (
        btrim(deletion_receipt_id) <> '' AND
        deletion_receipt_id !~ '[[:cntrl:]]' AND
        btrim(deleted_by) <> '' AND deleted_by !~ '[[:cntrl:]]'),
    CONSTRAINT ck_ai_transfer_raw_deletion_reason CHECK (
        reason = 'RETENTION_EXPIRED'),
    CONSTRAINT ck_ai_transfer_raw_deletion_expired CHECK (
        deleted_at >= expires_at),
    CONSTRAINT ck_ai_transfer_raw_deletion_digests CHECK (
        response_body_sha256 ~ '^[0-9a-f]{64}$' AND
        body_aad_sha256 ~ '^[0-9a-f]{64}$' AND
        metadata_sha256 ~ '^[0-9a-f]{64}$' AND
        wrap_aad_sha256 ~ '^[0-9a-f]{64}$' AND
        envelope_sha256 ~ '^[0-9a-f]{64}$' AND
        payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_raw_deletion_identity CHECK (
        (jsonb_typeof(deletion_receipt) = 'object' AND
         deletion_receipt ?& ARRAY[
            'schema_version', 'company_id', 'raw_response_id',
            'deletion_receipt_id', 'receipt_id', 'response_body_sha256',
            'response_byte_count', 'received_at', 'expires_at', 'algorithm',
            'metadata_schema_version', 'key_id', 'body_aad_sha256',
            'metadata_sha256', 'wrap_aad_sha256', 'envelope_sha256',
            'reason', 'deleted_by', 'deleted_at', 'payload_sha256'] AND
         deletion_receipt - ARRAY[
            'schema_version', 'company_id', 'raw_response_id',
            'deletion_receipt_id', 'receipt_id', 'response_body_sha256',
            'response_byte_count', 'received_at', 'expires_at', 'algorithm',
            'metadata_schema_version', 'key_id', 'body_aad_sha256',
            'metadata_sha256', 'wrap_aad_sha256', 'envelope_sha256',
            'reason', 'deleted_by', 'deleted_at', 'payload_sha256'] = '{}'::jsonb AND
         deletion_receipt->>'schema_version' IS NOT DISTINCT FROM
            'ai-transfer-raw-deletion-receipt-v1' AND
         deletion_receipt->>'company_id' IS NOT DISTINCT FROM company_id AND
         deletion_receipt->>'raw_response_id' IS NOT DISTINCT FROM
            raw_response_id AND
         deletion_receipt->>'deletion_receipt_id' IS NOT DISTINCT FROM
            deletion_receipt_id AND
         deletion_receipt->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND
         deletion_receipt->>'response_body_sha256' IS NOT DISTINCT FROM
            response_body_sha256 AND
         (deletion_receipt->>'response_byte_count')::integer IS NOT DISTINCT FROM
            response_byte_count AND
         (deletion_receipt->>'received_at')::timestamptz IS NOT DISTINCT FROM
            received_at AND
         (deletion_receipt->>'expires_at')::timestamptz IS NOT DISTINCT FROM
            expires_at AND
         deletion_receipt->>'metadata_schema_version' IS NOT DISTINCT FROM
            metadata_schema_version AND
         deletion_receipt->>'algorithm' IS NOT DISTINCT FROM algorithm AND
         deletion_receipt->>'key_id' IS NOT DISTINCT FROM key_id AND
         deletion_receipt->>'body_aad_sha256' IS NOT DISTINCT FROM
            body_aad_sha256 AND
         deletion_receipt->>'metadata_sha256' IS NOT DISTINCT FROM
            metadata_sha256 AND
         deletion_receipt->>'wrap_aad_sha256' IS NOT DISTINCT FROM
            wrap_aad_sha256 AND
         deletion_receipt->>'envelope_sha256' IS NOT DISTINCT FROM
            envelope_sha256 AND
         deletion_receipt->>'reason' IS NOT DISTINCT FROM reason AND
         deletion_receipt->>'deleted_by' IS NOT DISTINCT FROM deleted_by AND
         (deletion_receipt->>'deleted_at')::timestamptz IS NOT DISTINCT FROM
            deleted_at AND
         deletion_receipt->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256)
        IS TRUE)
)
"""
    )
    op.create_index(
        "ix_ai_transfer_raw_company_expiry",
        METADATA_TABLE,
        ["company_id", "expires_at", "raw_response_id"],
    )
    _create_retention_enforcement()
    _secure_tables()


def _create_retention_enforcement() -> None:
    op.execute(
        """
CREATE FUNCTION require_ai_transfer_complete_receipt_raw()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.capture_complete AND NOT EXISTS (
        SELECT 1 FROM ai_transfer_raw_responses AS r
        JOIN ai_transfer_raw_response_blobs AS b
          ON b.company_id = r.company_id
         AND b.raw_response_id = r.raw_response_id
         WHERE r.company_id = NEW.company_id
           AND r.execution_id = NEW.execution_id
           AND r.ordinal = NEW.ordinal
           AND r.receipt_id = NEW.receipt_id) THEN
        RAISE EXCEPTION 'complete AI transfer receipt requires encrypted raw response'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$
"""
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_transfer_complete_receipt_requires_raw "
        "AFTER INSERT ON ai_transfer_dispatch_receipts "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION require_ai_transfer_complete_receipt_raw()"
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_raw_metadata_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF clock_timestamp() >= NEW.expires_at THEN
        RAISE EXCEPTION 'expired AI transfer raw response cannot be inserted'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_raw_metadata_insert_guard "
        f"BEFORE INSERT ON {METADATA_TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_raw_metadata_insert()"
    )
    op.execute(
        """
CREATE FUNCTION require_ai_transfer_raw_blob()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ai_transfer_raw_response_blobs AS b
         WHERE b.company_id = NEW.company_id
           AND b.raw_response_id = NEW.raw_response_id) THEN
        RAISE EXCEPTION 'AI transfer raw metadata requires one encrypted blob'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$
"""
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_transfer_raw_metadata_requires_blob "
        f"AFTER INSERT ON {METADATA_TABLE} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION require_ai_transfer_raw_blob()"
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_raw_blob_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF clock_timestamp() >= NEW.expires_at OR EXISTS (
        SELECT 1 FROM ai_transfer_raw_response_deletion_receipts AS d
         WHERE d.company_id = NEW.company_id
           AND d.raw_response_id = NEW.raw_response_id) THEN
        RAISE EXCEPTION 'expired or deleted AI transfer raw blob cannot be inserted'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_raw_blob_insert_guard "
        f"BEFORE INSERT ON {BLOB_TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_raw_blob_insert()"
    )
    # Recheck after unique-index waits: an INSERT can start before expiry and
    # resume only after a concurrent purge has deleted the previous primary key.
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_transfer_raw_blob_commit_guard "
        f"AFTER INSERT ON {BLOB_TABLE} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION enforce_ai_transfer_raw_blob_insert()"
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_raw_blob_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF clock_timestamp() < OLD.expires_at
       OR NOT EXISTS (
            SELECT 1 FROM ai_transfer_raw_response_deletion_receipts AS d
             WHERE d.company_id = OLD.company_id
               AND d.raw_response_id = OLD.raw_response_id) THEN
        RAISE EXCEPTION 'AI transfer raw blob deletion is not expired or receipted'
            USING ERRCODE = '23514';
    END IF;
    RETURN OLD;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_raw_blob_delete_guard "
        f"BEFORE DELETE ON {BLOB_TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_raw_blob_delete()"
    )
    op.execute(
        """
CREATE FUNCTION require_ai_transfer_raw_deletion_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ai_transfer_raw_response_deletion_receipts AS d
         WHERE d.company_id = OLD.company_id
           AND d.raw_response_id = OLD.raw_response_id) THEN
        RAISE EXCEPTION 'AI transfer raw blob deletion requires a receipt'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$
"""
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_transfer_raw_blob_requires_deletion_receipt "
        f"AFTER DELETE ON {BLOB_TABLE} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION require_ai_transfer_raw_deletion_receipt()"
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_raw_deletion_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF clock_timestamp() < NEW.expires_at
       OR abs(extract(epoch FROM (NEW.deleted_at - clock_timestamp()))) > 2 THEN
        RAISE EXCEPTION 'AI transfer raw deletion receipt is not current or expired'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_raw_deletion_insert_guard "
        f"BEFORE INSERT ON {DELETION_TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_raw_deletion_insert()"
    )
    op.execute(
        """
CREATE FUNCTION require_ai_transfer_raw_blob_absent()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_transfer_raw_response_blobs AS b
         WHERE b.company_id = NEW.company_id
           AND b.raw_response_id = NEW.raw_response_id) THEN
        RAISE EXCEPTION 'AI transfer raw deletion receipt requires blob deletion'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$
"""
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_transfer_raw_deletion_requires_blob_absent "
        f"AFTER INSERT ON {DELETION_TABLE} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION require_ai_transfer_raw_blob_absent()"
    )


def _secure_tables() -> None:
    for table in (METADATA_TABLE, BLOB_TABLE, DELETION_TABLE):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({TENANT})")
        op.execute(f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({TENANT})")
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(f"CREATE POLICY {BLOB_TABLE}_delete ON {BLOB_TABLE} FOR DELETE USING ({TENANT})")
    op.execute(
        f"CREATE TRIGGER {METADATA_TABLE}_immutable BEFORE UPDATE OR DELETE "
        f"ON {METADATA_TABLE} FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {BLOB_TABLE}_immutable BEFORE UPDATE ON {BLOB_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {DELETION_TABLE}_immutable BEFORE UPDATE OR DELETE "
        f"ON {DELETION_TABLE} FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname = 'procurement_app') THEN "
        f"GRANT SELECT, INSERT ON {METADATA_TABLE} TO procurement_app; "
        f"GRANT SELECT, INSERT, DELETE ON {BLOB_TABLE} TO procurement_app; "
        f"GRANT SELECT, INSERT ON {DELETION_TABLE} TO procurement_app; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER ai_transfer_complete_receipt_requires_raw ON ai_transfer_dispatch_receipts"
    )
    op.execute("DROP FUNCTION require_ai_transfer_complete_receipt_raw()")
    op.drop_index("ix_ai_transfer_raw_company_expiry", table_name=METADATA_TABLE)
    op.drop_table(DELETION_TABLE)
    op.drop_table(BLOB_TABLE)
    op.drop_table(METADATA_TABLE)
    for function in (
        "require_ai_transfer_raw_blob_absent",
        "enforce_ai_transfer_raw_deletion_insert",
        "require_ai_transfer_raw_deletion_receipt",
        "enforce_ai_transfer_raw_blob_delete",
        "enforce_ai_transfer_raw_blob_insert",
        "require_ai_transfer_raw_blob",
        "enforce_ai_transfer_raw_metadata_insert",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_constraint(
        "uq_ai_transfer_dispatch_receipt_raw_binding",
        "ai_transfer_dispatch_receipts",
        type_="unique",
    )
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
        "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER')",
    )
