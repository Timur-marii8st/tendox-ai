"""Synthetic legacy files must not promote formula caches or unsafe containers."""

import struct
from io import BytesIO
from zipfile import ZipFile

import olefile
import pytest
import xlwt

from procurement.documents.bundle import DocumentBundleRejected, extract_document_bundle
from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    ExtractionLimits,
    extract_document,
)


def xls_bytes(*, formula: bool = False, row: int = 0, col: int = 1) -> bytes:
    book = xlwt.Workbook()
    sheet = book.add_sheet("Лист 1")
    sheet.write(0, 0, "Бумага А4")
    sheet.write(row, col, xlwt.Formula("1+2") if formula else 80)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def source(content: bytes, *, filename: str = "spec.xls") -> DocumentInput:
    return DocumentInput(
        document_id="synthetic-xls",
        filename=filename,
        declared_media_type="application/vnd.ms-excel",
        content=content,
    )


def test_xls_cells_have_native_source_and_formula_cache_is_excluded() -> None:
    result = extract_document(source(xls_bytes()))
    assert result.status == "PASS"
    assert [(block.text, block.provenance.locator) for block in result.blocks] == [
        ("Бумага А4", "Лист 1!A1"),
        ("80", "Лист 1!B1"),
    ]
    assert all(block.provenance.extractor.value == "native_xls" for block in result.blocks)
    formula = extract_document(source(xls_bytes(formula=True)))
    assert formula.status == "UNKNOWN" and "FORMULAS_IGNORED" in formula.reasons
    assert [block.text for block in formula.blocks] == ["Бумага А4"]
    assert formula.source_units_total == 2 and formula.source_units_extracted == 1


def test_xls_limits_and_magic_reject_before_facts() -> None:
    with pytest.raises(DocumentRejected, match="SOURCE_UNIT_LIMIT"):
        extract_document(
            source(xls_bytes(row=30, col=10)), limits=ExtractionLimits(max_source_units=20)
        )
    with pytest.raises(DocumentRejected, match="MAGIC_MISMATCH"):
        extract_document(source(b"<html>cached table</html>"))
    with pytest.raises(DocumentRejected, match="INPUT_TOO_LARGE"):
        extract_document(source(xls_bytes()), limits=ExtractionLimits(max_input_bytes=10))


def test_xls_zip_preserves_member_provenance() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("docs/spec.xls", xls_bytes())
    bundle = extract_document_bundle(
        DocumentInput(
            document_id="synthetic-bundle",
            filename="docs.zip",
            declared_media_type="application/zip",
            content=output.getvalue(),
        )
    )
    assert bundle.status == "PASS" and bundle.supported_members == 1
    assert "docs/spec.xls" in bundle.members[0].extraction.blocks[0].provenance.locator


def mutate_record(content: bytes, kind: int, mutate: object) -> bytes:
    output = BytesIO(content)
    with olefile.OleFileIO(output, write_mode=True) as ole:
        raw = bytearray(ole.openstream("Workbook").read())
        offset = 0
        while offset + 4 <= len(raw):
            record, size = struct.unpack_from("<HH", raw, offset)
            if record == kind:
                mutate(raw, offset)
                ole.write_stream("Workbook", bytes(raw))
                return output.getvalue()
            offset += 4 + size
    raise AssertionError("synthetic record missing")


@pytest.mark.parametrize(
    "case,code",
    [
        ("macro", "MACRO_ENABLED_FORMAT"),
        ("encrypted", "ENCRYPTED_DOCUMENT"),
        ("old-biff", "UNSUPPORTED_BIFF_VERSION"),
    ],
)
def test_xls_unsafe_or_unsupported_records_do_not_become_facts(case: str, code: str) -> None:
    if case == "macro":
        content = mutate_record(
            xls_bytes(), 0x0085, lambda data, offset: data.__setitem__(offset + 9, 1)
        )
    elif case == "encrypted":
        content = mutate_record(
            xls_bytes(), 0x0042, lambda data, offset: struct.pack_into("<H", data, offset, 0x002F)
        )
    else:
        content = mutate_record(
            xls_bytes(),
            0x0809,
            lambda data, offset: struct.pack_into("<H", data, offset + 4, 0x0500),
        )
    with pytest.raises(DocumentRejected, match=code):
        extract_document(source(content))


def test_xls_drawing_is_unknown_not_facts() -> None:
    # Replace a harmless synthetic CODEPAGE record with an ignored drawing.
    content = mutate_record(
        xls_bytes(), 0x0042, lambda data, offset: struct.pack_into("<H", data, offset, 0x00EC)
    )
    result = extract_document(source(content))
    assert result.status == "UNKNOWN" and "EMBEDDED_MEDIA_IGNORED" in result.reasons


def test_malformed_xls_member_rejects_bundle_before_facts() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("fake.xls", b"not an OLE workbook")
    with pytest.raises(DocumentBundleRejected, match="MEMBER_REJECTED"):
        extract_document_bundle(
            DocumentInput(
                document_id="synthetic-fake",
                filename="fake.zip",
                declared_media_type="application/zip",
                content=output.getvalue(),
            )
        )


def test_xls_analysis_retains_sha_and_source_cells() -> None:
    import hashlib

    from procurement.sources.eis_analysis import analyze_document

    content = xls_bytes(formula=True)
    result = analyze_document(content, "spec.xls", "https://example.test/synthetic.xls")
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.status == "UNKNOWN" and result.document_role == "UNKNOWN"
    assert [block.provenance.locator for block in result.blocks] == ["Лист 1!A1"]
