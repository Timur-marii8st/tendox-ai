"""Bounded, resumable-by-operator discovery; never asserts complete coverage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from procurement.sources.gosplan_discovery import MAX_OFFSET, GosplanError, fetch_page
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope


@dataclass(frozen=True)
class BatchResult:
    status: str
    reason: str
    pages_recorded: int
    next_offset: int | None
    observation_ids: tuple[str, ...]
    coverage: str = "UNKNOWN"


def collect_batch(
    client: httpx.Client, key: str, queue: GosplanQueue, scope: Scope, *, max_pages: int
) -> BatchResult:
    """Commit each page before advancing; offset is a hint, not a durable watermark."""
    if not 1 <= max_pages <= 10:
        raise ValueError("PAGE_BUDGET_INVALID")
    offset = scope.offset
    ids: list[str] = []
    for _ in range(max_pages):
        if offset > MAX_OFFSET:
            return BatchResult("UNKNOWN", "OFFSET_LIMIT", len(ids), None, tuple(ids))
        page_scope = Scope(scope.company, scope.law, scope.start, scope.end, offset, scope.limit)
        observed = datetime.now(UTC)
        try:
            page = fetch_page(
                client,
                key,
                scope.law,
                start=scope.start,
                end=scope.end,
                offset=offset,
                limit=scope.limit,
                now=observed,
            )
            observation_id = queue.record(page_scope, page, observed)
        except (GosplanError, QueueError, sqlite3.Error, OSError) as exc:
            reason = (
                str(exc) if isinstance(exc, (GosplanError, QueueError)) else "STORE_UNAVAILABLE"
            )
            return BatchResult("UNKNOWN", reason, len(ids), offset, tuple(ids))
        ids.append(observation_id)
        if not page.may_have_more:
            return BatchResult("STOPPED", "SHORT_PAGE", len(ids), None, tuple(ids))
        if offset + scope.limit > MAX_OFFSET:
            return BatchResult("UNKNOWN", "OFFSET_LIMIT", len(ids), None, tuple(ids))
        offset += scope.limit
    return BatchResult("STOPPED", "PAGE_BUDGET", len(ids), offset, tuple(ids))
