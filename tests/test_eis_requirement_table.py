from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.documents.extraction import ExtractedBlock
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources import eis_requirement_table as t
from procurement.sources.eis_document_review import ReviewDocumentAnalysis


def analysis(entries: list[tuple[str, str]]) -> ReviewDocumentAnalysis:
    blocks = tuple(
        ExtractedBlock(
            text=text,
            provenance=Provenance(
                document_id="a" * 64, locator=locator, extractor=Extractor.NATIVE_DOCX
            ),
        )
        for locator, text in entries
    )
    count = len(blocks)
    chars = sum(len(b.text) for b in blocks)
    return ReviewDocumentAnalysis(
        sha256="a" * 64,
        filename="ТЗ.docx",
        byte_count=100,
        extraction_status="PASS",
        extraction_reasons=(),
        source_units_total=count,
        source_units_extracted=count,
        characters_extracted=chars,
        blocks_extracted_total=count,
        blocks=blocks,
        retained_blocks=count,
        retained_characters=chars,
        retention_truncated=False,
        retention_reasons=(),
        retained_extracted_text_complete=True,
    )


def entries() -> list[tuple[str, str]]:
    rows = [
        list(t.HEADERS),
        ["Формат", "качественная", "А4", None, "Указать значение"],
        ["Марка бумаги", "качественная", "не ниже С", None, "Указать значение"],
        ["Количество листов", "количественная", "≥ 500", "Штука", "Указать значение"],
        ["Дополнительные характеристики*"],
        ["Масса бумаги", "количественная", "≥ 80 и < 90", "Грамм", "Указать значение"],
    ]
    return [
        (f"table 2 row {r} cell {c}", text)
        for r, row in enumerate(rows, 1)
        for c, text in enumerate(row, 1)
        if text is not None
    ]


def test_complete_retained_table_keeps_instruction_section_and_open_bounds() -> None:
    source = analysis(entries())
    result = t.build_eis_requirement_table(source, 2)
    assert result.row_count == 5 and result.cell_count == len(source.blocks)
    assert result.total_characters == source.retained_characters
    assert result.rows[3].kind == "CONTEXT_ONLY"
    assert result.rows[0].absent_columns == (4,)
    assert result.rows[0].absent_columns_status == "NO_RETAINED_TEXT"
    assert result.rows[-1].cells[-1].text == "Указать значение"
    assert [(h.operator, h.value) for h in result.rows[-1].numeric_hints] == [
        (">=", Decimal("80")),
        ("<", Decimal("90")),
    ]
    assert result.rows[-1].unit_raw == "Грамм"
    assert result.rows[1].numeric_hints == ()
    assert result.table_structure_status == result.native_text_completeness == "UNKNOWN"
    assert result.header[0].provenance == source.blocks[0].provenance
    assert t.EISRequirementTable.model_validate_json(result.model_dump_json()) == result


def test_missing_instruction_is_absent_text_not_invented_grid() -> None:
    source = analysis([(loc, text) for loc, text in entries() if loc != "table 2 row 2 cell 5"])
    row = t.build_eis_requirement_table(source, 2).rows[0]
    assert row.kind == "CHARACTERISTIC" and row.absent_columns == (4, 5)
    assert len(row.cells) == 3


@pytest.mark.parametrize(
    "bad", ["duplicate", "nested", "column", "gap", "header", "duplicate_label"]
)
def test_reject_ambiguous_topology(bad: str) -> None:
    data = entries()
    if bad == "duplicate":
        data.append(data[-1])
    elif bad == "nested":
        data.append(("table 2 row 2 cell 3 nested table 1 row 1 cell 1", "nested"))
    elif bad == "column":
        data.append(("table 2 row 6 cell 6", "extra"))
    elif bad == "gap":
        data = [(loc, text) for loc, text in data if not loc.startswith("table 2 row 5 ")]
    elif bad == "header":
        data[0] = (data[0][0], "Other")
    else:
        data = [(loc, "Формат" if loc == "table 2 row 3 cell 1" else text) for loc, text in data]
    with pytest.raises(ValueError):
        t.build_eis_requirement_table(analysis(data), 2)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (">= 80,5 и < 90.25", [(">=", Decimal("80.5")), ("<", Decimal("90.25"))]),
        ("= 3", [("==", Decimal("3"))]),
        ("≤ 5", [("<=", Decimal("5"))]),
        ("≥80 и <90 ...", []),
        ("80–90", []),
        ("не ниже С", []),
        ("Сэ", []),
        ("C", []),
        (">=80 Грамм", []),
    ],
)
def test_numeric_hints_only_full_grammar(raw: str, expected: list[tuple[str, Decimal]]) -> None:
    data = [(loc, raw if loc == "table 2 row 6 cell 3" else text) for loc, text in entries()]
    hints = t.build_eis_requirement_table(analysis(data), 2).rows[-1].numeric_hints
    assert [(hint.operator, hint.value) for hint in hints] == expected


@pytest.mark.parametrize(
    "field", ["kind", "numeric_hints", "source_char_count", "provenance", "total_characters"]
)
def test_tamper_rebuild(field: str) -> None:
    result = t.build_eis_requirement_table(analysis(entries()), 2)
    data = result.model_dump()
    if field == "kind":
        data["rows"][-1]["kind"] = "CONTEXT_ONLY"
    elif field == "numeric_hints":
        data["rows"][-1]["numeric_hints"] = ({"operator": "<=", "value": "90"},)
    elif field == "source_char_count":
        data["rows"][-1]["cells"][0]["source_char_count"] = 1
    elif field == "provenance":
        data["rows"][-1]["cells"][0]["provenance"]["document_id"] = "b" * 64
    else:
        data["total_characters"] += 1
    with pytest.raises(ValidationError):
        t.EISRequirementTable.model_validate(data)


def test_limits_and_preconditions() -> None:
    source = analysis(entries())
    for index in [True, 0, 101]:
        with pytest.raises(ValueError):
            t.build_eis_requirement_table(source, index)
    with pytest.raises(ValueError):
        t.build_eis_requirement_table(source.model_copy(update={"extraction_status": "UNKNOWN"}), 2)
    data = entries()
    data[-1] = (data[-1][0], "x" * 2001)
    with pytest.raises(ValueError):
        t.build_eis_requirement_table(analysis(data), 2)
    data = entries() + [(f"table 2 row {r} cell 1", f"context{r}") for r in range(7, 27)]
    with pytest.raises(ValueError):
        t.build_eis_requirement_table(analysis(data), 2)
    with pytest.raises(ValidationError):
        t.NumericHint(operator=">=", value=1.2)


def test_total_character_budget_and_nested_model_copy_tamper() -> None:
    data = entries()
    data = [
        (loc, "x" * 1900 if "cell 5" in loc and "row 1 " not in loc else text) for loc, text in data
    ]
    data += [(f"table 2 row {r} cell 1", "x" * 1900) for r in range(7, 13)]
    with pytest.raises(ValueError):
        t.build_eis_requirement_table(analysis(data), 2)
    result = t.build_eis_requirement_table(analysis(entries()), 2)
    badrow = result.rows[-1].model_copy(update={"numeric_hints": ()})
    values = {name: getattr(result, name) for name in type(result).model_fields}
    values["rows"] = (*result.rows[:-1], badrow)
    with pytest.raises(ValueError):
        t.EISRequirementTable(**values)
