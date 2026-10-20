"""Persist exact BOM and supplier quote proposals.

Revision ID: 20260920_04
Revises: 20260920_03
Create Date: 2026-09-20
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_04"
down_revision: str | None = "20260920_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "server_offer_proposals"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("offer_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("requirement_set_binding_id", sa.Text(), nullable=False),
        sa.Column("requirement_set_binding_sha256", sa.String(64), nullable=False),
        sa.Column("sourcing_run_id", sa.Text(), nullable=False),
        sa.Column("lead_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_document_sha256", sa.String(64), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("proposal", postgresql.JSONB(), nullable=False),
        sa.Column("prepared_by", sa.Text(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "offer_id", name="pk_server_offer_proposals"),
        sa.UniqueConstraint(
            "company_id", "offer_id", "proposal_sha256", name="uq_server_offer_proposal_exact"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "case_id", "case_version"],
            ["case_versions.company_id", "case_versions.case_id", "case_versions.version"],
            name="fk_server_offer_case_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "requirement_set_binding_id"],
            ["case_requirement_set_bindings.company_id", "case_requirement_set_bindings.binding_id"],
            name="fk_server_offer_requirement_binding",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sourcing_run_id"],
            ["sourcing_runs.company_id", "sourcing_runs.run_id"],
            name="fk_server_offer_sourcing_run",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_document_id", "source_document_sha256"],
            ["documents.company_id", "documents.document_id", "documents.sha256"],
            name="fk_server_offer_source_document",
        ),
        sa.CheckConstraint("btrim(company_id) <> ''", name="ck_server_offer_company"),
        sa.CheckConstraint("btrim(offer_id) <> ''", name="ck_server_offer_id"),
        sa.CheckConstraint("btrim(case_id) <> '' AND case_version >= 1", name="ck_server_offer_case"),
        sa.CheckConstraint("btrim(lead_id) <> ''", name="ck_server_offer_lead"),
        sa.CheckConstraint(
            "requirement_set_binding_sha256 ~ '^[0-9a-f]{64}$' AND source_document_sha256 ~ '^[0-9a-f]{64}$' AND proposal_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_server_offer_digests",
        ),
        sa.CheckConstraint("jsonb_typeof(proposal) = 'object'", name="ck_server_offer_object"),
        sa.CheckConstraint(
            "proposal->>'schema_version' = 'server-offer-proposal-v1' AND proposal->>'company_id' IS NOT DISTINCT FROM company_id AND proposal->>'offer_id' IS NOT DISTINCT FROM offer_id AND proposal->>'case_id' IS NOT DISTINCT FROM case_id AND (proposal->>'case_version')::integer IS NOT DISTINCT FROM case_version AND proposal->>'requirement_set_binding_id' IS NOT DISTINCT FROM requirement_set_binding_id AND proposal->>'requirement_set_binding_sha256' IS NOT DISTINCT FROM requirement_set_binding_sha256 AND proposal->>'sourcing_run_id' IS NOT DISTINCT FROM sourcing_run_id AND proposal->>'lead_id' IS NOT DISTINCT FROM lead_id AND proposal->>'source_document_id' IS NOT DISTINCT FROM source_document_id AND proposal->>'source_document_sha256' IS NOT DISTINCT FROM source_document_sha256 AND proposal->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND proposal->>'technical_status' = 'UNKNOWN' AND proposal->>'review_status' = 'PENDING_REVIEW' AND proposal->>'prepared_by' IS NOT DISTINCT FROM prepared_by AND (proposal->>'prepared_at')::timestamptz IS NOT DISTINCT FROM prepared_at",
            name="ck_server_offer_identity",
        ),
    )
    op.create_index(
        "ix_server_offer_case",
        TABLE,
        ["company_id", "case_id", "case_version", "prepared_at", "offer_id"],
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
    op.drop_index("ix_server_offer_case", table_name=TABLE)
    op.drop_table(TABLE)
