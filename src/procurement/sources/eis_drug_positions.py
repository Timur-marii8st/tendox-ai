"""Exact-path drug evidence, separate from immutable canonical notice snapshots.

Names, quantities and prices are source facts. No dose/pack conversion or
pharmaceutical equivalence is established here.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from decimal import Decimal

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import DecimalFact, TextFact
from procurement.sources.eis_feed_archive import EisNoticeSnapshot
from procurement.sources.eis_position_evidence import (
    MAX_POSITIONS,
    PositionEvidence,
    PositionEvidenceSet,
)

EXPORT = "http://zakupki.gov.ru/oos/export/1"
EP = "http://zakupki.gov.ru/oos/EPtypes/1"
COMMON = "http://zakupki.gov.ru/oos/common/1"
BASE = "http://zakupki.gov.ru/oos/base/1"
MAX_XML_BYTES = 32 * 1024**2
MAX_DRUG_OBJECTS = 1000
MAX_ALTERNATIVES = 64
MAX_SCALAR = 4000
_DECIMAL = re.compile(r"\+?(?:[0-9]{1,20}(?:\.[0-9]{1,12})?|\.[0-9]{1,12})\Z")


def _q(namespace: str, name: str) -> str:
    return "{" + namespace + "}" + name


def _one(parent: ET.Element | None, namespace: str, name: str) -> ET.Element | None:
    """A spoofed alias or duplicate singleton cannot supply a confirmed fact."""
    if parent is None:
        return None
    matches = [child for child in parent if child.tag.rsplit("}", 1)[-1] == name]
    return matches[0] if len(matches) == 1 and matches[0].tag == _q(namespace, name) else None


def _present(parent: ET.Element, name: str) -> bool:
    return any(child.tag.rsplit("}", 1)[-1] == name for child in parent)


def _scalar(node: ET.Element | None) -> str | None:
    if node is None or len(node) or len(node.text or "") > MAX_SCALAR:
        return None
    return (node.text or "").strip() or None


def _number(raw: str | None) -> Decimal | None:
    if raw is None or _DECIMAL.fullmatch(raw) is None:
        return None
    value = Decimal(raw)
    return value if value.is_finite() and value >= 0 else None


def _units(item: ET.Element, path: str) -> tuple[str | None, str]:
    """Only identical explicit manual units across every declared alternative.

    Equality of these source strings does not establish drug interchangeability.
    Dosage units, multipliers and packaging never substitute for this field.
    """
    info = _one(item, COMMON, "objectInfoUsingReferenceInfo")
    drugs = _one(info, COMMON, "drugsInfo")
    base = path + "/objectInfoUsingReferenceInfo/drugsInfo"
    records: list[tuple[ET.Element, str]] = []
    if drugs is None:
        return None, base + "/manualUserOKEI/name"
    if any(child.tag == _q(COMMON, "drugInterchangeInfo") for child in drugs) and len(drugs) != 1:
        return None, base
    for child_index, child in enumerate(drugs, 1):
        if child.tag == _q(COMMON, "drugInfo"):
            records.append((child, base + f"/drugInfo[{child_index}]"))
        elif child.tag == _q(COMMON, "drugInterchangeInfo"):
            manual = _one(child, COMMON, "drugInterchangeManualInfo")
            if manual is None:
                return None, base + "/drugInterchangeInfo"
            flag = _one(manual, COMMON, "isInterchange")
            if (
                len(child) != 1
                or (
                    _present(manual, "isInterchange")
                    and _scalar(flag) not in {"true", "false", "1", "0"}
                )
                or any(
                    entry.tag not in {_q(COMMON, "drugInfo"), _q(COMMON, "isInterchange")}
                    for entry in manual
                )
            ):
                return None, base + "/drugInterchangeInfo"
            for ordinal, entry in enumerate(manual.findall(_q(COMMON, "drugInfo")), 1):
                ref = _one(entry, COMMON, "drugInfoUsingReferenceInfo")
                if ref is None:
                    return None, base + "/drugInterchangeInfo/drugInterchangeManualInfo"
                records.append(
                    (
                        ref,
                        base
                        + "/drugInterchangeInfo/drugInterchangeManualInfo"
                        + f"/drugInfo[{ordinal}]/drugInfoUsingReferenceInfo",
                    )
                )
        else:
            return None, base
    if not records or len(records) > MAX_ALTERNATIVES:
        return None, base
    values: list[tuple[str, str, str]] = []
    for record, locator in records:
        unit = _one(record, COMMON, "manualUserOKEI")
        code = _scalar(_one(unit, BASE, "code"))
        name = _scalar(_one(unit, BASE, "name"))
        if code is None or name is None:
            return None, locator + "/manualUserOKEI/name"
        values.append((code, name, locator + "/manualUserOKEI/name"))
    if len({(code, name) for code, name, _ in values}) != 1:
        return None, base + "/manualUserOKEI/name"
    return values[0][1], values[0][2]


def drug_positions44(notice: EisNoticeSnapshot, xml: bytes) -> PositionEvidenceSet | None:
    """Read the verified drug branch; None means the branch is not supported/present.

    A mixed branch or oversized object list remains an empty, truncated UNKNOWN
    evidence set with its actual object count; it does not change canonical data.
    """
    if (
        len(xml) > MAX_XML_BYTES
        or hashlib.sha256(xml).hexdigest() != notice.xml_sha256
        or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.I)
    ):
        raise ValueError("DRUG_XML_BINDING_OR_SAFETY_INVALID")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ValueError("DRUG_XML_INVALID") from error
    if root.tag != _q(EXPORT, "export") or len(root) != 1:
        raise ValueError("DRUG_EXPORT_INVALID")
    document = root[0]
    if document.tag != _q(EXPORT, notice.document_type):
        raise ValueError("DRUG_DOCUMENT_TYPE_MISMATCH")
    notification = _one(document, EP, "notificationInfo")
    objects = _one(notification, EP, "purchaseObjectsInfo")
    drug = _one(objects, EP, "drugPurchaseObjectsInfo")
    if drug is None:
        return None
    common = _one(document, EP, "commonInfo")
    number = _scalar(_one(common, EP, "purchaseNumber"))
    version = _scalar(_one(document, EP, "versionNumber"))
    if number != notice.purchase_number or version != str(notice.version_number):
        raise ValueError("DRUG_NOTICE_IDENTITY_MISMATCH")
    entries = [child for child in drug if child.tag.rsplit("}", 1)[-1] == "drugPurchaseObjectInfo"]
    mixed = objects is not None and any(
        child.tag.rsplit("}", 1)[-1] == "notDrugPurchaseObjectsInfo" for child in objects
    )
    positions: list[PositionEvidence] = []
    conditions = _one(notification, EP, "contractConditionsInfo")
    maximum = _one(conditions, EP, "maxPriceInfo")
    currency_node = _one(_one(maximum, EP, "currency"), BASE, "code")
    currency = _scalar(currency_node)
    currency_path = (
        notice.document_type + "/notificationInfo/contractConditionsInfo/maxPriceInfo/currency/code"
    )

    def provenance(path: str) -> Provenance:
        # The path uses fixed source namespace bindings, never caller XML prefixes.
        names = path.split("/")
        common_names = {
            "drugPurchaseObjectInfo",
            "name",
            "objectInfoUsingReferenceInfo",
            "drugsInfo",
            "drugInfo",
            "drugInterchangeInfo",
            "drugInterchangeManualInfo",
            "drugInfoUsingReferenceInfo",
            "manualUserOKEI",
            "drugQuantityCustomersInfo",
            "total",
            "quantityUndefined",
            "price",
            "pricePerUnit",
            "positionPrice",
        }
        qualified = []
        for index, name in enumerate(names):
            local = name.split("[", 1)[0]
            namespace = (
                EXPORT
                if index == 0
                else BASE
                if local == "code" or (local == "name" and names[index - 1] == "manualUserOKEI")
                else COMMON
                if local in common_names
                else EP
            )
            qualified.append("Q{" + namespace + "}" + name)
        return Provenance(
            document_id=notice.xml_sha256,
            locator=notice.source_member + " :: /Q{" + EXPORT + "}export/" + "/".join(qualified),
            extractor=Extractor.API,
        )

    def text(value: str | None, path: str) -> TextFact:
        return TextFact(value=value, raw=value, provenance=provenance(path))

    def decimal(raw: str | None, path: str, *, allow: bool = True) -> DecimalFact:
        return DecimalFact(
            value=_number(raw) if allow else None, raw=raw, provenance=provenance(path)
        )

    if (
        not mixed
        and len(entries) <= MAX_DRUG_OBJECTS
        and all(entry.tag == _q(COMMON, "drugPurchaseObjectInfo") for entry in entries)
    ):
        for ordinal, entry in enumerate(entries[:MAX_POSITIONS], 1):
            path = (
                notice.document_type
                + "/notificationInfo/purchaseObjectsInfo/drugPurchaseObjectsInfo"
                + f"/drugPurchaseObjectInfo[{ordinal}]"
            )
            unit, unit_path = _units(entry, path)
            undefined = _one(entry, COMMON, "quantityUndefined")
            quantities = _one(entry, COMMON, "drugQuantityCustomersInfo")
            has_undefined = _present(entry, "quantityUndefined")
            has_quantities = _present(entry, "drugQuantityCustomersInfo")
            ambiguous = (
                (has_undefined and has_quantities)
                or (has_undefined and undefined is None)
                or (has_quantities and quantities is None)
            )
            total = _scalar(_one(quantities, COMMON, "total"))
            undefined_true = _scalar(_one(undefined, COMMON, "quantityUndefined")) == "true"
            price_path = path + ("/quantityUndefined/price" if undefined_true else "/pricePerUnit")
            price = _scalar(
                _one(undefined, COMMON, "price")
                if undefined_true
                else _one(entry, COMMON, "pricePerUnit")
            )
            line = _scalar(_one(entry, COMMON, "positionPrice"))
            positions.append(
                PositionEvidence(
                    source_index=ordinal,
                    name=text(_scalar(_one(entry, COMMON, "name")), path + "/name"),
                    quantity=decimal(
                        total,
                        path + "/drugQuantityCustomersInfo/total",
                        allow=unit is not None and not has_undefined and not ambiguous,
                    ),
                    unit=text(unit if not ambiguous else None, unit_path),
                    classification_code=text(None, path),
                    ktru_code=text(None, path),
                    unit_price=decimal(
                        price,
                        price_path,
                        allow=currency == "RUB"
                        and unit is not None
                        and not ambiguous
                        and (not has_undefined or undefined_true),
                    ),
                    line_sum=decimal(
                        line,
                        path + "/positionPrice",
                        allow=currency == "RUB" and not has_undefined and not ambiguous,
                    ),
                    currency=text(currency, currency_path),
                    characteristics=(),
                    characteristics_total=0,
                    characteristics_truncated=False,
                    characteristics_status="UNKNOWN",
                    provenance=provenance(path),
                )
            )
    return PositionEvidenceSet(
        law="44",
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
        positions=tuple(positions),
        positions_total=len(entries),
        positions_truncated=len(positions) < len(entries),
        native_tables=(),
    )
