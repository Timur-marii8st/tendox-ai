"""Admit bounded complete rejection archive sets without losing source history."""

from alembic import op

revision = "20261031_01"
down_revision = "20261027_03"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL statement_timeout='5s'")
    op.execute("SET LOCAL lock_timeout='2s'")
    op.drop_constraint("ck_eis_223_event_counts", "eis_223_event_windows", type_="check")
    op.create_check_constraint(
        "ck_eis_223_event_counts", "eis_223_event_windows",
        "archive_count BETWEEN 1 AND 8 AND record_count >= 1",
    )


def downgrade():
    op.execute("SET LOCAL statement_timeout='5s'")
    op.execute("SET LOCAL lock_timeout='2s'")
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_event_windows WHERE archive_count > 2) "
        "THEN RAISE EXCEPTION '223 event archive history must be preserved'; "
        "END IF; END $$"
    )
    op.drop_constraint("ck_eis_223_event_counts", "eis_223_event_windows", type_="check")
    op.create_check_constraint(
        "ck_eis_223_event_counts", "eis_223_event_windows",
        "archive_count BETWEEN 1 AND 2 AND record_count >= 1",
    )
