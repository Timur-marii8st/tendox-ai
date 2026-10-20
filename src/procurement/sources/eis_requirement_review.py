"""Two-person, exact-payload review of a bounded paper-format proposal."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from procurement.domain.compliance import RequirementCheck, check_requirement
from procurement.domain.offers import Attribute, Candidate
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement
from procurement.sources.eis_requirement_preview import (
    RequirementPreview,
    RequirementPreviewRequest,
    canonical_sha,
)

Mode = Literal["MANUAL", "PAPER_FORMAT"]
RowNumber = Annotated[int, Field(strict=True, ge=2, le=25)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _uuid(value: str) -> None:
    if str(UUID(value)) != value:
        raise ValueError("REVIEW_UUID_INVALID")


def _identity(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("REVIEW_IDENTITY_NOT_CANONICAL")


def _digest(model: BaseModel, field: str) -> None:
    if getattr(model, field) != canonical_sha(model.model_dump(mode="json", exclude={field})):
        raise ValueError("REVIEW_DIGEST_CONFLICT")


def _format(raw: str) -> str | None:
    match = re.fullmatch(r"([ABАВ])(10|[0-9])", raw.strip())
    if match is None:
        return None
    return {"А": "A", "В": "B"}.get(match[1], match[1]) + match[2]


def _label(raw: str) -> bool:
    return raw.strip().casefold() in {"формат", "формат бумаги"}


class RowChoice(Frozen):
    source_row: RowNumber
    mode: Mode
    supplier_index: int | None = Field(default=None, strict=True, ge=1, le=16)
    mandatory: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def choice(self) -> RowChoice:
        if self.mode == "MANUAL" and self.supplier_index is not None:
            raise ValueError("MANUAL_SUPPLIER_INDEX_FORBIDDEN")
        if self.mode == "PAPER_FORMAT" and (self.supplier_index is None or self.mandatory is None):
            raise ValueError("FORMAT_EXPLICIT_CHOICE_REQUIRED")
        return self


class ProposalRequest(Frozen):
    preview: RequirementPreviewRequest
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: tuple[RowChoice, ...] = Field(min_length=1, max_length=24)
    note: str = Field(default="", max_length=1000)


class RequirementProposal(Frozen):
    company_id: str = Field(min_length=1, max_length=200)
    proposal_id: str
    request: ProposalRequest
    preview: RequirementPreview
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: AwareDatetime
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def evidence(self) -> RequirementProposal:
        _identity(self.company_id)
        _identity(self.prepared_by)
        _uuid(self.proposal_id)
        preview = RequirementPreview.model_validate(self.preview.model_dump())
        request = ProposalRequest.model_validate(self.request.model_dump())
        if (
            request.preview != preview.request
            or request.expected_preview_sha256 != preview.preview_sha256
        ):
            raise ValueError("REVIEW_PREVIEW_CONFLICT")
        if [r.source_row for r in request.rows] != [r.source_row for r in preview.table.rows]:
            raise ValueError("REVIEW_ROWS_INCOMPLETE")
        for choice in request.rows:
            if choice.mode == "PAPER_FORMAT":
                _format_inputs(preview, choice)
        _digest(self, "proposal_sha256")
        return self


def _format_inputs(preview: RequirementPreview, choice: RowChoice) -> tuple[Requirement, Attribute]:
    row = next(row for row in preview.table.rows if row.source_row == choice.source_row)
    cells = {cell.column: cell for cell in row.cells}
    if (
        row.kind != "CHARACTERISTIC"
        or 4 in cells
        or not _label(cells[1].text)
        or _format(cells[3].text) is None
    ):
        raise ValueError("FORMAT_REQUIREMENT_UNSUPPORTED")
    details = preview.product.details
    formats = [
        (index, item)
        for index, item in enumerate(details.characteristics, 1)
        if _label(item.label_raw)
    ]
    if details.status != "EXTRACTED" or len(formats) != 1 or choice.supplier_index != formats[0][0]:
        raise ValueError("FORMAT_SUPPLIER_AMBIGUOUS")
    fact = formats[0][1]
    actual = _format(fact.value_raw)
    if actual is None or choice.mandatory is None:
        raise ValueError("FORMAT_SUPPLIER_UNSUPPORTED")
    required = _format(cells[3].text)
    assert required is not None
    requirement = Requirement(
        property="paper_format",
        operator=Operator.EQ,
        value=required,
        mandatory=choice.mandatory,
        raw_text=cells[1].text + ": " + cells[3].text,
        provenance=cells[3].provenance,
    )
    attribute = Attribute(
        property="paper_format",
        value=actual,
        provenance=Provenance(
            document_id=fact.html_sha256,
            locator=fact.value_locator,
            extractor=Extractor.API,
            confidence=1.0,
        ),
    )
    return requirement, attribute


class DecisionRequest(Frozen):
    proposal_id: str
    expected_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normative_document: bool = Field(strict=True)
    position_association: bool = Field(strict=True)
    confirmed_rows: tuple[RowNumber, ...] = Field(max_length=24)
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def rows(self) -> DecisionRequest:
        _uuid(self.proposal_id)
        if list(self.confirmed_rows) != sorted(set(self.confirmed_rows)):
            raise ValueError("CONFIRMED_ROWS_INVALID")
        return self


class RequirementDecision(Frozen):
    company_id: str = Field(min_length=1, max_length=200)
    decision_id: str
    request: DecisionRequest
    proposal: RequirementProposal
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: AwareDatetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def evidence(self) -> RequirementDecision:
        _identity(self.company_id)
        _identity(self.reviewed_by)
        _uuid(self.decision_id)
        proposal = RequirementProposal.model_validate(self.proposal.model_dump())
        request = DecisionRequest.model_validate(self.request.model_dump())
        if self.company_id != proposal.company_id:
            raise ValueError("REVIEW_COMPANY_CONFLICT")
        if (
            request.proposal_id != proposal.proposal_id
            or request.expected_proposal_sha256 != proposal.proposal_sha256
        ):
            raise ValueError("REVIEW_PROPOSAL_CONFLICT")
        if self.reviewed_by == proposal.prepared_by:
            raise ValueError("REVIEW_SELF_APPROVAL_FORBIDDEN")
        if self.reviewed_at < proposal.prepared_at:
            raise ValueError("REVIEW_TIME_INVALID")
        executable = {
            row.source_row
            for row in proposal.request.rows
            if row.mode == "PAPER_FORMAT" and row.mandatory is not None
        }
        if not set(request.confirmed_rows) <= executable:
            raise ValueError("REVIEW_CONFIRMATION_UNSUPPORTED")
        _digest(self, "decision_sha256")
        return self


class ReviewComparisonRow(Frozen):
    source_row: RowNumber
    mode: Mode
    mandatory: bool | None = Field(strict=True)
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reason: Literal[
        "MANUAL_REVIEW_REQUIRED", "NOT_CONFIRMED", "GLOBAL_CONFIRMATION_MISSING", "FORMAT_CHECKED"
    ]
    check: RequirementCheck | None = None
    supplier_provenance: Provenance | None = None


def _comparison_rows(decision: RequirementDecision) -> tuple[ReviewComparisonRow, ...]:
    result = []
    for choice in decision.proposal.request.rows:
        check = None
        provenance = None
        status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
        reason: Literal[
            "MANUAL_REVIEW_REQUIRED",
            "NOT_CONFIRMED",
            "GLOBAL_CONFIRMATION_MISSING",
            "FORMAT_CHECKED",
        ]
        if choice.mode == "MANUAL":
            reason = "MANUAL_REVIEW_REQUIRED"
        elif not decision.request.normative_document or not decision.request.position_association:
            reason = "GLOBAL_CONFIRMATION_MISSING"
        elif choice.source_row not in decision.request.confirmed_rows:
            reason = "NOT_CONFIRMED"
        else:
            requirement, attribute = _format_inputs(decision.proposal.preview, choice)
            candidate = Candidate(
                candidate_id=decision.proposal.preview.product.run_id,
                name="Reviewed saved supplier product",
                attributes=(attribute,),
            )
            check = check_requirement(requirement, candidate)
            status = check.verdict.value
            reason = "FORMAT_CHECKED"
            provenance = attribute.provenance
        result.append(
            ReviewComparisonRow(
                source_row=choice.source_row,
                mode=choice.mode,
                mandatory=choice.mandatory,
                status=status,
                reason=reason,
                check=check,
                supplier_provenance=provenance,
            )
        )
    return tuple(result)


class RequirementComparison(Frozen):
    company_id: str = Field(min_length=1, max_length=200)
    proposal_id: str
    decision_id: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: RequirementDecision
    rows: tuple[ReviewComparisonRow, ...] = Field(min_length=1, max_length=24)
    candidate_blocked: bool = Field(strict=True)
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    full_tspec_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def evidence(self) -> RequirementComparison:
        decision = RequirementDecision.model_validate(self.decision.model_dump())
        if (
            self.company_id != decision.company_id
            or self.proposal_id != decision.proposal.proposal_id
            or self.decision_id != decision.decision_id
            or self.proposal_sha256 != decision.proposal.proposal_sha256
            or self.decision_sha256 != decision.decision_sha256
        ):
            raise ValueError("COMPARISON_BINDING_CONFLICT")
        expected = _comparison_rows(decision)
        blocked = any(row.status == "FAIL" and row.mandatory is True for row in expected)
        if self.rows != expected or self.candidate_blocked != blocked:
            raise ValueError("COMPARISON_DERIVATION_CONFLICT")
        _digest(self, "comparison_sha256")
        return self


def build_requirement_proposal(
    *,
    company_id: str,
    proposal_id: str,
    request: ProposalRequest,
    preview: RequirementPreview,
    prepared_by: str,
    prepared_at: datetime,
) -> RequirementProposal:
    payload = dict(
        company_id=company_id,
        proposal_id=proposal_id,
        request=request.model_dump(mode="json"),
        preview=preview.model_dump(mode="json"),
        prepared_by=prepared_by,
        prepared_at=to_jsonable_python(prepared_at),
        source_requests=0,
        jobs_created=0,
    )
    return RequirementProposal.model_validate(
        {**payload, "proposal_sha256": canonical_sha(payload)}
    )


def build_requirement_decision(
    *,
    company_id: str,
    decision_id: str,
    request: DecisionRequest,
    proposal: RequirementProposal,
    reviewed_by: str,
    reviewed_at: datetime,
) -> RequirementDecision:
    payload = dict(
        company_id=company_id,
        decision_id=decision_id,
        request=request.model_dump(mode="json"),
        proposal=proposal.model_dump(mode="json"),
        reviewed_by=reviewed_by,
        reviewed_at=to_jsonable_python(reviewed_at),
        source_requests=0,
        jobs_created=0,
    )
    return RequirementDecision.model_validate(
        {**payload, "decision_sha256": canonical_sha(payload)}
    )


def build_requirement_comparison(decision: RequirementDecision) -> RequirementComparison:
    decision = RequirementDecision.model_validate(decision.model_dump())
    rows = _comparison_rows(decision)
    payload = dict(
        company_id=decision.company_id,
        proposal_id=decision.proposal.proposal_id,
        decision_id=decision.decision_id,
        proposal_sha256=decision.proposal.proposal_sha256,
        decision_sha256=decision.decision_sha256,
        decision=decision.model_dump(mode="json"),
        rows=[row.model_dump(mode="json") for row in rows],
        candidate_blocked=any(row.status == "FAIL" and row.mandatory is True for row in rows),
        technical="UNKNOWN",
        full_tspec_completeness="UNKNOWN",
        participation="UNKNOWN",
        source_requests=0,
        jobs_created=0,
    )
    return RequirementComparison.model_validate(
        {**payload, "comparison_sha256": canonical_sha(payload)}
    )
