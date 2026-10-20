"""Saved characteristic observations stay conservative and source-bound."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import DecimalFact, TextFact
from procurement.sources.eis_characteristic_compare import (
    CharacteristicPairRequest,
    PositionSelection,
    SavedPosition,
    build_characteristic_pair_report,
)
from procurement.sources.eis_position_evidence import (
    CharacteristicEvidence,
    CharacteristicNumberFact,
    CharacteristicValueEvidence,
    PositionEvidence,
)
from procurement.storage.eis_document_store import NoticeDocumentRef

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def provenance(sha: str, locator: str = "notice.xml :: item[1]") -> Provenance:
    return Provenance(document_id=sha, locator=locator, extractor=Extractor.API)


def text(value: str | None, sha: str, locator: str = "fact") -> TextFact:
    return TextFact(value=value, raw=value, provenance=provenance(sha, locator))


def number(value: str | None, sha: str, *, raw_truncated: bool = False):
    return CharacteristicNumberFact(
        value=Decimal(value) if value is not None else None,
        raw=value,
        raw_truncated=raw_truncated,
        provenance=provenance(sha, "number"),
    )


def value(
    sha: str,
    *,
    description: str | None = "Белый",
    concrete: tuple[str, ...] = (),
    unit: str | None = "шт",
    minimum: str | None = None,
    minimum_operator: str | None = None,
    maximum: str | None = None,
    maximum_operator: str | None = None,
    range_source_complete: bool = False,
    total: int | None = None,
    truncated: bool = False,
) -> CharacteristicValueEvidence:
    values = tuple(number(item, sha) for item in concrete)
    return CharacteristicValueEvidence(
        description=text(description, sha),
        minimum=number(minimum, sha),
        minimum_operator=text(minimum_operator, sha),
        maximum=number(maximum, sha),
        maximum_operator=text(maximum_operator, sha),
        unit=text(unit, sha),
        concrete_values=values,
        concrete_values_total=len(values) if total is None else total,
        concrete_values_truncated=truncated,
        range_source_complete=range_source_complete,
    )


def characteristic(
    name: str | None,
    sha: str,
    *,
    values: tuple[CharacteristicValueEvidence, ...] | None = None,
    instruction: str | None = "2",
    total: int | None = None,
    truncated: bool = False,
) -> CharacteristicEvidence:
    selected = values if values is not None else (value(sha),)
    return CharacteristicEvidence(
        name=text(name, sha, "characteristic/name"),
        instruction_code=text(instruction, sha, "characteristic/instruction"),
        values=selected,
        values_total=len(selected) if total is None else total,
        truncated=truncated,
    )


def saved(
    sha: str,
    characteristics: tuple[CharacteristicEvidence, ...],
    *,
    source_index: int = 1,
    total: int | None = None,
    truncated: bool = False,
    legacy: bool = False,
) -> SavedPosition:
    selection = PositionSelection(
        notice=NoticeDocumentRef(
            purchase_number="0" * 19,
            version_number=1,
            notice_xml_sha256=sha,
        ),
        source_index=source_index,
    )
    p = provenance(sha)
    unknown_text = text(None, sha)
    unknown_decimal = DecimalFact(value=None, raw=None, provenance=p)
    position = PositionEvidence(
        source_index=source_index,
        name=text("Товар", sha),
        quantity=unknown_decimal,
        unit=unknown_text,
        classification_code=unknown_text,
        ktru_code=text("17.12.14.110-00000001", sha),
        unit_price=unknown_decimal,
        line_sum=unknown_decimal,
        currency=unknown_text,
        characteristics=characteristics,
        characteristics_total=(
            len(characteristics) + int(truncated) if total is None else total
        ),
        characteristics_truncated=truncated,
        characteristics_status="SOURCE_VALUES" if characteristics else "UNKNOWN",
        provenance=p,
    )
    return SavedPosition(
        selection=selection,
        position=position,
        storage_kind="SAVED_PROJECTION",
        legacy_values_unknown=legacy,
    )


def report(target: SavedPosition, candidate: SavedPosition):
    request = CharacteristicPairRequest(
        target=target.selection,
        candidate=candidate.selection,
    )
    return build_characteristic_pair_report(request, target, candidate, NOW)


def test_same_ktru_does_not_hide_different_complete_characteristic():
    left = saved("a" * 64, (characteristic(" Цвет ", "a" * 64),))
    right = saved(
        "b" * 64,
        (characteristic("цвет", "b" * 64, values=(value("b" * 64, description="Синий"),)),),
    )
    result = report(left, right)
    assert result.rows[0].observation == "DIFFERENT"
    assert result.different_count == 1 and result.source_requests == 0
    assert result.technical == result.participation == result.profit == "UNKNOWN"


@pytest.mark.parametrize(
    "left,right",
    [
        ((characteristic("Цвет", "a" * 64),), ()),
        (
            (characteristic("Цвет", "a" * 64), characteristic(" цвет ", "a" * 64)),
            (characteristic("Цвет", "b" * 64),),
        ),
        ((characteristic(None, "a" * 64),), (characteristic(None, "b" * 64),)),
    ],
)
def test_missing_duplicate_unmatched_or_blank_names_are_unknown(left, right):
    result = report(saved("a" * 64, left), saved("b" * 64, right))
    assert result.rows and all(row.observation == "UNKNOWN" for row in result.rows)


def test_nested_and_position_truncation_are_unknown_and_raw_range_is_retained():
    ranged = value(
        "a" * 64,
        description=None,
        minimum="10",
        minimum_operator="greaterOrEqual",
    )
    left = saved("a" * 64, (characteristic("Размер", "a" * 64, values=(ranged,)),))
    right = saved(
        "b" * 64,
        (
            characteristic(
                "Размер", "b" * 64, values=(value("b" * 64),), total=2, truncated=True
            ),
        ),
        truncated=True,
    )
    row = report(left, right).rows[0]
    assert row.observation == "UNKNOWN"
    assert row.target_values[0].minimum.raw == "10"


def test_range_overlap_units_and_missing_instruction_never_compare():
    cases = [
        (
            value("a" * 64, description=None, minimum="10", minimum_operator="greaterOrEqual"),
            value("b" * 64, description=None, minimum="20", minimum_operator="greaterOrEqual"),
            "2",
            "2",
        ),
        (value("a" * 64, unit="шт"), value("b" * 64, unit="кг"), "2", "2"),
        (value("a" * 64), value("b" * 64), None, None),
    ]
    for left_value, right_value, left_instruction, right_instruction in cases:
        left = saved(
            "a" * 64,
            (
                characteristic(
                    "Параметр", "a" * 64, values=(left_value,), instruction=left_instruction
                ),
            ),
        )
        right = saved(
            "b" * 64,
            (
                characteristic(
                    "Параметр", "b" * 64, values=(right_value,), instruction=right_instruction
                ),
            ),
        )
        assert report(left, right).rows[0].observation == "UNKNOWN"


def recorded_range(
    sha: str,
    *,
    minimum: str | None = "500",
    minimum_operator: str | None = "greaterOrEqual",
    maximum: str | None = None,
    maximum_operator: str | None = None,
    unit: str = "Штука",
) -> CharacteristicValueEvidence:
    return value(
        sha,
        description=None,
        unit=unit,
        minimum=minimum,
        minimum_operator=minimum_operator,
        maximum=maximum,
        maximum_operator=maximum_operator,
        range_source_complete=True,
    )


def test_exact_recorded_live_range_is_same_and_policy_is_v2():
    left = saved(
        "a" * 64,
        (characteristic("Листов в пачке", "a" * 64, values=(recorded_range("a" * 64),)),),
    )
    right = saved(
        "b" * 64,
        (characteristic("Листов в пачке", "b" * 64, values=(recorded_range("b" * 64),)),),
    )
    result = report(left, right)
    assert result.policy_version == "eis-characteristic-observation-v2"
    assert result.rows[0].observation == "SAME"
    assert result.rows[0].reason == "EXACT_COMPLETE_STORED_VALUES_EQUAL"
    assert result.technical == result.delivery_region == result.profit == "UNKNOWN"


def test_different_complete_recorded_ranges_are_different_with_decimal_precision():
    left_range = recorded_range(
        "a" * 64, minimum="-0", maximum="1.000000000001", maximum_operator="lessOrEqual"
    )
    right_range = recorded_range(
        "b" * 64, minimum="0", maximum="1.000000000002", maximum_operator="lessOrEqual"
    )
    left = saved("a" * 64, (characteristic("Диапазон", "a" * 64, values=(left_range,)),))
    right = saved("b" * 64, (characteristic("Диапазон", "b" * 64, values=(right_range,)),))
    assert report(left, right).rows[0].observation == "DIFFERENT"


@pytest.mark.parametrize(
    "update",
    [
        {"range_source_complete": False},
        {"description": "mixed"},
        {"minimum_operator": "unknown"},
        {"maximum_operator": "lessOrEqual"},
        {"minimum_raw": ""},
        {"maximum_raw": "sNaN", "maximum_value": "1", "maximum_operator": "lessOrEqual"},
        {"maximum_raw": "Infinity", "maximum_value": "1", "maximum_operator": "lessOrEqual"},
        {"minimum": "10", "maximum": "5", "maximum_operator": "lessOrEqual"},
        {
            "minimum": "5",
            "minimum_operator": "greater",
            "maximum": "5",
            "maximum_operator": "lessOrEqual",
        },
        {"minimum_raw_truncated": True},
    ],
)
def test_incomplete_malformed_or_empty_recorded_ranges_stay_unknown(update):
    source = recorded_range("a" * 64)
    payload = source.model_dump()
    if "range_source_complete" in update:
        payload["range_source_complete"] = update["range_source_complete"]
    if "description" in update:
        payload["description"]["value"] = update["description"]
    if "minimum" in update:
        payload["minimum"]["value"] = Decimal(update["minimum"])
        payload["minimum"]["raw"] = update["minimum"]
    if "maximum" in update:
        payload["maximum"]["value"] = Decimal(update["maximum"])
        payload["maximum"]["raw"] = update["maximum"]
    for name in ("minimum_operator", "maximum_operator"):
        if name in update:
            payload[name]["value"] = update[name]
    for name in ("minimum_raw", "maximum_raw"):
        if name in update:
            payload[name.removesuffix("_raw")]["raw"] = update[name]
    if "maximum_value" in update:
        payload["maximum"]["value"] = Decimal(update["maximum_value"])
    if update.get("minimum_raw_truncated"):
        payload["minimum"]["raw_truncated"] = True
    invalid = CharacteristicValueEvidence.model_validate(payload)
    left = saved("a" * 64, (characteristic("Диапазон", "a" * 64, values=(invalid,)),))
    right = saved(
        "b" * 64,
        (characteristic("Диапазон", "b" * 64, values=(recorded_range("b" * 64),)),),
    )
    assert report(left, right).rows[0].observation == "UNKNOWN"


@pytest.mark.parametrize(
    "unit,instruction",
    [("Килограмм", "2"), ("Штука", "3")],
)
def test_recorded_range_requires_matching_unit_and_instruction(unit, instruction):
    left = saved(
        "a" * 64,
        (characteristic("Диапазон", "a" * 64, values=(recorded_range("a" * 64),)),),
    )
    right = saved(
        "b" * 64,
        (
            characteristic(
                "Диапазон",
                "b" * 64,
                values=(recorded_range("b" * 64, unit=unit),),
                instruction=instruction,
            ),
        ),
    )
    assert report(left, right).rows[0].observation == "UNKNOWN"


@pytest.mark.parametrize("bound", ["minimum", "maximum"])
@pytest.mark.parametrize("raw_truncated", [False, True])
def test_unparsed_or_truncated_raw_range_with_description_is_unknown(bound, raw_truncated):
    left_value = value("a" * 64)
    payload = left_value.model_dump()
    payload[bound]["raw"] = "invalid range"
    payload[bound]["raw_truncated"] = raw_truncated
    left_value = CharacteristicValueEvidence.model_validate(payload)
    left = saved(
        "a" * 64,
        (characteristic("Параметр", "a" * 64, values=(left_value,)),),
    )
    right = saved("b" * 64, (characteristic("Параметр", "b" * 64),))
    assert report(left, right).rows[0].observation == "UNKNOWN"


def test_decimal_comparison_is_exact_and_unsafe_precision_is_unknown():
    left_value = value("a" * 64, description=None, concrete=("1.000000000001",))
    right_value = value("b" * 64, description=None, concrete=("1.000000000002",))
    left = saved("a" * 64, (characteristic("Число", "a" * 64, values=(left_value,)),))
    right = saved("b" * 64, (characteristic("Число", "b" * 64, values=(right_value,)),))
    assert report(left, right).rows[0].observation == "DIFFERENT"
    unsafe = value("b" * 64, description=None, concrete=("1e-13",))
    with pytest.raises(ValidationError, match="DECIMAL_OUT_OF_BOUNDS"):
        saved("b" * 64, (characteristic("Число", "b" * 64, values=(unsafe,)),))


def test_description_and_concrete_shapes_cannot_be_compared():
    described = saved("a" * 64, (characteristic("Число", "a" * 64),))
    concrete_value = value("b" * 64, description=None, concrete=("1",))
    concrete = saved(
        "b" * 64,
        (characteristic("Число", "b" * 64, values=(concrete_value,)),),
    )
    row = report(described, concrete).rows[0]
    assert row.observation == "UNKNOWN" and row.reason == "MIXED_VALUE_SHAPES"


def test_selection_strict_index_provenance_ref_and_legacy_guards():
    with pytest.raises(ValidationError):
        PositionSelection(
            notice=NoticeDocumentRef(
                purchase_number="0" * 19,
                version_number=1,
                notice_xml_sha256="a" * 64,
            ),
            source_index="1",
        )
    left = saved("a" * 64, (characteristic("Цвет", "a" * 64),), legacy=True)
    right = saved("b" * 64, (characteristic("Цвет", "b" * 64),))
    assert report(left, right).rows[0].observation == "UNKNOWN"
    payload = right.model_dump()
    payload["selection"]["notice"]["notice_xml_sha256"] = "c" * 64
    with pytest.raises(ValidationError, match="PROVENANCE_MISMATCH"):
        SavedPosition.model_validate(payload)
    payload = right.model_dump()
    payload["position"]["quantity"]["value"] = True
    with pytest.raises(ValidationError, match="INEXACT_DECIMAL"):
        SavedPosition.model_validate(payload)
    payload = right.model_dump()
    payload["position"]["quantity"]["value"] = Decimal("1e13")
    with pytest.raises(ValidationError, match="DECIMAL_OUT_OF_BOUNDS"):
        SavedPosition.model_validate(payload)
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        build_characteristic_pair_report(
            CharacteristicPairRequest(target=left.selection, candidate=right.selection),
            left,
            right,
            datetime(2026, 1, 1),
        )


def test_empty_positions_have_empty_unknown_report():
    result = report(saved("a" * 64, ()), saved("b" * 64, ()))
    assert result.rows == () and result.row_count == 0
    assert result.coverage == result.comparability == "UNKNOWN"
