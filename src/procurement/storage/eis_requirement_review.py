"""Immutable two-person review over exact requirement preview snapshots."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Text, and_, cast, func, insert, select
from sqlalchemy.engine import Connection

from procurement.sources.eis_requirement_preview import canonical_sha
from procurement.sources.eis_requirement_review import (
    DecisionRequest,
    ProposalRequest,
    RequirementComparison,
    RequirementDecision,
    RequirementProposal,
    build_requirement_comparison,
    build_requirement_decision,
    build_requirement_proposal,
)
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_requirement_preview import read_requirement_preview_connection
from procurement.storage.eis_supplier_page import _tenant_lease, _write
from procurement.storage.models import eis_requirement_review_decisions as decisions
from procurement.storage.models import eis_requirement_review_proposals as proposals
from procurement.storage.repository import PostgresStorage

MAX_REVIEW_BYTES = 384 * 1024


@contextmanager
def _review_lease(storage: PostgresStorage, company: str) -> Iterator[None]:
    try:
        with _tenant_lease(storage, company):
            yield
    except ValueError as error:
        if str(error) in {"SUPPLIER_PAGE_BUSY", "SUPPLIER_PAGE_TENANT_BUSY"}:
            raise ValueError("REQUIREMENT_REVIEW_BUSY") from error
        raise


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SavedRequirementProposal(Frozen):
    proposal: RequirementProposal
    created: bool = Field(strict=True)
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0


class SavedRequirementDecision(Frozen):
    decision: RequirementDecision
    created: bool = Field(strict=True)
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0


def _bounded(model: BaseModel) -> None:
    if len(model.model_dump_json().encode()) > MAX_REVIEW_BYTES:
        raise ValueError("REQUIREMENT_REVIEW_RESPONSE_LIMIT")


def _load_proposal(conn: Connection, company: str, proposal_id: str) -> RequirementProposal:
    scope = and_(proposals.c.company_id == company, proposals.c.proposal_id == proposal_id)
    meta = conn.execute(
        select(
            proposals.c.proposal_id,
            proposals.c.proposal_sha256,
            proposals.c.request_key,
            proposals.c.product_run_id,
            proposals.c.prepared_by,
            proposals.c.prepared_at,
            func.octet_length(cast(proposals.c.proposal, Text)),
        ).where(scope)
    ).one_or_none()
    if meta is None:
        raise LookupError("REQUIREMENT_PROPOSAL_NOT_FOUND")
    if meta[6] > MAX_REVIEW_BYTES:
        raise ValueError("REQUIREMENT_PROPOSAL_EVIDENCE_CONFLICT")
    payload = conn.scalar(select(proposals.c.proposal).where(scope))
    proposal = RequirementProposal.model_validate(payload)
    if (
        proposal.proposal_id != proposal_id
        or proposal.proposal_id != meta[0]
        or canonical_sha(proposal.model_dump(mode="json", exclude={"proposal_sha256"})) != meta[1]
        or proposal.proposal_sha256 != meta[1]
        or canonical_sha(
            {"actor": proposal.prepared_by, "request": proposal.request.model_dump(mode="json")}
        )
        != meta[2]
        or proposal.preview.product.run_id != meta[3]
        or proposal.prepared_by != meta[4]
        or proposal.prepared_at != meta[5]
        or proposal.company_id != company
    ):
        raise ValueError("REQUIREMENT_PROPOSAL_EVIDENCE_CONFLICT")
    preview = read_requirement_preview_connection(conn, company, proposal.request.preview)
    rebuilt = build_requirement_proposal(
        company_id=company,
        proposal_id=proposal.proposal_id,
        request=proposal.request,
        preview=preview,
        prepared_by=proposal.prepared_by,
        prepared_at=proposal.prepared_at,
    )
    if rebuilt != proposal:
        raise ValueError("REQUIREMENT_PROPOSAL_EVIDENCE_CONFLICT")
    return proposal


def create_requirement_proposal(
    storage: PostgresStorage,
    company: str,
    request: ProposalRequest,
    *,
    actor_id: str,
) -> SavedRequirementProposal:
    if not actor_id.strip():
        raise ValueError("REQUIREMENT_REVIEW_ACTOR_INVALID")
    key = canonical_sha({"actor": actor_id, "request": request.model_dump(mode="json")})
    with _review_lease(storage, company), _write(storage, company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        existing = conn.scalar(
            select(proposals.c.proposal_id).where(
                proposals.c.company_id == company, proposals.c.request_key == key
            )
        )
        if existing is not None:
            return SavedRequirementProposal(
                proposal=_load_proposal(conn, company, existing), created=False
            )
        preview = read_requirement_preview_connection(conn, company, request.preview)
        if preview.preview_sha256 != request.expected_preview_sha256:
            raise ValueError("REQUIREMENT_PREVIEW_DIGEST_CONFLICT")
        proposal = build_requirement_proposal(
            company_id=company,
            proposal_id=str(uuid.uuid4()),
            request=request,
            preview=preview,
            prepared_by=actor_id,
            prepared_at=datetime.now(UTC),
        )
        _bounded(proposal)
        conn.execute(
            insert(proposals).values(
                company_id=company,
                proposal_id=proposal.proposal_id,
                request_key=key,
                product_run_id=proposal.preview.product.run_id,
                proposal=proposal.model_dump(mode="json"),
                proposal_sha256=proposal.proposal_sha256,
                prepared_by=actor_id,
                prepared_at=proposal.prepared_at,
            )
        )
        _audit(
            conn,
            company,
            actor_id,
            request.preview.document.notice,
            "EIS_REQUIREMENT_PROPOSAL_CREATED",
            {"proposal_id": proposal.proposal_id, "proposal_sha256": proposal.proposal_sha256},
        )
        return SavedRequirementProposal(proposal=proposal, created=True)


def read_requirement_proposal(
    storage: PostgresStorage, company: str, proposal_id: str
) -> SavedRequirementProposal:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        return SavedRequirementProposal(
            proposal=_load_proposal(conn, company, proposal_id), created=False
        )


def _load_decision(
    conn: Connection, company: str, proposal: RequirementProposal
) -> RequirementDecision:
    scope = and_(
        decisions.c.company_id == company,
        decisions.c.proposal_id == proposal.proposal_id,
    )
    meta = conn.execute(
        select(
            decisions.c.decision_id,
            decisions.c.proposal_id,
            decisions.c.request_sha256,
            decisions.c.decision_sha256,
            decisions.c.reviewed_by,
            decisions.c.reviewed_at,
            func.octet_length(cast(decisions.c.decision, Text)),
        ).where(scope)
    ).one_or_none()
    if meta is None:
        raise LookupError("REQUIREMENT_DECISION_NOT_FOUND")
    if meta[6] > MAX_REVIEW_BYTES:
        raise ValueError("REQUIREMENT_DECISION_EVIDENCE_CONFLICT")
    payload = conn.scalar(select(decisions.c.decision).where(scope))
    decision = RequirementDecision.model_validate(payload)
    rebuilt = build_requirement_decision(
        company_id=company,
        decision_id=decision.decision_id,
        request=decision.request,
        proposal=proposal,
        reviewed_by=decision.reviewed_by,
        reviewed_at=decision.reviewed_at,
    )
    if (
        rebuilt != decision
        or decision.decision_id != meta[0]
        or decision.request.proposal_id != meta[1]
        or canonical_sha(decision.request) != meta[2]
        or decision.decision_sha256 != meta[3]
        or decision.reviewed_by != meta[4]
        or decision.reviewed_at != meta[5]
        or decision.company_id != company
    ):
        raise ValueError("REQUIREMENT_DECISION_EVIDENCE_CONFLICT")
    return decision


def create_requirement_decision(
    storage: PostgresStorage,
    company: str,
    request: DecisionRequest,
    *,
    actor_id: str,
) -> SavedRequirementDecision:
    if not actor_id.strip():
        raise ValueError("REQUIREMENT_REVIEW_ACTOR_INVALID")
    with _review_lease(storage, company), _write(storage, company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        proposal = _load_proposal(conn, company, request.proposal_id)
        if request.expected_proposal_sha256 != proposal.proposal_sha256:
            raise ValueError("REQUIREMENT_PROPOSAL_DIGEST_CONFLICT")
        try:
            existing = _load_decision(conn, company, proposal)
        except LookupError:
            existing = None
        if existing is not None:
            if existing.request != request or existing.reviewed_by != actor_id:
                raise ValueError("REQUIREMENT_DECISION_CONFLICT")
            return SavedRequirementDecision(decision=existing, created=False)
        decision = build_requirement_decision(
            company_id=company,
            decision_id=str(uuid.uuid4()),
            request=request,
            proposal=proposal,
            reviewed_by=actor_id,
            reviewed_at=datetime.now(UTC),
        )
        _bounded(decision)
        conn.execute(
            insert(decisions).values(
                company_id=company,
                decision_id=decision.decision_id,
                proposal_id=proposal.proposal_id,
                request_sha256=canonical_sha(request),
                decision=decision.model_dump(mode="json"),
                decision_sha256=decision.decision_sha256,
                reviewed_by=actor_id,
                reviewed_at=decision.reviewed_at,
            )
        )
        _audit(
            conn,
            company,
            actor_id,
            proposal.request.preview.document.notice,
            "EIS_REQUIREMENT_DECISION_CREATED",
            {"proposal_id": proposal.proposal_id, "decision_id": decision.decision_id},
        )
        return SavedRequirementDecision(decision=decision, created=True)


def read_requirement_comparison(
    storage: PostgresStorage, company: str, proposal_id: str
) -> RequirementComparison:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        proposal = _load_proposal(conn, company, proposal_id)
        decision = _load_decision(conn, company, proposal)
        comparison = build_requirement_comparison(decision)
        _bounded(comparison)
        return comparison
