"""Bounded read-only comparison of selected known EIS XML versions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Extractor, Provenance
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_evidence_bridge import EisEvidenceBridge, read_eis_evidence_bridge

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


class EisComparisonRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    notices: tuple[NoticeDocumentRef, ...] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _different_purchases(self) -> EisComparisonRequest:
        if len({item.purchase_number for item in self.notices}) != len(self.notices):
            raise ValueError("different purchases are required")
        return self


class EisComparisonRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence: EisEvidenceBridge
    deadline_provenance: Provenance | None
    readiness_status: Literal["BLOCKED", "NEEDS_ANALYSIS"]
    blocking_reasons: tuple[
        Literal[
            "NOTICE_VERSION_STALE",
            "DEADLINE_EXPIRED",
            "PROCEDURE_BLOCKED",
            "NOTICE_VARIANT_REVIEW_REQUIRED",
        ],
        ...,
    ]
    reasons: tuple[str, ...]


class EisComparisonResult(BaseModel):
    """Input order is preserved; no profit or participation rank is invented."""

    model_config = ConfigDict(frozen=True)
    checked_at: datetime
    comparison_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    scope: Literal["SELECTED_KNOWN_XML_VERSIONS"] = "SELECTED_KNOWN_XML_VERSIONS"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    profit_order_status: Literal["UNKNOWN"] = "UNKNOWN"
    rows: tuple[EisComparisonRow, ...] = Field(min_length=2, max_length=3)


def build_eis_comparison(
    request: EisComparisonRequest,
    bridges: tuple[EisEvidenceBridge, ...],
    *,
    now: datetime,
) -> EisComparisonResult:
    """Compare source-bound facts and gaps, preserving mandatory blockers."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if tuple(item.notice for item in bridges) != request.notices:
        raise ValueError("EIS_COMPARISON_REFERENCE_MISMATCH")
    if any(item.checked_at != now for item in bridges):
        raise ValueError("EIS_COMPARISON_TIME_MISMATCH")
    rows = [comparison44_row(bridge) for bridge in bridges]
    return EisComparisonResult(checked_at=now, rows=tuple(rows))


def get_eis_comparison(
    storage: PostgresStorage,
    company_id: str,
    request: EisComparisonRequest,
    *,
    now: datetime | None = None,
) -> EisComparisonResult:
    """Use only saved tenant evidence. No jobs, download, parser or audit writes."""
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    with storage.transaction(company_id, consistent_read=True) as connection:
        bridges = tuple(
            read_eis_evidence_bridge(connection, company_id, ref, now=checked_at)
            for ref in request.notices
        )
    return build_eis_comparison(request, bridges, now=checked_at)


def comparison44_row(bridge: EisEvidenceBridge) -> EisComparisonRow:
    """Preserve source blockers in both law-specific and mixed comparison."""
    blockers: list[
        Literal[
            "NOTICE_VERSION_STALE",
            "DEADLINE_EXPIRED",
            "PROCEDURE_BLOCKED",
            "NOTICE_VARIANT_REVIEW_REQUIRED",
        ]
    ] = []
    if (
        bridge.collection.read_gate is not None
        and "NOTICE_VARIANT_REVIEW_REQUIRED" in bridge.collection.read_gate.blocked_reasons
    ):
        blockers.append("NOTICE_VARIANT_REVIEW_REQUIRED")
    if bridge.collection.version_status == "STALE":
        blockers.append("NOTICE_VERSION_STALE")
    if bridge.application_status == "FAIL":
        blockers.append(
            "DEADLINE_EXPIRED"
            if "DEADLINE_EXPIRED" in bridge.application_reasons
            else "PROCEDURE_BLOCKED"
        )
    reasons = [
        f"Получено {bridge.collection.received_count} из "
        f"{bridge.collection.listed_count} перечисленных файлов.",
        "Полнота комплекта и требования ещё не утверждены.",
        "Для сравнения прибыли нужны полное КП, все затраты и налоговая модель.",
    ]
    if blockers:
        reasons.insert(
            0,
            "Выявлено препятствие для дальнейшего отбора; "
            "проверьте актуальную карточку и источники.",
        )
    return EisComparisonRow(
        evidence=bridge,
        deadline_provenance=(
            Provenance(
                document_id=bridge.notice.notice_xml_sha256,
                locator=f"{bridge.document_type}/notificationInfo/procedureInfo/collectingInfo/endDT",
                extractor=Extractor.API,
            )
            if bridge.deadline is not None
            else None
        ),
        readiness_status="BLOCKED" if blockers else "NEEDS_ANALYSIS",
        blocking_reasons=tuple(blockers),
        reasons=tuple(reasons),
    )
