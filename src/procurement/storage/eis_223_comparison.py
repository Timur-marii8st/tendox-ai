"""Selected 223 source comparison; no downloads, jobs, ranking or admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.sources.eis_223_events import Eis223RejectionState
from procurement.sources.eis_223_lot_event_policy import Eis223LotCancellationState
from procurement.sources.eis_223_policy import deadline223
from procurement.sources.eis_223_schema import Eis223SchemaCheck, schema_quality
from procurement.sources.eis_analysis import ConditionSnippet
from procurement.sources.eis_position_evidence import PositionEvidenceSet, positions223
from procurement.storage.eis_223_documents import _notice, read_document223_status
from procurement.storage.models import eis_223_notice_versions, eis_223_schema_checks

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.storage.eis_223_documents import Document223Status
    from procurement.storage.repository import PostgresStorage


class ComparisonModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Comparison223Request(ComparisonModel):
    notices: tuple[Notice223DocumentRef, ...] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def different_purchases(self) -> Comparison223Request:
        if len({r.purchase_number for r in self.notices}) != len(self.notices):
            raise ValueError("DIFFERENT_PURCHASES_REQUIRED")
        return self


class Comparison223Document(ComparisonModel):
    content_uid: str | None
    filename: str | None
    source_url: str | None
    source_locator: str
    received: bool
    sha256: str | None
    extraction_status: Literal["PASS", "FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]
    snippets: tuple[ConditionSnippet, ...] = Field(max_length=18)
    snippets_total: int
    preview_truncated: bool
    review_status: Literal["UNKNOWN"] = "UNKNOWN"


class Comparison223Row(ComparisonModel):
    cancellation_state: Eis223RejectionState | None = None
    lot_cancellation_state: Eis223LotCancellationState | None = None
    notice: Eis223NoticeSnapshot
    source_window: str
    source_response_sha256: str
    archive_sha256: str
    source_schema_status: Literal["PASS", "FAIL", "UNKNOWN"]
    source_schema_checks: tuple[Eis223SchemaCheck, ...]
    readiness_status: Literal["BLOCKED", "NEEDS_ANALYSIS"]
    blocking_reasons: tuple[str, ...]
    reasons: tuple[str, ...]
    download_status: Literal["INCOMPLETE", "COMPLETE_LISTED_SET", "UNKNOWN_MANIFEST"]
    queue_status: Literal["NOT_REQUESTED", "QUEUED", "COMPLETE", "BLOCKED", "ATTENTION_REQUIRED"]
    documents: tuple[Comparison223Document, ...]
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"
    economics_status: Literal["UNKNOWN"] = "UNKNOWN"
    position_set: PositionEvidenceSet | None = None


class Comparison223Result(ComparisonModel):
    checked_at: datetime
    comparison_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    scope: Literal["SELECTED_KNOWN_XML_VERSIONS"] = "SELECTED_KNOWN_XML_VERSIONS"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    profit_order_status: Literal["UNKNOWN"] = "UNKNOWN"
    rows: tuple[Comparison223Row, ...] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def aware_check(self) -> Comparison223Result:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        return self


def comparison223_documents(status: Document223Status) -> tuple[Comparison223Document, ...]:
    """Bounded preview only; retain exact file/member provenance and truncation flag."""
    result = []
    for item in status.documents:
        analysis = item.analysis
        snippets = analysis.snippets if analysis else ()
        result.append(
            Comparison223Document(
                content_uid=item.reference.content_uid,
                filename=item.reference.filename,
                source_url=item.reference.source_url,
                source_locator=item.reference.source_locator,
                received=item.received,
                sha256=analysis.sha256 if analysis else None,
                extraction_status=analysis.status if analysis else "UNKNOWN",
                reasons=analysis.reasons if analysis else item.reference.reasons,
                snippets=tuple(s.model_copy(update={"text": s.text[:600]}) for s in snippets[:18]),
                snippets_total=len(snippets),
                preview_truncated=len(snippets) > 18
                or any(len(s.text) > 600 for s in snippets[:18]),
            )
        )
    return tuple(result)


def get_comparison223(
    storage: PostgresStorage,
    company: str,
    request: Comparison223Request,
    *,
    now: datetime | None = None,
) -> Comparison223Result:
    at = now or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    rows = []
    # All versions, quality, receipts and gates share one read-only snapshot.
    with storage.transaction(company, consistent_read=True) as conn:
        rows = [read_comparison223_row(conn, company, ref, now=at) for ref in request.notices]
    return Comparison223Result(checked_at=at, rows=tuple(rows))


def read_comparison223_row(
    conn: Connection, company: str, ref: Notice223DocumentRef, *, now: datetime
) -> Comparison223Row:
    """Exact row in a shared read-only snapshot, also used by mixed comparison."""
    notice = _notice(conn, company, ref)
    status = read_document223_status(conn, company, ref, now=now)
    table = eis_223_notice_versions
    source = (
        conn.execute(
            select(table).where(
                table.c.company_id == company,
                table.c.purchase_number == ref.purchase_number,
                table.c.version_number == ref.version_number,
                table.c.xml_sha256 == ref.notice_xml_sha256,
            )
        )
        .mappings()
        .one()
    )
    checks = eis_223_schema_checks
    quality = tuple(
        Eis223SchemaCheck.model_validate(row["report"])
        for row in conn.execute(
            select(checks)
            .where(
                checks.c.company_id == company,
                checks.c.purchase_number == ref.purchase_number,
                checks.c.version_number == ref.version_number,
                checks.c.xml_sha256 == ref.notice_xml_sha256,
            )
            .order_by(checks.c.schema_release, checks.c.validator_version)
        ).mappings()
    )
    if any(
        (q.purchase_number, q.version_number, q.xml_sha256)
        != (ref.purchase_number, ref.version_number, ref.notice_xml_sha256)
        for q in quality
    ):
        raise ValueError("SCHEMA_EVIDENCE_IDENTITY_MISMATCH")
    reasons = [
        "Сопоставлены выбранные сохранённые версии; охват и свежесть всей ЕИС UNKNOWN.",
        "Начальные цены по лотам не являются прибылью; валюта и налоги требуют проверки.",
        "Условия документов — непроверенные фрагменты, полнота ТЗ и право участия UNKNOWN.",
        "Для ранжирования нужны полное действительное КП и base/realistic/conservative.",
    ]
    if deadline223(notice).value is None:
        reasons.append("Часовой пояс срока не подтверждён; действующая подача UNKNOWN.")
    if notice.document_type == "purchaseNotice":
        reasons.append(
            "Общее извещение: вид цены, ограничения по лотам и актуальная стадия требуют проверки."
        )
        if any(
            lot.source_price_kind != "INITIAL_SUM" or lot.initial_sum_rub is None
            for lot in notice.lots
        ):
            reasons.append(
                "Максимальная/формульная цена и неподтверждённая валюта "
                "не используются как начальная цена для расчёта."
            )
    if schema_quality(quality) == "FAIL":
        reasons.append("Ошибка XSD источника требует проверки; это не supplier hard gate.")
    return Comparison223Row(
        cancellation_state=status.cancellation_state,
        lot_cancellation_state=status.lot_cancellation_state,
        position_set=positions223(
            notice,
            (
                (d.reference.content_uid, d.analysis)
                for d in status.documents
                if d.analysis is not None and d.reference.content_uid is not None
            ),
        ),
        notice=notice,
        source_window=source["window_key"],
        source_response_sha256=source["response_sha256"],
        archive_sha256=source["archive_sha256"],
        source_schema_status=schema_quality(quality),
        source_schema_checks=quality,
        readiness_status="BLOCKED" if status.blocked_reasons else "NEEDS_ANALYSIS",
        blocking_reasons=status.blocked_reasons,
        reasons=tuple(reasons),
        download_status=status.download_status,
        queue_status=status.queue_status,
        documents=comparison223_documents(status),
    )
