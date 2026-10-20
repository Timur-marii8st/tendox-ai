"""Cancellation events must not produce false admission or chronology."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources.eis_feed_archive import (
    EisFeedArchiveError,
    EisProcedureEvent,
    inspect_eis_auction_archive,
)
from procurement.sources.eis_procedure_state import resolve_procedure_state

NOW = datetime(2026, 9, 28, tzinfo=UTC)
NUMBER = "0848300054826000154"


def event_zip(
    kind: str = "epNotificationCancel",
    *,
    identifier: str = "1",
    number: str = NUMBER,
    published: str = "2026-09-25T10:00:00+03:00",
    stage: str = "AP",
) -> bytes:
    detail = "<cancelReasonInfo><reason>Отмена</reason></cancelReasonInfo>"
    if kind == "epNotificationCancelFailure":
        detail = (
            f"<cancelFailureInfo><recoveryToStage>{stage}</recoveryToStage></cancelFailureInfo>"
        )
    xml = f"""<export xmlns="http://zakupki.gov.ru/oos/export/1">
<{kind}><id>{identifier}</id><commonInfo><purchaseNumber>{number}</purchaseNumber>
<docPublishDTInEIS>{published}</docPublishDTInEIS></commonInfo>{detail}</{kind}></export>"""
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("event.xml", xml.encode())
    return output.getvalue()


def parse(content: bytes, kind: str = "epNotificationCancel") -> EisProcedureEvent:
    result = inspect_eis_auction_archive(
        content,
        source_locator="test",
        source_response_sha256="a" * 64,
        expected_document_type=kind,
    )
    assert not result.records
    return result.events[0]


def test_cancel_shape_does_not_require_notice_version_or_price() -> None:
    event = parse(event_zip())
    assert event.document_id == "1" and event.purchase_number == NUMBER
    assert event.locator.startswith("epNotificationCancel/")
    assert event.parser_version == "eis-procedure-event-v1"
    state = resolve_procedure_state((event,), purchase_number=NUMBER, now=NOW)
    assert state.application_status == "FAIL"
    assert any(event.xml_sha256 in reason for reason in state.reasons)


def test_failure_ap_restores_only_unknown_and_later_cancel_blocks() -> None:
    cancel = parse(event_zip())
    restored = parse(
        event_zip(
            "epNotificationCancelFailure", identifier="2", published="2026-09-26T10:00:00+03:00"
        ),
        "epNotificationCancelFailure",
    )
    assert (
        resolve_procedure_state(
            (cancel, restored), purchase_number=NUMBER, now=NOW
        ).application_status
        == "UNKNOWN"
    )
    new_cancel = replace(cancel, document_id="3", published_at=NOW - timedelta(hours=1))
    assert (
        resolve_procedure_state(
            (restored, cancel, new_cancel), purchase_number=NUMBER, now=NOW
        ).application_status
        == "FAIL"
    )


@pytest.mark.parametrize("stage", ["NP", "CW", "FO", "CO"])
def test_restored_non_application_stage_is_blocked(stage: str) -> None:
    event = parse(
        event_zip("epNotificationCancelFailure", stage=stage), "epNotificationCancelFailure"
    )
    assert (
        resolve_procedure_state((event,), purchase_number=NUMBER, now=NOW).application_status
        == "FAIL"
    )


@pytest.mark.parametrize("published", ["", "2026-09-25T10:00:00", "2026-10-01T10:00:00+03:00"])
def test_missing_naive_or_future_event_time_does_not_establish_stage(published: str) -> None:
    event = parse(event_zip(published=published))
    assert (
        resolve_procedure_state((event,), purchase_number=NUMBER, now=NOW).application_status
        == "UNKNOWN"
    )


def test_tied_events_and_empty_history_remain_unknown() -> None:
    cancel = parse(event_zip())
    restored = parse(event_zip("epNotificationCancelFailure"), "epNotificationCancelFailure")
    assert (
        resolve_procedure_state(
            (cancel, restored), purchase_number=NUMBER, now=NOW
        ).application_status
        == "UNKNOWN"
    )
    assert (
        resolve_procedure_state((), purchase_number=NUMBER, now=NOW).application_status == "UNKNOWN"
    )


def test_foreign_purchase_and_type_are_rejected() -> None:
    with pytest.raises(ValueError, match="EVENT_PURCHASE_MISMATCH"):
        resolve_procedure_state((parse(event_zip()),), purchase_number="other", now=NOW)
    with pytest.raises(EisFeedArchiveError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        parse(event_zip("epNotificationCancelFailure"))
    with pytest.raises(EisFeedArchiveError, match="RECOVERY_STAGE_INVALID"):
        parse(event_zip("epNotificationCancelFailure", stage="PASS"), "epNotificationCancelFailure")
