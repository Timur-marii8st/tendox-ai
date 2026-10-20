"""Persist exact per-source artifacts for multi-source sourcing runs.

Revision ID: 20260920_03
Revises: 20260920_02
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_03"
down_revision: str | None = "20260920_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sourcing_run_sources"
TENANT = "company_id = nullif(current_setting('app.company_id', true), '')"
MAX_SOURCE_BYTES = 20 * 1024 * 1024


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("company_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("source_content", sa.LargeBinary(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("company_id", "run_id", "ordinal", name=f"pk_{TABLE}"),
        sa.ForeignKeyConstraint(
            ["company_id", "run_id"],
            ["sourcing_runs.company_id", "sourcing_runs.run_id"],
            name=f"fk_{TABLE}_run",
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10", name=f"ck_{TABLE}_ordinal"),
        sa.CheckConstraint("btrim(source_name) <> ''", name=f"ck_{TABLE}_name"),
        sa.CheckConstraint("source_url ~ '^https://[^[:space:]]+$'", name=f"ck_{TABLE}_url"),
        sa.CheckConstraint(
            "source_kind IN ('MANUFACTURER_CATALOG', 'SUPPLIER_CATALOG')",
            name=f"ck_{TABLE}_kind",
        ),
        sa.CheckConstraint(
            "media_type IN ('text/html', 'application/pdf')",
            name=f"ck_{TABLE}_media_type",
        ),
        sa.CheckConstraint("status IN ('COMPLETED', 'SOURCE_ERROR')", name=f"ck_{TABLE}_status"),
        sa.CheckConstraint(
            "((status = 'COMPLETED' AND source_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_sha256 = encode(sha256(source_content), 'hex') "
            f"AND octet_length(source_content) BETWEEN 1 AND {MAX_SOURCE_BYTES} "
            "AND error_code IS NULL) OR (status = 'SOURCE_ERROR' AND source_sha256 IS NULL "
            "AND source_content IS NULL AND error_code ~ '^[A-Z][A-Z0-9_]{1,63}$'))",
            name=f"ck_{TABLE}_shape",
        ),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT})")
    op.execute(
        f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_sourcing_run_source_manifest() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF jsonb_typeof(NEW.result->'sources') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'sourcing run sources must be an array';
            END IF;
            IF jsonb_array_length(NEW.result->'sources') IS DISTINCT FROM (
                SELECT count(*)::integer FROM sourcing_run_sources AS source
                WHERE source.company_id = NEW.company_id AND source.run_id = NEW.run_id
            ) THEN
                RAISE EXCEPTION 'sourcing run source manifest count mismatch';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM jsonb_array_elements(NEW.result->'sources')
                    WITH ORDINALITY AS expected(item, ordinal)
                LEFT JOIN sourcing_run_sources AS source
                    ON source.company_id = NEW.company_id
                    AND source.run_id = NEW.run_id
                    AND source.ordinal = expected.ordinal
                WHERE source.ordinal IS NULL
                    OR expected.item->>'source_name' IS DISTINCT FROM source.source_name
                    OR expected.item->>'source_kind' IS DISTINCT FROM source.source_kind
                    OR expected.item->>'source_url' IS DISTINCT FROM source.source_url
                    OR expected.item->>'media_type' IS DISTINCT FROM source.media_type
                    OR expected.item->>'status' IS DISTINCT FROM source.status
                    OR expected.item->>'source_sha256' IS DISTINCT FROM source.source_sha256
                    OR (expected.item->>'source_byte_size')::integer
                        IS DISTINCT FROM octet_length(source.source_content)
                    OR (expected.item->>'observed_at')::timestamptz
                        IS DISTINCT FROM source.observed_at
                    OR expected.item->>'error_code' IS DISTINCT FROM source.error_code
            ) THEN
                RAISE EXCEPTION 'sourcing run source manifest identity mismatch';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER sourcing_run_source_manifest_exact "
        "AFTER INSERT ON sourcing_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION validate_sourcing_run_source_manifest()"
    )
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
        f"THEN GRANT SELECT, INSERT ON {TABLE} TO procurement_app; END IF; END $$"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER sourcing_run_source_manifest_exact ON sourcing_runs")
    op.execute("DROP FUNCTION validate_sourcing_run_source_manifest()")
    op.drop_table(TABLE)
