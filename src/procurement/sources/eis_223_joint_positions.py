"""Owner-aware joint positions derived from exact retained XML, never a new notice."""

from __future__ import annotations

import hashlib
from typing import Literal, get_args
from xml.etree import ElementTree as ET

from pydantic import Field, model_validator

from procurement.domain.provenance import Provenance
from procurement.sources.eis_223_archive import (
    MAX_NOTICE_ITEMS,
    MAX_NOTICE_XML_BYTES,
    PURCHASE_NS,
    TYPES_NS,
    Eis223ContractError,
    Eis223LotItem,
    Eis223NoticeSnapshot,
    SourceModel,
    TextFact,
    _children,
    _decimal,
    _one,
    _optional,
    _provenance,
    _text,
)

PARSER_VERSION = "eis223-joint-positions-v1"
JointDocumentType223 = Literal[
    "purchaseNoticeZPESMBO", "purchaseNoticeKESMBO", "purchaseNotice", "purchaseNoticeAESMBO"
]
SUPPORTED_JOINT_DOCUMENT_TYPES = frozenset(get_args(JointDocumentType223))


def _identical_joint_mirrors(direct: list[ET.Element], joint: ET.Element) -> bool:
    """Accept only bijective GUID matches with identical item trees except local ordinal."""
    grouped = [item for item in joint.iter() if item.tag == f"{{{TYPES_NS}}}lotItem"]
    if not direct or len(direct) != len(grouped) or len(direct) > MAX_NOTICE_ITEMS:
        return False

    def identity(item: ET.Element) -> str | None:
        values = _children(item, TYPES_NS, "guid")
        ordinals = _children(item, TYPES_NS, "ordinalNumber")
        if (len(values) != 1 or len(values[0]) or not values[0].text or len(ordinals) != 1
                or ordinals[0].attrib or len(ordinals[0]) or not ordinals[0].text
                or not ordinals[0].text.strip().isdecimal()
                or (ordinals[0].tail and ordinals[0].tail.strip())):
            return None
        value = values[0].text.strip()
        return value if value and len(value) <= 100 else None

    def shape(item: ET.Element, *, root: bool = False, depth: int = 0) -> tuple:
        if depth > 64:
            raise ValueError("MIRROR_DEPTH_LIMIT")
        # Ignore only formatting-only whitespace; preserve all substantive bytes.
        text = item.text if item.text and item.text.strip() else None
        tail = item.tail if item.tail and item.tail.strip() else None
        return (
            item.tag, tuple(sorted(item.attrib.items())), text, tail,
            tuple(shape(child, depth=depth + 1) for child in item if not (
                root and child.tag == f"{{{TYPES_NS}}}ordinalNumber"
            )),
        )

    direct_ids = [identity(item) for item in direct]
    joint_ids = [identity(item) for item in grouped]
    if (None in direct_ids or None in joint_ids or len(set(direct_ids)) != len(direct_ids)
            or len(set(joint_ids)) != len(joint_ids) or set(direct_ids) != set(joint_ids)):
        return False
    by_id = dict(zip(joint_ids, grouped, strict=True))
    try:
        return all(shape(item, root=True) == shape(by_id[ident], root=True)
                   for item, ident in zip(direct, direct_ids, strict=True))
    except ValueError:
        return False


class JointCustomerPositions223(SourceModel):
    customer_index: int = Field(ge=1)
    name: TextFact
    inn: TextFact
    kpp: TextFact
    iko: TextFact
    items: tuple[Eis223LotItem, ...]
    provenance: Provenance


class JointLotPositions223(SourceModel):
    lot_index: int = Field(ge=1)
    ordinal: TextFact
    customers: tuple[JointCustomerPositions223, ...] = Field(min_length=1)
    provenance: Provenance


class Eis223PositionProjection(SourceModel):
    law: Literal["223"] = "223"
    document_type: JointDocumentType223 = "purchaseNoticeZPESMBO"
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    version_number: int = Field(ge=1)
    notice_xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_member: str = Field(min_length=1, max_length=1024)
    parser_version: Literal["eis223-joint-positions-v1"] = PARSER_VERSION
    lots: tuple[JointLotPositions223, ...] = Field(min_length=1)
    source_item_coverage: Literal["PASS", "UNKNOWN"]
    specification_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    economics_status: Literal["UNKNOWN"] = "UNKNOWN"
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _source_bound(self):
        prefix = f"{self.document_type}/p:body/p:item/p:{self.document_type}Data/p:lots"
        paths = set()
        previous = 0
        count = 0
        for lot in self.lots:
            if lot.lot_index <= previous:
                raise ValueError("JOINT_LOT_ORDER")
            previous = lot.lot_index
            lot_path = prefix + f"/t:lot[{lot.lot_index}]"
            if (
                lot.provenance.locator != lot_path
                or lot.ordinal.provenance.locator != lot_path + "/t:ordinalNumber"
            ):
                raise ValueError("JOINT_LOT_SOURCE")
            for ci, customer in enumerate(lot.customers, 1):
                customer_path = lot_path + f"/t:jointLotData/t:lotCustomers/t:lotCustomer[{ci}]"
                if customer.customer_index != ci or customer.provenance.locator != customer_path:
                    raise ValueError("JOINT_CUSTOMER_SOURCE")
                for name in ("name", "inn", "kpp", "iko"):
                    suffix = "fullName" if name == "name" else name
                    if (
                        getattr(customer, name).provenance.locator
                        != customer_path + "/t:customerInfo/t:" + suffix
                    ):
                        raise ValueError("JOINT_CUSTOMER_FACT_SOURCE")
                for ii, item in enumerate(customer.items, 1):
                    path = customer_path + f"/t:lotCustomerData/t:lotItems/t:lotItem[{ii}]"
                    if item.provenance.locator != path or path in paths:
                        raise ValueError("JOINT_ITEM_SOURCE")
                    paths.add(path)
                    count += 1
                    for field, suffix in {
                        "description": "t:additionalInfo",
                        "classification_code": "t:okpd2/t:code",
                        "classification_name": "t:okpd2/t:name",
                        "quantity": "t:qty",
                        "unit_code": "t:okei/t:code",
                        "unit_name": "t:okei/t:name",
                    }.items():
                        if getattr(item, field).provenance.locator != path + "/" + suffix:
                            raise ValueError("JOINT_ITEM_FACT_SOURCE")
        if count > MAX_NOTICE_ITEMS or (
            self.source_item_coverage == "PASS"
            and (not count or any(not c.items for lot in self.lots for c in lot.customers))
        ):
            raise ValueError("JOINT_ITEM_COVERAGE")

        def walk(value):
            if isinstance(value, Provenance):
                if value.document_id != self.notice_xml_sha256 or not value.locator.startswith(
                    prefix + "/"
                ):
                    raise ValueError("JOINT_XML_PROVENANCE")
            elif isinstance(value, SourceModel):
                for field in type(value).model_fields:
                    walk(getattr(value, field))
            elif isinstance(value, tuple):
                for child in value:
                    walk(child)

        for lot in self.lots:
            walk(lot)
        return self


def joint_positions223(raw: bytes, notice: Eis223NoticeSnapshot) -> Eis223PositionProjection | None:
    """Enumerate only exact supported customer-item branches; unknown is never empty PASS."""
    if notice.document_type not in SUPPORTED_JOINT_DOCUMENT_TYPES:
        return None
    if (
        not raw
        or len(raw) > MAX_NOTICE_XML_BYTES
        or hashlib.sha256(raw).hexdigest() != notice.xml_sha256
    ):
        raise ValueError("JOINT_XML_IDENTITY")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("JOINT_XML_DECLARATION")
    try:
        root = ET.fromstring(raw)
        if root.tag != f"{{{PURCHASE_NS}}}{notice.document_type}":
            raise ValueError("JOINT_ROOT_NAMESPACE")
        data = _one(
            _one(_one(root, PURCHASE_NS, "body"), PURCHASE_NS, "item"),
            PURCHASE_NS,
            notice.document_type + "Data",
        )
        if (
            _text(data, PURCHASE_NS, "registrationNumber", notice.xml_sha256, "unused").value
            != notice.purchase_number
        ):
            raise ValueError("JOINT_NOTICE_IDENTITY")
        version = _text(data, PURCHASE_NS, "version", notice.xml_sha256, "unused").value
        if version is None or not version.isdecimal() or int(version) != notice.version_number:
            raise ValueError("JOINT_NOTICE_IDENTITY")
        for child in data:
            if child.tag.rsplit("}", 1)[-1] == "lots" and child.tag != f"{{{PURCHASE_NS}}}lots":
                raise ValueError("JOINT_FOREIGN_QNAME")
        parent = _optional(data, PURCHASE_NS, "lots")
        if parent is not None:
            protected = {
                "lot",
                "lotData",
                "ordinalNumber",
                "jointLotData",
                "jointLot",
                "lotCustomers",
                "lotCustomer",
                "lotCustomerData",
                "lotItems",
                "lotItem",
            }
            for element in parent.iter():
                local = element.tag.rsplit("}", 1)[-1]
                if local in protected and element.tag != f"{{{TYPES_NS}}}{local}":
                    raise ValueError("JOINT_FOREIGN_QNAME")
        native_lots = _children(parent, TYPES_NS, "lot") if parent is not None else []
        groups = []
        seen_items = set()
        ordinary_items = set()
        all_items = (
            {id(e) for e in parent.iter() if e.tag == f"{{{TYPES_NS}}}lotItem"}
            if parent is not None
            else set()
        )
        joint_items = set()
        sha = notice.xml_sha256
        base = f"{notice.document_type}/p:body/p:item/p:{notice.document_type}Data/p:lots"
        complete = True
        false_with_customers = False
        mirrored_direct_items = False
        for li, lot in enumerate(native_lots, 1):
            direct_parent = _optional(_optional(lot, TYPES_NS, "lotData"), TYPES_NS, "lotItems")
            direct_items = (
                _children(direct_parent, TYPES_NS, "lotItem") if direct_parent is not None else []
            )
            ordinary_items.update(id(item) for item in direct_items)
            joint = _optional(lot, TYPES_NS, "jointLotData")
            if joint is None:
                continue
            flag = _text(
                joint, TYPES_NS, "jointLot", sha, base + f"/t:lot[{li}]/t:jointLotData/t:jointLot"
            ).value
            if flag == "false" and not any(
                e.tag.rsplit("}", 1)[-1] in {"lotCustomers", "lotCustomer", "lotItem"}
                for e in joint.iter()
            ):
                continue
            header = _optional(lot, TYPES_NS, "lotData")
            direct = _optional(header, TYPES_NS, "lotItems")
            if direct is not None and _children(direct, TYPES_NS, "lotItem"):
                if flag != "true" or not _identical_joint_mirrors(direct_items, joint):
                    raise ValueError("JOINT_AMBIGUOUS_LOT_SHAPES")
                # The observed duplicates have different ordinals. Do not claim
                # complete item coverage or project the same items twice.
                mirrored_direct_items = True
                complete = False
            path = base + f"/t:lot[{li}]"
            if flag not in {"true", "false"}:
                raise ValueError("JOINT_FLAG_UNSUPPORTED")
            if flag == "false":
                false_with_customers = True
                complete = False
            for element in joint.iter():
                local = element.tag.rsplit("}", 1)[-1]
                if (
                    local
                    in {
                        "jointLot",
                        "lotCustomers",
                        "lotCustomer",
                        "lotCustomerData",
                        "lotItems",
                        "lotItem",
                        "customerInfo",
                        "fullName",
                        "inn",
                        "kpp",
                        "iko",
                        "qty",
                        "additionalInfo",
                        "okpd2",
                        "okei",
                        "code",
                        "name",
                    }
                    and element.tag != f"{{{TYPES_NS}}}{local}"
                ):
                    raise ValueError("JOINT_FOREIGN_QNAME")
                if element.tag == f"{{{TYPES_NS}}}lotItem":
                    joint_items.add(id(element))
            owners = _one(joint, TYPES_NS, "lotCustomers")
            customers = []
            for ci, owner in enumerate(_children(owners, TYPES_NS, "lotCustomer"), 1):
                cp = path + f"/t:jointLotData/t:lotCustomers/t:lotCustomer[{ci}]"
                detail = _one(owner, TYPES_NS, "lotCustomerData")
                identity = _optional(owner, TYPES_NS, "customerInfo")
                items_parent = _optional(detail, TYPES_NS, "lotItems")
                items = []
                for ii, item in enumerate(
                    _children(items_parent, TYPES_NS, "lotItem")
                    if items_parent is not None
                    else [],
                    1,
                ):
                    if len(seen_items) >= MAX_NOTICE_ITEMS:
                        raise ValueError("JOINT_ITEM_LIMIT")
                    seen_items.add(id(item))
                    ip = cp + f"/t:lotCustomerData/t:lotItems/t:lotItem[{ii}]"
                    classification = _optional(item, TYPES_NS, "okpd2")
                    unit = _optional(item, TYPES_NS, "okei")
                    items.append(
                        Eis223LotItem(
                            description=_text(
                                item, TYPES_NS, "additionalInfo", sha, ip + "/t:additionalInfo"
                            ),
                            classification_code=_text(
                                classification, TYPES_NS, "code", sha, ip + "/t:okpd2/t:code"
                            ),
                            classification_name=_text(
                                classification, TYPES_NS, "name", sha, ip + "/t:okpd2/t:name"
                            ),
                            quantity=_decimal(item, "qty", sha, ip + "/t:qty"),
                            unit_code=_text(unit, TYPES_NS, "code", sha, ip + "/t:okei/t:code"),
                            unit_name=_text(unit, TYPES_NS, "name", sha, ip + "/t:okei/t:name"),
                            provenance=_provenance(sha, ip),
                        )
                    )
                complete = complete and bool(items)
                if ci > MAX_NOTICE_ITEMS:
                    raise ValueError("JOINT_CUSTOMER_LIMIT")
                customers.append(
                    JointCustomerPositions223(
                        customer_index=ci,
                        name=_text(
                            identity, TYPES_NS, "fullName", sha, cp + "/t:customerInfo/t:fullName"
                        ),
                        inn=_text(identity, TYPES_NS, "inn", sha, cp + "/t:customerInfo/t:inn"),
                        kpp=_text(identity, TYPES_NS, "kpp", sha, cp + "/t:customerInfo/t:kpp"),
                        iko=_text(identity, TYPES_NS, "iko", sha, cp + "/t:customerInfo/t:iko"),
                        items=tuple(items),
                        provenance=_provenance(sha, cp),
                    )
                )
            if not customers:
                raise ValueError("JOINT_CUSTOMERS_MISSING")
            groups.append(
                JointLotPositions223(
                    lot_index=li,
                    ordinal=_text(lot, TYPES_NS, "ordinalNumber", sha, path + "/t:ordinalNumber"),
                    customers=tuple(customers),
                    provenance=_provenance(sha, path),
                )
            )
        if seen_items != joint_items or all_items != seen_items | ordinary_items:
            raise ValueError("JOINT_UNMAPPED_ITEMS")
        if not groups:
            return None
        return Eis223PositionProjection(
            document_type=notice.document_type,
            purchase_number=notice.purchase_number,
            version_number=notice.version_number,
            notice_xml_sha256=sha,
            source_member=notice.source_member,
            lots=tuple(groups),
            source_item_coverage="PASS" if complete else "UNKNOWN",
            reasons=(
                (("JOINT_FLAG_FALSE_WITH_CUSTOMERS",) if false_with_customers else ())
                + (("JOINT_MIRRORED_DIRECT_ITEMS",) if mirrored_direct_items else ())
                + (("JOINT_CUSTOMER_ITEMS_UNKNOWN",) if any(
                    not customer.items for lot in groups for customer in lot.customers
                ) else ())
            ),
        )
    except (Eis223ContractError, ET.ParseError) as error:
        raise ValueError("JOINT_SOURCE_INVALID") from error
