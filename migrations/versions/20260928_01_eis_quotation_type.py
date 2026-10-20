"""Допустить проверенный тип электронного запроса котировок 44-ФЗ.

Revision ID: 20260928_01
Revises: 20260927_03
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260928_01"
down_revision: str | None = "20260927_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_eis_notice_type", "eis_notice_versions", type_="check")
    op.create_check_constraint(
        "ck_eis_notice_type",
        "eis_notice_versions",
        "document_type IN ('epNotificationEF2020', 'epNotificationEZK2020')",
    )


def downgrade() -> None:
    # При наличии EZK-записей constraint не позволит откат и сохранит данные.
    op.drop_constraint("ck_eis_notice_type", "eis_notice_versions", type_="check")
    op.create_check_constraint(
        "ck_eis_notice_type", "eis_notice_versions", "document_type = 'epNotificationEF2020'"
    )
