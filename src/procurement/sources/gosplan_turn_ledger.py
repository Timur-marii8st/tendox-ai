"""Tenant audit for one bounded source turn; this module does not grant admission."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC
from uuid import uuid4

from sqlalchemy import exists, func, insert, select, text

from procurement.storage.models import audit_events
from procurement.storage.repository import PostgresStorage

OBJECT = "GOSPLAN_SOURCE_TURN"
STARTED = "GOSPLAN_SOURCE_TURN_STARTED"
FINISHED = "GOSPLAN_SOURCE_TURN_FINISHED"


def start_turn(
    storage: PostgresStorage,
    company: str,
    law: str,
    number: str,
    evidence_sha256: str,
    evidence: dict[str, object],
) -> str | None:
    """Persist a crash-conservative claim; caller must already own source/budget guards."""
    if (
        law not in ("44", "223")
        or not re.fullmatch(r"[0-9]{19}" if law == "44" else r"[0-9]{11}", number)
        or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
    ):
        raise ValueError("TURN_SCOPE_INVALID")
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > 512 * 1024 or hashlib.sha256(encoded).hexdigest() != evidence_sha256:
        raise ValueError("TURN_EVIDENCE_INVALID")
    starts = audit_events.alias("gosplan_started")
    ends = audit_events.alias("gosplan_finished")
    with storage.transaction(company) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        conn.execute(text("SET LOCAL lock_timeout = '2000ms'"))
        conn.scalar(
            select(func.pg_advisory_xact_lock(func.hashtextextended(company + "/gosplan-turn", 0)))
        )
        now = conn.scalar(select(func.now()))
        if now is None or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("TURN_CLOCK_INVALID")
        now = now.astimezone(UTC)
        hour = now.replace(minute=0, second=0, microsecond=0)
        has_unfinished = conn.scalar(
            select(
                exists(
                    select(starts.c.event_id).where(
                        starts.c.company_id == company,
                        starts.c.event_type == STARTED,
                        starts.c.object_type == OBJECT,
                        ~exists(
                            select(ends.c.event_id).where(
                                ends.c.company_id == starts.c.company_id,
                                ends.c.event_type == FINISHED,
                                ends.c.object_type == OBJECT,
                                ends.c.object_id == starts.c.object_id,
                            )
                        ),
                    )
                )
            )
        )
        used = conn.scalar(
            select(
                exists(
                    select(audit_events.c.event_id).where(
                        audit_events.c.company_id == company,
                        audit_events.c.event_type == STARTED,
                        audit_events.c.object_type == OBJECT,
                        audit_events.c.occurred_at >= hour,
                    )
                )
            )
        )
        if has_unfinished or used:
            return None
        turn = uuid4().hex
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=uuid4().hex,
                actor_id="gosplan-recovery",
                event_type=STARTED,
                object_type=OBJECT,
                object_id=turn,
                occurred_at=now,
                basis={
                    "law": law,
                    "number": number,
                    "evidence_sha256": evidence_sha256,
                    "evidence": evidence,
                    "hour": hour.isoformat(),
                    "coverage": "UNKNOWN",
                },
            )
        )
        return turn


def finish_turn(storage: PostgresStorage, company: str, turn: str, outcome: str) -> None:
    """Finish only a known completed operation; UNKNOWN is intentionally left open."""
    if not re.fullmatch(r"[0-9a-f]{32}", turn) or outcome not in {
        "SYNCED",
        "NO_DATA",
        "PREPARING",
        "SERVICE_ERROR",
        "NOT_STARTED",
    }:
        raise ValueError("TURN_FINISH_INVALID")
    with storage.transaction(company) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        conn.execute(text("SET LOCAL lock_timeout = '2000ms'"))
        conn.scalar(
            select(func.pg_advisory_xact_lock(func.hashtextextended(company + "/gosplan-turn", 0)))
        )
        start = conn.scalar(
            select(audit_events.c.event_id).where(
                audit_events.c.company_id == company,
                audit_events.c.event_type == STARTED,
                audit_events.c.object_type == OBJECT,
                audit_events.c.object_id == turn,
            )
        )
        finished = conn.scalar(
            select(audit_events.c.event_id).where(
                audit_events.c.company_id == company,
                audit_events.c.event_type == FINISHED,
                audit_events.c.object_type == OBJECT,
                audit_events.c.object_id == turn,
            )
        )
        if not start or finished:
            raise ValueError("TURN_NOT_ACTIVE")
        now = conn.scalar(select(func.now()))
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=uuid4().hex,
                actor_id="gosplan-recovery",
                event_type=FINISHED,
                object_type=OBJECT,
                object_id=turn,
                occurred_at=now,
                basis={"outcome": outcome, "coverage": "UNKNOWN"},
            )
        )
