"""Atomic cancellation evidence variants and bounded reads in a tenant snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, insert, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping

from procurement.sources.eis_223_event_sync import (
    Eis223EventReadyWindow,
    preflight_purchase_rejection_window,
)
from procurement.sources.eis_223_events import (
    Eis223EventSchemaCheck,
    Eis223PurchaseRejection,
    Eis223RejectionState,
    resolve_purchase_rejection_state,
)
from procurement.sources.eis_223_schema import SCHEMAS, VALIDATOR
from procurement.storage.models import (
    audit_events,
    eis_223_blobs,
    eis_223_event_archive_sources,
    eis_223_event_schema_checks,
    eis_223_event_windows,
    eis_223_events,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.storage.repository import PostgresStorage


class Event223IngestReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    window_key: str
    record_count: int
    new_events: int
    guid_conflicts: int
    replayed: bool


def ingest_event223_window(
    storage: PostgresStorage,
    company: str,
    window: Eis223EventReadyWindow,
    *,
    actor_id: str,
    now: datetime | None = None,
) -> Event223IngestReport:
    inspections = preflight_purchase_rejection_window(company, window)
    at = now or datetime.now(UTC)
    if not actor_id.strip() or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("ACTOR_OR_TIME_INVALID")
    manifest = hashlib.sha256(
        json.dumps(
            [
                {"sha256": a.archive_sha256, "url": url, "records": len(a.records)}
                for a, url in zip(inspections, window.archive_urls, strict=True)
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    count = sum(len(a.records) for a in inspections)
    with storage.transaction(company) as conn:
        # Shares the notice/document import lock: cancellation cannot race the
        # final receipt commit while that consumer rechecks source state.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "eis223:" + company},
        )
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": company}
        )
        windows = eis_223_event_windows
        existing = (
            conn.execute(
                select(windows).where(
                    windows.c.company_id == company,
                    windows.c.window_key == window.window_key,
                    windows.c.response_sha256 == window.response_sha256,
                )
            )
            .mappings()
            .first()
        )
        if existing:
            if (
                existing["manifest_sha256"],
                existing["record_count"],
                existing["prepared_sha256"],
            ) != (manifest, count, window.prepared_sha256):
                raise ValueError("WINDOW_REPLAY_CONFLICT")
            return Event223IngestReport(
                window_key=window.window_key,
                record_count=count,
                new_events=0,
                guid_conflicts=0,
                replayed=True,
            )
        conn.execute(
            insert(windows).values(
                company_id=company,
                window_key=window.window_key,
                response_sha256=window.response_sha256,
                prepared_sha256=window.prepared_sha256,
                manifest_sha256=manifest,
                archive_count=len(inspections),
                record_count=count,
                ingested_at=at,
            )
        )
        new = 0
        seen_guids: set[str] = set()
        for inspection, content, url in zip(
            inspections, window.archives, window.archive_urls, strict=True
        ):
            conn.execute(
                pg_insert(eis_223_blobs)
                .values(
                    company_id=company, archive_sha256=inspection.archive_sha256, content=content
                )
                .on_conflict_do_nothing()
            )
            conn.execute(
                insert(eis_223_event_archive_sources).values(
                    company_id=company,
                    window_key=window.window_key,
                    response_sha256=window.response_sha256,
                    archive_sha256=inspection.archive_sha256,
                    source_url=url,
                )
            )
            for event in inspection.records:
                guid = event.event_guid.value
                if guid is None:
                    raise ValueError("EVENT_GUID_INVALID")
                seen_guids.add(guid)
                added = conn.execute(
                    pg_insert(eis_223_events)
                    .values(
                        company_id=company,
                        event_guid=guid,
                        purchase_number=event.purchase_number,
                        xml_sha256=event.xml_sha256,
                        window_key=window.window_key,
                        response_sha256=window.response_sha256,
                        archive_sha256=inspection.archive_sha256,
                        snapshot=event.model_dump(mode="json"),
                        ingested_at=at,
                    )
                    .on_conflict_do_nothing()
                    .returning(eis_223_events.c.xml_sha256)
                ).first()
                new += added is not None
        t = eis_223_events
        conflicts = len(
            conn.execute(
                select(t.c.event_guid)
                .where(t.c.company_id == company, t.c.event_guid.in_(seen_guids))
                .group_by(t.c.event_guid)
                .having(func.count() > 1)
            ).all()
        )
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=str(uuid4()),
                actor_id=actor_id,
                event_type="EIS_223_EVENT_WINDOW_INGESTED",
                object_type="EIS_223_EVENT_WINDOW",
                object_id=window.window_key,
                object_version=None,
                occurred_at=at,
                basis={
                    "response_sha256": window.response_sha256,
                    "record_count": count,
                    "new_events": new,
                    "guid_conflicts": conflicts,
                    "coverage": "UNKNOWN",
                },
            )
        )
    return Event223IngestReport(
        window_key=window.window_key,
        record_count=count,
        new_events=new,
        guid_conflicts=conflicts,
        replayed=False,
    )


def read_event223_states(
    conn: Connection, company: str, numbers: tuple[str, ...], *, now: datetime
) -> dict[str, Eis223RejectionState]:
    """Two bounded event queries, one quality query, no transitive graph expansion.

    Overflow holds the entire requested batch instead of materializing a partial
    set that could hide a conflicting variant. Search calls this before ranking.
    """
    if len(numbers) > 200 or len(set(numbers)) != len(numbers):
        raise ValueError("EVENT_BATCH_LIMIT")
    if not numbers:
        return {}
    t = eis_223_events
    # 100 variants per number, also a fixed global memory cap for search batches.
    cap = 2000
    direct = (
        conn.execute(
            select(t.c.event_guid)
            .where(t.c.company_id == company, t.c.purchase_number.in_(numbers))
            .distinct()
            .order_by(t.c.event_guid)
            .limit(cap + 1)
        )
        .scalars()
        .all()
    )
    overflow = len(direct) > cap
    rows = (
        []
        if overflow or not direct
        else conn.execute(
            select(t)
            .where(t.c.company_id == company, t.c.event_guid.in_(direct))
            .order_by(t.c.event_guid, t.c.xml_sha256)
            .limit(cap + 1)
        )
        .mappings()
        .all()
    )
    overflow = overflow or len(rows) > cap
    if overflow:
        return {
            n: resolve_purchase_rejection_state(
                n, (), (), now=now, reason_codes=("EVENT_EVIDENCE_LIMIT",)
            )
            for n in numbers
        }
    events = []
    for row in rows:
        event = Eis223PurchaseRejection.model_validate(row["snapshot"])
        if (event.purchase_number, event.event_guid.value, event.xml_sha256) != (
            row["purchase_number"],
            row["event_guid"],
            row["xml_sha256"],
        ):
            raise ValueError("EVENT_SOURCE_IDENTITY_MISMATCH")
        events.append(event)
    checks = eis_223_event_schema_checks
    quality = (
        ()
        if not events
        else tuple(
            Eis223EventSchemaCheck.model_validate(row["report"])
            for row in conn.execute(
                select(checks).where(
                    checks.c.company_id == company,
                    tuple_(checks.c.event_guid, checks.c.xml_sha256).in_(
                        [(e.event_guid.value, e.xml_sha256) for e in events]
                    ),
                    checks.c.validator_version == VALIDATOR,
                )
            ).mappings()
        )
    )
    # Exact identity is revalidated by the resolver; no quality from a notice.
    result = {}
    for number in numbers:
        guids = {e.event_guid.value for e in events if e.purchase_number == number}
        selected = tuple(e for e in events if e.event_guid.value in guids)
        selected_checks = tuple(c for c in quality if c.event_guid in guids)
        result[number] = resolve_purchase_rejection_state(
            number, selected, selected_checks, now=now
        )
    return result


def record_event_schema_check(
    storage: PostgresStorage, company: str, check: Eis223EventSchemaCheck, *, actor_id: str
) -> bool:
    if not actor_id.strip():
        raise ValueError("ACTOR_MISSING")
    check = Eis223EventSchemaCheck.model_validate(check.model_dump())
    table = eis_223_event_schema_checks
    report = check.model_dump(mode="json")
    values = {
        k: getattr(check, k)
        for k in (
            "purchase_number",
            "event_guid",
            "xml_sha256",
            "schema_release",
            "tree_sha256",
            "validator_version",
            "status",
            "checked_at",
        )
    }
    with storage.transaction(company) as conn:
        added = conn.execute(
            pg_insert(table)
            .values(company_id=company, report=report, **values)
            .on_conflict_do_nothing()
            .returning(table.c.xml_sha256)
        ).first()
        if added is None:
            old = conn.scalar(
                select(table.c.report).where(
                    table.c.company_id == company,
                    *[
                        getattr(table.c, k) == values[k]
                        for k in (
                            "purchase_number",
                            "event_guid",
                            "xml_sha256",
                            "schema_release",
                            "tree_sha256",
                            "validator_version",
                        )
                    ],
                )
            )
            if old is None or {k: v for k, v in old.items() if k != "checked_at"} != {
                k: v for k, v in report.items() if k != "checked_at"
            }:
                raise ValueError("SCHEMA_CHECK_CONFLICT")
            return False
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=str(uuid4()),
                actor_id=actor_id,
                event_type="EIS_223_EVENT_SCHEMA_CHECKED",
                object_type="EIS_223_EVENT",
                object_id=check.event_guid,
                object_version=None,
                occurred_at=check.checked_at,
                basis={
                    "xml_sha256": check.xml_sha256,
                    "schema_release": check.schema_release,
                    "status": check.status,
                    "current_procedure_status": "UNKNOWN",
                },
            )
        )
    return True


def pending_event_quality(storage: PostgresStorage, company: str) -> tuple[RowMapping, ...]:
    """At most two immutable variants, including conflicting historical evidence."""
    events, checks, blobs = eis_223_events, eis_223_event_schema_checks, eis_223_blobs
    missing = [
        ~select(checks.c.xml_sha256)
        .where(
            checks.c.company_id == company,
            checks.c.event_guid == events.c.event_guid,
            checks.c.xml_sha256 == events.c.xml_sha256,
            checks.c.schema_release == release,
            checks.c.tree_sha256 == policy[2],
            checks.c.validator_version == VALIDATOR,
        )
        .exists()
        for release, policy in SCHEMAS.items()
    ]
    query = (
        select(events, blobs.c.content)
        .select_from(
            events.join(
                blobs,
                and_(
                    blobs.c.company_id == events.c.company_id,
                    blobs.c.archive_sha256 == events.c.archive_sha256,
                ),
            )
        )
        .where(events.c.company_id == company, or_(*missing))
        .order_by(events.c.ingested_at, events.c.event_guid, events.c.xml_sha256)
        .limit(2)
    )
    with storage.transaction(company, consistent_read=True) as conn:
        return tuple(conn.execute(query).mappings().all())
