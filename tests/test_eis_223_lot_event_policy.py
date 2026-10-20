"""No false lot FAIL/PASS from schema, apparent identifiers, overflow or absence."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.sources.eis_223_archive import TextFact, parse_notice223_xml
from procurement.sources.eis_223_events import Eis223EventSchemaCheck
from procurement.sources.eis_223_lot_event_policy import (
    resolve_lot_cancellation_state,
    selected_lot_cancellation_state,
)
from procurement.sources.eis_223_lot_events import parse_purchase_lot_cancellation_xml
from procurement.sources.eis_223_schema import SCHEMAS, VALIDATOR
from test_eis_223_archive import xml
from test_eis_223_lot_events import lot_event_xml

NOW = datetime(2026, 10, 3, tzinfo=UTC)
NUMBER = "32600000001"


def event(raw=None):
    return parse_purchase_lot_cancellation_xml(
        raw or lot_event_xml().replace(b"12345678901", NUMBER.encode()), source_member="lot.xml"
    )


def checks(item):
    return tuple(
        Eis223EventSchemaCheck(
            event_guid=item.event_guid.value,
            purchase_number=item.purchase_number,
            xml_sha256=item.xml_sha256,
            schema_release=r,
            package_sha256=p[0],
            root_sha256=p[1],
            tree_sha256=p[2],
            validator_version=VALIDATOR,
            status="PASS",
            diagnostics=(),
            checked_at=NOW,
        )
        for r, p in SCHEMAS.items()
    )


def notice():
    return parse_notice223_xml(xml(), source_member="notice.xml")


def test_absence_never_confirms_availability():
    state = resolve_lot_cancellation_state(NUMBER, (), (), now=NOW)
    assert not state.operation_hold and state.application_status == "UNKNOWN"
    selected = selected_lot_cancellation_state(notice(), 1, state)
    assert selected.application_status == selected.association_status == "UNKNOWN"
    assert selected.selected_index == 1 and selected.lot_ordinal.value != "7"


def test_dual_schema_and_aware_times_never_confirm_target_or_other_lot():
    item = event()
    state = resolve_lot_cancellation_state(NUMBER, (item,), checks(item), now=NOW)
    assert state.source_schema_status == "PASS" and state.operation_hold
    assert state.evidence_status == state.application_status == "UNKNOWN"
    source_notice = notice()
    lot = source_notice.lots[0]
    matching = lot.model_copy(
        update={
            "guid": TextFact(
                value=item.cancelled_lots[0].lot_guid.value,
                raw=item.cancelled_lots[0].lot_guid.raw,
                provenance=lot.ordinal.provenance,
            ),
            "ordinal": lot.ordinal.model_copy(update={"raw": "7", "value": "7"}),
        }
    )
    source_notice = source_notice.model_copy(update={"lots": (lot, matching)})
    other = selected_lot_cancellation_state(source_notice, 1, state)
    coincident = selected_lot_cancellation_state(source_notice, 2, state)
    assert other.operation_hold and not other.apparent_match_event_guids
    assert coincident.operation_hold and coincident.apparent_match_event_guids == (
        item.event_guid.value,
    )
    assert coincident.selected_index == 2 and coincident.lot_ordinal.value == "7"
    assert other.application_status == coincident.application_status == "UNKNOWN"


@pytest.mark.parametrize("overflow", ["per_number", "global"])
def test_overflow_selected_projection_returns_unknown_hold_not_500(overflow):
    material = (
        tuple(
            event(
                lot_event_xml()
                .replace(b"12345678901", NUMBER.encode())
                .replace(
                    b"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
                    f"{i:08x}-aaaa-aaaa-aaaa-aaaaaaaaaaaa".encode(),
                )
            )
            for i in range(101)
        )
        if overflow == "per_number"
        else ()
    )
    state = resolve_lot_cancellation_state(
        NUMBER,
        material,
        (),
        now=NOW,
        reason_codes=("EVENT_EVIDENCE_LIMIT",) if overflow == "global" else (),
    )
    assert state.operation_hold and not state.events
    assert selected_lot_cancellation_state(notice(), 1, state).operation_hold


def test_conflicting_guid_and_other_target_preserve_unknown_hold():
    first = event()
    second = event(lot_event_xml().replace(b"12345678901", b"32600000002"))
    state = resolve_lot_cancellation_state(NUMBER, (first, second), (), now=NOW)
    assert state.operation_hold and len(state.events) == 2
    assert {"LOT_EVENT_GUID_TARGET_CONFLICT", "LOT_EVENT_GUID_VARIANTS"} <= set(state.reason_codes)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda r: r.replace(b"+03:00", b""), "LOT_CANCELLATION_TIME_UNRESOLVED"),
        (
            lambda r: r.replace(b"<p:cancelDate>2026-10-01</p:cancelDate>", b""),
            "LOT_CANCELLATION_DECISION_INCOMPLETE",
        ),
        (
            lambda r: r.replace(b"<p:description>common cause</p:description>", b""),
            "LOT_CANCELLATION_DECISION_INCOMPLETE",
        ),
        (
            lambda r: r.replace(b"2026-10-01T09:10", b"2026-10-04T09:10"),
            "LOT_CANCELLATION_TIME_UNRESOLVED",
        ),
    ],
)
def test_incomplete_source_remains_unknown(mutation, reason):
    item = event(mutation(lot_event_xml().replace(b"12345678901", NUMBER.encode())))
    state = resolve_lot_cancellation_state(NUMBER, (item,), checks(item), now=NOW)
    assert (
        state.source_schema_status == "PASS"
        and state.operation_hold
        and reason in state.reason_codes
    )


def test_exact_quality_identity_and_validated_models():
    item = event()
    bad = checks(item)[0].model_copy(update={"purchase_number": "32600000002"})
    with pytest.raises(ValueError, match="ASSOCIATION"):
        resolve_lot_cancellation_state(NUMBER, (item,), (bad,), now=NOW)
    state = resolve_lot_cancellation_state(NUMBER, (item,), (), now=NOW)
    with pytest.raises(ValidationError):
        type(state).model_validate({**state.model_dump(), "application_status": "FAIL"})
    with pytest.raises(ValueError, match="TIMEZONE"):
        resolve_lot_cancellation_state(NUMBER, (), (), now=NOW.replace(tzinfo=None))
