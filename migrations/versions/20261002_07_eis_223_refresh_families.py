"""Admit quotation refresh attempts while preserving the existing journal."""

from alembic import op

from procurement.storage.models import eis_223_sync_attempts

revision = "20261002_07"
down_revision = "20261002_06"
branch_labels = None
depends_on = None


def upgrade():
    name = "ck_eis_223_attempt_scope"
    op.drop_constraint(name, eis_223_sync_attempts.name, type_="check")
    op.create_check_constraint(
        name,
        eis_223_sync_attempts.name,
        "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO)$'",
    )


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_sync_attempts "
        "WHERE split_part(window_key, '/', 5) = 'purchaseNoticeZKESMBO') "
        "THEN RAISE EXCEPTION '223 quotation attempts must be preserved'; END IF; END $$"
    )
    op.drop_constraint("ck_eis_223_attempt_scope", "eis_223_sync_attempts", type_="check")
    op.create_check_constraint(
        "ck_eis_223_attempt_scope",
        "eis_223_sync_attempts",
        "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseNoticeAESMBO$'",
    )
