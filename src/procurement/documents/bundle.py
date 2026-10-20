"""Безопасное раскрытие ZIP-пакета закупочных документов.

Архив остаётся immutable source. Поддержанные PDF/DOCX/XLSX извлекаются только
в памяти; provenance каждого блока получает путь участника. Неизвестные форматы
не становятся фактами, а опасная структура отклоняет пакет целиком.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unicodedata
from enum import StrEnum
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Self
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import (
    DEFAULT_EXTRACTION_LIMITS,
    DocumentInput,
    DocumentRejected,
    ExtractedBlock,
    ExtractionLimits,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    extract_document,
)
from procurement.domain.provenance import Provenance

ZIP_MEDIA_TYPES = frozenset({"application/zip", "application/x-zip-compressed"})
"""Разрешённые declared MIME для внешнего ZIP-контейнера."""

_MEMBER_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".doc": "application/msword",
}
_MACRO_EXTENSIONS = frozenset({".docm", ".xlsm", ".xltm"})
_NESTED_ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz"})
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_MAX_MEMBER_PATH_LENGTH = 512


class BundleRejectionCode(StrEnum):
    """Причины отказа до использования любого участника архива."""

    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    FILENAME_INVALID = "FILENAME_INVALID"
    MEDIA_TYPE_MISMATCH = "MEDIA_TYPE_MISMATCH"
    MAGIC_MISMATCH = "MAGIC_MISMATCH"
    MALFORMED_ARCHIVE = "MALFORMED_ARCHIVE"
    MEMBER_LIMIT = "MEMBER_LIMIT"
    EXPANSION_LIMIT = "EXPANSION_LIMIT"
    MEMBER_TOO_LARGE = "MEMBER_TOO_LARGE"
    UNSAFE_MEMBER_PATH = "UNSAFE_MEMBER_PATH"
    DUPLICATE_MEMBER_PATH = "DUPLICATE_MEMBER_PATH"
    ENCRYPTED_MEMBER = "ENCRYPTED_MEMBER"
    SYMLINK_MEMBER = "SYMLINK_MEMBER"
    NESTED_ARCHIVE = "NESTED_ARCHIVE"
    MACRO_ENABLED_MEMBER = "MACRO_ENABLED_MEMBER"
    MEMBER_REJECTED = "MEMBER_REJECTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class DocumentBundleRejected(ValueError):
    """Архив нельзя безопасно раскрыть; сообщение не содержит приватных путей."""

    def __init__(self, code: BundleRejectionCode) -> None:
        self.code = code
        super().__init__(f"document bundle rejected: {code.value}")


class DocumentBundleMemberUnavailable(RuntimeError):
    """Persisted ZIP and member snapshot no longer form one verifiable source."""


class BundleReason(StrEnum):
    """Неблокирующая причина неполноты типизированного результата."""

    EMPTY_ARCHIVE = "EMPTY_ARCHIVE"
    UNSUPPORTED_MEMBERS = "UNSUPPORTED_MEMBERS"
    MEMBER_EXTRACTION_UNKNOWN = "MEMBER_EXTRACTION_UNKNOWN"


class DocumentBundleMember(BaseModel):
    """Метаданные и extraction одного участника без его исходных байтов."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_path: str = Field(min_length=1, max_length=_MAX_MEMBER_PATH_LENGTH)
    media_type: str | None = None
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: ExtractionResult

    @model_validator(mode="after")
    def _member_is_consistent(self) -> Self:
        _safe_member_path(self.archive_path)
        unsupported = ExtractionReason.UNSUPPORTED_FORMAT in self.extraction.reasons
        if self.media_type is None and not unsupported:
            raise ValueError("member without media type must be unsupported")
        if self.media_type is not None and unsupported:
            raise ValueError("supported member cannot report unsupported format")
        if self.media_type is None and self.extraction.blocks:
            raise ValueError("unsupported member cannot expose extracted blocks")
        if self.media_type is not None and self.media_type not in _MEMBER_MEDIA_TYPES.values():
            raise ValueError("member media type is not supported")
        if self.extraction.status is ExtractionStatus.FAIL:
            raise ValueError("rejected member must reject the whole bundle")
        return self


class DocumentBundleResult(BaseModel):
    """Результат раскрытия immutable ZIP с evidence каждого участника."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ExtractionStatus
    reasons: tuple[BundleReason, ...]
    members: tuple[DocumentBundleMember, ...]
    members_total: int = Field(ge=0)
    supported_members: int = Field(ge=0)
    unsupported_members: int = Field(ge=0)

    @model_validator(mode="after")
    def _result_is_consistent(self) -> Self:
        if self.members_total != len(self.members):
            raise ValueError("members_total must match members")
        supported = sum(member.media_type is not None for member in self.members)
        if supported != self.supported_members:
            raise ValueError("supported_members count is inconsistent")
        if self.members_total - supported != self.unsupported_members:
            raise ValueError("unsupported_members count is inconsistent")
        if len({member.archive_path.casefold() for member in self.members}) != len(self.members):
            raise ValueError("bundle member paths must be unique")
        expected_reasons: list[BundleReason] = []
        if not self.members:
            expected_reasons.append(BundleReason.EMPTY_ARCHIVE)
        if self.unsupported_members:
            expected_reasons.append(BundleReason.UNSUPPORTED_MEMBERS)
        if any(
            member.media_type is not None
            and member.extraction.status is ExtractionStatus.UNKNOWN
            for member in self.members
        ):
            expected_reasons.append(BundleReason.MEMBER_EXTRACTION_UNKNOWN)
        if self.reasons != tuple(expected_reasons):
            raise ValueError("bundle reasons are inconsistent with members")
        expected_status = (
            ExtractionStatus.PASS
            if self.members
            and not self.unsupported_members
            and all(
                member.extraction.status is ExtractionStatus.PASS
                for member in self.members
            )
            else ExtractionStatus.UNKNOWN
        )
        if self.status is not expected_status:
            raise ValueError("bundle status is inconsistent with member extraction")
        return self


class DocumentBundleMemberSource(BaseModel):
    """Internal exact bytes of one supported member, never an API response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_bundle_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    member_index: int = Field(ge=0)
    archive_path: str = Field(min_length=1, max_length=_MAX_MEMBER_PATH_LENGTH)
    media_type: str = Field(min_length=1)
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes = Field(exclude=True, repr=False)
    extraction: ExtractionResult

    @model_validator(mode="after")
    def _source_is_consistent(self) -> Self:
        _safe_member_path(self.archive_path)
        if self.source_document_id != bundle_member_source_id(
            self.source_bundle_id,
            self.member_index,
        ):
            raise ValueError("bundle member source identity is inconsistent")
        if self.media_type not in _MEMBER_MEDIA_TYPES.values():
            raise ValueError("bundle member source media type is unsupported")
        if len(self.content) != self.byte_size:
            raise ValueError("bundle member byte_size does not match content")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("bundle member SHA-256 does not match content")
        return self


def bundle_member_source_id(bundle_id: str, member_index: int) -> str:
    """Return the stable OCR identity of one member inside an immutable ZIP."""
    if not bundle_id:
        raise ValueError("bundle_id must not be empty")
    if member_index < 0:
        raise ValueError("member_index must not be negative")
    return f"{bundle_id}:member:{member_index}"


def read_document_bundle_member(
    document: DocumentInput,
    result: DocumentBundleResult,
    member_index: int,
    *,
    limits: ExtractionLimits | None = None,
) -> DocumentBundleMemberSource:
    """Reopen and verify one supported member against its persisted snapshot."""
    active_limits = limits or DEFAULT_EXTRACTION_LIMITS
    if member_index < 0 or member_index >= len(result.members):
        raise IndexError("document bundle member does not exist")
    if (
        result.source_document_id != document.document_id
        or result.source_sha256 != hashlib.sha256(document.content).hexdigest()
    ):
        raise DocumentBundleMemberUnavailable("document bundle source mismatch")
    expected = result.members[member_index]
    if expected.media_type is None:
        raise DocumentBundleMemberUnavailable("document bundle member is unsupported")
    try:
        _validate_outer(document, active_limits)
        with ZipFile(BytesIO(document.content)) as archive:
            all_infos = tuple(archive.infolist())
            if len(all_infos) > active_limits.max_zip_members:
                raise DocumentBundleRejected(BundleRejectionCode.MEMBER_LIMIT)
            infos = tuple(info for info in all_infos if not info.is_dir())
            _validate_infos(infos, active_limits)
            if len(infos) != len(result.members):
                raise DocumentBundleMemberUnavailable("document bundle member count mismatch")
            info = infos[member_index]
            archive_path = _safe_member_path(info.filename)
            media_type = _MEMBER_MEDIA_TYPES.get(PurePosixPath(archive_path).suffix.casefold())
            if archive_path != expected.archive_path or media_type != expected.media_type:
                raise DocumentBundleMemberUnavailable("document bundle member identity mismatch")
            content = archive.read(info)
    except DocumentBundleMemberUnavailable:
        raise
    except (
        DocumentBundleRejected,
        BadZipFile,
        NotImplementedError,
        OSError,
        RuntimeError,
    ) as error:
        raise DocumentBundleMemberUnavailable(
            "document bundle member cannot be verified"
        ) from error
    digest = hashlib.sha256(content).hexdigest()
    if (
        len(content) != info.file_size
        or len(content) != expected.byte_size
        or digest != expected.sha256
    ):
        raise DocumentBundleMemberUnavailable("document bundle member evidence mismatch")
    return DocumentBundleMemberSource(
        source_bundle_id=document.document_id,
        source_document_id=bundle_member_source_id(document.document_id, member_index),
        member_index=member_index,
        archive_path=archive_path,
        media_type=expected.media_type,
        byte_size=len(content),
        sha256=digest,
        content=content,
        extraction=expected.extraction,
    )


def extract_document_bundle(
    document: DocumentInput,
    *,
    limits: ExtractionLimits | None = None,
) -> DocumentBundleResult:
    """Проверить ZIP и извлечь поддержанные участники с archive provenance."""
    active_limits = limits or DEFAULT_EXTRACTION_LIMITS
    _validate_outer(document, active_limits)
    try:
        with ZipFile(BytesIO(document.content)) as archive:
            all_infos = tuple(archive.infolist())
            if len(all_infos) > active_limits.max_zip_members:
                raise DocumentBundleRejected(BundleRejectionCode.MEMBER_LIMIT)
            infos = tuple(info for info in all_infos if not info.is_dir())
            _validate_infos(infos, active_limits)
            members = tuple(
                _extract_member(document.document_id, archive, info, active_limits)
                for info in infos
            )
    except DocumentBundleRejected:
        raise
    except (BadZipFile, NotImplementedError, OSError, RuntimeError) as error:
        raise DocumentBundleRejected(BundleRejectionCode.MALFORMED_ARCHIVE) from error

    unsupported = sum(member.media_type is None for member in members)
    reasons: list[BundleReason] = []
    if not members:
        reasons.append(BundleReason.EMPTY_ARCHIVE)
    if unsupported:
        reasons.append(BundleReason.UNSUPPORTED_MEMBERS)
    if any(
        member.media_type is not None
        and member.extraction.status is ExtractionStatus.UNKNOWN
        for member in members
    ):
        reasons.append(BundleReason.MEMBER_EXTRACTION_UNKNOWN)
    status = (
        ExtractionStatus.PASS
        if members
        and not reasons
        else ExtractionStatus.UNKNOWN
    )
    return DocumentBundleResult(
        source_document_id=document.document_id,
        source_sha256=hashlib.sha256(document.content).hexdigest(),
        status=status,
        reasons=tuple(reasons),
        members=members,
        members_total=len(members),
        supported_members=len(members) - unsupported,
        unsupported_members=unsupported,
    )


def extract_document_bundle_path(
    path: Path,
    *,
    limits: ExtractionLimits | None = None,
) -> DocumentBundleResult:
    """Прочитать локальный ZIP с проверкой размера до загрузки в память."""
    active_limits = limits or DEFAULT_EXTRACTION_LIMITS
    try:
        if path.stat().st_size > active_limits.max_input_bytes:
            raise DocumentBundleRejected(BundleRejectionCode.INPUT_TOO_LARGE)
        with path.open("rb") as source:
            content = source.read(active_limits.max_input_bytes + 1)
    except DocumentBundleRejected:
        raise
    except OSError as error:
        raise DocumentBundleRejected(BundleRejectionCode.SOURCE_UNAVAILABLE) from error
    if len(content) > active_limits.max_input_bytes:
        raise DocumentBundleRejected(BundleRejectionCode.INPUT_TOO_LARGE)
    digest = hashlib.sha256(content).hexdigest()
    return extract_document_bundle(
        DocumentInput(
            document_id=f"bundle-{digest[:16]}",
            filename=path.name,
            declared_media_type="application/zip",
            content=content,
        ),
        limits=active_limits,
    )


def publish_document_bundle_result(result: DocumentBundleResult, target: Path) -> Path:
    """Атомарно создать полный локальный JSON-отчёт без перезаписи."""
    resolved = target.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved.parent,
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(result.model_dump_json(indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, resolved)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return resolved


def _validate_outer(document: DocumentInput, limits: ExtractionLimits) -> None:
    if len(document.content) > limits.max_input_bytes:
        raise DocumentBundleRejected(BundleRejectionCode.INPUT_TOO_LARGE)
    filename = document.filename
    if not filename.casefold().endswith(".zip"):
        raise DocumentBundleRejected(BundleRejectionCode.FILENAME_INVALID)
    if document.declared_media_type.strip().casefold() not in ZIP_MEDIA_TYPES:
        raise DocumentBundleRejected(BundleRejectionCode.MEDIA_TYPE_MISMATCH)
    if not document.content.startswith(_ZIP_MAGICS):
        raise DocumentBundleRejected(BundleRejectionCode.MAGIC_MISMATCH)


def _validate_infos(infos: tuple[ZipInfo, ...], limits: ExtractionLimits) -> None:
    if len(infos) > limits.max_zip_members:
        raise DocumentBundleRejected(BundleRejectionCode.MEMBER_LIMIT)
    if sum(info.file_size for info in infos) > limits.max_zip_expanded_bytes:
        raise DocumentBundleRejected(BundleRejectionCode.EXPANSION_LIMIT)
    seen: set[str] = set()
    for info in infos:
        if info.file_size < 0 or info.compress_size < 0:
            raise DocumentBundleRejected(BundleRejectionCode.MALFORMED_ARCHIVE)
        normalized = _safe_member_path(info.filename)
        canonical = unicodedata.normalize("NFC", normalized).casefold()
        if canonical in seen:
            raise DocumentBundleRejected(BundleRejectionCode.DUPLICATE_MEMBER_PATH)
        seen.add(canonical)
        if info.flag_bits & 0x1:
            raise DocumentBundleRejected(BundleRejectionCode.ENCRYPTED_MEMBER)
        unix_mode = info.external_attr >> 16
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise DocumentBundleRejected(BundleRejectionCode.SYMLINK_MEMBER)
        if info.file_size > limits.max_input_bytes:
            raise DocumentBundleRejected(BundleRejectionCode.MEMBER_TOO_LARGE)


def _extract_member(
    document_id: str,
    archive: ZipFile,
    info: ZipInfo,
    limits: ExtractionLimits,
) -> DocumentBundleMember:
    archive_path = _safe_member_path(info.filename)
    suffix = PurePosixPath(archive_path).suffix.casefold()
    if suffix in _NESTED_ARCHIVE_EXTENSIONS:
        raise DocumentBundleRejected(BundleRejectionCode.NESTED_ARCHIVE)
    if suffix in _MACRO_EXTENSIONS:
        raise DocumentBundleRejected(BundleRejectionCode.MACRO_ENABLED_MEMBER)
    try:
        content = archive.read(info)
    except (BadZipFile, NotImplementedError, RuntimeError) as error:
        raise DocumentBundleRejected(BundleRejectionCode.MALFORMED_ARCHIVE) from error
    if len(content) != info.file_size:
        raise DocumentBundleRejected(BundleRejectionCode.MALFORMED_ARCHIVE)
    if _looks_like_archive(content) and suffix not in {".docx", ".xlsx"}:
        raise DocumentBundleRejected(BundleRejectionCode.NESTED_ARCHIVE)

    media_type = _MEMBER_MEDIA_TYPES.get(suffix)
    digest = hashlib.sha256(content).hexdigest()
    if media_type is None:
        extraction = ExtractionResult(
            status=ExtractionStatus.UNKNOWN,
            reasons=(ExtractionReason.UNSUPPORTED_FORMAT,),
            source_units_total=0,
            source_units_extracted=0,
            characters_extracted=0,
        )
    else:
        try:
            raw_extraction = extract_document(
                DocumentInput(
                    document_id=document_id,
                    filename=PurePosixPath(archive_path).name,
                    declared_media_type=media_type,
                    content=content,
                ),
                limits=limits,
            )
        except DocumentRejected as error:
            raise DocumentBundleRejected(BundleRejectionCode.MEMBER_REJECTED) from error
        extraction = _prefix_provenance(raw_extraction, archive_path)
    return DocumentBundleMember(
        archive_path=archive_path,
        media_type=media_type,
        byte_size=len(content),
        sha256=digest,
        extraction=extraction,
    )


def _prefix_provenance(result: ExtractionResult, archive_path: str) -> ExtractionResult:
    blocks = tuple(
        ExtractedBlock(
            text=block.text,
            provenance=Provenance(
                document_id=block.provenance.document_id,
                locator=f'archive member "{archive_path}" :: {block.provenance.locator}',
                extractor=block.provenance.extractor,
                confidence=block.provenance.confidence,
            ),
        )
        for block in result.blocks
    )
    return result.model_copy(update={"blocks": blocks})


def _safe_member_path(raw: str) -> str:
    normalized = unicodedata.normalize("NFC", raw.replace("\\", "/"))
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(raw)
    if (
        not normalized
        or len(normalized) > _MAX_MEMBER_PATH_LENGTH
        or "\x00" in normalized
        or any(ord(character) < 32 for character in normalized)
        or normalized.startswith("/")
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or not posix.name
    ):
        raise DocumentBundleRejected(BundleRejectionCode.UNSAFE_MEMBER_PATH)
    return posix.as_posix()


def _looks_like_archive(content: bytes) -> bool:
    return (
        content.startswith(_ZIP_MAGICS)
        or content.startswith(b"7z\xbc\xaf'\x1c")
        or content.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
        or content.startswith(b"\x1f\x8b")
        or (len(content) >= 262 and content[257:262] == b"ustar")
    )
