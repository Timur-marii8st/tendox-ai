"""Pure observation of characteristics from two selected saved EIS positions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Provenance
from procurement.sources.eis_position_evidence import (
    CharacteristicEvidence,
    CharacteristicNumberFact,
    CharacteristicValueEvidence,
    PositionEvidence,
)
from procurement.storage.eis_document_store import NoticeDocumentRef

POLICY_VERSION: Literal["eis-characteristic-observation-v2"] = (
    "eis-characteristic-observation-v2"
)
MAX_REPORT_ROWS = 48
MAX_DECIMAL_DIGITS = 30
MAX_DECIMAL_EXPONENT = 12
ValuePayload = tuple[Literal["DESCRIPTION"], str] | tuple[
    Literal["CONCRETE_VALUES"], tuple[Decimal, ...]
] | tuple[
    Literal["RECORDED_RANGE"],
    tuple[Decimal | None, str | None, Decimal | None, str | None],
]
ValueSignature = tuple[str, ValuePayload]
CharacteristicSignature = tuple[str, tuple[ValueSignature, ...]]


class ObservationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PositionSelection(ObservationModel):
    notice: NoticeDocumentRef
    source_index: int = Field(strict=True, ge=1, le=25)


class CharacteristicPairRequest(ObservationModel):
    target: PositionSelection
    candidate: PositionSelection


class SavedPosition(ObservationModel):
    selection: PositionSelection
    position: PositionEvidence
    storage_kind: Literal["SAVED_NOTICE_FIELDS", "SAVED_PROJECTION"]
    legacy_values_unknown: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_inexact_raw_numbers(cls, data: object) -> object:
        """Do not let bool/float source facts become Decimal during nested parsing."""

        def check(value: object) -> None:
            if isinstance(value, Mapping):
                fact_value = value.get("value")
                if isinstance(fact_value, (float, bool)):
                    raise ValueError("SAVED_POSITION_INEXACT_DECIMAL")
                for nested in value.values():
                    check(nested)
            elif isinstance(value, (tuple, list)):
                for nested in value:
                    check(nested)

        check(data)
        return data

    @model_validator(mode="after")
    def exact_selected_source(self) -> SavedPosition:
        if self.position.source_index != self.selection.source_index:
            raise ValueError("POSITION_SELECTION_INDEX_MISMATCH")

        expected = self.selection.notice.notice_xml_sha256

        def check(value: object) -> None:
            if isinstance(value, Provenance):
                if value.document_id != expected:
                    raise ValueError("POSITION_SELECTION_PROVENANCE_MISMATCH")
            elif isinstance(value, BaseModel):
                for field_name in type(value).model_fields:
                    check(getattr(value, field_name))
            elif isinstance(value, tuple):
                for item in value:
                    check(item)

        check(self.position)

        def coherent(total: int, length: int, truncated: bool) -> bool:
            return total > length if truncated else total == length

        position = self.position
        if not coherent(
            position.characteristics_total,
            len(position.characteristics),
            position.characteristics_truncated,
        ):
            raise ValueError("POSITION_CHARACTERISTIC_CARDINALITY_MISMATCH")
        for characteristic in position.characteristics:
            if not coherent(
                characteristic.values_total,
                len(characteristic.values),
                characteristic.truncated,
            ):
                raise ValueError("CHARACTERISTIC_VALUE_CARDINALITY_MISMATCH")
            for value in characteristic.values:
                if not coherent(
                    value.concrete_values_total,
                    len(value.concrete_values),
                    value.concrete_values_truncated,
                ):
                    raise ValueError("CONCRETE_VALUE_CARDINALITY_MISMATCH")

        def check_decimals(value: object) -> None:
            if isinstance(value, Decimal):
                if not _bounded(value):
                    raise ValueError("SAVED_POSITION_DECIMAL_OUT_OF_BOUNDS")
            elif isinstance(value, BaseModel):
                for field_name in type(value).model_fields:
                    check_decimals(getattr(value, field_name))
            elif isinstance(value, tuple):
                for item in value:
                    check_decimals(item)

        check_decimals(position)
        return self


class CharacteristicPairRow(ObservationModel):
    name: str
    target_indices: tuple[int, ...]
    candidate_indices: tuple[int, ...]
    target_values: tuple[CharacteristicValueEvidence, ...] = Field(max_length=8)
    candidate_values: tuple[CharacteristicValueEvidence, ...] = Field(max_length=8)
    observation: Literal["SAME", "DIFFERENT", "UNKNOWN"]
    reason: str
    target_provenance: Provenance
    candidate_provenance: Provenance


class CharacteristicPairReport(ObservationModel):
    request: CharacteristicPairRequest
    checked_at: datetime
    policy_version: Literal["eis-characteristic-observation-v2"] = POLICY_VERSION
    scope: Literal["SELECTED_SAVED_POSITION_PAIR"] = "SELECTED_SAVED_POSITION_PAIR"
    target: SavedPosition
    candidate: SavedPosition
    rows: tuple[CharacteristicPairRow, ...] = Field(max_length=MAX_REPORT_ROWS)
    row_count: int = Field(ge=0, le=MAX_REPORT_ROWS)
    same_count: int = Field(ge=0, le=MAX_REPORT_ROWS)
    different_count: int = Field(ge=0, le=MAX_REPORT_ROWS)
    unknown_count: int = Field(ge=0, le=MAX_REPORT_ROWS)
    source_requests: Literal[0] = 0
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    delivery_region: Literal["UNKNOWN"] = "UNKNOWN"
    comparability: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    profit: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def exact_report(self) -> CharacteristicPairReport:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        if self.target.selection != self.request.target:
            raise ValueError("TARGET_SELECTION_MISMATCH")
        if self.candidate.selection != self.request.candidate:
            raise ValueError("CANDIDATE_SELECTION_MISMATCH")
        counts = {
            status: sum(row.observation == status for row in self.rows)
            for status in ("SAME", "DIFFERENT", "UNKNOWN")
        }
        if (
            self.row_count != len(self.rows)
            or self.same_count != counts["SAME"]
            or self.different_count != counts["DIFFERENT"]
            or self.unknown_count != counts["UNKNOWN"]
        ):
            raise ValueError("CHARACTERISTIC_REPORT_COUNT_MISMATCH")
        return self


def _normalize_name(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _display_name(
    target: tuple[tuple[int, CharacteristicEvidence], ...],
    candidate: tuple[tuple[int, CharacteristicEvidence], ...],
) -> str:
    for _, characteristic in (*target, *candidate):
        if characteristic.name.value and characteristic.name.value.strip():
            return " ".join(characteristic.name.value.split())
    return ""


def _bounded(value: Decimal) -> bool:
    digits = value.as_tuple().digits
    return (
        value.is_finite()
        and len(digits) <= MAX_DECIMAL_DIGITS
        and abs(cast(int, value.as_tuple().exponent)) <= MAX_DECIMAL_EXPONENT
        and abs(value.adjusted()) <= MAX_DECIMAL_EXPONENT
    )


def _value_signature(value: CharacteristicValueEvidence) -> ValueSignature | None:
    if value.concrete_values_truncated or value.concrete_values_total != len(value.concrete_values):
        return None
    unit = value.unit.value
    if unit is None or not unit.strip():
        return None
    description = value.description.value
    has_description = description is not None and bool(description.strip())
    has_numbers = bool(value.concrete_values)
    range_fields = (
        value.minimum.value,
        value.minimum.raw,
        value.minimum_operator.value,
        value.maximum.value,
        value.maximum.raw,
        value.maximum_operator.value,
    )
    has_range = (
        value.range_source_complete
        or value.minimum.raw_truncated
        or value.maximum.raw_truncated
        or any(item is not None for item in range_fields)
    )
    if sum((has_description, has_numbers, has_range)) != 1:
        return None
    if has_description:
        return (unit, ("DESCRIPTION", cast(str, description)))
    if has_numbers:
        numbers: list[Decimal] = []
        for fact in value.concrete_values:
            if fact.value is None or fact.raw_truncated or not _bounded(fact.value):
                return None
            numbers.append(fact.value)
        return (unit, ("CONCRETE_VALUES", tuple(numbers)))
    if not value.range_source_complete:
        return None

    def bound(
        fact: CharacteristicNumberFact, operator: str | None, allowed: set[str]
    ) -> tuple[Decimal | None, str | None] | None:
        raw = fact.raw
        if fact.raw_truncated:
            return None
        if raw is None:
            return (None, None) if fact.value is None and operator is None else None
        if not raw:
            return None
        try:
            parsed = Decimal(raw)
        except InvalidOperation:
            return None
        if (
            not parsed.is_finite()
            or not _bounded(parsed)
            or fact.value is None
            or parsed != fact.value
            or operator not in allowed
        ):
            return None
        return parsed, operator

    minimum = bound(
        value.minimum,
        value.minimum_operator.value,
        {"greater", "greaterOrEqual"},
    )
    maximum = bound(
        value.maximum,
        value.maximum_operator.value,
        {"less", "lessOrEqual"},
    )
    if minimum is None or maximum is None or (minimum[0] is None and maximum[0] is None):
        return None
    if minimum[0] is not None and maximum[0] is not None:
        if minimum[0] > maximum[0]:
            return None
        if minimum[0] == maximum[0] and (
            minimum[1] != "greaterOrEqual" or maximum[1] != "lessOrEqual"
        ):
            return None
    return (
        unit,
        ("RECORDED_RANGE", (minimum[0], minimum[1], maximum[0], maximum[1])),
    )


def _characteristic_signature(
    characteristic: CharacteristicEvidence,
) -> CharacteristicSignature | None:
    instruction = characteristic.instruction_code.value
    if (
        instruction is None
        or not instruction.strip()
        or characteristic.truncated
        or characteristic.values_total != len(characteristic.values)
        or not characteristic.values
    ):
        return None
    values = tuple(_value_signature(value) for value in characteristic.values)
    if any(value is None for value in values):
        return None
    complete_values: tuple[ValueSignature, ...] = tuple(
        value for value in values if value is not None
    )
    if len({value[1][0] for value in complete_values}) != 1:
        return None
    return instruction, complete_values


def _complete_position(saved: SavedPosition) -> bool:
    position = saved.position
    return (
        not saved.legacy_values_unknown
        and position.characteristics_status == "SOURCE_VALUES"
        and not position.characteristics_truncated
        and position.characteristics_total == len(position.characteristics)
    )


def build_characteristic_pair_report(
    request: CharacteristicPairRequest,
    target: SavedPosition,
    candidate: SavedPosition,
    now: datetime,
) -> CharacteristicPairReport:
    """Compare exact complete stored values; never infer technical compliance."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if target.selection != request.target:
        raise ValueError("TARGET_SELECTION_MISMATCH")
    if candidate.selection != request.candidate:
        raise ValueError("CANDIDATE_SELECTION_MISMATCH")

    def grouped(
        position: PositionEvidence,
    ) -> dict[str, tuple[tuple[int, CharacteristicEvidence], ...]]:
        result: dict[str, tuple[tuple[int, CharacteristicEvidence], ...]] = {}
        for index, characteristic in enumerate(position.characteristics, 1):
            key = _normalize_name(characteristic.name.value)
            result[key] = (*result.get(key, ()), (index, characteristic))
        return result

    target_groups = grouped(target.position)
    candidate_groups = grouped(candidate.position)
    keys = tuple(dict.fromkeys((*target_groups, *candidate_groups)))[:MAX_REPORT_ROWS]
    rows: list[CharacteristicPairRow] = []
    positions_complete = _complete_position(target) and _complete_position(candidate)
    for key in keys:
        target_group = target_groups.get(key, ())
        candidate_group = candidate_groups.get(key, ())
        target_characteristic = target_group[0][1] if target_group else None
        candidate_characteristic = candidate_group[0][1] if candidate_group else None
        observation: Literal["SAME", "DIFFERENT", "UNKNOWN"] = "UNKNOWN"
        reason = "INCOMPLETE_OR_TRUNCATED_SAVED_VALUES"
        if not key:
            reason = "BLANK_CHARACTERISTIC_NAME"
        elif len(target_group) != 1 or len(candidate_group) != 1:
            reason = "DUPLICATE_OR_UNMATCHED_CHARACTERISTIC_NAME"
        elif positions_complete:
            assert target_characteristic is not None
            assert candidate_characteristic is not None
            target_signature = _characteristic_signature(target_characteristic)
            candidate_signature = _characteristic_signature(candidate_characteristic)
            if target_signature is None or candidate_signature is None:
                reason = "UNSUPPORTED_OR_INCOMPLETE_VALUE_SHAPE"
            elif target_signature[0] != candidate_signature[0]:
                reason = "FILLING_INSTRUCTION_NOT_EXPLICITLY_EQUAL"
            elif tuple(value[0] for value in target_signature[1]) != tuple(
                value[0] for value in candidate_signature[1]
            ):
                reason = "UNITS_NOT_EXPLICITLY_EQUAL"
            elif tuple(value[1][0] for value in target_signature[1]) != tuple(
                value[1][0] for value in candidate_signature[1]
            ):
                reason = "MIXED_VALUE_SHAPES"
            else:
                observation = "SAME" if target_signature == candidate_signature else "DIFFERENT"
                reason = (
                    "EXACT_COMPLETE_STORED_VALUES_EQUAL"
                    if observation == "SAME"
                    else ("EXACT_COMPLETE_STORED_VALUES_DIFFER")
                )
        rows.append(
            CharacteristicPairRow(
                name=_display_name(target_group, candidate_group),
                target_indices=tuple(index for index, _ in target_group),
                candidate_indices=tuple(index for index, _ in candidate_group),
                target_values=tuple(
                    value for _, characteristic in target_group for value in characteristic.values
                )[:8],
                candidate_values=tuple(
                    value
                    for _, characteristic in candidate_group
                    for value in characteristic.values
                )[:8],
                observation=observation,
                reason=reason,
                target_provenance=(
                    target_characteristic.name.provenance
                    if target_characteristic is not None and target_characteristic.name.value
                    else target.position.provenance
                ),
                candidate_provenance=(
                    candidate_characteristic.name.provenance
                    if candidate_characteristic is not None and candidate_characteristic.name.value
                    else candidate.position.provenance
                ),
            )
        )
    row_tuple = tuple(rows)
    return CharacteristicPairReport(
        request=request,
        checked_at=now,
        target=target,
        candidate=candidate,
        rows=row_tuple,
        row_count=len(row_tuple),
        same_count=sum(row.observation == "SAME" for row in row_tuple),
        different_count=sum(row.observation == "DIFFERENT" for row in row_tuple),
        unknown_count=sum(row.observation == "UNKNOWN" for row in row_tuple),
    )
