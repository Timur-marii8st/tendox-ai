"""Persist exact AI transfer requests and independent fifteen-minute approvals.

Revision ID: 20260917_04
Revises: 20260917_03
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_04"
down_revision: str | None = "20260917_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("ai_transfer_requests", "ai_transfer_chunks", "ai_transfer_approvals")
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_documents_exact_source", "documents", ["company_id", "document_id", "sha256"]
    )
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
        "'AI_REQUIREMENTS_REVIEWER', 'AI_TRANSFER_APPROVER')",
    )
    op.execute(
        """
CREATE TABLE ai_transfer_requests (
    company_id TEXT NOT NULL, 
    transfer_id TEXT NOT NULL, 
    source_document_id TEXT NOT NULL, 
    source_sha256 VARCHAR(64) NOT NULL, 
    payload_sha256 VARCHAR(64) NOT NULL, 
    chunk_count INTEGER NOT NULL, 
    request JSONB NOT NULL, 
    prepared_by TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_ai_transfer_requests PRIMARY KEY (company_id, transfer_id), 
    CONSTRAINT uq_ai_transfer_payload UNIQUE (company_id, transfer_id, payload_sha256), 
    CONSTRAINT fk_ai_transfer_source FOREIGN KEY(
        company_id, source_document_id, source_sha256)
        REFERENCES documents (company_id, document_id, sha256), 
    CONSTRAINT ck_ai_transfer_chunk_count CHECK (chunk_count BETWEEN 1 AND 9999), 
    CONSTRAINT ck_ai_transfer_payload_sha256 CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'), 
    CONSTRAINT ck_ai_transfer_preparer CHECK (btrim(prepared_by) <> ''), 
    CONSTRAINT ck_ai_transfer_request_identity CHECK (
        (jsonb_typeof(request) = 'object' AND
        jsonb_typeof(request->'chunks') = 'array' AND
        request->>'schema_version' = 'persisted-ai-transfer-request-v1' AND
        request->>'company_id' = company_id AND
        request->>'transfer_id' = transfer_id AND
        request->>'source_document_id' = source_document_id AND
        request->>'source_sha256' = source_sha256 AND
        request->>'payload_sha256' = payload_sha256 AND
        request->>'prepared_by' = prepared_by AND
        (request->>'prepared_at')::timestamptz = created_at AND
        request->>'source_binding' = 'VERIFIED_PERSISTED_SOURCE' AND
        request->>'document_role' = 'TENDER_REQUIREMENTS' AND
        request->>'retention' = 'RAW_RESPONSE_30_DAYS_V1' AND
        request->>'execution' = 'ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1') IS TRUE)
)

"""
    )
    op.execute(
        """
CREATE TABLE ai_transfer_chunks (
    company_id TEXT NOT NULL, 
    transfer_id TEXT NOT NULL, 
    payload_sha256 VARCHAR(64) NOT NULL, 
    ordinal INTEGER NOT NULL, 
    chunk_id TEXT NOT NULL, 
    request_body_json TEXT NOT NULL, 
    request_sha256 VARCHAR(64) NOT NULL, 
    chunk JSONB NOT NULL, 
    CONSTRAINT pk_ai_transfer_chunks PRIMARY KEY (company_id, transfer_id, ordinal), 
    CONSTRAINT uq_ai_transfer_chunk_id UNIQUE (company_id, transfer_id, chunk_id), 
    CONSTRAINT fk_ai_transfer_chunk_request FOREIGN KEY(
        company_id, transfer_id, payload_sha256)
        REFERENCES ai_transfer_requests (company_id, transfer_id, payload_sha256), 
    CONSTRAINT ck_ai_transfer_chunk_ordinal CHECK (ordinal BETWEEN 1 AND 9999), 
    CONSTRAINT ck_ai_transfer_chunk_id CHECK (chunk_id = 'chunk-' || lpad(ordinal::text, 4, '0')), 
    CONSTRAINT ck_ai_transfer_chunk_body_digest CHECK (
        request_sha256 = encode(sha256(convert_to(request_body_json, 'UTF8')), 'hex')), 
    CONSTRAINT ck_ai_transfer_chunk_identity CHECK (
        (jsonb_typeof(chunk) = 'object' AND
        chunk->>'chunk_id' = chunk_id AND
        chunk->>'request_body_json' = request_body_json AND
        chunk->>'request_sha256' = request_sha256 AND
        jsonb_typeof(chunk->'source_block_ids') = 'array') IS TRUE)
)

"""
    )
    op.execute(
        """
CREATE TABLE ai_transfer_approvals (
    company_id TEXT NOT NULL, 
    transfer_id TEXT NOT NULL, 
    request_payload_sha256 VARCHAR(64) NOT NULL, 
    approval JSONB NOT NULL, 
    approved_by TEXT NOT NULL, 
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_ai_transfer_approvals PRIMARY KEY (company_id, transfer_id), 
    CONSTRAINT fk_ai_transfer_approval_request FOREIGN KEY(
        company_id, transfer_id, request_payload_sha256)
        REFERENCES ai_transfer_requests (company_id, transfer_id, payload_sha256), 
    CONSTRAINT ck_ai_transfer_approver CHECK (btrim(approved_by) <> ''), 
    CONSTRAINT ck_ai_transfer_approval_expiry CHECK (
        expires_at = approved_at + interval '15 minutes'), 
    CONSTRAINT ck_ai_transfer_approval_identity CHECK (
        (jsonb_typeof(approval) = 'object' AND
        approval->>'schema_version' = 'persisted-ai-transfer-approval-v1' AND
        approval->>'company_id' = company_id AND
        approval->>'transfer_id' = transfer_id AND
        approval->>'request_payload_sha256' = request_payload_sha256 AND
        approval->>'status' = 'APPROVED' AND
        approval->>'approved_by' = approved_by AND
        (approval->>'approved_at')::timestamptz = approved_at AND
        (approval->>'expires_at')::timestamptz = expires_at) IS TRUE)
)

"""
    )
    op.execute(
        """
        CREATE FUNCTION enforce_ai_transfer_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            expected jsonb;
            expected_count integer;
            actual jsonb;
            actual_count integer;
            first_ordinal integer;
            last_ordinal integer;
        BEGIN
            SELECT request->'chunks', chunk_count INTO expected, expected_count
              FROM ai_transfer_requests
             WHERE company_id = NEW.company_id AND transfer_id = NEW.transfer_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'AI transfer request is absent' USING ERRCODE = '23514';
            END IF;
            SELECT COALESCE(jsonb_agg(chunk ORDER BY ordinal), '[]'::jsonb),
                   count(*)::integer, min(ordinal), max(ordinal)
              INTO actual, actual_count, first_ordinal, last_ordinal
              FROM ai_transfer_chunks
             WHERE company_id = NEW.company_id AND transfer_id = NEW.transfer_id;
            IF jsonb_array_length(expected) IS DISTINCT FROM expected_count
               OR actual_count IS DISTINCT FROM expected_count
               OR first_ordinal IS DISTINCT FROM 1
               OR last_ordinal IS DISTINCT FROM expected_count
               OR actual IS DISTINCT FROM expected THEN
                RAISE EXCEPTION 'AI transfer chunks do not match exact request'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for table in ("ai_transfer_requests", "ai_transfer_chunks"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_consistency AFTER INSERT ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION enforce_ai_transfer_consistency()"
        )
    op.execute(
        """
        CREATE FUNCTION enforce_ai_transfer_approval()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            preparer text;
            prepared timestamptz;
        BEGIN
            SELECT prepared_by, created_at INTO preparer, prepared
              FROM ai_transfer_requests
             WHERE company_id = NEW.company_id AND transfer_id = NEW.transfer_id
               AND payload_sha256 = NEW.request_payload_sha256;
            IF NOT FOUND OR btrim(NEW.approved_by) = btrim(preparer)
               OR NEW.approved_at < prepared
               OR NEW.expires_at <> NEW.approved_at + interval '15 minutes' THEN
                RAISE EXCEPTION 'AI transfer approval is not independent and exact'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_approval_binding BEFORE INSERT ON ai_transfer_approvals "
        "FOR EACH ROW EXECUTE FUNCTION enforce_ai_transfer_approval()"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({TENANT})")
        op.execute(f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({TENANT})")
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
        )
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles "
            "WHERE rolname = 'procurement_app') THEN "
            f"GRANT SELECT, INSERT ON {table} TO procurement_app; END IF; END $$"
        )


def downgrade() -> None:
    op.execute("DROP FUNCTION enforce_ai_transfer_consistency() CASCADE")
    op.execute("DROP FUNCTION enforce_ai_transfer_approval() CASCADE")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_constraint("uq_documents_exact_source", "documents", type_="unique")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
        "'AI_REQUIREMENTS_REVIEWER')",
    )
