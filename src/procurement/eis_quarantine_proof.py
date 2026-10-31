"""Verify one quarantined source conflict; never grants a source turn."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import exists, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_variant_intake import EisVariantIntakeReport
from procurement.storage.eis_notice_hold import read_notice_source_hold_connection
from procurement.storage.eis_notice_projection import _json, _receipt_and_diagnosis, _sha
from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_notice_projection_batches,
    eis_notice_projection_decisions,
    eis_notice_variant_origins,
    eis_sync_attempts,
)


class QuarantineProof(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["VERIFIED", "UNKNOWN"]
    company_id: str
    window_key: str
    attempt_id: str
    snapshot: str | None = None
    checked_at: datetime | None = None
    receipt_sha256: str | None = None
    held_count: int = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    source_admission: Literal["NOT_GRANTED"] = "NOT_GRANTED"


def verify_quarantined_conflict(
    conn: Connection, company: str, window_key: str, expected_attempt_id: str
) -> QuarantineProof:
    """Check latest source evidence and current HOLD in caller's tenant read snapshot."""
    unknown = QuarantineProof(
        status="UNKNOWN", company_id=company, window_key=window_key, attempt_id=expected_attempt_id
    )
    try:
        if (
            conn.scalar(text("SHOW transaction_isolation")) != "repeatable read"
            or conn.scalar(text("SHOW transaction_read_only")) != "on"
            or conn.scalar(text("SELECT current_setting('app.company_id', true)")) != company
        ):
            return unknown
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        conn.execute(text("SET LOCAL lock_timeout = '2000ms'"))
        checked_at = datetime.now(UTC)
        snapshot = conn.scalar(text("SELECT txid_current_snapshot()::text"))
        if not snapshot:
            return unknown
        attempt = (
            conn.execute(
                select(eis_sync_attempts)
                .where(
                    eis_sync_attempts.c.company_id == company,
                    eis_sync_attempts.c.window_key == window_key,
                )
                .order_by(
                    eis_sync_attempts.c.attempted_at.desc(), eis_sync_attempts.c.attempt_id.desc()
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if (
            not attempt
            or attempt["attempt_id"] != expected_attempt_id
            or attempt["outcome"] != "FAILED"
            or attempt["reason_code"] != "DUPLICATE_NOTICE_VERSION"
            or not attempt["source_response_sha256"]
            or attempt["attempted_at"] > checked_at
        ):
            return unknown
        source_sha = attempt["source_response_sha256"]
        audit = (
            conn.execute(
                select(audit_events.c.basis).where(
                    audit_events.c.company_id == company,
                    audit_events.c.event_type == "EIS_SYNC_ATTEMPT_RECORDED",
                    audit_events.c.object_type == "eis_sync_target",
                    audit_events.c.object_id == window_key,
                    audit_events.c.basis["attempt_id"].astext == expected_attempt_id,
                )
            )
            .scalars()
            .one_or_none()
        )
        if (
            not isinstance(audit, dict)
            or audit.get("outcome") != "FAILED"
            or (
                audit.get("reason_code") != "DUPLICATE_NOTICE_VERSION"
                or audit.get("source_response_sha256") != source_sha
            )
        ):
            return unknown
        raw = audit.get("variant_intake") or (audit.get("observation") or {}).get("variant_intake")
        variant = EisVariantIntakeReport.model_validate(raw)
        projection = variant.projection
        if (
            variant.status != "PARTIAL"
            or variant.stage != "COMPLETE"
            or projection is None
            or projection.held_count < 1
            or projection.replayed
        ):
            return unknown
        if conn.scalar(
            select(
                exists(
                    select(eis_feed_windows.c.window_key).where(
                        eis_feed_windows.c.company_id == company,
                        eis_feed_windows.c.window_key == window_key,
                        eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
                    )
                )
            )
        ):
            return unknown
        batch = (
            conn.execute(
                select(eis_notice_projection_batches).where(
                    eis_notice_projection_batches.c.company_id == company,
                    eis_notice_projection_batches.c.batch_id == projection.batch_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            not batch
            or batch["window_key"] != window_key
            or batch["response_sha256"] != source_sha
            or batch["receipt_id"] != projection.receipt_id
            or projection.receipt_id != variant.ledger_receipt_id
            or batch["audit_event_id"] != projection.audit_event_id
            or any(
                batch[field] != getattr(projection, field)
                for field in (
                    "occurrence_count",
                    "pair_count",
                    "projected_count",
                    "replayed_count",
                    "held_count",
                )
            )
        ):
            return unknown
        receipt, diagnosis = _receipt_and_diagnosis(conn, company, projection.receipt_id)
        if (
            receipt.window_key != window_key
            or receipt.response_sha256 != source_sha
            or receipt.ledger_audit_event_id != variant.ledger_audit_event_id
            or receipt.canonical_admission != "NOT_ENABLED"
            or diagnosis.occurrence_count != projection.occurrence_count
            or list(receipt.archive_sha256s) != batch["archive_sha256s"]
        ):
            return unknown
        count = conn.scalar(
            select(func.count())
            .select_from(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company,
                eis_notice_variant_origins.c.receipt_id == projection.receipt_id,
            )
        )
        decisions = (
            conn.execute(
                select(eis_notice_projection_decisions)
                .where(
                    eis_notice_projection_decisions.c.company_id == company,
                    eis_notice_projection_decisions.c.batch_id == projection.batch_id,
                )
                .order_by(
                    eis_notice_projection_decisions.c.purchase_number,
                    eis_notice_projection_decisions.c.version_number,
                )
            )
            .mappings()
            .all()
        )
        basis = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.company_id == company,
                audit_events.c.event_id == batch["audit_event_id"],
                audit_events.c.event_type == "EIS_NOTICE_PROJECTION_RECORDED",
                audit_events.c.object_type == "eis_notice_projection_batch",
                audit_events.c.object_id == batch["batch_id"],
            )
        ).scalar_one_or_none()
        if (
            count != projection.occurrence_count
            or len(decisions) != projection.pair_count
            or not isinstance(basis, dict)
            or basis.get("batch_id") != batch["batch_id"]
            or basis.get("payload_sha256") != batch["payload_sha256"]
            or _sha({k: v for k, v in basis.items() if k != "payload_sha256"})
            != batch["payload_sha256"]
            or basis.get("batch")
            != _json({k: v for k, v in batch.items() if k != "payload_sha256"})
            or basis.get("decisions") != [dict(row) for row in decisions]
            or basis.get("receipt_sha256") != receipt.receipt_sha256
        ):
            return unknown
        if any(
            sum(row["status"] == status for row in decisions) != expected
            for status, expected in (
                ("PROJECTED", projection.projected_count),
                ("REPLAYED", projection.replayed_count),
                ("HOLD", projection.held_count),
            )
        ):
            return unknown
        for row in decisions:
            if row["status"] == "HOLD":
                hold = read_notice_source_hold_connection(
                    conn, company, row["purchase_number"], row["version_number"]
                )
                if hold.status != "HOLD" or hold.resolution != "UNKNOWN":
                    return unknown
        return QuarantineProof(
            status="VERIFIED",
            company_id=company,
            window_key=window_key,
            attempt_id=expected_attempt_id,
            snapshot=snapshot,
            checked_at=checked_at,
            receipt_sha256=receipt.receipt_sha256,
            held_count=projection.held_count,
        )
    except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError, ValidationError):
        return unknown
