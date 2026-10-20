"""Immutable bounded EAEU manufacturer search evidence."""

from alembic import op

revision = "20261006_09"
down_revision = "20261006_08"
branch_labels = None
depends_on = None

TABLES = (
    "manufacturer_search_runs",
    "manufacturer_search_attempts",
    "manufacturer_search_results",
)


def _protect(table: str) -> None:
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
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


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    op.execute("""CREATE TABLE manufacturer_search_runs (
      company_id TEXT NOT NULL, run_id TEXT NOT NULL, command_id TEXT NOT NULL,
      query VARCHAR(80) NOT NULL, parser_revision TEXT NOT NULL, request_body BYTEA NOT NULL,
      request_sha256 VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_manufacturer_search_runs PRIMARY KEY(company_id,run_id),
      CONSTRAINT uq_manufacturer_search_command UNIQUE(company_id,command_id),
      CONSTRAINT ck_manufacturer_search_runs_values CHECK ((
        btrim(company_id)<>'' AND run_id ~ '^[0-9a-f-]{36}$'
        AND command_id ~ '^[0-9a-f-]{36}$' AND char_length(query) BETWEEN 1 AND 80
        AND parser_revision='eaeu-registry-parser-v1' AND octet_length(request_body)<=1024
        AND request_sha256=encode(sha256(request_body),'hex')
      ) IS TRUE)
    )""")
    op.execute("""CREATE INDEX ix_manufacturer_search_runs_company_created
      ON manufacturer_search_runs(company_id,created_at)""")
    op.execute("""CREATE TABLE manufacturer_search_attempts (
      company_id TEXT NOT NULL, attempt_id TEXT NOT NULL, run_id TEXT NOT NULL,
      status TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT pk_manufacturer_search_attempts PRIMARY KEY(company_id,attempt_id),
      CONSTRAINT uq_manufacturer_search_attempt_run UNIQUE(company_id,run_id),
      CONSTRAINT uq_manufacturer_search_attempt_identity UNIQUE(company_id,attempt_id,run_id),
      CONSTRAINT fk_manufacturer_search_attempt_run FOREIGN KEY(company_id,run_id)
        REFERENCES manufacturer_search_runs(company_id,run_id),
      CONSTRAINT ck_manufacturer_search_attempt_values CHECK ((
        attempt_id ~ '^[0-9a-f-]{36}$' AND status='STARTED'
      ) IS TRUE)
    )""")
    op.execute("""CREATE TABLE manufacturer_search_results (
      company_id TEXT NOT NULL, run_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
      status TEXT NOT NULL, reason_code TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL,
      finished_at TIMESTAMPTZ NOT NULL, response_body BYTEA, response_sha256 VARCHAR(64),
      response_byte_size INTEGER, matched_count INTEGER, candidate_count INTEGER NOT NULL,
      CONSTRAINT pk_manufacturer_search_results PRIMARY KEY(company_id,run_id),
      CONSTRAINT uq_manufacturer_search_result_attempt UNIQUE(company_id,attempt_id),
      CONSTRAINT fk_manufacturer_search_result_attempt
        FOREIGN KEY(company_id,attempt_id,run_id)
        REFERENCES manufacturer_search_attempts(company_id,attempt_id,run_id),
      CONSTRAINT ck_manufacturer_search_result_bounds CHECK ((
        (status='COMPLETED' AND reason_code='VERIFIED_RESPONSE'
          AND response_body IS NOT NULL AND response_sha256 ~ '^[0-9a-f]{64}$'
          AND response_byte_size=octet_length(response_body)
          AND response_sha256=encode(sha256(response_body),'hex')
          AND response_byte_size BETWEEN 1 AND 524288 AND matched_count>=0
          AND candidate_count BETWEEN 0 AND 10 AND candidate_count<=matched_count)
        OR
        (status='SOURCE_ERROR' AND reason_code='SOURCE_UNAVAILABLE_OR_CHANGED'
          AND matched_count IS NULL AND candidate_count=0 AND (
            (response_body IS NULL AND response_sha256 IS NULL AND response_byte_size IS NULL)
            OR (response_body IS NOT NULL AND response_sha256 ~ '^[0-9a-f]{64}$'
              AND response_byte_size=octet_length(response_body)
              AND response_sha256=encode(sha256(response_body),'hex')
              AND response_byte_size BETWEEN 0 AND 524288)))
      ) IS TRUE)
    )""")
    for table in TABLES:
        _protect(table)


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    for table in reversed(TABLES):
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM {table}) THEN "
            "RAISE EXCEPTION 'manufacturer search history must be preserved'; END IF; END $$"
        )
        op.drop_table(table)
