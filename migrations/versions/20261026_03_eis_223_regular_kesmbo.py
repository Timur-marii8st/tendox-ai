"""Admit authenticated regular KESMBO paths without changing captured source history."""

from alembic import op

revision = "20261026_03"
down_revision = "20261026_02"
branch_labels = None
depends_on = None

REGIONAL_KES = (
    "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
    "[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/purchaseNoticeKESMBO$'"
)
CHECKS = (
    ("eis_223_windows", "ck_eis_223_window"),
    ("eis_223_sync_attempts", "ck_eis_223_attempt_scope"),
    ("eis_223_region_targets", "ck_eis_223_region_target_scope"),
    ("eis_223_region_waves", "ck_eis_223_region_wave_bounds"),
)
BEFORE = {
    "ck_eis_223_region_wave_bounds": "start_day <= end_day AND target_count BETWEEN 1 AND 990",
    "ck_eis_223_window": (
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$' "
        "OR window_key ~ '^getDocsIP/RI223/by-number/[0-9]{11}/purchaseNoticeKESMBO$'"
    ),
    "ck_eis_223_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
        "[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$'"
    ),
    "ck_eis_223_region_target_scope": (
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/"
        "[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/"
        "(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|"
        "purchaseRejection|purchaseLotCancellation)$'"
    ),
}
AFTER = {
    "ck_eis_223_region_wave_bounds": "start_day <= end_day AND target_count BETWEEN 1 AND 1188",
    "ck_eis_223_window": BEFORE["ck_eis_223_window"] + " OR " + REGIONAL_KES,
    "ck_eis_223_attempt_scope": BEFORE["ck_eis_223_attempt_scope"].replace(
        "|purchaseNotice)$", "|purchaseNotice|purchaseNoticeKESMBO)$"
    ),
    "ck_eis_223_region_target_scope": BEFORE["ck_eis_223_region_target_scope"].replace(
        "|purchaseRejection|", "|purchaseNoticeKESMBO|purchaseRejection|"
    ),
}


def upgrade():
    for table, name in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, AFTER[name])


def downgrade():
    # Planned KES targets already require compatible consumers, even without ZIPs.
    op.execute("SET LOCAL row_security = off")
    conditions = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE {REGIONAL_KES})" for table, _ in CHECKS[:3]
    )
    conditions += " OR EXISTS (SELECT 1 FROM eis_223_region_waves WHERE target_count > 990)"
    op.execute(
        "DO $$ BEGIN IF "
        + conditions
        + " THEN RAISE EXCEPTION '223 regular KESMBO history must be preserved'; "
        "END IF; END $$"
    )
    for table, name in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, BEFORE[name])
