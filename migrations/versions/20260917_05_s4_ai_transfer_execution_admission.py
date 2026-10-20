"""Persist one AI transfer admission and its permanent first dispatch claim.

Revision ID: 20260917_05
Revises: 20260917_04
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_05"
down_revision: str | None = "20260917_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("ai_transfer_execution_admissions", "ai_transfer_dispatch_claims")
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_ai_transfer_approval_exact",
        "ai_transfer_approvals",
        ["company_id", "transfer_id", "request_payload_sha256"],
    )
    op.create_unique_constraint(
        "uq_ai_transfer_chunk_dispatch_binding",
        "ai_transfer_chunks",
        [
            "company_id",
            "transfer_id",
            "payload_sha256",
            "ordinal",
            "chunk_id",
            "request_sha256",
        ],
    )
    op.execute(
        """
CREATE TABLE ai_transfer_execution_admissions (
    company_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    transfer_id TEXT NOT NULL,
    request_payload_sha256 VARCHAR(64) NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL,
    approval_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    chunk_count INTEGER NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    admission JSONB NOT NULL,
    admitted_by TEXT NOT NULL,
    admitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_ai_transfer_execution_admissions
        PRIMARY KEY (company_id, execution_id),
    CONSTRAINT uq_ai_transfer_execution_transfer UNIQUE (company_id, transfer_id),
    CONSTRAINT uq_ai_transfer_execution_binding UNIQUE (
        company_id, execution_id, transfer_id,
        request_payload_sha256, payload_sha256),
    CONSTRAINT fk_ai_transfer_admission_request FOREIGN KEY (
        company_id, transfer_id, request_payload_sha256)
        REFERENCES ai_transfer_requests (company_id, transfer_id, payload_sha256),
    CONSTRAINT fk_ai_transfer_admission_approval FOREIGN KEY (
        company_id, transfer_id, request_payload_sha256)
        REFERENCES ai_transfer_approvals (
            company_id, transfer_id, request_payload_sha256),
    CONSTRAINT ck_ai_transfer_admission_payload_sha256 CHECK (
        request_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_admission_event_sha256 CHECK (
        payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_admission_chunks CHECK (chunk_count BETWEEN 1 AND 9999),
    CONSTRAINT ck_ai_transfer_admission_approval_window CHECK (
        approval_expires_at = approved_at + interval '15 minutes'),
    CONSTRAINT ck_ai_transfer_admission_execution_id CHECK (btrim(execution_id) <> ''),
    CONSTRAINT ck_ai_transfer_admission_approver CHECK (btrim(approved_by) <> ''),
    CONSTRAINT ck_ai_transfer_admission_actor CHECK (btrim(admitted_by) <> ''),
    CONSTRAINT ck_ai_transfer_admission_identity CHECK (
        (jsonb_typeof(admission) = 'object' AND
        admission->>'schema_version' IS NOT DISTINCT FROM
            'ai-transfer-execution-admission-v1' AND
        admission->>'company_id' IS NOT DISTINCT FROM company_id AND
        admission->>'execution_id' IS NOT DISTINCT FROM execution_id AND
        admission->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND
        admission->>'request_payload_sha256' IS NOT DISTINCT FROM
            request_payload_sha256 AND
        admission->>'approved_by' IS NOT DISTINCT FROM approved_by AND
        (admission->>'approved_at')::timestamptz IS NOT DISTINCT FROM approved_at AND
        (admission->>'approval_expires_at')::timestamptz IS NOT DISTINCT FROM
            approval_expires_at AND
        (admission->>'chunk_count')::integer IS NOT DISTINCT FROM chunk_count AND
        admission->>'status' IS NOT DISTINCT FROM 'ADMITTED' AND
        admission->>'execution_policy' IS NOT DISTINCT FROM
            'ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1' AND
        admission->>'admitted_by' IS NOT DISTINCT FROM admitted_by AND
        (admission->>'admitted_at')::timestamptz IS NOT DISTINCT FROM admitted_at AND
        admission->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256)
        IS TRUE)
)
"""
    )
    op.execute(
        """
CREATE TABLE ai_transfer_dispatch_claims (
    company_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    transfer_id TEXT NOT NULL,
    request_payload_sha256 VARCHAR(64) NOT NULL,
    admission_payload_sha256 VARCHAR(64) NOT NULL,
    ordinal INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    claim JSONB NOT NULL,
    attempt INTEGER NOT NULL,
    claim_status TEXT NOT NULL,
    delivery_state TEXT NOT NULL,
    claimed_by TEXT NOT NULL,
    claimed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    CONSTRAINT pk_ai_transfer_dispatch_claims
        PRIMARY KEY (company_id, execution_id, ordinal),
    CONSTRAINT uq_ai_transfer_dispatch_claim_id UNIQUE (company_id, claim_id),
    CONSTRAINT uq_ai_transfer_dispatch_transfer_ordinal UNIQUE (
        company_id, transfer_id, ordinal),
    CONSTRAINT fk_ai_transfer_claim_admission FOREIGN KEY (
        company_id, execution_id, transfer_id,
        request_payload_sha256, admission_payload_sha256)
        REFERENCES ai_transfer_execution_admissions (
            company_id, execution_id, transfer_id,
            request_payload_sha256, payload_sha256),
    CONSTRAINT fk_ai_transfer_claim_chunk FOREIGN KEY (
        company_id, transfer_id, request_payload_sha256,
        ordinal, chunk_id, request_sha256)
        REFERENCES ai_transfer_chunks (
            company_id, transfer_id, payload_sha256,
            ordinal, chunk_id, request_sha256),
    CONSTRAINT ck_ai_transfer_dispatch_first_ordinal CHECK (ordinal = 1),
    CONSTRAINT ck_ai_transfer_dispatch_claim_id CHECK (btrim(claim_id) <> ''),
    CONSTRAINT ck_ai_transfer_dispatch_attempt CHECK (attempt = 1),
    CONSTRAINT ck_ai_transfer_dispatch_status CHECK (
        claim_status = 'PERMANENTLY_CLAIMED'),
    CONSTRAINT ck_ai_transfer_dispatch_delivery CHECK (
        delivery_state = 'DELIVERY_UNKNOWN'),
    CONSTRAINT ck_ai_transfer_dispatch_actor CHECK (btrim(claimed_by) <> ''),
    CONSTRAINT ck_ai_transfer_dispatch_payload_sha256 CHECK (
        request_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_dispatch_request_sha256 CHECK (
        request_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_dispatch_admission_sha256 CHECK (
        admission_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_dispatch_event_sha256 CHECK (
        payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ai_transfer_dispatch_identity CHECK (
        (jsonb_typeof(claim) = 'object' AND
        claim->>'schema_version' IS NOT DISTINCT FROM
            'ai-transfer-dispatch-claim-v1' AND
        claim->>'company_id' IS NOT DISTINCT FROM company_id AND
        claim->>'claim_id' IS NOT DISTINCT FROM claim_id AND
        claim->>'execution_id' IS NOT DISTINCT FROM execution_id AND
        claim->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND
        claim->>'request_payload_sha256' IS NOT DISTINCT FROM
            request_payload_sha256 AND
        claim->>'admission_payload_sha256' IS NOT DISTINCT FROM
            admission_payload_sha256 AND
        (claim->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND
        claim->>'chunk_id' IS NOT DISTINCT FROM chunk_id AND
        claim->>'request_sha256' IS NOT DISTINCT FROM request_sha256 AND
        (claim->>'attempt')::integer IS NOT DISTINCT FROM attempt AND
        claim->>'claim_status' IS NOT DISTINCT FROM claim_status AND
        claim->>'delivery_state' IS NOT DISTINCT FROM delivery_state AND
        claim->>'claimed_by' IS NOT DISTINCT FROM claimed_by AND
        (claim->>'claimed_at')::timestamptz IS NOT DISTINCT FROM claimed_at AND
        claim->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256)
        IS TRUE)
)
"""
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_execution_admission()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    db_now timestamptz;
    preparer text;
    prepared timestamptz;
    approver text;
    approved timestamptz;
    approval_expires timestamptz;
    expected_chunk_count integer;
BEGIN
    db_now := clock_timestamp();

    SELECT r.prepared_by, r.created_at,
           a.approved_by, a.approved_at, a.expires_at, r.chunk_count
      INTO preparer, prepared, approver, approved, approval_expires,
           expected_chunk_count
      FROM ai_transfer_requests AS r
      JOIN ai_transfer_approvals AS a
        ON a.company_id = r.company_id
       AND a.transfer_id = r.transfer_id
       AND a.request_payload_sha256 = r.payload_sha256
     WHERE r.company_id = NEW.company_id
       AND r.transfer_id = NEW.transfer_id
       AND r.payload_sha256 = NEW.request_payload_sha256;

    IF NOT FOUND
       OR NEW.admitted_by IS DISTINCT FROM preparer
       OR btrim(approver) = btrim(preparer)
       OR approved < prepared
       OR approval_expires <> approved + interval '15 minutes'
       OR NEW.approved_by IS DISTINCT FROM approver
       OR NEW.approved_at IS DISTINCT FROM approved
       OR NEW.approval_expires_at IS DISTINCT FROM approval_expires
       OR NEW.chunk_count IS DISTINCT FROM expected_chunk_count
       OR approved > NEW.admitted_at
       OR NEW.admitted_at >= approval_expires
       OR abs(extract(epoch FROM (NEW.admitted_at - db_now))) > 2
       OR clock_timestamp() >= approval_expires THEN
        RAISE EXCEPTION 'AI transfer execution admission is not exact or current'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_execution_admission_binding "
        "BEFORE INSERT ON ai_transfer_execution_admissions FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_execution_admission()"
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_first_dispatch_claim()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    db_now timestamptz;
    admitted timestamptz;
    approval_expires timestamptz;
BEGIN
    db_now := clock_timestamp();

    SELECT e.admitted_at, a.expires_at
      INTO admitted, approval_expires
      FROM ai_transfer_execution_admissions AS e
      JOIN ai_transfer_approvals AS a
        ON a.company_id = e.company_id
       AND a.transfer_id = e.transfer_id
       AND a.request_payload_sha256 = e.request_payload_sha256
     WHERE e.company_id = NEW.company_id
       AND e.execution_id = NEW.execution_id
       AND e.transfer_id = NEW.transfer_id
       AND e.request_payload_sha256 = NEW.request_payload_sha256;

    IF NOT FOUND
       OR NEW.ordinal IS DISTINCT FROM 1
       OR NEW.chunk_id IS DISTINCT FROM 'chunk-0001'
       OR admitted > NEW.claimed_at
       OR NEW.claimed_at >= approval_expires
       OR abs(extract(epoch FROM (NEW.claimed_at - db_now))) > 2
       OR EXISTS (
            SELECT 1
              FROM ai_transfer_dispatch_claims AS existing
             WHERE existing.company_id = NEW.company_id
               AND (existing.execution_id = NEW.execution_id
                    OR existing.transfer_id = NEW.transfer_id))
       OR clock_timestamp() >= approval_expires THEN
        RAISE EXCEPTION 'AI transfer first dispatch claim is not exact or current'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_first_dispatch_claim_binding "
        "BEFORE INSERT ON ai_transfer_dispatch_claims FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_first_dispatch_claim()"
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
    op.execute("DROP FUNCTION enforce_ai_transfer_first_dispatch_claim() CASCADE")
    op.execute("DROP FUNCTION enforce_ai_transfer_execution_admission() CASCADE")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_constraint(
        "uq_ai_transfer_chunk_dispatch_binding", "ai_transfer_chunks", type_="unique"
    )
    op.drop_constraint("uq_ai_transfer_approval_exact", "ai_transfer_approvals", type_="unique")
