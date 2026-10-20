"""Bounded native DOCX text for evidence review, without requirement conclusions."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePath, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    ExtractedBlock,
    ExtractionLimits,
    ExtractionReason,
    extract_document,
)
from procurement.domain.provenance import Provenance

REVIEW_VERSION: Literal["eis-native-review-v1"] = "eis-native-review-v1"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_REVIEW_INPUT_BYTES = 4 * 1024 * 1024
MAX_REVIEW_BLOCKS = 1_000
MAX_REVIEW_CHARACTERS = 100_000
MAX_PAGE_TEXT_CHARACTERS = 16_000
MAX_PAGE_RESPONSE_BYTES = 240 * 1024
REVIEW_EXTRACTION_LIMITS = ExtractionLimits(
    max_input_bytes=MAX_REVIEW_INPUT_BYTES,
    max_zip_expanded_bytes=32 * 1024 * 1024,
    max_source_units=20_000,
    max_extracted_characters=1_000_000,
)

ReviewStatus = Literal["PASS", "FAIL", "UNKNOWN"]
Unknown = Literal["UNKNOWN"]
TextScope = Literal["SUPPORTED_DOCX_BODY_PARAGRAPHS_AND_TABLES"]


class ReviewModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewDocumentAnalysis(ReviewModel):
    review_version: Literal["eis-native-review-v1"] = REVIEW_VERSION
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=1_024)
    byte_count: int = Field(ge=1, le=MAX_REVIEW_INPUT_BYTES, strict=True)
    extraction_input_byte_limit: Literal[4194304] = 4194304
    extraction_expanded_byte_limit: Literal[33554432] = 33554432
    extraction_source_unit_limit: Literal[20000] = 20000
    extraction_character_limit: Literal[1000000] = 1000000
    extraction_status: ReviewStatus
    extraction_reasons: tuple[ExtractionReason | Literal["DOCUMENT_REJECTED"], ...] = Field(
        max_length=16
    )
    rejection_code: DocumentRejectionCode | None = None
    source_units_total: int | None = Field(default=None, ge=0, le=20_000, strict=True)
    source_units_extracted: int | None = Field(default=None, ge=0, le=20_000, strict=True)
    characters_extracted: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    blocks_extracted_total: int | None = Field(default=None, ge=0, le=20_000, strict=True)
    blocks: tuple[ExtractedBlock, ...] = Field(max_length=MAX_REVIEW_BLOCKS)
    retained_blocks: int = Field(ge=0, le=MAX_REVIEW_BLOCKS, strict=True)
    retained_characters: int = Field(ge=0, le=MAX_REVIEW_CHARACTERS, strict=True)
    retention_truncated: bool = Field(strict=True)
    retention_reasons: tuple[Literal["RETAINED_BLOCK_LIMIT", "RETAINED_CHARACTER_LIMIT"], ...] = (
        Field(max_length=2)
    )
    retention_block_limit: Literal[1000] = 1000
    retention_character_limit: Literal[100000] = 100000
    text_scope: TextScope = "SUPPORTED_DOCX_BODY_PARAGRAPHS_AND_TABLES"
    retained_extracted_text_complete: bool = Field(strict=True)
    native_text_completeness: Unknown = "UNKNOWN"
    document_role: Unknown = "UNKNOWN"
    position_association: Unknown = "UNKNOWN"
    approved_requirements: Unknown = "UNKNOWN"
    full_tspec_completeness: Unknown = "UNKNOWN"
    participation: Unknown = "UNKNOWN"

    @model_validator(mode="after")
    def consistent_evidence(self) -> ReviewDocumentAnalysis:
        if _safe_filename(self.filename) != self.filename:
            raise ValueError("REVIEW_DOCUMENT_FILENAME_INVALID")
        totals = (
            self.source_units_total,
            self.source_units_extracted,
            self.characters_extracted,
            self.blocks_extracted_total,
        )
        if self.rejection_code is not None:
            if (
                any(value is not None for value in totals)
                or self.blocks
                or self.retained_blocks
                or self.retained_characters
                or self.retention_truncated
                or self.retention_reasons
            ):
                raise ValueError("REVIEW_REJECTION_HAS_FACTS")
            if self.extraction_status != "UNKNOWN":
                raise ValueError("REVIEW_REJECTION_STATUS_INVALID")
        elif any(value is None for value in totals):
            raise ValueError("REVIEW_EXTRACTION_TOTAL_MISSING")
        if self.retained_blocks != len(self.blocks):
            raise ValueError("REVIEW_RETAINED_BLOCK_COUNT_INVALID")
        if self.retained_characters != sum(len(block.text) for block in self.blocks):
            raise ValueError("REVIEW_RETAINED_CHARACTER_COUNT_INVALID")
        if any(block.provenance.document_id != self.sha256 for block in self.blocks):
            raise ValueError("REVIEW_PROVENANCE_MISMATCH")
        if self.blocks_extracted_total is not None:
            assert self.source_units_total is not None
            assert self.source_units_extracted is not None
            assert self.characters_extracted is not None
            if self.source_units_extracted > self.source_units_total:
                raise ValueError("REVIEW_EXTRACTED_SOURCE_UNIT_COUNT_INVALID")
            if self.source_units_extracted != self.blocks_extracted_total:
                raise ValueError("REVIEW_EXTRACTED_BLOCK_COUNT_INVALID")
            if self.retained_characters > self.characters_extracted:
                raise ValueError("REVIEW_RETENTION_CHARACTER_COUNT_INVALID")
            if self.retained_blocks > self.blocks_extracted_total:
                raise ValueError("REVIEW_RETENTION_COUNT_INVALID")
            if self.retention_truncated != (self.retained_blocks < self.blocks_extracted_total):
                raise ValueError("REVIEW_RETENTION_FLAG_INVALID")
            if (
                not self.retention_truncated
                and self.retained_characters != self.characters_extracted
            ):
                raise ValueError("REVIEW_RETENTION_CHARACTER_COUNT_INVALID")
            if self.retention_truncated and self.retained_characters >= self.characters_extracted:
                raise ValueError("REVIEW_RETENTION_CHARACTER_COUNT_INVALID")
        if self.retention_truncated != bool(self.retention_reasons):
            raise ValueError("REVIEW_RETENTION_REASON_INVALID")
        expected_retained_complete = (
            self.rejection_code is None
            and not self.retention_truncated
            and self.retained_blocks > 0
            and self.retained_characters > 0
            and self.retained_blocks == self.blocks_extracted_total
            and self.retained_characters == self.characters_extracted
        )
        if self.retained_extracted_text_complete != expected_retained_complete:
            raise ValueError("REVIEW_RETAINED_COMPLETENESS_INVALID")
        return self


class ReviewPageBlock(ReviewModel):
    block_index: int = Field(ge=0, le=MAX_REVIEW_BLOCKS - 1, strict=True)
    character_start: int = Field(ge=0, le=MAX_REVIEW_CHARACTERS, strict=True)
    character_end: int = Field(ge=1, le=MAX_REVIEW_CHARACTERS, strict=True)
    source_character_count: int = Field(ge=1, le=MAX_REVIEW_CHARACTERS, strict=True)
    text: str = Field(min_length=1)
    provenance: Provenance
    text_truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def exact_span(self) -> ReviewPageBlock:
        if (
            not self.character_start < self.character_end <= self.source_character_count
            or len(self.text) != self.character_end - self.character_start
            or self.text_truncated
            != (self.character_start != 0 or self.character_end != self.source_character_count)
        ):
            raise ValueError("REVIEW_PAGE_BLOCK_SPAN_INVALID")
        return self


class ReviewDocumentPage(ReviewModel):
    review_version: Literal["eis-native-review-v1"] = REVIEW_VERSION
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=1_024)
    byte_count: int = Field(ge=1, le=MAX_REVIEW_INPUT_BYTES, strict=True)
    extraction_input_byte_limit: Literal[4194304] = 4194304
    extraction_expanded_byte_limit: Literal[33554432] = 33554432
    extraction_source_unit_limit: Literal[20000] = 20000
    extraction_character_limit: Literal[1000000] = 1000000
    extraction_status: ReviewStatus
    extraction_reasons: tuple[ExtractionReason | Literal["DOCUMENT_REJECTED"], ...] = Field(
        max_length=16
    )
    rejection_code: DocumentRejectionCode | None = None
    source_units_total: int | None = Field(default=None, ge=0, le=20_000, strict=True)
    source_units_extracted: int | None = Field(default=None, ge=0, le=20_000, strict=True)
    characters_extracted: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    blocks_extracted_total: int | None = Field(default=None, ge=0, le=20_000, strict=True)
    offset: int = Field(ge=0, le=999, strict=True)
    character_offset: int = Field(ge=0, le=MAX_REVIEW_CHARACTERS - 1, strict=True)
    limit: int = Field(ge=1, le=25, strict=True)
    retained_total: int = Field(ge=0, le=MAX_REVIEW_BLOCKS, strict=True)
    retained_characters: int = Field(ge=0, le=MAX_REVIEW_CHARACTERS, strict=True)
    retention_truncated: bool = Field(strict=True)
    retention_reasons: tuple[Literal["RETAINED_BLOCK_LIMIT", "RETAINED_CHARACTER_LIMIT"], ...] = (
        Field(max_length=2)
    )
    retention_block_limit: Literal[1000] = 1000
    retention_character_limit: Literal[100000] = 100000
    text_scope: TextScope = "SUPPORTED_DOCX_BODY_PARAGRAPHS_AND_TABLES"
    retained_extracted_text_complete: bool = Field(strict=True)
    native_text_completeness: Unknown = "UNKNOWN"
    page_start: int = Field(ge=0, le=999, strict=True)
    next_offset: int | None = Field(default=None, ge=0, le=999, strict=True)
    next_character_offset: int | None = Field(
        default=None, ge=0, le=MAX_REVIEW_CHARACTERS - 1, strict=True
    )
    blocks: tuple[ReviewPageBlock, ...] = Field(max_length=25)
    page_text_characters: int = Field(ge=0, le=MAX_PAGE_TEXT_CHARACTERS, strict=True)
    page_text_truncated: bool = Field(strict=True)
    page_reasons: tuple[Literal["PAGE_TEXT_LIMIT"], ...] = Field(max_length=1)
    delivery_lead_indices: tuple[int, ...] = Field(max_length=25)
    structured_delivery: Unknown = "UNKNOWN"
    document_role: Unknown = "UNKNOWN"
    position_association: Unknown = "UNKNOWN"
    approved_requirements: Unknown = "UNKNOWN"
    full_tspec_completeness: Unknown = "UNKNOWN"
    participation: Unknown = "UNKNOWN"

    @model_validator(mode="after")
    def consistent_page(self) -> ReviewDocumentPage:
        if _safe_filename(self.filename) != self.filename:
            raise ValueError("REVIEW_DOCUMENT_FILENAME_INVALID")
        if self.offset >= self.retained_total:
            if self.character_offset != 0 or self.blocks:
                raise ValueError("REVIEW_PAGE_OFFSET_INVALID")
        elif not self.blocks or self.blocks[0].character_start != self.character_offset:
            raise ValueError("REVIEW_PAGE_OFFSET_INVALID")
        indexes = tuple(block.block_index for block in self.blocks)
        if indexes and indexes != tuple(range(self.offset, self.offset + len(self.blocks))):
            raise ValueError("REVIEW_PAGE_INDEX_INVALID")
        if len(self.blocks) > self.limit or any(
            left.character_end != left.source_character_count or right.character_start != 0
            for left, right in zip(self.blocks, self.blocks[1:], strict=False)
        ):
            raise ValueError("REVIEW_PAGE_BLOCK_SPAN_INVALID")
        if self.page_start != self.offset:
            raise ValueError("REVIEW_PAGE_START_INVALID")
        if self.blocks and self.blocks[-1].block_index >= self.retained_total:
            raise ValueError("REVIEW_PAGE_INDEX_INVALID")
        if (self.next_offset is None) != (self.next_character_offset is None):
            raise ValueError("REVIEW_PAGE_NEXT_INVALID")
        if self.blocks:
            last = self.blocks[-1]
            if self.next_offset == last.block_index:
                if (
                    self.next_character_offset != last.character_end
                    or not last.text_truncated
                    or self.page_text_characters != MAX_PAGE_TEXT_CHARACTERS
                ):
                    raise ValueError("REVIEW_PAGE_NEXT_INVALID")
            elif self.next_offset is not None:
                if (
                    self.next_offset != last.block_index + 1
                    or self.next_character_offset != 0
                    or last.character_end != last.source_character_count
                    or (
                        len(self.blocks) < self.limit
                        and self.page_text_characters < MAX_PAGE_TEXT_CHARACTERS
                    )
                ):
                    raise ValueError("REVIEW_PAGE_NEXT_INVALID")
            elif (
                last.block_index + 1 < self.retained_total
                or last.character_end != last.source_character_count
            ):
                raise ValueError("REVIEW_PAGE_NEXT_INVALID")
        elif self.next_offset is not None:
            raise ValueError("REVIEW_PAGE_NEXT_INVALID")
        if self.page_text_characters != sum(len(block.text) for block in self.blocks):
            raise ValueError("REVIEW_PAGE_CHARACTER_COUNT_INVALID")
        if self.page_text_truncated != any(block.text_truncated for block in self.blocks):
            raise ValueError("REVIEW_PAGE_TRUNCATION_INVALID")
        if self.page_text_truncated != bool(self.page_reasons):
            raise ValueError("REVIEW_PAGE_REASON_INVALID")
        totals = (
            self.source_units_total,
            self.source_units_extracted,
            self.characters_extracted,
            self.blocks_extracted_total,
        )
        if self.rejection_code is not None:
            if (
                any(value is not None for value in totals)
                or self.retained_total
                or self.retained_characters
                or self.retention_truncated
                or self.retention_reasons
                or self.retained_extracted_text_complete
            ):
                raise ValueError("REVIEW_PAGE_REJECTION_HAS_FACTS")
        elif any(value is None for value in totals):
            raise ValueError("REVIEW_PAGE_EXTRACTION_TOTAL_MISSING")
        if self.blocks_extracted_total is not None:
            assert self.source_units_total is not None
            assert self.source_units_extracted is not None
            assert self.characters_extracted is not None
            if self.source_units_extracted > self.source_units_total:
                raise ValueError("REVIEW_PAGE_EXTRACTED_SOURCE_UNIT_COUNT_INVALID")
            if self.source_units_extracted != self.blocks_extracted_total:
                raise ValueError("REVIEW_PAGE_EXTRACTED_BLOCK_COUNT_INVALID")
            if self.retained_characters > self.characters_extracted:
                raise ValueError("REVIEW_PAGE_RETENTION_CHARACTER_COUNT_INVALID")
            if self.retained_total > self.blocks_extracted_total:
                raise ValueError("REVIEW_PAGE_RETENTION_COUNT_INVALID")
            if self.retention_truncated != (self.retained_total < self.blocks_extracted_total):
                raise ValueError("REVIEW_PAGE_RETENTION_FLAG_INVALID")
            if (
                not self.retention_truncated
                and self.retained_characters != self.characters_extracted
            ):
                raise ValueError("REVIEW_PAGE_RETENTION_CHARACTER_COUNT_INVALID")
            if self.retention_truncated and self.retained_characters >= self.characters_extracted:
                raise ValueError("REVIEW_PAGE_RETENTION_CHARACTER_COUNT_INVALID")
        if self.retention_truncated != bool(self.retention_reasons):
            raise ValueError("REVIEW_PAGE_RETENTION_REASON_INVALID")
        expected_retained_complete = (
            self.rejection_code is None
            and not self.retention_truncated
            and self.retained_total > 0
            and self.retained_characters > 0
            and self.retained_total == self.blocks_extracted_total
            and self.retained_characters == self.characters_extracted
        )
        if self.retained_extracted_text_complete != expected_retained_complete:
            raise ValueError("REVIEW_PAGE_RETAINED_COMPLETENESS_INVALID")
        if any(block.provenance.document_id != self.sha256 for block in self.blocks):
            raise ValueError("REVIEW_PAGE_PROVENANCE_MISMATCH")
        index_set = {block.block_index for block in self.blocks}
        if (
            len(set(self.delivery_lead_indices)) != len(self.delivery_lead_indices)
            or not set(self.delivery_lead_indices) <= index_set
        ):
            raise ValueError("REVIEW_DELIVERY_LEADS_INVALID")
        return self


def _safe_filename(filename: object) -> str:
    if not isinstance(filename, str) or not filename or len(filename) > 1_024 or "\x00" in filename:
        raise ValueError("REVIEW_DOCUMENT_FILENAME_INVALID")
    if PurePath(filename).name != filename or PureWindowsPath(filename).name != filename:
        raise ValueError("REVIEW_DOCUMENT_FILENAME_INVALID")
    if not filename.casefold().endswith(".docx"):
        raise ValueError("REVIEW_DOCUMENT_FORMAT_UNSUPPORTED")
    return filename


def analyze_review_document(content: bytes, filename: str) -> ReviewDocumentAnalysis:
    """Extract a bounded whole-block DOCX prefix with exact digest provenance."""
    safe_filename = _safe_filename(filename)
    if type(content) is not bytes or not content:
        raise ValueError("REVIEW_DOCUMENT_CONTENT_INVALID")
    if len(content) > MAX_REVIEW_INPUT_BYTES:
        raise ValueError("REVIEW_DOCUMENT_BYTES_LIMIT")
    digest = hashlib.sha256(content).hexdigest()
    try:
        extracted = extract_document(
            DocumentInput(
                document_id=digest,
                filename=safe_filename,
                declared_media_type=DOCX_MEDIA_TYPE,
                content=content,
            ),
            limits=REVIEW_EXTRACTION_LIMITS,
        )
    except DocumentRejected as error:
        return ReviewDocumentAnalysis(
            sha256=digest,
            filename=safe_filename,
            byte_count=len(content),
            extraction_status="UNKNOWN",
            extraction_reasons=("DOCUMENT_REJECTED",),
            rejection_code=error.code.value,
            blocks=(),
            retained_blocks=0,
            retained_characters=0,
            retention_truncated=False,
            retention_reasons=(),
            retained_extracted_text_complete=False,
            native_text_completeness="UNKNOWN",
        )

    retained: list[ExtractedBlock] = []
    retained_characters = 0
    for block in extracted.blocks:
        if len(retained) == MAX_REVIEW_BLOCKS:
            break
        if retained_characters + len(block.text) > MAX_REVIEW_CHARACTERS:
            break
        retained.append(block)
        retained_characters += len(block.text)
    truncated = len(retained) < len(extracted.blocks)
    retention_reasons = []
    if len(extracted.blocks) > MAX_REVIEW_BLOCKS:
        retention_reasons.append("RETAINED_BLOCK_LIMIT")
    if sum(len(block.text) for block in extracted.blocks[: MAX_REVIEW_BLOCKS + 1]) > (
        MAX_REVIEW_CHARACTERS
    ):
        retention_reasons.append("RETAINED_CHARACTER_LIMIT")
    retained_complete = not truncated and bool(retained) and retained_characters > 0
    return ReviewDocumentAnalysis(
        sha256=digest,
        filename=safe_filename,
        byte_count=len(content),
        extraction_status=extracted.status.value,
        extraction_reasons=tuple(reason.value for reason in extracted.reasons),
        source_units_total=extracted.source_units_total,
        source_units_extracted=extracted.source_units_extracted,
        characters_extracted=extracted.characters_extracted,
        blocks_extracted_total=len(extracted.blocks),
        blocks=tuple(retained),
        retained_blocks=len(retained),
        retained_characters=retained_characters,
        retention_truncated=truncated,
        retention_reasons=tuple(retention_reasons),
        retained_extracted_text_complete=retained_complete,
        native_text_completeness="UNKNOWN",
    )


_DELIVERY = re.compile(r"поставк|доставк|отгрузк|монтаж", re.IGNORECASE)


def review_document_page(
    analysis: ReviewDocumentAnalysis,
    offset: int,
    limit: int,
    *,
    character_offset: int = 0,
) -> ReviewDocumentPage:
    """Return a deterministic bounded view; delivery matches remain unstructured leads."""
    if type(offset) is not int or not 0 <= offset <= 999:
        raise ValueError("REVIEW_PAGE_OFFSET_INVALID")
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("REVIEW_PAGE_LIMIT_INVALID")
    if type(character_offset) is not int or character_offset < 0:
        raise ValueError("REVIEW_PAGE_CHARACTER_OFFSET_INVALID")
    if offset >= analysis.retained_blocks:
        if character_offset != 0:
            raise ValueError("REVIEW_PAGE_CHARACTER_OFFSET_INVALID")
    elif character_offset >= len(analysis.blocks[offset].text):
        raise ValueError("REVIEW_PAGE_CHARACTER_OFFSET_INVALID")
    remaining = MAX_PAGE_TEXT_CHARACTERS
    page_blocks: list[ReviewPageBlock] = []
    next_offset: int | None = None
    next_character_offset: int | None = None
    for block_index in range(offset, min(offset + limit, analysis.retained_blocks)):
        block = analysis.blocks[block_index]
        start = character_offset if block_index == offset else 0
        end = min(len(block.text), start + remaining)
        if end <= start:
            break
        page_blocks.append(
            ReviewPageBlock(
                block_index=block_index,
                character_start=start,
                character_end=end,
                source_character_count=len(block.text),
                text=block.text[start:end],
                provenance=block.provenance,
                text_truncated=start != 0 or end != len(block.text),
            )
        )
        remaining -= end - start
        if end < len(block.text):
            next_offset, next_character_offset = block_index, end
            break
        if remaining == 0 and block_index + 1 < analysis.retained_blocks:
            next_offset, next_character_offset = block_index + 1, 0
            break
    else:
        page_end = offset + len(page_blocks)
        if page_end < analysis.retained_blocks:
            next_offset, next_character_offset = page_end, 0
    matches = {block.block_index for block in page_blocks if _DELIVERY.search(block.text)}
    page_indexes = {block.block_index for block in page_blocks}
    leads = sorted(
        candidate
        for matched in matches
        for candidate in (matched - 1, matched, matched + 1)
        if candidate in page_indexes
    )
    page = ReviewDocumentPage(
        sha256=analysis.sha256,
        filename=analysis.filename,
        byte_count=analysis.byte_count,
        extraction_status=analysis.extraction_status,
        extraction_reasons=analysis.extraction_reasons,
        rejection_code=analysis.rejection_code,
        source_units_total=analysis.source_units_total,
        source_units_extracted=analysis.source_units_extracted,
        characters_extracted=analysis.characters_extracted,
        blocks_extracted_total=analysis.blocks_extracted_total,
        offset=offset,
        character_offset=character_offset,
        limit=limit,
        retained_total=analysis.retained_blocks,
        retained_characters=analysis.retained_characters,
        retention_truncated=analysis.retention_truncated,
        retention_reasons=analysis.retention_reasons,
        text_scope=analysis.text_scope,
        retained_extracted_text_complete=analysis.retained_extracted_text_complete,
        native_text_completeness=analysis.native_text_completeness,
        page_start=offset,
        next_offset=next_offset,
        next_character_offset=next_character_offset,
        blocks=tuple(page_blocks),
        page_text_characters=sum(len(block.text) for block in page_blocks),
        page_text_truncated=any(block.text_truncated for block in page_blocks),
        page_reasons=("PAGE_TEXT_LIMIT",)
        if any(block.text_truncated for block in page_blocks)
        else (),
        delivery_lead_indices=tuple(dict.fromkeys(leads)),
    )
    if len(page.model_dump_json().encode()) > MAX_PAGE_RESPONSE_BYTES:
        raise ValueError("REVIEW_PAGE_RESPONSE_LIMIT")
    return page
