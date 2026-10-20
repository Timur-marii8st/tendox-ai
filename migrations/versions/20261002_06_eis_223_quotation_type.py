"""Admit the verified 223 electronic SME quotation metadata family."""

from alembic import op

from procurement.storage.models import eis_223_notice_versions, eis_223_windows

revision = "20261002_06"
down_revision = "20261002_05"
branch_labels = None
depends_on = None


def upgrade():
    for table, name in (
        (eis_223_windows, "ck_eis_223_window"),
        (eis_223_notice_versions, "ck_eis_223_snapshot_identity"),
    ):
        op.drop_constraint(name, table.name, type_="check")
        constraint = next(c for c in table.constraints if c.name == name)
        op.create_check_constraint(name, table.name, str(constraint.sqltext))


def downgrade():
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_windows "
        "WHERE split_part(window_key, '/', 5) = 'purchaseNoticeZKESMBO') "
        "THEN RAISE EXCEPTION '223 quotation history must be preserved'; END IF; END $$"
    )
    op.drop_constraint("ck_eis_223_window", "eis_223_windows", type_="check")
    op.create_check_constraint(
        "ck_eis_223_window",
        "eis_223_windows",
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseNoticeAESMBO$'",
    )
    op.drop_constraint("ck_eis_223_snapshot_identity", "eis_223_notice_versions", type_="check")
    op.create_check_constraint(
        "ck_eis_223_snapshot_identity",
        "eis_223_notice_versions",
        "COALESCE((jsonb_typeof(snapshot) = 'object' AND snapshot->>'law' = '223' "
        "AND snapshot->>'document_type' = 'purchaseNoticeAESMBO' "
        "AND snapshot->>'purchase_number' = purchase_number "
        "AND (snapshot->>'version_number')::integer = version_number "
        "AND snapshot->>'xml_sha256' = xml_sha256), false)",
    )
