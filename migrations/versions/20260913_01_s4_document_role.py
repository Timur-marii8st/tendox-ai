"""Persist the trusted role of each source document.

Revision ID: 20260913_01
Revises: 20260909_02
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260913_01"
down_revision = "20260909_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing immutable rows cannot be reclassified safely. UNKNOWN preserves
    # that uncertainty, while new API writes must supply an explicit role.
    op.add_column(
        "documents",
        sa.Column(
            "document_role",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
    )
    op.alter_column("documents", "document_role", server_default=None)
    op.create_check_constraint(
        "ck_documents_role_allowed",
        "documents",
        "document_role IN ('UNKNOWN', 'TENDER_REQUIREMENTS', 'SUPPLIER_QUOTE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_role_allowed", "documents", type_="check")
    op.drop_column("documents", "document_role")
