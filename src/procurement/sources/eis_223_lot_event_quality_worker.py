"""Two offline cancellation variants per run; no additional source requests."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING
from zipfile import ZipFile

from procurement.sources.eis_223_lot_events import (
    Eis223LotCancellation,
    inspect_purchase_lot_cancellation_archive,
    validate_purchase_lot_cancellation_schema,
)
from procurement.sources.eis_223_schema import load_schema_tree
from procurement.storage.eis_223_lot_events import (
    pending_lot_event_quality,
    record_lot_event_schema_check,
)

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


def process_lot_event_quality_batch(
    storage: PostgresStorage,
    company: str,
    *,
    actor_id: str,
    schema_base: Path = Path("/var/lib/eis-browser/research/223"),
) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", company) or not actor_id.strip():
        raise ValueError("QUALITY_SCOPE_INVALID")
    started = perf_counter()
    targets = pending_lot_event_quality(storage, company)
    if not targets:
        return {"selected": 0, "new_checks": 0, "source_requests": 0, "reason": "NOT_DUE"}
    archives = {r["archive_sha256"]: bytes(r["content"]) for r in targets}
    if sum(map(len, archives.values())) > 32 * 1024**2:
        raise ValueError("QUALITY_BYTE_BUDGET_REACHED")
    trees = tuple(
        load_schema_tree(schema_base / company / f"schemas-{r}", r) for r in ("16.2", "16.3")
    )
    for digest, raw in archives.items():
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("QUALITY_ARCHIVE_SHA_MISMATCH")
        inspect_purchase_lot_cancellation_archive(
            raw,
            company_id=company,
            source_response_sha256="0" * 64,
            source_locator="saved-immutable-event-archive",
        )
    attempted = new = failed = 0
    for row in targets:
        if perf_counter() - started >= 30:
            break
        event = Eis223LotCancellation.model_validate(row["snapshot"])
        if (event.event_guid.value, event.purchase_number, event.xml_sha256) != (
            row["event_guid"],
            row["purchase_number"],
            row["xml_sha256"],
        ):
            raise ValueError("QUALITY_SOURCE_BINDING_INVALID")
        with ZipFile(BytesIO(archives[row["archive_sha256"]])) as archive:
            content = archive.read(event.source_member)
        for tree in trees:
            check = validate_purchase_lot_cancellation_schema(
                event, content, tree, now=datetime.now(UTC)
            )
            new += record_lot_event_schema_check(storage, company, check, actor_id=actor_id)
            failed += check.status == "FAIL"
        attempted += 1
    return {
        "selected": len(targets),
        "attempted": attempted,
        "new_checks": new,
        "failed_checks": failed,
        "source_requests": 0,
        "reason": "COMPLETED" if attempted == len(targets) else "TIME_BUDGET_REACHED",
    }
