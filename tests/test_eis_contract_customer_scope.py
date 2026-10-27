"""Synthetic joint notices; the entire buyer partition must agree before selection."""

import xml.etree.ElementTree as ET
from decimal import Decimal, localcontext

import pytest

from procurement.sources.eis_contract_results import (
    BASE,
    COMMON,
    EP,
    EXPORT,
    TYPES,
    contract_result,
    notice_market,
)

A, B = "01000000001", "01000000002"
NS = {"e": EP, "c": COMMON, "b": BASE}
ITEMS = "e:notificationInfo/e:purchaseObjectsInfo/e:notDrugPurchaseObjectsInfo"
BUYERS = "e:notificationInfo/e:customerRequirementsInfo"


def buyer(number, maximum):
    return (
        f"<e:customerRequirementInfo><e:customer><b:regNum>{number}</b:regNum></e:customer>"
        f"<e:contractConditionsInfo><e:maxPriceInfo><e:maxPrice>{maximum}</e:maxPrice>"
        "</e:maxPriceInfo><e:deliveryPlacesInfo><e:byGARInfo><c:GARInfo>"
        f"<c:GARAddress>г Москва, buyer {number}</c:GARAddress></c:GARInfo></e:byGARInfo>"
        "</e:deliveryPlacesInfo></e:contractConditionsInfo></e:customerRequirementInfo>"
    )


def allocation(number, quantity):
    return (
        f"<c:customerQuantity><c:customer><b:regNum>{number}</b:regNum></c:customer>"
        f"<c:quantity>{quantity}</c:quantity></c:customerQuantity>"
    )


def item(sid, price, quantity, total, allocations):
    return (
        f"<c:purchaseObject><c:sid>{sid}</c:sid><c:type>PRODUCT</c:type>"
        "<c:name>Synthetic paper</c:name><c:KTRU><b:code>99.99.99.999-00000001</b:code>"
        "</c:KTRU><c:OKEI><b:code>796</b:code></c:OKEI>"
        f"<c:price>{price}</c:price><c:quantity><c:value>{quantity}</c:value></c:quantity>"
        f"<c:sum>{total}</c:sum><c:customerQuantities>{allocations}</c:customerQuantities>"
        "</c:purchaseObject>"
    )


def joint(*, items=None, buyers=None, global_price="50.00"):
    if items is None:
        items = item("101", "10", "3", "30", allocation(A, "1") + allocation(B, "2"))
        items += item("102", "20", "1", "20", allocation(A, "1"))
    if buyers is None:
        buyers = buyer(A, "30") + buyer(B, "20")
    return (
        f'<export xmlns="{EXPORT}"><epNotificationEF2020 xmlns:e="{EP}" '
        f'xmlns:c="{COMMON}" xmlns:b="{BASE}"><e:versionNumber>1</e:versionNumber>'
        "<e:commonInfo><e:purchaseNumber>0100000000026000001</e:purchaseNumber>"
        "<e:publishDTInEIS>2026-10-01T10:00:00Z</e:publishDTInEIS></e:commonInfo>"
        f"<e:notificationInfo><e:purchaseObjectsInfo><e:notDrugPurchaseObjectsInfo>{items}"
        "<e:quantityUndefined>false</e:quantityUndefined></e:notDrugPurchaseObjectsInfo>"
        "</e:purchaseObjectsInfo><e:contractConditionsInfo><e:maxPriceInfo>"
        f"<e:maxPrice>{global_price}</e:maxPrice><e:currency><b:code>RUB</b:code></e:currency>"
        "</e:maxPriceInfo></e:contractConditionsInfo>"
        f"<e:customerRequirementsInfo>{buyers}</e:customerRequirementsInfo>"
        "</e:notificationInfo></epNotificationEF2020></export>"
    ).encode()


def change(path, text=None, *, remove=False, duplicate=False, raw=None):
    root = ET.fromstring(joint() if raw is None else raw)
    node = root[0].find(path, NS)
    assert node is not None
    if remove or duplicate:
        parent = next(parent for parent in root.iter() if node in list(parent))
        if remove:
            parent.remove(node)
        if duplicate:
            parent.append(ET.fromstring(ET.tostring(node)))
    else:
        node.text = text
    return ET.tostring(root)


def parse(raw=None, customer=A):
    return notice_market(joint() if raw is None else raw, "synthetic.xml", customer_number=customer)


def test_joint_selects_all_buyer_goods_and_preserves_global_price_and_source_provenance():
    result = parse()
    assert result.reasons == ()
    assert result.scope_kind == "WHOLE_CUSTOMER_CONTRACT"
    assert result.initial.value == Decimal("30")
    assert result.notice_initial.value == Decimal("50")
    assert result.customer.value == A
    assert [(i.sid.value, i.quantity.value, i.line_sum.value) for i in result.items] == [
        ("101", Decimal("1"), Decimal("10.00")),
        ("102", Decimal("1"), Decimal("20.00")),
    ]
    assert result.delivery_addresses[0].value.endswith(A)
    assert B not in result.delivery_addresses[0].value
    assert result.currency.source.locator.endswith("maxPriceInfo/currency/b:code")
    for selected in result.items:
        assert "customerQuantity[1]/quantity" in selected.quantity.source.locator
        assert selected.line_sum.source.locator.endswith("/price")
        assert any(
            "customerQuantity[1]/quantity" in p.locator
            for p in selected.line_sum.supporting_sources
        )
        assert any("customer/b:regNum" in p.locator for p in selected.line_sum.supporting_sources)
        for fact in (selected.quantity, selected.line_sum, result.initial, result.customer):
            assert fact.source.document_id == result.xml_sha256
            assert all(p.document_id == result.xml_sha256 for p in fact.supporting_sources)


def test_other_buyer_is_selected_independently_without_proportional_allocation():
    result = parse(customer=B)
    assert result.reasons == ()
    assert result.initial.value == Decimal("20")
    assert len(result.items) == 1
    assert result.items[0].quantity.value == Decimal("2")
    assert result.delivery_addresses[0].value.endswith(B)


@pytest.mark.parametrize("customer", [None, "01000000003"])
def test_joint_never_falls_back_to_global_baseline_without_matching_customer(customer):
    result = parse(customer=customer)
    assert result.initial.value is None
    assert result.notice_initial.value == Decimal("50")
    assert result.items == ()
    assert any(reason.startswith("CUSTOMER_IDENTITY") for reason in result.reasons)


def single_customer():
    return joint(
        items=item("101", "10", "3", "30", allocation(A, "3")),
        buyers=buyer(A, "30"),
        global_price="30",
    )


def test_sole_source_customer_derives_identity_only_with_full_partition_proof():
    result = parse(single_customer(), None)
    assert result.reasons == ()
    assert result.customer.value == A
    assert result.initial.value == result.notice_initial.value == Decimal("30")
    assert result.items[0].quantity.value == Decimal("3")
    assert result.delivery_addresses[0].value.endswith(A)
    assert result.customer.source.document_id == result.xml_sha256
    assert result.customer.source.locator.endswith("customerRequirementInfo[1]/customer/b:regNum")
    assert "customerRequirementInfo[1]/contractConditionsInfo" in result.initial.source.locator


@pytest.mark.parametrize(
    "fault", ["quantity", "allocation_buyer", "total", "duplicate", "namespace"]
)
def test_sole_customer_selection_does_not_relax_whole_scope_or_identity(fault):
    raw = single_customer()
    if fault == "quantity":
        raw = raw.replace(b"<c:quantity>3</c:quantity>", b"<c:quantity>2</c:quantity>")
    elif fault == "allocation_buyer":
        raw = raw.replace(allocation(A, "3").encode(), allocation(B, "3").encode())
    elif fault == "total":
        raw = raw.replace(b"<e:maxPrice>30</e:maxPrice>", b"<e:maxPrice>31</e:maxPrice>", 1)
    elif fault == "duplicate":
        raw = raw.replace(buyer(A, "30").encode(), (buyer(A, "30") * 2).encode())
    else:
        raw = raw.replace(
            b"<e:customerRequirementInfo>",
            b'<e:customerRequirementInfo xmlns:e="urn:forged">',
        )
    result = parse(raw, None)
    assert result.reasons
    assert result.initial.value is None and result.items == ()


@pytest.mark.parametrize(
    "path",
    [
        BUYERS + "/e:customerRequirementInfo",
        BUYERS + "/e:customerRequirementInfo/e:customer",
        BUYERS + "/e:customerRequirementInfo/e:customer/b:regNum",
    ],
)
def test_forged_parallel_customer_path_prevents_automatic_identity(path):
    root = ET.fromstring(single_customer())
    node = root[0].find(path, NS)
    parent = next(parent for parent in root.iter() if node in list(parent))
    forged = ET.fromstring(ET.tostring(node))
    forged.tag = "{urn:forged}" + forged.tag.rsplit("}", 1)[-1]
    parent.append(forged)
    result = parse(ET.tostring(root), None)
    assert "CUSTOMER_IDENTITY_REQUIRED" in result.reasons
    assert result.initial.value is None and result.items == ()


@pytest.mark.parametrize(
    "name", ["customerQuantity", "customer", "regNum", "quantity", "itemQuantity"]
)
def test_forged_parallel_allocation_prevents_automatic_single_customer(name):
    root = ET.fromstring(single_customer())
    if name == "itemQuantity":
        node = root[0].find(ITEMS + "/c:purchaseObject/c:quantity", NS)
    else:
        allocation_node = next(n for n in root.iter() if n.tag == f"{{{COMMON}}}customerQuantity")
        node = next(n for n in allocation_node.iter() if n.tag.rsplit("}", 1)[-1] == name)
    parent = next(parent for parent in root.iter() if node in list(parent))
    forged = ET.fromstring(ET.tostring(node))
    forged.tag = "{urn:forged}" + node.tag.rsplit("}", 1)[-1]
    parent.append(forged)
    result = parse(ET.tostring(root), None)
    assert "CUSTOMER_PARTITION_SOURCE_AMBIGUOUS" in result.reasons
    assert result.initial.value is None and result.items == ()


@pytest.mark.parametrize(
    "path,text,reason",
    [
        (
            ITEMS + "/c:purchaseObject/c:quantity/c:value",
            "4",
            "CUSTOMER_PARTITION_QUANTITY_CONFLICT",
        ),
        (ITEMS + "/c:purchaseObject/c:sum", "31", "CUSTOMER_PARTITION_ITEM_TOTAL_CONFLICT"),
        (
            BUYERS
            + "/e:customerRequirementInfo/e:contractConditionsInfo/e:maxPriceInfo/e:maxPrice",
            "29",
            "CUSTOMER_PARTITION_BUYER_TOTAL_CONFLICT",
        ),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity/c:quantity",
            "1e0",
            "CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED",
        ),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity/c:quantity",
            "NaN",
            "CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED",
        ),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity/c:quantity",
            "по заявкам",
            "CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED",
        ),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity/c:quantity",
            "-1",
            "CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED",
        ),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity/c:quantity",
            "0",
            "CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED",
        ),
        (
            ITEMS + "/c:purchaseObject/c:price",
            "10,0",
            "CUSTOMER_PARTITION_ITEM_NUMERIC_UNCONFIRMED",
        ),
        (ITEMS + "/c:purchaseObject/c:type", "WORK", "CUSTOMER_PARTITION_NON_PRODUCT"),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity/c:customer/b:regNum",
            "01000000003",
            "CUSTOMER_PARTITION_ALLOCATION_BUYER_INVALID",
        ),
        (
            "e:notificationInfo/e:contractConditionsInfo/e:maxPriceInfo/e:currency/b:code",
            "USD",
            "CUSTOMER_NATIVE_RUB_NOT_CONFIRMED",
        ),
    ],
)
def test_entire_partition_must_be_numeric_fixed_and_consistent(path, text, reason):
    result = parse(change(path, text))
    assert result.initial.value is None
    assert result.items == ()
    assert reason in result.reasons


@pytest.mark.parametrize(
    "path,reason",
    [
        (ITEMS + "/c:purchaseObject/c:customerQuantities", "CUSTOMER_PARTITION_ALLOCATION_MISSING"),
        (ITEMS + "/c:purchaseObject/c:price", "CUSTOMER_PARTITION_ITEM_NUMERIC_UNCONFIRMED"),
        (
            BUYERS + "/e:customerRequirementInfo/e:customer/b:regNum",
            "CUSTOMER_PARTITION_IDENTITY_INVALID",
        ),
    ],
)
def test_missing_partition_fields_do_not_return_partial_buyer_success(path, reason):
    result = parse(change(path, remove=True))
    assert result.initial.value is None
    assert reason in result.reasons


@pytest.mark.parametrize(
    "path,reason",
    [
        (ITEMS + "/c:purchaseObject", "CUSTOMER_PARTITION_SID_INVALID_OR_DUPLICATE"),
        (BUYERS + "/e:customerRequirementInfo", "CUSTOMER_PARTITION_DUPLICATE_BUYER"),
        (
            ITEMS + "/c:purchaseObject/c:customerQuantities/c:customerQuantity",
            "CUSTOMER_PARTITION_ALLOCATION_BUYER_INVALID",
        ),
    ],
)
def test_duplicate_buyer_item_or_allocation_rejects_even_equal_values(path, reason):
    result = parse(change(path, duplicate=True))
    assert result.initial.value is None
    assert reason in result.reasons


def test_foreign_buyer_defect_blocks_selected_buyer_even_when_own_totals_are_correct():
    # Only the other buyer's exclusive item has a bad global quantity.
    items = item("101", "10", "3", "30", allocation(A, "3"))
    items += item("102", "10", "3", "20", allocation(B, "2"))
    result = parse(joint(items=items))
    assert "CUSTOMER_PARTITION_QUANTITY_CONFLICT" in result.reasons
    assert result.initial.value is None


@pytest.mark.parametrize(
    "extra",
    [
        "<c:undefined>true</c:undefined>",
        "<c:volumeTextForm>по заявкам</c:volumeTextForm>",
    ],
)
def test_numeric_value_cannot_override_undefined_or_text_volume_even_with_qf(extra):
    raw = joint().replace(
        b"<c:type>PRODUCT</c:type>",
        b"<c:type>PRODUCT</c:type><c:volumeSpecifyingMethod>QF</c:volumeSpecifyingMethod>",
    )
    raw = raw.replace(b"<c:value>3</c:value>", ("<c:value>3</c:value>" + extra).encode())
    result = parse(raw)
    assert result.initial.value is None
    assert "CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED" in result.reasons


def test_high_precision_decimal_arithmetic_does_not_depend_on_ambient_context():
    raw = joint(
        items=item(
            "101",
            "123456789.123456789",
            "2",
            "246913578.25",
            allocation(A, "1") + allocation(B, "1"),
        ),
        buyers=buyer(A, "123456789.12") + buyer(B, "123456789.13"),
        global_price="246913578.25",
    )
    with localcontext() as context:
        context.prec = 6
        result = parse(raw)
    assert result.reasons == ()
    assert result.items[0].line_sum.value == Decimal("123456789.12")


def test_cent_rounding_is_half_up_and_one_cent_tolerance_is_bounded():
    raw = joint(
        items=item("101", "1.005", "2", "2.01", allocation(A, "1") + allocation(B, "1")),
        buyers=buyer(A, "1.00") + buyer(B, "1.01"),
        global_price="2.01",
    )
    result = parse(raw)
    assert result.reasons == ()
    assert result.items[0].line_sum.value == Decimal("1.01")
    changed = raw.replace(b"<e:maxPrice>1.00</e:maxPrice>", b"<e:maxPrice>0.99</e:maxPrice>")
    assert "CUSTOMER_PARTITION_BUYER_TOTAL_CONFLICT" in parse(changed).reasons


def test_customer_currency_or_formula_is_not_silently_converted():
    for extra, reason in [
        ("<e:currency><b:code>USD</b:code></e:currency>", "CUSTOMER_CURRENCY_SCOPE_UNSUPPORTED"),
        (
            "<e:isContractPriceFormula>true</e:isContractPriceFormula>",
            "CUSTOMER_FORMULA_PRICE_NOT_SUPPORTED",
        ),
    ]:
        raw = joint().replace(
            b"<e:maxPrice>30</e:maxPrice>", ("<e:maxPrice>30</e:maxPrice>" + extra).encode()
        )
        result = parse(raw)
        assert reason in result.reasons
        assert result.initial.value is None


def test_max_price_currency_is_not_used_as_customer_baseline():
    raw = joint().replace(
        b"</e:maxPriceInfo><e:deliveryPlacesInfo>",
        b"</e:maxPriceInfo><e:maxPriceCurrency>999</e:maxPriceCurrency><e:deliveryPlacesInfo>",
    )
    assert parse(raw).initial.value == Decimal("30")


def test_more_than_25_global_goods_can_select_bounded_complete_customer_scope():
    items = item("1", "1", "1", "1", allocation(A, "1"))
    items += "".join(item(str(i), "1", "1", "1", allocation(B, "1")) for i in range(2, 81))
    result = parse(joint(items=items, buyers=buyer(A, "1") + buyer(B, "79"), global_price="80"))
    assert result.reasons == ()
    assert len(result.items) == 1
    result_b = parse(
        joint(items=items, buyers=buyer(A, "1") + buyer(B, "79"), global_price="80"), B
    )
    assert "CUSTOMER_SELECTED_ITEMS_UNAVAILABLE_OR_LIMIT" in result_b.reasons
    assert result_b.initial.value is None


@pytest.mark.parametrize("limit", ["goods", "buyers", "allocations"])
def test_global_partition_resource_caps_apply_before_selection(limit):
    if limit == "goods":
        raw = joint(items=item("1", "1", "1", "1", allocation(A, "1")) * 1001)
    elif limit == "buyers":
        raw = joint(buyers=buyer(A, "30") * 201)
    else:
        raw = joint(items=item("1", "1", "1", "1", allocation(A, "1") * 2001))
    result = parse(raw)
    assert result.initial.value is None
    assert "CUSTOMER_PARTITION_LIMIT" in result.reasons


def ordinary(*, identified=True):
    raw = joint(items=item("101", "10", "3", "30", ""), buyers=buyer(A, "30"), global_price="30")
    raw = raw.replace(b"<c:customerQuantities></c:customerQuantities>", b"")
    if not identified:
        raw = raw.replace(f"<e:customer><b:regNum>{A}</b:regNum></e:customer>".encode(), b"")
    return raw


def test_ordinary_no_argument_stays_whole_notice_and_explicit_buyer_requires_exact_identity():
    result = parse(ordinary(), None)
    assert result.scope_kind == "WHOLE_NOTICE"
    assert result.initial == result.notice_initial
    assert result.initial.value == Decimal("30")
    assert parse(ordinary()).reasons == ()
    for raw, customer in [(ordinary(), B), (ordinary(identified=False), A)]:
        result = parse(raw, customer)
        assert result.initial.value is None
        assert result.notice_initial.value == Decimal("30")
        assert "CUSTOMER_IDENTITY_UNCONFIRMED" in result.reasons


def test_contract_customer_is_source_fact_and_changes_commercial_fingerprint():
    def contract(number):
        return (
            f'<export xmlns="{EXPORT}"><contract xmlns:t="{TYPES}">'
            "<t:regNum>2000000000026000001</t:regNum><t:customer>"
            f"<t:regNum>{number}</t:regNum></t:customer></contract></export>"
        ).encode()

    left, right = (contract_result(contract(number), "contract.xml") for number in (A, B))
    assert left.customer.value == A
    assert left.customer.source.locator.endswith("contract/customer/regNum")
    assert left.customer.source.document_id == left.xml_sha256
    assert left.commercial_fingerprint != right.commercial_fingerprint


@pytest.mark.parametrize("customer", ["bad", "123", 1.0])
def test_customer_selector_cannot_be_fuzzy_or_float(customer):
    with pytest.raises((ValueError, TypeError)):
        parse(customer=customer)
