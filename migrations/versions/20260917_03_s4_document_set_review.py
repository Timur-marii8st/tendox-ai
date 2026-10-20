"""Persist terminal completeness decisions for exact document sets.

Revision ID: 20260917_03
Revises: 20260917_02
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_03"
down_revision: str | None = "20260917_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"


def _append_only(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_select_tenant ON {table} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {table}_insert_tenant ON {table} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")


def upgrade() -> None:
    op.create_table(
        "document_set_completeness_decisions",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("manifest_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "manifest_id", name="pk_document_set_completeness_decisions"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "manifest_id", "manifest_evidence_sha256"],
            [
                "document_set_evidence_manifests.company_id",
                "document_set_evidence_manifests.manifest_id",
                "document_set_evidence_manifests.evidence_sha256",
            ],
            name="fk_document_set_decision_manifest",
        ),
        sa.CheckConstraint(
            "manifest_evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_decision_manifest_sha256",
        ),
        sa.CheckConstraint(
            "decision_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_decision_sha256",
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNKNOWN')",
            name="ck_document_set_decision_status",
        ),
        sa.CheckConstraint("decided_by <> ''", name="ck_document_set_decider_nonempty"),
        sa.CheckConstraint(
            "jsonb_typeof(decision) = 'object' AND jsonb_typeof(decision->'members') = 'array'",
            name="ck_document_set_decision_object",
        ),
        sa.CheckConstraint(
            "decision->>'schema_version' IS NOT DISTINCT FROM "
            "'document-set-completeness-decision-v1' AND "
            "decision->>'company_id' IS NOT DISTINCT FROM company_id AND "
            "decision->>'manifest_id' IS NOT DISTINCT FROM manifest_id AND "
            "decision->>'manifest_evidence_sha256' IS NOT DISTINCT FROM "
            "manifest_evidence_sha256 AND "
            "decision->>'status' IS NOT DISTINCT FROM status AND "
            "decision->>'decision_sha256' IS NOT DISTINCT FROM decision_sha256 AND "
            "decision->>'decided_by' IS NOT DISTINCT FROM decided_by AND "
            "(decision->>'decided_at')::timestamptz IS NOT DISTINCT FROM created_at",
            name="ck_document_set_decision_identity",
        ),
    )
    op.create_table(
        "document_set_completeness_member_attestations",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("review_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("decision_sha256", sa.String(64), nullable=False),
        sa.Column("assessment", sa.Text(), nullable=False),
        sa.Column("attestation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id",
            "manifest_id",
            "ordinal",
            name="pk_document_set_member_attestations",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "manifest_id"],
            [
                "document_set_completeness_decisions.company_id",
                "document_set_completeness_decisions.manifest_id",
            ],
            name="fk_document_set_attestation_decision",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "manifest_id", "ordinal"],
            [
                "document_set_evidence_members.company_id",
                "document_set_evidence_members.manifest_id",
                "document_set_evidence_members.ordinal",
            ],
            name="fk_document_set_attestation_member",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "review_id"],
            [
                "document_completeness_review_decisions.company_id",
                "document_completeness_review_decisions.review_id",
            ],
            name="fk_document_set_attestation_review_decision",
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_document_set_attestation_ordinal"),
        sa.CheckConstraint(
            "review_evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_attestation_review_sha256",
        ),
        sa.CheckConstraint(
            "decision_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_attestation_decision_sha256",
        ),
        sa.CheckConstraint(
            "assessment IN ('REVIEWED_IN_SCOPE', 'UNRESOLVED')",
            name="ck_document_set_attestation_assessment",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(attestation) = 'object'",
            name="ck_document_set_attestation_object",
        ),
        sa.CheckConstraint(
            "(attestation->'reference'->>'member_ordinal')::integer "
            "IS NOT DISTINCT FROM ordinal AND "
            "attestation->'reference'->>'review_id' IS NOT DISTINCT FROM review_id AND "
            "attestation->'reference'->>'review_evidence_sha256' IS NOT DISTINCT FROM "
            "review_evidence_sha256 AND "
            "attestation->'reference'->>'decision_sha256' IS NOT DISTINCT FROM "
            "decision_sha256 AND "
            "attestation->>'assessment' IS NOT DISTINCT FROM assessment",
            name="ck_document_set_attestation_identity",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_document_set_review_consistency()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target_company text := COALESCE(NEW.company_id, OLD.company_id);
            target_manifest text := COALESCE(NEW.manifest_id, OLD.manifest_id);
            expected_members jsonb;
            expected_count integer;
            manifest_count integer;
            decision_scope text;
            manifest_scope text;
            actual_members jsonb;
            actual_count integer;
            invalid_binding boolean;
        BEGIN
            SELECT decision.decision->'members',
                   jsonb_array_length(decision.decision->'members'),
                   manifest.member_count,
                   decision.decision->>'scope',
                   manifest.scope
              INTO expected_members, expected_count, manifest_count,
                   decision_scope, manifest_scope
              FROM document_set_completeness_decisions AS decision
              JOIN document_set_evidence_manifests AS manifest
                ON manifest.company_id = decision.company_id
               AND manifest.manifest_id = decision.manifest_id
             WHERE decision.company_id = target_company
               AND decision.manifest_id = target_manifest;
            IF NOT FOUND THEN RETURN NULL; END IF;

            SELECT COALESCE(jsonb_agg(attestation ORDER BY ordinal), '[]'::jsonb),
                   count(*)::integer
              INTO actual_members, actual_count
              FROM document_set_completeness_member_attestations
             WHERE company_id = target_company AND manifest_id = target_manifest;

            SELECT COALESCE(bool_or(
                       att.review_id IS DISTINCT FROM member.completeness_review_id
                       OR att.review_evidence_sha256 IS DISTINCT FROM
                          member.completeness_review_evidence_sha256
                       OR att.review_evidence_sha256 IS DISTINCT FROM
                          single_decision.evidence_sha256
                   ), false)
              INTO invalid_binding
              FROM document_set_completeness_member_attestations AS att
              JOIN document_set_evidence_members AS member
                ON member.company_id = att.company_id
               AND member.manifest_id = att.manifest_id
               AND member.ordinal = att.ordinal
              JOIN document_completeness_review_decisions AS single_decision
                ON single_decision.company_id = att.company_id
               AND single_decision.review_id = att.review_id
             WHERE att.company_id = target_company AND att.manifest_id = target_manifest;

            IF expected_members IS NULL
               OR expected_count IS DISTINCT FROM manifest_count
               OR decision_scope IS DISTINCT FROM manifest_scope
               OR actual_count IS DISTINCT FROM expected_count
               OR actual_members IS DISTINCT FROM expected_members
               OR invalid_binding THEN
                RAISE EXCEPTION 'document set review attestations do not match decision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER document_set_review_decision_consistency
        AFTER INSERT OR UPDATE ON document_set_completeness_decisions
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION enforce_document_set_review_consistency()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER document_set_review_attestation_consistency
        AFTER INSERT OR UPDATE OR DELETE ON document_set_completeness_member_attestations
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION enforce_document_set_review_consistency()
        """
    )
    for table in (
        "document_set_completeness_decisions",
        "document_set_completeness_member_attestations",
    ):
        _append_only(table)
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_set_completeness_decisions TO procurement_app;
                GRANT SELECT, INSERT ON document_set_completeness_member_attestations
                    TO procurement_app;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION enforce_document_set_review_consistency() CASCADE")
    op.drop_table("document_set_completeness_member_attestations")
    op.drop_table("document_set_completeness_decisions")
