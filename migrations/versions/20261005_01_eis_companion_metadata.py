"""Admit six exact-number companion metadata families with immutable XML identity."""

from alembic import op

revision = "20261005_01"
down_revision = "20261004_03"
branch_labels = None
depends_on = None

COMPANIONS = (
    "'epClarificationDoc','epProtocolEOK2020FirstSections',"
    "'epProtocolEOK2020SecondSections','epProtocolEOK2020Final',"
    "'fcsPlacementResult','fcsProposalsResult'"
)
OLD_STAGE = (
    "((document_type = 'epNotificationCancel' AND recovery_stage IS NULL) OR "
    "(document_type = 'epNotificationCancelFailure' AND "
    "recovery_stage IN ('NP','AP','CW','FO','CO'))) IS TRUE"
)
NEW_STAGE = (
    "((document_type = 'epNotificationCancel' AND recovery_stage IS NULL) OR "
    "(document_type = 'epNotificationCancelFailure' AND "
    "recovery_stage IN ('NP','AP','CW','FO','CO')) OR "
    f"(document_type IN ({COMPANIONS}) AND recovery_stage IS NULL)) IS TRUE"
)
FAMILY = (
    "((document_type IN ('epNotificationCancel','epNotificationCancelFailure') AND "
    "parser_version = 'eis-procedure-event-v1') OR "
    f"(document_type IN ({COMPANIONS}) AND parser_version = 'eis-companion-document-v1' "
    "AND document_id = 'sha256:' || xml_sha256)) IS TRUE"
)


def upgrade() -> None:
    # Some historical bootstrap migrations create current metadata on a fresh DB.
    # Replace only our named constraint in either bootstrap or deployed schema.
    op.execute("ALTER TABLE eis_procedure_events DROP CONSTRAINT IF EXISTS ck_eis_event_family")
    op.drop_constraint("ck_eis_event_parser", "eis_procedure_events", type_="check")
    op.drop_constraint("ck_eis_event_type_stage", "eis_procedure_events", type_="check")
    op.create_check_constraint(
        "ck_eis_event_parser",
        "eis_procedure_events",
        "parser_version IN ('eis-procedure-event-v1','eis-companion-document-v1')",
    )
    op.create_check_constraint("ck_eis_event_type_stage", "eis_procedure_events", NEW_STAGE)
    op.create_check_constraint("ck_eis_event_family", "eis_procedure_events", FAMILY)


def downgrade() -> None:
    # Original constraints deliberately fail when companion evidence exists.
    # No automatic deletion or transformation of immutable source rows.
    op.drop_constraint("ck_eis_event_family", "eis_procedure_events", type_="check")
    op.drop_constraint("ck_eis_event_parser", "eis_procedure_events", type_="check")
    op.drop_constraint("ck_eis_event_type_stage", "eis_procedure_events", type_="check")
    op.create_check_constraint(
        "ck_eis_event_parser",
        "eis_procedure_events",
        "parser_version = 'eis-procedure-event-v1'",
    )
    op.create_check_constraint("ck_eis_event_type_stage", "eis_procedure_events", OLD_STAGE)
