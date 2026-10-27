"""Tenant attempt journal and bounded 223 refresh selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.engine import RowMapping

from procurement.sources.eis_223_archive import SUPPORTED_DOCUMENT_TYPES
from procurement.sources.eis_223_event_sync import event_window_key
from procurement.sources.eis_223_lot_event_sync import lot_event_window_key
from procurement.sources.eis_223_sync import Eis223RefreshTarget, window_key
from procurement.storage.models import (
    audit_events,
    eis_223_event_sync_attempts,
    eis_223_event_windows,
    eis_223_lot_event_sync_attempts,
    eis_223_lot_event_windows,
    eis_223_sync_attempts,
    eis_223_windows,
)

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

Outcome = Literal["SYNCED", "NO_DATA", "PREPARING", "SERVICE_ERROR", "FAILED"]
MSK = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class Eis223EventRefreshTarget:
    day: date
    document_type: Literal["purchaseRejection", "purchaseLotCancellation"] = "purchaseRejection"
    region: str = "50"


RefreshTarget = Eis223RefreshTarget | Eis223EventRefreshTarget


def refresh_window_key(target: RefreshTarget) -> str:
    if (
        isinstance(target, Eis223EventRefreshTarget)
        and target.document_type == "purchaseLotCancellation"
    ):
        return lot_event_window_key(target.day, region=target.region)
    return (
        event_window_key(target.day, region=target.region)
        if isinstance(target, Eis223EventRefreshTarget)
        else window_key(target.day, target.document_type, region=target.region)
    )


def _aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")


def record_attempt(
    storage: PostgresStorage,
    company: str,
    key: str,
    outcome: Outcome,
    *,
    actor_id: str,
    checked_at: datetime,
    response_sha256: str | None,
    reason: str | None = None,
) -> None:
    _aware(checked_at)
    if not actor_id.strip() or not re.fullmatch(
        r"getDocsIP/RI223/(?:0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2}\+03:00/"
        r"(purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice|purchaseNoticeKESMBO|purchaseNoticeZPESMBO|purchaseRejection|purchaseLotCancellation)",
        key,
    ):
        raise ValueError("ATTEMPT_SCOPE_INVALID")
    event = key.endswith("/purchaseRejection")
    windows = eis_223_event_windows if event else eis_223_windows
    attempts = eis_223_event_sync_attempts if event else eis_223_sync_attempts
    if key.endswith("/purchaseLotCancellation"):
        windows, attempts = eis_223_lot_event_windows, eis_223_lot_event_sync_attempts
    with storage.transaction(company) as conn:
        if (
            outcome == "SYNCED"
            and conn.scalar(
                select(func.count())
                .select_from(windows)
                .where(
                    windows.c.company_id == company,
                    windows.c.window_key == key,
                    windows.c.response_sha256 == response_sha256,
                )
            )
            != 1
        ):
            raise ValueError("SYNCED_CHECKPOINT_MISSING")
        attempt_id = str(uuid4())
        conn.execute(
            insert(attempts).values(
                company_id=company,
                attempt_id=attempt_id,
                window_key=key,
                status=outcome,
                response_sha256=response_sha256,
                checkpoint_response_sha256=response_sha256 if outcome == "SYNCED" else None,
                reason=reason,
                checked_at=checked_at,
            )
        )
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=str(uuid4()),
                actor_id=actor_id,
                event_type="EIS_223_SYNC_ATTEMPT",
                object_type="EIS_223_SOURCE_WINDOW",
                object_id=key,
                object_version=None,
                occurred_at=checked_at,
                basis={
                    "attempt_id": attempt_id,
                    "status": outcome,
                    "response_sha256": response_sha256,
                    "reason": reason,
                    "coverage": "UNKNOWN",
                    "freshness": "UNKNOWN",
                },
            )
        )


def due_windows(
    storage: PostgresStorage, company: str, now: datetime, *, include_events: bool = False
) -> tuple[RefreshTarget, ...]:
    _aware(now)
    today = now.astimezone(MSK).date()
    days = (today, today - timedelta(days=1))
    targets: tuple[RefreshTarget, ...] = tuple(
        Eis223RefreshTarget(d, family) for d in days for family in SUPPORTED_DOCUMENT_TYPES
    )

    if include_events:
        targets += tuple(
            Eis223EventRefreshTarget(d, family)
            for d in days
            for family in ("purchaseRejection", "purchaseLotCancellation")
        )

    def key(target: RefreshTarget) -> str:
        return refresh_window_key(target)

    latest: dict[str, RowMapping] = {}
    tables = (
        (eis_223_sync_attempts, eis_223_event_sync_attempts, eis_223_lot_event_sync_attempts)
        if include_events
        else (eis_223_sync_attempts,)
    )
    with storage.transaction(company, consistent_read=True) as conn:
        for table in tables:
            rows = conn.execute(
                select(table)
                .where(
                    table.c.company_id == company,
                    table.c.window_key.in_([key(target) for target in targets]),
                )
                .distinct(table.c.window_key)
                .order_by(
                    table.c.window_key,
                    table.c.checked_at.desc(),
                    table.c.status.in_(("FAILED", "SERVICE_ERROR", "PREPARING")).desc(),
                    table.c.attempt_id.desc(),
                )
            ).mappings()
            for row in rows:
                latest.setdefault(row["window_key"], row)
    due = []
    for target in targets:
        observation = latest.get(key(target))
        if observation is None:
            due.append(target)
            continue
        delay = timedelta(hours=6 if observation["status"] in {"SYNCED", "NO_DATA"} else 1)
        if now - observation["checked_at"] >= delay:
            due.append(target)
    # Today/previous day only; shared oldest-observation order across ten targets.
    due.sort(
        key=lambda target: (
            latest[key(target)]["checked_at"]
            if key(target) in latest
            else datetime.min.replace(tzinfo=MSK)
        )
    )
    return tuple(due)
