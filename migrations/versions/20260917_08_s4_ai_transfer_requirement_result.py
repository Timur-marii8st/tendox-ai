"""Persist immutable server-managed AI requirement materializations.

Revision ID: 20260917_08
Revises: 20260917_07
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_08"
down_revision: str | None = "20260917_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_transfer_requirement_materializations"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"

V1_FIELDS = (
    "'schema_version','origin','company_id','run_id','source_document_id',"
    "'source_sha256','extraction','report','completeness_status','submitted_by',"
    "'submitted_at','evidence_sha256'"
)
V2_FIELDS = (
    "'schema_version','origin','company_id','run_id','source_document_id',"
    "'source_sha256','extraction','result','completeness_status','prepared_by',"
    "'materialized_by','materialized_at','evidence_sha256'"
)


def _replace_run_snapshot_constraints(*, v2: bool) -> None:
    op.drop_constraint(
        "ck_ai_requirement_run_snapshot_shape",
        "document_ai_requirement_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_requirement_run_snapshot_identity",
        "document_ai_requirement_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_requirement_run_payload_objects",
        "document_ai_requirement_runs",
        type_="check",
    )
    if not v2:
        op.create_check_constraint(
            "ck_ai_requirement_run_snapshot_shape",
            "document_ai_requirement_runs",
            "(jsonb_typeof(snapshot) = 'object' AND snapshot ?& ARRAY["
            + V1_FIELDS
            + "] AND snapshot - ARRAY["
            + V1_FIELDS
            + "] = '{}'::jsonb) IS TRUE",
        )
        op.create_check_constraint(
            "ck_ai_requirement_run_snapshot_identity",
            "document_ai_requirement_runs",
            "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
            "snapshot->>'origin' = 'IMPORTED_REPORT' AND "
            "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
            "snapshot->>'source_document_id' = source_document_id AND "
            "snapshot->>'source_sha256' = source_sha256 AND "
            "snapshot->>'evidence_sha256' = evidence_sha256 AND "
            "snapshot->>'completeness_status' = 'UNKNOWN') IS TRUE",
        )
        op.create_check_constraint(
            "ck_ai_requirement_run_payload_objects",
            "document_ai_requirement_runs",
            "(jsonb_typeof(snapshot->'extraction') = 'object' AND "
            "jsonb_typeof(snapshot->'report') = 'object') IS TRUE",
        )
        return

    op.create_check_constraint(
        "ck_ai_requirement_run_snapshot_shape",
        "document_ai_requirement_runs",
        "(jsonb_typeof(snapshot) = 'object' AND ("
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "snapshot ?& ARRAY["
        + V1_FIELDS
        + "] AND snapshot - ARRAY["
        + V1_FIELDS
        + "] = '{}'::jsonb) OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "snapshot ?& ARRAY["
        + V2_FIELDS
        + "] AND snapshot - ARRAY["
        + V2_FIELDS
        + "] = '{}'::jsonb))) IS TRUE",
    )
    op.create_check_constraint(
        "ck_ai_requirement_run_snapshot_identity",
        "document_ai_requirement_runs",
        "(((snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "snapshot->>'origin' = 'IMPORTED_REPORT' AND "
        "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "snapshot->>'origin' = 'SERVER_MANAGED_TRANSFER' AND "
        "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
        "snapshot->>'source_document_id' = source_document_id AND "
        "snapshot->>'source_sha256' = source_sha256 AND "
        "snapshot->>'evidence_sha256' = evidence_sha256 AND "
        "snapshot->>'completeness_status' = 'UNKNOWN' AND "
        "snapshot->>'prepared_by' = snapshot->'result'->>'prepared_by' AND "
        "snapshot->>'materialized_by' = snapshot->'result'->>'materialized_by' AND "
        "(snapshot->>'materialized_at')::timestamptz IS NOT DISTINCT FROM "
        "(snapshot->'result'->>'materialized_at')::timestamptz))) IS TRUE",
    )
    op.create_check_constraint(
        "ck_ai_requirement_run_payload_objects",
        "document_ai_requirement_runs",
        "((snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND "
        "jsonb_typeof(snapshot->'report') = 'object') OR "
        "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2' AND "
        "jsonb_typeof(snapshot->'extraction') = 'object' AND "
        "jsonb_typeof(snapshot->'result') = 'object' AND "
        "snapshot->'result'->>'company_id' = company_id AND "
        "btrim(coalesce(snapshot->'result'->>'result_id', '')) <> '')) IS TRUE",
    )


def upgrade() -> None:
    _replace_run_snapshot_constraints(v2=True)
    op.create_unique_constraint(
        "uq_ai_transfer_claim_materialization_binding",
        "ai_transfer_dispatch_claims",
        ["company_id", "execution_id", "transfer_id", "ordinal", "claim_id", "payload_sha256"],
    )
    op.create_unique_constraint(
        "uq_ai_transfer_receipt_materialization_binding",
        "ai_transfer_dispatch_receipts",
        [
            "company_id",
            "execution_id",
            "transfer_id",
            "ordinal",
            "claim_id",
            "receipt_id",
            "payload_sha256",
        ],
    )
    op.create_unique_constraint(
        "uq_ai_transfer_raw_materialization_binding",
        "ai_transfer_raw_responses",
        ["company_id", "raw_response_id", "receipt_id", "metadata_sha256"],
    )
    op.execute(
        f"""
CREATE TABLE {TABLE} (
    company_id TEXT NOT NULL,
    materialization_id TEXT NOT NULL,
    transfer_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    claim_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    raw_response_id TEXT NOT NULL,
    request_payload_sha256 VARCHAR(64) NOT NULL,
    claim_payload_sha256 VARCHAR(64) NOT NULL,
    receipt_payload_sha256 VARCHAR(64) NOT NULL,
    raw_metadata_sha256 VARCHAR(64) NOT NULL,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    result_id TEXT,
    result_payload_sha256 VARCHAR(64),
    run_id TEXT,
    run_evidence_sha256 VARCHAR(64),
    materialized_by TEXT NOT NULL,
    materialized_at TIMESTAMP WITH TIME ZONE NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    materialization JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_ai_transfer_requirement_materializations
        PRIMARY KEY (company_id, materialization_id),
    CONSTRAINT uq_ai_transfer_requirement_materialization_execution_parser
        UNIQUE (company_id, execution_id, parser_version),
    CONSTRAINT uq_ai_transfer_requirement_materialization_result
        UNIQUE (company_id, result_id),
    CONSTRAINT uq_ai_transfer_requirement_materialization_raw
        UNIQUE (company_id, raw_response_id, parser_version),
    CONSTRAINT uq_ai_transfer_requirement_materialization_receipt
        UNIQUE (company_id, receipt_id, parser_version),
    CONSTRAINT fk_ai_transfer_materialization_exact_claim FOREIGN KEY (
        company_id, execution_id, transfer_id, ordinal, claim_id, claim_payload_sha256)
        REFERENCES ai_transfer_dispatch_claims (
        company_id, execution_id, transfer_id, ordinal, claim_id, payload_sha256),
    CONSTRAINT fk_ai_transfer_materialization_exact_receipt FOREIGN KEY (
        company_id, execution_id, transfer_id, ordinal, claim_id, receipt_id,
        receipt_payload_sha256)
        REFERENCES ai_transfer_dispatch_receipts (
        company_id, execution_id, transfer_id, ordinal, claim_id, receipt_id,
        payload_sha256),
    CONSTRAINT fk_ai_transfer_materialization_exact_raw FOREIGN KEY (
        company_id, raw_response_id, receipt_id, raw_metadata_sha256)
        REFERENCES ai_transfer_raw_responses (
        company_id, raw_response_id, receipt_id, metadata_sha256),
    CONSTRAINT fk_ai_transfer_materialization_exact_run FOREIGN KEY (
        company_id, run_id, run_evidence_sha256)
        REFERENCES document_ai_requirement_runs (company_id, run_id, evidence_sha256),
    CONSTRAINT ck_ai_transfer_materialization_first_ordinal CHECK (ordinal = 1),
    CONSTRAINT ck_ai_transfer_materialization_schema CHECK (
        parser_version = 'ai-transfer-requirement-parser-v1'),
    CONSTRAINT ck_ai_transfer_materialization_status CHECK (
        status IN ('MATERIALIZED', 'REJECTED') AND
        reason IN ('MATERIALIZED', 'UNSUPPORTED_MULTI_CHUNK', 'INVALID_CANDIDATE_EVIDENCE')),
    CONSTRAINT ck_ai_transfer_materialization_outputs CHECK (
        ((status = 'MATERIALIZED' AND reason = 'MATERIALIZED' AND
          result_id IS NOT NULL AND result_payload_sha256 IS NOT NULL AND
          run_id IS NOT NULL AND run_evidence_sha256 IS NOT NULL) OR
         (status = 'REJECTED' AND reason <> 'MATERIALIZED' AND
          result_id IS NULL AND result_payload_sha256 IS NULL AND
          run_id IS NULL AND run_evidence_sha256 IS NULL)) IS TRUE),
    CONSTRAINT ck_ai_transfer_materialization_safe_text CHECK (
        btrim(materialization_id) <> '' AND materialization_id !~ '[[:cntrl:]]' AND
        btrim(transfer_id) <> '' AND transfer_id !~ '[[:cntrl:]]' AND
        btrim(execution_id) <> '' AND execution_id !~ '[[:cntrl:]]' AND
        btrim(claim_id) <> '' AND claim_id !~ '[[:cntrl:]]' AND
        btrim(receipt_id) <> '' AND receipt_id !~ '[[:cntrl:]]' AND
        btrim(raw_response_id) <> '' AND raw_response_id !~ '[[:cntrl:]]' AND
        btrim(materialized_by) <> '' AND materialized_by !~ '[[:cntrl:]]' AND
        (result_id IS NULL OR (btrim(result_id) <> '' AND result_id !~ '[[:cntrl:]]')) AND
        (run_id IS NULL OR (btrim(run_id) <> '' AND run_id !~ '[[:cntrl:]]'))),
    CONSTRAINT ck_ai_transfer_materialization_digests CHECK (
        request_payload_sha256 ~ '^[0-9a-f]{{64}}$' AND
        claim_payload_sha256 ~ '^[0-9a-f]{{64}}$' AND
        receipt_payload_sha256 ~ '^[0-9a-f]{{64}}$' AND
        raw_metadata_sha256 ~ '^[0-9a-f]{{64}}$' AND
        payload_sha256 ~ '^[0-9a-f]{{64}}$' AND
        (result_payload_sha256 IS NULL OR result_payload_sha256 ~ '^[0-9a-f]{{64}}$') AND
        (run_evidence_sha256 IS NULL OR run_evidence_sha256 ~ '^[0-9a-f]{{64}}$')),
    CONSTRAINT ck_ai_transfer_materialization_identity CHECK (
        (jsonb_typeof(materialization) = 'object' AND materialization ?& ARRAY[
          'schema_version','company_id','materialization_id','transfer_id','execution_id',
          'ordinal','claim_id','receipt_id','raw_response_id','request_payload_sha256',
          'claim_payload_sha256','receipt_payload_sha256','raw_metadata_sha256',
          'parser_version','status','reason','result_id','result_payload_sha256','run_id',
          'run_evidence_sha256','materialized_by','materialized_at','payload_sha256'] AND
         materialization - ARRAY[
          'schema_version','company_id','materialization_id','transfer_id','execution_id',
          'ordinal','claim_id','receipt_id','raw_response_id','request_payload_sha256',
          'claim_payload_sha256','receipt_payload_sha256','raw_metadata_sha256',
          'parser_version','status','reason','result_id','result_payload_sha256','run_id',
          'run_evidence_sha256','materialized_by','materialized_at',
          'payload_sha256'] = '{{}}'::jsonb AND
         materialization->>'schema_version' IS NOT DISTINCT FROM
            'ai-transfer-requirement-materialization-v1' AND
         materialization->>'company_id' IS NOT DISTINCT FROM company_id AND
         materialization->>'materialization_id' IS NOT DISTINCT FROM materialization_id AND
         materialization->>'transfer_id' IS NOT DISTINCT FROM transfer_id AND
         materialization->>'execution_id' IS NOT DISTINCT FROM execution_id AND
         (materialization->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND
         materialization->>'claim_id' IS NOT DISTINCT FROM claim_id AND
         materialization->>'receipt_id' IS NOT DISTINCT FROM receipt_id AND
         materialization->>'raw_response_id' IS NOT DISTINCT FROM raw_response_id AND
         materialization->>'request_payload_sha256' IS NOT DISTINCT FROM request_payload_sha256 AND
         materialization->>'claim_payload_sha256' IS NOT DISTINCT FROM claim_payload_sha256 AND
         materialization->>'receipt_payload_sha256' IS NOT DISTINCT FROM receipt_payload_sha256 AND
         materialization->>'raw_metadata_sha256' IS NOT DISTINCT FROM raw_metadata_sha256 AND
         materialization->>'parser_version' IS NOT DISTINCT FROM parser_version AND
         materialization->>'status' IS NOT DISTINCT FROM status AND
         materialization->>'reason' IS NOT DISTINCT FROM reason AND
         materialization->>'result_id' IS NOT DISTINCT FROM result_id AND
         materialization->>'result_payload_sha256' IS NOT DISTINCT FROM result_payload_sha256 AND
         materialization->>'run_id' IS NOT DISTINCT FROM run_id AND
         materialization->>'run_evidence_sha256' IS NOT DISTINCT FROM run_evidence_sha256 AND
         materialization->>'materialized_by' IS NOT DISTINCT FROM materialized_by AND
         (materialization->>'materialized_at')::timestamptz IS NOT DISTINCT FROM materialized_at AND
         materialization->>'payload_sha256' IS NOT DISTINCT FROM payload_sha256 AND
         created_at IS NOT DISTINCT FROM materialized_at) IS TRUE)
)
"""
    )
    op.execute(
        """
CREATE FUNCTION enforce_ai_transfer_requirement_materialization_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ai_transfer_dispatch_claims AS c
        WHERE c.company_id = NEW.company_id AND c.execution_id = NEW.execution_id
          AND c.ordinal = NEW.ordinal AND c.claim_id = NEW.claim_id
          AND c.request_payload_sha256 = NEW.request_payload_sha256
    ) THEN
        RAISE EXCEPTION 'AI requirement materialization request projection is not exact'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM ai_transfer_dispatch_receipts AS r
        WHERE r.company_id = NEW.company_id AND r.execution_id = NEW.execution_id
          AND r.ordinal = NEW.ordinal AND r.receipt_id = NEW.receipt_id
          AND r.outcome = 'SUCCESS' AND r.reason = 'VALIDATED_RESPONSE'
          AND r.capture_complete
    ) THEN
        RAISE EXCEPTION 'AI requirement materialization requires successful captured receipt'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'MATERIALIZED' AND NOT EXISTS (
        SELECT 1 FROM document_ai_requirement_runs AS run
        WHERE run.company_id = NEW.company_id AND run.run_id = NEW.run_id
          AND run.evidence_sha256 = NEW.run_evidence_sha256
          AND run.snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2'
          AND run.snapshot->'result'->>'result_id' = NEW.result_id
          AND run.snapshot->'result'->>'payload_sha256' = NEW.result_payload_sha256
          AND run.snapshot->'result'->>'company_id' = NEW.company_id
          AND run.snapshot->'result'->>'transfer_id' = NEW.transfer_id
          AND run.snapshot->'result'->>'execution_id' = NEW.execution_id
          AND (run.snapshot->'result'->>'ordinal')::integer = NEW.ordinal
          AND run.snapshot->'result'->>'claim_id' = NEW.claim_id
          AND run.snapshot->'result'->>'receipt_id' = NEW.receipt_id
          AND run.snapshot->'result'->>'raw_response_id' = NEW.raw_response_id
          AND run.snapshot->'result'->>'request_payload_sha256' =
              NEW.request_payload_sha256
          AND run.snapshot->'result'->>'claim_payload_sha256' =
              NEW.claim_payload_sha256
          AND run.snapshot->'result'->>'receipt_payload_sha256' =
              NEW.receipt_payload_sha256
          AND run.snapshot->'result'->>'raw_metadata_sha256' =
              NEW.raw_metadata_sha256
          AND run.snapshot->'result'->>'request_sha256' = (
              SELECT c.request_sha256 FROM ai_transfer_dispatch_claims AS c
              WHERE c.company_id = NEW.company_id
                AND c.execution_id = NEW.execution_id AND c.ordinal = NEW.ordinal)
          AND run.snapshot->'result'->>'response_body_sha256' = (
              SELECT raw.response_body_sha256 FROM ai_transfer_raw_responses AS raw
              WHERE raw.company_id = NEW.company_id
                AND raw.raw_response_id = NEW.raw_response_id)
          AND run.snapshot->'result'->>'assistant_content_sha256' = (
              SELECT r.assistant_content_sha256 FROM ai_transfer_dispatch_receipts AS r
              WHERE r.company_id = NEW.company_id
                AND r.execution_id = NEW.execution_id AND r.ordinal = NEW.ordinal)
          AND run.snapshot->'result'->>'provider_response_id' = (
              SELECT r.provider_response_id FROM ai_transfer_dispatch_receipts AS r
              WHERE r.company_id = NEW.company_id
                AND r.execution_id = NEW.execution_id AND r.ordinal = NEW.ordinal)
          AND run.snapshot->'result'->>'provider_model' = (
              SELECT r.provider_model FROM ai_transfer_dispatch_receipts AS r
              WHERE r.company_id = NEW.company_id
                AND r.execution_id = NEW.execution_id AND r.ordinal = NEW.ordinal)
          AND run.snapshot->'result'->>'source_document_id' = run.source_document_id
          AND run.snapshot->'result'->>'source_sha256' = run.source_sha256
          AND run.source_document_id = (
              SELECT req.source_document_id FROM ai_transfer_requests AS req
              WHERE req.company_id = NEW.company_id AND req.transfer_id = NEW.transfer_id)
          AND run.source_sha256 = (
              SELECT req.source_sha256 FROM ai_transfer_requests AS req
              WHERE req.company_id = NEW.company_id AND req.transfer_id = NEW.transfer_id)
          AND run.snapshot->'result'->>'extraction_sha256' = (
              SELECT req.request->>'extraction_sha256' FROM ai_transfer_requests AS req
              WHERE req.company_id = NEW.company_id AND req.transfer_id = NEW.transfer_id)
          AND run.snapshot->'result'->'source_block_ids' = (
              SELECT req.request->'source_block_ids' FROM ai_transfer_requests AS req
              WHERE req.company_id = NEW.company_id AND req.transfer_id = NEW.transfer_id)
          AND run.snapshot->'result'->>'prepared_by' = (
              SELECT req.prepared_by FROM ai_transfer_requests AS req
              WHERE req.company_id = NEW.company_id AND req.transfer_id = NEW.transfer_id)
          AND run.snapshot->'result'->>'execution_status' = 'COMPLETE'
          AND run.snapshot->'result'->>'completeness_status' = 'UNKNOWN'
          AND run.snapshot->>'materialized_by' = NEW.materialized_by
          AND (run.snapshot->>'materialized_at')::timestamptz IS NOT DISTINCT FROM
              NEW.materialized_at
    ) THEN
        RAISE EXCEPTION 'AI requirement materialization run binding is not exact'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.materialized_at < (
        SELECT r.recorded_at FROM ai_transfer_dispatch_receipts AS r
        WHERE r.company_id = NEW.company_id AND r.execution_id = NEW.execution_id
          AND r.ordinal = NEW.ordinal AND r.receipt_id = NEW.receipt_id
    ) OR NEW.materialized_at < (
        SELECT raw.received_at FROM ai_transfer_raw_responses AS raw
        WHERE raw.company_id = NEW.company_id
          AND raw.raw_response_id = NEW.raw_response_id
    ) OR NEW.materialized_at > clock_timestamp() + interval '5 seconds' THEN
        RAISE EXCEPTION 'AI requirement materialization chronology is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reason <> 'UNSUPPORTED_MULTI_CHUNK' AND (
        NEW.materialized_at >= (
            SELECT raw.expires_at FROM ai_transfer_raw_responses AS raw
            WHERE raw.company_id = NEW.company_id
              AND raw.raw_response_id = NEW.raw_response_id)
        OR clock_timestamp() >= (
            SELECT raw.expires_at FROM ai_transfer_raw_responses AS raw
            WHERE raw.company_id = NEW.company_id
              AND raw.raw_response_id = NEW.raw_response_id)
    ) THEN
        RAISE EXCEPTION 'AI requirement raw response retention expired'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""
    )
    op.execute(
        f"CREATE TRIGGER ai_transfer_requirement_materialization_insert_guard "
        f"BEFORE INSERT ON {TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION enforce_ai_transfer_requirement_materialization_insert()"
    )
    op.execute(
        """
CREATE FUNCTION ensure_ai_transfer_requirement_run_has_materialization()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.snapshot->>'schema_version' = 'persisted-ai-requirement-run-v2'
       AND NOT EXISTS (
        SELECT 1 FROM ai_transfer_requirement_materializations AS m
        WHERE m.company_id = NEW.company_id
          AND m.run_id = NEW.run_id
          AND m.run_evidence_sha256 = NEW.evidence_sha256
          AND m.status = 'MATERIALIZED'
          AND m.reason = 'MATERIALIZED'
          AND m.result_id = NEW.snapshot->'result'->>'result_id'
          AND m.result_payload_sha256 = NEW.snapshot->'result'->>'payload_sha256'
          AND m.transfer_id = NEW.snapshot->'result'->>'transfer_id'
          AND m.execution_id = NEW.snapshot->'result'->>'execution_id'
          AND m.ordinal = (NEW.snapshot->'result'->>'ordinal')::integer
          AND m.claim_id = NEW.snapshot->'result'->>'claim_id'
          AND m.receipt_id = NEW.snapshot->'result'->>'receipt_id'
          AND m.raw_response_id = NEW.snapshot->'result'->>'raw_response_id'
          AND m.request_payload_sha256 =
              NEW.snapshot->'result'->>'request_payload_sha256'
          AND m.claim_payload_sha256 =
              NEW.snapshot->'result'->>'claim_payload_sha256'
          AND m.receipt_payload_sha256 =
              NEW.snapshot->'result'->>'receipt_payload_sha256'
          AND m.raw_metadata_sha256 =
              NEW.snapshot->'result'->>'raw_metadata_sha256'
          AND m.materialized_by = NEW.snapshot->>'materialized_by'
          AND m.materialized_at =
              (NEW.snapshot->>'materialized_at')::timestamptz
    ) THEN
        RAISE EXCEPTION 'server-managed AI requirement run lacks exact materialization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$
"""
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ai_requirement_run_materialization_required "
        "AFTER INSERT ON document_ai_requirement_runs DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION "
        "ensure_ai_transfer_requirement_run_has_materialization()"
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
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname = 'procurement_app') THEN "
        f"GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER ai_requirement_run_materialization_required ON document_ai_requirement_runs"
    )
    op.execute("DROP FUNCTION ensure_ai_transfer_requirement_run_has_materialization()")
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION enforce_ai_transfer_requirement_materialization_insert()")
    op.drop_constraint(
        "uq_ai_transfer_raw_materialization_binding",
        "ai_transfer_raw_responses",
        type_="unique",
    )
    op.drop_constraint(
        "uq_ai_transfer_receipt_materialization_binding",
        "ai_transfer_dispatch_receipts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_ai_transfer_claim_materialization_binding",
        "ai_transfer_dispatch_claims",
        type_="unique",
    )
    _replace_run_snapshot_constraints(v2=False)
