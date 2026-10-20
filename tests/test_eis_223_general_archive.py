"""Synthetic exact-shape contract for the general RI223 purchaseNotice family."""

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources.eis_223_archive import (
    PURCHASE_NS,
    Eis223ContractError,
    inspect_notice223_archive,
    notice223_request,
    parse_notice223_xml,
)

TYPES_NS = "http://zakupki.gov.ru/223fz/types/1"
UID = "A" * 32
URL = "https://zakupki.gov.ru/223/filestore/public/1.0/download/fz223/file.html?uid=" + UID


def general_xml(
    *,
    price: str = "<t:initialSum>100.25</t:initialSum>",
    currency: str = "<t:code>RUB</t:code><t:digitalCode>643</t:digitalCode>",
    deadline: str = "2026-10-09T08:00:00+03:00",
    hide: str = "false",
    lot_oriented: str = "false",
    lot_data: bool = True,
    document_flag: str = "",
    manifest_extra: str = "",
    lot_msp: str | None = None,
) -> bytes:
    details = ""
    if lot_data:
        msp = f"<t:forSmallOrMiddle>{lot_msp}</t:forSmallOrMiddle>" if lot_msp else ""
        details = f"""<t:lotData><t:subject>Бумага</t:subject>{msp}
        <t:currency>{currency}</t:currency>{price}
        <t:lotItems><t:lotItem><t:ordinalNumber>4</t:ordinalNumber>
        <t:okpd2><t:code>17.12.14</t:code><t:name>Бумага</t:name></t:okpd2>
        <t:qty>10</t:qty><t:additionalInfo>A4</t:additionalInfo>
        </t:lotItem></t:lotItems></t:lotData>"""
    return f'''<p:purchaseNotice xmlns:p="{PURCHASE_NS}" xmlns:t="{TYPES_NS}">
    <t:header><t:guid>packet-guid</t:guid><t:createDateTime>2026-10-01T10:00:00Z</t:createDateTime></t:header>
    <p:body><p:item><t:guid>item-guid</t:guid><p:purchaseNoticeData>
    <p:guid>purchase-guid</p:guid><p:registrationNumber>32600000001</p:registrationNumber>
    <p:version>2</p:version><p:name>Иной способ закупки</p:name><p:status>P</p:status>
    <p:hidePurchase>{hide}</p:hidePurchase><p:isLotOriented>{lot_oriented}</p:isLotOriented>
    <p:publicationDateTime>2026-10-01T09:00:00Z</p:publicationDateTime>
    <p:submissionCloseDateTime>{deadline}</p:submissionCloseDateTime>
    <p:attachments><t:totalDocumentsCount>1</t:totalDocumentsCount>{manifest_extra}
    <t:document><t:guid>document-guid</t:guid><t:fileName>ТЗ.docx</t:fileName>
    <t:contentUid>{UID}</t:contentUid><t:url>{URL}</t:url>{document_flag}</t:document>
    </p:attachments><p:lots><t:lot><t:guid>lot-guid</t:guid><t:ordinalNumber>7</t:ordinalNumber>
    <t:cancelled>false</t:cancelled>{details}</t:lot></p:lots>
    </p:purchaseNoticeData></p:item></p:body></p:purchaseNotice>'''.encode()


def archive(raw: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr("general.xml", raw)
    return output.getvalue()


def parse(raw: bytes):
    return parse_notice223_xml(raw, source_member="general.xml", document_type="purchaseNotice")


def test_general_initial_sum_identity_deadline_and_exact_provenance() -> None:
    notice = parse(
        general_xml(
            price="<t:initialSum>100.25</t:initialSum>"
            "<t:startingContractPriceRub>100.25</t:startingContractPriceRub>"
        )
    )
    lot = notice.lots[0]
    assert notice.purchase_guid.value == "purchase-guid"
    assert notice.hide_purchase_raw.value == notice.is_lot_oriented_raw.value == "false"
    assert notice.selected_deadline == notice.deadline
    assert notice.deadline.value == datetime.fromisoformat("2026-10-09T08:00:00+03:00")
    assert lot.ordinal.value == "7" and lot.guid.value == "lot-guid"
    assert lot.detail_status == "PRESENT" and lot.source_price_kind == "INITIAL_SUM"
    assert lot.source_amount.value == lot.initial_sum.value == Decimal("100.25")
    assert lot.source_rub_equivalent.value == Decimal("100.25")
    assert lot.initial_sum_rub == Decimal("100.25")
    assert lot.source_currency_status == "CONSISTENT"
    assert lot.source_amount.provenance.locator.endswith("/t:lotData/t:initialSum")
    assert notice.attachments[0].url.value == URL


def test_lot_msp_fact_coexists_with_missing_top_level_without_eligibility_inference() -> None:
    notice = parse(general_xml(lot_msp="true"))
    assert notice.for_small_or_middle_raw.value is None
    assert notice.lots[0].for_small_or_middle_raw.value == "true"
    assert notice.for_small_or_middle_raw.provenance.locator.endswith(
        "/p:purchaseNoticeData/p:forSmallOrMiddle"
    )
    assert notice.lots[0].for_small_or_middle_raw.provenance.locator.endswith(
        "/t:lotData/t:forSmallOrMiddle"
    )
    assert notice.application_status == notice.lot_review_status == "UNKNOWN"


@pytest.mark.parametrize(
    ("price", "kind", "amount", "text"),
    [
        ("<t:maxContractPrice>7000000</t:maxContractPrice>", "MAX_CONTRACT_PRICE", "7000000", None),
        ("<t:initialSumInfo>По формуле</t:initialSumInfo>", "TEXT_ONLY", None, "По формуле"),
    ],
)
def test_non_initial_price_branches_are_exact_but_never_legacy_economics(
    price: str, kind: str, amount: str | None, text: str | None
) -> None:
    lot = parse(general_xml(price=price)).lots[0]
    assert lot.source_price_kind == kind
    assert lot.source_amount.value == (Decimal(amount) if amount else None)
    assert lot.source_price_text.value == text
    assert lot.initial_sum.value is None and lot.initial_sum_rub is None


def test_invalid_max_contract_price_keeps_branch_and_literal_but_no_amount() -> None:
    lot = parse(general_xml(price="<t:maxContractPrice>-1</t:maxContractPrice>")).lots[0]
    assert lot.source_price_kind == "MAX_CONTRACT_PRICE"
    assert lot.source_amount.raw == "-1" and lot.source_amount.value is None
    assert lot.initial_sum.value is None and lot.initial_sum_rub is None


def test_conflicting_price_or_currency_branches_fail_closed() -> None:
    with pytest.raises(Eis223ContractError, match="PRICE_BRANCH_CONFLICT"):
        parse(
            general_xml(
                price="<t:initialSum>1</t:initialSum><t:maxContractPrice>2</t:maxContractPrice>"
            )
        )
    lot = parse(
        general_xml(currency="<t:letterCode>RUB</t:letterCode><t:code>USD</t:code><t:digitalCode>840</t:digitalCode>")
    ).lots[0]
    assert lot.currency_letter_code.value == "RUB" and lot.currency.value == "USD"
    assert lot.source_currency_status == "UNKNOWN" and lot.initial_sum_rub is None


@pytest.mark.parametrize("unsupported", ["priceFormula", "commodityPrice"])
def test_formula_and_commodity_price_never_activate_initial_sum_economics(
    unsupported: str,
) -> None:
    lot = parse(
        general_xml(price=f"<t:initialSum>100.25</t:initialSum><t:{unsupported}>5</t:{unsupported}>")
    ).lots[0]
    assert lot.initial_sum.value == Decimal("100.25")
    assert lot.initial_sum_rub is None
    if unsupported == "priceFormula":
        assert lot.source_price_formula.value == "5"
    else:
        assert lot.source_commodity_price.value == Decimal("5")


def test_optional_lot_data_and_lot_oriented_deadline_remain_unknown() -> None:
    notice = parse(general_xml(lot_data=False, lot_oriented="true"))
    lot = notice.lots[0]
    assert lot.detail_status == "UNKNOWN" and lot.source_price_kind == "UNKNOWN"
    assert lot.subject.value is None and lot.items == () and lot.initial_sum_rub is None
    assert notice.deadline.value is not None
    assert notice.selected_deadline.value is None and notice.selected_deadline.status == "UNKNOWN"


def test_manifest_keeps_fs_previous_additional_and_suppresses_hidden_downloads() -> None:
    extra = """<t:additionalDocumentsCount>3</t:additionalDocumentsCount>
    <t:documentFS><t:guid>fs-guid</t:guid><t:contentUid>BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB</t:contentUid></t:documentFS>
    <t:prevDocument><t:guid>previous-guid</t:guid></t:prevDocument>"""
    raw = general_xml(
        hide="true",
        document_flag="<t:notPlacement>true</t:notPlacement>",
        manifest_extra=extra,
    ).replace(b"<t:totalDocumentsCount>1", b"<t:totalDocumentsCount>2")
    notice = parse(raw)
    assert notice.attachments[0].url.value is None
    assert notice.attachments[0].url.raw == URL
    assert notice.attachments[0].not_placement_raw.value == "true"
    assert notice.manifest_additional_count.value == "3"
    assert [item.kind for item in notice.manifest_references] == [
        "DOCUMENT_FS",
        "PREVIOUS_DOCUMENT",
    ]
    assert notice.manifest_references[0].content_uid.value == "B" * 32
    assert notice.manifest_references[1].guid.value == "previous-guid"
    assert notice.manifest_status == "UNKNOWN"
    assert all("attachments" in item.provenance.locator for item in notice.manifest_references)


def test_manifest_reference_collection_is_bounded() -> None:
    references = "".join(
        f"<t:prevDocument><t:guid>previous-{index}</t:guid></t:prevDocument>"
        for index in range(200)
    )
    with pytest.raises(Eis223ContractError, match="NOTICE_COLLECTION_LIMIT"):
        parse(general_xml(manifest_extra=references))


def test_malformed_flags_and_unsafe_url_never_become_positive() -> None:
    notice = parse(
        general_xml(hide="maybe", lot_oriented="maybe").replace(
            URL.encode(), b"https://example.com/unsafe"
        )
    )
    assert notice.hide_purchase_raw.value == notice.is_lot_oriented_raw.value == "maybe"
    assert notice.selected_deadline.value is None
    assert notice.attachments[0].url.value is None


def test_accredited_only_flag_and_parser_model_tampering_cannot_restore_positive_fields() -> None:
    notice = parse(
        general_xml().replace(
            b"<p:isLotOriented>",
            b"<p:hidePurchaseCustomerAccredited>true</p:hidePurchaseCustomerAccredited>"
            b"<p:isLotOriented>",
        )
    )
    assert notice.hide_purchase_customer_accredited_raw.value == "true"
    assert notice.attachments[0].url.value is None

    body = notice.model_dump(mode="json")
    body.pop("hide_purchase_raw")
    with pytest.raises(ValueError, match="generic notice extensions"):
        type(notice).model_validate(body)
    body = notice.model_dump(mode="json")
    body["attachments"][0]["url"]["value"] = URL
    with pytest.raises(ValueError, match="restricted attachment URL"):
        type(notice).model_validate(body)
    manifest = notice.model_dump(mode="json")
    manifest["manifest_status"] = "COUNT_CONSISTENT"
    manifest["manifest_additional_count"]["value"] = "1"
    manifest["manifest_additional_count"]["raw"] = "1"
    with pytest.raises(ValueError, match="manifest count"):
        type(notice).model_validate(manifest)
    visible = parse(general_xml()).model_dump(mode="json")
    visible["selected_deadline"] = {
        **visible["selected_deadline"],
        "value": None,
        "status": "UNKNOWN",
    }
    with pytest.raises(ValueError, match="selected deadline"):
        type(notice).model_validate(visible)


def test_invalid_present_commodity_and_unknown_currency_code_block_rub_projection() -> None:
    invalid_commodity = parse(
        general_xml(
            price="<t:initialSum>100.25</t:initialSum><t:commodityPrice>bad</t:commodityPrice>"
        )
    ).lots[0]
    assert invalid_commodity.source_commodity_price_present is True
    assert invalid_commodity.source_commodity_price.value is None
    assert invalid_commodity.initial_sum_rub is None
    forged = parse(
        general_xml(
            price="<t:initialSum>100.25</t:initialSum><t:commodityPrice>bad</t:commodityPrice>"
        )
    ).model_dump(mode="json")
    forged["lots"][0]["source_commodity_price_present"] = False
    forged["lots"][0]["initial_sum_rub"] = "100.25"
    with pytest.raises(ValueError, match="presence flags"):
        type(parse(general_xml())).model_validate(forged)

    unknown_currency = parse(
        general_xml(currency="<t:code>XYZ</t:code>")
    ).lots[0]
    assert unknown_currency.source_currency_status == "UNKNOWN"
    assert unknown_currency.initial_sum_rub is None


def test_runtime_request_and_archive_are_explicitly_bound_to_general_family() -> None:
    request = notice223_request(
        "synthetic-token-123",
        "11111111-1111-4111-8111-111111111111",
        "50",
        date(2026, 10, 1),
        document_type="purchaseNotice",
    )
    assert b"<documentType223>purchaseNotice</documentType223>" in request
    result = inspect_notice223_archive(
        archive(general_xml()),
        company_id="tenant-a",
        source_response_sha256="a" * 64,
        source_locator="synthetic",
        document_type="purchaseNotice",
    )
    assert result.records[0].document_type == "purchaseNotice"
