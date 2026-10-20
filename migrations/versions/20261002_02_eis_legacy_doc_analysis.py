"""Retain v1/v2 and allow the bounded legacy-DOC text analyzer.

Revision ID: 20261002_02
Revises: 20261002_01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261002_02"
down_revision: str | None = "20261002_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_eis_document_analyzer", "eis_document_analyses", type_="check")
    op.create_check_constraint(
        "ck_eis_document_analyzer",
        "eis_document_analyses",
        "analyzer_version IN ('eis-native-v1', 'eis-native-v2-xls', 'eis-native-v3-doc')",
    )


def downgrade() -> None:
    # Validation fails with existing v3 rows; evidence is never removed.
    op.drop_constraint("ck_eis_document_analyzer", "eis_document_analyses", type_="check")
    op.create_check_constraint(
        "ck_eis_document_analyzer",
        "eis_document_analyses",
        "analyzer_version IN ('eis-native-v1', 'eis-native-v2-xls')",
    )
