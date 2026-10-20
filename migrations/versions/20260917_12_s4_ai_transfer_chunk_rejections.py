"""Persist terminal semantic rejections for captured AI transfer chunks.

Revision ID: 20260917_12
Revises: 20260917_11
Create Date: 2026-09-17
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_12"
down_revision: str | None = "20260917_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
PARSER = "ai-transfer-requirement-parser-v1"
TABLE = "ai_transfer_requirement_chunk_rejections"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("transfer_id", sa.Text(), nullable=False),
        sa.Column("rejection_id", sa.Text(), nullable=False),
        sa.Column("request_payload_sha256", sa.String(64), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("claim_payload_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_id", sa.Text(), nullable=False),
        sa.Column("receipt_payload_sha256", sa.String(64), nullable=False),
        sa.Column("raw_response_id", sa.Text(), nullable=False),
        sa.Column("raw_metadata_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rejection", postgresql.JSONB(), nullable=False),
        sa.Column("rejected_by", sa.Text(), nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id",
            "execution_id",
            "ordinal",
            "parser_version",
            name="pk_ai_transfer_requirement_chunk_rejections",
        ),
        sa.UniqueConstraint(
            "company_id",
            "rejection_id",
            name="uq_ai_transfer_requirement_chunk_rejection_id",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["company_id", "raw_response_id", "receipt_id", "raw_metadata_sha256"],
            [
                "ai_transfer_raw_responses.company_id",
                "ai_transfer_raw_responses.raw_response_id",
                "ai_transfer_raw_responses.receipt_id",
                "ai_transfer_raw_responses.metadata_sha256",
            ],
            name="fk_ai_transfer_chunk_rejection_exact_raw",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_chunk_rejection_ordinal"
        ),
        sa.CheckConstraint(
            f"parser_version = '{PARSER}'", name="ck_ai_transfer_chunk_rejection_parser"
        ),
        sa.CheckConstraint(
            "reason = 'INVALID_CANDIDATE_EVIDENCE' AND payload_sha256 ~ '^[0-9a-f]{64}$' AND "
            "jsonb_typeof(rejection) = 'object' AND rejection->>'schema_version' = 'ai-transfer-requirement-chunk-rejection-v1' AND "
            "rejection->>'company_id' = company_id AND rejection->>'rejection_id' = rejection_id AND "
            "rejection->>'execution_id' = execution_id AND (rejection->>'ordinal')::integer = ordinal AND "
            "rejection->>'transfer_id' = transfer_id AND rejection->>'claim_id' = claim_id AND "
            "rejection->>'receipt_id' = receipt_id AND rejection->>'raw_response_id' = raw_response_id AND "
            "rejection->>'request_payload_sha256' = request_payload_sha256 AND "
            "rejection->>'claim_payload_sha256' = claim_payload_sha256 AND "
            "rejection->>'receipt_payload_sha256' = receipt_payload_sha256 AND "
            "rejection->>'raw_metadata_sha256' = raw_metadata_sha256 AND "
            "rejection->>'parser_version' = parser_version AND rejection->>'reason' = reason AND "
            "rejection->>'rejected_by' = rejected_by AND "
            "(rejection->>'rejected_at')::timestamptz IS NOT DISTINCT FROM rejected_at AND "
            "rejection->>'payload_sha256' = payload_sha256 AND created_at IS NOT DISTINCT FROM rejected_at",
            name="ck_ai_transfer_chunk_rejection_identity",
        ),
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_chunk_rejection_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_transfer_requirement_chunk_results AS result
         WHERE result.company_id = NEW.company_id
           AND result.execution_id = NEW.execution_id
           AND result.ordinal = NEW.ordinal
           AND result.parser_version = NEW.parser_version
    ) OR EXISTS (
        SELECT 1 FROM ai_transfer_requirement_batch_results AS batch
         WHERE batch.company_id = NEW.company_id
           AND batch.execution_id = NEW.execution_id
           AND batch.parser_version = NEW.parser_version
    ) OR NOT EXISTS (
        SELECT 1 FROM ai_transfer_dispatch_receipts AS receipt
        JOIN ai_transfer_dispatch_claims AS claim
          ON claim.company_id = receipt.company_id
         AND claim.execution_id = receipt.execution_id
         AND claim.ordinal = receipt.ordinal AND claim.claim_id = receipt.claim_id
        JOIN ai_transfer_raw_responses AS raw
          ON raw.company_id = receipt.company_id
         AND raw.execution_id = receipt.execution_id
         AND raw.ordinal = receipt.ordinal AND raw.receipt_id = receipt.receipt_id
        JOIN ai_transfer_requests AS request
          ON request.company_id = receipt.company_id
         AND request.transfer_id = receipt.transfer_id
         AND request.payload_sha256 = claim.request_payload_sha256
       WHERE receipt.company_id = NEW.company_id
         AND receipt.execution_id = NEW.execution_id
         AND receipt.ordinal = NEW.ordinal
         AND receipt.receipt_id = NEW.receipt_id
         AND receipt.outcome = 'SUCCESS'
         AND receipt.reason = 'VALIDATED_RESPONSE'
         AND receipt.capture_complete
         AND raw.raw_response_id = NEW.raw_response_id
         AND raw.metadata_sha256 = NEW.raw_metadata_sha256
         AND NEW.request_payload_sha256 = request.payload_sha256
         AND NEW.rejected_at >= receipt.recorded_at
         AND NEW.rejected_at >= raw.received_at
         AND NEW.rejected_at < raw.expires_at
         AND clock_timestamp() < raw.expires_at
    ) OR NEW.rejected_at > clock_timestamp() + interval '5 seconds' THEN
        RAISE EXCEPTION 'AI transfer chunk rejection evidence is not exact or current'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        f"CREATE TRIGGER ai_transfer_chunk_rejection_insert_guard BEFORE INSERT ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION enforce_ai_transfer_chunk_rejection_insert()"
    )
    op.execute(
        """
CREATE FUNCTION reject_ai_transfer_chunk_result_after_rejection()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_transfer_requirement_chunk_rejections AS rejection
         WHERE rejection.company_id = NEW.company_id
           AND rejection.execution_id = NEW.execution_id
           AND rejection.ordinal = NEW.ordinal
           AND rejection.parser_version = NEW.parser_version
    ) THEN
        RAISE EXCEPTION 'AI transfer chunk already has a terminal semantic rejection'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_chunk_result_rejection_guard BEFORE INSERT ON "
        "ai_transfer_requirement_chunk_results FOR EACH ROW "
        "EXECUTE FUNCTION reject_ai_transfer_chunk_result_after_rejection()"
    )
    op.execute(
        """
CREATE FUNCTION reject_ai_transfer_claim_after_semantic_rejection()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_transfer_requirement_chunk_rejections AS rejection
         WHERE rejection.company_id = NEW.company_id
           AND rejection.execution_id = NEW.execution_id
           AND rejection.ordinal < NEW.ordinal
    ) THEN
        RAISE EXCEPTION 'AI transfer execution has a terminal semantic rejection'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_claim_semantic_rejection_guard BEFORE INSERT ON "
        "ai_transfer_dispatch_claims FOR EACH ROW "
        "EXECUTE FUNCTION reject_ai_transfer_claim_after_semantic_rejection()"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(
        f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
        f"THEN GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER ai_transfer_claim_semantic_rejection_guard ON ai_transfer_dispatch_claims"
    )
    op.execute("DROP FUNCTION reject_ai_transfer_claim_after_semantic_rejection()")
    op.execute(
        "DROP TRIGGER ai_transfer_chunk_result_rejection_guard ON ai_transfer_requirement_chunk_results"
    )
    op.execute("DROP FUNCTION reject_ai_transfer_chunk_result_after_rejection()")
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION enforce_ai_transfer_chunk_rejection_insert()")
