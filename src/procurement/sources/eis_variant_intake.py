"""Bounded automatic projection of already retained and audited conflicting bytes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, get_args

from psycopg import Error as PsycopgError
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_notice_conflicts import EisNoticeConflictDiagnosis
from procurement.sources.eis_rejected_evidence import EisRejectedEvidence
from procurement.storage.eis_notice_projection import (
    EisNoticeProjectionReport,
    project_retained_notice_variants,
)
from procurement.storage.eis_notice_variants import store_notice_variants

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

IntakeStage = Literal["PREREQUISITES", "RETENTION", "DIAGNOSIS", "LEDGER", "PROJECTION", "COMPLETE"]
IntakeReason = Literal[
    "PREREQUISITES_MISSING",
    "DATABASE_FAILED",
    "RETENTION_FAILED",
    "DIAGNOSIS_FAILED",
    "LEDGER_FAILED",
    "PROJECTION_FAILED",
    "NOTICE_VARIANT_LEDGER_INVALID",
    "NOTICE_VARIANT_RETENTION_UNAUDITED",
    "NOTICE_VARIANT_DIAGNOSIS_UNAUDITED",
    "NOTICE_VARIANT_FACT_CONFLICT",
    "NOTICE_VARIANT_RECEIPT_REPLAY_CONFLICT",
    "NOTICE_VARIANT_ORIGIN_REPLAY_CONFLICT",
    "NOTICE_VARIANT_AUDIT_REPLAY_CONFLICT",
    "NOTICE_PROJECTION_GLOBAL_RECEIPT_INCOMPLETE",
    "NOTICE_PROJECTION_HISTORY_LIMIT",
    "NOTICE_PROJECTION_PAYLOAD_LIMIT",
    "NOTICE_PROJECTION_SNAPSHOT_LIMIT",
    "NOTICE_PROJECTION_RECEIPT_CHANGED",
    "NOTICE_PROJECTION_RECEIPT_NOT_FOUND",
    "NOTICE_PROJECTION_DIAGNOSIS_MISMATCH",
    "NOTICE_PROJECTION_INVENTORY_MISMATCH",
    "NOTICE_PROJECTION_REPLAY_CONFLICT",
    "NOTICE_PROJECTION_TRANSPORT_CONFLICT",
    "NOTICE_PROJECTION_TRANSPORT_MISSING",
    "NOTICE_PROJECTION_CANONICAL_REPLAY_CONFLICT",
    "NOTICE_PROJECTION_DECISION_REPLAY_CONFLICT",
    "DIAGNOSIS_BINDING_MISMATCH",
    "VARIANT_INTAKE_REPORT_INVALID",
]


class EisVariantIntakeReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["NOT_ATTEMPTED", "PARTIAL", "FAILED"] = "NOT_ATTEMPTED"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    stage: IntakeStage = "PREREQUISITES"
    reason: IntakeReason | None = "PREREQUISITES_MISSING"
    ledger_receipt_id: str | None = None
    ledger_audit_event_id: str | None = None
    projection: EisNoticeProjectionReport | None = None

    @model_validator(mode="after")
    def _consistent(self) -> EisVariantIntakeReport:
        ids = bool(self.ledger_receipt_id) and bool(self.ledger_audit_event_id)
        if bool(self.ledger_receipt_id) != bool(self.ledger_audit_event_id):
            raise ValueError("VARIANT_INTAKE_REPORT_INVALID")
        if self.status == "NOT_ATTEMPTED":
            valid = (
                self.stage == "PREREQUISITES"
                and self.reason == "PREREQUISITES_MISSING"
                and not ids
                and self.projection is None
            )
        elif self.status == "FAILED":
            valid = (
                self.stage in {"RETENTION", "DIAGNOSIS", "LEDGER", "PROJECTION"}
                and self.reason is not None
                and self.projection is None
                and ids == (self.stage == "PROJECTION")
            )
        else:
            p = self.projection
            valid = (
                self.stage == "COMPLETE"
                and self.reason is None
                and ids
                and p is not None
                and p.receipt_id == self.ledger_receipt_id
                and p.projected_count + p.replayed_count + p.held_count == p.pair_count
                and p.pair_count <= p.occurrence_count
            )
        if not valid:
            raise ValueError("VARIANT_INTAKE_REPORT_INVALID")
        return self

    @property
    def new_versions(self) -> int:
        if (
            self.status == "PARTIAL"
            and self.projection is not None
            and not self.projection.replayed
        ):
            return self.projection.projected_count
        return 0


def variant_intake_failure(
    stage: Literal["RETENTION", "DIAGNOSIS", "LEDGER", "PROJECTION"],
    error: Exception,
    *,
    ledger_receipt_id: str | None = None,
    ledger_audit_event_id: str | None = None,
) -> EisVariantIntakeReport:
    """Classify database failures; never persist exception messages or arbitrary codes."""
    reason: IntakeReason
    if isinstance(error, (SQLAlchemyError, PsycopgError)):
        reason = "DATABASE_FAILED"
    elif isinstance(error, ValueError) and str(error) in get_args(IntakeReason):
        from typing import cast

        reason = cast(IntakeReason, str(error))
    else:
        reason = {
            "RETENTION": "RETENTION_FAILED",
            "DIAGNOSIS": "DIAGNOSIS_FAILED",
            "LEDGER": "LEDGER_FAILED",
            "PROJECTION": "PROJECTION_FAILED",
        }[stage]  # type: ignore[assignment]
    return EisVariantIntakeReport(
        status="FAILED",
        stage=stage,
        reason=reason,
        ledger_receipt_id=ledger_receipt_id,
        ledger_audit_event_id=ledger_audit_event_id,
    )


def intake_notice_variants(
    storage: PostgresStorage,
    company: str,
    evidence: EisRejectedEvidence | None,
    diagnosis: EisNoticeConflictDiagnosis | None,
    archives: tuple[bytes, ...],
    *,
    actor_id: str,
) -> EisVariantIntakeReport:
    """Use exactly the existing archive bytes; ledger validates all prerequisite audits."""
    if evidence is None or evidence.status != "RETAINED" or diagnosis is None:
        return EisVariantIntakeReport()
    try:
        ledger = store_notice_variants(storage, company, evidence, diagnosis, actor_id=actor_id)
    except Exception as error:
        return variant_intake_failure("LEDGER", error)
    try:
        projection = project_retained_notice_variants(
            storage,
            company,
            ledger.receipt_id,
            archives,
            actor_id=actor_id,
        )
        return EisVariantIntakeReport(
            status="PARTIAL",
            stage="COMPLETE",
            reason=None,
            ledger_receipt_id=ledger.receipt_id,
            ledger_audit_event_id=ledger.audit_event_id,
            projection=projection,
        )
    except Exception as error:
        return variant_intake_failure(
            "PROJECTION",
            error,
            ledger_receipt_id=ledger.receipt_id,
            ledger_audit_event_id=ledger.audit_event_id,
        )
