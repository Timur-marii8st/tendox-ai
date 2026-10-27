"""Synthetic official-shaped specs; no private fixtures or source requests."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_contract_characteristics import (
    BASE,
    COMMON,
    TYPES,
    parse_spec,
    specifications_bound,
)


def profile(values=None, *, notice=True, manual=False, kind="2", value_type="2", extra=""):
    prefix = "c" if notice else "t"
    ns = COMMON if notice else TYPES
    tag = "purchaseObject" if notice else "product"
    if values is None:
        return ET.fromstring(f'<{prefix}:{tag} xmlns:{prefix}="{ns}"/>')
    form = "characteristicsUsingTextForm" if manual else "characteristicsUsingReferenceInfo"
    k = "" if manual or kind is None else f"<p:kind>{kind}</p:kind>"
    raw = f'''<p:{tag} xmlns:p="{ns}" xmlns:b="{BASE}"><p:KTRU><p:characteristics>
    <p:{form}><p:name>Test specification</p:name><p:type>{value_type}</p:type>{k}
    <p:values>{values}</p:values></p:{form}>{extra}</p:characteristics></p:KTRU></p:{tag}>'''
    return ET.fromstring(raw)


def text(value):
    return f"<p:value><p:qualityDescription>{value}</p:qualityDescription></p:value>"


def point(number, *, notice=True, unit="796"):
    u = "b" if notice else "p"
    return (
        f"<p:value><p:OKEI><{u}:code>{unit}</{u}:code></p:OKEI>"
        f"<p:valueSet><p:concreteValue>{number}</p:concreteValue></p:valueSet></p:value>"
    )


def interval(lower=None, upper=None, lop="greaterOrEqual", uop="lessOrEqual", *, unit="796"):
    lo = (
        ""
        if lower is None
        else f"<p:min>{lower}</p:min><p:minMathNotation>{lop}</p:minMathNotation>"
    )
    hi = (
        ""
        if upper is None
        else f"<p:max>{upper}</p:max><p:maxMathNotation>{uop}</p:maxMathNotation>"
    )
    return (
        f"<p:value><p:OKEI><b:code>{unit}</b:code></p:OKEI>"
        "<p:valueFormat>N</p:valueFormat><p:rangeSet>"
        f"<p:valueRange>{lo}{hi}</p:valueRange></p:rangeSet></p:value>"
    )


def parsed(values, **kwargs):
    return parse_spec(profile(values, **kwargs), notice=kwargs.get("notice", True))


def test_actual_manual_text_and_reference_paths_are_supported_and_frozen():
    a = parsed(text("белая"), manual=True, value_type="1")
    b = parsed(text("белая"), manual=True, value_type="1", notice=False)
    assert specifications_bound(a, b) is True
    assert a.signature == b.signature
    assert "characteristicsUsingTextForm" in a.characteristics[0].locator
    with pytest.raises(FrozenInstanceError):
        a.signature = "changed"
    a = parsed(interval("500"))
    b = parsed(point("500", notice=False), notice=False)
    assert specifications_bound(a, b) is True
    assert a.signature != b.signature  # Cohort MUST retain notice signature.
    assert b.characteristics[0].values[0].point == Decimal("500")


@pytest.mark.parametrize("label", ["С", "C", "не ниже С", "Не ниже C"])
def test_no_ordinal_guess_or_transliteration(label):
    assert (
        specifications_bound(
            parsed(text("Не ниже С"), value_type="1"),
            parsed(text(label), value_type="1", notice=False),
        )
        is None
    )


def test_whitespace_normalization_does_not_remove_text_case_or_semantics():
    a = parsed(text("  белая\n бумага "), manual=True, value_type="1")
    b = parsed(text("белая бумага"), manual=True, value_type="1", notice=False)
    assert specifications_bound(a, b) is True


@pytest.mark.parametrize(
    "lo,hi,lop,uop,number,expected",
    [
        ("-10", "0", "greaterOrEqual", "lessOrEqual", "-10", True),
        ("-10", "0", "greater", "lessOrEqual", "-10", False),
        ("-10", "0", "greaterOrEqual", "less", "0", False),
        ("-10", "0", "greater", "less", "-5", True),
        (None, "+0", "greaterOrEqual", "lessOrEqual", "-0.00", True),
        ("500", None, "greaterOrEqual", "lessOrEqual", "499.99999999999", False),
        ("500", None, "greaterOrEqual", "lessOrEqual", "+500.000", True),
    ],
)
def test_exact_signed_decimal_and_inclusive_exclusive_boundaries(
    lo, hi, lop, uop, number, expected
):
    assert (
        specifications_bound(
            parsed(interval(lo, hi, lop, uop), manual=True),
            parsed(point(number, notice=False), notice=False, manual=True),
        )
        is expected
    )


def test_notice_set_allows_only_explicit_contract_subset():
    a = parsed(point("1") + point("2"), kind="3")
    assert specifications_bound(a, parsed(point("2", notice=False), kind="3", notice=False)) is True
    assert (
        specifications_bound(a, parsed(point("3", notice=False), kind="3", notice=False)) is False
    )
    assert (
        specifications_bound(
            a, parsed(point("1", notice=False, unit="006"), kind="3", notice=False)
        )
        is None
    )


def test_missing_one_side_unknown_absent_both_compatibility_only():
    empty = parse_spec(profile(), notice=True)
    assert specifications_bound(empty, parse_spec(profile(notice=False), notice=False)) is True
    assert specifications_bound(empty, parsed(point("1", notice=False), notice=False)) is None
    assert specifications_bound(parsed(point("1")), empty) is None


@pytest.mark.parametrize(
    "bad",
    [
        "<p:value><p:qualityDescription>A4</p:qualityDescription><p:OKEI/></p:value>",
        "<p:value><p:qualityDescription>A4</p:qualityDescription><p:valueFormat>A</p:valueFormat></p:value>",
        "<p:value><p:qualityDescription/></p:value>",
        "<p:value><b:qualityDescription>A4</b:qualityDescription></p:value>",
        '<p:value><p:qualityDescription x="1">A4</p:qualityDescription></p:value>',
        text("A4") + "<p:unknownSemanticField>anything</p:unknownSemanticField>",
        "<p:value><p:qualityDescription>A4</p:qualityDescription></p:value>mixed text",
    ],
)
def test_prior_false_pass_malformed_qualitative_branches_unknown(bad):
    a = parsed(bad, value_type="1")
    assert a.reasons and a.signature is None
    assert specifications_bound(a, parsed(text("A4"), value_type="1", notice=False)) is None


@pytest.mark.parametrize(
    "bad",
    [
        point("1").replace("<p:concreteValue>1</p:concreteValue>", "<p:concreteValue/>"),
        point("1").replace("</p:valueSet>", "<p:concreteValue>2</p:concreteValue></p:valueSet>"),
        point("1").replace("</p:value>", "<p:rangeSet/></p:value>"),
        point("NaN"),
        point("Infinity"),
        point("1e2"),
        point("1,2"),
        point("1" * 21),
        interval("1", "1", "greater", "lessOrEqual"),
        interval("2", "1"),
        interval(),
        interval("1").replace("<p:min>1</p:min>", "<p:min/>"),
        interval("1").replace("greaterOrEqual", "unknown"),
        interval("1").replace("valueRange", "outValueRange"),
        point("1").replace("<b:code>796</b:code>", "<p:code>796</p:code>"),
        point("1").replace("</p:OKEI>", "<b:code>006</b:code></p:OKEI>"),
        point("1").replace("</p:value>", "<p:valueFormat/></p:value>"),
    ],
)
def test_numeric_malformed_or_unsupported_never_admitted(bad):
    a = parsed(bad)
    assert a.reasons and a.signature is None
    assert specifications_bound(a, parsed(point("1", notice=False), notice=False)) is None


def test_container_limits_duplicates_empty_and_right_side():
    a = profile(text("A4"), value_type="1")
    chars = a.find(f"{{{COMMON}}}KTRU/{{{COMMON}}}characteristics")
    assert chars is not None
    chars.append(ET.fromstring(ET.tostring(chars[0])))
    assert parse_spec(a, notice=True).reasons
    for raw in [text("A4") * 49, "", text("A4") * 2]:
        assert parsed(raw, value_type="1", kind="1").reasons
    a = profile(text("A4"), value_type="1")
    ktru = a.find(f"{{{COMMON}}}KTRU")
    assert ktru is not None
    ET.SubElement(ktru, f"{{{COMMON}}}rightSideKTRUInfo")
    assert parse_spec(a, notice=True).reasons
    assert parsed(text("A4"), value_type="1", kind="").reasons


def test_normalized_decimals_signature_stable_and_ranges_not_inferred_as_points():
    assert parsed(point("+500.00")).signature == parsed(point("500")).signature
    a = parsed(interval("500"))
    assert a.signature != parsed(point("500")).signature
    assert specifications_bound(a, parsed(interval("500"), notice=False)) is None


def test_observed_notice_metadata_validated_without_becoming_contract_value():
    a = profile(
        text("белая"),
        manual=True,
        value_type="1",
        extra="<p:addCharacteristicInfoReason>Архивное хранение</p:addCharacteristicInfoReason>",
    )
    char = a.find(f".//{{{COMMON}}}characteristicsUsingTextForm")
    assert char is not None
    ET.SubElement(char, f"{{{COMMON}}}sid").text = "123"
    ins = ET.SubElement(char, f"{{{COMMON}}}characteristicsFillingInstruction")
    ET.SubElement(ins, f"{{{BASE}}}code").text = "6"
    assert (
        specifications_bound(
            parse_spec(a, notice=True),
            parsed(text("белая"), notice=False, manual=True, value_type="1"),
        )
        is True
    )
    ins.append(ET.Element(f"{{{BASE}}}unknown"))
    assert parse_spec(a, notice=True).reasons


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.replace("<p:max>5</p:max>", "<p:max/>"),
        lambda v: v.replace("<p:maxMathNotation>lessOrEqual</p:maxMathNotation>", ""),
        lambda v: v.replace("<p:valueRange>", "<p:valueRange><p:min/>"),
        lambda v: v.replace("<p:valueRange>", "<p:valueRange><p:minMathNotation/>"),
        lambda v: v.replace("<p:rangeSet>", '<p:rangeSet unexpected="true">'),
        lambda v: v.replace("<b:code>796</b:code>", "<b:code>796</b:code><b:name/>"),
    ],
)
def test_present_empty_or_partial_bounds_cannot_become_unbounded(mutation):
    assert parsed(mutation(interval(None, "5"))).reasons


def test_unknown_containers_namespace_and_values_attributes_are_not_absence():
    raw = profile(text("A4"), value_type="1")
    values = raw.find(f".//{{{COMMON}}}values")
    assert values is not None
    values.set("ignored", "no")
    assert parse_spec(raw, notice=True).reasons
    raw = profile(text("A4"), value_type="1")
    block = raw.find(f".//{{{COMMON}}}characteristics")
    assert block is not None
    block.tag = "{urn:other}characteristics"
    assert parse_spec(raw, notice=True).reasons
    raw = profile()
    okpd = ET.SubElement(raw, f"{{{COMMON}}}OKPD2")
    ET.SubElement(okpd, f"{{{COMMON}}}characteristics")
    assert parse_spec(raw, notice=True).reasons


def test_48_characteristics_and_48_values_cap_without_silent_truncation():
    raw = profile(text("A4"), value_type="1")
    block = raw.find(f".//{{{COMMON}}}characteristics")
    assert block is not None
    template = ET.tostring(block[0])
    for i in range(1, 48):
        new = ET.fromstring(template)
        name = new.find(f"{{{COMMON}}}name")
        assert name is not None
        name.text = f"Characteristic {i}"
        block.append(new)
    assert not parse_spec(raw, notice=True).reasons
    block.append(ET.fromstring(template))
    assert parse_spec(raw, notice=True).reasons
    assert not parsed("".join(point(str(i)) for i in range(48)), kind="3").reasons
    assert parsed("".join(point(str(i)) for i in range(49)), kind="3").reasons


def test_conflicting_kind_empty_is_not_missing_and_kinds_do_not_silently_match():
    a = parsed(text("A4"), value_type="1", kind="")
    b = parsed(text("A4"), value_type="1", notice=False, kind=None)
    assert a.reasons and specifications_bound(a, b) is None
    a = parsed(text("A4"), value_type="1", kind="1")
    assert specifications_bound(a, b) is None


def test_decimal_equivalence_does_not_depend_on_ambient_decimal_context():
    from decimal import localcontext

    with localcontext() as ctx:
        ctx.prec = 3
        n = parsed(interval("12345678901234567890.12345678901"))
        c = parsed(point("12345678901234567890.12345678901", notice=False), notice=False)
        assert specifications_bound(n, c) is True


def grade(
    value,
    *,
    notice=True,
    instruction="2",
    name="Марка бумаги",
    manual=False,
    kind="1",
    alternative=None,
):
    item = profile(
        text(value) + (text(alternative) if alternative else ""),
        notice=notice,
        manual=manual,
        kind=kind,
        value_type="1",
    )
    ns = COMMON if notice else TYPES
    form = "characteristicsUsingTextForm" if manual else "characteristicsUsingReferenceInfo"
    char = item.find(f"{{{ns}}}KTRU/{{{ns}}}characteristics/{{{ns}}}{form}")
    assert char is not None
    char.find(f"{{{ns}}}name").text = name
    if notice and instruction is not None:
        node = ET.SubElement(char, f"{{{ns}}}characteristicsFillingInstruction")
        ET.SubElement(node, f"{{{BASE}}}code").text = instruction
    return parse_spec(item, notice=notice)


@pytest.mark.parametrize("manual", [True, False])
@pytest.mark.parametrize(
    "minimum,actual", [("Не ниже В", "В"), ("не ниже C", "C"), ("НЕ НИЖЕ Ё", "Е\u0308")]
)
def test_paper_grade_literal_minimum_boundary(minimum, actual, manual):
    requirement = grade(minimum, manual=manual)
    offered = grade(actual, notice=False, manual=manual)
    assert specifications_bound(requirement, offered) is True
    characteristic = requirement.characteristics[0]
    assert characteristic.filling_instruction_code == "2"
    assert characteristic.filling_instruction_locator == (
        f"{characteristic.locator}/characteristicsFillingInstruction/{{{BASE}}}code"
    )
    assert offered.characteristics[0].filling_instruction_locator is None


@pytest.mark.parametrize(
    "minimum,actual,changes",
    [
        ("Не ниже В", "В", {"instruction": None}),
        ("Не ниже В", "В", {"instruction": "6"}),
        ("Не ниже В", "В", {"instruction": "02"}),
        ("Не ниже В", "В", {"instruction": ""}),
        ("Не ниже В", "В", {"name": "Класс бумаги"}),
        ("Не ниже A4", "A4", {}),
        ("Не ниже В или С", "В", {}),
        ("Не ниже B", "В", {}),
        ("Не ниже C", "С", {}),
        ("Не ниже C", "c", {}),
        ("Не ниже В", "С", {}),
        ("Не ниже В.", "В", {}),
        ("Не ниже В", "В", {"alternative": "С", "kind": "3"}),
    ],
)
def test_paper_grade_boundary_requires_exact_bounded_microcontract(minimum, actual, changes):
    requirement = grade(minimum, **changes)
    offered = grade(
        actual,
        notice=False,
        name=changes.get("name", "Марка бумаги"),
        kind=changes.get("kind", "1"),
    )
    assert specifications_bound(requirement, offered) is None


@pytest.mark.parametrize("changes", [{"manual": True}, {"kind": "3"}, {"alternative": "С"}])
def test_paper_grade_boundary_rejects_contract_identity_or_value_alternatives(changes):
    assert specifications_bound(grade("Не ниже В"), grade("В", notice=False, **changes)) is None


def test_instruction_changes_cohort_even_without_value_alternatives():
    profiles = [grade("Не ниже В", instruction=code) for code in (None, "2", "6")]
    assert all(not p.reasons for p in profiles)
    assert len({p.signature for p in profiles}) == 3
    # Instruction 6 still allows exact literal equality, but never the new boundary proof.
    assert specifications_bound(profiles[2], grade("Не ниже В", notice=False)) is True
