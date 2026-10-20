"""Allow explicit legacy-XLS analyzer version alongside retained v1 evidence.

Revision ID: 20261002_01
Revises: 20260928_04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261002_01"
down_revision: str | None = "20260928_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_eis_document_analyzer", "eis_document_analyses", type_="check")
    op.create_check_constraint(
        "ck_eis_document_analyzer",
        "eis_document_analyses",
        "analyzer_version IN ('eis-native-v1', 'eis-native-v2-xls')",
    )


def downgrade() -> None:
    # Validation fails transactionally if v2 evidence exists: never erase it.
    op.drop_constraint("ck_eis_document_analyzer", "eis_document_analyses", type_="check")
    op.create_check_constraint(
        "ck_eis_document_analyzer", "eis_document_analyses", "analyzer_version = 'eis-native-v1'"
    )
