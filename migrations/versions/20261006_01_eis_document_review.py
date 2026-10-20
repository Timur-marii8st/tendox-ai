"""Add a separate immutable DOCX review revision; preserve native v1/v2/v3."""

from alembic import op

revision = "20261006_01"
down_revision = "20261005_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("SET LOCAL statement_timeout='60s'")
    op.drop_constraint("ck_eis_document_analyzer", "eis_document_analyses", type_="check")
    op.create_check_constraint(
        "ck_eis_document_analyzer",
        "eis_document_analyses",
        "analyzer_version IN ('eis-native-v1','eis-native-v2-xls','eis-native-v3-doc',"
        "'eis-native-review-v1')",
    )


def downgrade() -> None:
    # Existing review evidence deliberately blocks downgrade; never delete it.
    op.drop_constraint("ck_eis_document_analyzer", "eis_document_analyses", type_="check")
    op.create_check_constraint(
        "ck_eis_document_analyzer",
        "eis_document_analyses",
        "analyzer_version IN ('eis-native-v1','eis-native-v2-xls','eis-native-v3-doc')",
    )
