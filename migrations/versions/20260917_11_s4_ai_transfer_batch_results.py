"""Persist per-chunk results and complete raw-free AI transfer batches.

Revision ID: 20260917_11
Revises: 20260917_10
Create Date: 2026-09-17
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_11"
down_revision: str | None = "20260917_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
PARSER = "ai-transfer-requirement-parser-v1"


def _replace_run_constraints(*, include_v3: bool) -> None:
    for name in (
        "ck_ai_requirement_run_snapshot_shape",
        "ck_ai_requirement_run_snapshot_identity",
        "ck_ai_requirement_run_payload_objects",
    ):
        op.drop_constraint(name, "document_ai_requirement_runs", type_="check")
    v3_shape = (
        " OR (snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3' AND "
        "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','result','completeness_status',"
        "'prepared_by','aggregated_by','aggregated_at','evidence_sha256'] AND "
        "snapshot - ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','result','completeness_status',"
        "'prepared_by','aggregated_by','aggregated_at','evidence_sha256'] = '{}'::jsonb)"
        if include_v3
        else ""
    )
    v3_identity = (
        " OR (snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3' AND "
        "snapshot->>'origin' = 'SERVER_MANAGED_TRANSFER_BATCH' AND "
        "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN' AND "
        "snapshot->>'prepared_by' = snapshot->'result'->>'prepared_by' AND "
        "snapshot->>'aggregated_by' = snapshot->'result'->>'aggregated_by' AND "
        "(snapshot->>'aggregated_at')::timestamptz IS NOT DISTINCT FROM "
        "(snapshot->'result'->>'aggregated_at')::timestamptz)"
        if include_v3
        else ""
    )
    v3_payload = (
        " OR (snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND "
        "jsonb_typeof(snapshot->'result') = 'object' AND "
        "snapshot->'result'->>'company_id' = company_id AND "
        "btrim(coalesce(snapshot->'result'->>'batch_result_id', '')) <> '')"
        if include_v3
        else ""
    )
    op.create_check_constraint(
        "ck_ai_requirement_run_snapshot_shape",
        "document_ai_requirement_runs",
        "(jsonb_typeof(snapshot) = 'object' AND ("
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','report','completeness_status',"
        "'submitted_by','submitted_at','evidence_sha256'] AND snapshot - ARRAY["
        "'schema_version','origin','company_id','run_id','source_document_id',"
        "'source_sha256','extraction','report','completeness_status','submitted_by',"
        "'submitted_at','evidence_sha256'] = '{}'::jsonb) OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','result','completeness_status',"
        "'prepared_by','materialized_by','materialized_at','evidence_sha256'] AND "
        "snapshot - ARRAY['schema_version','origin','company_id','run_id',"
        "'source_document_id','source_sha256','extraction','result','completeness_status',"
        "'prepared_by','materialized_by','materialized_at','evidence_sha256'] = '{}'::jsonb)"
        + v3_shape
        + ")) IS TRUE",
    )
    op.create_check_constraint(
        "ck_ai_requirement_run_snapshot_identity",
        "document_ai_requirement_runs",
        "(((snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "snapshot->>'origin' = 'IMPORTED_REPORT' AND snapshot->>'company_id' = company_id AND "
        "snapshot->>'run_id' = run_id AND snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "snapshot->>'origin' = 'SERVER_MANAGED_TRANSFER' AND snapshot->>'company_id' = company_id AND "
        "snapshot->>'run_id' = run_id AND snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN' AND "
        "snapshot->>'prepared_by' = snapshot->'result'->>'prepared_by' AND "
        "snapshot->>'materialized_by' = snapshot->'result'->>'materialized_by' AND "
        "(snapshot->>'materialized_at')::timestamptz IS NOT DISTINCT FROM "
        "(snapshot->'result'->>'materialized_at')::timestamptz)" + v3_identity + ")) IS TRUE",
    )
    op.create_check_constraint(
        "ck_ai_requirement_run_payload_objects",
        "document_ai_requirement_runs",
        "((snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND jsonb_typeof(snapshot->'report') = 'object') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND jsonb_typeof(snapshot->'result') = 'object' AND "
        "snapshot->'result'->>'company_id' = company_id AND "
        "btrim(coalesce(snapshot->'result'->>'result_id', '')) <> '')" + v3_payload + ") IS TRUE",
    )


def upgrade() -> None:
    _replace_run_constraints(include_v3=True)
    op.create_table(
        "ai_transfer_requirement_chunk_results",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("transfer_id", sa.Text(), nullable=False),
        sa.Column("result_id", sa.Text(), nullable=False),
        sa.Column("request_payload_sha256", sa.String(64), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("claim_payload_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_id", sa.Text(), nullable=False),
        sa.Column("receipt_payload_sha256", sa.String(64), nullable=False),
        sa.Column("raw_response_id", sa.Text(), nullable=False),
        sa.Column("raw_metadata_sha256", sa.String(64), nullable=False),
        sa.Column("result_payload_sha256", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("materialized_by", sa.Text(), nullable=False),
        sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id",
            "execution_id",
            "ordinal",
            "parser_version",
            name="pk_ai_transfer_requirement_chunk_results",
        ),
        sa.UniqueConstraint(
            "company_id", "result_id", name="uq_ai_transfer_requirement_chunk_result_id"
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
            name="fk_ai_transfer_chunk_result_exact_claim",
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
            name="fk_ai_transfer_chunk_result_exact_receipt",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "raw_response_id", "receipt_id", "raw_metadata_sha256"],
            [
                "ai_transfer_raw_responses.company_id",
                "ai_transfer_raw_responses.raw_response_id",
                "ai_transfer_raw_responses.receipt_id",
                "ai_transfer_raw_responses.metadata_sha256",
            ],
            name="fk_ai_transfer_chunk_result_exact_raw",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 9999", name="ck_ai_transfer_chunk_result_ordinal"
        ),
        sa.CheckConstraint(
            f"parser_version = '{PARSER}'", name="ck_ai_transfer_chunk_result_parser"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object' AND result->>'schema_version' = 'ai-transfer-requirement-result-v1' AND "
            "result->>'payload_sha256' = result_payload_sha256 AND result->>'company_id' = company_id AND "
            "result->>'execution_id' = execution_id AND (result->>'ordinal')::integer = ordinal AND "
            "result->>'transfer_id' = transfer_id AND result->>'result_id' = result_id AND "
            "result->>'claim_id' = claim_id AND result->>'receipt_id' = receipt_id AND "
            "result->>'raw_response_id' = raw_response_id AND result->>'request_payload_sha256' = request_payload_sha256 AND "
            "result->>'claim_payload_sha256' = claim_payload_sha256 AND result->>'receipt_payload_sha256' = receipt_payload_sha256 AND "
            "result->>'raw_metadata_sha256' = raw_metadata_sha256 AND result->>'materialized_by' = materialized_by AND "
            "(result->>'materialized_at')::timestamptz IS NOT DISTINCT FROM materialized_at AND created_at IS NOT DISTINCT FROM materialized_at",
            name="ck_ai_transfer_chunk_result_identity",
        ),
    )
    op.create_table(
        "ai_transfer_requirement_batch_results",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("transfer_id", sa.Text(), nullable=False),
        sa.Column("batch_result_id", sa.Text(), nullable=False),
        sa.Column("request_payload_sha256", sa.String(64), nullable=False),
        sa.Column("batch_payload_sha256", sa.String(64), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("run_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("aggregated_by", sa.Text(), nullable=False),
        sa.Column("aggregated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id",
            "execution_id",
            "parser_version",
            name="pk_ai_transfer_requirement_batch_results",
        ),
        sa.UniqueConstraint(
            "company_id", "batch_result_id", name="uq_ai_transfer_requirement_batch_result_id"
        ),
        sa.ForeignKeyConstraint(
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
        sa.CheckConstraint(
            f"parser_version = '{PARSER}'", name="ck_ai_transfer_batch_result_parser"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object' AND result->>'schema_version' = 'ai-transfer-requirement-batch-v1' AND "
            "result->>'payload_sha256' = batch_payload_sha256 AND result->>'company_id' = company_id AND "
            "result->>'execution_id' = execution_id AND result->>'transfer_id' = transfer_id AND "
            "result->>'batch_result_id' = batch_result_id AND result->>'request_payload_sha256' = request_payload_sha256 AND "
            "result->>'aggregated_by' = aggregated_by AND "
            "(result->>'aggregated_at')::timestamptz IS NOT DISTINCT FROM aggregated_at AND created_at IS NOT DISTINCT FROM aggregated_at",
            name="ck_ai_transfer_batch_result_identity",
        ),
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_chunk_result_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ai_transfer_dispatch_receipts AS r
        JOIN ai_transfer_dispatch_claims AS c
          ON c.company_id = r.company_id AND c.execution_id = r.execution_id
         AND c.ordinal = r.ordinal AND c.claim_id = r.claim_id
        JOIN ai_transfer_raw_responses AS raw
          ON raw.company_id = r.company_id AND raw.execution_id = r.execution_id
         AND raw.ordinal = r.ordinal AND raw.receipt_id = r.receipt_id
        JOIN ai_transfer_requests AS req
          ON req.company_id = r.company_id AND req.transfer_id = r.transfer_id
         AND req.payload_sha256 = c.request_payload_sha256
        JOIN ai_transfer_chunks AS chunk
          ON chunk.company_id = c.company_id AND chunk.transfer_id = c.transfer_id
         AND chunk.ordinal = c.ordinal AND chunk.chunk_id = c.chunk_id
        WHERE r.company_id = NEW.company_id AND r.execution_id = NEW.execution_id
          AND r.ordinal = NEW.ordinal AND r.receipt_id = NEW.receipt_id
          AND r.outcome = 'SUCCESS' AND r.reason = 'VALIDATED_RESPONSE'
          AND r.capture_complete AND raw.raw_response_id = NEW.raw_response_id
          AND raw.metadata_sha256 = NEW.raw_metadata_sha256
          AND NEW.result->>'request_sha256' = c.request_sha256
          AND NEW.result->>'response_body_sha256' = raw.response_body_sha256
          AND NEW.result->>'assistant_content_sha256' = r.assistant_content_sha256
          AND NEW.result->>'provider_response_id' = r.provider_response_id
          AND NEW.result->>'provider_model' = r.provider_model
          AND NEW.result->>'source_document_id' = req.source_document_id
          AND NEW.result->>'source_sha256' = req.source_sha256
          AND NEW.result->>'extraction_sha256' = req.request->>'extraction_sha256'
          AND NEW.result->'source_block_ids' = chunk.chunk->'source_block_ids'
          AND NEW.result->>'prepared_by' = req.prepared_by
          AND NEW.materialized_at >= r.recorded_at
          AND NEW.materialized_at >= raw.received_at
          AND NEW.materialized_at < raw.expires_at
          AND clock_timestamp() < raw.expires_at
    ) OR NEW.materialized_at > clock_timestamp() + interval '5 seconds' THEN
        RAISE EXCEPTION 'AI transfer chunk result evidence is not exact or current'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_chunk_result_insert_guard BEFORE INSERT ON "
        "ai_transfer_requirement_chunk_results FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_chunk_result_insert()"
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_batch_result_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_count integer;
BEGIN
    SELECT chunk_count INTO expected_count FROM ai_transfer_execution_admissions
     WHERE company_id = NEW.company_id AND execution_id = NEW.execution_id
       AND transfer_id = NEW.transfer_id
       AND request_payload_sha256 = NEW.request_payload_sha256;
    IF NOT FOUND OR expected_count <> (
        SELECT count(*) FROM ai_transfer_requirement_chunk_results AS c
         WHERE c.company_id = NEW.company_id AND c.execution_id = NEW.execution_id
           AND c.parser_version = NEW.parser_version)
       OR NEW.result->'chunk_results' IS DISTINCT FROM (
        SELECT jsonb_agg(c.result ORDER BY c.ordinal)
          FROM ai_transfer_requirement_chunk_results AS c
         WHERE c.company_id = NEW.company_id AND c.execution_id = NEW.execution_id
           AND c.parser_version = NEW.parser_version)
       OR NOT EXISTS (
        SELECT 1 FROM ai_transfer_requests AS req
         WHERE req.company_id = NEW.company_id AND req.transfer_id = NEW.transfer_id
           AND req.payload_sha256 = NEW.request_payload_sha256
           AND NEW.result->>'source_document_id' = req.source_document_id
           AND NEW.result->>'source_sha256' = req.source_sha256
           AND NEW.result->>'extraction_sha256' = req.request->>'extraction_sha256'
           AND NEW.result->'source_block_ids' = req.request->'source_block_ids'
           AND NEW.result->>'prepared_by' = req.prepared_by)
       OR NEW.aggregated_at > clock_timestamp() + interval '5 seconds' THEN
        RAISE EXCEPTION 'AI transfer batch is incomplete or differs from chunk results'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        "CREATE TRIGGER ai_transfer_batch_result_insert_guard BEFORE INSERT ON "
        "ai_transfer_requirement_batch_results FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_batch_result_insert()"
    )
    op.execute(
        """
CREATE FUNCTION ensure_ai_transfer_batch_run_binding()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.snapshot->>'schema_version' = 'persisted-ai-requirement-run-v3'
       AND NOT EXISTS (
        SELECT 1 FROM ai_transfer_requirement_batch_results AS b
         WHERE b.company_id = NEW.company_id AND b.run_id = NEW.run_id
           AND b.run_evidence_sha256 = NEW.evidence_sha256
           AND b.batch_result_id = NEW.snapshot->'result'->>'batch_result_id'
           AND b.batch_payload_sha256 = NEW.snapshot->'result'->>'payload_sha256'
           AND b.execution_id = NEW.snapshot->'result'->>'execution_id'
           AND b.aggregated_by = NEW.snapshot->>'aggregated_by'
           AND b.aggregated_at = (NEW.snapshot->>'aggregated_at')::timestamptz
    ) THEN
        RAISE EXCEPTION 'server-managed AI transfer batch run lacks exact result'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$
"""
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_transfer_batch_run_required AFTER INSERT ON "
        "document_ai_requirement_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION ensure_ai_transfer_batch_run_binding()"
    )
    for table in (
        "ai_transfer_requirement_chunk_results",
        "ai_transfer_requirement_batch_results",
    ):
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
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'procurement_app') THEN GRANT SELECT, INSERT ON "
            f"{table} TO procurement_app; END IF; END $$"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER ai_transfer_batch_run_required ON document_ai_requirement_runs")
    op.execute("DROP FUNCTION ensure_ai_transfer_batch_run_binding()")
    op.drop_table("ai_transfer_requirement_batch_results")
    op.drop_table("ai_transfer_requirement_chunk_results")
    op.execute("DROP FUNCTION enforce_ai_transfer_batch_result_insert()")
    op.execute("DROP FUNCTION enforce_ai_transfer_chunk_result_insert()")
    _replace_run_constraints(include_v3=False)
