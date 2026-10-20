"""Persist independently reviewed requirement sets and exact case bindings.

Revision ID: 20260920_02
Revises: 20260920_01
Create Date: 2026-09-20
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_02"
down_revision: str | None = "20260920_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
PROPOSALS = "reviewed_requirement_set_proposals"
DECISIONS = "reviewed_requirement_set_decisions"
BINDINGS = "case_requirement_set_bindings"


def _protect(table: str) -> None:
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
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
        f"THEN GRANT SELECT, INSERT ON {table} TO procurement_app; END IF; END $$"
    )


def upgrade() -> None:
    op.create_table(
        PROPOSALS,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("set_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_document_sha256", sa.String(64), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("proposal", postgresql.JSONB(), nullable=False),
        sa.Column("prepared_by", sa.Text(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "set_id", name="pk_reviewed_requirement_set_proposals"
        ),
        sa.UniqueConstraint(
            "company_id",
            "set_id",
            "proposal_sha256",
            name="uq_reviewed_requirement_set_proposal_exact",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_document_id", "source_document_sha256"],
            ["documents.company_id", "documents.document_id", "documents.sha256"],
            name="fk_reviewed_requirement_set_source",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_reviewed_requirement_set_company_nonempty"),
        sa.CheckConstraint("set_id <> ''", name="ck_reviewed_requirement_set_id_nonempty"),
        sa.CheckConstraint(
            "prepared_by <> ''", name="ck_reviewed_requirement_set_preparer_nonempty"
        ),
        sa.CheckConstraint(
            "proposal_sha256 ~ '^[0-9a-f]{64}$' AND source_document_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_reviewed_requirement_set_digests",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposal) = 'object'", name="ck_requirement_set_proposal_object"
        ),
        sa.CheckConstraint(
            "proposal->>'schema_version' IS NOT DISTINCT FROM 'reviewed-requirement-set-proposal-v1' AND "
            "proposal->>'company_id' IS NOT DISTINCT FROM company_id AND "
            "proposal->>'set_id' IS NOT DISTINCT FROM set_id AND "
            "proposal->>'source_document_id' IS NOT DISTINCT FROM source_document_id AND "
            "proposal->>'source_document_sha256' IS NOT DISTINCT FROM source_document_sha256 AND "
            "proposal->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
            "proposal->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND "
            "(proposal->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at",
            name="ck_reviewed_requirement_set_proposal_identity",
        ),
    )
    _protect(PROPOSALS)

    op.create_table(
        DECISIONS,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("set_id", sa.Text(), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision", postgresql.JSONB(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "set_id", name="pk_reviewed_requirement_set_decisions"
        ),
        sa.UniqueConstraint(
            "company_id",
            "set_id",
            "proposal_sha256",
            "decision_sha256",
            name="uq_reviewed_requirement_set_decision_exact",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "set_id", "proposal_sha256"],
            [
                "reviewed_requirement_set_proposals.company_id",
                "reviewed_requirement_set_proposals.set_id",
                "reviewed_requirement_set_proposals.proposal_sha256",
            ],
            name="fk_reviewed_requirement_set_decision_proposal",
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNKNOWN')", name="ck_requirement_set_decision_status"
        ),
        sa.CheckConstraint("reviewed_by <> ''", name="ck_requirement_set_reviewer_nonempty"),
        sa.CheckConstraint(
            "proposal_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_requirement_set_decision_digests",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(decision) = 'object'", name="ck_requirement_set_decision_object"
        ),
        sa.CheckConstraint(
            "decision->>'schema_version' IS NOT DISTINCT FROM 'reviewed-requirement-set-decision-v1' AND "
            "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
            "decision->>'set_id' IS NOT DISTINCT FROM set_id AND "
            "decision->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
            "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
            "decision->>'status' IS NOT DISTINCT FROM status AND "
            "decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by AND "
            "(decision->>'reviewed_at')::timestamptz IS NOT DISTINCT FROM reviewed_at",
            name="ck_reviewed_requirement_set_decision_identity",
        ),
    )
    _protect(DECISIONS)

    op.create_table(
        BINDINGS,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Text(), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("binding_sha256", sa.String(64), nullable=False),
        sa.Column("binding", postgresql.JSONB(), nullable=False),
        sa.Column("bound_by", sa.Text(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "binding_id", name="pk_case_requirement_set_bindings"
        ),
        sa.UniqueConstraint(
            "company_id", "case_id", "case_version", name="uq_case_requirement_set_binding_version"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "case_id", "case_version"],
            ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
            name="fk_case_requirement_set_binding_case",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "set_id", "proposal_sha256", "decision_sha256"],
            [
                "reviewed_requirement_set_decisions.company_id",
                "reviewed_requirement_set_decisions.set_id",
                "reviewed_requirement_set_decisions.proposal_sha256",
                "reviewed_requirement_set_decisions.decision_sha256",
            ],
            name="fk_case_requirement_set_binding_decision",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_case_requirement_set_company_nonempty"),
        sa.CheckConstraint("binding_id <> ''", name="ck_case_requirement_set_binding_nonempty"),
        sa.CheckConstraint(
            "case_id <> '' AND case_version >= 1", name="ck_case_requirement_set_case"
        ),
        sa.CheckConstraint("set_id <> ''", name="ck_case_requirement_set_id_nonempty"),
        sa.CheckConstraint("bound_by <> ''", name="ck_case_requirement_set_binder_nonempty"),
        sa.CheckConstraint(
            "proposal_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$' AND binding_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_case_requirement_set_digests",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(binding) = 'object'", name="ck_case_requirement_set_binding_object"
        ),
        sa.CheckConstraint(
            "binding->>'schema_version' IS NOT DISTINCT FROM 'case-requirement-set-binding-v1' AND "
            "binding->>'company_id' IS NOT DISTINCT FROM company_id AND "
            "binding->>'binding_id' IS NOT DISTINCT FROM binding_id AND "
            "binding->>'case_id' IS NOT DISTINCT FROM case_id AND "
            "(binding->>'case_version')::integer IS NOT DISTINCT FROM case_version AND "
            "binding->>'set_id' IS NOT DISTINCT FROM set_id AND "
            "binding->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND "
            "binding->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
            "binding->>'binding_sha256' IS NOT DISTINCT FROM binding_sha256 AND "
            "binding->>'bound_by' IS NOT DISTINCT FROM bound_by AND "
            "(binding->>'bound_at')::timestamptz IS NOT DISTINCT FROM bound_at",
            name="ck_case_requirement_set_binding_identity",
        ),
    )
    _protect(BINDINGS)


def downgrade() -> None:
    op.drop_table(BINDINGS)
    op.drop_table(DECISIONS)
    op.drop_table(PROPOSALS)
