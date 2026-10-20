"""Exact retained CAPTCHA admission and immutable tenant audit receipts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from procurement.sources.supplier_serp import ENGINES, EngineAttempt, SearchEngine
from procurement.storage.eis_document_store import _audit
from procurement.storage.eis_supplier_search import SupplierSearchRequest
from procurement.storage.eis_supplier_serp import POLICY, SupplierSerpReport, read_supplier_serp
from procurement.storage.models import audit_events
from procurement.storage.repository import PostgresStorage

START_EVENT = "SUPPLIER_CAPTCHA_STARTED"
VERIFIED_EVENT = "SUPPLIER_CAPTCHA_VERIFIED"
END_EVENT = "SUPPLIER_CAPTCHA_ENDED"


def admit_captcha(
    storage: PostgresStorage,
    company: str,
    actor: str,
    request: SupplierSearchRequest,
    run_id: str,
    engine: SearchEngine,
) -> SupplierSerpReport:
    """Only the exact current BLOCKED observation authorizes assistance."""
    report = read_supplier_serp(storage, company, request).report
    if (
        report.run_id != run_id
        or report.policy_version != POLICY
        or report.query is None
        or report.batch is None
        or engine not in ENGINES
        or not any(a.engine == engine and a.status == "BLOCKED" for a in report.batch.attempts)
    ):
        raise ValueError("CAPTCHA_OBSERVATION_STALE")
    now = datetime.now(UTC)
    with storage.transaction(company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"supplier-captcha:{company}"},
        )
        count = conn.scalar(
            select(func.count())
            .select_from(audit_events)
            .where(
                audit_events.c.company_id == company,
                audit_events.c.event_type == START_EVENT,
                audit_events.c.occurred_at > now - timedelta(hours=1),
            )
        )
        last = conn.scalar(
            select(func.max(audit_events.c.occurred_at)).where(
                audit_events.c.company_id == company,
                audit_events.c.event_type == START_EVENT,
            )
        )
        daily = conn.scalar(
            select(func.count())
            .select_from(audit_events)
            .where(
                audit_events.c.company_id == company,
                audit_events.c.event_type == START_EVENT,
                audit_events.c.occurred_at > now - timedelta(days=1),
            )
        )
        if int(daily or 0) >= 24:
            raise ValueError("CAPTCHA_DAILY_LIMIT")
        if int(count or 0) >= 10 or (last is not None and now - last < timedelta(seconds=35)):
            raise ValueError("CAPTCHA_ADMISSION_COOLDOWN")
        _audit(
            conn,
            company,
            actor,
            request.selection.notice,
            START_EVENT,
            {
                "run_id": run_id,
                "engine": engine.value,
                "position_sha256": report.position_sha256,
                "query_sha256": hashlib.sha256(report.query.encode()).hexdigest(),
            },
        )
    return report


def audit_captcha_end(
    storage: PostgresStorage,
    company: str,
    actor: str,
    report: SupplierSerpReport,
    engine: SearchEngine,
    session_id: str,
    outcome: str,
    attempt: EngineAttempt | None = None,
) -> None:
    """Record actual source evidence; screenshots/typed answers never enter audit."""
    if outcome == "VERIFIED" and (
        attempt is None
        or attempt.status not in {"COMPLETED", "EMPTY"}
        or attempt.engine != engine
        or attempt.query != report.query
    ):
        raise ValueError("CAPTCHA_VERIFICATION_INVALID")
    with storage.transaction(company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        _audit(
            conn,
            company,
            actor,
            report.request.selection.notice,
            VERIFIED_EVENT if outcome == "VERIFIED" else END_EVENT,
            {
                "session_id": session_id,
                "run_id": report.run_id,
                "engine": engine.value,
                "outcome": outcome,
                "position_sha256": report.position_sha256,
                "query_sha256": hashlib.sha256((report.query or "").encode()).hexdigest(),
                "dom_sha256": attempt.dom_sha256 if attempt else None,
                "dom_locator": f"manual-dom/{session_id}.html" if attempt else None,
                "source_status": attempt.status if attempt else None,
                "transport_version": "manual-captcha-cdp-v1",
                "supplier_identity": "UNKNOWN",
                "participation": "UNKNOWN",
            },
        )


def recovery_receipts(conn, company: str, now: datetime) -> list[dict]:
    rows = conn.execute(
        select(audit_events.c.basis, audit_events.c.occurred_at)
        .where(
            audit_events.c.company_id == company,
            audit_events.c.event_type == VERIFIED_EVENT,
            audit_events.c.occurred_at >= now - timedelta(minutes=15),
        )
        .order_by(audit_events.c.occurred_at.desc())
        .limit(10)
    ).all()
    return [{**row.basis, "verified_at": row.occurred_at} for row in rows]
