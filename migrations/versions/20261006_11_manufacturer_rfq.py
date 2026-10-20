"""Immutable no-dispatch manufacturer RFQ drafts."""

from alembic import op

revision = "20261006_11"
down_revision = "20261006_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("""CREATE TABLE manufacturer_rfq_drafts(
      company_id TEXT NOT NULL, draft_id TEXT NOT NULL, command_id TEXT NOT NULL,
      run_id TEXT NOT NULL, record_id VARCHAR(24) NOT NULL,
      proposal_id TEXT NOT NULL, decision_id TEXT NOT NULL,
      manual_inputs_sha256 VARCHAR(64) NOT NULL, draft_sha256 VARCHAR(64) NOT NULL,
      draft_canonical BYTEA NOT NULL, text_sha256 VARCHAR(64) NOT NULL,
      text_content BYTEA NOT NULL, draft JSONB NOT NULL,
      created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_manufacturer_rfq_drafts PRIMARY KEY(company_id,draft_id),
      CONSTRAINT uq_manufacturer_rfq_command UNIQUE(company_id,command_id),
      CONSTRAINT fk_manufacturer_rfq_proposal FOREIGN KEY(company_id,proposal_id)
        REFERENCES manufacturer_review_proposals(company_id,proposal_id),
      CONSTRAINT fk_manufacturer_rfq_decision FOREIGN KEY(company_id,decision_id)
        REFERENCES manufacturer_review_decisions(company_id,decision_id),
      CONSTRAINT ck_manufacturer_rfq_draft_values CHECK ((
        draft_id ~ '^[0-9a-f-]{36}$' AND command_id ~ '^[0-9a-f-]{36}$'
        AND record_id ~ '^[0-9a-f]{24}$' AND manual_inputs_sha256 ~ '^[0-9a-f]{64}$'
        AND draft_sha256=encode(sha256(draft_canonical),'hex')
        AND text_sha256=encode(sha256(text_content),'hex')
        AND octet_length(draft_canonical)<=262144 AND octet_length(text_content)<=131072
        AND jsonb_typeof(draft)='object' AND draft->>'draft_id' IS NOT DISTINCT FROM draft_id
        AND draft->>'command_id' IS NOT DISTINCT FROM command_id
        AND draft->>'run_id' IS NOT DISTINCT FROM run_id
        AND draft->>'proposal_id' IS NOT DISTINCT FROM proposal_id
        AND draft->>'decision_id' IS NOT DISTINCT FROM decision_id
        AND draft->>'manual_inputs_sha256' IS NOT DISTINCT FROM manual_inputs_sha256
        AND draft->>'draft_sha256' IS NOT DISTINCT FROM draft_sha256
        AND draft->>'text_sha256' IS NOT DISTINCT FROM text_sha256
        AND draft->>'created_by' IS NOT DISTINCT FROM created_by
        AND draft->>'status'='DRAFT_NO_DISPATCH') IS TRUE)
    )""")
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    table = "manufacturer_rfq_drafts"
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


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM manufacturer_rfq_drafts) THEN "
        "RAISE EXCEPTION 'manufacturer RFQ draft history must be preserved'; END IF; END $$"
    )
    op.drop_table("manufacturer_rfq_drafts")
