"""Synthetic purchaseRejection XML/ZIP evidence only."""

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from lxml import etree as E  # type: ignore[import-untyped]

from procurement.sources.eis_223_events import (
    Eis223EventContractError,
    Eis223RejectionState,
    inspect_purchase_rejection_archive,
    parse_purchase_rejection_xml,
    resolve_purchase_rejection_state,
    validate_purchase_rejection_schema,
)
from procurement.sources.eis_223_schema import SchemaTree

GUID = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"


def event_xml(
    *,
    guid: str = GUID,
    number: str = "12345678901",
    publication: str | None = "2026-10-01T10:10:00+03:00",
    cause: str = "synthetic untrusted cause",
) -> bytes:
    published = (
        f"<p:publicationDateTime>{publication}</p:publicationDateTime>" if publication else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:purchaseRejection xmlns:p="http://zakupki.gov.ru/223fz/purchase/1"
 xmlns:t="http://zakupki.gov.ru/223fz/types/1">
 <t:header><t:guid>BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB</t:guid>
 <t:createDateTime>2026-10-01T09:00:00+03:00</t:createDateTime></t:header>
 <p:body><p:item><t:guid>CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC</t:guid>
 <p:purchaseRejectionData><p:guid>{guid}</p:guid>
 <p:createDateTime>2026-10-01T09:30:00+03:00</p:createDateTime>
 <p:cancelNoticeRegistrationNumber>{number}</p:cancelNoticeRegistrationNumber>
 {published}<p:rejectionDate>2026-10-01T10:05:00+03:00</p:rejectionDate>
 <p:causeForRejection>{cause}</p:causeForRejection><p:placer><t:mainInfo>
 <t:inn>7700000000</t:inn><t:kpp>770001001</t:kpp>
 </t:mainInfo></p:placer></p:purchaseRejectionData></p:item></p:body>
</p:purchaseRejection>""".encode()


def zip_bytes(items: list[tuple[str, bytes]]) -> bytes:
    result = BytesIO()
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        for name, raw in items:
            archive.writestr(name, raw)
    return result.getvalue()


def parse(**kwargs):
    return parse_purchase_rejection_xml(event_xml(**kwargs), source_member="event.xml")


def test_exact_event_facts_are_typed_normalized_and_provenanced():
    event = parse()
    assert event.event_guid.value == GUID.lower() and event.event_guid.raw == GUID
    assert event.purchase_number == "12345678901" and event.publication_at.status == "AWARE"
    assert event.header_guid.provenance.locator == "purchaseRejection/t:header/t:guid"
    assert event.item_guid.provenance.locator.endswith("p:item/t:guid")
    assert event.cause.raw == "synthetic untrusted cause"
    assert "version" not in event.model_dump() and "status" not in event.model_dump()


def test_optional_or_naive_publication_stays_unknown():
    assert parse(publication=None).publication_at.status == "UNKNOWN"
    assert parse(publication="2026-10-01T10:00:00").publication_at.status == "UNKNOWN"


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"12345678901", "１２３４５６７８９０１".encode(), "PURCHASE_NUMBER_INVALID"),
        (GUID.encode(), b"not-a-guid", "EVENT_GUID_INVALID"),
        (b"<p:purchaseRejection", b"<p:purchaseNotice", "DOCUMENT_TYPE_UNSUPPORTED"),
    ],
)
def test_ambiguous_or_unsupported_identity_is_rejected(old, new, reason):
    raw = event_xml().replace(old, new, 1 if reason == "DOCUMENT_TYPE_UNSUPPORTED" else -1)
    if reason == "DOCUMENT_TYPE_UNSUPPORTED":
        raw = raw.replace(b"</p:purchaseRejection>", b"</p:purchaseNotice>")
    with pytest.raises(Eis223EventContractError, match=reason):
        parse_purchase_rejection_xml(raw, source_member="event.xml")


def test_direct_duplicate_and_namespace_shadow_are_rejected():
    raw = event_xml().replace(
        f"<p:guid>{GUID}</p:guid>".encode(),
        f"<p:guid>{GUID}</p:guid><p:guid>{GUID}</p:guid>".encode(),
    )
    with pytest.raises(Eis223EventContractError, match="MISSING_OR_DUPLICATE"):
        parse_purchase_rejection_xml(raw, source_member="event.xml")
    shadow = event_xml().replace(b"<p:guid>", b"<guid>", 1).replace(b"</p:guid>", b"</guid>", 1)
    with pytest.raises(Eis223EventContractError, match="NAMESPACE"):
        parse_purchase_rejection_xml(shadow, source_member="event.xml")


def test_archive_retains_guid_variants_but_rejects_exact_duplicate_and_unsafe_path():
    first = event_xml(cause="one")
    second = event_xml(cause="two")
    report = inspect_purchase_rejection_archive(
        zip_bytes([("one.xml", first), ("two.xml", second)]),
        company_id="tenant-a",
        source_response_sha256="a" * 64,
        source_locator="synthetic",
    )
    assert len(report.records) == 2
    with pytest.raises(Eis223EventContractError, match="VARIANT_DUPLICATE"):
        inspect_purchase_rejection_archive(
            zip_bytes([("one.xml", first), ("two.xml", first)]),
            company_id="tenant-a",
            source_response_sha256="a" * 64,
            source_locator="synthetic",
        )
    with pytest.raises(Eis223EventContractError, match="MEMBER_REJECTED"):
        inspect_purchase_rejection_archive(
            zip_bytes([("../event.xml", first)]),
            company_id="tenant-a",
            source_response_sha256="a" * 64,
            source_locator="synthetic",
        )


def test_dtd_and_symlink_are_rejected():
    with pytest.raises(Eis223EventContractError, match="XML_REJECTED"):
        parse_purchase_rejection_xml(b"<!DOCTYPE x>" + event_xml(), source_member="event.xml")
    result = BytesIO()
    with ZipFile(result, "w") as archive:
        info = ZipInfo("event.xml")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, event_xml())
    with pytest.raises(Eis223EventContractError, match="MEMBER_REJECTED"):
        inspect_purchase_rejection_archive(
            result.getvalue(),
            company_id="tenant-a",
            source_response_sha256="a" * 64,
            source_locator="synthetic",
        )


def test_resolver_is_conservative_and_overflow_holds():
    event = parse()
    now = datetime(2026, 10, 2, tzinfo=UTC)
    checks = tuple(
        SimpleNamespace(
            event_guid=event.event_guid.value,
            purchase_number=event.purchase_number,
            xml_sha256=event.xml_sha256,
            schema_release=release,
            status="PASS",
        )
        for release in ("16.2", "16.3")
    )
    state = resolve_purchase_rejection_state(event.purchase_number, [event], checks, now=now)
    assert (state.evidence_status, state.application_status, state.operation_hold) == (
        "PASS",
        "FAIL",
        True,
    )
    assert state.reason_codes == ("PURCHASE_REJECTION_CONFIRMED",)
    missing = resolve_purchase_rejection_state(event.purchase_number, [], [], now=now)
    assert not missing.operation_hold and missing.evidence_status == "UNKNOWN"
    overflow = resolve_purchase_rejection_state(
        event.purchase_number, [], [], now=now, reason_codes=("EVENT_EVIDENCE_LIMIT",)
    )
    assert overflow.operation_hold and overflow.events == ()


def test_rejection_after_publication_is_unknown_even_with_both_schema_passes():
    event = parse(publication="2026-10-01T10:00:00+03:00")
    checks = tuple(
        SimpleNamespace(
            event_guid=event.event_guid.value,
            purchase_number=event.purchase_number,
            xml_sha256=event.xml_sha256,
            schema_release=release,
            status="PASS",
        )
        for release in ("16.2", "16.3")
    )
    state = resolve_purchase_rejection_state(
        event.purchase_number,
        [event],
        checks,
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assert state.evidence_status == state.application_status == "UNKNOWN"
    assert state.operation_hold
    assert "REJECTION_EVENT_TIME_ORDER_UNRESOLVED" in state.reason_codes


def test_hold_state_requires_machine_readable_reason():
    with pytest.raises(ValueError, match="REJECTION_HOLD_REASON_MISSING"):
        Eis223RejectionState(
            purchase_number="12345678901",
            checked_at=datetime(2026, 10, 2, tzinfo=UTC),
            evidence_status="UNKNOWN",
            application_status="UNKNOWN",
            operation_hold=True,
            reason_codes=(),
            events=(),
        )


def test_same_guid_variants_and_target_conflict_stay_unknown_hold():
    first = parse(cause="one")
    second = parse(cause="two", number="10987654321")
    state = resolve_purchase_rejection_state(
        first.purchase_number,
        [second, first],
        [],
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assert state.evidence_status == "UNKNOWN" and state.operation_hold
    assert {"EVENT_GUID_VARIANTS", "EVENT_GUID_TARGET_CONFLICT"} <= set(state.reason_codes)


def test_schema_evidence_is_bound_to_event_guid_purchase_and_xml():
    schema = E.XMLSchema(
        E.fromstring(
            b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            b'targetNamespace="http://zakupki.gov.ru/223fz/purchase/1">'
            b'<xs:element name="purchaseRejection" type="xs:anyType"/></xs:schema>'
        )
    )
    raw = event_xml()
    event = parse_purchase_rejection_xml(raw, source_member="event.xml")
    check = validate_purchase_rejection_schema(
        event, raw, SchemaTree("16.3", schema), now=datetime(2026, 10, 2, tzinfo=UTC)
    )
    assert check.status == "PASS" and check.event_guid == GUID.lower()
    changed = event.model_copy(update={"xml_sha256": "f" * 64})
    with pytest.raises(ValueError, match="EVENT_SCHEMA_XML_IDENTITY_MISMATCH"):
        validate_purchase_rejection_schema(
            changed, raw, SchemaTree("16.3", schema), now=datetime(2026, 10, 2, tzinfo=UTC)
        )
