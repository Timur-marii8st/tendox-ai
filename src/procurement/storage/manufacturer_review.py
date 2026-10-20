"""Immutable evidence and independent review for one retained manufacturer dossier."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, insert, select, text
from sqlalchemy.engine import Connection

from procurement.domain.manufacturer_review import (
    LegalIdentity,
    ManufacturerCitation,
    ManufacturerReviewDecision,
    ManufacturerReviewProposal,
    ReviewStatus,
    StableManufacturerDossier,
    canonical_sha256,
    current_review_status,
    decision_digest,
    proposal_digest,
    validate_decision,
)
from procurement.storage.manufacturer_search import read_candidate
from procurement.storage.models import audit_events
from procurement.storage.models import manufacturer_evidence_artifacts as artifacts
from procurement.storage.models import manufacturer_review_decisions as decisions
from procurement.storage.models import manufacturer_review_proposals as proposals
from procurement.storage.repository import PostgresStorage

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


class ManufacturerReviewConflict(ValueError):
    pass


class ManufacturerReviewNotFound(LookupError):
    pass


class ManufacturerReviewSourceMismatch(ValueError):
    pass


class ManufacturerReviewIndependenceViolation(ValueError):
    pass


class ManufacturerEvidenceArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    artifact_id: str
    command_id: str
    source_title: str
    source_url: str
    origin_status: Literal["CLAIMED_BY_UPLOADER"] = "CLAIMED_BY_UPLOADER"
    original_filename: str
    media_type: Literal["application/pdf"] = "application/pdf"
    byte_size: int = Field(ge=1, le=MAX_ARTIFACT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    uploaded_by: str
    uploaded_at: AwareDatetime


class ReviewedManufacturerArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    metadata: ManufacturerEvidenceArtifact
    content: bytes


class SavedManufacturerProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal: ManufacturerReviewProposal
    created: bool = Field(strict=True)


class ManufacturerProposalSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal_id: str
    run_id: str
    record_id: str
    legal_name: str
    proposed_by: str
    proposed_at: AwareDatetime
    decision_status: ReviewStatus | None


class SavedManufacturerDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision: ManufacturerReviewDecision
    current_status: ReviewStatus
    created: bool = Field(strict=True)


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _uuid(value: str, code: str) -> str:
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError(code) from error
    if parsed != value:
        raise ValueError(code)
    return value


def _audit(
    conn: Connection,
    company_id: str,
    actor_id: str,
    event_type: str,
    object_id: str,
    basis: dict[str, object],
    at: datetime,
) -> None:
    conn.execute(
        insert(audit_events).values(
            event_id=str(uuid.uuid4()),
            company_id=company_id,
            actor_id=actor_id,
            event_type=event_type,
            object_type="MANUFACTURER_REVIEW",
            object_id=object_id,
            object_version=1,
            basis=basis,
            occurred_at=at,
        )
    )


def _lock(conn: Connection, *keys: str) -> None:
    for key in sorted(set(keys)):
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
        )


def _artifact(row: dict[str, object]) -> ManufacturerEvidenceArtifact:
    return ManufacturerEvidenceArtifact(
        artifact_id=row["artifact_id"],
        command_id=row["command_id"],
        source_title=row["source_title"],
        source_url=row["source_url"],
        original_filename=row["original_filename"],
        byte_size=row["byte_size"],
        sha256=row["sha256"],
        uploaded_by=row["uploaded_by"],
        uploaded_at=row["uploaded_at"],
    )


def store_evidence_artifact(
    storage: PostgresStorage,
    company_id: str,
    content: bytes,
    source_title: str,
    source_url: str,
    original_filename: str,
    actor_id: str,
    command_id: str,
) -> ManufacturerEvidenceArtifact:
    _uuid(command_id, "MANUFACTURER_ARTIFACT_COMMAND_INVALID")
    actor_id = actor_id.strip()
    if not actor_id or len(actor_id) > 200:
        raise ValueError("MANUFACTURER_ARTIFACT_ACTOR_INVALID")
    if not 1 <= len(content) <= MAX_ARTIFACT_BYTES or not content.startswith(b"%PDF-"):
        raise ValueError("MANUFACTURER_ARTIFACT_PDF_INVALID")
    if not source_title.strip() or len(source_title) > 500:
        raise ValueError("MANUFACTURER_ARTIFACT_TITLE_INVALID")
    if not source_url.startswith("https://") or len(source_url) > 2048:
        raise ValueError("MANUFACTURER_ARTIFACT_URL_INVALID")
    if not original_filename.lower().endswith(".pdf") or len(original_filename) > 255:
        raise ValueError("MANUFACTURER_ARTIFACT_FILENAME_INVALID")
    digest = hashlib.sha256(content).hexdigest()
    with storage.transaction(company_id) as conn:
        _lock(conn, company_id + "/manufacturer-artifact/" + command_id)
        replay = conn.execute(
            select(artifacts).where(
                and_(artifacts.c.company_id == company_id, artifacts.c.command_id == command_id)
            )
        ).mappings().one_or_none()
        if replay is not None:
            if (
                bytes(replay["content"]) != content
                or replay["source_title"] != source_title.strip()
                or replay["source_url"] != source_url
                or replay["original_filename"] != original_filename
                or replay["uploaded_by"] != actor_id
            ):
                raise ManufacturerReviewConflict("MANUFACTURER_ARTIFACT_COMMAND_CONFLICT")
            return _artifact(dict(replay))
        artifact_id, now = str(uuid.uuid4()), datetime.now(UTC)
        row = conn.execute(
            insert(artifacts)
            .values(
                company_id=company_id,
                artifact_id=artifact_id,
                command_id=command_id,
                source_title=source_title.strip(),
                source_url=source_url,
                original_filename=original_filename,
                media_type="application/pdf",
                content=content,
                byte_size=len(content),
                sha256=digest,
                uploaded_by=actor_id,
                uploaded_at=now,
            )
            .returning(artifacts)
        ).mappings().one()
        _audit(
            conn,
            company_id,
            actor_id,
            "manufacturer_review.artifact_stored",
            artifact_id,
            {"sha256": digest, "byte_size": len(content), "origin": "CLAIMED_BY_UPLOADER"},
            now,
        )
        return _artifact(dict(row))


def _stable_dossier(storage: PostgresStorage, company_id: str, run_id: str, record_id: str):
    source = read_candidate(storage, company_id, run_id, record_id)
    item = source.candidate
    return StableManufacturerDossier(
        run_id=run_id,
        record_id=record_id,
        response_sha256=source.provenance.response_sha256,
        source_record_index=item.source_record_index,
        registry_number=item.registry_number,
        product_name=item.product_name,
        source_manufacturer_name=item.manufacturer_name,
        record_url=item.record_url,
        document_expires_on=(
            item.document_expires_on.isoformat() if item.document_expires_on else None
        ),
    )


def _load_artifacts(
    conn: Connection, company_id: str, citations: tuple[ManufacturerCitation, ...]
) -> dict[str, dict[str, object]]:
    ids = {citation.artifact_id for citation in citations}
    rows = conn.execute(
        select(artifacts).where(
            and_(artifacts.c.company_id == company_id, artifacts.c.artifact_id.in_(ids))
        )
    ).mappings().all()
    found = {row["artifact_id"]: dict(row) for row in rows}
    if len(found) != len(ids):
        raise ManufacturerReviewSourceMismatch("MANUFACTURER_ARTIFACT_NOT_FOUND")
    for citation in citations:
        row = found[citation.artifact_id]
        content = bytes(row["content"])
        if (
            citation.artifact_sha256 != row["sha256"]
            or len(content) != row["byte_size"]
            or hashlib.sha256(content).hexdigest() != row["sha256"]
        ):
            raise ManufacturerReviewSourceMismatch("MANUFACTURER_ARTIFACT_EVIDENCE_CONFLICT")
    return found


def _build_proposal(
    *,
    proposal_id: str,
    command_id: str,
    dossier: StableManufacturerDossier,
    claimed_identity: LegalIdentity,
    citations: tuple[ManufacturerCitation, ...],
    actor_id: str,
    at: datetime,
) -> ManufacturerReviewProposal:
    payload = {
        "schema_version": "manufacturer-review-proposal-v1",
        "proposal_id": proposal_id,
        "command_id": command_id,
        "dossier": dossier.model_dump(mode="json"),
        "dossier_sha256": canonical_sha256(dossier),
        "claimed_identity": claimed_identity.model_dump(mode="json"),
        "citations": [item.model_dump(mode="json") for item in citations],
        "proposed_by": actor_id,
        "proposed_at": at.isoformat().replace("+00:00", "Z"),
    }
    payload["proposal_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return ManufacturerReviewProposal.model_validate(payload)


def prepare_manufacturer_review(
    storage: PostgresStorage,
    company_id: str,
    run_id: str,
    record_id: str,
    claimed_identity: LegalIdentity,
    citations: tuple[ManufacturerCitation, ...],
    actor_id: str,
    command_id: str,
) -> SavedManufacturerProposal:
    _uuid(command_id, "MANUFACTURER_PROPOSAL_COMMAND_INVALID")
    actor_id = actor_id.strip()
    if not actor_id or len(actor_id) > 200:
        raise ValueError("MANUFACTURER_PROPOSER_INVALID")
    dossier = _stable_dossier(storage, company_id, run_id, record_id)
    with storage.transaction(company_id) as conn:
        _lock(conn, company_id + "/manufacturer-proposal/" + command_id)
        replay = conn.execute(
            select(proposals.c.proposal).where(
                and_(proposals.c.company_id == company_id, proposals.c.command_id == command_id)
            )
        ).scalar_one_or_none()
        if replay is not None:
            stored = ManufacturerReviewProposal.model_validate(replay)
            if (
                stored.dossier != dossier
                or stored.claimed_identity != claimed_identity
                or stored.citations != citations
                or stored.proposed_by != actor_id
            ):
                raise ManufacturerReviewConflict("MANUFACTURER_PROPOSAL_COMMAND_CONFLICT")
            return SavedManufacturerProposal(proposal=stored, created=False)
        _load_artifacts(conn, company_id, citations)
        proposal = _build_proposal(
            proposal_id=str(uuid.uuid4()),
            command_id=command_id,
            dossier=dossier,
            claimed_identity=claimed_identity,
            citations=citations,
            actor_id=actor_id,
            at=datetime.now(UTC),
        )
        canonical = _canonical_bytes(proposal.model_dump(mode="json", exclude={"proposal_sha256"}))
        conn.execute(
            insert(proposals).values(
                company_id=company_id,
                proposal_id=proposal.proposal_id,
                command_id=command_id,
                run_id=run_id,
                record_id=record_id,
                dossier_sha256=proposal.dossier_sha256,
                proposal_sha256=proposal.proposal_sha256,
                proposal_canonical=canonical,
                proposal=proposal.model_dump(mode="json"),
                proposed_by=actor_id,
                proposed_at=proposal.proposed_at,
            )
        )
        _audit(
            conn,
            company_id,
            actor_id,
            "manufacturer_review.proposed",
            proposal.proposal_id,
            {"run_id": run_id, "record_id": record_id, "proposal_sha256": proposal.proposal_sha256},
            proposal.proposed_at,
        )
    return SavedManufacturerProposal(proposal=proposal, created=True)


def _read_proposal_connection(
    conn: Connection, company_id: str, proposal_id: str
) -> ManufacturerReviewProposal:
    row = conn.execute(
        select(proposals).where(
            and_(proposals.c.company_id == company_id, proposals.c.proposal_id == proposal_id)
        )
    ).mappings().one_or_none()
    if row is None:
        raise ManufacturerReviewNotFound("MANUFACTURER_PROPOSAL_NOT_FOUND")
    proposal = ManufacturerReviewProposal.model_validate(row["proposal"])
    canonical = _canonical_bytes(proposal.model_dump(mode="json", exclude={"proposal_sha256"}))
    if (
        bytes(row["proposal_canonical"]) != canonical
        or proposal_digest(proposal) != row["proposal_sha256"]
        or proposal.proposal_id != row["proposal_id"]
        or proposal.dossier.run_id != row["run_id"]
        or proposal.dossier.record_id != row["record_id"]
        or proposal.dossier_sha256 != row["dossier_sha256"]
        or proposal.proposed_by != row["proposed_by"]
        or proposal.proposed_at != row["proposed_at"]
    ):
        raise ManufacturerReviewSourceMismatch("MANUFACTURER_PROPOSAL_EVIDENCE_CONFLICT")
    _load_artifacts(conn, company_id, proposal.citations)
    return proposal


def read_manufacturer_proposal(storage, company_id: str, proposal_id: str):
    _uuid(proposal_id, "MANUFACTURER_PROPOSAL_ID_INVALID")
    with storage.transaction(company_id, consistent_read=True) as conn:
        return SavedManufacturerProposal(
            proposal=_read_proposal_connection(conn, company_id, proposal_id), created=False
        )


def list_manufacturer_proposals(storage, company_id: str, limit: int = 20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("MANUFACTURER_PROPOSAL_LIMIT_INVALID")
    with storage.transaction(company_id, consistent_read=True) as conn:
        rows = conn.execute(
            select(
                proposals.c.proposal,
                proposals.c.proposal_id,
                proposals.c.run_id,
                proposals.c.record_id,
                proposals.c.dossier_sha256,
                proposals.c.proposal_sha256,
                proposals.c.proposal_canonical,
                proposals.c.proposed_by,
                proposals.c.proposed_at,
                decisions.c.decision,
                decisions.c.decision_id,
                decisions.c.proposal_sha256.label("decision_proposal_sha256"),
                decisions.c.decision_sha256,
                decisions.c.decision_canonical,
                decisions.c.reviewed_by,
                decisions.c.reviewed_at,
                decisions.c.effective_until,
            )
            .select_from(
                proposals.outerjoin(
                    decisions,
                    and_(proposals.c.company_id == decisions.c.company_id,
                         proposals.c.proposal_id == decisions.c.proposal_id),
                )
            )
            .where(proposals.c.company_id == company_id)
            .order_by(proposals.c.proposed_at.desc())
            .limit(limit)
        ).mappings().all()
        artifact_ids = {
            citation.artifact_id
            for row in rows
            for citation in ManufacturerReviewProposal.model_validate(row["proposal"]).citations
        }
        artifact_metadata_rows = conn.execute(
            select(
                artifacts.c.artifact_id,
                artifacts.c.sha256,
                artifacts.c.byte_size,
                artifacts.c.uploaded_by,
                func.octet_length(artifacts.c.content).label("actual_byte_size"),
            ).where(
                and_(
                    artifacts.c.company_id == company_id,
                    artifacts.c.artifact_id.in_(artifact_ids),
                )
            )
        ).mappings().all()
        artifact_metadata = {
            row["artifact_id"]: dict(row) for row in artifact_metadata_rows
        }
    result = []
    for row in rows:
        proposal = ManufacturerReviewProposal.model_validate(row["proposal"])
        proposal_canonical = _canonical_bytes(
            proposal.model_dump(mode="json", exclude={"proposal_sha256"})
        )
        if (
            bytes(row["proposal_canonical"]) != proposal_canonical
            or proposal_digest(proposal) != row["proposal_sha256"]
            or proposal.proposal_id != row["proposal_id"]
            or proposal.dossier.run_id != row["run_id"]
            or proposal.dossier.record_id != row["record_id"]
            or proposal.dossier_sha256 != row["dossier_sha256"]
            or proposal.proposed_by != row["proposed_by"]
            or proposal.proposed_at != row["proposed_at"]
        ):
            raise ManufacturerReviewSourceMismatch("MANUFACTURER_PROPOSAL_EVIDENCE_CONFLICT")
        artifact_rows = {
            citation.artifact_id: artifact_metadata[citation.artifact_id]
            for citation in proposal.citations
            if citation.artifact_id in artifact_metadata
        }
        if len(artifact_rows) != len({item.artifact_id for item in proposal.citations}):
            raise ManufacturerReviewSourceMismatch("MANUFACTURER_ARTIFACT_NOT_FOUND")
        for citation in proposal.citations:
            artifact = artifact_rows[citation.artifact_id]
            if (
                citation.artifact_sha256 != artifact["sha256"]
                or artifact["byte_size"] != artifact["actual_byte_size"]
            ):
                raise ManufacturerReviewSourceMismatch(
                    "MANUFACTURER_ARTIFACT_EVIDENCE_CONFLICT"
                )
        decision = (
            ManufacturerReviewDecision.model_validate(row["decision"]) if row["decision"] else None
        )
        if decision is not None:
            decision_canonical = _canonical_bytes(
                decision.model_dump(mode="json", exclude={"decision_sha256"})
            )
            if (
                bytes(row["decision_canonical"]) != decision_canonical
                or decision_digest(decision) != row["decision_sha256"]
                or decision.decision_id != row["decision_id"]
                or decision.proposal_id != proposal.proposal_id
                or decision.proposal_sha256 != row["decision_proposal_sha256"]
                or decision.proposal_sha256 != proposal.proposal_sha256
                or decision.reviewed_by != row["reviewed_by"]
                or decision.reviewed_at != row["reviewed_at"]
                or decision.effective_until != row["effective_until"]
            ):
                raise ManufacturerReviewSourceMismatch(
                    "MANUFACTURER_DECISION_EVIDENCE_CONFLICT"
                )
            try:
                validate_decision(
                    proposal,
                    decision,
                    artifact_uploaders={
                        artifact["uploaded_by"] for artifact in artifact_rows.values()
                    },
                )
            except ValueError as error:
                raise ManufacturerReviewSourceMismatch(
                    "MANUFACTURER_DECISION_EVIDENCE_CONFLICT"
                ) from error
        result.append(
            ManufacturerProposalSummary(
                proposal_id=proposal.proposal_id,
                run_id=proposal.dossier.run_id,
                record_id=proposal.dossier.record_id,
                legal_name=proposal.claimed_identity.legal_name,
                proposed_by=proposal.proposed_by,
                proposed_at=proposal.proposed_at,
                decision_status=current_review_status(decision) if decision else None,
            )
        )
    return tuple(result)


def read_proposal_artifact(storage, company_id: str, proposal_id: str, artifact_id: str):
    with storage.transaction(company_id, consistent_read=True) as conn:
        proposal = _read_proposal_connection(conn, company_id, proposal_id)
        if artifact_id not in {item.artifact_id for item in proposal.citations}:
            raise ManufacturerReviewNotFound("MANUFACTURER_PROPOSAL_ARTIFACT_NOT_FOUND")
        row = conn.execute(
            select(artifacts).where(
                and_(artifacts.c.company_id == company_id, artifacts.c.artifact_id == artifact_id)
            )
        ).mappings().one()
        content = bytes(row["content"])
        if len(content) != row["byte_size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ManufacturerReviewSourceMismatch("MANUFACTURER_ARTIFACT_EVIDENCE_CONFLICT")
        return ReviewedManufacturerArtifact(metadata=_artifact(dict(row)), content=content)


def _build_decision(proposal, reviewer_id, command_id, at, **values):
    payload: dict[str, object] = {
        "schema_version": "manufacturer-review-decision-v1",
        "decision_id": str(uuid.uuid4()),
        "command_id": command_id,
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": proposal.proposal_sha256,
        "dossier_sha256": proposal.dossier_sha256,
        **values,
        "reviewed_by": reviewer_id,
        "reviewed_at": at,
    }
    normalized = ManufacturerReviewDecision.model_construct(
        **payload, decision_sha256="0" * 64
    ).model_dump(mode="json", exclude={"decision_sha256"})
    payload = normalized
    payload["decision_sha256"] = hashlib.sha256(_canonical_bytes(normalized)).hexdigest()
    return ManufacturerReviewDecision.model_validate(payload)


def decide_manufacturer_review(
    storage, company_id: str, proposal_id: str, identity_status: ReviewStatus,
    role_status: ReviewStatus, official_origin_confirmed: bool,
    identity_fields_confirmed: bool, exact_product_link_confirmed: bool,
    effective_until: datetime | None, rationale: str, citation_indexes: tuple[int, ...],
    reviewer_id: str, command_id: str,
):
    _uuid(command_id, "MANUFACTURER_DECISION_COMMAND_INVALID")
    reviewer_id = reviewer_id.strip()
    if not reviewer_id or len(reviewer_id) > 200:
        raise ValueError("MANUFACTURER_REVIEWER_INVALID")
    with storage.transaction(company_id) as conn:
        _lock(
            conn,
            company_id + "/manufacturer-decision-command/" + command_id,
            company_id + "/manufacturer-decision-proposal/" + proposal_id,
        )
        proposal = _read_proposal_connection(conn, company_id, proposal_id)
        existing = conn.execute(
            select(decisions.c.decision).where(
                and_(decisions.c.company_id == company_id, decisions.c.proposal_id == proposal_id)
            )
        ).scalar_one_or_none()
        by_command = conn.execute(
            select(decisions.c.decision).where(
                and_(decisions.c.company_id == company_id, decisions.c.command_id == command_id)
            )
        ).scalar_one_or_none()
        values = dict(
            identity_status=identity_status, role_status=role_status,
            official_origin_confirmed=official_origin_confirmed,
            identity_fields_confirmed=identity_fields_confirmed,
            exact_product_link_confirmed=exact_product_link_confirmed,
            effective_until=effective_until, rationale=rationale,
            citation_indexes=citation_indexes,
        )
        target = existing or by_command
        if target is not None:
            saved = ManufacturerReviewDecision.model_validate(target)
            comparable = saved.model_dump(exclude={"decision_id", "decision_sha256", "reviewed_at",
                                                   "proposal_sha256", "dossier_sha256",
                                                   "proposal_id", "command_id", "reviewed_by"})
            requested = ManufacturerReviewDecision.model_construct(**values).model_dump()
            if (
                saved.command_id != command_id
                or saved.proposal_id != proposal_id
                or saved.reviewed_by != reviewer_id
                or comparable != requested
            ):
                raise ManufacturerReviewConflict("MANUFACTURER_DECISION_TERMINAL_CONFLICT")
            return SavedManufacturerDecision(
                decision=saved, current_status=current_review_status(saved), created=False
            )
        artifact_rows = _load_artifacts(conn, company_id, proposal.citations)
        decision = _build_decision(
            proposal, reviewer_id, command_id, datetime.now(UTC), **values
        )
        try:
            validate_decision(
                proposal,
                decision,
                artifact_uploaders={row["uploaded_by"] for row in artifact_rows.values()},
            )
        except ValueError as error:
            if str(error) == "MANUFACTURER_REVIEW_NOT_INDEPENDENT":
                raise ManufacturerReviewIndependenceViolation(str(error)) from error
            raise
        canonical = _canonical_bytes(decision.model_dump(mode="json", exclude={"decision_sha256"}))
        conn.execute(
            insert(decisions).values(
                company_id=company_id, decision_id=decision.decision_id,
                command_id=command_id, proposal_id=proposal_id,
                proposal_sha256=decision.proposal_sha256,
                decision_sha256=decision.decision_sha256,
                decision_canonical=canonical, decision=decision.model_dump(mode="json"),
                reviewed_by=reviewer_id, reviewed_at=decision.reviewed_at,
                effective_until=decision.effective_until,
            )
        )
        _audit(conn, company_id, reviewer_id, "manufacturer_review.decided",
               decision.decision_id,
               {"proposal_id": proposal_id, "decision_sha256": decision.decision_sha256,
                "identity_status": decision.identity_status.value,
                "role_status": decision.role_status.value}, decision.reviewed_at)
    return SavedManufacturerDecision(
        decision=decision, current_status=current_review_status(decision), created=True
    )


def read_manufacturer_decision(storage, company_id: str, proposal_id: str):
    with storage.transaction(company_id, consistent_read=True) as conn:
        proposal = _read_proposal_connection(conn, company_id, proposal_id)
        decision = _read_decision_connection(conn, company_id, proposal)
        return SavedManufacturerDecision(
            decision=decision, current_status=current_review_status(decision), created=False
        )


def _read_decision_connection(
    conn: Connection, company_id: str, proposal: ManufacturerReviewProposal
) -> ManufacturerReviewDecision:
    row = conn.execute(
        select(decisions).where(
            and_(
                decisions.c.company_id == company_id,
                decisions.c.proposal_id == proposal.proposal_id,
            )
        )
    ).mappings().one_or_none()
    if row is None:
        raise ManufacturerReviewNotFound("MANUFACTURER_DECISION_NOT_FOUND")
    decision = ManufacturerReviewDecision.model_validate(row["decision"])
    canonical = _canonical_bytes(
        decision.model_dump(mode="json", exclude={"decision_sha256"})
    )
    if (
        bytes(row["decision_canonical"]) != canonical
        or decision_digest(decision) != row["decision_sha256"]
        or decision.decision_id != row["decision_id"]
        or decision.proposal_id != row["proposal_id"]
        or decision.proposal_sha256 != proposal.proposal_sha256
        or decision.reviewed_by != row["reviewed_by"]
        or decision.reviewed_at != row["reviewed_at"]
        or decision.effective_until != row["effective_until"]
    ):
        raise ManufacturerReviewSourceMismatch("MANUFACTURER_DECISION_EVIDENCE_CONFLICT")
    artifact_rows = _load_artifacts(conn, company_id, proposal.citations)
    try:
        validate_decision(
            proposal,
            decision,
            artifact_uploaders={row["uploaded_by"] for row in artifact_rows.values()},
        )
    except ValueError as error:
        raise ManufacturerReviewSourceMismatch(
            "MANUFACTURER_DECISION_EVIDENCE_CONFLICT"
        ) from error
    return decision
