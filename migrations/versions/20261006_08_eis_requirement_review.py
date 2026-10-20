"""Immutable operator proposals and independent requirement decisions."""

from alembic import op

revision = "20261006_08"
down_revision = "20261006_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    op.execute("""CREATE TABLE eis_requirement_review_proposals (
      company_id TEXT NOT NULL, proposal_id TEXT NOT NULL, request_key VARCHAR(64) NOT NULL,
      product_run_id TEXT NOT NULL, proposal JSONB NOT NULL, proposal_sha256 VARCHAR(64) NOT NULL,
      prepared_by TEXT NOT NULL, prepared_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_eis_requirement_review_proposals PRIMARY KEY(company_id,proposal_id),
      CONSTRAINT uq_eis_requirement_review_proposal_key UNIQUE(company_id,request_key),
      CONSTRAINT fk_eis_requirement_review_product FOREIGN KEY(company_id,product_run_id)
        REFERENCES eis_supplier_product_reports(company_id,run_id),
      CONSTRAINT ck_eis_requirement_review_proposal CHECK ((
        btrim(company_id)<>'' AND btrim(prepared_by)<>'' AND request_key ~ '^[0-9a-f]{64}$'
        AND proposal_sha256 ~ '^[0-9a-f]{64}$' AND proposal_id ~ '^[0-9a-f-]{36}$'
        AND jsonb_typeof(proposal)='object' AND octet_length(proposal::text)<=393216
        AND proposal->>'company_id'=company_id AND proposal->>'proposal_id'=proposal_id
        AND proposal->>'proposal_sha256'=proposal_sha256
        AND proposal->>'prepared_by'=prepared_by
        AND (proposal->>'prepared_at')::timestamptz=prepared_at
        AND proposal->'preview'->'product'->>'run_id'
          = product_run_id) IS TRUE))""")
    op.execute("""CREATE TABLE eis_requirement_review_decisions (
      company_id TEXT NOT NULL, decision_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
      request_sha256 VARCHAR(64) NOT NULL, decision JSONB NOT NULL,
      decision_sha256 VARCHAR(64) NOT NULL, reviewed_by TEXT NOT NULL,
      reviewed_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_eis_requirement_review_decisions PRIMARY KEY(company_id,decision_id),
      CONSTRAINT uq_eis_requirement_review_decision UNIQUE(company_id,proposal_id),
      CONSTRAINT fk_eis_requirement_review_proposal FOREIGN KEY(company_id,proposal_id)
        REFERENCES eis_requirement_review_proposals(company_id,proposal_id),
      CONSTRAINT ck_eis_requirement_review_decision CHECK ((
        btrim(company_id)<>'' AND btrim(reviewed_by)<>'' AND request_sha256 ~ '^[0-9a-f]{64}$'
        AND decision_sha256 ~ '^[0-9a-f]{64}$' AND decision_id ~ '^[0-9a-f-]{36}$'
        AND jsonb_typeof(decision)='object' AND octet_length(decision::text)<=393216
        AND decision->>'company_id'=company_id AND decision->>'decision_id'=decision_id
        AND decision->>'decision_sha256'=decision_sha256 AND decision->>'reviewed_by'=reviewed_by
        AND (decision->>'reviewed_at')::timestamptz=reviewed_at
        AND decision->'request'->>'proposal_id'=proposal_id) IS TRUE))""")
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for table in ("eis_requirement_review_proposals", "eis_requirement_review_decisions"):
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({tenant})",
            f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({tenant})",
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()",
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC",
            f"GRANT SELECT, INSERT ON {table} TO procurement_app",
        ):
            op.execute(statement)


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    for table in ("eis_requirement_review_decisions", "eis_requirement_review_proposals"):
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM {table}) THEN "
            "RAISE EXCEPTION 'requirement review history must be preserved'; END IF; END $$"
        )
        op.drop_table(table)
