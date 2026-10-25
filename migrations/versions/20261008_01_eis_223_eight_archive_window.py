"""Admit eight notice archives while preserving immutable source history."""

from alembic import op

revision = "20261008_01"
down_revision = "20261006_08"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_eis_223_counts", "eis_223_windows", type_="check")
    op.create_check_constraint(
        "ck_eis_223_counts",
        "eis_223_windows",
        "archive_count BETWEEN 1 AND 8 AND record_count >= 1",
    )


def downgrade():
    # A tenant-filtered query must never hide wider source history from this guard.
    op.execute("SET LOCAL row_security = off")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM eis_223_windows WHERE archive_count > 4) "
        "THEN RAISE EXCEPTION '223 wide archive history must be preserved'; "
        "END IF; END $$"
    )
    op.drop_constraint("ck_eis_223_counts", "eis_223_windows", type_="check")
    op.create_check_constraint(
        "ck_eis_223_counts",
        "eis_223_windows",
        "archive_count BETWEEN 1 AND 4 AND record_count >= 1",
    )
