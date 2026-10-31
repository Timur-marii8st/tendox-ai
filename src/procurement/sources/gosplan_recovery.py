"""Single explicit 44-FZ recovery orchestration under an external source lease."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from procurement.sources.eis_number_sync import sync_eis_number
from procurement.sources.gosplan_queue import GosplanQueue

# Provider types are only a filter; official EIS source validation still decides admission.
RECOVERABLE_44 = frozenset(
    ("epNotificationEF2020", "epNotificationEZK2020", "epNotificationEOK2020")
)

if TYPE_CHECKING:
    from procurement.sources.eis_feed_sync import EisFeedTransport
    from procurement.storage.repository import PostgresStorage


async def recover_one_44(
    queue: GosplanQueue,
    storage: PostgresStorage,
    company: str,
    number: str,
    token: str,
    transport: EisFeedTransport,
) -> str:
    """Claim durably; the caller must hold the source lease and joint budget.

    Unknown failures remain UNKNOWN, and an interrupted claim remains open for
    explicit reconciliation. This function does not schedule retries or 223-FZ.
    """
    matches = [
        row for row in queue.pending_with_types(company) if row[0] == "44" and row[1] == number
    ]
    if len(matches) != 1 or matches[0][3] not in RECOVERABLE_44:
        return "UNSUPPORTED"
    claim = queue.claim(company, "44", number, datetime.now(UTC), matches[0][2])
    try:
        result = await sync_eis_number(
            storage, company, "gosplan-official-recovery", number, token, transport
        )
    except Exception:
        queue.finish(company, claim, "UNKNOWN", None)
        return "UNKNOWN"
    if result.purchase_number != number:
        queue.finish(company, claim, "UNKNOWN", None)
        return "UNKNOWN"
    if result.status == "SYNCED" and (
        result.latest_version_number is None
        or result.latest_xml_sha256 is None
        or result.source_response_sha256 is None
    ):
        queue.finish(company, claim, "UNKNOWN", None)
        return "UNKNOWN"
    queue.finish(company, claim, result.status, result.source_response_sha256)
    return result.status


async def recover_one_223(
    queue: GosplanQueue,
    storage: PostgresStorage,
    company: str,
    number: str,
    token: str,
    transport: EisFeedTransport,
) -> str:
    """Process only explicit 223-FZ families; caller owns source lease and budget."""
    from procurement.sources.eis_223_number_sync import FAMILIES, sync_223_number

    matches = [row for row in queue.pending(company) if row[0] == "223" and row[1] == number]
    if len(matches) != 1:
        return "UNKNOWN"
    family = queue.candidate_type(company, "223", number)
    if family not in FAMILIES:
        return "UNSUPPORTED"
    claim = queue.claim(company, "223", number, datetime.now(UTC), matches[0][2])
    try:
        result = await sync_223_number(
            storage, company, "gosplan-official-recovery", number, family, token, transport
        )
    except Exception:
        queue.finish(company, claim, "UNKNOWN", None)
        return "UNKNOWN"
    if result.purchase_number != number or (
        result.status == "SYNCED"
        and (
            result.latest_version_number is None
            or result.latest_xml_sha256 is None
            or result.source_response_sha256 is None
        )
    ):
        queue.finish(company, claim, "UNKNOWN", None)
        return "UNKNOWN"
    queue.finish(company, claim, result.status, result.source_response_sha256)
    return result.status
