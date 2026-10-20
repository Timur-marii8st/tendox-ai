"""Add immutable persisted document completeness review workflow.

Revision ID: 20260916_04
Revises: 20260916_03
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260916_04"
down_revision: str | None = "20260916_03"
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
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER', 'COMPLETENESS_REVIEWER')",
    )
    op.create_table(
        "document_completeness_reviews",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_document_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "review_id", name="pk_document_completeness_reviews"),
        sa.UniqueConstraint(
            "company_id",
            "review_id",
            "evidence_sha256",
            name="uq_completeness_review_evidence_binding",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_document_id"],
            ["documents.company_id", "documents.document_id"],
            name="fk_completeness_review_source_document",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_completeness_review_company_nonempty"),
        sa.CheckConstraint("review_id <> ''", name="ck_completeness_review_id_nonempty"),
        sa.CheckConstraint(
            "source_document_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_completeness_review_source_sha256",
        ),
        sa.CheckConstraint(
            "evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_completeness_review_evidence_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'", name="ck_completeness_review_snapshot"
        ),
        sa.CheckConstraint(
            "snapshot->>'schema_version' = 'document-completeness-review-v1'",
            name="ck_completeness_review_schema",
        ),
        sa.CheckConstraint(
            "snapshot->>'company_id' = company_id AND snapshot->>'review_id' = review_id",
            name="ck_completeness_review_identity",
        ),
        sa.CheckConstraint(
            "snapshot->>'source_document_id' = source_document_id AND "
            "snapshot->>'source_document_sha256' = source_document_sha256 AND "
            "snapshot->>'evidence_sha256' = evidence_sha256",
            name="ck_completeness_review_source_identity",
        ),
    )
    op.create_index(
        "ix_completeness_review_company_created",
        "document_completeness_reviews",
        ["company_id", "created_at", "review_id"],
    )
    op.create_table(
        "document_completeness_review_decisions",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "review_id", name="pk_document_completeness_review_decisions"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "review_id", "evidence_sha256"],
            [
                "document_completeness_reviews.company_id",
                "document_completeness_reviews.review_id",
                "document_completeness_reviews.evidence_sha256",
            ],
            name="fk_completeness_decision_review",
        ),
        sa.CheckConstraint(
            "evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_completeness_decision_evidence_sha256",
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_completeness_decision_status",
        ),
        sa.CheckConstraint("decided_by <> ''", name="ck_completeness_decider_nonempty"),
        sa.CheckConstraint(
            "jsonb_typeof(decision) = 'object'", name="ck_completeness_decision_object"
        ),
        sa.CheckConstraint(
            "decision->>'schema_version' = 'document-completeness-decision-v1' AND "
            "decision->>'company_id' = company_id AND decision->>'review_id' = review_id AND "
            "decision->>'evidence_sha256' = evidence_sha256 AND decision->>'status' = status",
            name="ck_completeness_decision_identity",
        ),
    )
    for table in (
        "document_completeness_reviews",
        "document_completeness_review_decisions",
    ):
        _append_only(table)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_completeness_reviews TO procurement_app;
                GRANT SELECT, INSERT ON document_completeness_review_decisions TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("document_completeness_review_decisions")
    op.drop_index(
        "ix_completeness_review_company_created",
        table_name="document_completeness_reviews",
    )
    op.drop_table("document_completeness_reviews")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint(
        "ck_api_keys_access_role",
        "api_keys",
        "access_role IN ('OPERATOR', 'MODEL_BRAND_REVIEWER')",
    )
