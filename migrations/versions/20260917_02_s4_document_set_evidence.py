"""Persist exact evidence manifests for explicitly selected document sets.

Revision ID: 20260917_02
Revises: 20260917_01
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_02"
down_revision: str | None = "20260917_01"
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
    op.create_table(
        "document_set_evidence_manifests",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("completeness_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id", "manifest_id", name="pk_document_set_evidence_manifests"
        ),
        sa.UniqueConstraint(
            "company_id",
            "manifest_id",
            "evidence_sha256",
            name="uq_document_set_evidence_binding",
        ),
        sa.CheckConstraint("company_id <> ''", name="ck_document_set_company_nonempty"),
        sa.CheckConstraint("manifest_id <> ''", name="ck_document_set_id_nonempty"),
        sa.CheckConstraint("scope <> ''", name="ck_document_set_scope_nonempty"),
        sa.CheckConstraint("member_count BETWEEN 2 AND 10", name="ck_document_set_member_count"),
        sa.CheckConstraint(
            "completeness_status = 'UNKNOWN'", name="ck_document_set_status_unknown"
        ),
        sa.CheckConstraint(
            "reason = 'MULTI_DOCUMENT_REVIEW_REQUIRED'",
            name="ck_document_set_reason_review_required",
        ),
        sa.CheckConstraint(
            "evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_evidence_sha256",
        ),
        sa.CheckConstraint("created_by <> ''", name="ck_document_set_creator_nonempty"),
        sa.CheckConstraint(
            "jsonb_typeof(manifest) = 'object'", name="ck_document_set_manifest_object"
        ),
        sa.CheckConstraint(
            "manifest->>'schema_version' IS NOT DISTINCT FROM "
            "'document-set-evidence-manifest-v1' AND "
            "manifest->>'company_id' IS NOT DISTINCT FROM company_id AND "
            "manifest->>'manifest_id' IS NOT DISTINCT FROM manifest_id AND "
            "manifest->>'scope' IS NOT DISTINCT FROM scope AND "
            "manifest->>'completeness_status' IS NOT DISTINCT FROM completeness_status AND "
            "manifest->>'reason' IS NOT DISTINCT FROM reason AND "
            "manifest->>'evidence_sha256' IS NOT DISTINCT FROM evidence_sha256 AND "
            "manifest->>'created_by' IS NOT DISTINCT FROM created_by AND "
            "(manifest->>'created_at')::timestamptz IS NOT DISTINCT FROM created_at AND "
            "jsonb_typeof(manifest->'members') = 'array' AND "
            "jsonb_array_length(manifest->'members') = member_count",
            name="ck_document_set_manifest_identity",
        ),
    )
    op.create_index(
        "ix_document_set_evidence_company_created",
        "document_set_evidence_manifests",
        ["company_id", "created_at", "manifest_id"],
    )
    op.create_table(
        "document_set_evidence_members",
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_document_sha256", sa.String(64), nullable=False),
        sa.Column("completeness_review_id", sa.Text(), nullable=False),
        sa.Column("completeness_review_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("mapper_version", sa.Text(), nullable=False),
        sa.Column("mapper_min_confidence", sa.Float(), nullable=False),
        sa.Column("member", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint(
            "company_id",
            "manifest_id",
            "ordinal",
            name="pk_document_set_evidence_members",
        ),
        sa.UniqueConstraint(
            "company_id",
            "manifest_id",
            "source_document_id",
            name="uq_document_set_source_document",
        ),
        sa.UniqueConstraint(
            "company_id",
            "manifest_id",
            "completeness_review_id",
            name="uq_document_set_review",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "manifest_id"],
            [
                "document_set_evidence_manifests.company_id",
                "document_set_evidence_manifests.manifest_id",
            ],
            name="fk_document_set_member_manifest",
        ),
        sa.ForeignKeyConstraint(
            [
                "company_id",
                "completeness_review_id",
                "completeness_review_evidence_sha256",
            ],
            [
                "document_completeness_reviews.company_id",
                "document_completeness_reviews.review_id",
                "document_completeness_reviews.evidence_sha256",
            ],
            name="fk_document_set_member_review",
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_document_set_member_ordinal"),
        sa.CheckConstraint(
            "source_document_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_member_source_sha256",
        ),
        sa.CheckConstraint(
            "completeness_review_evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_set_member_review_sha256",
        ),
        sa.CheckConstraint(
            "mapper_min_confidence BETWEEN 0 AND 1",
            name="ck_document_set_member_confidence",
        ),
        sa.CheckConstraint("jsonb_typeof(member) = 'object'", name="ck_document_set_member_object"),
        sa.CheckConstraint(
            "(member->>'ordinal')::integer IS NOT DISTINCT FROM ordinal AND "
            "member->>'source_document_id' IS NOT DISTINCT FROM source_document_id AND "
            "member->>'source_document_sha256' IS NOT DISTINCT FROM "
            "source_document_sha256 AND "
            "member->>'completeness_review_id' IS NOT DISTINCT FROM completeness_review_id AND "
            "member->>'completeness_review_evidence_sha256' IS NOT DISTINCT FROM "
            "completeness_review_evidence_sha256 AND "
            "member->>'mapper_version' IS NOT DISTINCT FROM mapper_version AND "
            "(member->>'mapper_min_confidence')::double precision IS NOT DISTINCT FROM "
            "mapper_min_confidence",
            name="ck_document_set_member_identity",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_document_set_evidence_consistency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_company_id text := COALESCE(NEW.company_id, OLD.company_id);
            target_manifest_id text := COALESCE(NEW.manifest_id, OLD.manifest_id);
            expected_count integer;
            expected_members jsonb;
            actual_count integer;
            actual_members jsonb;
            invalid_review_binding boolean;
        BEGIN
            SELECT member_count, manifest->'members'
              INTO expected_count, expected_members
              FROM document_set_evidence_manifests
             WHERE company_id = target_company_id
               AND manifest_id = target_manifest_id;

            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT count(*)::integer, COALESCE(jsonb_agg(member ORDER BY ordinal), '[]'::jsonb)
              INTO actual_count, actual_members
              FROM document_set_evidence_members
             WHERE company_id = target_company_id
               AND manifest_id = target_manifest_id;

            SELECT COALESCE(bool_or(
                       member.source_document_id IS DISTINCT FROM review.source_document_id
                       OR member.source_document_sha256 IS DISTINCT FROM
                          review.source_document_sha256
                       OR member.mapper_version IS DISTINCT FROM
                          review.snapshot->>'mapper_version'
                       OR member.mapper_min_confidence IS DISTINCT FROM
                          (review.snapshot->>'mapper_min_confidence')::double precision
                   ), false)
              INTO invalid_review_binding
              FROM document_set_evidence_members AS member
              JOIN document_completeness_reviews AS review
                ON review.company_id = member.company_id
               AND review.review_id = member.completeness_review_id
               AND review.evidence_sha256 = member.completeness_review_evidence_sha256
             WHERE member.company_id = target_company_id
               AND member.manifest_id = target_manifest_id;

            IF actual_count IS DISTINCT FROM expected_count
               OR actual_members IS DISTINCT FROM expected_members
               OR invalid_review_binding THEN
                RAISE EXCEPTION 'document set evidence members do not match manifest'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER document_set_evidence_manifest_consistency
        AFTER INSERT OR UPDATE ON document_set_evidence_manifests
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_document_set_evidence_consistency()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER document_set_evidence_member_consistency
        AFTER INSERT OR UPDATE OR DELETE ON document_set_evidence_members
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_document_set_evidence_consistency()
        """
    )
    for table in ("document_set_evidence_manifests", "document_set_evidence_members"):
        _append_only(table)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
                GRANT SELECT, INSERT ON document_set_evidence_manifests TO procurement_app;
                GRANT SELECT, INSERT ON document_set_evidence_members TO procurement_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION enforce_document_set_evidence_consistency() CASCADE")
    op.drop_table("document_set_evidence_members")
    op.drop_index(
        "ix_document_set_evidence_company_created",
        table_name="document_set_evidence_manifests",
    )
    op.drop_table("document_set_evidence_manifests")
