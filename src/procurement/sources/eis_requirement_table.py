"""Selected retained native DOCX table text, never approved requirements."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_document_review import ReviewDocumentAnalysis

HEADERS = (
    "Наименование характеристики",
    "Тип характеристики (количественная/качественная)",
    "Значение характеристики",
    "Единица измерения характеристики",
    "Инструкция по заполнению характеристик",
)
MAX_RESPONSE_BYTES = 128 * 1024
_COORDINATE = re.compile(r"table ([1-9][0-9]*) row ([1-9][0-9]*) cell ([1-9][0-9]*)")
_NUMBER = r"[+-]?[0-9]{1,18}(?:[.,][0-9]{1,8})?"
_CONSTRAINT = rf"(>=|<=|==|>|<|=|≥|≤)\s*({_NUMBER})"
_NUMERIC = re.compile(rf"\s*{_CONSTRAINT}(?:\s+и\s+{_CONSTRAINT})?\s*")
Operator = Literal[">=", "<=", ">", "<", "=="]
RowKind = Literal["CONTEXT_ONLY", "CHARACTERISTIC", "MANUAL_REVIEW_REQUIRED"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NumericHint(FrozenModel):
    operator: Operator
    value: Decimal = Field(allow_inf_nan=False, max_digits=26, decimal_places=8)

    @field_validator("value", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("NUMERIC_HINT_FLOAT_FORBIDDEN")
        return value

    @field_serializer("value")
    def decimal_string(self, value: Decimal) -> str:
        return format(value, "f")


def _hints(text: str) -> tuple[NumericHint, ...]:
    match = _NUMERIC.fullmatch(text)
    if match is None:
        return ()
    result = []
    for operator, raw in ((match[1], match[2]), (match[3], match[4])):
        if operator is None:
            continue
        normalized = {"≥": ">=", "≤": "<=", "=": "=="}.get(operator, operator)
        result.append(
            NumericHint.model_validate(
                {"operator": normalized, "value": Decimal(raw.replace(",", "."))}
            )
        )
    return tuple(result)


class RequirementTableCell(FrozenModel):
    source_row: int = Field(ge=1, le=25, strict=True)
    column: int = Field(ge=1, le=5, strict=True)
    text: str = Field(min_length=1, max_length=2000)
    block_index: int = Field(ge=0, le=999, strict=True)
    source_char_count: int = Field(ge=1, le=2000, strict=True)
    provenance: Provenance

    @model_validator(mode="after")
    def evidence(self) -> RequirementTableCell:
        match = _COORDINATE.fullmatch(self.provenance.locator)
        if (
            match is None
            or int(match[2]) != self.source_row
            or int(match[3]) != self.column
            or self.provenance.extractor != Extractor.NATIVE_DOCX
            or self.source_char_count != len(self.text)
            or not self.text.strip()
        ):
            raise ValueError("TABLE_CELL_EVIDENCE_INVALID")
        return self


def _kind(cells: tuple[RequirementTableCell, ...]) -> RowKind:
    if len(cells) == 1 and cells[0].column == 1:
        return "CONTEXT_ONLY"
    columns = {cell.column for cell in cells}
    return "CHARACTERISTIC" if {1, 3} <= columns else "MANUAL_REVIEW_REQUIRED"


class RequirementTableRow(FrozenModel):
    source_row: int = Field(ge=2, le=25, strict=True)
    kind: RowKind
    cells: tuple[RequirementTableCell, ...] = Field(min_length=1, max_length=5)
    absent_columns: tuple[Annotated[int, Field(ge=1, le=5, strict=True)], ...] = Field(max_length=5)
    absent_columns_status: Literal["NO_RETAINED_TEXT"] = "NO_RETAINED_TEXT"
    numeric_hints: tuple[NumericHint, ...] = Field(default=(), max_length=2)
    unit_raw: str | None = Field(default=None, max_length=2000)
    mandatory_status: Literal["UNKNOWN"] = "UNKNOWN"
    approved_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def rebuilt(self) -> RequirementTableRow:
        columns = [cell.column for cell in self.cells]
        if columns != sorted(set(columns)) or any(
            cell.source_row != self.source_row for cell in self.cells
        ):
            raise ValueError("TABLE_ROW_COORDINATES_INVALID")
        expected_absent = tuple(column for column in range(1, 6) if column not in columns)
        values = {cell.column: cell.text for cell in self.cells}
        expected_kind = _kind(self.cells)
        hints = _hints(values[3]) if expected_kind == "CHARACTERISTIC" else ()
        if (
            self.kind != expected_kind
            or self.absent_columns != expected_absent
            or self.numeric_hints != hints
            or self.unit_raw != values.get(4)
        ):
            raise ValueError("TABLE_ROW_DERIVATION_INVALID")
        return self


class EISRequirementTable(FrozenModel):
    revision: Literal["eis-native-requirement-table-v1"] = "eis-native-requirement-table-v1"
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    table_index: int = Field(ge=1, le=100, strict=True)
    header: tuple[RequirementTableCell, ...] = Field(min_length=5, max_length=5)
    rows: tuple[RequirementTableRow, ...] = Field(min_length=1, max_length=24)
    row_count: int = Field(ge=1, le=24, strict=True)
    cell_count: int = Field(ge=6, le=125, strict=True)
    total_characters: int = Field(ge=1, le=16000, strict=True)
    table_structure_status: Literal["UNKNOWN"] = "UNKNOWN"
    native_text_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    approved_requirements: Literal["UNKNOWN"] = "UNKNOWN"
    mandatory_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def evidence(self) -> EISRequirementTable:
        # Nested model_copy instances can bypass their own initial validation.
        for cell in self.header:
            RequirementTableCell.model_validate(cell.model_dump())
        for row in self.rows:
            RequirementTableRow.model_validate(row.model_dump())
        if [cell.column for cell in self.header] != list(range(1, 6)) or any(
            cell.source_row != 1 for cell in self.header
        ):
            raise ValueError("TABLE_HEADER_COORDINATES_INVALID")
        if tuple(" ".join(cell.text.split()) for cell in self.header) != HEADERS:
            raise ValueError("TABLE_HEADER_UNSUPPORTED")
        if [row.source_row for row in self.rows] != list(range(2, len(self.rows) + 2)):
            raise ValueError("TABLE_ROW_GAP")
        cells = (*self.header, *(cell for row in self.rows for cell in row.cells))
        if (
            self.row_count != len(self.rows)
            or self.cell_count != len(cells)
            or self.total_characters != sum(len(cell.text) for cell in cells)
        ):
            raise ValueError("TABLE_COUNTS_INVALID")
        indexes = [cell.block_index for cell in cells]
        if indexes != sorted(set(indexes)):
            raise ValueError("TABLE_BLOCK_ORDER_INVALID")
        labels = [
            " ".join(row.cells[0].text.split()) for row in self.rows if row.kind == "CHARACTERISTIC"
        ]
        if len(set(labels)) != len(labels):
            raise ValueError("TABLE_DUPLICATE_LABEL")
        for cell in cells:
            if (
                cell.provenance.document_id != self.document_sha256
                or cell.provenance.locator
                != f"table {self.table_index} row {cell.source_row} cell {cell.column}"
            ):
                raise ValueError("TABLE_SOURCE_BINDING_INVALID")
        if len(self.model_dump_json().encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("TABLE_RESPONSE_LIMIT")
        return self


def build_eis_requirement_table(
    analysis: ReviewDocumentAnalysis, table_index: int
) -> EISRequirementTable:
    if type(table_index) is not int or not 1 <= table_index <= 100:
        raise ValueError("TABLE_INDEX_INVALID")
    # Revalidate even a caller-created model_copy rather than trusting its apparent model type.
    analysis = ReviewDocumentAnalysis.model_validate(analysis.model_dump())
    if analysis.extraction_status != "PASS" or not analysis.retained_extracted_text_complete:
        raise ValueError("TABLE_RETAINED_TEXT_INCOMPLETE")
    selected: dict[int, list[RequirementTableCell]] = {}
    seen: set[tuple[int, int]] = set()
    prefix = f"table {table_index} "
    for block_index, block in enumerate(analysis.blocks):
        locator = block.provenance.locator
        if not locator.startswith(prefix):
            continue
        match = _COORDINATE.fullmatch(locator)
        if match is None:
            raise ValueError("TABLE_NESTED_OR_UNSUPPORTED_LOCATOR")
        row, column = int(match[2]), int(match[3])
        if (row, column) in seen:
            raise ValueError("TABLE_DUPLICATE_CELL")
        seen.add((row, column))
        cell = RequirementTableCell(
            source_row=row,
            column=column,
            text=block.text,
            block_index=block_index,
            source_char_count=len(block.text),
            provenance=block.provenance,
        )
        selected.setdefault(row, []).append(cell)
    if not selected:
        raise ValueError("TABLE_NOT_RETAINED")
    header = tuple(selected.pop(1, []))
    rows = []
    for row_number, cells_list in sorted(selected.items()):
        cells = tuple(cells_list)
        kind = _kind(cells)
        values = {cell.column: cell.text for cell in cells}
        rows.append(
            RequirementTableRow(
                source_row=row_number,
                kind=kind,
                cells=cells,
                absent_columns=tuple(col for col in range(1, 6) if col not in values),
                numeric_hints=_hints(values[3]) if kind == "CHARACTERISTIC" else (),
                unit_raw=values.get(4),
            )
        )
    all_cells = (*header, *(cell for row in rows for cell in row.cells))
    return EISRequirementTable(
        document_sha256=analysis.sha256,
        table_index=table_index,
        header=header,
        rows=tuple(rows),
        row_count=len(rows),
        cell_count=len(all_cells),
        total_characters=sum(len(cell.text) for cell in all_cells),
    )
