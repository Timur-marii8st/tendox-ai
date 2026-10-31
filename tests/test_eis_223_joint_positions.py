"""Joint source positions retain separate customer scopes; canonical stays immutable."""

import copy
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_archive import TYPES_NS, parse_notice223_xml
from procurement.sources.eis_223_joint_positions import joint_positions223
from test_eis_223_zpesmbo import FAMILY, zp_xml


def joint_xml(*, duplicate_owner=False, unknown=False):
    root = ET.fromstring(zp_xml())
    lot = root.find(f".//{{{TYPES_NS}}}lot")
    assert lot is not None
    detail = lot.find(f"{{{TYPES_NS}}}lotData")
    assert detail is not None
    original_items = detail.find(f"{{{TYPES_NS}}}lotItems")
    assert original_items is not None
    detail.remove(original_items)
    joint = ET.SubElement(lot, f"{{{TYPES_NS}}}jointLotData")
    ET.SubElement(joint, f"{{{TYPES_NS}}}jointLot").text = "true"
    owners = ET.SubElement(joint, f"{{{TYPES_NS}}}lotCustomers")
    for i, quantity in enumerate(("6290.8", "1140"), 1):
        owner = ET.SubElement(owners, f"{{{TYPES_NS}}}lotCustomer")
        data = ET.SubElement(owner, f"{{{TYPES_NS}}}lotCustomerData")
        items = ET.SubElement(data, f"{{{TYPES_NS}}}lotItems")
        item = copy.deepcopy(original_items.find(f"{{{TYPES_NS}}}lotItem"))
        assert item is not None
        items.append(item)
        item.find(f"{{{TYPES_NS}}}qty").text = quantity if not unknown else None
        identity = ET.SubElement(owner, f"{{{TYPES_NS}}}customerInfo")
        ET.SubElement(identity, f"{{{TYPES_NS}}}fullName").text = (
            "Первый" if duplicate_owner else f"Заказчик {i}"
        )
        ET.SubElement(identity, f"{{{TYPES_NS}}}inn").text = "1234567890"
    return ET.tostring(root)


def project(raw):
    notice = parse_notice223_xml(raw, source_member="joint.xml", document_type=FAMILY)
    return notice, joint_positions223(raw, notice)


def test_joint_two_buyers_positions_are_bijective_and_not_merged():
    notice, result = project(joint_xml(duplicate_owner=True))
    assert notice.lots[0].items == ()
    assert result is not None and result.source_item_coverage == "PASS"
    assert result.specification_completeness == result.economics_status == "UNKNOWN"
    assert len(result.lots) == 1 and len(result.lots[0].customers) == 2
    first, second = result.lots[0].customers
    assert first.name.value == second.name.value == "Первый"
    assert first.customer_index == 1 and second.customer_index == 2
    assert first.items[0].quantity.value == Decimal("6290.8")
    assert second.items[0].quantity.value == Decimal("1140")
    assert first.items[0].provenance != second.items[0].provenance
    assert (
        "lotCustomer[2]/t:lotCustomerData/t:lotItems/t:lotItem[1]"
        in second.items[0].provenance.locator
    )
    assert result.notice_xml_sha256 == notice.xml_sha256


def test_ordinary_control_has_no_joint_projection():
    _, result = project(zp_xml())
    assert result is None


def test_absent_quantity_stays_unknown_without_invented_sum():
    _, result = project(joint_xml(unknown=True))
    assert result is not None
    assert all(c.items[0].quantity.value is None for c in result.lots[0].customers)
    assert result.economics_status == "UNKNOWN"


@pytest.mark.parametrize(
    "drift", ["duplicate-scalar", "foreign-qname", "both-shapes", "unmapped-item"]
)
def test_ambiguous_or_unmapped_joint_source_fails_closed(drift):
    root = ET.fromstring(joint_xml())
    lot = root.find(f".//{{{TYPES_NS}}}lot")
    assert lot is not None
    if drift == "duplicate-scalar":
        identity = root.find(f".//{{{TYPES_NS}}}customerInfo")
        ET.SubElement(identity, f"{{{TYPES_NS}}}inn").text = "9999999999"
    elif drift == "foreign-qname":
        item = root.find(f".//{{{TYPES_NS}}}lotItem")
        item.tag = "{https://untrusted.invalid}lotItem"
    elif drift == "both-shapes":
        detail = lot.find(f"{{{TYPES_NS}}}lotData")
        direct = ET.SubElement(detail, f"{{{TYPES_NS}}}lotItems")
        direct.append(copy.deepcopy(root.find(f".//{{{TYPES_NS}}}lotItem")))
    else:
        joint = root.find(f".//{{{TYPES_NS}}}jointLotData")
        ET.SubElement(joint, f"{{{TYPES_NS}}}lotItem")
    raw = ET.tostring(root)
    notice = parse_notice223_xml(raw, source_member="joint.xml", document_type=FAMILY)
    with pytest.raises(ValueError, match="JOINT_"):
        joint_positions223(raw, notice)


def test_wrong_xml_cannot_be_attached_to_existing_notice():
    raw = joint_xml()
    notice = parse_notice223_xml(raw, source_member="joint.xml", document_type=FAMILY)
    with pytest.raises(ValueError, match="JOINT_XML_IDENTITY"):
        joint_positions223(raw + b" ", notice)


def test_ordinary_false_joint_marker_does_not_conflict_with_direct_items():
    root = ET.fromstring(zp_xml())
    lot = root.find(f".//{{{TYPES_NS}}}lot")
    joint = ET.SubElement(lot, f"{{{TYPES_NS}}}jointLotData")
    ET.SubElement(joint, f"{{{TYPES_NS}}}jointLot").text = "false"
    _, projection = project(ET.tostring(root))
    assert projection is None


def test_false_joint_flag_with_customer_items_is_preserved_as_uncertain():
    root = ET.fromstring(joint_xml())
    flag = root.find(f".//{{{TYPES_NS}}}jointLot")
    assert flag is not None
    flag.text = "false"
    notice, projection = project(ET.tostring(root))
    assert projection is not None
    assert projection.notice_xml_sha256 == notice.xml_sha256
    assert projection.source_item_coverage == "UNKNOWN"
    assert "JOINT_FLAG_FALSE_WITH_CUSTOMERS" in projection.reasons
    assert len(projection.lots[0].customers) == 2
    assert projection.lots[0].customers[0].items[0].quantity.value == Decimal("6290.8")
    assert projection.economics_status == "UNKNOWN"


def test_false_joint_flag_does_not_bypass_ambiguous_lot_guard():
    root = ET.fromstring(joint_xml())
    root.find(f".//{{{TYPES_NS}}}jointLot").text = "false"
    lot = root.find(f".//{{{TYPES_NS}}}lot")
    detail = lot.find(f"{{{TYPES_NS}}}lotData")
    direct = ET.SubElement(detail, f"{{{TYPES_NS}}}lotItems")
    direct.append(copy.deepcopy(root.find(f".//{{{TYPES_NS}}}lotItem")))
    with pytest.raises(ValueError, match="JOINT_AMBIGUOUS_LOT_SHAPES"):
        project(ET.tostring(root))


@pytest.mark.parametrize("name", ["inn", "qty", "lotCustomers", "additionalInfo"])
def test_foreign_scalar_or_container_qname_rejected(name):
    root = ET.fromstring(joint_xml())
    element = root.find(f".//{{{TYPES_NS}}}{name}")
    element.tag = "{https://untrusted.invalid}" + name
    raw = ET.tostring(root)
    with pytest.raises(ValueError, match=r"JOINT_FOREIGN_QNAME|FIELD_NAMESPACE_INVALID"):
        notice = parse_notice223_xml(raw, source_member="joint.xml", document_type=FAMILY)
        joint_positions223(raw, notice)


@pytest.mark.parametrize("name", ["lot", "jointLotData", "lotItems"])
def test_foreign_structural_sibling_cannot_be_hidden_outside_joint_scan(name):
    root = ET.fromstring(joint_xml())
    element = root.find(f".//{{{TYPES_NS}}}{name}")
    assert element is not None
    element.tag = "{https://untrusted.invalid}" + name
    raw = ET.tostring(root)
    with pytest.raises(ValueError, match=r"JOINT_FOREIGN_QNAME|FIELD_NAMESPACE_INVALID"):
        notice = parse_notice223_xml(raw, source_member="joint.xml", document_type=FAMILY)
        joint_positions223(raw, notice)


def test_hidden_joint_copy_outside_selected_branch_is_not_complete():
    root = ET.fromstring(joint_xml())
    lot = root.find(f".//{{{TYPES_NS}}}lot")
    joint = lot.find(f"{{{TYPES_NS}}}jointLotData")
    nested = ET.SubElement(lot, f"{{{TYPES_NS}}}unexpectedContainer")
    nested.append(copy.deepcopy(joint))
    with pytest.raises(ValueError, match="JOINT_UNMAPPED_ITEMS"):
        project(ET.tostring(root))


def test_mixed_ordinary_and_joint_lots_have_disjoint_complete_item_scopes():
    root = ET.fromstring(joint_xml())
    parent = next(e for e in root.iter() if e.tag.endswith("}lots"))
    ordinary_root = ET.fromstring(zp_xml())
    ordinary = ordinary_root.find(f".//{{{TYPES_NS}}}lot")
    ordinary.find(f"{{{TYPES_NS}}}ordinalNumber").text = "2"
    parent.append(copy.deepcopy(ordinary))
    notice, result = project(ET.tostring(root))
    assert result.source_item_coverage == "PASS"
    assert len(result.lots) == 1 and result.lots[0].lot_index == 1
    assert len(notice.lots[1].items) > 0


ADDED_FAMILIES = ("purchaseNoticeKESMBO", "purchaseNotice", "purchaseNoticeAESMBO")


def family_joint_xml(family, **kwargs):
    """Synthetic QName adaptation; real raw evidence is verified separately."""
    return joint_xml(**kwargs).replace(FAMILY.encode(), family.encode())


@pytest.mark.parametrize("family", ADDED_FAMILIES)
def test_added_joint_family_preserves_exact_type_owner_and_source_paths(family):
    raw = family_joint_xml(family, duplicate_owner=True)
    notice = parse_notice223_xml(raw, source_member="family.xml", document_type=family)
    result = joint_positions223(raw, notice)
    assert result is not None, "supported canonical family loses its joint positions"
    assert result.document_type == family
    assert result.source_item_coverage == "PASS"
    assert result.economics_status == result.specification_completeness == "UNKNOWN"
    a, b = result.lots[0].customers
    assert a.name.value == b.name.value and a.customer_index != b.customer_index
    assert [i.items[0].quantity.value for i in (a, b)] == [Decimal("6290.8"), Decimal("1140")]
    assert a.items[0].provenance.document_id == notice.xml_sha256
    assert a.items[0].provenance.locator.startswith(family + "/p:body/p:item/p:" + family + "Data/")


@pytest.mark.parametrize("family", ADDED_FAMILIES)
def test_added_family_missing_facts_remain_unknown_despite_price_and_header(family):
    root = ET.fromstring(family_joint_xml(family))
    for item in root.iter(f"{{{TYPES_NS}}}lotItem"):
        for field in ("qty", "okei", "additionalInfo"):
            child = item.find(f"{{{TYPES_NS}}}{field}")
            if child is not None:
                item.remove(child)
        ET.SubElement(item, f"{{{TYPES_NS}}}commodityItemPrice").text = "99.99"
    raw = ET.tostring(root)
    notice = parse_notice223_xml(raw, source_member="unknown.xml", document_type=family)
    result = joint_positions223(raw, notice)
    assert result is not None
    for customer in result.lots[0].customers:
        item = customer.items[0]
        assert item.quantity.value is item.unit_name.value is item.description.value is None
    assert result.economics_status == result.specification_completeness == "UNKNOWN"


@pytest.mark.parametrize("family", ADDED_FAMILIES)
@pytest.mark.parametrize("drift", ["foreign", "duplicate", "unmapped"])
def test_added_joint_family_retains_ambiguity_guards(family, drift):
    root = ET.fromstring(family_joint_xml(family))
    if drift == "foreign":
        root.find(f".//{{{TYPES_NS}}}qty").tag = "{https://untrusted.invalid}qty"
    elif drift == "duplicate":
        owner = root.find(f".//{{{TYPES_NS}}}customerInfo")
        ET.SubElement(owner, f"{{{TYPES_NS}}}inn").text = "9999999999"
    else:
        joint = root.find(f".//{{{TYPES_NS}}}jointLotData")
        ET.SubElement(joint, f"{{{TYPES_NS}}}lotItem")
    raw = ET.tostring(root)
    with pytest.raises(ValueError, match=r"JOINT_|FIELD_NAMESPACE_INVALID"):
        notice = parse_notice223_xml(raw, source_member="bad.xml", document_type=family)
        joint_positions223(raw, notice)


@pytest.mark.parametrize("family", ADDED_FAMILIES)
def test_projection_cannot_claim_another_family_with_unchanged_source_paths(family):
    from procurement.sources.eis_223_joint_positions import Eis223PositionProjection

    raw = family_joint_xml(family)
    notice = parse_notice223_xml(raw, source_member="family.xml", document_type=family)
    payload = joint_positions223(raw, notice).model_dump(mode="json")
    payload["document_type"] = FAMILY
    with pytest.raises(ValueError, match="JOINT_LOT_SOURCE"):
        Eis223PositionProjection.model_validate(payload)


def test_unverified_joint_family_stays_unsupported():
    family = "purchaseNoticeZKESMBO"
    raw = family_joint_xml(family)
    notice = parse_notice223_xml(raw, source_member="unknown-family.xml", document_type=family)
    assert joint_positions223(raw, notice) is None


def mirrored_joint_xml(*, mismatch=None):
    root = ET.fromstring(joint_xml())
    lot = root.find(f".//{{{TYPES_NS}}}lot")
    detail = lot.find(f"{{{TYPES_NS}}}lotData")
    joint = lot.find(f"{{{TYPES_NS}}}jointLotData")
    items = list(joint.iter(f"{{{TYPES_NS}}}lotItem"))
    direct = ET.SubElement(detail, f"{{{TYPES_NS}}}lotItems")
    for index, item in enumerate(items, 1):
        ET.SubElement(item, f"{{{TYPES_NS}}}guid").text = f"guid-{index}"
        source_ordinal = item.find(f"{{{TYPES_NS}}}ordinalNumber")
        if source_ordinal is None:
            source_ordinal = ET.SubElement(item, f"{{{TYPES_NS}}}ordinalNumber")
        source_ordinal.text = str(index)
        duplicate = copy.deepcopy(item)
        ordinal = duplicate.find(f"{{{TYPES_NS}}}ordinalNumber")
        if ordinal is None:
            ordinal = ET.SubElement(duplicate, f"{{{TYPES_NS}}}ordinalNumber")
        ordinal.text = str(index + 4)
        direct.append(duplicate)
    if mismatch == "quantity":
        direct[0].find(f"{{{TYPES_NS}}}qty").text = "1"
    if mismatch == "duplicate-guid":
        direct[1].find(f"{{{TYPES_NS}}}guid").text = "guid-1"
    if mismatch == "missing-item":
        direct.remove(direct[-1])
    if mismatch == "missing-guid":
        direct[0].remove(direct[0].find(f"{{{TYPES_NS}}}guid"))
    if mismatch == "different-text":
        direct[0].find(f"{{{TYPES_NS}}}qty").text += " "
    if mismatch == "meaningful-tail":
        direct[0][0].tail = "unexpected text"
    if mismatch == "multiple-ordinals":
        ET.SubElement(direct[0], f"{{{TYPES_NS}}}ordinalNumber").text = "9"
    if mismatch == "ordinal-attributes":
        direct[0].find(f"{{{TYPES_NS}}}ordinalNumber").set("unexpected", "x")
    if mismatch == "excess-depth":
        node = direct[0]
        for _ in range(70):
            node = ET.SubElement(node, "nested")
    return ET.tostring(root)


def test_bijective_joint_mirrors_preserve_customer_items_with_unknown_coverage():
    notice, projection = project(mirrored_joint_xml())
    assert projection.source_item_coverage == "UNKNOWN"
    assert "JOINT_MIRRORED_DIRECT_ITEMS" in projection.reasons
    assert sum(len(c.items) for c in projection.lots[0].customers) == 2
    assert [c.items[0].quantity.value for c in projection.lots[0].customers] == [
        Decimal("6290.8"),
        Decimal("1140"),
    ]
    assert projection.notice_xml_sha256 == notice.xml_sha256
    assert all(
        "jointLotData" in c.items[0].provenance.locator for c in projection.lots[0].customers
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        "quantity",
        "duplicate-guid",
        "missing-item",
        "missing-guid",
        "different-text",
        "meaningful-tail",
        "multiple-ordinals",
        "ordinal-attributes",
        "excess-depth",
    ],
)
def test_joint_mirror_mismatch_remains_hard_failure(mismatch):
    with pytest.raises(ValueError, match="JOINT_AMBIGUOUS_LOT_SHAPES"):
        project(mirrored_joint_xml(mismatch=mismatch))
