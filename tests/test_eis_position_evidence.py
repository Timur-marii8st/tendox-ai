"""Source overlaps never become product equivalence, reviewed requirements or profit."""

from dataclasses import replace
from decimal import Decimal
from io import BytesIO

import pytest
from docx import Document
from pydantic import ValidationError

from procurement.sources.eis_223_archive import DecimalFact, parse_notice223_xml
from procurement.sources.eis_analysis import analyze_document
from procurement.sources.eis_feed_archive import (
    EisCharacteristic,
    EisCharacteristicValue,
    EisLotItem,
    EisNoticeSnapshot,
)
from procurement.sources.eis_position_evidence import (
    CharacteristicValueEvidence,
    PositionEvidenceSet,
    native_table_leads,
    position_links,
    positions44,
    positions223,
)
from test_eis_223_archive import xml


def test_concrete_evidence_signed_facts_differences_and_bounds():
    from procurement.sources.eis_feed_archive import EisConcreteValue
    from procurement.sources.eis_position_evidence import CharacteristicNumberFact

    n = notice44()
    c = n.lot_items[0].characteristics[0]
    value = replace(
        c.values[0],
        minimum=Decimal("-40"),
        maximum=Decimal("0"),
        concrete_values=tuple(
            EisConcreteValue(Decimal(i), str(i), f"valueSet/concreteValue[{i + 1}]")
            for i in range(9)
        ),
    )

    def source(v):
        return replace(
            n, lot_items=(replace(n.lot_items[0], characteristics=(replace(c, values=(v,)),)),)
        )

    p = positions44(source(value))
    v = p.positions[0].characteristics[0].values[0]
    assert v.minimum.value == -40 and v.maximum.value == 0
    assert (
        v.concrete_values_total == 9 and v.concrete_values_truncated and len(v.concrete_values) == 8
    )
    assert v.concrete_values[0].value == 0 and v.concrete_values[0].raw == "0"
    assert v.concrete_values[0].provenance.document_id == p.notice_xml_sha256
    changed = replace(value, concrete_values=(EisConcreteValue(Decimal("400"), "400", "value[1]"),))
    links, _ = position_links((p, positions44(source(changed))))
    assert "SOURCE_CHARACTERISTIC_VALUES_DIFFER" in links[0].differences
    assert "SOURCE_PREVIEW_TRUNCATED" in links[0].differences
    for bad in (1.5, True, "NaN", "Infinity"):
        with pytest.raises(ValidationError):
            CharacteristicNumberFact(value=bad, raw=None, provenance=v.minimum.provenance)
    with pytest.raises(ValidationError):
        DecimalFact(value=Decimal("-40"), raw=None, provenance=v.minimum.provenance)


def test_ambiguous_range_invalidates_only_its_position_without_discarding_other_facts():
    n = notice44()
    item = n.lot_items[0]
    characteristic = item.characteristics[0]
    ambiguous = replace(characteristic.values[0], range_structure_unknown=True)
    changed = replace(item, characteristics=(replace(characteristic, values=(ambiguous,)),))
    result = positions44(replace(n, lot_items=(changed, item)))
    assert result.positions[0].characteristics_status == "UNKNOWN"
    assert result.positions[1].characteristics_status == "SOURCE_VALUES"
    assert result.positions[0].name == result.positions[1].name
    assert result.positions[0].quantity == result.positions[1].quantity
    assert (
        result.positions[0].characteristics[0].values[0].description.value
        == ambiguous.quality_description
    )
    assert all(p.review_status == "UNKNOWN" for p in result.positions)


def test_invalid_concrete_raw_is_bounded_and_old_snapshot_defaults_unknown():
    from pydantic import TypeAdapter

    from procurement.sources.eis_feed_archive import EisConcreteValue

    n = notice44()
    c = n.lot_items[0].characteristics[0]
    v = replace(c.values[0], concrete_values=(EisConcreteValue(None, "x" * 450, "value[1]"),))
    p = positions44(
        replace(n, lot_items=(replace(n.lot_items[0], characteristics=(replace(c, values=(v,)),)),))
    )
    fact = p.positions[0].characteristics[0].values[0].concrete_values[0]
    assert fact.value is None and len(fact.raw) == 400 and fact.raw_truncated
    old = TypeAdapter(EisNoticeSnapshot).dump_python(n, mode="json")
    del old["lot_items"][0]["characteristics"][0]["values"][0]["concrete_values"]
    restored = TypeAdapter(EisNoticeSnapshot).validate_python(old)
    assert restored.lot_items[0].characteristics[0].values[0].concrete_values == ()


def notice44(*, quantity="2", unit="Штука", minimum="500"):
    value = EisCharacteristicValue(
        None,
        Decimal(minimum),
        "greaterOrEqual",
        None,
        None,
        "Штука",
        "objects/item[1]/KTRU/characteristics[1]/value[1]",
    )
    characteristic = EisCharacteristic(
        "Листов в пачке", "source", "2", (value,), "objects/item[1]/KTRU/characteristics[1]"
    )
    item = EisLotItem(
        "Бумага А4",
        "17.12.14.110-00000001",
        "17.12.14.110",
        Decimal(quantity),
        unit,
        Decimal("120.25"),
        Decimal("240.50"),
        None,
        "objects/item[1]",
        (characteristic,),
    )
    return EisNoticeSnapshot(
        "0" * 19,
        "epNotificationEF2020",
        1,
        "Бумага",
        None,
        None,
        Decimal("240.50"),
        "a" * 64,
        "notice.xml",
        (),
        (item,),
        "PARSED",
    )


def test_xml_positions_preserve_exact_range_operator_money_and_provenance():
    notice = notice44()
    characteristic = notice.lot_items[0].characteristics[0]
    ranged = replace(characteristic.values[0], minimum_raw="500", range_source_complete=True)
    notice = replace(
        notice,
        lot_items=(
            replace(
                notice.lot_items[0],
                characteristics=(replace(characteristic, values=(ranged,)),),
            ),
        ),
    )
    result = positions44(notice)
    p = result.positions[0]
    assert p.unit_price.value == Decimal("120.25")
    assert p.currency.value == "RUB" and p.review_status == "UNKNOWN"
    value = p.characteristics[0].values[0]
    assert value.minimum.value == 500 and value.minimum_operator.value == "greaterOrEqual"
    assert value.minimum.raw == "500" and value.range_source_complete
    assert value.maximum.value is None and value.unit.value == "Штука"
    assert value.minimum.provenance.document_id == result.notice_xml_sha256
    assert "notice.xml ::" in value.minimum.provenance.locator
    assert result.specification_completeness == "UNKNOWN"
    assert PositionEvidenceSet.model_validate(result.model_dump(mode="json")) == result


def test_range_source_complete_is_a_strict_boolean():
    result = positions44(notice44())
    payload = result.positions[0].characteristics[0].values[0].model_dump()
    payload["range_source_complete"] = 1
    with pytest.raises(ValidationError):
        CharacteristicValueEvidence.model_validate(payload)


@pytest.mark.parametrize("code,numeric", [("USD", "840"), ("RUB", "643")])
def test_223_lot_price_never_invents_item_price_or_characteristics(code, numeric):
    n = parse_notice223_xml(xml(code=code, numeric=numeric), source_member="223.xml")
    result = positions223(n)
    p = result.positions[0]
    assert p.lot_index == 1 and p.lot_ordinal == n.lots[0].ordinal
    assert p.currency.value == code
    assert p.unit_price.value is p.line_sum.value is None
    assert p.characteristics_status == "UNKNOWN"
    assert p.quantity == n.lots[0].items[0].quantity


def test_223_multiple_lots_keep_source_indexes_and_currency_separate():
    n = parse_notice223_xml(xml(), source_member="223.xml")
    n = n.model_copy(update={"lots": (n.lots[0], n.lots[0])})
    result = positions223(n)
    assert [p.lot_index for p in result.positions] == [1, 2]
    assert [p.source_index for p in result.positions] == [1, 2]


def test_no_currency_assumption_when_44_currency_not_confirmed():
    result = positions44(replace(notice44(), nmck_rub=None))
    assert result.positions[0].currency.value is None


def test_position_and_characteristic_bounds_show_omitted_counts():
    n = notice44()
    c = n.lot_items[0].characteristics[0]
    c = replace(c, values=c.values * 9)
    item = replace(n.lot_items[0], characteristics=(c,) * 25)
    result = positions44(replace(n, lot_items=(item,) * 26))
    assert (
        len(result.positions) == 25 and result.positions_total == 26 and result.positions_truncated
    )
    p = result.positions[0]
    assert len(p.characteristics) == 24 and p.characteristics_truncated
    assert p.characteristics[0].values_total == 9 and p.characteristics[0].truncated


def test_different_xml_evidence_is_rejected_and_float_money_forbidden():
    result = positions44(notice44())
    payload = result.model_dump()
    payload["positions"][0]["quantity"]["provenance"]["document_id"] = "b" * 64
    with pytest.raises(ValidationError, match="POSITION_XML_PROVENANCE_MISMATCH"):
        PositionEvidenceSet.model_validate(payload)
    with pytest.raises(ValidationError, match="float"):
        DecimalFact(value=1.2, raw=None, provenance=result.positions[0].provenance)


def table_analysis():
    doc = Document()
    table = doc.add_table(rows=14, cols=9)
    for i, row in enumerate(table.rows):
        for j, cell in enumerate(row.cells):
            cell.text = f"R{i + 1}C{j + 1} " + ("x" * 401 if i == 0 and j == 0 else "значение")
    buf = BytesIO()
    doc.save(buf)
    return analyze_document(buf.getvalue(), "Спецификация.docx", "https://example.test/source")


def test_native_table_rows_keep_cells_locators_sha_and_truncation():
    a = table_analysis()
    leads = native_table_leads((("A" * 32, a),))
    d = leads[0]
    assert d.rows_total == 14 and len(d.rows) == 12 and d.truncated
    assert d.rows[0].cells_total == 9 and len(d.rows[0].cells) == 8
    assert d.rows[0].cells[0].text.startswith("R1C1") and d.rows[0].cells[0].truncated
    assert "table 1 row 1 cell 1" in d.rows[0].cells[0].provenance.locator
    assert d.rows[0].cells[0].provenance.document_id == a.sha256
    assert d.role_status == d.position_association == "UNKNOWN"


def test_wrong_native_hash_is_rejected_but_bundle_member_not_attached_to_parent():
    a = table_analysis()
    block = a.blocks[0].model_copy(
        update={"provenance": a.blocks[0].provenance.model_copy(update={"document_id": "f" * 64})}
    )
    wrong = a.model_copy(update={"blocks": (block,)})
    with pytest.raises(ValueError, match="POSITION_NATIVE_PROVENANCE_MISMATCH"):
        native_table_leads((("uid", wrong),))
    assert native_table_leads((("uid", wrong.model_copy(update={"filename": "bundle.zip"})),)) == ()


def test_named_or_classification_overlap_never_produces_equivalence_or_price_rank():
    first = positions44(notice44())
    second = positions44(
        replace(notice44(quantity="3", unit="Пачка", minimum="1000"), xml_sha256="b" * 64)
    )
    links, truncated = position_links((first, second))
    link = links[0]
    assert not truncated and link.basis == "NAME"
    assert link.equivalence == link.price_comparability == "UNKNOWN"
    assert set(link.differences) == {
        "SOURCE_QUANTITY_DIFFERS",
        "SOURCE_UNIT_LABEL_DIFFERS",
        "SOURCE_CHARACTERISTIC_VALUES_DIFFER",
    }
    assert [p.document_id for p in link.evidence] == ["a" * 64, "b" * 64]
    item = replace(notice44().lot_items[0], name="Иное оборудование", ktru_code=None)
    other = positions44(replace(notice44(), lot_items=(item,), xml_sha256="b" * 64))
    classification = position_links((first, other))[0][0]
    assert (
        classification.basis == "CLASSIFICATION"
        and "CLASSIFICATION_DOES_NOT_ESTABLISH_EQUIVALENCE" in classification.differences
    )


def test_link_limit_and_missing_units_remain_explicit():
    n = notice44()
    n = replace(n, lot_items=(replace(n.lot_items[0], unit=None),) * 25)
    links, truncated = position_links((positions44(n), positions44(n)))
    assert len(links) == 24 and truncated
    assert "UNIT_UNKNOWN" in links[0].differences
