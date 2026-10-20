import hashlib

import pytest
from pydantic import ValidationError

from procurement.sources import supplier_product_details as p

URL = "https://bumaga-s.ru/товар/paper"


def row(label: str, value: str, kind: str = "product-description-item") -> str:
    return (
        f'<div class="{kind}"><div class="title">{label}</div>'
        f'<div class="value productProperties"><a>{value}</a></div></div>'
    )


def fixture(rows: str = "") -> bytes:
    return (
        '<div class="product-card-content-item"><h1>Бумага SvetoCopy</h1>'
        '<span itemscope itemtype="http://schema.org/Product">'
        '<meta itemprop="name" content="Бумага SvetoCopy"></span>'
        + rows
        + '<div class="cart-product-form product-btn" data-package="5"></div></div>'
    ).encode()


def test_raw_characteristics_packaging_and_control_are_not_economic_units() -> None:
    content = fixture(
        row("формат", "А4")
        + row("плотность бумаги", "80 +/- 3г/кв.м")
        + row("количество листов", "500 листов")
        + row("класс бумаги", "Сэ")
        + row("Упаковка:", "5/100", "product-main-info-item")
    )
    result = p.parse_supplier_product_details(URL, content)
    assert result.status == "EXTRACTED"
    assert result.html_sha256 == hashlib.sha256(content).hexdigest()
    assert result.contents_raw.value == "500 листов" and result.packaging_raw.value == "5/100"
    assert result.characteristics[1].value_raw == "80 +/- 3г/кв.м"
    assert result.characteristics[3].value_raw == "Сэ"
    assert result.order_controls[0].raw_value == "5"
    assert result.price_basis_raw is None
    assert (
        result.price_basis_status
        == result.MOQ_status
        == result.order_step_status
        == result.technical_status
        == "UNKNOWN"
    )
    assert all(x.html_sha256 == result.html_sha256 for x in result.characteristics)


def test_conflicts_keep_raw_rows_without_summary() -> None:
    result = p.parse_supplier_product_details(
        URL, fixture(row("формат", "А4") + row("формат", "А3"))
    )
    assert result.status == "AMBIGUOUS"
    assert [x.value_raw for x in result.characteristics] == ["А4", "А3"]
    assert result.product_name is result.contents_raw is result.packaging_raw is None


@pytest.mark.parametrize(
    "wrapper",
    [
        "<template>",
        "<noscript>",
        "<div hidden>",
        '<div aria-hidden="true">',
        '<div style="display:none">',
    ],
)
def test_hidden_context_never_extracts(wrapper: str) -> None:
    tag = wrapper.split()[0].lstrip("<").rstrip(">")
    content = wrapper.encode() + fixture(row("формат", "А4")) + f"</{tag}>".encode()
    assert p.parse_supplier_product_details(URL, content).status == "AMBIGUOUS"


def test_competing_product_and_name_conflict_rejected() -> None:
    content = (
        fixture()
        + b'<template><span itemscope itemtype="http://schema.org/Product"></span></template>'
    )
    assert p.parse_supplier_product_details(URL, content).status == "AMBIGUOUS"
    content = fixture().replace(b'content="', b'content="other ')
    assert p.parse_supplier_product_details(URL, content).status == "AMBIGUOUS"


def test_limits_clear_partial_facts() -> None:
    content = fixture("".join(row(f"field{i}", "value") for i in range(17)))
    result = p.parse_supplier_product_details(URL, content)
    assert result.status == "LIMIT_EXCEEDED" and result.characteristics == ()
    assert p.parse_supplier_product_details(URL, b"<div>" * 129).status == "LIMIT_EXCEEDED"
    assert (
        p.parse_supplier_product_details(URL, b"x" * (p.MAX_BODY_BYTES + 1)).status
        == "LIMIT_EXCEEDED"
    )
    assert p.parse_supplier_product_details(URL, b"\xff").status == "UNSUPPORTED"


def test_tenant_independent_source_binding_model_rejects_wrong_hash() -> None:
    result = p.parse_supplier_product_details(URL, fixture(row("формат", "А4")))
    data = result.model_dump()
    data["html_sha256"] = "a" * 64
    with pytest.raises(ValidationError):
        p.SupplierProductDetails.model_validate(data)


def test_unsupported_host_and_no_product() -> None:
    assert (
        p.parse_supplier_product_details("https://other.ru/товар/paper", fixture()).status
        == "UNSUPPORTED"
    )
    assert p.parse_supplier_product_details(URL, b"<html></html>").status == "EMPTY"


def test_recommendation_controls_not_attributed_to_main_product() -> None:
    rows = (
        row("формат", "А4")
        + '<div class="products-item"><div class="cart-product-form" data-package="99"></div>'
        + row("формат", "А3")
        + "</div>"
    )
    result = p.parse_supplier_product_details(URL, fixture(rows))
    assert result.status == "EXTRACTED"
    assert [c.raw_value for c in result.order_controls] == ["5"]
    assert [c.value_raw for c in result.characteristics] == ["А4"]


def test_observed_discount_marker_binding_preserves_full_raw_name() -> None:
    content = fixture().replace(b"<h1>", b'<h1><span class="SpecSkidka">*</span> ')
    result = p.parse_supplier_product_details(URL, content)
    assert result.status == "EXTRACTED" and result.product_name.value.startswith("* ")
    unknown = content.replace(b"SpecSkidka", b"unrecognized")
    assert p.parse_supplier_product_details(URL, unknown).status == "AMBIGUOUS"


@pytest.mark.parametrize(
    "broken",
    [
        "context",
        "product",
        "heading",
        "row",
        "mismatched_context",
    ],
)
def test_selected_scope_requires_explicit_unambiguous_close(broken: str) -> None:
    content = fixture(row("формат", "А4"))
    if broken == "context":
        content = content[:-6]
    elif broken == "product":
        content = content.replace(b"</span>", b"", 1)
    elif broken == "heading":
        content = content.replace(b"</h1>", b"", 1)
    elif broken == "row":
        content = content.replace(b"</a></div></div>", b"</a></div>", 1)
    else:
        content = content[:-6] + b"<section></div>"
    result = p.parse_supplier_product_details(URL, content)
    assert result.status == "AMBIGUOUS"
    assert result.product_name is None and result.characteristics == ()


def test_unclosed_unrelated_global_optional_tags_do_not_invalidate_product() -> None:
    content = b"<html><body>" + fixture(row("формат", "А4"))
    assert p.parse_supplier_product_details(URL, content).status == "EXTRACTED"
