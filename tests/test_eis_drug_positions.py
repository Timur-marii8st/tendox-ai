"""Drug source evidence never infers doses, packs, quote validity or equivalence."""

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from procurement.sources.eis_drug_positions import drug_positions44
from procurement.sources.eis_feed_archive import EisNoticeSnapshot

E = "http://zakupki.gov.ru/oos/export/1"
P = "http://zakupki.gov.ru/oos/EPtypes/1"
C = "http://zakupki.gov.ru/oos/common/1"
B = "http://zakupki.gov.ru/oos/base/1"


def source(
    items: str, *, extra: str = "", currency: str = "RUB"
) -> tuple[EisNoticeSnapshot, bytes]:
    xml = f'''<e:export xmlns:e="{E}" xmlns:p="{P}" xmlns:c="{C}" xmlns:b="{B}">
<e:epNotificationEF2020>
<p:id>44105096</p:id>
<p:versionNumber>1</p:versionNumber>
<p:commonInfo>
<p:purchaseNumber>0123456789026000001</p:purchaseNumber>
<p:docNumber>1</p:docNumber>
<p:purchaseObjectInfo>Синтетические лекарства</p:purchaseObjectInfo>
</p:commonInfo>
<p:notificationInfo>
<p:purchaseObjectsInfo>
<p:drugPurchaseObjectsInfo>{items}</p:drugPurchaseObjectsInfo>{extra}</p:purchaseObjectsInfo>
<p:contractConditionsInfo>
<p:maxPriceInfo>
<p:maxPrice>100</p:maxPrice>
<p:currency>
<b:code>{currency}</b:code>
</p:currency>
</p:maxPriceInfo>
</p:contractConditionsInfo>
</p:notificationInfo>
</e:epNotificationEF2020>
</e:export>'''.encode()
    return EisNoticeSnapshot(
        "0123456789026000001",
        "epNotificationEF2020",
        1,
        "Синтетические лекарства",
        None,
        None,
        Decimal("100"),
        hashlib.sha256(xml).hexdigest(),
        "notice.xml",
    ), xml


def drug(
    *,
    undefined: bool = False,
    quantity: str = "500",
    unit: str = "Миллиграмм (мг)",
    name: str = "Синтетический препарат",
    second_unit: str | None = None,
    extra: str = "",
) -> str:
    def reference(u: str) -> str:
        return (
            f"<c:drugInfo>"
            f"<c:manualUserOKEI>"
            f"<b:code>161</b:code>"
            f"<b:name>{u}</b:name>"
            f"</c:manualUserOKEI>"
            f"</c:drugInfo>"
        )

    refs = reference(unit) + (reference(second_unit) if second_unit is not None else "")
    mode = (
        "<c:quantityUndefined><c:quantityUndefined>true</c:quantityUndefined><c:price>2.50000</c:price></c:quantityUndefined>"
        if undefined
        else (
            f"<c:drugQuantityCustomersInfo>"
            f"<c:drugQuantityCustomerInfo>"
            f"<c:quantity>{quantity}</c:quantity>"
            f"</c:drugQuantityCustomerInfo>"
            f"<c:total>{quantity}</c:total>"
            f"</c:drugQuantityCustomersInfo>"
            f"<c:pricePerUnit>2.50</c:pricePerUnit>"
            f"<c:positionPrice>1250.00</c:positionPrice>"
        )
    )
    return (
        f"<c:drugPurchaseObjectInfo>"
        f"<c:name>{name}</c:name>"
        f"<c:objectInfoUsingReferenceInfo>"
        f"<c:drugsInfo>{refs}</c:drugsInfo>"
        f"</c:objectInfoUsingReferenceInfo>{mode}{extra}</c:drugPurchaseObjectInfo>"
    )


def test_explicit_name_quantity_prices_and_exact_source_paths():
    from procurement.sources.eis_feed_archive import _notice

    notice, xml = source(drug())
    canonical = _notice(xml, notice.source_member, notice.document_type)
    assert canonical.lot_items == () and canonical.lot_parse_status == "UNKNOWN"
    result = drug_positions44(notice, xml)
    assert result is not None and result.positions_total == 1
    p = result.positions[0]
    assert p.name.value == "Синтетический препарат" and p.quantity.value == Decimal("500")
    assert (
        p.unit.value == "Миллиграмм (мг)"
        and p.unit_price.value == Decimal("2.50")
        and p.line_sum.value == Decimal("1250.00")
    )
    assert (
        "drugQuantityCustomersInfo" in p.quantity.provenance.locator
        and "Q{" + C + "}total" in p.quantity.provenance.locator
    )
    assert (
        "manualUserOKEI" in p.unit.provenance.locator
        and "pricePerUnit" in p.unit_price.provenance.locator
    )
    assert p.provenance.document_id == notice.xml_sha256
    assert p.classification_code.value is None and p.ktru_code.value is None
    assert p.review_status == result.review_status == result.specification_completeness == "UNKNOWN"
    assert notice.lot_items == () and notice.lot_parse_status == "UNKNOWN"


def test_undefined_quantity_is_not_ceiling_divided_by_price_or_embedded_dose():
    notice, xml = source(drug(undefined=True, name="Препарат 500 мг, упаковка №100"))
    result = drug_positions44(notice, xml)
    assert result is not None
    p = result.positions[0]
    assert p.quantity.value is None and p.line_sum.value is None
    assert p.unit_price.value == Decimal("2.50000") and p.unit.value == "Миллиграмм (мг)"


@pytest.mark.parametrize("other", ["Штука (шт)", "мг"])
def test_alternative_units_do_not_get_guessed_or_normalized(other):
    notice, xml = source(drug(second_unit=other))
    result = drug_positions44(notice, xml)
    assert result is not None
    assert result.positions[0].unit.value is None and result.positions[0].quantity.value is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "1e999999", "not-a-number"])
def test_bad_source_numbers_stay_unknown(bad):
    notice, xml = source(drug(quantity=bad))
    result = drug_positions44(notice, xml)
    assert result is not None
    assert result.positions[0].quantity.value is None


def test_source_order_duplicates_and_preview_count_are_not_deduplicated():
    notice, xml = source(drug() * 27)
    result = drug_positions44(notice, xml)
    assert result is not None
    assert (
        len(result.positions) == 25 and result.positions_total == 27 and result.positions_truncated
    )
    assert [p.source_index for p in result.positions] == list(range(1, 26))
    assert result.positions[0].provenance.locator != result.positions[1].provenance.locator


def test_identity_and_unsafe_xml_rejected():
    notice, xml = source(drug())
    with pytest.raises(ValueError):
        drug_positions44(replace(notice, xml_sha256="a" * 64), xml)
    unsafe = xml.replace(b"<e:export", b'<!DOCTYPE x [<!ENTITY a "bad">]><e:export')
    with pytest.raises(ValueError):
        drug_positions44(replace(notice, xml_sha256=hashlib.sha256(unsafe).hexdigest()), unsafe)


def test_namespace_spoof_does_not_supply_names_or_quantities():
    notice, xml = source(drug().replace("<c:name>", "<p:name>").replace("</c:name>", "</p:name>"))
    result = drug_positions44(notice, xml)
    assert result is not None
    assert result.positions[0].name.value is None


def test_mixed_goods_drugs_are_not_silently_selected():
    notice, xml = source(drug(), extra="<p:notDrugPurchaseObjectsInfo/>")
    result = drug_positions44(notice, xml)
    assert result is not None
    assert not result.positions and result.specification_completeness == "UNKNOWN"


@pytest.mark.parametrize(
    "extra",
    [
        "<c:quantityUndefined><c:quantityUndefined>true</c:quantityUndefined></c:quantityUndefined>",
        "<c:drugQuantityCustomersInfo><c:total>500</c:total></c:drugQuantityCustomersInfo>",
        "<p:drugQuantityCustomersInfo><p:total>500</p:total></p:drugQuantityCustomersInfo>",
    ],
)
def test_duplicate_or_conflicting_quantity_modes_do_not_confirm_numbers(extra):
    notice, xml = source(drug(extra=extra))
    result = drug_positions44(notice, xml)
    assert result is not None
    p = result.positions[0]
    assert p.quantity.value is None and p.unit_price.value is None and p.line_sum.value is None


@pytest.mark.parametrize("currency", ["USD", "", "643"])
def test_non_rub_or_missing_currency_does_not_confirm_ruble_prices(currency):
    notice, xml = source(drug(), currency=currency)
    result = drug_positions44(notice, xml)
    assert result is not None
    assert result.positions[0].unit_price.value is None
    assert result.positions[0].line_sum.value is None


def test_explicit_interchange_reference_unit_has_exact_qname_locator():
    item = (
        drug()
        .replace(
            "<c:drugsInfo><c:drugInfo>",
            "<c:drugsInfo><c:drugInterchangeInfo><c:drugInterchangeManualInfo><c:isInterchange>true</c:isInterchange><c:drugInfo><c:drugInfoUsingReferenceInfo>",
        )
        .replace(
            "</c:manualUserOKEI></c:drugInfo></c:drugsInfo>",
            "</c:manualUserOKEI></c:drugInfoUsingReferenceInfo></c:drugInfo></c:drugInterchangeManualInfo></c:drugInterchangeInfo></c:drugsInfo>",
        )
    )
    notice, xml = source(item)
    result = drug_positions44(notice, xml)
    assert result is not None
    p = result.positions[0]
    assert p.quantity.value == Decimal("500")
    assert "Q{" + B + "}name" in p.unit.provenance.locator
    assert "drugInfo[1]" in p.unit.provenance.locator


def test_foreign_parallel_drug_object_is_not_dropped_from_count():
    item = (
        drug()
        .replace("<c:drugPurchaseObjectInfo>", "<p:drugPurchaseObjectInfo>")
        .replace("</c:drugPurchaseObjectInfo>", "</p:drugPurchaseObjectInfo>")
    )
    notice, xml = source(drug() + item)
    result = drug_positions44(notice, xml)
    assert result is not None
    assert result.positions_total == 2 and not result.positions and result.positions_truncated
