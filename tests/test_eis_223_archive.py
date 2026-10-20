"""Synthetic contracts only; real 223 XML bytes stay on the VPS."""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from procurement.sources.eis_223_archive import (
    DOCUMENT_TYPE,
    PURCHASE_NS,
    Eis223ContractError,
    Eis223NoticeSnapshot,
    inspect_notice223_archive,
    notice223_request,
    parse_notice223_xml,
)

UID = "A" * 32
URL = "https://zakupki.gov.ru/223/filestore/public/1.0/download/fz223/file.html?uid=" + UID


def test_quotation_family_is_explicit_and_all_fact_paths_follow_its_data():
    family = "purchaseNoticeZKESMBO"
    raw = xml().replace(b"purchaseNoticeAESMBO", family.encode())
    notice = parse_notice223_xml(raw, source_member="quotation.xml", document_type=family)
    assert notice.document_type == family and notice.deadline.value is None
    assert notice.title.provenance.locator.startswith(family + "/")
    assert notice.deadline.provenance.locator.endswith(f"p:{family}Data/p:submissionCloseDateTime")
    assert notice.lots[0].items[0].description.provenance.locator.startswith(family + "/")
    parsed = inspect_notice223_archive(
        zip_bytes([("quotation.xml", raw)]),
        company_id="tenant-a",
        source_response_sha256="b" * 64,
        source_locator="synthetic",
        document_type=family,
    )
    assert parsed.records == (notice,)
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        parse_notice223_xml(raw, source_member="quotation.xml")
    with pytest.raises(ValueError, match="selected source family"):
        Eis223NoticeSnapshot.model_validate({**notice.model_dump(), "document_type": DOCUMENT_TYPE})


def test_generic_other_method_requires_its_explicit_family_selection():
    raw = xml().replace(b"purchaseNoticeAESMBO", b"purchaseNotice")
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        parse_notice223_xml(raw, source_member="other.xml")
    assert (
        parse_notice223_xml(raw, source_member="other.xml", document_type="purchaseNotice")
        .document_type
        == "purchaseNotice"
    )


def xml(
    *,
    deadline="2026-10-09T08:00:00",
    amount="100.25",
    code="RUB",
    numeric="643",
    extra="",
    second_lot="",
):
    return f'''<p:purchaseNoticeAESMBO xmlns:p="{PURCHASE_NS}" xmlns:t="http://zakupki.gov.ru/223fz/types/1">
      <t:header><t:guid>synthetic</t:guid></t:header><p:body><p:item><p:purchaseNoticeAESMBOData>
      <p:registrationNumber>32600000001</p:registrationNumber><p:version>2</p:version>
      <p:name>Поставка бумаги</p:name>{extra}<p:status>P</p:status>
      <p:publicationDateTime>2026-10-01T09:00:00Z</p:publicationDateTime>
      <p:submissionCloseDateTime>{deadline}</p:submissionCloseDateTime>
      <p:customer><t:mainInfo><t:timeZone><t:offset>0</t:offset></t:timeZone></t:mainInfo></p:customer>
      <p:attachments><t:totalDocumentsCount>1</t:totalDocumentsCount><t:document>
      <t:fileName>ТЗ.docx</t:fileName><t:contentUid>{UID}</t:contentUid><t:url>{URL}</t:url>
      </t:document></p:attachments>
      <p:lots><t:lot><t:ordinalNumber>1</t:ordinalNumber><t:cancelled>false</t:cancelled>
      <t:lotData><t:subject>Бумага для печати</t:subject><t:currency><t:code>{code}</t:code>
      <t:digitalCode>{numeric}</t:digitalCode></t:currency><t:initialSum>{amount}</t:initialSum>
      <t:lotItems><t:lotItem><t:okpd2><t:code>17.12.14</t:code><t:name>Бумага</t:name></t:okpd2>
      <t:qty>10</t:qty><t:okei><t:code>796</t:code><t:name>Штука</t:name></t:okei>
      <t:additionalInfo>Бумага А4 80</t:additionalInfo></t:lotItem></t:lotItems>
      </t:lotData></t:lot>{second_lot}</p:lots>
      </p:purchaseNoticeAESMBOData></p:item></p:body></p:purchaseNoticeAESMBO>'''.encode()


def zip_bytes(entries):
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


def inspect(raw):
    return inspect_notice223_archive(
        raw,
        company_id="tenant-a",
        source_response_sha256="b" * 64,
        source_locator="getDocsIP/RI223/50/2026-10-01+03:00/purchaseNoticeAESMBO",
    )


def test_request_uses_223_branch_without_44_or_policy_overrides():
    raw = notice223_request(
        "synthetic-token-123", "11111111-1111-4111-8111-111111111111", "50", date(2026, 10, 1)
    )
    root = ET.fromstring(raw)
    params = next(e for e in root.iter() if e.tag == "selectionParams")
    assert params.findtext("subsystemType") == "RI223"
    assert params.findtext("documentType223") == DOCUMENT_TYPE
    assert params.find("documentType44") is None
    assert params.findtext("periodInfo/exactDate") == "2026-10-01+03:00"


def test_exact_metadata_has_separate_law_lots_currency_and_unknown_admission():
    raw = xml()
    result = inspect(zip_bytes([("synthetic.xml", raw)]))
    notice = result.records[0]
    assert (
        notice.law == "223"
        and notice.purchase_number == "32600000001"
        and notice.version_number == 2
    )
    assert notice.xml_sha256 == hashlib.sha256(raw).hexdigest()
    assert notice.deadline.value is None and notice.deadline.raw == "2026-10-09T08:00:00"
    assert notice.deadline.status == "UNKNOWN" and notice.customer_timezone_offset_raw.value == "0"
    assert notice.publication.value == datetime.fromisoformat("2026-10-01T09:00:00+00:00")
    assert notice.lots[0].initial_sum_rub == Decimal("100.25")
    assert notice.lots[0].items[0].quantity.value == Decimal("10")
    assert notice.lots[0].items[0].description.value == "Бумага А4 80"
    assert notice.attachments[0].url.value == URL and notice.manifest_status == "COUNT_CONSISTENT"
    assert (
        notice.application_status
        == notice.economics_status
        == notice.lot_review_status
        == "UNKNOWN"
    )
    assert result.corpus_coverage == "UNKNOWN"
    assert Eis223NoticeSnapshot.model_validate_json(notice.model_dump_json()) == notice


def test_lot_prices_are_not_summed_or_flattened():
    second = (
        "<t:lot><t:ordinalNumber>2</t:ordinalNumber><t:lotData><t:subject>Сервер</t:subject>"
        "<t:currency><t:code>USD</t:code><t:digitalCode>840</t:digitalCode></t:currency>"
        "<t:initialSum>500</t:initialSum></t:lotData></t:lot>"
    )
    n = parse_notice223_xml(xml(second_lot=second), source_member="synthetic.xml")
    assert len(n.lots) == 2 and n.lots[1].initial_sum_rub is None
    assert n.lots[1].initial_sum.value == Decimal("500") and n.lots[0].initial_sum_rub == Decimal(
        "100.25"
    )
    assert n.lots[0].provenance.locator != n.lots[1].provenance.locator


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1,5", "1e3", ""])
def test_invalid_money_is_unknown_with_literal_source(amount):
    n = parse_notice223_xml(xml(amount=amount), source_member="synthetic.xml")
    assert n.lots[0].initial_sum.value is None and n.lots[0].initial_sum_rub is None
    assert n.lots[0].initial_sum.raw == (amount or None)


@pytest.mark.parametrize("code,numeric", [("USD", "840"), ("RUB", "840"), ("", "643")])
def test_currency_conflict_or_missing_code_never_becomes_rubles(code, numeric):
    n = parse_notice223_xml(xml(code=code, numeric=numeric), source_member="synthetic.xml")
    assert n.lots[0].initial_sum_rub is None


@pytest.mark.parametrize("deadline", ["", "2026-10-09", "garbage", "2026-10-09T08:00:00"])
def test_missing_or_naive_deadline_remains_unknown(deadline):
    assert (
        parse_notice223_xml(xml(deadline=deadline), source_member="s.xml").deadline.status
        == "UNKNOWN"
    )


def test_aware_deadline_is_retained_without_changing_zone():
    n = parse_notice223_xml(xml(deadline="2026-10-09T08:00:00+05:00"), source_member="s.xml")
    assert n.deadline.value == datetime.fromisoformat("2026-10-09T08:00:00+05:00")


def test_nested_identity_cannot_overwrite_direct_version():
    n = parse_notice223_xml(
        xml(
            extra="<p:extra><p:registrationNumber>32600000099</p:registrationNumber><p:version>9</p:version></p:extra>"
        ),
        source_member="s.xml",
    )
    assert n.purchase_number == "32600000001" and n.version_number == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.replace(
            b"<p:version>2</p:version>", b"<p:version>2</p:version><p:version>3</p:version>"
        ),
        lambda b: b.replace(b"<p:version>2</p:version>", b"<t:version>2</t:version>"),
        lambda b: b.replace(b"32600000001", b"9000000000000000001"),
        lambda b: b.replace(b"purchaseNoticeAESMBO", b"purchaseNoticeKESMBO"),
        lambda b: b.replace(b"<p:name>", b"<p:name><p:child/>"),
        lambda b: b'<!DOCTYPE root [<!ENTITY x "danger">]>' + b,
        lambda b: b"\x00" + b,
    ],
)
def test_identity_namespace_nested_scalar_and_xml_attacks_rejected(mutation):
    with pytest.raises(Eis223ContractError):
        parse_notice223_xml(mutation(xml()), source_member="s.xml")


@pytest.mark.parametrize(
    "name", ["../s.xml", "/s.xml", "C:s.xml", "folder\\s.xml", "s.txt", "folder/s.xml"]
)
def test_archive_paths_are_rejected(name):
    with pytest.raises(Eis223ContractError):
        inspect(zip_bytes([(name, xml())]))


def test_symlink_and_duplicate_notice_versions_rejected():
    info = ZipInfo("s.xml")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with pytest.raises(Eis223ContractError):
        inspect(zip_bytes([(info, xml())]))
    with pytest.raises(Eis223ContractError, match="NOTICE_VERSION_DUPLICATE"):
        inspect(zip_bytes([("a.xml", xml()), ("b.xml", xml())]))


def test_unsafe_attachment_url_and_manifest_mismatch_do_not_approve_downloads():
    n = parse_notice223_xml(
        xml()
        .replace(URL.encode(), b"https://example.com/steal")
        .replace(b"<t:totalDocumentsCount>1", b"<t:totalDocumentsCount>2"),
        source_member="s.xml",
    )
    assert (
        n.attachments[0].url.value is None
        and n.attachments[0].url.raw == "https://example.com/steal"
    )
    assert n.manifest_status == "UNKNOWN"


def test_tampered_fact_sha_or_float_money_rejected_on_model_load():
    n = parse_notice223_xml(xml(), source_member="s.xml")
    body = n.model_dump(mode="json")
    body["title"]["provenance"]["document_id"] = "c" * 64
    with pytest.raises(ValueError, match="exact XML"):
        Eis223NoticeSnapshot.model_validate(body)
    body = n.model_dump(mode="json")
    body["lots"][0]["initial_sum"]["value"] = 1.5
    with pytest.raises(ValueError, match="float"):
        Eis223NoticeSnapshot.model_validate(body)


def test_legacy_snapshot_without_generic_extension_fields_keeps_old_price_semantics():
    notice = parse_notice223_xml(xml(), source_member="legacy.xml")
    body = notice.model_dump(mode="json")
    for field in (
        "purchase_guid",
        "hide_purchase_raw",
        "hide_purchase_customer_accredited_raw",
        "for_small_or_middle_raw",
        "is_lot_oriented_raw",
        "selected_deadline",
        "manifest_additional_count",
        "manifest_references",
    ):
        body.pop(field)
    for field in (
        "guid",
        "detail_status",
        "source_price_kind",
        "source_amount",
        "source_rub_equivalent",
        "source_price_text",
        "source_price_formula",
        "source_price_formula_present",
        "source_commodity_price",
        "source_commodity_price_present",
        "currency_letter_code",
        "source_currency_status",
        "for_small_or_middle_raw",
    ):
        body["lots"][0].pop(field)
    body["attachments"][0].pop("not_placement_raw")

    restored = Eis223NoticeSnapshot.model_validate(body)
    assert restored.lots[0].initial_sum_rub == Decimal("100.25")
    assert restored.lots[0].source_price_kind is None
    assert restored.selected_deadline is None and restored.manifest_references == ()


def test_malformed_url_is_unknown_and_does_not_activate_external_content():
    raw = xml().replace(URL.encode(), b"https://[malformed")
    assert parse_notice223_xml(raw, source_member="s.xml").attachments[0].url.value is None


def test_rub_projection_and_nested_float_cannot_be_forged():
    n = parse_notice223_xml(xml(code="USD", numeric="840"), source_member="s.xml")
    body = n.model_dump(mode="json")
    body["lots"][0]["initial_sum_rub"] = "100.25"
    with pytest.raises(ValueError, match="consistent source currency"):
        Eis223NoticeSnapshot.model_validate(body)
    body["lots"][0]["initial_sum_rub"] = 100.25
    with pytest.raises(ValueError, match="float"):
        Eis223NoticeSnapshot.model_validate(body)
