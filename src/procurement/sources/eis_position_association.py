"""Immutable operator links between one saved EIS position and cached DOCX text spans."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.provenance import Provenance
from procurement.sources.eis_223_archive import TextFact
from procurement.sources.eis_characteristic_compare import SavedPosition
from procurement.sources.eis_document_review import REVIEW_VERSION, ReviewDocumentAnalysis
from procurement.storage.eis_document_review import ReviewDocumentRequest
from procurement.storage.eis_supplier_search import SupplierSearchRequest

ASSOCIATION_POLICY: Literal["eis-position-fragment-association-v1"] = (
    "eis-position-fragment-association-v1"
)
MAX_SELECTED_CHARACTERS = 16_000


def _canonical_uuid(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as error:
        raise ValueError("POSITION_ASSOCIATION_ID_INVALID") from error
    return value


class AssociationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FragmentSelection(AssociationModel):
    block_index: int = Field(ge=0, le=999, strict=True)
    character_start: int = Field(ge=0, le=99_999, strict=True)
    character_end: int = Field(ge=1, le=100_000, strict=True)

    @model_validator(mode="after")
    def nonempty(self) -> FragmentSelection:
        if self.character_end <= self.character_start:
            raise ValueError("POSITION_ASSOCIATION_RANGE_INVALID")
        return self


class AssociationRequest(AssociationModel):
    position: SupplierSearchRequest
    document: ReviewDocumentRequest
    analyzer_version: Literal["eis-native-review-v1"] = REVIEW_VERSION
    fragments: tuple[FragmentSelection, ...] = Field(min_length=1, max_length=10)

    @field_validator("analyzer_version", mode="before")
    @classmethod
    def strict_analyzer(cls, value: object) -> object:
        if type(value) is not str:
            raise ValueError("POSITION_ASSOCIATION_ANALYZER_INVALID")
        return value

    @model_validator(mode="after")
    def exact_notice_and_order(self) -> AssociationRequest:
        if self.position.selection.notice != self.document.notice:
            raise ValueError("POSITION_ASSOCIATION_NOTICE_MISMATCH")
        previous: FragmentSelection | None = None
        for selection in self.fragments:
            if previous is not None and (
                selection.block_index < previous.block_index
                or (
                    selection.block_index == previous.block_index
                    and selection.character_start < previous.character_end
                )
            ):
                raise ValueError("POSITION_ASSOCIATION_FRAGMENT_ORDER_INVALID")
            previous = selection
        return self


class AssociatedFragment(AssociationModel):
    selection: FragmentSelection
    text: str = Field(min_length=1, max_length=MAX_SELECTED_CHARACTERS)
    provenance: Provenance
    source_character_count: int = Field(ge=1, le=100_000, strict=True)


class PositionFragmentAssociationReport(AssociationModel):
    policy_version: Literal["eis-position-fragment-association-v1"] = ASSOCIATION_POLICY
    association_id: str
    request: AssociationRequest
    position_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_name: TextFact
    analysis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=1_024)
    observation_id: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    analyzed_at: AwareDatetime
    created_at: AwareDatetime
    linked_by: str = Field(min_length=1, max_length=200)
    fragments: tuple[AssociatedFragment, ...] = Field(min_length=1, max_length=10)
    retained_total: int = Field(ge=1, le=1_000, strict=True)
    retained_characters: int = Field(ge=1, le=100_000, strict=True)
    selected_characters: int = Field(ge=1, le=MAX_SELECTED_CHARACTERS, strict=True)
    association_status: Literal["OPERATOR_LINKED"] = "OPERATOR_LINKED"
    requirement_status: Literal["UNKNOWN"] = "UNKNOWN"
    full_tspec_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def consistent(self) -> PositionFragmentAssociationReport:
        try:
            if str(uuid.UUID(self.association_id)) != self.association_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("POSITION_ASSOCIATION_ID_INVALID") from error
        if self.document_sha256 != self.request.document.expected_document_sha256:
            raise ValueError("POSITION_ASSOCIATION_DOCUMENT_MISMATCH")
        if self.position_name.provenance.document_id != (
            self.request.position.selection.notice.notice_xml_sha256
        ):
            raise ValueError("POSITION_ASSOCIATION_POSITION_PROVENANCE_MISMATCH")
        if tuple(fragment.selection for fragment in self.fragments) != self.request.fragments:
            raise ValueError("POSITION_ASSOCIATION_FRAGMENT_BINDING_INVALID")
        if self.selected_characters != sum(len(fragment.text) for fragment in self.fragments):
            raise ValueError("POSITION_ASSOCIATION_CHARACTER_COUNT_INVALID")
        if self.selected_characters > self.retained_characters:
            raise ValueError("POSITION_ASSOCIATION_CHARACTER_COUNT_INVALID")
        for fragment in self.fragments:
            selection = fragment.selection
            if (
                fragment.provenance.document_id != self.document_sha256
                or len(fragment.text) != selection.character_end - selection.character_start
                or selection.character_end > fragment.source_character_count
                or selection.block_index >= self.retained_total
            ):
                raise ValueError("POSITION_ASSOCIATION_FRAGMENT_EVIDENCE_INVALID")
        return self


class SavedAssociation(AssociationModel):
    report: PositionFragmentAssociationReport
    created: bool = Field(strict=True)


class AssociationReadScope(AssociationModel):
    position: SupplierSearchRequest
    document: ReviewDocumentRequest
    analyzer_version: Literal["eis-native-review-v1"] = REVIEW_VERSION

    @model_validator(mode="after")
    def exact_notice(self) -> AssociationReadScope:
        if self.position.selection.notice != self.document.notice:
            raise ValueError("POSITION_ASSOCIATION_NOTICE_MISMATCH")
        return self


class AssociationCursor(AssociationModel):
    created_at: AwareDatetime
    association_id: str

    @field_validator("association_id")
    @classmethod
    def canonical_id(cls, value: str) -> str:
        return _canonical_uuid(value)


class AssociationListRequest(AssociationModel):
    scope: AssociationReadScope
    cursor: AssociationCursor | None = None
    limit: int = Field(default=20, ge=1, le=20, strict=True)


class AssociationMetadata(AssociationModel):
    association_id: str
    created_at: AwareDatetime
    linked_by: str = Field(min_length=1, max_length=200)
    fragment_count: int = Field(ge=1, le=10, strict=True)
    selected_characters: int = Field(ge=1, le=MAX_SELECTED_CHARACTERS, strict=True)

    _canonical_id = field_validator("association_id")(_canonical_uuid)

    @model_validator(mode="after")
    def counts(self) -> AssociationMetadata:
        if self.selected_characters < self.fragment_count:
            raise ValueError("POSITION_ASSOCIATION_METADATA_COUNT_INVALID")
        return self


class AssociationListResult(AssociationModel):
    request: AssociationListRequest
    items: tuple[AssociationMetadata, ...] = Field(max_length=20)
    next_cursor: AssociationCursor | None
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0
    writes: Literal[0] = 0

    @model_validator(mode="after")
    def page_binding(self) -> AssociationListResult:
        keys = [(item.created_at, item.association_id) for item in self.items]
        if (
            keys != sorted(keys, reverse=True)
            or len({item.association_id for item in self.items}) != len(self.items)
            or len(set(keys)) != len(keys)
        ):
            raise ValueError("POSITION_ASSOCIATION_PAGE_ORDER_INVALID")
        if len(self.items) > self.request.limit:
            raise ValueError("POSITION_ASSOCIATION_PAGE_LIMIT_INVALID")
        if self.request.cursor is not None:
            cursor_key = (
                self.request.cursor.created_at,
                self.request.cursor.association_id,
            )
            if any(key >= cursor_key for key in keys):
                raise ValueError("POSITION_ASSOCIATION_CURSOR_INVALID")
        if self.next_cursor is not None and len(self.items) != self.request.limit:
            raise ValueError("POSITION_ASSOCIATION_CURSOR_INVALID")
        expected = (
            AssociationCursor(
                created_at=self.items[-1].created_at,
                association_id=self.items[-1].association_id,
            )
            if self.items and self.next_cursor is not None
            else None
        )
        if self.next_cursor != expected:
            raise ValueError("POSITION_ASSOCIATION_CURSOR_INVALID")
        return self


class AssociationDetailRequest(AssociationModel):
    scope: AssociationReadScope
    association_id: str

    _canonical_id = field_validator("association_id")(_canonical_uuid)


def build_position_fragment_association(
    request: AssociationRequest,
    position: SavedPosition,
    analysis: ReviewDocumentAnalysis,
    *,
    position_sha256: str,
    observation_id: str,
    observed_at: datetime,
    analyzed_at: datetime,
    linked_by: str,
    now: datetime,
    association_id: str,
) -> PositionFragmentAssociationReport:
    """Select exact stored spans without interpreting them as requirements."""
    if not linked_by.strip():
        raise ValueError("POSITION_ASSOCIATION_ACTOR_MISSING")
    if position.selection != request.position.selection:
        raise ValueError("POSITION_ASSOCIATION_POSITION_MISMATCH")
    if analysis.review_version != request.analyzer_version:
        raise ValueError("POSITION_ASSOCIATION_ANALYZER_MISMATCH")
    analysis_sha256 = hashlib.sha256(
        json.dumps(
            analysis.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    fragments: list[AssociatedFragment] = []
    for selection in request.fragments:
        if selection.block_index >= len(analysis.blocks):
            raise ValueError("POSITION_ASSOCIATION_RANGE_INVALID")
        block = analysis.blocks[selection.block_index]
        if selection.character_end > len(block.text):
            raise ValueError("POSITION_ASSOCIATION_RANGE_INVALID")
        selected = block.text[selection.character_start : selection.character_end]
        fragments.append(
            AssociatedFragment(
                selection=selection,
                text=selected,
                provenance=block.provenance.model_copy(
                    update={
                        "locator": (
                            f"{block.provenance.locator} :: characters"
                            f"[{selection.character_start}:{selection.character_end}]"
                        )
                    }
                ),
                source_character_count=len(block.text),
            )
        )
    selected_characters = sum(len(fragment.text) for fragment in fragments)
    if selected_characters > MAX_SELECTED_CHARACTERS:
        raise ValueError("POSITION_ASSOCIATION_CHARACTER_LIMIT")
    return PositionFragmentAssociationReport(
        association_id=association_id,
        request=request,
        position_sha256=position_sha256,
        position_name=position.position.name,
        analysis_sha256=analysis_sha256,
        document_sha256=analysis.sha256,
        filename=analysis.filename,
        observation_id=observation_id,
        observed_at=observed_at,
        analyzed_at=analyzed_at,
        created_at=now,
        linked_by=linked_by.strip(),
        fragments=tuple(fragments),
        retained_total=analysis.retained_blocks,
        retained_characters=analysis.retained_characters,
        selected_characters=selected_characters,
    )
