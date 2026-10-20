"""Admit explicit general 223 metadata without rewriting source history."""

from alembic import op

from procurement.storage.models import (
    eis_223_notice_versions,
    eis_223_sync_attempts,
    eis_223_windows,
)

revision = "20261003_01"
down_revision = "20261002_11"
branch_labels = None
depends_on = None

CHECKS = (
    (eis_223_windows, "ck_eis_223_window"),
    (eis_223_notice_versions, "ck_eis_223_snapshot_identity"),
    (eis_223_sync_attempts, "ck_eis_223_attempt_scope"),
)

GENERAL_CHECKS = {
    "ck_eis_223_window": (
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$'"
    ),
    "ck_eis_223_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$'"
    ),
}


def upgrade():
    for table, name in CHECKS:
        op.drop_constraint(name, table.name, type_="check")
        constraint = next(c for c in table.constraints if c.name == name)
        sql = GENERAL_CHECKS.get(name, str(constraint.sqltext))
        op.create_check_constraint(name, table.name, sql)


def downgrade():
    # Fail rather than silently excluding history hidden by tenant RLS.
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_windows "
        "WHERE split_part(window_key, '/', 5) = 'purchaseNotice') "
        "OR EXISTS (SELECT 1 FROM eis_223_notice_versions "
        "WHERE snapshot->>'document_type' = 'purchaseNotice') "
        "OR EXISTS (SELECT 1 FROM eis_223_sync_attempts "
        "WHERE split_part(window_key, '/', 5) = 'purchaseNotice') "
        "THEN RAISE EXCEPTION '223 general history must be preserved'; END IF; END $$"
    )
    for table, name in CHECKS:
        constraint = next(c for c in table.constraints if c.name == name)
        current = GENERAL_CHECKS.get(name, str(constraint.sqltext))
        previous = current.replace("|purchaseNotice)", ")").replace(
            ",'purchaseNotice')", ")"
        )
        op.drop_constraint(name, table.name, type_="check")
        op.create_check_constraint(name, table.name, previous)
