"""Persist imported AI requirement runs and independent reviews.

Revision ID: 20260917_01
Revises: 20260916_04
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_01"
down_revision: str | None = "20260916_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "company_id = nullif(current_setting('app.company_id', true), '')"


def _append_only(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_select_tenant ON {table} FOR SELECT USING ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE POLICY {table}_insert_tenant ON {table} FOR INSERT WITH CHECK ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")


def upgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER', "
        "'AI_REQUIREMENTS_REVIEWER')",
    )
    op.create_table(
        "document_ai_requirement_runs",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "run_id", name="pk_document_ai_requirement_runs"),
        sa.UniqueConstraint(
            "company_id",
            "run_id",
            "evidence_sha256",
            name="uq_ai_requirement_run_evidence_binding",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_document_id"],
            ["documents.company_id", "documents.document_id"],
            name="fk_ai_requirement_run_source_document",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_ai_requirement_run_company_nonempty"),
        sa.CheckConstraint("run_id <> ''", name="ck_ai_requirement_run_id_nonempty"),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ai_requirement_run_source_sha256"
        ),
        sa.CheckConstraint(
            "evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ai_requirement_run_evidence_sha256",
        ),
        sa.CheckConstraint(
            "(jsonb_typeof(snapshot) = 'object' AND "
            "snapshot ?& ARRAY['schema_version','origin','company_id','run_id',"
            "'source_document_id','source_sha256','extraction','report',"
            "'completeness_status','submitted_by','submitted_at','evidence_sha256']) IS TRUE",
            name="ck_ai_requirement_run_snapshot_shape",
        ),
        sa.CheckConstraint(
            "(snapshot->>'schema_version' = 'persisted-ai-requirement-run-v1' AND "
            "snapshot->>'origin' = 'IMPORTED_REPORT' AND "
            "snapshot->>'company_id' = company_id AND snapshot->>'run_id' = run_id AND "
            "snapshot->>'source_document_id' = source_document_id AND "
            "snapshot->>'source_sha256' = source_sha256 AND "
            "snapshot->>'evidence_sha256' = evidence_sha256 AND "
            "snapshot->>'completeness_status' = 'UNKNOWN') IS TRUE",
            name="ck_ai_requirement_run_snapshot_identity",
        ),
        sa.CheckConstraint(
            "(jsonb_typeof(snapshot->'extraction') = 'object' AND "
            "jsonb_typeof(snapshot->'report') = 'object') IS TRUE",
            name="ck_ai_requirement_run_payload_objects",
        ),
    )
    op.create_index(
        "ix_ai_requirement_run_company_created",
        "document_ai_requirement_runs",
        ["company_id", "created_at", "run_id"],
    )
    op.create_table(
        "document_ai_requirement_review_decisions",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "run_id", name="pk_document_ai_requirement_review_decisions"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "run_id", "evidence_sha256"],
            [
                "document_ai_requirement_runs.company_id",
                "document_ai_requirement_runs.run_id",
                "document_ai_requirement_runs.evidence_sha256",
            ],
            name="fk_ai_requirement_decision_run_evidence",
        ),
        sa.CheckConstraint(
            "evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ai_requirement_decision_evidence_sha256",
        ),
        sa.CheckConstraint(
            "reviewed_by <> ''", name="ck_ai_requirement_decision_reviewer_nonempty"
        ),
        sa.CheckConstraint(
            "(jsonb_typeof(decision) = 'object' AND "
            "decision ?& ARRAY['schema_version','company_id','run_id','evidence_sha256',"
            "'candidate_decisions','reviewed_by','reviewed_at','completeness_status']) IS TRUE",
            name="ck_ai_requirement_decision_shape",
        ),
        sa.CheckConstraint(
            "(decision->>'schema_version' = 'persisted-ai-requirement-review-v1' AND "
            "decision->>'company_id' = company_id AND decision->>'run_id' = run_id AND "
            "decision->>'evidence_sha256' = evidence_sha256 AND "
            "decision->>'reviewed_by' = reviewed_by AND "
            "decision->>'completeness_status' = 'UNKNOWN' AND "
            "jsonb_typeof(decision->'candidate_decisions') = 'array') IS TRUE",
            name="ck_ai_requirement_decision_identity",
        ),
    )
    for table in (
        "document_ai_requirement_runs",
        "document_ai_requirement_review_decisions",
    ):
        _append_only(table)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_ai_requirement_runs TO procurement_app;
                GRANT SELECT, INSERT ON document_ai_requirement_review_decisions TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("document_ai_requirement_review_decisions")
    op.drop_index(
        "ix_ai_requirement_run_company_created",
        table_name="document_ai_requirement_runs",
    )
    op.drop_table("document_ai_requirement_runs")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER')",
    )
