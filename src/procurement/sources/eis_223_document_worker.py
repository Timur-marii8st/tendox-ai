"""One queued223file step; called under the shared global server import lock."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from procurement.sources.eis_223_documents import download_public223_attachment
from procurement.sources.eis_corpus import resource_gate
from procurement.storage.eis_223_document_queue import next_document223, record_document223_attempt
from procurement.storage.eis_223_documents import collect_document223

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

SAFE_REASONS = frozenset(
    {
        "ROBOTS_CRAWL_DELAY",
        "SOURCE_BUSY",
        "ATTACHMENT_UNAVAILABLE",
        "ATTACHMENT_TOO_LARGE",
        "ATTACHMENT_URL_INVALID",
        "BROWSER_UNAVAILABLE",
        "PROXY_CONFIG_INVALID",
        "NOTICE_VERSION_STALE",
        "DEADLINE_EXPIRED",
        "PURCHASE_REJECTION_CONFIRMED",
        "PURCHASE_REJECTION_REVIEW_REQUIRED",
        "LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED",
        "UNKNOWN_MANIFEST",
        "DOCUMENT_BYTES_RESOURCE_LIMIT",
        "DOCUMENT_SET_RESOURCE_LIMIT",
        "DATABASE_BUDGET_REACHED",
        "DISK_RESERVE_REACHED",
    }
)


class Document223Step(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["IDLE", "PROCESSED", "BLOCKED"]
    attempted: Literal[0, 1]
    reason: str | None = None
    purchase_number: str | None = None
    content_uid: str | None = None
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"


def run_document223_step(
    storage: PostgresStorage,
    company: str,
    *,
    actor_id: str,
    now: datetime | None = None,
    downloader: Callable[[str, str], bytes] = download_public223_attachment,
) -> Document223Step:
    now = now or datetime.now(UTC)
    if not actor_id.strip() or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DOCUMENT_WORKER_INPUT_INVALID")
    gate = resource_gate(
        storage, company, max_database_bytes=100 * 1024**3, min_free_bytes=40 * 1024**3
    )
    if gate:
        return Document223Step(status="BLOCKED", attempted=0, reason=gate)
    target = next_document223(storage, company, now)
    if target is None:
        return Document223Step(status="IDLE", attempted=0)
    ref, uid = target
    reason = None
    try:
        collect_document223(storage, company, ref, uid, actor_id=actor_id, downloader=downloader)
    except ValueError as error:
        reason = str(error) if str(error) in SAFE_REASONS else "DOCUMENT_223_UNAVAILABLE"
    record_document223_attempt(
        storage,
        company,
        ref,
        uid,
        "FAILED" if reason else "RECEIVED",
        reason,
        actor_id=actor_id,
        now=datetime.now(UTC),
    )
    return Document223Step(
        status="BLOCKED" if reason else "PROCESSED",
        attempted=1,
        reason=reason,
        purchase_number=ref.purchase_number,
        content_uid=uid,
    )
