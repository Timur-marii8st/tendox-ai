"""Вложенные изображения DOCX остаются отдельными проверяемыми OCR-источниками."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image

from procurement.cli import main
from procurement.documents.docx_media import (
    DocxMediaIssueCode,
    DocxMediaLimits,
    DocxMediaRejected,
    DocxMediaRejectionCode,
    extract_docx_media,
    ocr_docx_media,
)
from procurement.documents.extraction import DocumentInput, ExtractionStatus
from procurement.documents.ocr import OcrCandidate, OcrEngineInput
from procurement.domain.provenance import Extractor

docx = pytest.importorskip("docx")

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _docx_with_picture(image: bytes = _TINY_PNG) -> bytes:
    document = docx.Document()
    document.add_paragraph("Нативный заголовок")
    document.add_picture(BytesIO(image))
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _png_bytes(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def _append_unreferenced_media(content: bytes) -> bytes:
    source = BytesIO(content)
    output = BytesIO()
    with ZipFile(source) as archive, ZipFile(output, "w", compression=ZIP_DEFLATED) as rebuilt:
        for item in archive.infolist():
            rebuilt.writestr(item, archive.read(item))
        rebuilt.writestr("word/media/unreferenced.png", _TINY_PNG)
    return output.getvalue()


def _input(content: bytes | None = None) -> DocumentInput:
    return DocumentInput(
        document_id="document-version-42",
        filename="technical-specification.docx",
        declared_media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        content=content or _docx_with_picture(),
    )


def _replace_linked_image(content: bytes, replacement: bytes) -> bytes:
    source = BytesIO(content)
    output = BytesIO()
    with ZipFile(source) as archive, ZipFile(output, "w", compression=ZIP_DEFLATED) as rebuilt:
        for item in archive.infolist():
            data = archive.read(item)
            if item.filename.startswith("word/media/"):
                data = replacement
            rebuilt.writestr(item, data)
    return output.getvalue()


def _replace_image_target(content: bytes, target: str) -> bytes:
    output = BytesIO()
    with (
        ZipFile(BytesIO(content)) as archive,
        ZipFile(output, "w", compression=ZIP_DEFLATED) as rebuilt,
    ):
        for item in archive.infolist():
            data = archive.read(item)
            if item.filename == "word/_rels/document.xml.rels":
                data = data.replace(b'Target="media/image1.png"', f'Target="{target}"'.encode())
            rebuilt.writestr(item, data)
    return output.getvalue()


class FakeImageRunner:
    engine = "fake-image-ocr/1"

    def __init__(self) -> None:
        self.sources: list[OcrEngineInput] = []

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]:
        self.sources.append(source)
        assert content == _TINY_PNG
        assert media_type == "image/png"
        return (
            OcrCandidate(
                page_number=1,
                block_index=0,
                text="Требование из изображения",
                confidence=0.98,
                locator="image 1 bbox 1,2,30,40",
            ),
        )


def test_extracts_only_referenced_supported_media_with_digest_and_dimensions() -> None:
    document = _input()

    result = extract_docx_media(document)

    assert result.status is ExtractionStatus.PASS
    assert result.source_document_id == document.document_id
    assert result.source_sha256 == hashlib.sha256(document.content).hexdigest()
    assert result.issues == ()
    assert len(result.media) == 1
    media = result.media[0]
    assert media.source_media_id == "document-version-42:media:0"
    assert media.archive_path == "word/media/image1.png"
    assert media.media_type == "image/png"
    assert media.width == 1
    assert media.height == 1
    assert media.sha256 == hashlib.sha256(_TINY_PNG).hexdigest()
    assert media.content == _TINY_PNG
    assert media.references == ("word/document.xml relationship rId9",)


def test_absolute_package_media_target_is_allowed_only_inside_media_tree() -> None:
    absolute = _replace_image_target(_docx_with_picture(), "/word/media/image1.png")
    result = extract_docx_media(_input(absolute))
    assert result.status is ExtractionStatus.PASS
    assert [item.archive_path for item in result.media] == ["word/media/image1.png"]

    traversal = _replace_image_target(_docx_with_picture(), "/word/media/../media/image1.png")
    with pytest.raises(DocxMediaRejected) as raised:
        extract_docx_media(_input(traversal))
    assert raised.value.code is DocxMediaRejectionCode.UNSAFE_MEDIA_PATH


def test_invalid_linked_image_stays_unknown_without_ocr_source() -> None:
    corrupted = _replace_linked_image(_docx_with_picture(), b"\x89PNG\r\n\x1a\ninvalid")

    result = extract_docx_media(_input(corrupted))

    assert result.status is ExtractionStatus.UNKNOWN
    assert result.media == ()
    assert len(result.issues) == 1
    assert result.issues[0].code is DocxMediaIssueCode.INVALID_IMAGE


def test_unreferenced_package_media_is_not_an_ocr_source() -> None:
    content = _append_unreferenced_media(_docx_with_picture())

    result = extract_docx_media(_input(content))

    assert result.status is ExtractionStatus.PASS
    assert [item.archive_path for item in result.media] == ["word/media/image1.png"]


def test_image_pixel_limit_rejects_before_ocr() -> None:
    content = _docx_with_picture(_png_bytes(2, 2))

    with pytest.raises(DocxMediaRejected) as raised:
        extract_docx_media(_input(content), limits=DocxMediaLimits(max_image_pixels=3))

    assert raised.value.code is DocxMediaRejectionCode.IMAGE_PIXEL_LIMIT


def test_ocr_derivative_keeps_outer_document_and_exact_media_locator() -> None:
    runner = FakeImageRunner()

    report = ocr_docx_media(_input(), runner=runner)

    assert report.status is ExtractionStatus.PASS
    assert len(report.results) == 1
    item = report.results[0]
    assert item.media.source_media_id == "document-version-42:media:0"
    assert item.ocr.source_document_id == item.media.source_media_id
    assert item.ocr.source_sha256 == item.media.sha256
    assert item.ocr.blocks[0].text == "Требование из изображения"
    provenance = item.ocr.blocks[0].provenance
    assert provenance.document_id == item.media.source_media_id
    assert provenance.extractor is Extractor.OCR
    assert provenance.locator == ('DOCX media "word/media/image1.png" :: image 1 bbox 1,2,30,40')
    assert runner.sources == [
        OcrEngineInput(
            source_document_id=item.media.source_media_id,
            source_sha256=item.media.sha256,
            page_count=1,
        )
    ]


def test_cli_publishes_private_report_without_printing_ocr_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = ocr_docx_media(_input(), runner=FakeImageRunner())
    monkeypatch.setattr("procurement.cli.ocr_docx_media_path", lambda *args, **kwargs: report)
    output = tmp_path / "report.json"

    result = main(
        [
            "ocr-docx-media",
            str(tmp_path / "source.docx"),
            "--output",
            str(output),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert result == 0
    assert summary["status"] == "PASS"
    assert summary["media_total"] == 1
    assert "Требование из изображения" not in json.dumps(summary, ensure_ascii=False)
    published = json.loads(output.read_text(encoding="utf-8"))
    assert published["results"][0]["ocr"]["blocks"][0]["text"] == ("Требование из изображения")
    assert "content" not in published["extraction"]["media"][0]
