"""Persist explicit case bindings to terminal document-set decisions.

Revision ID: 20260918_01
Revises: 20260917_12
Create Date: 2026-09-18
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260918_01"
down_revision: str | None = "20260917_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
TABLE = "case_document_evidence_bindings"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("manifest_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("binding_sha256", sa.String(64), nullable=False),
        sa.Column("binding", postgresql.JSONB(), nullable=False),
        sa.Column("bound_by", sa.Text(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id",
            "binding_id",
            name="pk_case_document_evidence_bindings",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "manifest_id", "manifest_evidence_sha256"],
            [
                "document_set_evidence_manifests.company_id",
                "document_set_evidence_manifests.manifest_id",
                "document_set_evidence_manifests.evidence_sha256",
            ],
            name="fk_case_evidence_binding_manifest",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "manifest_id"],
            [
                "document_set_completeness_decisions.company_id",
                "document_set_completeness_decisions.manifest_id",
            ],
            name="fk_case_evidence_binding_decision",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_case_evidence_company_nonempty"),
        sa.CheckConstraint("binding_id <> ''", name="ck_case_evidence_binding_nonempty"),
        sa.CheckConstraint("manifest_id <> ''", name="ck_case_evidence_manifest_nonempty"),
        sa.CheckConstraint(
            "manifest_evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_case_evidence_manifest_sha256",
        ),
        sa.CheckConstraint(
            "decision_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_case_evidence_decision_sha256",
        ),
        sa.CheckConstraint(
            "binding_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_case_evidence_binding_sha256",
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_case_evidence_status",
        ),
        sa.CheckConstraint("bound_by <> ''", name="ck_case_evidence_binder_nonempty"),
        sa.CheckConstraint(
            "jsonb_typeof(binding) = 'object'",
            name="ck_case_evidence_binding_object",
        ),
        sa.CheckConstraint(
            "binding->>'schema_version' IS NOT DISTINCT FROM 'case-document-evidence-binding-v1' AND "
            "binding->>'company_id' IS NOT DISTINCT FROM company_id AND "
            "binding->>'binding_id' IS NOT DISTINCT FROM binding_id AND "
            "binding->>'manifest_id' IS NOT DISTINCT FROM manifest_id AND "
            "binding->>'manifest_evidence_sha256' IS NOT DISTINCT FROM manifest_evidence_sha256 AND "
            "binding->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
            "binding->>'status' IS NOT DISTINCT FROM status AND "
            "binding->>'bound_by' IS NOT DISTINCT FROM bound_by AND "
            "(binding->>'bound_at')::timestamptz IS NOT DISTINCT FROM bound_at AND "
            "binding->>'binding_sha256' IS NOT DISTINCT FROM binding_sha256 AND "
            "created_at IS NOT DISTINCT FROM bound_at",
            name="ck_case_evidence_binding_identity",
        ),
    )
    op.create_index(
        "ix_case_evidence_company_created",
        TABLE,
        ["company_id", "created_at", "binding_id"],
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
