"""Audit retention separately from the EIS attempt; it never closes a corpus window."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import insert

from procurement.sources.eis_no_data_evidence import NoDataRetention
from procurement.storage.models import audit_events

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


def record_no_data_evidence(
    storage: PostgresStorage,
    company_id: str,
    receipt: NoDataRetention,
    *,
    actor_id: str,
) -> str:
    if receipt.company_id != company_id or not actor_id.strip() or receipt.status == "DISABLED":
        raise ValueError("NO_DATA_EVIDENCE_AUDIT_INVALID")
    event_id = str(uuid4())
    with storage.transaction(company_id) as conn:
        conn.execute(
            insert(audit_events).values(
                company_id=company_id,
                event_id=event_id,
                actor_id=actor_id,
                event_type="EIS_NO_DATA_RESPONSE_EVIDENCE",
                object_type="eis_sync_target",
                object_id=receipt.window_key,
                occurred_at=receipt.observed_at,
                basis={"evidence": receipt.model_dump(mode="json"), "coverage": "UNKNOWN"},
            )
        )
    return event_id
