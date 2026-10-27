"""Admit source-verified joint families, preserving existing immutable ZP JSON."""

from alembic import op

revision = "20261027_03"
down_revision = "20261027_02"
branch_labels = None
depends_on = None

TABLE = "eis_223_position_projections"
CONSTRAINT = "ck_eis_223_position_identity"
NEW_TYPES = (
    "('purchaseNoticeZPESMBO','purchaseNoticeKESMBO','purchaseNotice','purchaseNoticeAESMBO')"
)


def _identity_sql(type_predicate):
    return (
        "COALESCE(jsonb_typeof(position_set) = 'object' AND position_set->>'law' = '223' AND "
        + type_predicate
        + " AND position_set->>'purchase_number' = purchase_number AND "
        "(position_set->>'version_number')::integer = version_number AND "
        "position_set->>'notice_xml_sha256' = notice_xml_sha256 AND "
        "position_set->>'parser_version' = parser_version AND "
        "jsonb_typeof(position_set->'lots') = 'array' AND "
        "jsonb_array_length(position_set->'lots') > 0 AND "
        "length(position_set->>'source_member') BETWEEN 1 AND 1024 AND "
        "position_set->>'source_item_coverage' IN ('PASS','UNKNOWN') AND "
        "position_set->>'specification_completeness' = 'UNKNOWN' AND "
        "position_set->>'economics_status' = 'UNKNOWN', false)"
    )


def _replace(predicate):
    op.execute("SET LOCAL statement_timeout='5s'")
    op.execute("SET LOCAL lock_timeout='2s'")
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, _identity_sql(predicate))


def upgrade():
    _replace("position_set->>'document_type' IN " + NEW_TYPES)


def downgrade():
    # Owner must see every tenant; a non-owner fails closed under FORCE RLS.
    op.execute("SET LOCAL statement_timeout='5s'")
    op.execute("SET LOCAL lock_timeout='2s'")
    op.execute("SET LOCAL row_security=off")
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM "
        + TABLE
        + " WHERE position_set->>'document_type' IS DISTINCT FROM 'purchaseNoticeZPESMBO') "
        "THEN RAISE EXCEPTION 'non-ZP joint position history must be preserved'; END IF; END $$"
    )
    _replace("position_set->>'document_type' = 'purchaseNoticeZPESMBO'")
