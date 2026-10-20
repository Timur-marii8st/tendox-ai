"""Допустить XSD/live подтверждённый электронный открытый конкурс 44-ФЗ.

Revision ID: 20261002_03
Revises: 20261002_02
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261002_03"
down_revision: str | None = "20261002_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_eis_notice_type", "eis_notice_versions", type_="check")
    op.create_check_constraint(
        "ck_eis_notice_type",
        "eis_notice_versions",
        "document_type IN ('epNotificationEF2020', 'epNotificationEZK2020', "
        "'epNotificationEOK2020')",
    )


def downgrade() -> None:
    # Existing EOK rows intentionally prevent destructive downgrade.
    op.drop_constraint("ck_eis_notice_type", "eis_notice_versions", type_="check")
    op.create_check_constraint(
        "ck_eis_notice_type",
        "eis_notice_versions",
        "document_type IN ('epNotificationEF2020', 'epNotificationEZK2020')",
    )
