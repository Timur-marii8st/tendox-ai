"""Allow encrypted raw capture for each ordered AI transfer chunk.

Revision ID: 20260917_10
Revises: 20260917_09
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_10"
down_revision: str | None = "20260917_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ai_transfer_raw_first_ordinal",
        "ai_transfer_raw_responses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_transfer_raw_ordinal",
        "ai_transfer_raw_responses",
        "ordinal BETWEEN 1 AND 9999",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_transfer_raw_ordinal",
        "ai_transfer_raw_responses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_ai_transfer_raw_first_ordinal",
        "ai_transfer_raw_responses",
        "ordinal = 1",
    )
