"""Typed read-only preview of one retained DOCX requirement table."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from procurement.sources.eis_requirement_table import EISRequirementTable
from procurement.sources.eis_supplier_product import SupplierProductReport, SupplierProductRequest
from procurement.storage.eis_document_review import ReviewDocumentRequest

POLICY_VERSION: Literal["eis-requirement-preview-v1"] = "eis-requirement-preview-v1"


def canonical_sha(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RequirementPreviewRequest(Frozen):
    product: SupplierProductRequest
    document: ReviewDocumentRequest
    table_index: int = Field(strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def exact_notice(self) -> Self:
        if self.document.notice != self.product.catalog.page.position.selection.notice:
            raise ValueError("REQUIREMENT_PREVIEW_NOTICE_CONFLICT")
        return self


class RequirementPreview(Frozen):
    policy_version: Literal["eis-requirement-preview-v1"] = POLICY_VERSION
    scope: Literal["SELECTED_RETAINED_DOCX_TABLE"] = "SELECTED_RETAINED_DOCX_TABLE"
    request: RequirementPreviewRequest
    product: SupplierProductReport
    product_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_observation_id: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    analyzed_at: AwareDatetime
    filename: str = Field(min_length=1, max_length=500)
    table: EISRequirementTable
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_requirement_status: Literal["UNKNOWN"] = "UNKNOWN"
    document_role: Literal["UNKNOWN"] = "UNKNOWN"
    position_association: Literal["UNKNOWN"] = "UNKNOWN"
    full_tspec_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0
    database_writes: Literal[0] = 0

    @model_validator(mode="after")
    def exact_bindings(self) -> Self:
        if self.product.request != self.request.product:
            raise ValueError("REQUIREMENT_PREVIEW_PRODUCT_CONFLICT")
        if canonical_sha(self.product) != self.product_report_sha256:
            raise ValueError("REQUIREMENT_PREVIEW_PRODUCT_DIGEST_CONFLICT")
        if self.table.document_sha256 != self.request.document.expected_document_sha256:
            raise ValueError("REQUIREMENT_PREVIEW_DOCUMENT_DIGEST_CONFLICT")
        if self.table.table_index != self.request.table_index:
            raise ValueError("REQUIREMENT_PREVIEW_TABLE_CONFLICT")
        payload = self.model_dump(mode="json", exclude={"preview_sha256"})
        if canonical_sha(payload) != self.preview_sha256:
            raise ValueError("REQUIREMENT_PREVIEW_DIGEST_CONFLICT")
        return self


def build_requirement_preview(**values: object) -> RequirementPreview:
    """Build the response with its deterministic self digest."""

    payload = {
        "policy_version": POLICY_VERSION,
        "scope": "SELECTED_RETAINED_DOCX_TABLE",
        **values,
    }
    serialized = to_jsonable_python(payload)
    return RequirementPreview.model_validate(
        {**serialized, "preview_sha256": canonical_sha(serialized)}
    )
