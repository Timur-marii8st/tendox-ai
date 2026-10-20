"""Version-bound derived keys and bounded tenant-scoped backfill."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, exists, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_index_search import search_keys_v1
from procurement.storage.models import audit_events, eis_notice_search_keys, eis_notice_versions

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy import Connection

    from procurement.storage.repository import PostgresStorage


def insert_search_keys(
    connection: Connection,
    company_id: str,
    purchase_number: str,
    version_number: int,
    title: str,
    lot_names: Iterable[str],
) -> bool:
    """Persist only derivations of this exact immutable XML version."""
    keys = set(search_keys_v1(title))
    for name in lot_names:
        keys.update(search_keys_v1(name))
    return (
        connection.execute(
            pg_insert(eis_notice_search_keys)
            .values(
                company_id=company_id,
                purchase_number=purchase_number,
                version_number=version_number,
                keys=sorted(keys),
                key_version="eis-lexical-v1",
            )
            .on_conflict_do_nothing()
            .returning(eis_notice_search_keys.c.purchase_number)
        ).scalar_one_or_none()
        is not None
    )


def backfill_search_keys(
    storage: PostgresStorage, company_id: str, *, actor_id: str, batch_size: int = 500
) -> int:
    """Reindex legacy versions without mutating them or holding an unbounded batch."""
    if not company_id.strip() or not actor_id.strip() or not 1 <= batch_size <= 1000:
        raise ValueError("SEARCH_BACKFILL_INVALID")
    indexed = exists(
        select(eis_notice_search_keys.c.purchase_number).where(
            and_(
                eis_notice_search_keys.c.company_id == eis_notice_versions.c.company_id,
                eis_notice_search_keys.c.purchase_number == eis_notice_versions.c.purchase_number,
                eis_notice_search_keys.c.version_number == eis_notice_versions.c.version_number,
            )
        )
    )
    total = 0
    while True:
        with storage.transaction(company_id) as connection:
            rows = (
                connection.execute(
                    select(
                        eis_notice_versions.c.purchase_number,
                        eis_notice_versions.c.version_number,
                        eis_notice_versions.c.title,
                        eis_notice_versions.c.lot_items,
                    )
                    .where(and_(eis_notice_versions.c.company_id == company_id, ~indexed))
                    .order_by(
                        eis_notice_versions.c.purchase_number, eis_notice_versions.c.version_number
                    )
                    .limit(batch_size)
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            added = sum(
                insert_search_keys(
                    connection,
                    company_id,
                    row["purchase_number"],
                    row["version_number"],
                    row["title"],
                    (item["name"] for item in row["lot_items"]),
                )
                for row in rows
            )
            connection.execute(
                insert(audit_events).values(
                    event_id=str(uuid.uuid4()),
                    company_id=company_id,
                    actor_id=actor_id,
                    event_type="EIS_SEARCH_KEYS_BACKFILLED",
                    object_type="EIS_SEARCH_INDEX",
                    object_id="eis-lexical-v1",
                    object_version=None,
                    basis={"new_versions": added, "key_version": "eis-lexical-v1"},
                    occurred_at=datetime.now(UTC),
                )
            )
            total += added
    return total
