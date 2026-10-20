"""Independent manufacturer identity and role review."""

from alembic import op

revision = "20261006_10"
down_revision = "20261006_09"
branch_labels = None
depends_on = None

TABLES = (
    "manufacturer_evidence_artifacts",
    "manufacturer_review_proposals",
    "manufacturer_review_decisions",
)


def _protect(table: str) -> None:
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for sql in (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({tenant})",
        f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({tenant})",
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()",
        f"REVOKE ALL ON TABLE {table} FROM PUBLIC",
        f"GRANT SELECT, INSERT ON {table} TO procurement_app",
    ):
        op.execute(sql)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR','MODEL_BRAND_REVIEWER','MANUFACTURER_REVIEWER',"
        "'COMPLETENESS_REVIEWER','AI_REQUIREMENTS_REVIEWER','AI_TRANSFER_APPROVER',"
        "'PARTICIPATION_APPROVER','APPLICATION_REVIEWER',"
        "'APPLICATION_SUBMISSION_APPROVER','APPLICATION_SUBMISSION_EXECUTOR','AUDITOR')",
    )
    op.execute("""CREATE TABLE manufacturer_evidence_artifacts(
      company_id TEXT NOT NULL, artifact_id TEXT NOT NULL, command_id TEXT NOT NULL,
      source_title TEXT NOT NULL, source_url TEXT NOT NULL, original_filename TEXT NOT NULL,
      media_type TEXT NOT NULL, content BYTEA NOT NULL, byte_size INTEGER NOT NULL,
      sha256 VARCHAR(64) NOT NULL, uploaded_by TEXT NOT NULL, uploaded_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_manufacturer_evidence_artifacts PRIMARY KEY(company_id,artifact_id),
      CONSTRAINT uq_manufacturer_evidence_command UNIQUE(company_id,command_id),
      CONSTRAINT ck_manufacturer_evidence_values CHECK ((btrim(company_id)<>''
        AND artifact_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$'
        AND source_url ~ '^https://' AND media_type='application/pdf'
        AND byte_size BETWEEN 1 AND 2097152 AND byte_size=octet_length(content)
        AND sha256=encode(sha256(content),'hex') AND btrim(uploaded_by)<>'') IS TRUE)
    )""")
    op.execute("""CREATE TABLE manufacturer_review_proposals(
      company_id TEXT NOT NULL, proposal_id TEXT NOT NULL, command_id TEXT NOT NULL,
      run_id TEXT NOT NULL, record_id VARCHAR(24) NOT NULL, dossier_sha256 VARCHAR(64) NOT NULL,
      proposal_sha256 VARCHAR(64) NOT NULL, proposal_canonical BYTEA NOT NULL,
      proposal JSONB NOT NULL, proposed_by TEXT NOT NULL, proposed_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_manufacturer_review_proposals PRIMARY KEY(company_id,proposal_id),
      CONSTRAINT uq_manufacturer_review_proposal_command UNIQUE(company_id,command_id),
      CONSTRAINT fk_manufacturer_review_proposal_run FOREIGN KEY(company_id,run_id)
        REFERENCES manufacturer_search_runs(company_id,run_id),
      CONSTRAINT ck_manufacturer_review_proposal_values CHECK ((
        proposal_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$'
        AND record_id ~ '^[0-9a-f]{24}$' AND dossier_sha256 ~ '^[0-9a-f]{64}$'
        AND proposal_sha256=encode(sha256(proposal_canonical),'hex')
        AND jsonb_typeof(proposal)='object' AND octet_length(proposal_canonical)<=65536
        AND proposal->>'proposal_id' IS NOT DISTINCT FROM proposal_id
        AND proposal->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256
        AND proposal->>'dossier_sha256' IS NOT DISTINCT FROM dossier_sha256
        AND proposal->>'proposed_by' IS NOT DISTINCT FROM proposed_by) IS TRUE)
    )""")
    op.execute("""CREATE TABLE manufacturer_review_decisions(
      company_id TEXT NOT NULL, decision_id TEXT NOT NULL, command_id TEXT NOT NULL,
      proposal_id TEXT NOT NULL, proposal_sha256 VARCHAR(64) NOT NULL,
      decision_sha256 VARCHAR(64) NOT NULL, decision_canonical BYTEA NOT NULL,
      decision JSONB NOT NULL, reviewed_by TEXT NOT NULL, reviewed_at TIMESTAMPTZ NOT NULL,
      effective_until TIMESTAMPTZ,
      CONSTRAINT pk_manufacturer_review_decisions PRIMARY KEY(company_id,decision_id),
      CONSTRAINT uq_manufacturer_review_decision_proposal UNIQUE(company_id,proposal_id),
      CONSTRAINT uq_manufacturer_review_decision_command UNIQUE(company_id,command_id),
      CONSTRAINT fk_manufacturer_review_decision_proposal FOREIGN KEY(company_id,proposal_id)
        REFERENCES manufacturer_review_proposals(company_id,proposal_id),
      CONSTRAINT ck_manufacturer_review_decision_values CHECK ((
        decision_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$'
        AND proposal_sha256 ~ '^[0-9a-f]{64}$'
        AND decision_sha256=encode(sha256(decision_canonical),'hex')
        AND jsonb_typeof(decision)='object' AND octet_length(decision_canonical)<=65536
        AND decision->>'decision_id' IS NOT DISTINCT FROM decision_id
        AND decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256
        AND decision->>'proposal_id' IS NOT DISTINCT FROM proposal_id
        AND decision->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256
        AND decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by) IS TRUE)
    )""")
    for table in TABLES:
        _protect(table)


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    for table in reversed(TABLES):
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM {table}) THEN "
            "RAISE EXCEPTION 'manufacturer review history must be preserved'; END IF; END $$"
        )
        op.drop_table(table)
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role", "api_keys",
        "access_role IN ('OPERATOR','MODEL_BRAND_REVIEWER','COMPLETENESS_REVIEWER',"
        "'AI_REQUIREMENTS_REVIEWER','AI_TRANSFER_APPROVER','PARTICIPATION_APPROVER',"
        "'APPLICATION_REVIEWER','APPLICATION_SUBMISSION_APPROVER',"
        "'APPLICATION_SUBMISSION_EXECUTOR','AUDITOR')",
    )
