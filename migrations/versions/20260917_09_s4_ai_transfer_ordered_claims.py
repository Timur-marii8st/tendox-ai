"""Allow only the next exact AI transfer chunk to receive a durable claim.

Revision ID: 20260917_09
Revises: 20260917_08
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_09"
down_revision: str | None = "20260917_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ai_transfer_dispatch_first_ordinal",
        "ai_transfer_dispatch_claims",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_transfer_dispatch_ordinal",
        "ai_transfer_dispatch_claims",
        "ordinal BETWEEN 1 AND 9999",
    )
    op.drop_constraint(
        "ck_ai_transfer_receipt_first_ordinal",
        "ai_transfer_dispatch_receipts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_transfer_receipt_ordinal",
        "ai_transfer_dispatch_receipts",
        "ordinal BETWEEN 1 AND 9999",
    )
    op.execute(
        """
CREATE OR REPLACE FUNCTION enforce_ai_transfer_first_dispatch_claim()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    db_now timestamptz;
    admitted timestamptz;
    approval_expires timestamptz;
    expected_chunk_count integer;
    prior_claim_count integer;
    last_receipt_at timestamptz;
    execution_found boolean;
BEGIN
    db_now := clock_timestamp();

    SELECT e.admitted_at, a.expires_at, e.chunk_count
      INTO admitted, approval_expires, expected_chunk_count
      FROM ai_transfer_execution_admissions AS e
      JOIN ai_transfer_approvals AS a
        ON a.company_id = e.company_id
       AND a.transfer_id = e.transfer_id
       AND a.request_payload_sha256 = e.request_payload_sha256
     WHERE e.company_id = NEW.company_id
       AND e.execution_id = NEW.execution_id
       AND e.transfer_id = NEW.transfer_id
       AND e.request_payload_sha256 = NEW.request_payload_sha256;
    execution_found := FOUND;

    SELECT count(*), max(r.recorded_at)
      INTO prior_claim_count, last_receipt_at
      FROM ai_transfer_dispatch_claims AS c
      LEFT JOIN ai_transfer_dispatch_receipts AS r
        ON r.company_id = c.company_id
       AND r.execution_id = c.execution_id
       AND r.ordinal = c.ordinal
       AND r.claim_id = c.claim_id
       AND r.claim_payload_sha256 = c.payload_sha256
     WHERE c.company_id = NEW.company_id
       AND c.execution_id = NEW.execution_id
       AND c.ordinal < NEW.ordinal;

    IF NOT execution_found
       OR NEW.ordinal < 1
       OR NEW.ordinal > expected_chunk_count
       OR NEW.ordinal IS DISTINCT FROM prior_claim_count + 1
       OR admitted > NEW.claimed_at
       OR NEW.claimed_at >= approval_expires
       OR (last_receipt_at IS NOT NULL AND last_receipt_at > NEW.claimed_at)
       OR abs(extract(epoch FROM (NEW.claimed_at - db_now))) > 2
       OR EXISTS (
            SELECT 1
              FROM ai_transfer_dispatch_claims AS existing
             WHERE existing.company_id = NEW.company_id
               AND existing.execution_id = NEW.execution_id
               AND existing.ordinal >= NEW.ordinal)
       OR EXISTS (
            SELECT 1
              FROM ai_transfer_dispatch_claims AS prior
              LEFT JOIN ai_transfer_dispatch_receipts AS receipt
                ON receipt.company_id = prior.company_id
               AND receipt.execution_id = prior.execution_id
               AND receipt.ordinal = prior.ordinal
               AND receipt.claim_id = prior.claim_id
               AND receipt.claim_payload_sha256 = prior.payload_sha256
              LEFT JOIN ai_transfer_raw_responses AS raw
                ON raw.company_id = receipt.company_id
               AND raw.execution_id = receipt.execution_id
               AND raw.ordinal = receipt.ordinal
               AND raw.claim_id = receipt.claim_id
               AND raw.receipt_id = receipt.receipt_id
               AND raw.receipt_payload_sha256 = receipt.payload_sha256
             WHERE prior.company_id = NEW.company_id
               AND prior.execution_id = NEW.execution_id
               AND prior.ordinal < NEW.ordinal
               AND (receipt.receipt_id IS NULL
                    OR receipt.outcome <> 'SUCCESS'
                    OR receipt.reason <> 'VALIDATED_RESPONSE'
                    OR receipt.capture_complete IS NOT TRUE
                    OR raw.raw_response_id IS NULL))
       OR clock_timestamp() >= approval_expires THEN
        RAISE EXCEPTION 'AI transfer next dispatch claim is not exact or current'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )


def downgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE FUNCTION enforce_ai_transfer_first_dispatch_claim()
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
            SELECT 1 FROM ai_transfer_dispatch_claims AS existing
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
    op.drop_constraint(
        "ck_ai_transfer_receipt_ordinal",
        "ai_transfer_dispatch_receipts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_transfer_receipt_first_ordinal",
        "ai_transfer_dispatch_receipts",
        "ordinal = 1",
    )
    op.drop_constraint(
        "ck_ai_transfer_dispatch_ordinal",
        "ai_transfer_dispatch_claims",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_transfer_dispatch_first_ordinal",
        "ai_transfer_dispatch_claims",
        "ordinal = 1",
    )
