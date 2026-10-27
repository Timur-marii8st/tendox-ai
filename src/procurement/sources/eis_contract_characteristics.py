"""Bounded KTRU specifications from retained notice/RGK XML, with no unit conversion.

Contract XSD: IntegrationTypes16.3 zfcs_contract2015RefKtruCharacteristicType,
zfcs_tenderPlan2017ManualKtruCharacteristicType and their value types. Notice
COMMON/BASE paths also occur in retained official paper XML. Unsupported forms
remain UNKNOWN. A signature identifies the notice requirements, not the narrower
concrete values offered in a contract. Callers retain XML SHA and these locators.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast
from xml.etree import ElementTree as ET

COMMON = "http://zakupki.gov.ru/oos/common/1"
TYPES = "http://zakupki.gov.ru/oos/types/1"
BASE = "http://zakupki.gov.ru/oos/base/1"
LIMIT = 48
SPEC_POLICY_VERSION = "eis-spec-2026-10-25-paper-grade-boundary-v1"


@dataclass(frozen=True)
class SpecValue:
    kind: Literal["TEXT", "POINT", "RANGE"]
    text: str | None = None
    unit: str | None = None
    point: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    lower_inclusive: bool = False
    upper_inclusive: bool = False


@dataclass(frozen=True)
class Characteristic:
    name: str
    value_type: Literal["1", "2"]
    form: Literal["REFERENCE", "MANUAL"]
    kind: str | None
    values: tuple[SpecValue, ...]
    locator: str
    filling_instruction_code: str | None = None

    @property
    def filling_instruction_locator(self) -> str | None:
        if self.filling_instruction_code is None:
            return None
        return f"{self.locator}/characteristicsFillingInstruction/{{{BASE}}}code"


@dataclass(frozen=True)
class SpecProfile:
    present: bool
    signature: str | None
    characteristics: tuple[Characteristic, ...]
    reasons: tuple[str, ...] = ()


class _Unsupported(ValueError):
    pass


def _text(node: ET.Element) -> str:
    if node.attrib or len(node) or not node.text or not node.text.strip():
        raise _Unsupported("SPEC_SCALAR_INVALID")
    text = unicodedata.normalize("NFC", " ".join(node.text.split()))
    if len(text) > 2000:
        raise _Unsupported("SPEC_SCALAR_LIMIT")
    return text


def _children(
    node: ET.Element, ns: str, allowed: set[str], repeated: set[str] | None = None
) -> dict[str, list[ET.Element]]:
    if node.attrib or (node.text or "").strip():
        raise _Unsupported("SPEC_CONTAINER_INVALID")
    result: dict[str, list[ET.Element]] = {}
    for child in node:
        if (child.tail or "").strip() or child.tag not in {f"{{{ns}}}{name}" for name in allowed}:
            raise _Unsupported("SPEC_CHILD_UNSUPPORTED")
        name = child.tag.removeprefix(f"{{{ns}}}")
        result.setdefault(name, []).append(child)
        if len(result[name]) > (LIMIT if repeated and name in repeated else 1):
            raise _Unsupported("SPEC_DUPLICATE_OR_LIMIT")
    return result


def _scalar(
    fields: dict[str, list[ET.Element]], name: str, *, required: bool = False
) -> str | None:
    if name not in fields:
        if required:
            raise _Unsupported("SPEC_REQUIRED_FIELD_MISSING")
        return None
    return _text(fields[name][0])


def _decimal(text: str) -> Decimal:
    if not re.fullmatch(r"[+-]?[0-9]{1,20}(?:\.[0-9]{1,11})?", text):
        raise _Unsupported("SPEC_DECIMAL_INVALID")
    return Decimal(text)


def _number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _value_key(value: SpecValue) -> tuple[object, ...]:
    return (
        value.kind,
        value.text,
        value.unit,
        _number(value.point),
        _number(value.lower),
        _number(value.upper),
        value.lower_inclusive,
        value.upper_inclusive,
    )


def _value(node: ET.Element, ns: str, notice: bool, value_type: str) -> SpecValue:
    allowed = {"qualityDescription", "OKEI", "valueFormat", "valueSet", "rangeSet"}
    if notice:
        allowed |= {"sid", "externalSid"}
    fields = _children(
        node,
        ns,
        allowed,
    )
    for name in ("sid", "externalSid"):
        _scalar(fields, name)
    if value_type == "1":
        if any(name in fields for name in ("OKEI", "valueFormat", "valueSet", "rangeSet")):
            raise _Unsupported("SPEC_VALUE_BRANCH_CONFLICT")
        text = _scalar(fields, "qualityDescription", required=True)
        return SpecValue("TEXT", text=text)
    if "qualityDescription" in fields or "OKEI" not in fields:
        raise _Unsupported("SPEC_VALUE_BRANCH_CONFLICT")
    unit_fields = _children(
        fields["OKEI"][0], BASE if notice else TYPES, {"code", "name", "nationalCode"}
    )
    unit = _scalar(unit_fields, "code", required=True)
    for name in ("name", "nationalCode"):
        _scalar(unit_fields, name)
    if unit is None or not re.fullmatch(r"[0-9]{1,10}", unit):
        raise _Unsupported("SPEC_UNIT_UNSUPPORTED")
    if _scalar(fields, "valueFormat") not in (None, "N"):
        raise _Unsupported("SPEC_VALUE_FORMAT_UNSUPPORTED")
    if ("valueSet" in fields) == ("rangeSet" in fields):
        raise _Unsupported("SPEC_VALUE_BRANCH_CONFLICT")
    if "valueSet" in fields:
        points = _children(fields["valueSet"][0], ns, {"concreteValue"})
        raw = _scalar(points, "concreteValue", required=True)
        assert raw is not None
        return SpecValue("POINT", unit=unit, point=_decimal(raw))
    ranges = _children(fields["rangeSet"][0], ns, {"valueRange"})
    if "valueRange" not in ranges:
        raise _Unsupported("SPEC_RANGE_UNSUPPORTED")
    bounds = _children(
        ranges["valueRange"][0], ns, {"min", "max", "minMathNotation", "maxMathNotation"}
    )
    raw_lower, raw_upper = _scalar(bounds, "min"), _scalar(bounds, "max")
    lop, uop = _scalar(bounds, "minMathNotation"), _scalar(bounds, "maxMathNotation")
    if (
        (raw_lower is None) != (lop is None)
        or (raw_upper is None) != (uop is None)
        or (raw_lower is None and raw_upper is None)
        or lop not in (None, "greater", "greaterOrEqual")
        or uop not in (None, "less", "lessOrEqual")
    ):
        raise _Unsupported("SPEC_RANGE_INVALID")
    lower = None if raw_lower is None else _decimal(raw_lower)
    upper = None if raw_upper is None else _decimal(raw_upper)
    li, ui = lop == "greaterOrEqual", uop == "lessOrEqual"
    if (
        lower is not None
        and upper is not None
        and (lower > upper or (lower == upper and not (li and ui)))
    ):
        raise _Unsupported("SPEC_EMPTY_RANGE")
    return SpecValue(
        "RANGE", unit=unit, lower=lower, upper=upper, lower_inclusive=li, upper_inclusive=ui
    )


def parse_spec(item: ET.Element, *, notice: bool) -> SpecProfile:
    """Parse one source item; malformed/unsupported specifications never raise admission.

    Empty-on-both is a compatibility profile only, not proof of product equivalence.
    Root item fields are owned by the caller; specification subtrees are strict.
    """
    ns = COMMON if notice else TYPES
    try:
        if item.tag != f"{{{ns}}}{'purchaseObject' if notice else 'product'}":
            raise _Unsupported("SPEC_ITEM_NAMESPACE_INVALID")
        # Reject lookalike specification roots rather than treating them as absent.
        for child in item:
            local = child.tag.rsplit("}", 1)[-1]
            if local in {"characteristics", "addCharacteristics"}:
                raise _Unsupported("SPEC_ROOT_UNSUPPORTED")
            if local == "KTRU" and child.tag != f"{{{ns}}}KTRU":
                raise _Unsupported("SPEC_NAMESPACE_INVALID")
            if local == "OKPD2" and any(
                sub.tag.rsplit("}", 1)[-1] in {"characteristics", "addCharacteristics"}
                for sub in child
            ):
                raise _Unsupported("SPEC_ROOT_UNSUPPORTED")
        ktrus = item.findall(f"{{{ns}}}KTRU")
        if len(ktrus) > 1:
            raise _Unsupported("SPEC_DUPLICATE_KTRU")
        if not ktrus:
            return SpecProfile(False, "", ())
        for node in ktrus[0]:
            local = node.tag.rsplit("}", 1)[-1]
            if local in {"rightSideKTRUInfo", "addCharacteristics"}:
                raise _Unsupported("SPEC_ROOT_UNSUPPORTED")
            if local == "characteristics" and node.tag != f"{{{ns}}}characteristics":
                raise _Unsupported("SPEC_NAMESPACE_INVALID")
        blocks = ktrus[0].findall(f"{{{ns}}}characteristics")
        if not blocks:
            return SpecProfile(False, "", ())
        if len(blocks) != 1:
            raise _Unsupported("SPEC_DUPLICATE_CONTAINER")
        refs, manual = "characteristicsUsingReferenceInfo", "characteristicsUsingTextForm"
        allowed = {refs, manual}
        if notice:
            allowed.add("addCharacteristicInfoReason")
        fields = _children(blocks[0], ns, allowed, {refs, manual})
        # Justification is descriptive metadata, not a product value; still validate it.
        _scalar(fields, "addCharacteristicInfoReason")
        count = len(fields.get(refs, [])) + len(fields.get(manual, []))
        if not 1 <= count <= LIMIT:
            raise _Unsupported("SPEC_CHARACTERISTIC_LIMIT")
        results: list[Characteristic] = []
        names: set[str] = set()
        for form, tag in (("REFERENCE", refs), ("MANUAL", manual)):
            for index, node in enumerate(fields.get(tag, []), 1):
                allowed = {"name", "type", "values"}
                if notice:
                    allowed |= {"sid", "externalSid", "characteristicsFillingInstruction"}
                if form == "REFERENCE":
                    allowed |= {"code", "kind"}
                parts = _children(node, ns, allowed)
                name = _scalar(parts, "name", required=True)
                value_type = _scalar(parts, "type", required=True)
                assert name is not None
                name = name.casefold()
                if name in names or value_type not in ("1", "2"):
                    raise _Unsupported("SPEC_IDENTITY_INVALID")
                names.add(name)
                kind = _scalar(parts, "kind")
                if kind not in (None, "1", "2", "3"):
                    raise _Unsupported("SPEC_KIND_INVALID")
                for field in ("sid", "externalSid", "code"):
                    _scalar(parts, field)
                instruction_code = None
                if "characteristicsFillingInstruction" in parts:
                    instruction = _children(
                        parts["characteristicsFillingInstruction"][0], BASE, {"code", "name"}
                    )
                    instruction_code = _scalar(instruction, "code", required=True)
                    _scalar(instruction, "name")
                if "values" not in parts:
                    raise _Unsupported("SPEC_VALUES_MISSING")
                values = _children(parts["values"][0], ns, {"value"}, {"value"}).get("value", [])
                if not values or (kind == "2" and len(values) != 1):
                    raise _Unsupported("SPEC_VALUE_COUNT_INVALID")
                parsed = tuple(_value(v, ns, notice, value_type) for v in values)
                keys = [_value_key(v) for v in parsed]
                if len(set(keys)) != len(keys):
                    raise _Unsupported("SPEC_DUPLICATE_VALUE")
                ordered = tuple(sorted(parsed, key=lambda v: repr(_value_key(v))))
                results.append(
                    Characteristic(
                        name,
                        cast(Literal["1", "2"], value_type),
                        cast(Literal["REFERENCE", "MANUAL"], form),
                        kind,
                        ordered,
                        f"KTRU/characteristics/{tag}[{index}]",
                        instruction_code,
                    )
                )
        results.sort(key=lambda c: c.name)
        payload = {
            "policy": SPEC_POLICY_VERSION,
            "characteristics": [
                (
                    c.name,
                    c.value_type,
                    c.form,
                    c.kind,
                    c.filling_instruction_code,
                    [_value_key(v) for v in c.values],
                )
                for c in results
            ],
        }
        signature = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        return SpecProfile(True, signature, tuple(results))
    except _Unsupported as error:
        return SpecProfile(True, None, (), (str(error),))


def _paper_grade_boundary(requirement: Characteristic, offered: Characteristic) -> bool:
    """Product interpretation: equality at one literal minimum, never grade ordering.

    Effective 2026-10-25; source instruction 2 is required. This is deliberately
    limited to one atomic paper grade, retaining case and alphabet of that grade.
    """
    if (
        requirement.name != "марка бумаги"
        or requirement.filling_instruction_code != "2"
        or len(requirement.values) != 1
        or len(offered.values) != 1
    ):
        return False
    required, actual = requirement.values[0], offered.values[0]
    if required.kind != "TEXT" or actual.kind != "TEXT" or required.text is None:
        return False
    match = re.fullmatch(r"(?i:не ниже) ([A-Za-zА-Яа-яЁё0-9])", required.text)
    return match is not None and actual.text == match.group(1)


def specifications_bound(notice: SpecProfile, contract: SpecProfile) -> bool | None:
    """Bind exact text, the bounded paper-grade rule, or allowed numeric points.

    False denotes a numeric point proved outside the allowed set; textual differences,
    missing identities/units and unsupported contract ranges remain UNKNOWN (None).
    No ordinal interpretation, transliteration or unit conversion is attempted.
    """
    if notice.reasons or contract.reasons or notice.signature is None or contract.signature is None:
        return None
    if not notice.present and not contract.present:
        return True
    if notice.present != contract.present:
        return None
    expected = {c.name: c for c in notice.characteristics}
    actual = {c.name: c for c in contract.characteristics}
    if expected.keys() != actual.keys():
        return None
    for name, requirement in expected.items():
        offered = actual[name]
        if (requirement.value_type, requirement.form, requirement.kind) != (
            offered.value_type,
            offered.form,
            offered.kind,
        ):
            return None
        if requirement.value_type == "1":
            if requirement.values != offered.values and not _paper_grade_boundary(
                requirement, offered
            ):
                return None
            continue
        for value in offered.values:
            if value.kind != "POINT" or value.point is None:
                return None
            if any(v.unit != value.unit for v in requirement.values):
                return None
            accepted = False
            for allowed in requirement.values:
                if allowed.kind == "POINT":
                    accepted |= value.point == allowed.point
                elif allowed.kind == "RANGE":
                    low = (
                        allowed.lower is None
                        or value.point > allowed.lower
                        or (allowed.lower_inclusive and value.point == allowed.lower)
                    )
                    high = (
                        allowed.upper is None
                        or value.point < allowed.upper
                        or (allowed.upper_inclusive and value.point == allowed.upper)
                    )
                    accepted |= low and high
            if not accepted:
                return False
    return True
