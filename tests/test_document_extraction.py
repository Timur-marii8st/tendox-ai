"""Регрессии безопасного нативного извлечения документов."""

from __future__ import annotations

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

    def test_xlsx_exposes_cached_or_literal_cell_value_with_cell_provenance(self) -> None:
        result = extract_document(
            _document(
                "specification.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                _xlsx_bytes("500"),
            )
        )

        assert result.status is ExtractionStatus.PASS
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
