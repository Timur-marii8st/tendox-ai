"""Persist independent exact server-offer reviews.

Revision ID: 20260920_05
Revises: 20260920_04
Create Date: 2026-09-20
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_05"
down_revision: str | None = "20260920_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "server_offer_review_decisions"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("offer_id", sa.Text(), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("requirement_set_id", sa.Text(), nullable=False),
        sa.Column("requirement_set_proposal_sha256", sa.String(64), nullable=False),
        sa.Column("requirement_set_decision_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("decision", postgresql.JSONB(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("company_id", "offer_id", name="pk_server_offer_review_decisions"),
        sa.UniqueConstraint("company_id", "offer_id", "proposal_sha256", "decision_sha256", name="uq_server_offer_review_exact"),
        sa.ForeignKeyConstraint(["company_id", "offer_id", "proposal_sha256"], ["server_offer_proposals.company_id", "server_offer_proposals.offer_id", "server_offer_proposals.proposal_sha256"], name="fk_server_offer_review_proposal"),
        sa.ForeignKeyConstraint(["company_id", "requirement_set_id", "requirement_set_proposal_sha256", "requirement_set_decision_sha256"], ["reviewed_requirement_set_decisions.company_id", "reviewed_requirement_set_decisions.set_id", "reviewed_requirement_set_decisions.proposal_sha256", "reviewed_requirement_set_decisions.decision_sha256"], name="fk_server_offer_review_requirement_decision"),
        sa.CheckConstraint("status IN ('PASS', 'FAIL', 'UNKNOWN')", name="ck_server_offer_review_status"),
        sa.CheckConstraint("btrim(reviewed_by) <> ''", name="ck_server_offer_review_reviewer"),
        sa.CheckConstraint("proposal_sha256 ~ '^[0-9a-f]{64}$' AND requirement_set_proposal_sha256 ~ '^[0-9a-f]{64}$' AND requirement_set_decision_sha256 ~ '^[0-9a-f]{64}$' AND decision_sha256 ~ '^[0-9a-f]{64}$'", name="ck_server_offer_review_digests"),
        sa.CheckConstraint("jsonb_typeof(decision) = 'object'", name="ck_server_offer_review_object"),
        sa.CheckConstraint("decision->>'schema_version' = 'server-offer-review-decision-v1' AND decision->>'company_id' IS NOT DISTINCT FROM company_id AND decision->>'offer_id' IS NOT DISTINCT FROM offer_id AND decision->>'proposal_sha256' IS NOT DISTINCT FROM proposal_sha256 AND decision->>'requirement_set_id' IS NOT DISTINCT FROM requirement_set_id AND decision->>'requirement_set_proposal_sha256' IS NOT DISTINCT FROM requirement_set_proposal_sha256 AND decision->>'requirement_set_decision_sha256' IS NOT DISTINCT FROM requirement_set_decision_sha256 AND decision->>'status' IS NOT DISTINCT FROM status AND decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND decision->>'reviewed_by' IS NOT DISTINCT FROM reviewed_by AND (decision->>'reviewed_at')::timestamptz IS NOT DISTINCT FROM reviewed_at", name="ck_server_offer_review_identity"),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()")
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') " f"THEN GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$")


def downgrade() -> None:
    op.drop_table(TABLE)
