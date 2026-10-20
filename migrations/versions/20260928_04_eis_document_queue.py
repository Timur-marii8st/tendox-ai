"""Immutable document jobs, received bytes and cached analysis.

Revision ID: 20260928_04
Revises: 20260928_03
"""

from collections.abc import Sequence

from alembic import op

from procurement.storage.models import (
    eis_document_analyses,
    eis_document_blobs,
    eis_document_jobs,
    eis_document_observations,
)

revision: str = "20260928_04"
down_revision: str | None = "20260928_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
TABLES = (eis_document_jobs, eis_document_blobs, eis_document_analyses, eis_document_observations)


def upgrade() -> None:
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for table in TABLES:
        name = table.name
        op.create_table(name, *[column.copy() for column in table.columns], *table.constraints)
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({tenant})")
        op.execute(f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({tenant})")
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
        )
        op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') "
            f"THEN GRANT SELECT, INSERT ON {name} TO procurement_app; END IF; END $$"
        )
    op.create_index(
        "ix_eis_document_observations_notice",
        "eis_document_observations",
        ["company_id", "purchase_number", "version_number", "observed_at"],
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table.name)
