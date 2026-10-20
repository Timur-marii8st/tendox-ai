"""Bounded parameterized notice/event refresh under the shared server lease."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, text

from procurement.sources.eis_223_archive import SUPPORTED_DOCUMENT_TYPES
from procurement.sources.eis_223_catalog_fetch import fetch_region_selector
from procurement.sources.eis_223_event_quality_worker import process_event_quality_batch
from procurement.sources.eis_223_event_sync import fetch_purchase_rejection_day
from procurement.sources.eis_223_lot_event_quality_worker import process_lot_event_quality_batch
from procurement.sources.eis_223_lot_event_sync import fetch_purchase_lot_cancellation_day
from procurement.sources.eis_223_quality_worker import process_quality_batch
from procurement.sources.eis_223_sync import fetch_notice223_day
from procurement.sources.eis_corpus import priority_requested
from procurement.sources.eis_feed_sync import EisFeedTransport, eis_browser_transport
from procurement.storage.eis_223_catalog_checks import catalog_refresh_due, record_catalog_check
from procurement.storage.eis_223_events import ingest_event223_window
from procurement.storage.eis_223_index import ingest_notice223_window
from procurement.storage.eis_223_lot_events import ingest_lot_event223_window
from procurement.storage.eis_223_regions import (
    _accepted_catalog,
    ensure_region_wave,
    read_region_coverage,
    regional_due_windows,
)
from procurement.storage.eis_223_sync import (
    MSK,
    Eis223EventRefreshTarget,
    Outcome,
    due_windows,
    record_attempt,
    refresh_window_key,
)
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
ACTOR = "223-refresh"
MAX_WINDOWS = 2
MAX_SECONDS = 180
REGIONAL_MAX_WINDOWS = 32
REGIONAL_MAX_SECONDS = 600
WINDOW_TIMEOUT = 180
MAX_DB_BYTES = 100 * 1024**3
MIN_FREE_BYTES = 40 * 1024**3
PRIORITY_REQUEST = Path("/var/lib/eis-browser/eis-priority.request")
SAFE_REASONS = frozenset(
    {
        "SOURCE_TRANSPORT_FAILED",
        "SOURCE_RESPONSE_REJECTED",
        "SOURCE_CONTRACT_CHANGED",
        "INITIAL_REQUEST_MISMATCH",
        "PREPARED_REQUEST_MISMATCH",
        "ARCHIVE_CONTENT_REJECTED",
        "SOURCE_BINDING_INVALID",
        "ARCHIVE_SET_MISMATCH",
        "ARCHIVE_COUNT_LIMIT",
        "WINDOW_BYTES_LIMIT",
        "WINDOW_EXPANSION_LIMIT",
        "WINDOW_EXPANDED_LIMIT",
        "WINDOW_MEMBER_LIMIT",
        "ARCHIVE_RESOURCE_LIMIT",
        "ARCHIVE_INVALID",
        "NOTICE_VERSION_CONFLICT",
        "XML_TOKEN_REFLECTION_REJECTED",
        "ARCHIVE_BYTES_LIMIT",
        "ARCHIVE_EXPANSION_LIMIT",
    }
)


class CountedTransport:
    def __init__(self, transport: EisFeedTransport):
        self.transport = transport
        self.posts = 0
        self.downloads = 0

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        self.posts += 1
        return await self.transport.post(xml)

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        self.downloads += 1
        return await self.transport.download(url, token)


async def refresh_catalog(storage: PostgresStorage) -> dict[str, object]:
    if not catalog_refresh_due(storage, COMPANY, datetime.now(UTC)):
        return {"status": "NOT_DUE", "source_requests": 0}
    fetched = await fetch_region_selector()
    check = record_catalog_check(
        storage,
        COMPANY,
        fetched.body or None,
        checked_at=fetched.observed_at,
        actor_id=ACTOR,
        reason=fetched.reason,
        http_status=fetched.http_status,
    )
    return {**check.model_dump(mode="json"), "source_requests": fetched.source_requests}


def probe() -> dict[str, object]:
    """Read-only demand check: an idle cron must not preempt the corpus worker."""
    engine = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=5000"},
    )
    try:
        storage = PostgresStorage(engine)
        now = datetime.now(UTC)
        coverage = read_region_coverage(storage, COMPANY, now=now)
        catalog_due = catalog_refresh_due(storage, COMPANY, now)
        # A new calendar wave is materialized only by run() under the import lease.
        new_wave_due = (
            coverage.catalog_sha256 is not None or accepted_catalog_present(storage)
        ) and (
            coverage.wave_id is None
            or (
                coverage.first_sweep_finished
                and coverage.end_day is not None
                and coverage.end_day < now.astimezone(MSK).date()
            )
        )
        due = regional_due_windows(storage, COMPANY, now, limit=2)
        ready = catalog_due or new_wave_due or bool(due)
        return {
            "status": "READY" if ready else "IDLE",
            "company_id": COMPANY,
            "checked_at": now.isoformat(),
            "catalog_due": catalog_due,
            "new_wave_due": new_wave_due,
            "due_windows": len(due),
            "source_requests": 0,
            "coverage": "UNKNOWN",
        }
    finally:
        engine.dispose()


def accepted_catalog_present(storage: PostgresStorage) -> bool:
    # Coverage before the first wave deliberately has no catalog fields.
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        return _accepted_catalog(conn, COMPANY) is not None


def optional_quality(storage: PostgresStorage, *, regional: bool) -> dict[str, object]:
    if regional and priority_requested(PRIORITY_REQUEST, now=datetime.now(UTC)):
        return {"reason": "DEFERRED_FOR_PRIORITY", "source_requests": 0}
    return quality_report(storage)


def quality_report(storage: PostgresStorage) -> dict[str, object]:
    try:
        # Alternate event families between cron slots; same two-event offline budget.
        event_worker = (
            process_event_quality_batch
            if datetime.now(UTC).minute < 30
            else process_lot_event_quality_batch
        )
        event = event_worker(storage, COMPANY, actor_id=ACTOR)
        notice = process_quality_batch(storage, COMPANY, actor_id=ACTOR).model_dump(mode="json")
        return {"events": event, "notices": notice, "source_requests": 0}
    except Exception:
        # Quality failures never rewrite the independently recorded source outcome.
        return {"reason": "QUALITY_UNAVAILABLE", "source_requests": 0, "eligibility": "UNKNOWN"}


async def run() -> dict[str, object]:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    storage = PostgresStorage(engine)
    started = perf_counter()
    regional = os.environ.get("EIS_223_REGIONAL_ENABLED") == "1"
    max_windows = REGIONAL_MAX_WINDOWS if regional else MAX_WINDOWS
    max_seconds = REGIONAL_MAX_SECONDS if regional else MAX_SECONDS
    report: dict[str, object] = {
        "company_id": COMPANY,
        "region_scope": "OFFICIAL_CATALOG" if regional else "PILOT_50",
        "document_types": list(SUPPORTED_DOCUMENT_TYPES),
        "event_types": ["purchaseRejection", "purchaseLotCancellation"],
        "coverage": "UNKNOWN",
        "freshness": "UNKNOWN",
        "attempted": 0,
    }
    try:
        with engine.connect() as conn:
            size = conn.scalar(text("SELECT pg_database_size(current_database())"))
        if size is None or size >= MAX_DB_BYTES:
            return {**report, "reason": "DATABASE_BUDGET_REACHED"}
        if shutil.disk_usage("/var/lib/eis-browser").free < MIN_FREE_BYTES:
            return {**report, "reason": "DISK_RESERVE_REACHED"}
        if regional:
            # The public GET shares the lease and start/resource budget with this batch.
            # Rejected membership leaves the last accepted catalog usable.
            report["catalog_check"] = await refresh_catalog(storage)
            wave = ensure_region_wave(storage, COMPANY, datetime.now(UTC), actor_id=ACTOR)
            if wave is None:
                return {**report, "reason": "OFFICIAL_REGION_CATALOG_MISSING"}
            due = regional_due_windows(storage, COMPANY, datetime.now(UTC), limit=max_windows)
            report["wave_id"] = wave
            report["regional_coverage"] = read_region_coverage(
                storage, COMPANY, now=datetime.now(UTC)
            ).model_dump(mode="json")
        else:
            due = due_windows(storage, COMPANY, datetime.now(UTC), include_events=True)
        targets = due[:max_windows]
        report.update(
            selected_windows=len(targets),
            max_windows=max_windows,
            start_budget_seconds=max_seconds,
        )
        if not regional:
            report.update(due_windows=len(due), deferred_windows=max(0, len(due) - max_windows))
        if not targets:
            return {
                **report,
                "reason": "NOT_DUE",
                "quality": optional_quality(storage, regional=regional),
            }
        outcomes = []
        async with eis_browser_transport() as underlying_transport:
            transport = CountedTransport(underlying_transport)
            for target in targets:
                # Give the acquired lane one atomic window, then hand the shared
                # lease to announced foreground work. No source window is cancelled.
                if (
                    regional
                    and outcomes
                    and priority_requested(PRIORITY_REQUEST, now=datetime.now(UTC))
                ):
                    report["stop_reason"] = "PRIORITY_REFRESH_REQUESTED"
                    break
                remaining = max_seconds - (perf_counter() - started)
                if remaining < 1:
                    break
                if regional:
                    with engine.connect() as conn:
                        size = conn.scalar(text("SELECT pg_database_size(current_database())"))
                    if size is None or size >= MAX_DB_BYTES:
                        report["stop_reason"] = "DATABASE_BUDGET_REACHED"
                        break
                    if shutil.disk_usage("/var/lib/eis-browser").free < MIN_FREE_BYTES:
                        report["stop_reason"] = "DISK_RESERVE_REACHED"
                        break
                key = refresh_window_key(target)
                response_sha = None
                reason = None
                new_versions = 0
                new_events = 0
                outcome: Outcome
                try:
                    request = (
                        (
                            fetch_purchase_lot_cancellation_day
                            if target.document_type == "purchaseLotCancellation"
                            else fetch_purchase_rejection_day
                        )(
                            COMPANY,
                            target.day,
                            os.environ["EIS_GETDOCS_IP_TOKEN"],
                            transport,
                            region=target.region,
                        )
                        if isinstance(target, Eis223EventRefreshTarget)
                        else fetch_notice223_day(
                            COMPANY,
                            target.day,
                            os.environ["EIS_GETDOCS_IP_TOKEN"],
                            transport,
                            region=target.region,
                            document_type=target.document_type,
                        )
                    )
                    # A started bounded full-set intake gets its own timeout; crossing
                    # the batch start deadline does not cancel a READY set halfway.
                    observed = await asyncio.wait_for(
                        request, timeout=WINDOW_TIMEOUT if regional else remaining
                    )
                    outcome = observed.status
                    response_sha = observed.response_sha256
                    if outcome == "SYNCED":
                        if observed.window is None:
                            raise ValueError("SOURCE_WINDOW_MISSING")
                        if isinstance(target, Eis223EventRefreshTarget):
                            event_ingest = (
                                ingest_lot_event223_window
                                if target.document_type == "purchaseLotCancellation"
                                else ingest_event223_window
                            )
                            result_event = event_ingest(
                                storage, COMPANY, observed.window, actor_id=ACTOR
                            )
                            new_events = result_event.new_events
                        else:
                            result = ingest_notice223_window(
                                storage, COMPANY, observed.window, actor_id=ACTOR
                            )
                            new_versions = result.new_versions
                except TimeoutError:
                    outcome = "FAILED"
                    reason = "RUN_TIME_BUDGET_REACHED"
                except Exception as error:
                    # Never log raw transport/SQL details or outgoing SOAP/token.
                    outcome = "FAILED"
                    value = str(error)
                    reason = value if value in SAFE_REASONS else "SYNC_FAILED"
                    failure_sha = getattr(error, "source_response_sha256", None)
                    if isinstance(failure_sha, str) and re.fullmatch(r"[0-9a-f]{64}", failure_sha):
                        response_sha = failure_sha
                record_attempt(
                    storage,
                    COMPANY,
                    key,
                    outcome,
                    actor_id=ACTOR,
                    checked_at=datetime.now(UTC),
                    response_sha256=response_sha,
                    reason=reason,
                )
                outcomes.append(
                    {
                        "window_key": key,
                        "status": outcome,
                        "reason": reason,
                        "response_sha256": response_sha,
                        "new_versions": new_versions,
                        "new_events": new_events,
                    }
                )
                if outcome == "SERVICE_ERROR" or (
                    outcome not in {"SYNCED", "NO_DATA"}
                    and (
                        not regional
                        or reason in {"SOURCE_TRANSPORT_FAILED", "XML_TOKEN_REFLECTION_REJECTED"}
                    )
                ):
                    break
            report.update(source_posts=transport.posts, archive_gets=transport.downloads)
        if regional:
            report["regional_coverage"] = read_region_coverage(
                storage, COMPANY, now=datetime.now(UTC)
            ).model_dump(mode="json")
        return {
            **report,
            "attempted": len(outcomes),
            "outcomes": outcomes,
            "seconds": perf_counter() - started,
            "budget_overrun_seconds": max(0, perf_counter() - started - max_seconds),
            "quality": (
                {"reason": "DEFERRED_FOR_PRIORITY", "source_requests": 0}
                if report.get("stop_reason") == "PRIORITY_REFRESH_REQUESTED"
                else optional_quality(storage, regional=regional)
            ),
        }
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        import argparse

        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--probe", action="store_true")
        arguments = parser.parse_args()
        print(json.dumps(probe() if arguments.probe else asyncio.run(run()), ensure_ascii=False))
    except Exception:
        print(
            json.dumps(
                {
                    "company_id": COMPANY,
                    "reason": "REFRESH_UNAVAILABLE",
                    "coverage": "UNKNOWN",
                    "freshness": "UNKNOWN",
                }
            )
        )
        raise SystemExit(1) from None
