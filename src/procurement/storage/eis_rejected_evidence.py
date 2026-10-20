"""Tenant audit of a quarantined source set; never a corpus checkpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from procurement.sources.eis_notice_conflicts import EisNoticeConflictDiagnosis
from procurement.sources.eis_rejected_evidence import EisRejectedEvidence
from procurement.storage.models import audit_events

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


def record_rejected_evidence(
    storage: PostgresStorage,
    company_id: str,
    evidence: EisRejectedEvidence,
    *,
    actor_id: str,
) -> str:
    if evidence.company_id != company_id or not actor_id.strip() or evidence.status == "DISABLED":
        raise ValueError("REJECTED_EVIDENCE_AUDIT_INVALID")
    basis = {"evidence": evidence.model_dump(mode="json"), "coverage": "UNKNOWN"}
    identity = evidence.manifest_sha256 or (
        evidence.window_key + "/" + evidence.observed_at.isoformat() + "/" + evidence.status
    )
    event_id = str(uuid5(NAMESPACE_URL, company_id + "/eis-rejected/" + identity))
    with storage.transaction(company_id) as conn:
        conn.execute(
            insert(audit_events)
            .values(
                company_id=company_id,
                event_id=event_id,
                actor_id=actor_id,
                event_type="EIS_REJECTED_WINDOW_EVIDENCE",
                object_type="eis_sync_target",
                object_id=evidence.window_key,
                basis=basis,
                occurred_at=evidence.observed_at,
            )
            .on_conflict_do_nothing(
                index_elements=[audit_events.c.company_id, audit_events.c.event_id]
            )
        )
        existing = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.company_id == company_id, audit_events.c.event_id == event_id
            )
        ).scalar_one()
        if existing != basis:
            raise ValueError("REJECTED_EVIDENCE_AUDIT_REPLAY_CONFLICT")
    return event_id


def record_notice_conflict_diagnosis(
    storage: PostgresStorage,
    company_id: str,
    evidence: EisRejectedEvidence,
    diagnosis: EisNoticeConflictDiagnosis,
    *,
    actor_id: str,
) -> str:
    """Bind offline inventory to an audited full source set, never a checkpoint."""
    evidence = EisRejectedEvidence.model_validate(evidence.model_dump())
    diagnosis = EisNoticeConflictDiagnosis.model_validate(diagnosis.model_dump())
    if (
        evidence.company_id != company_id
        or not actor_id.strip()
        or evidence.status != "RETAINED"
        or diagnosis.archive_sha256s != evidence.archive_sha256s
    ):
        raise ValueError("CONFLICT_DIAGNOSIS_AUDIT_INVALID")
    retained_event = str(
        uuid5(NAMESPACE_URL, company_id + "/eis-rejected/" + str(evidence.manifest_sha256))
    )
    basis = {
        "evidence": evidence.model_dump(mode="json"),
        "diagnosis": diagnosis.model_dump(mode="json"),
        "coverage": "UNKNOWN",
        "canonical_admission": "REJECTED",
    }
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            company_id
            + "/eis-conflict-diagnosis/"
            + str(evidence.manifest_sha256)
            + "/"
            + diagnosis.sha256,
        )
    )
    with storage.transaction(company_id) as conn:
        retained_basis = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.company_id == company_id,
                audit_events.c.event_id == retained_event,
                audit_events.c.event_type == "EIS_REJECTED_WINDOW_EVIDENCE",
                audit_events.c.object_id == evidence.window_key,
            )
        ).scalar_one_or_none()
        if retained_basis != {"evidence": evidence.model_dump(mode="json"), "coverage": "UNKNOWN"}:
            raise ValueError("CONFLICT_DIAGNOSIS_RETENTION_UNAUDITED")
        conn.execute(
            insert(audit_events)
            .values(
                company_id=company_id,
                event_id=event_id,
                actor_id=actor_id,
                event_type="EIS_NOTICE_CONFLICT_DIAGNOSIS",
                object_type="eis_sync_target",
                object_id=evidence.window_key,
                basis=basis,
                occurred_at=evidence.observed_at,
            )
            .on_conflict_do_nothing(
                index_elements=[audit_events.c.company_id, audit_events.c.event_id]
            )
        )
        existing = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.company_id == company_id, audit_events.c.event_id == event_id
            )
        ).scalar_one()
        if existing != basis:
            raise ValueError("CONFLICT_DIAGNOSIS_AUDIT_REPLAY_CONFLICT")
    return event_id
