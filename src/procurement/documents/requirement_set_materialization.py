"""Server-derived preview and explicit materialization of DOCX requirement rows."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.documents.facts import DocumentRole, map_blocks_to_requirements
from procurement.documents.reviewed_requirements import (
    RequirementEntryDisposition,
    ReviewedRequirementEntry,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement

_TABLE_CELL_RE = re.compile(
    r"^(?P<table>table \d+(?: row \d+ cell \d+ nested table \d+)*)"
    r" row (?P<row>\d+) cell (?P<cell>\d+)$"
)
_CANONICAL_PROPERTY_RE = re.compile(r"^[a-z][a-z0-9_]{1,99}$")


class RequirementSetMaterializationError(ValueError):
    """Exact extraction cannot safely produce the requested table preview."""


class NumericRequirementSuggestion(BaseModel):
    """Non-executable numeric hint copied from the existing table candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    operator: Operator
    value: Decimal
    unit: str | None = Field(default=None, min_length=1, max_length=200)
    source_locators: tuple[str, ...] = Field(min_length=2, max_length=3)


class RequirementTableDraftEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    ordinal: int = Field(ge=1, le=500)
    raw_name: str = Field(min_length=1, max_length=1_000)
    raw_value: str = Field(min_length=1, max_length=4_000)
    instruction: str | None = Field(default=None, min_length=1, max_length=4_000)
    provenance: Provenance
    numeric_suggestion: NumericRequirementSuggestion | None = None


class RequirementSetMaterializationPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["requirement-set-materialization-preview-v1"] = (
        "requirement-set-materialization-preview-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    table_locator: str = Field(min_length=1, max_length=1_000)
    expected_entry_count: int = Field(ge=1, le=500)
    entries: tuple[RequirementTableDraftEntry, ...] = Field(min_length=1, max_length=500)
    numeric_suggestion_count: int = Field(ge=0, le=500)
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _preview_is_complete_and_exact(self) -> Self:
        if len(self.entries) != self.expected_entry_count:
            raise ValueError("preview entries must match expected count")
        if tuple(item.ordinal for item in self.entries) != tuple(
            range(1, self.expected_entry_count + 1)
        ):
            raise ValueError("preview entries must be contiguous and ordered")
        if sum(item.numeric_suggestion is not None for item in self.entries) != (
            self.numeric_suggestion_count
        ):
            raise ValueError("numeric suggestion count does not match entries")
        if any(item.provenance.document_id != self.source_document_id for item in self.entries):
            raise ValueError("preview entry provenance must match source document")
        payload = self.model_dump(mode="json", exclude={"preview_sha256"})
        if canonical_json_sha256(payload) != self.preview_sha256:
            raise ValueError("materialization preview digest does not match payload")
        return self


class ExecutableRequirementSelection(BaseModel):
    """Operator choice to promote one displayed numeric hint into a requirement."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    ordinal: int = Field(ge=1, le=500)
    property: str = Field(min_length=2, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=200)
    mandatory: bool
    review_note: str = Field(min_length=1, max_length=2_000)

    @field_validator("property")
    @classmethod
    def _canonical_property(cls, value: str) -> str:
        normalized = value.strip()
        if _CANONICAL_PROPERTY_RE.fullmatch(normalized) is None:
            raise ValueError("property must be lower snake_case")
        return normalized

    @field_validator("unit", "review_note")
    @classmethod
    def _trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("selection text must not be blank")
        return normalized


def build_requirement_set_materialization_preview(
    *,
    company_id: str,
    source_document_id: str,
    source_document_sha256: str,
    extraction: ExtractionResult,
    expected_entry_count: int,
) -> RequirementSetMaterializationPreview:
    """Find exactly one native DOCX table with the requested complete row count."""
    if extraction.status is not ExtractionStatus.PASS:
        raise RequirementSetMaterializationError("source extraction must be PASS")
    if not 1 <= expected_entry_count <= 500:
        raise RequirementSetMaterializationError("expected entry count is outside bounds")

    tables: dict[str, dict[int, dict[int, ExtractedBlock]]] = {}
    for block in extraction.blocks:
        provenance = block.provenance
        if (
            provenance.document_id != source_document_id
            or provenance.extractor is not Extractor.NATIVE_DOCX
            or provenance.confidence < 0.75
        ):
            continue
        match = _TABLE_CELL_RE.fullmatch(provenance.locator)
        if match is None:
            continue
        tables.setdefault(match.group("table"), {}).setdefault(int(match.group("row")), {})[
            int(match.group("cell"))
        ] = block

    expected_ordinals = set(range(1, expected_entry_count + 1))
    candidates = [
        (locator, rows)
        for locator, rows in tables.items()
        if set(rows) == expected_ordinals
        and all(1 in cells and 2 in cells for cells in rows.values())
    ]
    if len(candidates) != 1:
        raise RequirementSetMaterializationError(
            "expected exactly one complete native DOCX table for the declared row count"
        )
    table_locator, rows = candidates[0]

    mapping = map_blocks_to_requirements(
        extraction.blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )
    suggestions: dict[int, NumericRequirementSuggestion] = {}
    for candidate in mapping.table_row_candidates:
        first = _TABLE_CELL_RE.fullmatch(candidate.source_blocks[0].provenance.locator)
        if first is None or first.group("table") != table_locator:
            continue
        ordinal = int(first.group("row"))
        if ordinal in suggestions:
            raise RequirementSetMaterializationError(
                "one source row produced more than one numeric suggestion"
            )
        suggestions[ordinal] = NumericRequirementSuggestion(
            operator=candidate.operator,
            value=candidate.value,
            unit=candidate.unit,
            source_locators=tuple(item.provenance.locator for item in candidate.source_blocks),
        )

    entries: list[RequirementTableDraftEntry] = []
    for ordinal in range(1, expected_entry_count + 1):
        cells = rows[ordinal]
        name_block = cells[1]
        value_block = cells[2]
        raw_name = name_block.text.strip()
        raw_value = value_block.text.strip()
        if not raw_name or not raw_value:
            raise RequirementSetMaterializationError("source table contains a blank key cell")
        cell_blocks = tuple(cells[index] for index in sorted(cells) if index in (1, 2, 3))
        confidence = min(item.provenance.confidence for item in cell_blocks)
        instruction_block = cells.get(3)
        instruction = None if instruction_block is None else instruction_block.text.strip() or None
        entries.append(
            RequirementTableDraftEntry(
                ordinal=ordinal,
                raw_name=raw_name,
                raw_value=raw_value,
                instruction=instruction,
                provenance=Provenance(
                    document_id=source_document_id,
                    locator=f"{table_locator} row {ordinal}",
                    extractor=Extractor.NATIVE_DOCX,
                    confidence=confidence,
                ),
                numeric_suggestion=suggestions.get(ordinal),
            )
        )

    payload = {
        "schema_version": "requirement-set-materialization-preview-v1",
        "company_id": company_id,
        "source_document_id": source_document_id,
        "source_document_sha256": source_document_sha256,
        "table_locator": table_locator,
        "expected_entry_count": expected_entry_count,
        "entries": tuple(item.model_dump(mode="json") for item in entries),
        "numeric_suggestion_count": len(suggestions),
    }
    return RequirementSetMaterializationPreview(
        company_id=company_id,
        source_document_id=source_document_id,
        source_document_sha256=source_document_sha256,
        table_locator=table_locator,
        expected_entry_count=expected_entry_count,
        entries=tuple(entries),
        numeric_suggestion_count=len(suggestions),
        preview_sha256=canonical_json_sha256(payload),
    )


def materialize_reviewed_requirement_entries(
    preview: RequirementSetMaterializationPreview,
    selections: tuple[ExecutableRequirementSelection, ...],
) -> tuple[ReviewedRequirementEntry, ...]:
    """Apply only explicit selections; every other exact source row stays manual."""
    selected = {item.ordinal: item for item in selections}
    if len(selected) != len(selections):
        raise RequirementSetMaterializationError("selection ordinals must not repeat")
    entries_by_ordinal = {item.ordinal: item for item in preview.entries}
    if any(ordinal not in entries_by_ordinal for ordinal in selected):
        raise RequirementSetMaterializationError("selection ordinal is outside preview")

    result: list[ReviewedRequirementEntry] = []
    for entry in preview.entries:
        selection = selected.get(entry.ordinal)
        if selection is None:
            note = (
                "Числовая подсказка не выбрана оператором; требуется ручная проверка."
                if entry.numeric_suggestion is not None
                else "Безопасная машинная нормализация отсутствует; требуется ручная проверка."
            )
            result.append(
                ReviewedRequirementEntry(
                    ordinal=entry.ordinal,
                    raw_name=entry.raw_name,
                    raw_value=entry.raw_value,
                    provenance=entry.provenance,
                    disposition=RequirementEntryDisposition.MANUAL_REVIEW_REQUIRED,
                    review_note=note,
                )
            )
            continue
        suggestion = entry.numeric_suggestion
        if suggestion is None:
            raise RequirementSetMaterializationError(
                "only a displayed numeric suggestion can become executable"
            )
        requirement = Requirement(
            property=selection.property,
            operator=suggestion.operator,
            value=suggestion.value,
            unit=selection.unit or suggestion.unit,
            mandatory=selection.mandatory,
            raw_text=f"{entry.raw_name}: {entry.raw_value}",
            provenance=entry.provenance,
        )
        result.append(
            ReviewedRequirementEntry(
                ordinal=entry.ordinal,
                raw_name=entry.raw_name,
                raw_value=entry.raw_value,
                provenance=entry.provenance,
                disposition=RequirementEntryDisposition.EXECUTABLE,
                requirement=requirement,
                review_note=selection.review_note,
            )
        )
    return tuple(result)
