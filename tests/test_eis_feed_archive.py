"""The whole source window is retained before any user-query filtering."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources.eis_feed_archive import (
    EisArchiveInspection,
    EisFeedArchiveError,
    inspect_eis_auction_archive,
)

_RESPONSE_SHA = "a" * 64


def _notice(number: str, version: int = 1, *, deadline: str = "2026-10-05T10:00:00+03:00") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<export xmlns="http://zakupki.gov.ru/oos/export/1">
  <epNotificationEF2020>
    <versionNumber>{version}</versionNumber>
    <commonInfo>
      <purchaseNumber>{number}</purchaseNumber>
      <purchaseObjectInfo>Поставка бумаги</purchaseObjectInfo>
      <publishDTInEIS>2026-09-25T17:20:00+03:00</publishDTInEIS>
    </commonInfo>
    <notificationInfo>
      <procedureInfo><collectingInfo><endDT>{deadline}</endDT></collectingInfo></procedureInfo>
      <contractConditionsInfo><maxPriceInfo>
        <maxPrice>182420.00</maxPrice><currency><code>RUB</code></currency>
      </maxPriceInfo></contractConditionsInfo>
    </notificationInfo>
  </epNotificationEF2020>
</export>""".encode()


def _archive(*members: tuple[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


def _inspect(content: bytes) -> EisArchiveInspection:
    return inspect_eis_auction_archive(
        content,
        source_locator="getDocsIP/PRIZ/50/2026-09-25/17+03:00",
        source_response_sha256=_RESPONSE_SHA,
    )


def _attachments(count: int, *, duplicate_last_uid: bool = False) -> bytes:
    entries = []
    for index in range(1, count + 1):
        uid_index = 1 if duplicate_last_uid and index == count else index
        uid = f"{uid_index:032X}"
        entries.append(
            f"<attachmentInfo><publishedContentId>{uid}</publishedContentId>"
            f"<fileName>document-{index}.pdf</fileName><fileSize>{index}</fileSize>"
            f"<url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/"
            f"file.html?uid={uid}</url><docKindInfo><code>POD</code></docKindInfo>"
            f"</attachmentInfo>"
        )
    return ("<attachmentsInfo>" + "".join(entries) + "</attachmentsInfo>").encode()


def _notice_with_attachments(number: str, count: int, *, duplicate_last_uid: bool = False) -> bytes:
    return _notice(number).replace(
        b"<notificationInfo>",
        _attachments(count, duplicate_last_uid=duplicate_last_uid) + b"<notificationInfo>",
    )


def numeric_notice(
    number="0848300054826000154",
    *,
    concrete="<concreteValue>30</concreteValue><concreteValue>400</concreteValue>",
) -> bytes:
    source = _notice(number).decode()
    objects = f"""<purchaseObjectsInfo><notDrugPurchaseObjectsInfo><purchaseObject>
    <name>Регулятор</name><quantity><value>1</value></quantity><OKEI><name>Штука</name></OKEI>
    <KTRU><characteristics>
    <characteristicsUsingReferenceInfo><name>Тип</name><values><value><qualityDescription>Электронный</qualityDescription></value></values></characteristicsUsingReferenceInfo>
    <characteristicsUsingTextForm><name>Параметр</name><values><value>
    <OKEI><name>Вольт</name></OKEI><valueSet>{concrete}</valueSet>
    <rangeSet><valueRange><min>-40</min><minMathNotation>greaterOrEqual</minMathNotation>
    <max>0</max><maxMathNotation>lessOrEqual</maxMathNotation></valueRange></rangeSet>
    </value></values></characteristicsUsingTextForm></characteristics></KTRU>
    </purchaseObject></notDrugPurchaseObjectsInfo></purchaseObjectsInfo>"""
    return source.replace("</notificationInfo>", objects + "</notificationInfo>").encode()


def test_concrete_values_signed_zero_order_and_mixed_kind_locators():
    source = numeric_notice(
        concrete="<concreteValue>30</concreteValue><concreteValue>-40.5</concreteValue><concreteValue>0</concreteValue>"
    )
    notice = _inspect(_archive(("numeric.xml", source))).records[0]
    c = notice.lot_items[0].characteristics[1]
    v = c.values[0]
    assert c.locator.endswith("characteristicsUsingTextForm[1]")
    assert v.minimum == -40 and v.maximum == 0
    assert v.minimum_raw == "-40" and v.maximum_raw == "0"
    assert not v.range_source_complete  # Coexisting valueSet makes the source shape mixed.
    assert [x.value for x in v.concrete_values] == [Decimal("30"), Decimal("-40.5"), Decimal("0")]
    assert [x.raw for x in v.concrete_values] == ["30", "-40.5", "0"]
    assert v.concrete_values[2].locator.endswith("/valueSet/concreteValue[3]")


def test_range_source_retains_present_empty_bound():
    replacement = "<min></min>"
    source = (
        numeric_notice(concrete="")
        .replace(b"<valueSet></valueSet>", b"")
        .replace(b"<min>-40</min>", replacement.encode())
    )
    parsed = _inspect(_archive(("range.xml", source))).records[0]
    observed = parsed.lot_items[0].characteristics[1].values[0]
    assert observed.minimum_raw == "" and observed.range_source_complete


@pytest.mark.parametrize(
    "replacement",
    ["<min><nested>500</nested></min>", "<min>500</min><unknown>x</unknown>"],
)
def test_unrecognized_range_structure_is_retained_without_partial_bounds(replacement):
    source = numeric_notice(concrete="").replace(b"<min>-40</min>", replacement.encode())
    observed = (
        _inspect(_archive(("range.xml", source)))
        .records[0]
        .lot_items[0]
        .characteristics[1]
        .values[0]
    )
    assert (
        observed.minimum,
        observed.minimum_operator,
        observed.maximum,
        observed.maximum_operator,
        observed.minimum_raw,
        observed.maximum_raw,
        observed.range_source_complete,
        observed.range_structure_unknown,
    ) == (None, None, None, None, None, None, False, True)


def test_range_source_complete_rejects_bool_coercion_at_snapshot_boundary():
    from pydantic import TypeAdapter, ValidationError

    parsed = _inspect(_archive(("range.xml", numeric_notice(concrete="")))).records[0]
    payload = TypeAdapter(type(parsed)).dump_python(parsed, mode="json")
    payload["lot_items"][0]["characteristics"][1]["values"][0]["range_source_complete"] = 1
    with pytest.raises(ValidationError):
        TypeAdapter(type(parsed)).validate_python(payload)

    payload = TypeAdapter(type(parsed)).dump_python(parsed, mode="json")
    payload["lot_items"][0]["characteristics"][1]["values"][0]["range_structure_unknown"] = 1
    with pytest.raises(ValidationError):
        TypeAdapter(type(parsed)).validate_python(payload)


def test_range_source_rejects_discarded_text_and_does_not_attest_value_set():
    tailed = numeric_notice(concrete="").replace(
        b"</min><minMathNotation>", b"</min> except X <minMathNotation>"
    )
    tailed_value = (
        _inspect(_archive(("range.xml", tailed)))
        .records[0]
        .lot_items[0]
        .characteristics[1]
        .values[0]
    )
    assert tailed_value.minimum is None and tailed_value.minimum_raw is None
    assert not tailed_value.range_source_complete
    assert tailed_value.range_structure_unknown
    mixed = _inspect(_archive(("range.xml", numeric_notice(concrete="")))).records[0]
    assert not mixed.lot_items[0].characteristics[1].values[0].range_source_complete


def authentic_numeric_range(
    *,
    number="0848300054826000154",
    value_format="N",
    metadata="",
    external_sid: str | None = None,
) -> bytes:
    source = numeric_notice(number=number, concrete="").replace(b"<valueSet></valueSet>", b"")
    external = f"<externalSid>{external_sid}</externalSid>" if external_sid is not None else ""
    prefix = (
        f"<sid>426d3d09</sid>{external}<valueFormat>{value_format}</valueFormat>{metadata}"
        "<OKEI><name>Вольт"
    )
    return source.replace(b"<OKEI><name>\xd0\x92\xd0\xbe\xd0\xbb\xd1\x8c\xd1\x82", prefix.encode())


def _replace_range(source: bytes, replacement: str) -> bytes:
    start = source.index(b"<rangeSet>")
    end = source.index(b"</rangeSet>", start) + len(b"</rangeSet>")
    return source[:start] + replacement.encode() + source[end:]


_VALID_RANGE = (
    "<rangeSet><valueRange><min>-40</min>"
    "<minMathNotation>greaterOrEqual</minMathNotation>"
    "<max>0</max><maxMathNotation>lessOrEqual</maxMathNotation>"
    "</valueRange></rangeSet>"
)


@pytest.mark.parametrize(
    "replacement",
    [
        _VALID_RANGE + _VALID_RANGE,
        "<rangeSet></rangeSet>",
        "<rangeSet><valueRange></valueRange></rangeSet>",
        "<rangeSet><valueRange><min>-40</min></valueRange><valueRange><max>0</max></valueRange></rangeSet>",
        '<rangeSet source="x"><valueRange><min>-40</min></valueRange></rangeSet>',
        '<rangeSet><valueRange source="x"><min>-40</min></valueRange></rangeSet>',
        '<rangeSet><valueRange><min source="x">-40</min></valueRange></rangeSet>',
        "<rangeSet><valueRange><min>-40</min><min>-41</min></valueRange></rangeSet>",
        "<rangeSet>mixed<valueRange><min>-40</min></valueRange></rangeSet>",
        "<rangeSet><valueRange><min>-40</min> mixed</valueRange></rangeSet>",
    ],
)
def test_ambiguous_range_shapes_keep_notice_but_discard_all_bounds(replacement):
    source = _replace_range(authentic_numeric_range(), replacement)
    notice = _inspect(_archive(("range.xml", source))).records[0]
    characteristic = notice.lot_items[0].characteristics[1]
    observed = characteristic.values[0]
    assert notice.purchase_number == "0848300054826000154"
    assert notice.title == "Поставка бумаги"
    assert notice.lot_items[0].name == "Регулятор"
    assert characteristic.name == "Параметр"
    assert characteristic.locator.endswith("characteristicsUsingTextForm[1]")
    assert (
        observed.minimum,
        observed.minimum_operator,
        observed.maximum,
        observed.maximum_operator,
        observed.minimum_raw,
        observed.maximum_raw,
        observed.range_source_complete,
        observed.range_structure_unknown,
    ) == (None, None, None, None, None, None, False, True)


def test_well_formed_malformed_numeric_leaf_retains_raw_for_unknown():
    source = authentic_numeric_range().replace(b"<min>-40</min>", b"<min>not-a-number</min>")
    observed = (
        _inspect(_archive(("range.xml", source)))
        .records[0]
        .lot_items[0]
        .characteristics[1]
        .values[0]
    )
    assert observed.minimum is None
    assert observed.minimum_raw == "not-a-number"
    assert observed.minimum_operator == "greaterOrEqual"
    assert observed.range_source_complete
    assert not observed.range_structure_unknown


def test_malformed_range_notice_does_not_drop_valid_neighbor_from_archive():
    bad_number = "0848300054826000154"
    good_number = "0848300054826000155"
    bad = _replace_range(
        authentic_numeric_range(number=bad_number),
        "<rangeSet><valueRange><min>-40</min><min>-41</min></valueRange></rangeSet>",
    )
    result = _inspect(
        _archive(
            ("bad-range.xml", bad),
            ("valid-neighbor.xml", authentic_numeric_range(number=good_number)),
        )
    )
    assert [record.purchase_number for record in result.records] == [bad_number, good_number]
    bad_characteristic = result.records[0].lot_items[0].characteristics[1]
    assert result.records[0].title == "Поставка бумаги"
    assert result.records[0].lot_items[0].name == "Регулятор"
    assert bad_characteristic.name == "Параметр"
    assert bad_characteristic.locator.endswith("characteristicsUsingTextForm[1]")
    assert bad_characteristic.values[0].minimum_raw is None
    assert not bad_characteristic.values[0].range_source_complete
    assert bad_characteristic.values[0].range_structure_unknown
    assert result.records[1].lot_items[0].characteristics[1].values[0].range_source_complete


def test_unknown_range_marker_survives_alongside_description_and_concrete_value():
    source = numeric_notice(concrete="<concreteValue>30</concreteValue>").replace(
        b"<OKEI><name>\xd0\x92\xd0\xbe\xd0\xbb\xd1\x8c\xd1\x82</name></OKEI>",
        b"<qualityDescription>explicit description</qualityDescription>"
        b"<OKEI><name>\xd0\x92\xd0\xbe\xd0\xbb\xd1\x8c\xd1\x82</name></OKEI>",
    )
    source = source.replace(b"<min>-40</min>", b"<min>-40</min><min>-41</min>")
    observed = (
        _inspect(_archive(("range.xml", source)))
        .records[0]
        .lot_items[0]
        .characteristics[1]
        .values[0]
    )
    assert observed.quality_description == "explicit description"
    assert [fact.value for fact in observed.concrete_values] == [Decimal("30")]
    assert observed.minimum_raw is None and observed.maximum_raw is None
    assert observed.range_structure_unknown


def test_authentic_sid_and_numeric_value_format_are_complete():
    parsed = _inspect(_archive(("range.xml", authentic_numeric_range()))).records[0]
    observed = parsed.lot_items[0].characteristics[1].values[0]
    assert observed.range_source_complete


def test_optional_external_sid_scalar_is_complete_without_uuid_assumption():
    parsed = _inspect(
        _archive(("range.xml", authentic_numeric_range(external_sid="catalog-item-42")))
    ).records[0]
    assert parsed.lot_items[0].characteristics[1].values[0].range_source_complete


@pytest.mark.parametrize(
    "external",
    [
        "<externalSid></externalSid>",
        "<externalSid><nested>catalog-item-42</nested></externalSid>",
        '<externalSid source="x">catalog-item-42</externalSid>',
        "<externalSid>one</externalSid><externalSid>two</externalSid>",
        "<externalSid>catalog-item-42</externalSid> mixed text ",
    ],
)
def test_malformed_external_sid_never_attests_range(external):
    source = authentic_numeric_range().replace(
        b"<valueFormat>N</valueFormat>",
        external.encode() + b"<valueFormat>N</valueFormat>",
    )
    parsed = _inspect(_archive(("range.xml", source))).records[0]
    assert not parsed.lot_items[0].characteristics[1].values[0].range_source_complete


@pytest.mark.parametrize(
    "source",
    [
        authentic_numeric_range(value_format="Q"),
        authentic_numeric_range(value_format=""),
        authentic_numeric_range(value_format="<nested>N</nested>"),
        authentic_numeric_range(metadata="<qualityDescription></qualityDescription>"),
        authentic_numeric_range(metadata="<unknown>x</unknown>"),
    ],
)
def test_non_numeric_or_malformed_outer_value_shape_is_incomplete(source):
    parsed = _inspect(_archive(("range.xml", source))).records[0]
    assert not parsed.lot_items[0].characteristics[1].values[0].range_source_complete


def test_significant_range_set_tail_is_incomplete():
    source = authentic_numeric_range().replace(b"</rangeSet>", b"</rangeSet> except X")
    parsed = _inspect(_archive(("range.xml", source))).records[0]
    assert not parsed.lot_items[0].characteristics[1].values[0].range_source_complete


@pytest.mark.parametrize("raw", ["", "NaN", "Infinity", "не указано", "1e999", "x" * 450])
def test_bad_concrete_value_keeps_raw_unknown_without_changing_money_parser(raw):
    source = numeric_notice(concrete=f"<concreteValue>{raw}</concreteValue>")
    n = _inspect(_archive(("numeric.xml", source))).records[0]
    value = n.lot_items[0].characteristics[1].values[0].concrete_values[0]
    assert value.value is None and value.raw == raw
    assert n.nmck_rub == Decimal("182420.00")


def test_duplicate_concrete_container_rejects_ambiguity():
    source = numeric_notice().replace(
        b"</valueSet>", b"</valueSet><valueSet><concreteValue>500</concreteValue></valueSet>"
    )
    with pytest.raises(EisFeedArchiveError, match="FIELD_DUPLICATE"):
        _inspect(_archive(("numeric.xml", source)))


def test_inspects_all_notices_without_query_filter() -> None:
    first = "0848300054826000154"
    second = "0848300064126000341"
    result = _inspect(_archive(("first.xml", _notice(first)), ("second.xml", _notice(second, 2))))
    assert [record.purchase_number for record in result.records] == [first, second]
    assert [record.version_number for record in result.records] == [1, 2]
    assert result.records[0].nmck_rub == 182420
    assert result.records[0].deadline is not None
    assert result.records[0].deadline.utcoffset().total_seconds() == 10800
    assert result.records[0].xml_sha256 != result.records[1].xml_sha256
    assert result.source_response_sha256 == _RESPONSE_SHA
    assert result.corpus_coverage == "UNKNOWN"


def test_missing_timezone_is_not_inferred() -> None:
    result = _inspect(
        _archive(("notice.xml", _notice("0848300054826000154", deadline="2026-10-05T10:00:00")))
    )
    assert result.records[0].deadline is None


def test_explicit_quotation_shape_preserves_evidence_and_versions() -> None:
    content = _notice("0303300031426000056").replace(
        b"epNotificationEF2020", b"epNotificationEZK2020"
    )
    result = inspect_eis_auction_archive(
        _archive(("quotation.xml", content)),
        source_locator="getDocsIP/PRIZ/50/2026-09-25+03:00/epNotificationEZK2020",
        source_response_sha256=_RESPONSE_SHA,
        expected_document_type="epNotificationEZK2020",
    )
    notice = result.records[0]
    assert notice.document_type == "epNotificationEZK2020"
    assert notice.version_number == 1 and notice.nmck_rub == 182420
    assert notice.deadline is not None
    with pytest.raises(EisFeedArchiveError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        _inspect(_archive(("quotation.xml", content)))


def test_competition_uses_direct_common_fields_and_never_infers_timezone() -> None:
    source = _notice("0848300054826000154", 4).replace(
        b"epNotificationEF2020", b"epNotificationEOK2020"
    )
    source = source.replace(
        b"</notificationInfo>",
        b"<criteriaInfo><criterionInfo>"
        b"<purchaseNumber>nested-unrelated</purchaseNumber><versionNumber>99</versionNumber>"
        b"</criterionInfo></criteriaInfo></notificationInfo>",
    )
    result = inspect_eis_auction_archive(
        _archive(("competition.xml", source)),
        source_locator="getDocsIP/PRIZ/50/2026-10-01+03:00/epNotificationEOK2020",
        source_response_sha256=_RESPONSE_SHA,
        expected_document_type="epNotificationEOK2020",
    )
    notice = result.records[0]
    assert notice.purchase_number == "0848300054826000154" and notice.version_number == 4
    assert notice.document_type == "epNotificationEOK2020"
    assert notice.nmck_rub == Decimal("182420.00") and notice.deadline.utcoffset() is not None
    assert result.corpus_coverage == "UNKNOWN"
    with pytest.raises(EisFeedArchiveError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        _inspect(_archive(("competition.xml", source)))
    naive = source.replace(b"2026-10-05T10:00:00+03:00", b"2026-10-05T10:00:00")
    assert (
        inspect_eis_auction_archive(
            _archive(("competition.xml", naive)),
            source_locator="synthetic",
            source_response_sha256=_RESPONSE_SHA,
            expected_document_type="epNotificationEOK2020",
        )
        .records[0]
        .deadline
        is None
    )


def test_large_official_sized_xml_remains_bounded_and_readable() -> None:
    source = _notice("0848300054826000154")
    source = source.replace(b"</export>", b"<!--" + b"x" * (25 * 1024 * 1024) + b"--></export>")
    result = _inspect(_archive(("notice.xml", source)))
    assert result.records[0].purchase_number == "0848300054826000154"


def test_xml_above_member_limit_rejects_the_whole_archive() -> None:
    source = _notice("0848300054826000154")
    oversized = source.replace(b"</export>", b"<!--" + b"x" * (33 * 1024 * 1024) + b"--></export>")
    content = _archive(("first.xml", source), ("oversized.xml", oversized))
    with pytest.raises(EisFeedArchiveError, match="MEMBER_UNSUPPORTED"):
        _inspect(content)


def test_extracts_official_attachment_and_exact_lot_item() -> None:
    uid = "A" * 32
    xml = f"""<export xmlns="http://zakupki.gov.ru/oos/export/1">
<epNotificationEF2020><versionNumber>1</versionNumber>
<commonInfo><purchaseNumber>0848300054826000154</purchaseNumber>
<purchaseObjectInfo>Поставка бумаги</purchaseObjectInfo></commonInfo>
<attachmentsInfo><attachmentInfo>
<publishedContentId>{uid}</publishedContentId><fileName>Спецификация.docx</fileName>
<fileSize>28281</fileSize>
<url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid={uid}</url>
<docKindInfo><code>POD</code></docKindInfo>
</attachmentInfo></attachmentsInfo>
<notificationInfo><purchaseObjectsInfo><notDrugPurchaseObjectsInfo>
<purchaseObject><KTRU><code>17.12.14.110-00000004</code>
<OKPD2><OKPDCode>17.12.14.119</OKPDCode></OKPD2>
<characteristics><characteristicsUsingReferenceInfo><name>Листов в пачке</name>
<values><value><OKEI><name>Штука</name></OKEI><rangeSet><valueRange>
<minMathNotation>greaterOrEqual</minMathNotation><min>500</min>
</valueRange></rangeSet></value></values>
<characteristicsFillingInstruction><code>2</code></characteristicsFillingInstruction>
</characteristicsUsingReferenceInfo></characteristics></KTRU>
<name>Бумага для офисной техники</name><OKEI><name>Пачка</name></OKEI>
<quantity><value>500</value></quantity><price>364.84</price><sum>182420.00</sum>
<restrictionsInfo><isProhibitionForeignPurchaseObjects>true</isProhibitionForeignPurchaseObjects></restrictionsInfo>
</purchaseObject></notDrugPurchaseObjectsInfo></purchaseObjectsInfo></notificationInfo>
</epNotificationEF2020></export>""".encode()
    notice = _inspect(_archive(("notice.xml", xml))).records[0]
    assert len(notice.attachments) == 1
    assert notice.attachments[0].kind_code == "POD"
    assert notice.attachments[0].byte_count == 28281
    assert notice.lot_parse_status == "PARSED"
    assert notice.lot_items[0].quantity == 500
    assert notice.lot_items[0].unit_price_rub == Decimal("364.84")
    assert notice.lot_items[0].line_sum_rub == 182420
    assert notice.lot_items[0].foreign_goods_prohibited is True
    characteristic = notice.lot_items[0].characteristics[0]
    assert characteristic.name == "Листов в пачке"
    assert characteristic.filling_instruction_code == "2"
    assert characteristic.values[0].minimum == 500
    assert characteristic.values[0].minimum_operator == "greaterOrEqual"
    assert characteristic.values[0].unit == "Штука"
    assert characteristic.values[0].minimum_raw == "500"
    assert characteristic.values[0].range_source_complete


def test_rejects_attachment_uid_url_mismatch() -> None:
    source = _notice("0848300054826000154")
    bad = source.replace(
        b"<notificationInfo>",
        b"<attachmentsInfo><attachmentInfo><publishedContentId>"
        + b"A" * 32
        + b"</publishedContentId><fileName>Spec.docx</fileName><fileSize>1</fileSize>"
        + b"<url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid="
        + b"B" * 32
        + b"</url></attachmentInfo></attachmentsInfo><notificationInfo>",
    )
    with pytest.raises(EisFeedArchiveError, match="ATTACHMENT_REFERENCE_INVALID"):
        _inspect(_archive(("notice.xml", bad)))


@pytest.mark.parametrize("name_length", [300, 1024, 1025])
def test_attachment_filename_bound_is_independent_of_filesystem_limit(name_length: int) -> None:
    uid = "A" * 32
    filename = "X" * (name_length - len(".docx")) + ".docx"
    source = _notice("0848300054826000154")
    xml = source.replace(
        b"<notificationInfo>",
        (
            f"<attachmentsInfo><attachmentInfo><publishedContentId>{uid}</publishedContentId>"
            f"<fileName>{filename}</fileName><fileSize>1</fileSize>"
            f"<url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/"
            f"file.html?uid={uid}</url></attachmentInfo></attachmentsInfo>"
            "<notificationInfo>"
        ).encode(),
    )
    if name_length > 1024:
        with pytest.raises(EisFeedArchiveError, match="ATTACHMENT_REFERENCE_INVALID"):
            _inspect(_archive(("notice.xml", xml)))
    else:
        notice = _inspect(_archive(("notice.xml", xml))).records[0]
        assert notice.attachments[0].filename == filename


def test_more_than_one_hundred_attachment_metadata_entries_preserve_the_full_day() -> None:
    crowded_number = "0848300054826000154"
    ordinary_number = "0848300064126000341"
    result = _inspect(
        _archive(
            ("crowded.xml", _notice_with_attachments(crowded_number, 101)),
            ("ordinary.xml", _notice(ordinary_number)),
        )
    )

    assert [record.purchase_number for record in result.records] == [
        crowded_number,
        ordinary_number,
    ]
    crowded = result.records[0]
    assert len(crowded.attachments) == 101
    assert crowded.attachments[0].content_uid == f"{1:032X}"
    assert crowded.attachments[-1].content_uid == f"{101:032X}"
    assert crowded.attachments[-1].locator.endswith("attachmentInfo[101]")
    assert result.source_response_sha256 == _RESPONSE_SHA
    assert result.corpus_coverage == "UNKNOWN"


def test_attachment_metadata_ceiling_is_inclusive() -> None:
    notice = _inspect(
        _archive(
            (
                "boundary.xml",
                _notice_with_attachments("0848300054826000154", 4096),
            )
        )
    ).records[0]

    assert len(notice.attachments) == 4096
    assert notice.attachments[-1].content_uid == f"{4096:032X}"
    assert notice.attachments[-1].locator.endswith("attachmentInfo[4096]")


def test_attachment_metadata_above_ceiling_rejects_the_whole_day() -> None:
    content = _archive(
        ("ordinary.xml", _notice("0848300064126000341")),
        (
            "over-limit.xml",
            _notice_with_attachments("0848300054826000154", 4097),
        ),
    )

    with pytest.raises(EisFeedArchiveError, match="ATTACHMENT_METADATA_COUNT_LIMIT"):
        _inspect(content)


def test_duplicate_attachment_uid_after_the_old_limit_remains_invalid() -> None:
    source = _notice_with_attachments("0848300054826000154", 101, duplicate_last_uid=True)

    with pytest.raises(EisFeedArchiveError, match="ATTACHMENT_REFERENCE_INVALID"):
        _inspect(_archive(("duplicate.xml", source)))


@pytest.mark.parametrize(
    ("members", "reason"),
    [
        (
            (("a.xml", _notice("0848300054826000154")), ("b.xml", _notice("0848300054826000154"))),
            "DUPLICATE_NOTICE_VERSION",
        ),
        ((("../notice.xml", _notice("0848300054826000154")),), "MEMBER_UNSUPPORTED"),
        ((("notice.xml", b"<export/>"),), "EXPORT_ENVELOPE_INVALID"),
        ((("notice.xml", b"<!DOCTYPE export><export/>"),), "XML_UNSAFE"),
    ],
)
def test_rejects_incomplete_or_unsafe_windows(
    members: tuple[tuple[str, bytes], ...], reason: str
) -> None:
    with pytest.raises(EisFeedArchiveError, match=reason):
        _inspect(_archive(*members))


def test_preserves_forward_slash_source_label_with_exact_provenance() -> None:
    raw = _notice_with_attachments("0848300054826000154", 1).replace(
        b"document-1.pdf", "Часть 1/2.pdf".encode()
    )
    notice = _inspect(_archive(("notice.xml", raw))).records[0]
    assert notice.attachments[0].filename == "Часть 1/2.pdf"
    assert notice.attachments[0].locator.endswith("attachmentInfo[1]")
    assert notice.attachments[0].content_uid == f"{1:032X}"
    assert notice.attachments[0].url.endswith(f"uid={1:032X}")


def test_backslash_in_source_label_still_rejects_whole_archive() -> None:
    raw = _notice_with_attachments("0848300054826000154", 1).replace(
        b"document-1.pdf", b"part\\document.pdf"
    )
    with pytest.raises(EisFeedArchiveError, match="ATTACHMENT_REFERENCE_INVALID"):
        _inspect(_archive(("notice.xml", raw)))
