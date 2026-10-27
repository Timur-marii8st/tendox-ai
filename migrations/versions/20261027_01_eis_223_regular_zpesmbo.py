"""Explicit ZPESMBO identity, regular windows and append-only seven-family scope."""

from alembic import op
from sqlalchemy import text

revision = "20261027_01"
down_revision = "20261026_03"
branch_labels = None
depends_on = None

CHECKS = (
    ("eis_223_windows", "ck_eis_223_window"),
    ("eis_223_notice_versions", "ck_eis_223_snapshot_identity"),
    ("eis_223_sync_attempts", "ck_eis_223_attempt_scope"),
    ("eis_223_region_targets", "ck_eis_223_region_target_scope"),
    ("eis_223_region_waves", "ck_eis_223_region_wave_bounds"),
)
BEFORE = {
    "ck_eis_223_window": (
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/("
        "purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$' OR window_key ~"
        " '^getDocsIP/RI223/by-number/[0-9]{11}/purchaseNoticeKESMBO$' OR window_key "
        "~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/p"
        "urchaseNoticeKESMBO$'"
    ),
    "ck_eis_223_snapshot_identity": (
        "COALESCE((jsonb_typeof(snapshot) = 'object' AND snapshot->>'law' = '223' AND"
        " snapshot->>'document_type' IN ('purchaseNoticeAESMBO','purchaseNoticeZKESMB"
        "O','purchaseNotice','purchaseNoticeKESMBO') AND snapshot->>'document_type' ="
        " split_part(window_key, '/', 5) AND snapshot->>'purchase_number' = purchase_"
        "number AND (split_part(window_key, '/', 3) <> 'by-number' OR purchase_number"
        " = split_part(window_key, '/', 4)) AND (snapshot->>'version_number')::intege"
        "r = version_number AND snapshot->>'xml_sha256' = xml_sha256), false)"
    ),
    "ck_eis_223_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2"
        "}[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|purchas"
        "eNoticeKESMBO)$'"
    ),
    "ck_eis_223_region_target_scope": (
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2"
        "}[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|purchas"
        "eNoticeKESMBO|purchaseRejection|purchaseLotCancellation)$'"
    ),
    "ck_eis_223_region_wave_bounds": ("start_day <= end_day AND target_count BETWEEN 1 AND 1188"),
}
AFTER = {
    "ck_eis_223_window": (
        "window_key ~ '^getDocsIP/RI223/[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}[+]03:00/("
        "purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$' OR window_key ~"
        " '^getDocsIP/RI223/by-number/[0-9]{11}/(purchaseNoticeKESMBO|purchaseNoticeZ"
        "PESMBO)$' OR window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-"
        "9]{2}-[0-9]{2}[+]03:00/(purchaseNoticeKESMBO|purchaseNoticeZPESMBO)$'"
    ),
    "ck_eis_223_snapshot_identity": (
        "COALESCE((jsonb_typeof(snapshot) = 'object' AND snapshot->>'law' = '223' AND"
        " snapshot->>'document_type' IN ('purchaseNoticeAESMBO','purchaseNoticeZKESMB"
        "O','purchaseNotice','purchaseNoticeKESMBO','purchaseNoticeZPESMBO') AND snap"
        "shot->>'document_type' = split_part(window_key, '/', 5) AND snapshot->>'purc"
        "hase_number' = purchase_number AND (split_part(window_key, '/', 3) <> 'by-nu"
        "mber' OR purchase_number = split_part(window_key, '/', 4)) AND (snapshot->>'"
        "version_number')::integer = version_number AND snapshot->>'xml_sha256' = xml"
        "_sha256), false)"
    ),
    "ck_eis_223_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2"
        "}[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|purchas"
        "eNoticeKESMBO|purchaseNoticeZPESMBO)$'"
    ),
    "ck_eis_223_region_target_scope": (
        "window_key ~ '^getDocsIP/RI223/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2"
        "}[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|purchas"
        "eNoticeKESMBO|purchaseNoticeZPESMBO|purchaseRejection|purchaseLotCancellatio"
        "n)$'"
    ),
    "ck_eis_223_region_wave_bounds": ("start_day <= end_day AND target_count BETWEEN 1 AND 1386"),
}


def _replace_validated_check(table, name):
    """Prove existing rows through the exact stronger validated predecessor.

    NOT VALID skips only the historical scan; PostgreSQL still enforces every
    new INSERT/UPDATE. Never mark the catalog validated without a real scan.
    """
    conn = op.get_bind()
    op.execute(f"LOCK TABLE public.{table} IN ACCESS EXCLUSIVE MODE")
    scope = (
        conn.execute(
            text(
                "SELECT c.relkind,c.relispartition, "
                "EXISTS (SELECT 1 FROM pg_inherits WHERE inhrelid=c.oid OR inhparent=c.oid) "
                "AS inherited FROM pg_class c WHERE c.oid=to_regclass(:table) "
                "AND c.relnamespace=to_regnamespace('public')"
            ),
            {"table": table},
        )
        .mappings()
        .one_or_none()
    )
    checks = (
        conn.execute(
            text(
                "SELECT conname,contype,convalidated,connoinherit,conislocal,coninhcount, "
                "pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint "
                "WHERE conrelid=to_regclass(:table) AND conname IN (:name,:before,:after)"
            ),
            {
                "table": table,
                "name": name,
                "before": name + "_v54_before",
                "after": name + "_v54_after",
            },
        )
        .mappings()
        .all()
    )
    if (
        scope is None
        or scope["relkind"] != "r"
        or scope["relispartition"]
        or scope["inherited"]
        or len(checks) != 1
        or checks[0]["conname"] != name
        or checks[0]["contype"] != "c"
        or not checks[0]["convalidated"]
        or checks[0]["connoinherit"]
        or not checks[0]["conislocal"]
        or checks[0]["coninhcount"] != 0
    ):
        raise RuntimeError("ZP_CHECK_PREIMAGE_UNVERIFIED:" + name)
    # Let PostgreSQL normalize both exact reviewed expressions on the same table;
    # text/substring matching would silently admit a weaker preimage.
    for suffix, expression in (("_v54_before", BEFORE[name]), ("_v54_after", AFTER[name])):
        op.create_check_constraint(
            name + suffix, table, expression, schema="public", postgresql_not_valid=True
        )
    expected = dict(
        conn.execute(
            text(
                "SELECT conname,pg_get_expr(conbin,conrelid) FROM pg_constraint "
                "WHERE conrelid=to_regclass(:table) AND conname IN (:before,:after)"
            ),
            {"table": table, "before": name + "_v54_before", "after": name + "_v54_after"},
        ).all()
    )
    actual = checks[0]["expression"]
    if actual == expected[name + "_v54_after"]:
        # Historical bootstrap uses current metadata. Exact validated AFTER
        # already proves/enforces the complete target and stays validated.
        op.drop_constraint(name + "_v54_after", table, schema="public", type_="check")
    elif actual == expected[name + "_v54_before"]:
        # The validated predecessor remains present until its broader replacement
        # exists; the exclusive table lock excludes concurrent writers/DDL.
        op.drop_constraint(name, table, schema="public", type_="check")
        op.execute(f"ALTER TABLE public.{table} RENAME CONSTRAINT {name}_v54_after TO {name}")
    else:
        raise RuntimeError("ZP_CHECK_PREIMAGE_UNVERIFIED:" + name)
    op.drop_constraint(name + "_v54_before", table, schema="public", type_="check")


def upgrade():
    op.execute("SET LOCAL statement_timeout = '5s'")
    op.execute("SET LOCAL lock_timeout = '2s'")
    for table, name in CHECKS:
        _replace_validated_check(table, name)


def downgrade():
    # Refuse evidence across all tenants before changing any CHECK. Lack of RLS
    # visibility raises instead of silently passing through an empty tenant view.
    op.execute("SET LOCAL row_security = off")
    conditions = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE window_key LIKE '%/purchaseNoticeZPESMBO')"
        for table in ("eis_223_windows", "eis_223_sync_attempts", "eis_223_region_targets")
    )
    conditions += (
        " OR EXISTS (SELECT 1 FROM eis_223_notice_versions "
        "WHERE snapshot->>'document_type' = 'purchaseNoticeZPESMBO')"
        " OR EXISTS (SELECT 1 FROM eis_223_region_waves WHERE target_count > 1188)"
    )
    op.execute(
        "DO $$ BEGIN IF "
        + conditions
        + " THEN RAISE EXCEPTION '223 ZPESMBO history and planned scope must be preserved'; "
        "END IF; END $$"
    )
    for table, name in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, BEFORE[name])
