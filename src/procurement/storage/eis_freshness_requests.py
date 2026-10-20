"""Immutable tenant requests; status is derived from official window attempts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from itertools import zip_longest
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, insert, select, text

from procurement.storage.models import audit_events, eis_sync_attempts

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.sources.eis_freshness import FreshnessTarget
    from procurement.storage.eis_sync_journal import EisSyncJournal
    from procurement.storage.repository import PostgresStorage

EVENT = "EIS_FRESHNESS_REQUESTED"


class EisRefreshRequestPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str = Field(min_length=1, max_length=120)
    regions: tuple[str, ...] = Field(min_length=1, max_length=3)

    @field_validator("query")
    @classmethod
    def query_valid(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("QUERY_EMPTY")
        return value.strip()

    @field_validator("regions")
    @classmethod
    def regions_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(
            len(code) != 2 or not code.isascii() or not code.isdigit() or not 1 <= int(code) <= 99
            for code in value
        ):
            raise ValueError("REFRESH_REGION_INVALID")
        return tuple(sorted(value))


class EisRefreshRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    company_id: str = Field(min_length=1)
    payload: EisRefreshRequestPayload
    requested_at: datetime
    expires_at: datetime
    window_keys: tuple[str, ...]
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def valid(self) -> EisRefreshRequest:
        for value in (self.requested_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("REQUEST_TIMEZONE_MISSING")
        if self.expires_at - self.requested_at != timedelta(hours=1):
            raise ValueError("REQUEST_EXPIRY_INVALID")
        expected = tuple(
            item.selection.window_key for item in request_targets(self.payload, self.requested_at)
        )
        if self.window_keys != expected:
            raise ValueError("REQUEST_TARGETS_MISMATCH")
        return self


class EisRefreshWindowStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    window_key: str
    outcome: str | None
    attempt_id: str | None
    attempted_at: datetime | None
    response_sha256: str | None
    reason: str | None
    polled_after_request: bool


class EisRefreshStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: EisRefreshRequest
    status: Literal["QUEUED", "PARTIAL", "POLLED", "EXPIRED"]
    checked_at: datetime
    polled_windows: int
    pending_windows: int
    synced_windows: int
    no_data_windows: int
    failed_windows: int
    windows: tuple[EisRefreshWindowStatus, ...]
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"


def request_targets(
    payload: EisRefreshRequestPayload, now: datetime
) -> tuple[FreshnessTarget, ...]:
    from procurement.sources.eis_freshness import EisFreshnessScope

    # The official endpoint accepts region/time, not a product keyword.
    targets = EisFreshnessScope(payload.regions, reconcile_days=1).targets(now)
    return tuple(
        replace(item, expires_at=now + timedelta(hours=1))
        for item in targets
        if item.lane != "EARLIER_HOUR"
    )


def fair_targets(
    foreground: tuple[FreshnessTarget, ...], baseline: tuple[FreshnessTarget, ...], *, limit: int
) -> tuple[FreshnessTarget, ...]:
    if not 1 <= limit <= 1000:
        raise ValueError("FRESHNESS_LIMIT_INVALID")
    selected: list[FreshnessTarget] = []
    seen = set()
    for pair in zip_longest(baseline, foreground):
        for item in pair:
            if item is not None and item.selection.window_key not in seen:
                selected.append(item)
                seen.add(item.selection.window_key)
                if len(selected) == limit:
                    return tuple(selected)
    return tuple(selected)


def _latest(connection: Connection, company_id: str, keys: tuple[str, ...]) -> dict[str, Any]:
    rows = (
        connection.execute(
            select(eis_sync_attempts)
            .where(
                and_(
                    eis_sync_attempts.c.company_id == company_id,
                    eis_sync_attempts.c.window_key.in_(keys),
                )
            )
            .distinct(eis_sync_attempts.c.window_key)
            .order_by(
                eis_sync_attempts.c.window_key,
                eis_sync_attempts.c.attempted_at.desc(),
                eis_sync_attempts.c.attempt_id.desc(),
            )
        )
        .mappings()
        .all()
    )
    return {row["window_key"]: row for row in rows}


def _status(
    request: EisRefreshRequest, attempts: dict[str, Any], now: datetime
) -> EisRefreshStatus:
    windows = []
    for key in request.window_keys:
        row = attempts.get(key)
        if row is not None and not request.requested_at <= row["attempted_at"] <= min(
            now, request.expires_at
        ):
            row = None
        windows.append(
            EisRefreshWindowStatus(
                window_key=key,
                outcome=row["outcome"] if row is not None else None,
                attempt_id=row["attempt_id"] if row is not None else None,
                attempted_at=row["attempted_at"] if row is not None else None,
                response_sha256=row["source_response_sha256"] if row is not None else None,
                reason=row["reason_code"] if row is not None else None,
                polled_after_request=bool(
                    row is not None
                    and row["outcome"] in {"SYNCED", "NO_DATA"}
                    and row["source_response_sha256"] is not None
                ),
            )
        )
    polled = sum(item.polled_after_request for item in windows)
    pending = len(windows) - polled
    status: Literal["QUEUED", "PARTIAL", "POLLED", "EXPIRED"] = "QUEUED"
    if pending == 0:
        status = "POLLED"
    elif now >= request.expires_at:
        status = "EXPIRED"
    elif any(item.attempt_id for item in windows):
        status = "PARTIAL"
    return EisRefreshStatus(
        request=request,
        status=status,
        checked_at=now,
        polled_windows=polled,
        pending_windows=pending,
        synced_windows=sum(item.outcome == "SYNCED" for item in windows),
        no_data_windows=sum(item.outcome == "NO_DATA" for item in windows),
        failed_windows=sum(
            item.outcome in {"FAILED", "SERVICE_ERROR", "PREPARING"} for item in windows
        ),
        windows=tuple(windows),
    )


def _active(
    connection: Connection, company_id: str, now: datetime
) -> tuple[EisRefreshRequest, ...]:
    rows = (
        connection.execute(
            select(audit_events.c.basis)
            .where(
                and_(
                    audit_events.c.company_id == company_id,
                    audit_events.c.event_type == EVENT,
                    audit_events.c.occurred_at > now - timedelta(hours=1),
                    audit_events.c.occurred_at <= now,
                )
            )
            .order_by(audit_events.c.occurred_at, audit_events.c.event_id)
            .limit(21)
        )
        .scalars()
        .all()
    )
    requests = tuple(EisRefreshRequest.model_validate(row) for row in rows)
    if any(item.company_id != company_id for item in requests):
        raise ValueError("REQUEST_TENANT_MISMATCH")
    return requests


def plan_refresh_request(
    storage: PostgresStorage,
    company_id: str,
    payload: EisRefreshRequestPayload,
    *,
    actor_id: str,
    now: datetime,
) -> EisRefreshStatus:
    if not company_id.strip() or not actor_id.strip():
        raise ValueError("REQUEST_ACTOR_INVALID")
    targets = request_targets(payload, now)
    with storage.transaction(company_id) as connection:
        # Serialize admission for this tenant, including concurrent HTTP submissions.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"eis-refresh-request/{company_id}"},
        )
        active = _active(connection, company_id, now)
        for previous in active:
            if previous.payload == payload:
                status = _status(
                    previous, _latest(connection, company_id, previous.window_keys), now
                )
                if status.pending_windows or now - previous.requested_at < timedelta(minutes=5):
                    return status
        if len(active) >= 20:
            raise ValueError("REFRESH_QUEUE_FULL")
        if active and now - max(item.requested_at for item in active) < timedelta(minutes=1):
            raise ValueError("REFRESH_REQUEST_RATE_LIMIT")
        request = EisRefreshRequest(
            request_id=str(uuid4()),
            company_id=company_id,
            payload=payload,
            requested_at=now,
            expires_at=now + timedelta(hours=1),
            window_keys=tuple(item.selection.window_key for item in targets),
        )
        connection.execute(
            insert(audit_events).values(
                event_id=request.request_id,
                company_id=company_id,
                actor_id=actor_id,
                event_type=EVENT,
                object_type="EIS_REFRESH_REQUEST",
                object_id=request.request_id,
                occurred_at=now,
                basis=request.model_dump(mode="json"),
            )
        )
        return _status(request, _latest(connection, company_id, request.window_keys), now)


def get_refresh_status(
    storage: PostgresStorage,
    company_id: str,
    request_id: str,
    *,
    now: datetime,
) -> EisRefreshStatus:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    with storage.transaction(company_id) as connection:
        row = connection.execute(
            select(audit_events.c.basis).where(
                and_(
                    audit_events.c.company_id == company_id,
                    audit_events.c.event_type == EVENT,
                    audit_events.c.object_id == request_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("REFRESH_REQUEST_NOT_FOUND")
        request = EisRefreshRequest.model_validate(row)
        if request.company_id != company_id or request.request_id != request_id:
            raise ValueError("REQUEST_IDENTITY_MISMATCH")
        return _status(request, _latest(connection, company_id, request.window_keys), now)


def pending_refresh_targets(
    journal: EisSyncJournal, *, now: datetime, plan: bool = True
) -> tuple[FreshnessTarget, ...]:
    from procurement.sources.eis_freshness import due_target

    with journal.storage.transaction(journal.company_id, consistent_read=True) as connection:
        requests = _active(connection, journal.company_id, now)
        attempts = _latest(
            connection,
            journal.company_id,
            tuple({key for item in requests for key in item.window_keys}),
        )
    queues = []
    for request in requests:
        pending = []
        for target in request_targets(request.payload, request.requested_at):
            row = attempts.get(target.selection.window_key)
            if row is not None:
                if (
                    request.requested_at <= row["attempted_at"] <= now
                    and row["outcome"] in {"SYNCED", "NO_DATA"}
                    and row["source_response_sha256"] is not None
                ):
                    continue
                if row["outcome"] not in {"SYNCED", "NO_DATA"} and not due_target(
                    target,
                    now=now,
                    attempted_at=row["attempted_at"],
                    outcome=row["outcome"],
                    reason=row["reason_code"],
                ):
                    continue
            pending.append(target)
        queues.append(pending)
    # Round robin among tenant requests, then baseline interleaving in the worker.
    seen = set()
    result = []
    for items in zip_longest(*queues):
        for item in items:
            if item is not None and item.selection.window_key not in seen:
                seen.add(item.selection.window_key)
                result.append(item)
    if plan:
        for offset in range(0, len(result), 31):
            journal.plan(tuple(item.selection for item in result[offset : offset + 31]))
    return tuple(result)
