"""Persist one immutable safe receipt for the first AI transfer dispatch.

Revision ID: 20260917_06
Revises: 20260917_05
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_06"
down_revision: str | None = "20260917_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_transfer_dispatch_receipts"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_ai_transfer_dispatch_claim_receipt_binding",
        "ai_transfer_dispatch_claims",
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "chunk_id",
            "request_sha256",
            "payload_sha256",
        ],
    )
    op.execute(
        """
CREATE TABLE ai_transfer_dispatch_receipts (
    company_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    transfer_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    claim_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    claim_payload_sha256 VARCHAR(64) NOT NULL,
    receipt_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    attempted BOOLEAN NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    http_status INTEGER,
    capture_complete BOOLEAN NOT NULL,
    captured_byte_count INTEGER NOT NULL,
    response_body_sha256 VARCHAR(64),
    provider_response_id VARCHAR(500),
    provider_model VARCHAR(500),
    assistant_content_sha256 VARCHAR(64),
    assistant_content_byte_count INTEGER,
    validator_version TEXT NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    receipt JSONB NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    CONSTRAINT pk_ai_transfer_dispatch_receipts
        PRIMARY KEY (company_id, execution_id, ordinal),
    CONSTRAINT uq_ai_transfer_dispatch_receipt_id
        UNIQUE (company_id, receipt_id),
    CONSTRAINT fk_ai_transfer_receipt_exact_claim FOREIGN KEY (
        company_id, execution_id, transfer_id, ordinal, claim_id,
        chunk_id, request_sha256, claim_payload_sha256)
        REFERENCES ai_transfer_dispatch_claims (
            company_id, execution_id, transfer_id, ordinal, claim_id,
            chunk_id, request_sha256, payload_sha256),
    CONSTRAINT ck_ai_transfer_receipt_first_ordinal CHECK (ordinal = 1),
    CONSTRAINT ck_ai_transfer_receipt_id CHECK (btrim(receipt_id) <> ''),
    CONSTRAINT ck_ai_transfer_receipt_claim_id CHECK (btrim(claim_id) <> ''),
    CONSTRAINT ck_ai_transfer_receipt_actor CHECK (btrim(recorded_by) <> ''),
    CONSTRAINT ck_ai_transfer_receipt_claim_sha256 CHECK (
        claim_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_receipt_request_sha256 CHECK (
        request_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_receipt_event_sha256 CHECK (
        payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_receipt_response_sha256 CHECK (
        response_body_sha256 IS NULL OR
        response_body_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_receipt_content_sha256 CHECK (
        assistant_content_sha256 IS NULL OR
        assistant_content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_receipt_outcome CHECK (
        outcome IN ('SUCCESS', 'FAILED', 'DELIVERY_UNKNOWN')),
    CONSTRAINT ck_ai_transfer_receipt_status CHECK (status = 'TERMINAL'),
    CONSTRAINT ck_ai_transfer_receipt_reason CHECK (
        reason IN (
            'VALIDATED_RESPONSE', 'REDIRECT_REJECTED',
            'HTTP_STATUS_REJECTED', 'MALFORMED_RESPONSE_JSON',
            'INVALID_PROVIDER_ENVELOPE', 'MODEL_MISMATCH',
            'INVALID_WIRE_RESPONSE', 'TIMEOUT', 'NETWORK_ERROR',
            'RESPONSE_TOO_LARGE', 'INCOMPLETE_RESPONSE',
            'COMPRESSED_RESPONSE', 'APPROVAL_EXPIRED_BEFORE_DISPATCH')),
    CONSTRAINT ck_ai_transfer_receipt_validator CHECK (
        validator_version = 'ai-transfer-transport-validator-v1'),
    CONSTRAINT ck_ai_transfer_receipt_http_status CHECK (
        http_status IS NULL OR http_status BETWEEN 100 AND 599),
    CONSTRAINT ck_ai_transfer_receipt_captured_bytes CHECK (
        captured_byte_count >= 0),
    CONSTRAINT ck_ai_transfer_receipt_content_bytes CHECK (
        assistant_content_byte_count IS NULL OR
        assistant_content_byte_count >= 1),
    CONSTRAINT ck_ai_transfer_receipt_capture_digest CHECK (
        capture_complete = (response_body_sha256 IS NOT NULL)),
    CONSTRAINT ck_ai_transfer_receipt_provider_text CHECK (
        (provider_response_id IS NULL OR
         (btrim(provider_response_id) <> '' AND
          provider_response_id !~ '[[:cntrl:]]')) AND
        (provider_model IS NULL OR
         (btrim(provider_model) <> '' AND
          provider_model !~ '[[:cntrl:]]'))),
    CONSTRAINT ck_ai_transfer_receipt_provider_pair CHECK (
        (provider_response_id IS NULL) = (provider_model IS NULL)),
    CONSTRAINT ck_ai_transfer_receipt_content_pair CHECK (
        (assistant_content_sha256 IS NULL) =
        (assistant_content_byte_count IS NULL)),
    CONSTRAINT ck_ai_transfer_receipt_chronology CHECK (
        attempted = (started_at IS NOT NULL AND finished_at IS NOT NULL) AND
        (started_at IS NULL OR finished_at >= started_at) AND
        (finished_at IS NULL OR recorded_at >= finished_at)),
    CONSTRAINT ck_ai_transfer_receipt_terminal_semantics CHECK (
        ((outcome = 'SUCCESS') = (reason = 'VALIDATED_RESPONSE') AND
        (outcome = 'DELIVERY_UNKNOWN') =
            (reason IN ('TIMEOUT', 'NETWORK_ERROR', 'RESPONSE_TOO_LARGE',
                        'INCOMPLETE_RESPONSE', 'COMPRESSED_RESPONSE')) AND
        ((outcome = 'SUCCESS' AND attempted AND http_status = 200 AND
          capture_complete AND captured_byte_count >= 1 AND
          response_body_sha256 IS NOT NULL AND
          provider_response_id IS NOT NULL AND provider_model IS NOT NULL AND
          assistant_content_sha256 IS NOT NULL AND
          assistant_content_byte_count IS NOT NULL) OR
         (outcome = 'DELIVERY_UNKNOWN' AND attempted AND NOT capture_complete AND
          response_body_sha256 IS NULL AND provider_response_id IS NULL AND
          provider_model IS NULL AND assistant_content_sha256 IS NULL AND
          assistant_content_byte_count IS NULL) OR
         (outcome = 'FAILED' AND reason = 'REDIRECT_REJECTED' AND attempted AND
          http_status BETWEEN 300 AND 399 AND NOT capture_complete AND
          captured_byte_count = 0 AND response_body_sha256 IS NULL AND
          provider_response_id IS NULL AND provider_model IS NULL AND
          assistant_content_sha256 IS NULL AND
          assistant_content_byte_count IS NULL) OR
         (outcome = 'FAILED' AND reason = 'HTTP_STATUS_REJECTED' AND attempted AND
          http_status IS NOT NULL AND http_status <> 200 AND
          NOT (http_status BETWEEN 300 AND 399) AND
          capture_complete AND response_body_sha256 IS NOT NULL AND
          provider_response_id IS NULL AND provider_model IS NULL AND
          assistant_content_sha256 IS NULL AND
          assistant_content_byte_count IS NULL) OR
         (outcome = 'FAILED' AND reason IN
            ('MALFORMED_RESPONSE_JSON', 'INVALID_PROVIDER_ENVELOPE') AND
          attempted AND http_status = 200 AND capture_complete AND
          response_body_sha256 IS NOT NULL AND provider_response_id IS NULL AND
          provider_model IS NULL AND assistant_content_sha256 IS NULL AND
          assistant_content_byte_count IS NULL) OR
         (outcome = 'FAILED' AND reason IN
            ('MODEL_MISMATCH', 'INVALID_WIRE_RESPONSE') AND attempted AND
          http_status = 200 AND capture_complete AND
          response_body_sha256 IS NOT NULL AND provider_response_id IS NOT NULL AND
          provider_model IS NOT NULL AND assistant_content_sha256 IS NULL AND
          assistant_content_byte_count IS NULL) OR
         (outcome = 'FAILED' AND
          reason = 'APPROVAL_EXPIRED_BEFORE_DISPATCH' AND NOT attempted AND
          http_status IS NULL AND NOT capture_complete AND
          captured_byte_count = 0 AND response_body_sha256 IS NULL AND
          provider_response_id IS NULL AND provider_model IS NULL AND
          assistant_content_sha256 IS NULL AND
          assistant_content_byte_count IS NULL))) IS TRUE),
    CONSTRAINT ck_ai_transfer_receipt_identity CHECK (
        (jsonb_typeof(receipt) = 'object' AND
         receipt ?& ARRAY[
            'schema_version', 'company_id', 'transfer_id', 'execution_id',
            'ordinal', 'claim_id', 'chunk_id', 'claim_payload_sha256',
            'receipt_id', 'outcome',
            'reason', 'status', 'attempted', 'request_sha256', 'http_status',
            'capture_complete', 'captured_byte_count', 'response_body_sha256',
            'provider_response_id', 'provider_model',
            'assistant_content_sha256', 'assistant_content_byte_count',
            'validator_version', 'started_at', 'finished_at', 'recorded_by',
            'recorded_at', 'payload_sha256'] AND
         receipt - ARRAY[
            'schema_version', 'company_id', 'transfer_id', 'execution_id',
            'ordinal', 'claim_id', 'chunk_id', 'claim_payload_sha256',
            'receipt_id', 'outcome',
            'reason', 'status', 'attempted', 'request_sha256', 'http_status',
            'capture_complete', 'captured_byte_count', 'response_body_sha256',
            'provider_response_id', 'provider_model',
            'assistant_content_sha256', 'assistant_content_byte_count',
            'validator_version', 'started_at', 'finished_at', 'recorded_by',
            'recorded_at', 'payload_sha256'] = '{}'::jsonb AND
         receipt->>'schema_version' IS NOT DISTINCT FROM
            'ai-transfer-dispatch-receipt-v1' AND
         receipt->>'company_id' IS NOT DISTINCT FROM company_id AND
         receipt->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND
         receipt->>'execution_id' IS NOT DISTINCT FROM execution_id AND
         (receipt->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND
         receipt->>'claim_id' IS NOT DISTINCT FROM claim_id AND
         receipt->>'chunk_id' IS NOT DISTINCT FROM chunk_id AND
         receipt->>'claim_payload_sha256' IS NOT DISTINCT FROM
            claim_payload_sha256 AND
         receipt->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND
         receipt->>'outcome' IS NOT DISTINCT FROM outcome AND
         receipt->>'reason' IS NOT DISTINCT FROM reason AND
         receipt->>'status' IS NOT DISTINCT FROM status AND
         (receipt->>'attempted')::boolean IS NOT DISTINCT FROM attempted AND
         receipt->>'request_sha256' IS NOT DISTINCT FROM request_sha256 AND
         (receipt->>'http_status')::integer IS NOT DISTINCT FROM http_status AND
         (receipt->>'capture_complete')::boolean IS NOT DISTINCT FROM
            capture_complete AND
         (receipt->>'captured_byte_count')::integer IS NOT DISTINCT FROM
            captured_byte_count AND
         receipt->>'response_body_sha256' IS NOT DISTINCT FROM
            response_body_sha256 AND
         receipt->>'provider_response_id' IS NOT DISTINCT FROM
            provider_response_id AND
         receipt->>'provider_model' IS NOT DISTINCT FROM provider_model AND
         receipt->>'assistant_content_sha256' IS NOT DISTINCT FROM
            assistant_content_sha256 AND
         (receipt->>'assistant_content_byte_count')::integer IS NOT DISTINCT FROM
            assistant_content_byte_count AND
         receipt->>'validator_version' IS NOT DISTINCT FROM validator_version AND
         (receipt->>'started_at')::timestamptz IS NOT DISTINCT FROM started_at AND
         (receipt->>'finished_at')::timestamptz IS NOT DISTINCT FROM finished_at AND
         receipt->>'recorded_by' IS NOT DISTINCT FROM recorded_by AND
         (receipt->>'recorded_at')::timestamptz IS NOT DISTINCT FROM recorded_at AND
         receipt->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256) IS TRUE)
)
"""
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_receipt_claim_chronology()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    claimed_at TIMESTAMP WITH TIME ZONE;
    claiming_worker TEXT;
    approval_expires TIMESTAMP WITH TIME ZONE;
BEGIN
    SELECT c.claimed_at, c.claimed_by, e.approval_expires_at
      INTO claimed_at, claiming_worker, approval_expires
      FROM ai_transfer_dispatch_claims AS c
      JOIN ai_transfer_execution_admissions AS e
        ON e.company_id = c.company_id
       AND e.execution_id = c.execution_id
       AND e.transfer_id = c.transfer_id
       AND e.request_payload_sha256 = c.request_payload_sha256
       AND e.payload_sha256 = c.admission_payload_sha256
     WHERE c.company_id = NEW.company_id
       AND c.execution_id = NEW.execution_id
       AND c.transfer_id = NEW.transfer_id
       AND c.ordinal = NEW.ordinal
       AND c.claim_id = NEW.claim_id
       AND c.chunk_id = NEW.chunk_id
       AND c.request_sha256 = NEW.request_sha256
       AND c.payload_sha256 = NEW.claim_payload_sha256;
    IF NOT FOUND
       OR (NEW.attempted AND
           (NEW.started_at IS NULL OR NEW.started_at < claimed_at))
       OR NEW.recorded_at < claimed_at THEN
        RAISE EXCEPTION 'AI transfer receipt cannot precede its durable claim'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.recorded_by IS DISTINCT FROM claiming_worker THEN
        RAISE EXCEPTION 'AI transfer receipt must identify its claiming worker'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reason = 'APPROVAL_EXPIRED_BEFORE_DISPATCH' AND (
        clock_timestamp() < approval_expires
        OR NEW.recorded_at < approval_expires
        OR abs(extract(epoch FROM (NEW.recorded_at - clock_timestamp()))) > 2
    ) THEN
        RAISE EXCEPTION 'AI transfer approval has not expired or expiry receipt is not current'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        f"CREATE TRIGGER ai_transfer_receipt_claim_chronology BEFORE INSERT ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION enforce_ai_transfer_receipt_claim_chronology()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname = 'procurement_app') THEN "
        f"GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION enforce_ai_transfer_receipt_claim_chronology()")
    op.drop_constraint(
        "uq_ai_transfer_dispatch_claim_receipt_binding",
        "ai_transfer_dispatch_claims",
        type_="unique",
    )
