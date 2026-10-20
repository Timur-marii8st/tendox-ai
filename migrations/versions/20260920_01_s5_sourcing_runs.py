"""Persist immutable case-bound sourcing observations.

Revision ID: 20260920_01
Revises: 20260918_01
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_01"
down_revision: str | None = "20260918_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sourcing_runs"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("source_content", sa.LargeBinary(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "run_id", name="pk_sourcing_runs"),
        sa.ForeignKeyConstraint(
            ["company_id", "case_id", "case_version"],
            ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
            name="fk_sourcing_runs_case_version",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_sourcing_runs_company_nonempty"),
        sa.CheckConstraint("run_id <> ''", name="ck_sourcing_runs_id_nonempty"),
        sa.CheckConstraint("case_id <> ''", name="ck_sourcing_runs_case_nonempty"),
        sa.CheckConstraint("case_version >= 1", name="ck_sourcing_runs_version_positive"),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'SOURCE_ERROR')", name="ck_sourcing_runs_status"
        ),
        sa.CheckConstraint(
            "((status = 'COMPLETED' AND source_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_sha256 = encode(sha256(source_content), 'hex') "
            f"AND octet_length(source_content) BETWEEN 1 AND {MAX_SNAPSHOT_BYTES}) "
            "OR (status = 'SOURCE_ERROR' AND source_sha256 IS NULL AND source_content IS NULL))",
            name="ck_sourcing_runs_source_shape",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object'", name="ck_sourcing_runs_result_object"
        ),
        sa.CheckConstraint(
            "result->>'company_id' IS NOT DISTINCT FROM company_id",
            name="ck_sourcing_runs_result_company",
        ),
        sa.CheckConstraint(
            "result->>'run_id' IS NOT DISTINCT FROM run_id", name="ck_sourcing_runs_result_id"
        ),
        sa.CheckConstraint(
            "result->>'case_id' IS NOT DISTINCT FROM case_id", name="ck_sourcing_runs_result_case"
        ),
        sa.CheckConstraint(
            "(result->>'case_version')::integer IS NOT DISTINCT FROM case_version",
            name="ck_sourcing_runs_result_version",
        ),
        sa.CheckConstraint(
            "result->>'status' IS NOT DISTINCT FROM status", name="ck_sourcing_runs_result_status"
        ),
        sa.CheckConstraint(
            "(result->>'created_at')::timestamptz IS NOT DISTINCT FROM created_at",
            name="ck_sourcing_runs_result_created",
        ),
        sa.CheckConstraint(
            "((status = 'COMPLETED' AND result->>'source_sha256' IS NOT DISTINCT FROM "
            "source_sha256 AND (result->>'source_byte_size')::integer IS NOT DISTINCT FROM "
            "octet_length(source_content)) OR (status = 'SOURCE_ERROR' AND "
            "result->'source_sha256' = 'null'::jsonb AND "
            "result->'source_byte_size' = 'null'::jsonb))",
            name="ck_sourcing_runs_result_source",
        ),
    )
    op.create_index(
        "ix_sourcing_runs_company_case_created",
        TABLE,
        ["company_id", "case_id", "case_version", "created_at", "run_id"],
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
    op.drop_table(TABLE)
