"""Synthetic purchaseLotCancellation XML/ZIP only."""

from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from lxml import etree as E  # type: ignore[import-untyped]

from procurement.sources.eis_223_lot_events import (
    Eis223LotEventContractError,
    inspect_purchase_lot_cancellation_archive,
    parse_purchase_lot_cancellation_xml,
    validate_purchase_lot_cancellation_schema,
)
from procurement.sources.eis_223_schema import SchemaTree

GUID = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"


def lot_event_xml(
    *, description: str = "COMMON", ordinal: str = "7", joint: str = "false"
) -> bytes:
    individual = (
        "<p:cancellation><t:cancelDate>2026-10-01</t:cancelDate>"
        "<t:cancelInfo>individual cause</t:cancelInfo></p:cancellation>"
        if description == "VARIOUS"
        else ""
    )
    common = (
        "<p:cancelDate>2026-10-01</p:cancelDate><p:description>common cause</p:description>"
        if description == "COMMON"
        else ""
    )
    return f"""<p:purchaseLotCancellation
 xmlns:p="http://zakupki.gov.ru/223fz/purchase/1"
 xmlns:t="http://zakupki.gov.ru/223fz/types/1">
 <t:header><t:guid>BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB</t:guid>
 <t:createDateTime>2026-10-01T09:00:00+03:00</t:createDateTime></t:header>
 <p:body><p:item><t:guid>CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC</t:guid>
 <p:purchaseLotCancellationData><p:guid>{GUID}</p:guid>
 <p:createDateTime>2026-10-01T09:10:00+03:00</p:createDateTime>
 <p:publicationDateTime>2026-10-01T10:00:00+03:00</p:publicationDateTime>
 <p:placer><t:mainInfo><t:inn>7700000000</t:inn><t:kpp>770001001</t:kpp></t:mainInfo></p:placer>
 <p:purchaseInfo><t:guid>DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD</t:guid>
 <t:purchaseNoticeNumber>12345678901</t:purchaseNoticeNumber>
 <t:name>synthetic</t:name><t:purchaseMethodCode>1</t:purchaseMethodCode></p:purchaseInfo>
 <p:cancelledLots><p:cancelledLot><p:guid>EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE</p:guid>
 <p:ordinalNumber>{ordinal}</p:ordinalNumber><p:subject>lot subject</p:subject>
 <p:jointLot>{joint}</p:jointLot>{individual}</p:cancelledLot></p:cancelledLots>
 <p:descriptionType>{description}</p:descriptionType>{common}
 </p:purchaseLotCancellationData></p:item></p:body></p:purchaseLotCancellation>""".encode()


def zip_bytes(items: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, raw in items:
            archive.writestr(name, raw)
    return output.getvalue()


def test_common_and_various_exact_facts_preserve_date_without_midnight():
    common = parse_purchase_lot_cancellation_xml(lot_event_xml(), source_member="event.xml")
    various = parse_purchase_lot_cancellation_xml(
        lot_event_xml(description="VARIOUS"), source_member="event.xml"
    )
    assert common.event_guid.value == GUID.lower() and common.purchase_number == "12345678901"
    assert common.common_cancellation_date.raw == "2026-10-01"
    assert common.common_cancellation_date.value == datetime(2026, 10, 1).date()
    assert common.common_cancellation_date.timezone_raw is None
    assert common.cancelled_lots[0].ordinal.raw == "7"
    assert various.cancelled_lots[0].cancellation_date.raw == "2026-10-01"
    assert common.purchase_number_provenance.locator.endswith("t:purchaseNoticeNumber")


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"<p:ordinalNumber>7", b"<p:ordinalNumber>0", "LOT_ORDINAL_INVALID"),
        (b"<p:jointLot>false", b"<p:jointLot>yes", "JOINT_LOT_INVALID"),
        (b"12345678901", "１２３４５６７８９０１".encode(), "PURCHASE_NUMBER_INVALID"),
    ],
)
def test_runtime_rejects_unsafe_association_values(old, new, reason):
    with pytest.raises(Eis223LotEventContractError, match=reason):
        parse_purchase_lot_cancellation_xml(
            lot_event_xml().replace(old, new), source_member="event.xml"
        )


def test_duplicate_ordinal_and_namespace_shadow_rejected():
    raw = lot_event_xml().replace(
        b"</p:cancelledLots>",
        lot_event_xml().split(b"<p:cancelledLot>", 1)[1].split(b"</p:cancelledLot>", 1)[0]
        .join((b"<p:cancelledLot>", b"</p:cancelledLot></p:cancelledLots>")),
    )
    with pytest.raises(Eis223LotEventContractError, match="LOT_ORDINAL_INVALID"):
        parse_purchase_lot_cancellation_xml(raw, source_member="event.xml")
    shadow = lot_event_xml().replace(b"<p:ordinalNumber>", b"<t:ordinalNumber>")
    shadow = shadow.replace(b"</p:ordinalNumber>", b"</t:ordinalNumber>")
    with pytest.raises(Eis223LotEventContractError, match="NAMESPACE"):
        parse_purchase_lot_cancellation_xml(shadow, source_member="event.xml")


def test_duplicate_lot_guid_is_rejected_even_with_different_positive_ordinal():
    first_lot = lot_event_xml().split(b"<p:cancelledLot>", 1)[1].split(
        b"</p:cancelledLot>", 1
    )[0]
    second_lot = first_lot.replace(
        b"<p:ordinalNumber>7", b"<p:ordinalNumber>8"
    )
    raw = lot_event_xml().replace(
        b"</p:cancelledLots>",
        b"<p:cancelledLot>" + second_lot + b"</p:cancelledLot></p:cancelledLots>",
    )
    with pytest.raises(Eis223LotEventContractError, match="LOT_GUID_DUPLICATE"):
        parse_purchase_lot_cancellation_xml(raw, source_member="event.xml")


def test_archive_variants_retained_exact_duplicate_and_unsafe_member_rejected():
    first = lot_event_xml()
    second = first.replace(b"common cause", b"changed cause")
    report = inspect_purchase_lot_cancellation_archive(
        zip_bytes([("one.xml", first), ("two.xml", second)]),
        company_id="tenant-a",
        source_response_sha256="a" * 64,
        source_locator="synthetic",
    )
    assert len(report.records) == 2
    for items, reason in [
        ([('one.xml', first), ('two.xml', first)], "EVENT_VARIANT_DUPLICATE"),
        ([('../one.xml', first)], "ARCHIVE_MEMBER_REJECTED"),
    ]:
        with pytest.raises(Eis223LotEventContractError, match=reason):
            inspect_purchase_lot_cancellation_archive(
                zip_bytes(items),
                company_id="tenant-a",
                source_response_sha256="a" * 64,
                source_locator="synthetic",
            )


def test_schema_check_is_bound_to_exact_event_identity():
    schema = E.XMLSchema(
        E.fromstring(
            b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            b'targetNamespace="http://zakupki.gov.ru/223fz/purchase/1">'
            b'<xs:element name="purchaseLotCancellation" type="xs:anyType"/></xs:schema>'
        )
    )
    raw = lot_event_xml()
    event = parse_purchase_lot_cancellation_xml(raw, source_member="event.xml")
    check = validate_purchase_lot_cancellation_schema(
        event, raw, SchemaTree("16.3", schema), now=datetime(2026, 10, 2, tzinfo=UTC)
    )
    assert check.status == "PASS" and check.event_guid == GUID.lower()
