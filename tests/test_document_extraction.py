"""Регрессии безопасного нативного извлечения документов."""

from __future__ import annotations

import base64
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    ExtractionLimits,
    ExtractionReason,
    ExtractionStatus,
    extract_document,
)
from procurement.domain.provenance import Extractor

pypdf = pytest.importorskip("pypdf")
docx = pytest.importorskip("docx")
openpyxl = pytest.importorskip("openpyxl")

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _document(filename: str, media_type: str, content: bytes) -> DocumentInput:
    return DocumentInput(
        document_id="document-version-42",
        filename=filename,
        declared_media_type=media_type,
        content=content,
    )


def _docx_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _docx_with_embedded_image_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    document.add_picture(BytesIO(_TINY_PNG))
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _docx_with_blank_units_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph("   ")
    document.add_paragraph(text)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = ""
    table.cell(0, 1).text = "  "
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _docx_table_bytes(values: tuple[str, ...]) -> bytes:
    document = docx.Document()
    table = document.add_table(rows=2, cols=len(values) // 2)
    for cell, value in zip((cell for row in table.rows for cell in row.cells), values, strict=True):
        cell.text = value
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _docx_nested_table_bytes() -> bytes:
    document = docx.Document()
    outer = document.add_table(rows=1, cols=2)
    outer.cell(0, 0).text = "Outer characteristic"
    outer.cell(0, 1).text = "Sibling cell"
    inner = outer.cell(0, 0).add_table(rows=2, cols=2)
    inner.cell(0, 0).text = "Installed memory"
    inner.cell(0, 1).text = "at least 32 GB"
    inner.cell(1, 0).text = "Storage"
    inner.cell(1, 1).text = "at least 960 GB"
    deeper = inner.cell(1, 0).add_table(rows=1, cols=1)
    deeper.cell(0, 0).text = "Nested note"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _xlsx_bytes(value: str) -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Specification"
    worksheet["B2"] = value
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _xlsx_with_formula_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Economics"
    worksheet["A1"] = "confirmed literal"
    worksheet["B1"] = "=1+1"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _blank_pdf_bytes() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class TestNativeExtraction:
    def test_docx_returns_native_text_with_provenance(self) -> None:
        result = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                _docx_bytes("Paper A4, 500 sheets"),
            )
        )

        assert result.status is ExtractionStatus.PASS
        assert result.source_units_total == 1
        assert result.source_units_extracted == 1
        assert result.blocks[0].text == "Paper A4, 500 sheets"
        assert result.blocks[0].provenance.document_id == "document-version-42"
        assert result.blocks[0].provenance.locator == "paragraph 1"
        assert result.blocks[0].provenance.extractor is Extractor.NATIVE_DOCX

    def test_docx_with_ignored_embedded_image_stays_unknown(self) -> None:
        result = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                _docx_with_embedded_image_bytes("Native heading"),
            )
        )

        assert result.status is ExtractionStatus.UNKNOWN
        assert [block.text for block in result.blocks] == ["Native heading"]
        assert result.reasons == (ExtractionReason.EMBEDDED_MEDIA_IGNORED,)

    def test_docx_blank_units_are_examined_without_looking_unextracted(self) -> None:
        result = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                _docx_with_blank_units_bytes("Native requirement"),
            )
        )

        assert result.status is ExtractionStatus.PASS
        assert result.source_units_total == 1
        assert result.source_units_extracted == 1
        assert [block.text for block in result.blocks] == ["Native requirement"]

    def test_docx_distinct_cells_are_not_lost_to_transient_wrapper_ids(self) -> None:
        values = tuple(f"cell-{number}" for number in range(10))
        content = _docx_table_bytes(values)

        first = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content,
            )
        )
        second = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content,
            )
        )

        assert first == second
        assert first.source_units_total == len(values)
        assert [block.text for block in first.blocks] == list(values)

    def test_docx_nested_tables_keep_each_cell_and_exact_locator(self) -> None:
        content = _docx_nested_table_bytes()
        result = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content,
            )
        )

        assert result.status is ExtractionStatus.PASS
        assert result.source_units_total == 7
        assert result.source_units_extracted == 7
        assert [(block.provenance.locator, block.text) for block in result.blocks] == [
            ("table 1 row 1 cell 1", "Outer characteristic"),
            ("table 1 row 1 cell 1 nested table 1 row 1 cell 1", "Installed memory"),
            ("table 1 row 1 cell 1 nested table 1 row 1 cell 2", "at least 32 GB"),
            ("table 1 row 1 cell 1 nested table 1 row 2 cell 1", "Storage"),
            (
                "table 1 row 1 cell 1 nested table 1 row 2 cell 1 nested table 1 row 1 cell 1",
                "Nested note",
            ),
            ("table 1 row 1 cell 1 nested table 1 row 2 cell 2", "at least 960 GB"),
            ("table 1 row 1 cell 2", "Sibling cell"),
        ]

    def test_docx_nested_tables_count_toward_source_unit_limit(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            extract_document(
                _document(
                    "technical-specification.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    _docx_nested_table_bytes(),
                ),
                limits=ExtractionLimits(max_source_units=6),
            )

        assert raised.value.code is DocumentRejectionCode.SOURCE_UNIT_LIMIT

    def test_docx_nested_text_counts_toward_character_limit(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            extract_document(
                _document(
                    "technical-specification.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    _docx_nested_table_bytes(),
                ),
                limits=ExtractionLimits(max_extracted_characters=40),
            )

        assert raised.value.code is DocumentRejectionCode.EXTRACTED_TEXT_LIMIT

    def test_docx_merged_parent_cell_does_not_duplicate_nested_text(self) -> None:
        document = docx.Document()
        outer = document.add_table(rows=2, cols=1)
        parent = outer.cell(0, 0).merge(outer.cell(1, 0))
        parent.text = "Merged parent"
        parent.add_table(rows=1, cols=1).cell(0, 0).text = "Nested value"
        output = BytesIO()
        document.save(output)

        result = extract_document(
            _document(
                "technical-specification.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                output.getvalue(),
            )
        )

        assert [block.text for block in result.blocks] == ["Merged parent", "Nested value"]
        assert result.source_units_total == 2

    def test_xlsx_exposes_cached_or_literal_cell_value_with_cell_provenance(self) -> None:
        result = extract_document(
            _document(
                "specification.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                _xlsx_bytes("500"),
            )
        )

        assert result.status is ExtractionStatus.PASS
        assert result.source_units_total == 1
        assert result.source_units_extracted == 1
        assert result.blocks[0].text == "500"
        assert result.blocks[0].provenance.locator == "Specification!B2"
        assert result.blocks[0].provenance.extractor is Extractor.NATIVE_XLSX

    def test_xlsx_formula_is_not_a_fact_and_keeps_result_unknown(self) -> None:
        result = extract_document(
            _document(
                "economics.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                _xlsx_with_formula_bytes(),
            )
        )

        assert result.status is ExtractionStatus.UNKNOWN
        assert [block.text for block in result.blocks] == ["confirmed literal"]
        assert ExtractionReason.FORMULAS_IGNORED in result.reasons

    def test_blank_pdf_requires_ocr_and_does_not_produce_facts(self) -> None:
        result = extract_document(_document("scan.pdf", "application/pdf", _blank_pdf_bytes()))

        assert result.status is ExtractionStatus.UNKNOWN
        assert result.blocks == ()
        assert result.reasons == (ExtractionReason.OCR_REQUIRED,)


class TestInputGuards:
    def test_extension_media_and_magic_mismatch_is_rejected(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            extract_document(
                _document(
                    "technical-specification.pdf",
                    "application/pdf",
                    _docx_bytes("not a PDF"),
                )
            )

        assert raised.value.code is DocumentRejectionCode.MAGIC_MISMATCH

    def test_zip_expansion_guard_runs_before_docx_parser(self) -> None:
        payload = BytesIO()
        with ZipFile(payload, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "x" * 10_000)

        with pytest.raises(DocumentRejected) as raised:
            extract_document(
                _document(
                    "technical-specification.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    payload.getvalue(),
                ),
                limits=ExtractionLimits(max_zip_expanded_bytes=100),
            )

        assert raised.value.code is DocumentRejectionCode.ZIP_EXPANSION_LIMIT

    def test_extracted_text_limit_rejects_oversized_result(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            extract_document(
                _document(
                    "technical-specification.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    _docx_bytes("x" * 20),
                ),
                limits=ExtractionLimits(max_extracted_characters=10),
            )

        assert raised.value.code is DocumentRejectionCode.EXTRACTED_TEXT_LIMIT

    def test_unknown_format_stays_unknown(self) -> None:
        result = extract_document(_document("notes.txt", "text/plain", b"untrusted text"))

        assert result.status is ExtractionStatus.UNKNOWN
        assert result.reasons == (ExtractionReason.UNSUPPORTED_FORMAT,)
