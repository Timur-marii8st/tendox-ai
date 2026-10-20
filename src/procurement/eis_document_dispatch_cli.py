"""Read-only due-work probe before the server requests a source-lock handoff."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine

from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_document_worker import run_document_step
from procurement.storage.eis_223_document_queue import next_document223
from procurement.storage.repository import PostgresStorage

if TYPE_CHECKING:
    from collections.abc import Sequence


class DocumentDispatchProbe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["READY", "IDLE", "BLOCKED"]
    law: Literal["44", "223"] | None = None
    reason: str | None = None
    checked_at: datetime
    attempted: Literal[0] = 0
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"


def probe_dispatch(
    storage: PostgresStorage,
    company: str,
    *,
    preferred_law: Literal["44", "223"],
    now: datetime | None = None,
) -> DocumentDispatchProbe:
    """Choose a due tenant family; an empty family never consumes its turn."""
    now = now or datetime.now(UTC)
    if not company.strip() or preferred_law not in {"44", "223"} or now.utcoffset() is None:
        raise ValueError("DOCUMENT_DISPATCH_INPUT_INVALID")
    reason = resource_gate(
        storage, company, max_database_bytes=100 * 1024**3, min_free_bytes=40 * 1024**3
    )
    if reason:
        return DocumentDispatchProbe(status="BLOCKED", reason=reason, checked_at=now)
    laws: tuple[Literal["44", "223"], ...] = (
        preferred_law,
        "223" if preferred_law == "44" else "44",
    )
    for law in laws:
        if law == "44":
            result = run_document_step(
                storage, company, actor_id="server-document-probe", now=now, probe_only=True
            )
            if result["status"] == "BLOCKED":
                return DocumentDispatchProbe(
                    status="BLOCKED", reason=str(result["reason"]), checked_at=now
                )
            ready = result["status"] == "READY"
        else:
            ready = next_document223(storage, company, now) is not None
        if ready:
            return DocumentDispatchProbe(status="READY", law=law, checked_at=now)
    return DocumentDispatchProbe(status="IDLE", checked_at=now)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--preferred-law", choices=("44", "223"), required=True)
    args = parser.parse_args(argv)
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        report = probe_dispatch(
            PostgresStorage(engine), args.company_id, preferred_law=args.preferred_law
        )
        print(report.model_dump_json())
        return 2 if report.status == "BLOCKED" else 0
    except Exception:
        print(
            DocumentDispatchProbe(
                status="BLOCKED", reason="DOCUMENT_PROBE_UNAVAILABLE", checked_at=datetime.now(UTC)
            ).model_dump_json()
        )
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
