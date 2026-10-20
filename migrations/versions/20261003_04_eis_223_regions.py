"""Immutable official region catalogs and bounded multi-region refresh plans."""

from alembic import op

from procurement.storage.models import (
    eis_223_event_sync_attempts,
    eis_223_lot_event_sync_attempts,
    eis_223_region_catalogs,
    eis_223_region_targets,
    eis_223_region_waves,
    eis_223_sync_attempts,
)

revision = "20261003_04"
down_revision = "20261003_03"
branch_labels = None
depends_on = None

PLAN_TABLES = (eis_223_region_catalogs, eis_223_region_waves, eis_223_region_targets)
ATTEMPT_SCOPES = (
    (eis_223_sync_attempts, "ck_eis_223_attempt_scope"),
    (eis_223_event_sync_attempts, "ck_eis_223_event_attempt_scope"),
    (eis_223_lot_event_sync_attempts, "ck_eis_223_lot_event_attempt_scope"),
)
LEGACY_ATTEMPT_SCOPES = {
    "ck_eis_223_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)$'"
    ),
    "ck_eis_223_event_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseRejection$'"
    ),
    "ck_eis_223_lot_event_attempt_scope": (
        "window_key ~ '^getDocsIP/RI223/50/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        "[+]03:00/purchaseLotCancellation$'"
    ),
}


def upgrade():
    tenant = "company_id = nullif(current_setting('app.company_id', true), '')"
    for table in PLAN_TABLES:
        name = table.name
        op.create_table(name, *[c.copy() for c in table.columns], *table.constraints)
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {name}_select ON {name} FOR SELECT USING ({tenant})")
        op.execute(f"CREATE POLICY {name}_insert ON {name} FOR INSERT WITH CHECK ({tenant})")
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()"
        )
        op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC")
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles "
            "WHERE rolname = 'procurement_app') THEN GRANT SELECT, INSERT ON "
            f"{name} TO procurement_app; END IF; END $$"
        )
    for table, name in ATTEMPT_SCOPES:
        op.drop_constraint(name, table.name, type_="check")
        constraint = next(c for c in table.constraints if c.name == name)
        op.create_check_constraint(name, table.name, str(constraint.sqltext))


def downgrade():
    op.execute("SET LOCAL row_security = off")
    plan_history = " OR ".join(f"EXISTS (SELECT 1 FROM {t.name})" for t in PLAN_TABLES)
    source_tables = (
        "eis_223_sync_attempts",
        "eis_223_event_sync_attempts",
        "eis_223_lot_event_sync_attempts",
        "eis_223_windows",
        "eis_223_event_windows",
        "eis_223_lot_event_windows",
    )
    non_legacy = " OR ".join(
        f"EXISTS (SELECT 1 FROM {name} WHERE split_part(window_key, '/', 3) <> '50')"
        for name in source_tables
    )
    op.execute(
        f"DO $$ BEGIN IF {plan_history} OR {non_legacy} THEN RAISE EXCEPTION "
        "'223 region plan or non-50 source history must be preserved'; END IF; END $$"
    )
    for table, name in ATTEMPT_SCOPES:
        op.drop_constraint(name, table.name, type_="check")
        op.create_check_constraint(name, table.name, LEGACY_ATTEMPT_SCOPES[name])
    for table in reversed(PLAN_TABLES):
        op.drop_table(table.name)
