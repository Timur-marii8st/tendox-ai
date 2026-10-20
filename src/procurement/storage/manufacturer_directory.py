"""Bounded read-only projection of independently reviewed manufacturers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from procurement.domain.manufacturer_directory import (
    DirectoryCoverage,
    DirectoryRecordInput,
    DirectoryReviewEvidence,
    ManufacturerDirectory,
    build_directory,
)
from procurement.domain.manufacturer_review import (
    ReviewStatus,
    StableManufacturerDossier,
    current_review_status,
)
from procurement.sources.eaeu_registry import RegistryCandidate
from procurement.storage.manufacturer_review import (
    ManufacturerReviewNotFound,
    ManufacturerReviewSourceMismatch,
    _read_decision_connection,
    _read_proposal_connection,
)
from procurement.storage.manufacturer_search import read_search
from procurement.storage.models import manufacturer_review_proposals as proposals
from procurement.storage.repository import PostgresStorage

MAX_LINKED_REVIEWS = 20


def _stable_candidate(
    run_id: str, response_sha256: str, candidate: RegistryCandidate
) -> StableManufacturerDossier:
    return StableManufacturerDossier(
        run_id=run_id,
        record_id=candidate.record_id,
        response_sha256=response_sha256,
        source_record_index=candidate.source_record_index,
        registry_number=candidate.registry_number,
        product_name=candidate.product_name,
        source_manufacturer_name=candidate.manufacturer_name,
        record_url=candidate.record_url,
        document_expires_on=(
            candidate.document_expires_on.isoformat()
            if candidate.document_expires_on is not None
            else None
        ),
    )


def build_manufacturer_directory(
    storage: PostgresStorage,
    company_id: str,
    run_id: str,
    *,
    evaluated_at: datetime | None = None,
) -> ManufacturerDirectory:
    """Read at most 20 linked reviews and never perform source I/O or persist projection state."""
    instant = evaluated_at or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("MANUFACTURER_DIRECTORY_TIME_NAIVE")
    saved_search = read_search(storage, company_id, run_id)
    report = saved_search.report
    response_sha = report.response_sha256
    reviews: dict[str, list[DirectoryReviewEvidence]] = {
        candidate.record_id: [] for candidate in report.candidates
    }
    with storage.transaction(company_id, consistent_read=True) as conn:
        proposal_rows = conn.execute(
            select(proposals.c.proposal_id, proposals.c.record_id)
            .where(
                (proposals.c.company_id == company_id) & (proposals.c.run_id == run_id)
            )
            .order_by(proposals.c.proposed_at, proposals.c.proposal_id)
            .limit(MAX_LINKED_REVIEWS + 1)
        ).mappings().all()
        proposal_ids = [row["proposal_id"] for row in proposal_rows]
        candidate_ids = tuple(candidate.record_id for candidate in report.candidates)
        linked_record_ids = frozenset(
            conn.scalars(
                select(proposals.c.record_id)
                .where(
                    (proposals.c.company_id == company_id)
                    & (proposals.c.run_id == run_id)
                    & proposals.c.record_id.in_(candidate_ids)
                )
                .distinct()
            ).all()
        )
        overflow = len(proposal_rows) > MAX_LINKED_REVIEWS
        candidates = {candidate.record_id: candidate for candidate in report.candidates}
        if not overflow:
            for proposal_id in proposal_ids:
                proposal = _read_proposal_connection(conn, company_id, proposal_id)
                candidate = candidates.get(proposal.dossier.record_id)
                if candidate is None or response_sha is None:
                    raise ManufacturerReviewSourceMismatch(
                        "MANUFACTURER_DIRECTORY_PROPOSAL_SOURCE_CONFLICT"
                    )
                if proposal.dossier != _stable_candidate(run_id, response_sha, candidate):
                    raise ManufacturerReviewSourceMismatch(
                        "MANUFACTURER_DIRECTORY_PROPOSAL_SOURCE_CONFLICT"
                    )
                try:
                    decision = _read_decision_connection(conn, company_id, proposal)
                except ManufacturerReviewNotFound:
                    decision_id = decision_sha = None
                    status = ReviewStatus.UNKNOWN
                else:
                    decision_id = decision.decision_id
                    decision_sha = decision.decision_sha256
                    status = current_review_status(decision, at=instant)
                reviews[candidate.record_id].append(
                    DirectoryReviewEvidence(
                        proposal_id=proposal.proposal_id,
                        proposal_sha256=proposal.proposal_sha256,
                        decision_id=decision_id,
                        decision_sha256=decision_sha,
                        dossier_sha256=proposal.dossier_sha256,
                        identity=proposal.claimed_identity,
                        current_status=status,
                    )
                )
    coverage = (
        DirectoryCoverage.COMPLETE
        if report.status == "COMPLETED" and not overflow
        else DirectoryCoverage.INCOMPLETE
    )
    inputs = tuple(
        DirectoryRecordInput(
            record_id=candidate.record_id,
            source_record_index=candidate.source_record_index,
            registry_number=candidate.registry_number,
            product_name=candidate.product_name,
            source_manufacturer_name=candidate.manufacturer_name,
            record_url=candidate.record_url,
            document_expires_on=candidate.document_expires_on,
            reviews=tuple(reviews[candidate.record_id]),
        )
        for candidate in report.candidates
    )
    return build_directory(
        run_id,
        inputs,
        response_sha256=response_sha,
        coverage=coverage,
        review_count=min(len(proposal_ids), MAX_LINKED_REVIEWS),
        reviewed_record_ids=linked_record_ids,
        evaluated_at=instant,
    )
