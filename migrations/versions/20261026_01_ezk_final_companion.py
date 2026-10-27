"""Retain EZK final protocol metadata in exact-number notice archives."""

from alembic import op

revision = "20261026_01"
down_revision = "20261025_01"
branch_labels = None
depends_on = None

PREVIOUS_COMPANIONS = (
    "'epClarificationDoc','epProtocolEOK2020FirstSections',"
    "'epProtocolEOK2020SecondSections','epProtocolEOK2020Final',"
    "'fcsPlacementResult','fcsProposalsResult'"
)


def _replace_checks(companions: str) -> None:
    op.execute("SET LOCAL lock_timeout='2s'")
    op.execute("SET LOCAL statement_timeout='5s'")
    op.drop_constraint("ck_eis_event_type_stage", "eis_procedure_events", type_="check")
    op.drop_constraint("ck_eis_event_family", "eis_procedure_events", type_="check")
    op.create_check_constraint(
        "ck_eis_event_type_stage",
        "eis_procedure_events",
        "((document_type = 'epNotificationCancel' AND recovery_stage IS NULL) OR "
        "(document_type = 'epNotificationCancelFailure' AND "
        "recovery_stage IN ('NP','AP','CW','FO','CO')) OR "
        f"(document_type IN ({companions}) AND recovery_stage IS NULL)) IS TRUE",
    )
    op.create_check_constraint(
        "ck_eis_event_family",
        "eis_procedure_events",
        "((document_type IN ('epNotificationCancel','epNotificationCancelFailure') AND "
        "parser_version = 'eis-procedure-event-v1') OR "
        f"(document_type IN ({companions}) AND parser_version = 'eis-companion-document-v1' "
        "AND document_id = 'sha256:' || xml_sha256)) IS TRUE",
    )


def upgrade() -> None:
    _replace_checks(PREVIOUS_COMPANIONS + ",'epProtocolEZK2020Final'")


def downgrade() -> None:
    # Existing final protocols deliberately block downgrade. Preserve evidence;
    # image rollback uses the expanded schema rather than deleting immutable rows.
    _replace_checks(PREVIOUS_COMPANIONS)
