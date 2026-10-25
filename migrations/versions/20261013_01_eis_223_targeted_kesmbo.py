"""Admit explicit captured KESMBO by-number provenance; source schedule remains unchanged."""

from alembic import op

revision = "20261013_01"
down_revision = "20261008_01"
branch_labels = None
depends_on = None

CHECKS = (
    ("eis_223_windows", "ck_eis_223_window"),
    ("eis_223_notice_versions", "ck_eis_223_snapshot_identity"),
)

BEFORE = {
    "ck_eis_223_window": (
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:"
        "00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$'"
    ),
    "ck_eis_223_snapshot_identity": (
        "COALESCE((jsonb_typeof(snapshot) = 'object' AND snapshot->>'law' = '223'"
        " AND snapshot->>'document_type' IN ('purchaseNoticeAESMBO','purchaseNoti"
        "ceZKESMBO','purchaseNotice') AND snapshot->>'document_type' = split_part"
        "(window_key, '/', 5) AND snapshot->>'purchase_number' = purchase_number "
        "AND (snapshot->>'version_number')::integer = version_number AND snapshot"
        "->>'xml_sha256' = xml_sha256), false)"
    ),
}
AFTER = {
    "ck_eis_223_window": (
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:"
        "00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$' OR wind"
        "ow_key ~ '^getDocsIP/RI223/by-number/[0-9]{11}/purchaseNoticeKESMBO$'"
    ),
    "ck_eis_223_snapshot_identity": (
        "COALESCE((jsonb_typeof(snapshot) = 'object' AND snapshot->>'law' = '223'"
        " AND snapshot->>'document_type' IN ('purchaseNoticeAESMBO','purchaseNoti"
        "ceZKESMBO','purchaseNotice','purchaseNoticeKESMBO') AND snapshot->>'docu"
        "ment_type' = split_part(window_key, '/', 5) AND snapshot->>'purchase_num"
        "ber' = purchase_number AND (split_part(window_key, '/', 3) <> 'by-number"
        "' OR purchase_number = split_part(window_key, '/', 4)) AND (snapshot->>'"
        "version_number')::integer = version_number AND snapshot->>'xml_sha256' ="
        " xml_sha256), false)"
    ),
}


def upgrade():
    for table, name in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, AFTER[name])


def downgrade():
    # Fail rather than delete or hide new source history behind a tenant filter.
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_windows "
        "WHERE split_part(window_key, '/', 3) = 'by-number') "
        "OR EXISTS (SELECT 1 FROM eis_223_notice_versions "
        "WHERE snapshot->>'document_type' = 'purchaseNoticeKESMBO') "
        "THEN RAISE EXCEPTION '223 targeted KESMBO history must be preserved'; END IF; END $$"
    )
    for table, name in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, BEFORE[name])
