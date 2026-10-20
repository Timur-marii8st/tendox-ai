"""Read OLE/BIFF8 literal cells; never use cached formula results as evidence."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO, StringIO
from typing import NoReturn

from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    ExtractedBlock,
    ExtractionLimits,
    ExtractionReason,
    ExtractionResult,
    _blocks_from_units,
    _result_or_unknown,
)
from procurement.domain.provenance import Extractor

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass(frozen=True)
class _Inspection:
    formula_cells: dict[str, frozenset[tuple[int, int]]]
    reasons: tuple[ExtractionReason, ...]


def _reject(code: DocumentRejectionCode = DocumentRejectionCode.MALFORMED_CONTAINER) -> NoReturn:
    raise DocumentRejected(code)


def _workbook_stream(content: bytes, limits: ExtractionLimits) -> tuple[bytes, bool]:
    import olefile  # type: ignore[import-untyped]

    with olefile.OleFileIO(BytesIO(content), raise_defects=olefile.DEFECT_INCORRECT) as ole:
        names = ole.listdir(streams=True, storages=True)
        if len(names) > limits.max_zip_members:
            _reject(DocumentRejectionCode.ZIP_MEMBER_LIMIT)
        parts = {part.casefold() for name in names for part in name}
        if any("vba" in part or part == "macros" for part in parts):
            _reject(DocumentRejectionCode.MACRO_ENABLED_FORMAT)
        streams = ole.listdir()
        if sum(ole.get_size(name) for name in streams) > limits.max_zip_expanded_bytes:
            _reject(DocumentRejectionCode.ZIP_EXPANSION_LIMIT)
        books = [
            name
            for name in streams
            if len(name) == 1 and name[0].casefold() in {"workbook", "book"}
        ]
        if len(books) != 1:
            _reject()
        if ole.get_size(books[0]) > limits.max_input_bytes:
            _reject(DocumentRejectionCode.INPUT_TOO_LARGE)
        stream = ole.openstream(books[0]).read()
        if len(stream) != ole.get_size(books[0]) or ole.parsing_issues:
            _reject()
        embedded = any(part == "objectpool" or part.startswith("mbd") for part in parts)
        return stream, embedded


def _inspect_biff(data: bytes, limits: ExtractionLimits, embedded: bool) -> _Inspection:
    offset = 0
    records = 0
    stack: list[tuple[int, int]] = []
    sheets: dict[int, str] = {}
    sheet_bofs: set[int] = set()
    formulas: dict[int, set[tuple[int, int]]] = {}
    reasons: set[ExtractionReason] = set()
    if embedded:
        reasons.add(ExtractionReason.EMBEDDED_MEDIA_IGNORED)
    if len(data) < 8 or data[:2] != b"\x09\x08":
        _reject()
    while offset < len(data):
        if offset + 4 > len(data):
            _reject()
        kind, size = struct.unpack_from("<HH", data, offset)
        if kind == size == 0:
            if any(data[offset:]):
                _reject()
            break  # OLE padding; check remainder once, not once per BIFF record.
        end = offset + 4 + size
        if size > 8224 or end > len(data):
            _reject()
        body = data[offset + 4 : end]
        records += 1
        if records > limits.max_source_units * 4:
            _reject(DocumentRejectionCode.SOURCE_UNIT_LIMIT)
        if kind == 0x002F:  # FILEPASS
            _reject(DocumentRejectionCode.ENCRYPTED_DOCUMENT)
        if kind == 0x0809:  # BOF
            if len(body) < 4:
                _reject()
            version, substream = struct.unpack_from("<HH", body)
            if version != 0x0600:
                _reject(DocumentRejectionCode.UNSUPPORTED_BIFF_VERSION)
            if substream == 0x0040:
                _reject(DocumentRejectionCode.MACRO_ENABLED_FORMAT)
            if substream not in {0x0005, 0x0010, 0x0020}:
                _reject()
            if offset == 0 and substream != 0x0005:
                _reject()
            stack.append((offset, substream))
            if substream == 0x0010:
                sheet_bofs.add(offset)
            if substream == 0x0020:
                reasons.add(ExtractionReason.EMBEDDED_MEDIA_IGNORED)
        elif kind == 0x000A:  # EOF
            if not stack:
                _reject()
            stack.pop()
        elif kind == 0x0085:  # BOUNDSHEET8
            if len(body) < 8:
                _reject()
            position = struct.unpack_from("<I", body)[0]
            sheet_type, count, flags = body[5:8]
            if sheet_type in {1, 6}:
                _reject(DocumentRejectionCode.MACRO_ENABLED_FORMAT)
            if sheet_type not in {0, 2} or flags & ~1:
                _reject()
            length = count * (2 if flags & 1 else 1)
            if count == 0 or len(body) != 8 + length or position in sheets:
                _reject()
            name = body[8:].decode("utf-16-le" if flags & 1 else "latin-1")
            if sheet_type == 0:
                sheets[position] = name
        elif kind == 0x0006:  # FORMULA: cell row/col precede cached value.
            if len(body) < 22:
                _reject()
            sheet = next(
                (position for position, substream in reversed(stack) if substream == 0x0010), None
            )
            if sheet is None:
                _reject()
            row, col = struct.unpack_from("<HH", body)
            formulas.setdefault(sheet, set()).add((row, col))
            reasons.add(ExtractionReason.FORMULAS_IGNORED)
        elif kind == 0x0200:  # DIMENSIONS: guard sheet capacity before xlrd loads cells.
            if len(body) < 12:
                _reject()
            _, rows, _, cols = struct.unpack_from("<IIHH", body)
            if rows * cols > limits.max_source_units:
                _reject(DocumentRejectionCode.SOURCE_UNIT_LIMIT)
        elif kind == 0x01AE:  # SUPBOOK: self links are local; other links stay ignored.
            if len(body) < 4:
                _reject()
            if struct.unpack_from("<H", body, 2)[0] != 0x0401:
                reasons.add(ExtractionReason.EXTERNAL_LINKS_IGNORED)
        elif kind in {0x005D, 0x00EC}:  # OBJ / MSODRAWING
            reasons.add(ExtractionReason.EMBEDDED_MEDIA_IGNORED)
        offset = end
    if stack or not sheets or set(sheets) != sheet_bofs or len(set(sheets.values())) != len(sheets):
        _reject()
    return _Inspection(
        {name: frozenset(formulas.get(position, ())) for position, name in sheets.items()},
        tuple(sorted(reasons, key=lambda reason: reason.value)),
    )


def extract_legacy_xls(document: DocumentInput, limits: ExtractionLimits) -> ExtractionResult:
    """Limits apply before and during parsing; no file/network/Office execution."""
    import xlrd  # type: ignore[import-untyped]

    try:
        data, embedded = _workbook_stream(document.content, limits)
        inspection = _inspect_biff(data, limits, embedded)
        units: list[tuple[str, str]] = []
        capacity = 0
        source_total = 0
        reasons = set(inspection.reasons)
        with xlrd.open_workbook(
            file_contents=document.content, on_demand=True, ragged_rows=True, logfile=StringIO()
        ) as book:
            if book.biff_version != 80 or set(book.sheet_names()) != set(inspection.formula_cells):
                _reject()
            for index in range(book.nsheets):
                sheet = book.sheet_by_index(index)
                capacity += sheet.nrows * sheet.ncols
                if capacity > limits.max_source_units:
                    _reject(DocumentRejectionCode.SOURCE_UNIT_LIMIT)
                ignored = inspection.formula_cells[sheet.name]
                source_total += len(ignored)
                for row in range(sheet.nrows):
                    for col, cell in enumerate(sheet.row(row)):
                        if (row, col) in ignored or cell.ctype in {
                            xlrd.XL_CELL_EMPTY,
                            xlrd.XL_CELL_BLANK,
                        }:
                            continue
                        if cell.ctype not in {xlrd.XL_CELL_TEXT, xlrd.XL_CELL_NUMBER}:
                            source_total += 1
                            reasons.add(ExtractionReason.UNSUPPORTED_SOURCE_UNITS)
                            continue
                        value = (
                            format(Decimal(str(cell.value)).normalize(), "f")
                            if cell.ctype == xlrd.XL_CELL_NUMBER
                            else str(cell.value)
                        )
                        if value.strip():
                            source_total += 1
                            units.append((f"{sheet.name}!{xlrd.formula.cellname(row, col)}", value))
                book.unload_sheet(index)
        blocks: tuple[ExtractedBlock, ...] = _blocks_from_units(
            document.document_id,
            Extractor.NATIVE_XLS,
            units,
            max_characters=limits.max_extracted_characters,
        )
        return _result_or_unknown(
            blocks, source_total, tuple(sorted(reasons, key=lambda reason: reason.value))
        )
    except DocumentRejected:
        raise
    except Exception as error:
        raise DocumentRejected(DocumentRejectionCode.PARSE_FAILED) from error
