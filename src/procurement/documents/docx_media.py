"""Безопасные OCR-источники из явно связанных изображений DOCX.

Файлы из ``word/media`` сами по себе не считаются содержимым документа. Модуль
следует только внутренним image relationships, которые реально используются в
XML-части DOCX, проверяет immutable bytes и возвращает отдельные media sources.
Нативный текст документа не объединяется с OCR автоматически.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
import tempfile
import unicodedata
import warnings
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal, Self
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import (
    DEFAULT_EXTRACTION_LIMITS,
    MAX_UPLOAD_BYTES,
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    extract_document,
)
from procurement.documents.ocr import (
    DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    OcrCandidate,
    OcrDerivative,
    OcrEngineError,
    OcrEngineInput,
    OcrRunner,
    build_ocr_derivative,
)
from procurement.documents.paddle_ocr import (
    MAX_OCR_IMAGE_BYTES,
    MAX_OCR_IMAGE_DIMENSION,
    MAX_OCR_IMAGE_PIXELS,
    PaddleOcrRunner,
)

DOCX_MEDIA_TYPES: dict[str, Literal["image/jpeg", "image/png"]] = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}
"""Форматы embedded media, разрешённые для локального OCR."""


class DocxMediaIssueCode(StrEnum):
    """Неблокирующая причина, по которой связанное media не стало OCR-source."""

    EXTERNAL_IMAGE = "EXTERNAL_IMAGE"
    MISSING_IMAGE = "MISSING_IMAGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    INVALID_IMAGE = "INVALID_IMAGE"


class DocxMediaRejectionCode(StrEnum):
    """Причина fail-closed отказа до передачи изображения в OCR."""

    UNSUPPORTED_DOCUMENT = "UNSUPPORTED_DOCUMENT"
    MALFORMED_RELATIONSHIPS = "MALFORMED_RELATIONSHIPS"
    UNSAFE_MEDIA_PATH = "UNSAFE_MEDIA_PATH"
    DUPLICATE_MEDIA_PATH = "DUPLICATE_MEDIA_PATH"
    SYMLINK_MEDIA = "SYMLINK_MEDIA"
    MEDIA_COUNT_LIMIT = "MEDIA_COUNT_LIMIT"
    MEDIA_SIZE_LIMIT = "MEDIA_SIZE_LIMIT"
    TOTAL_MEDIA_SIZE_LIMIT = "TOTAL_MEDIA_SIZE_LIMIT"
    IMAGE_DIMENSION_LIMIT = "IMAGE_DIMENSION_LIMIT"
    IMAGE_PIXEL_LIMIT = "IMAGE_PIXEL_LIMIT"


class DocxMediaRejected(ValueError):
    """DOCX media нельзя безопасно использовать; сообщение не содержит текста."""

    def __init__(self, code: DocxMediaRejectionCode) -> None:
        self.code = code
        super().__init__(f"DOCX media rejected: {code.value}")


class DocxMediaLimits(BaseModel):
    """Ресурсные границы отдельного embedded-media прохода."""

    model_config = ConfigDict(frozen=True)

    max_media_count: int = Field(default=50, ge=1)
    max_media_bytes: int = Field(default=MAX_OCR_IMAGE_BYTES, ge=1)
    max_total_media_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_dimension: int = Field(default=MAX_OCR_IMAGE_DIMENSION, ge=1)
    max_image_pixels: int = Field(default=MAX_OCR_IMAGE_PIXELS, ge=1)


DEFAULT_DOCX_MEDIA_LIMITS = DocxMediaLimits()


class DocxMediaIssue(BaseModel):
    """Видимая неполнота без исходных media bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_path: str = Field(min_length=1)
    code: DocxMediaIssueCode
    references: tuple[str, ...] = Field(min_length=1)


class DocxMediaSource(BaseModel):
    """Один immutable image source, связанный с внешним DOCX snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_document_id: str = Field(min_length=1)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_id: str = Field(min_length=1)
    media_index: int = Field(ge=0)
    archive_path: str = Field(min_length=1)
    media_type: Literal["image/jpeg", "image/png"]
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    references: tuple[str, ...] = Field(min_length=1)
    content: bytes = Field(min_length=1, exclude=True, repr=False)

    @model_validator(mode="after")
    def _source_is_consistent(self) -> Self:
        if self.source_media_id != docx_media_source_id(self.source_document_id, self.media_index):
            raise ValueError("DOCX media source identity is inconsistent")
        if len(self.content) != self.byte_size:
            raise ValueError("DOCX media byte_size does not match content")
        if not hmac.compare_digest(hashlib.sha256(self.content).hexdigest(), self.sha256):
            raise ValueError("DOCX media SHA-256 does not match content")
        if len(set(self.references)) != len(self.references):
            raise ValueError("DOCX media references must be unique")
        return self


class DocxMediaExtraction(BaseModel):
    """Результат раскрытия связанных media без повышения OCR-текста до факта."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ExtractionStatus
    media: tuple[DocxMediaSource, ...] = ()
    issues: tuple[DocxMediaIssue, ...] = ()

    @model_validator(mode="after")
    def _result_is_consistent(self) -> Self:
        expected = (
            ExtractionStatus.PASS if self.media and not self.issues else ExtractionStatus.UNKNOWN
        )
        if self.status is not expected:
            raise ValueError("DOCX media status is inconsistent")
        if len({item.media_index for item in self.media}) != len(self.media):
            raise ValueError("DOCX media indexes must be unique")
        if len({item.archive_path.casefold() for item in self.media}) != len(self.media):
            raise ValueError("DOCX media paths must be unique")
        if any(
            item.source_document_id != self.source_document_id
            or item.source_document_sha256 != self.source_sha256
            for item in self.media
        ):
            raise ValueError("DOCX media does not belong to extraction source")
        return self


class DocxMediaOcrItem(BaseModel):
    """Связь точного media source с отдельной OCR-производной."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    media: DocxMediaSource
    ocr: OcrDerivative

    @model_validator(mode="after")
    def _ocr_matches_media(self) -> Self:
        if (
            self.ocr.source_document_id != self.media.source_media_id
            or self.ocr.source_sha256 != self.media.sha256
        ):
            raise ValueError("DOCX media OCR does not match immutable source")
        return self


class DocxMediaOcrReport(BaseModel):
    """Локальный typed report; исходные bytes исключены из сериализации."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    extraction: DocxMediaExtraction
    status: ExtractionStatus
    results: tuple[DocxMediaOcrItem, ...] = ()

    @model_validator(mode="after")
    def _report_is_consistent(self) -> Self:
        expected = (
            ExtractionStatus.PASS
            if self.extraction.status is ExtractionStatus.PASS
            and len(self.results) == len(self.extraction.media)
            and all(item.ocr.status is ExtractionStatus.PASS for item in self.results)
            else ExtractionStatus.UNKNOWN
        )
        if self.status is not expected:
            raise ValueError("DOCX media OCR report status is inconsistent")
        if tuple(item.media for item in self.results) != self.extraction.media:
            raise ValueError("DOCX media OCR results do not match extraction order")
        return self


@dataclass(frozen=True)
class _LinkedImage:
    archive_path: str
    references: tuple[str, ...]


def docx_media_source_id(document_id: str, media_index: int) -> str:
    """Получить стабильный ID media source внутри immutable DOCX."""
    if not document_id:
        raise ValueError("document_id must not be empty")
    if media_index < 0:
        raise ValueError("media_index must not be negative")
    return f"{document_id}:media:{media_index}"


def extract_docx_media(
    document: DocumentInput,
    *,
    limits: DocxMediaLimits | None = None,
) -> DocxMediaExtraction:
    """Извлечь только реально связанные внутренние PNG/JPEG из DOCX."""
    if PurePath(document.filename).suffix.casefold() != ".docx" or not document.declared_media_type:
        raise DocxMediaRejected(DocxMediaRejectionCode.UNSUPPORTED_DOCUMENT)
    native = extract_document(document, limits=DEFAULT_EXTRACTION_LIMITS)
    if ExtractionReason.UNSUPPORTED_FORMAT in native.reasons:
        raise DocxMediaRejected(DocxMediaRejectionCode.UNSUPPORTED_DOCUMENT)

    active_limits = limits or DEFAULT_DOCX_MEDIA_LIMITS
    digest = hashlib.sha256(document.content).hexdigest()
    try:
        with ZipFile(BytesIO(document.content)) as archive:
            linked, relationship_issues = _linked_images(archive)
            if len(linked) + len(relationship_issues) > active_limits.max_media_count:
                raise DocxMediaRejected(DocxMediaRejectionCode.MEDIA_COUNT_LIMIT)
            media, media_issues = _read_linked_images(
                archive,
                linked,
                document_id=document.document_id,
                document_sha256=digest,
                limits=active_limits,
            )
    except DocxMediaRejected:
        raise
    except (BadZipFile, KeyError, OSError, RuntimeError) as error:
        raise DocxMediaRejected(DocxMediaRejectionCode.MALFORMED_RELATIONSHIPS) from error

    issues = tuple((*relationship_issues, *media_issues))
    status = ExtractionStatus.PASS if media and not issues else ExtractionStatus.UNKNOWN
    return DocxMediaExtraction(
        source_document_id=document.document_id,
        source_sha256=digest,
        status=status,
        media=media,
        issues=issues,
    )


def ocr_docx_media(
    document: DocumentInput,
    *,
    runner: OcrRunner,
    threshold: float = DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    limits: DocxMediaLimits | None = None,
) -> DocxMediaOcrReport:
    """Распознать media sources, не мутируя и не объединяя нативный результат."""
    extraction = extract_docx_media(document, limits=limits)
    native_media = ExtractionResult(
        status=ExtractionStatus.UNKNOWN,
        reasons=(ExtractionReason.EMBEDDED_MEDIA_IGNORED,),
        source_units_total=1,
        source_units_extracted=0,
        characters_extracted=0,
    )
    results: list[DocxMediaOcrItem] = []
    for media in extraction.media:
        source = OcrEngineInput(
            source_document_id=media.source_media_id,
            source_sha256=media.sha256,
            page_count=1,
        )
        candidates = runner.recognize(
            source,
            content=media.content,
            media_type=media.media_type,
        )
        if any(item.page_number != 1 for item in candidates):
            raise OcrEngineError("DOCX media OCR candidate is outside the immutable image")
        prefixed = tuple(_prefix_candidate(item, media.archive_path) for item in candidates)
        derivative = build_ocr_derivative(
            source,
            native_media,
            prefixed,
            engine=runner.engine,
            threshold=threshold,
        )
        results.append(DocxMediaOcrItem(media=media, ocr=derivative))
    typed_results = tuple(results)
    status = (
        ExtractionStatus.PASS
        if extraction.status is ExtractionStatus.PASS
        and typed_results
        and all(item.ocr.status is ExtractionStatus.PASS for item in typed_results)
        else ExtractionStatus.UNKNOWN
    )
    return DocxMediaOcrReport(extraction=extraction, status=status, results=typed_results)


def ocr_docx_media_path(
    path: Path,
    *,
    runner: OcrRunner | None = None,
    threshold: float = DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    limits: DocxMediaLimits | None = None,
) -> DocxMediaOcrReport:
    """Прочитать локальный DOCX с лимитом и выполнить embedded-media OCR."""
    with path.open("rb") as source:
        content = source.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocumentRejected(DocumentRejectionCode.INPUT_TOO_LARGE)
    digest = hashlib.sha256(content).hexdigest()
    return ocr_docx_media(
        DocumentInput(
            document_id=f"docx-{digest[:16]}",
            filename=path.name,
            declared_media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            content=content,
        ),
        runner=runner or PaddleOcrRunner(),
        threshold=threshold,
        limits=limits,
    )


def publish_docx_media_ocr_report(report: DocxMediaOcrReport, target: Path) -> Path:
    """Атомарно опубликовать полный локальный отчёт без перезаписи."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(report.model_dump_json(indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def _prefix_candidate(candidate: OcrCandidate, archive_path: str) -> OcrCandidate:
    return candidate.model_copy(
        update={"locator": f'DOCX media "{archive_path}" :: {candidate.locator}'}
    )


def _linked_images(
    archive: ZipFile,
) -> tuple[tuple[_LinkedImage, ...], tuple[DocxMediaIssue, ...]]:
    names = frozenset(info.filename for info in archive.infolist())
    casefolded: dict[str, list[str]] = {}
    for name in names:
        casefolded.setdefault(unicodedata.normalize("NFC", name).casefold(), []).append(name)

    references_by_target: dict[str, set[str]] = {}
    issues: list[DocxMediaIssue] = []
    relationship_parts = sorted(
        name
        for name in names
        if name.startswith("word/") and "/_rels/" in name and name.endswith(".rels")
    )
    for relationship_part in relationship_parts:
        source_part = _source_part(relationship_part)
        if source_part not in names:
            continue
        used_ids = _used_relationship_ids(archive.read(source_part))
        root = _parse_xml(archive.read(relationship_part))
        for relation in root.iter():
            if _local_name(relation.tag) != "Relationship":
                continue
            relation_id = relation.attrib.get("Id", "")
            relation_type = relation.attrib.get("Type", "")
            if relation_id not in used_ids or not relation_type.endswith("/image"):
                continue
            reference = f"{source_part} relationship {relation_id}"
            if relation.attrib.get("TargetMode", "Internal").casefold() == "external":
                issues.append(
                    DocxMediaIssue(
                        archive_path=f"external image relationship {relation_id}",
                        code=DocxMediaIssueCode.EXTERNAL_IMAGE,
                        references=(reference,),
                    )
                )
                continue
            target = _resolve_media_target(source_part, relation.attrib.get("Target", ""))
            matching = casefolded.get(unicodedata.normalize("NFC", target).casefold(), [])
            if len(matching) > 1:
                raise DocxMediaRejected(DocxMediaRejectionCode.DUPLICATE_MEDIA_PATH)
            if not matching:
                issues.append(
                    DocxMediaIssue(
                        archive_path=target,
                        code=DocxMediaIssueCode.MISSING_IMAGE,
                        references=(reference,),
                    )
                )
                continue
            references_by_target.setdefault(matching[0], set()).add(reference)

    linked = tuple(
        _LinkedImage(archive_path=path, references=tuple(sorted(references)))
        for path, references in sorted(
            references_by_target.items(), key=lambda item: item[0].casefold()
        )
    )
    return linked, tuple(issues)


def _source_part(relationship_part: str) -> str:
    path = PurePosixPath(relationship_part)
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        raise DocxMediaRejected(DocxMediaRejectionCode.MALFORMED_RELATIONSHIPS)
    source_name = path.name.removesuffix(".rels")
    return (path.parent.parent / source_name).as_posix()


def _used_relationship_ids(content: bytes) -> frozenset[str]:
    root = _parse_xml(content)
    result: set[str] = set()
    for element in root.iter():
        for attribute, value in element.attrib.items():
            if _is_embedded_relationship_attribute(attribute) and value:
                result.add(value)
    return frozenset(result)


def _is_embedded_relationship_attribute(attribute: str) -> bool:
    if not attribute.startswith("{") or "}" not in attribute:
        return False
    namespace, local = attribute[1:].split("}", maxsplit=1)
    return namespace.endswith("/relationships") and local in {"embed", "id"}


def _parse_xml(content: bytes) -> ElementTree.Element:
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise DocxMediaRejected(DocxMediaRejectionCode.MALFORMED_RELATIONSHIPS)
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise DocxMediaRejected(DocxMediaRejectionCode.MALFORMED_RELATIONSHIPS) from error


def _resolve_media_target(source_part: str, raw_target: str) -> str:
    if not raw_target or "\\" in raw_target or "\x00" in raw_target:
        raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)
    target = unquote(parsed.path)
    if not target or "\\" in target or "\x00" in target:
        raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)

    if target.startswith("/"):
        # OPC permits absolute package-part targets. Admit only media parts;
        # never let an absolute relationship escape the document's media tree.
        if not target.startswith("/word/media/") or ".." in PurePosixPath(target).parts:
            raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)
        segments: list[str] = []
        target = target.lstrip("/")
    else:
        segments = list(PurePosixPath(source_part).parent.parts)
    for segment in PurePosixPath(target).parts:
        if segment in {"", "."}:
            continue
        if segment == "..":
            if not segments:
                raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)
            segments.pop()
            continue
        if any(ord(character) < 32 for character in segment):
            raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)
        segments.append(segment)
    resolved = PurePosixPath(*segments).as_posix()
    if not resolved.startswith("word/media/") or len(resolved) > 512:
        raise DocxMediaRejected(DocxMediaRejectionCode.UNSAFE_MEDIA_PATH)
    return resolved


def _read_linked_images(
    archive: ZipFile,
    linked: tuple[_LinkedImage, ...],
    *,
    document_id: str,
    document_sha256: str,
    limits: DocxMediaLimits,
) -> tuple[tuple[DocxMediaSource, ...], tuple[DocxMediaIssue, ...]]:
    info_by_name = {item.filename: item for item in archive.infolist()}
    total_size = 0
    media: list[DocxMediaSource] = []
    issues: list[DocxMediaIssue] = []
    for media_index, linked_image in enumerate(linked):
        info = info_by_name[linked_image.archive_path]
        _validate_media_info(info)
        if info.file_size > limits.max_media_bytes:
            raise DocxMediaRejected(DocxMediaRejectionCode.MEDIA_SIZE_LIMIT)
        total_size += info.file_size
        if total_size > limits.max_total_media_bytes:
            raise DocxMediaRejected(DocxMediaRejectionCode.TOTAL_MEDIA_SIZE_LIMIT)
        extension = PurePosixPath(linked_image.archive_path).suffix.casefold()
        media_type = DOCX_MEDIA_TYPES.get(extension)
        if media_type is None:
            issues.append(
                DocxMediaIssue(
                    archive_path=linked_image.archive_path,
                    code=DocxMediaIssueCode.UNSUPPORTED_MEDIA_TYPE,
                    references=linked_image.references,
                )
            )
            continue
        content = archive.read(info)
        if len(content) != info.file_size:
            raise DocxMediaRejected(DocxMediaRejectionCode.MALFORMED_RELATIONSHIPS)
        dimensions = _image_dimensions(content, media_type, limits)
        if dimensions is None:
            issues.append(
                DocxMediaIssue(
                    archive_path=linked_image.archive_path,
                    code=DocxMediaIssueCode.INVALID_IMAGE,
                    references=linked_image.references,
                )
            )
            continue
        width, height = dimensions
        digest = hashlib.sha256(content).hexdigest()
        media.append(
            DocxMediaSource(
                source_document_id=document_id,
                source_document_sha256=document_sha256,
                source_media_id=docx_media_source_id(document_id, media_index),
                media_index=media_index,
                archive_path=linked_image.archive_path,
                media_type=media_type,
                byte_size=len(content),
                sha256=digest,
                width=width,
                height=height,
                references=linked_image.references,
                content=content,
            )
        )
    return tuple(media), tuple(issues)


def _validate_media_info(info: ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and stat.S_ISLNK(mode):
        raise DocxMediaRejected(DocxMediaRejectionCode.SYMLINK_MEDIA)
    if info.flag_bits & 0x1:
        raise DocxMediaRejected(DocxMediaRejectionCode.MALFORMED_RELATIONSHIPS)


def _image_dimensions(
    content: bytes,
    media_type: Literal["image/jpeg", "image/png"],
    limits: DocxMediaLimits,
) -> tuple[int, int] | None:
    expected_format = "JPEG" if media_type == "image/jpeg" else "PNG"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=[expected_format]) as image:
                if image.format != expected_format:
                    return None
                width, height = image.size
                if width > limits.max_dimension or height > limits.max_dimension:
                    raise DocxMediaRejected(DocxMediaRejectionCode.IMAGE_DIMENSION_LIMIT)
                if width * height > limits.max_image_pixels:
                    raise DocxMediaRejected(DocxMediaRejectionCode.IMAGE_PIXEL_LIMIT)
                image.verify()
                return width, height
    except DocxMediaRejected:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ):
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]
