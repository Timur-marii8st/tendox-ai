"""Supplier product associations retain evidence and never invent verdicts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.sources.eis_supplier_product import (
    SupplierProductRequest,
    build_supplier_product_report,
)
from procurement.sources.supplier_product_details import (
    SupplierCharacteristic,
    SupplierProductDetails,
)
from test_eis_characteristic_compare import characteristic, saved
from test_eis_supplier_catalog_api import REQUEST as SEARCH_REQUEST

SHA = "a" * 64
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def request(position=None) -> SupplierProductRequest:
    page = SEARCH_REQUEST.page
    if position is not None:
        page = page.model_copy(
            update={"position": page.position.model_copy(update={"selection": position.selection})}
        )
    catalog = SEARCH_REQUEST.model_copy(
        update={
            "page": page,
            "search_run_id": "33333333-3333-4333-8333-333333333333",
            "product_index": 1,
        }
    )
    return SupplierProductRequest(
        catalog=catalog,
        product_run_id="44444444-4444-4444-8444-444444444444",
    )


def details(*labels: str, status: str = "EXTRACTED") -> SupplierProductDetails:
    from procurement.sources.supplier_page import DeclaredFact

    facts = tuple(
        SupplierCharacteristic(
            label_raw=label,
            value_raw=f"raw-{index}",
            label_locator=f"label[{index}]",
            value_locator=f"value[{index}]",
            html_sha256=SHA,
        )
        for index, label in enumerate(labels, 1)
    )
    product_name = (
        DeclaredFact(value="Бумага", html_sha256=SHA, locator="product")
        if status == "EXTRACTED"
        else None
    )
    return SupplierProductDetails(
        source_url="https://bumaga-s.ru/товар/1",
        html_sha256=SHA,
        status=status,
        product_name=product_name,
        characteristics=facts if status in {"EXTRACTED", "AMBIGUOUS"} else (),
    )


def build(position, observed):
    return build_supplier_product_report(
        request(position),
        position,
        observed,
        parent_product_report_sha256="b" * 64,
        position_sha256="c" * 64,
        source_body_sha256=SHA,
        run_id="55555555-5555-4555-8555-555555555555",
        created_at=NOW,
    )


def test_unique_fixed_alias_is_recorded_but_all_decisions_remain_unknown():
    position = saved(SHA, (characteristic("Плотность", SHA), characteristic("Белизна", SHA)))
    report = build(position, details("Плотность бумаги", "Белизна CIE"))
    assert [row.supplier_indices for row in report.rows] == [(1,), (2,)]
    assert all(row.observation == "UNKNOWN" for row in report.rows)
    assert report.technical == report.unit_cost == report.participation == "UNKNOWN"


def test_duplicate_supplier_labels_are_all_retained_as_ambiguous():
    report = build(saved(SHA, (characteristic("Формат", SHA),)), details("Формат", "Формат бумаги"))
    assert report.rows[0].supplier_indices == (1, 2)
    assert report.rows[0].reason == "SUPPLIER_CHARACTERISTIC_AMBIGUOUS"


def test_missing_incomplete_and_unextracted_are_explicit_unknown_reasons():
    missing = build(saved(SHA, (characteristic("Состав", SHA),)), details("Плотность"))
    assert missing.rows[0].reason == "SUPPLIER_CHARACTERISTIC_MISSING"
    incomplete = build(
        saved(SHA, (characteristic("Плотность", SHA, truncated=True, total=2),)),
        details("Плотность"),
    )
    assert incomplete.rows[0].reason == "POSITION_CHARACTERISTIC_VALUES_INCOMPLETE"
    assert incomplete.rows[0].supplier_indices == (1,)
    unavailable = build(saved(SHA, (characteristic("Плотность", SHA),)), details(status="EMPTY"))
    assert unavailable.rows[0].reason == "SUPPLIER_DETAILS_NOT_EXTRACTED"


def test_actual_paper_aliases_remain_linked_when_legacy_values_are_unknown():
    names = (
        "Количество листов в пачке",
        "Марка бумаги",
        "Масса бумаги площадью 1м², грамм",
        "Формат",
    )
    position = saved(SHA, tuple(characteristic(name, SHA) for name in names), legacy=True)
    report = build(
        position,
        details("Количество листов", "Класс бумаги", "Плотность бумаги", "Формат бумаги"),
    )
    assert [row.supplier_indices for row in report.rows] == [(1,), (2,), (3,), (4,)]
    assert {row.reason for row in report.rows} == {"POSITION_CHARACTERISTIC_VALUES_INCOMPLETE"}


def test_request_rejects_search_stage_and_report_rejects_digest_or_row_tampering():
    with pytest.raises(ValidationError):
        SupplierProductRequest(
            catalog=SEARCH_REQUEST,
            product_run_id="44444444-4444-4444-8444-444444444444",
        )
    report = build(saved(SHA, (characteristic("Плотность", SHA),)), details("Плотность"))
    with pytest.raises(ValidationError):
        type(report).model_validate({**report.model_dump(), "source_body_sha256": "d" * 64})
    payload = report.model_dump()
    payload["rows"][0]["name"] = "Подмена"
    with pytest.raises(ValidationError):
        type(report).model_validate(payload)


@pytest.mark.parametrize("mutation", ["wrong_index", "omitted", "wrong_reason", "duplicate"])
def test_report_rejects_any_row_derivation_mutation(mutation):
    position = saved(
        SHA,
        (characteristic("Плотность", SHA), characteristic("Формат", SHA)),
    )
    report = build(position, details("Плотность бумаги", "Формат бумаги"))
    payload = report.model_dump()
    if mutation == "wrong_index":
        payload["rows"][0]["supplier_indices"] = (2,)
    elif mutation == "omitted":
        payload["rows"] = payload["rows"][:1]
        payload["row_count"] = 1
    elif mutation == "wrong_reason":
        payload["rows"][0]["reason"] = "SUPPLIER_CHARACTERISTIC_MISSING"
        payload["rows"][0]["supplier_indices"] = ()
    else:
        payload["rows"][0]["supplier_indices"] = (1, 1)
    with pytest.raises(ValidationError):
        type(report).model_validate(payload)
