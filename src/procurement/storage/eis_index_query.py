"""Explainable search across every current notice in a tenant's EIS index."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import Select, and_, case, exists, func, or_, select, true, union_all
from sqlalchemy.engine import Connection, RowMapping

from procurement.sources.eis_feed_archive import EisNoticeSnapshot, EisProcedureEvent
from procurement.sources.eis_index_search import (
    EisComparedNotice,
    EisSearchTermEvidence,
    compare_indexed_notices,
    search_query_keys_v1,
)
from procurement.sources.eis_procedure_state import resolve_procedure_state
from procurement.storage.eis_notice_hold import (
    notice_receipt_integrity_hold_clause,
    notice_variant_hold_clause,
)
from procurement.storage.eis_search_pagination import SearchPagination
from procurement.storage.models import (
    eis_feed_windows,
    eis_notice_search_keys,
    eis_notice_variant_origins,
    eis_notice_variants,
    eis_notice_versions,
    eis_procedure_events,
    eis_sync_targets,
)

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

_SNAPSHOT = TypeAdapter(EisNoticeSnapshot)
_COMPARED = TypeAdapter(EisComparedNotice)
_SNAPSHOT_FIELDS = frozenset(EisNoticeSnapshot.__dataclass_fields__)
_EVENT = TypeAdapter(EisProcedureEvent)
_EVENT_FIELDS = frozenset(EisProcedureEvent.__dataclass_fields__)
_NOTICE_PAGES = {
    "epNotificationEF2020": "ea20",
    "epNotificationEZK2020": "zk20",
    "epNotificationEOK2020": "ok20",
}
EisIndexSearchScope = Literal["ALL_CACHED", "NOT_EXPIRED_OR_UNKNOWN"]


class EisIndexedAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    url: str
    locator: str


class EisIndexedLotItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    ktru_code: str | None
    okpd2_code: str | None
    quantity: Decimal | None
    unit: str | None
    locator: str


class EisIndexedLead(BaseModel):
    model_config = ConfigDict(frozen=True)
    purchase_number: str
    document_type: str
    version_number: int
    title: str
    notice_url: str
    nmck_rub: Decimal | None
    deadline: datetime | None
    application_status: Literal["FAIL", "UNKNOWN"]
    economic_status: str
    match_quality: Literal["STRONG", "PARTIAL"]
    matched_terms: tuple[str, ...]
    match_locator: str
    reasons: tuple[str, ...]
    source_window: str
    source_member: str
    xml_sha256: str
    lot_items: tuple[EisIndexedLotItem, ...]
    attachments: tuple[EisIndexedAttachment, ...]
    term_evidence: tuple[EisSearchTermEvidence, ...] = ()


class EisIndexedSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    query: str
    inspected_current_notices: int
    matched_count: int
    indexed_windows: int
    latest_ingested_at: datetime | None
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"
    comparison_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    matched: tuple[EisIndexedLead, ...]
    planned_windows: int = 0
    pending_windows: int = 0
    requested_region_codes: int = 0
    evaluated_candidate_notices: int = 0
    unindexed_versions: int = 0
    latest_source_publication: datetime | None = None
    source_freshness: Literal["UNKNOWN"] = "UNKNOWN"
    compared_at: datetime | None = None
    search_elapsed_ms: int = 0
    eligible_count: int = 0
    strong_matched_count: int | None = Field(default=None, ge=0)
    partial_matched_count: int | None = Field(default=None, ge=0)
    held_current_notices: int = Field(default=0, ge=0)
    search_scope: EisIndexSearchScope = "ALL_CACHED"
    total_current_notices: int = Field(default=0, ge=0)
    excluded_expired_current_notices: int = Field(default=0, ge=0)
    next_cursor: str | None = None
    page_snapshot_sha256: str | None = None
    snapshot_at: datetime | None = None


def _rank_key(item: EisComparedNotice) -> tuple[bool, bool, bool, Decimal, int, str]:
    return (
        item.application_status == "FAIL",
        item.match_quality != "STRONG",
        item.conservative_profit_rub is None,
        -(item.conservative_profit_rub or Decimal(0)),
        -len(item.matched_terms),
        item.snapshot.purchase_number,
    )


@contextmanager
def _stream_notice_rows(
    connection: Connection, statement: Select[tuple[Any, ...]], batch_size: int
) -> Iterator[Iterator[Sequence[RowMapping]]]:
    """Keep one statement-local server cursor open while consuming bounded batches."""
    cursor = connection.execute(statement, execution_options={"yield_per": batch_size})
    try:
        yield cursor.mappings().partitions(batch_size)
    finally:
        cursor.close()


def search_eis_index(
    storage: PostgresStorage,
    company_id: str,
    query: str,
    *,
    now: datetime,
    limit: int = 100,
    batch_size: int = 500,
    require_documents: bool = False,
    exclude_failed: bool = False,
    search_scope: EisIndexSearchScope = "ALL_CACHED",
    paginate: bool = False,
    cursor: str | None = None,
) -> EisIndexedSearchResult:
    """Prefilter exact current versions; compare all candidates in bounded batches."""
    started = perf_counter_ns()
    if (
        not company_id.strip()
        or not 1 <= limit <= 100
        or not 1 <= batch_size <= 1000
        or now.utcoffset() is None
        or search_scope not in {"ALL_CACHED", "NOT_EXPIRED_OR_UNKNOWN"}
    ):
        raise ValueError("INDEX_QUERY_INVALID")
    compare_indexed_notices((), query, now=now)
    pager = (
        SearchPagination(
            company=company_id,
            law="44",
            query=query,
            scope=search_scope,
            now=now,
            cursor=cursor,
        )
        if paginate
        else None
    )
    if cursor is not None and pager is None:
        raise ValueError("SEARCH_PAGE_INVALID")
    if pager is not None:
        now = pager.at
    evaluated_count = 0
    matched_count = 0
    strong_count = 0
    eligible_count = 0
    leaders: list[EisComparedNotice] = []
    source_windows: dict[str, str] = {}
    newer = eis_notice_versions.alias("newer")
    current = ~exists(
        select(newer.c.purchase_number).where(
            and_(
                newer.c.company_id == eis_notice_versions.c.company_id,
                newer.c.purchase_number == eis_notice_versions.c.purchase_number,
                newer.c.version_number > eis_notice_versions.c.version_number,
                newer.c.ingested_at <= now if paginate else true(),
            )
        )
    )
    scope = and_(
        eis_notice_versions.c.ingested_at <= now if paginate else true(),
        (
            or_(eis_notice_versions.c.deadline.is_(None), eis_notice_versions.c.deadline > now)
            if search_scope == "NOT_EXPIRED_OR_UNKNOWN"
            else true()
        ),
    )
    key_join = and_(
        eis_notice_search_keys.c.company_id == eis_notice_versions.c.company_id,
        eis_notice_search_keys.c.purchase_number == eis_notice_versions.c.purchase_number,
        eis_notice_search_keys.c.version_number == eis_notice_versions.c.version_number,
    )
    indexed = exists(select(eis_notice_search_keys.c.purchase_number).where(key_join))
    held = notice_variant_hold_clause(
        company_id, eis_notice_versions.c.purchase_number, eis_notice_versions.c.version_number
    )
    indexed_candidates = (
        select(eis_notice_versions.c.purchase_number, eis_notice_versions.c.version_number)
        .select_from(eis_notice_versions.join(eis_notice_search_keys, key_join))
        .where(
            and_(
                eis_notice_versions.c.company_id == company_id,
                current,
                scope,
                ~held,
                eis_notice_search_keys.c["keys"].overlap(list(search_query_keys_v1(query))),
            )
        )
    )
    with storage.transaction(company_id, consistent_read=True) as connection:
        total_current_count, latest_source_publication, version_count = connection.execute(
            select(
                func.count(func.distinct(eis_notice_versions.c.purchase_number)),
                func.max(eis_notice_versions.c.published_at).filter(
                    eis_notice_versions.c.published_at <= now
                ),
                func.count(),
            ).where(
                eis_notice_versions.c.company_id == company_id,
                eis_notice_versions.c.ingested_at <= now if paginate else true(),
            )
        ).one()
        expired_count = (
            connection.scalar(
                select(func.count())
                .select_from(eis_notice_versions)
                .where(
                    eis_notice_versions.c.company_id == company_id,
                    current,
                    eis_notice_versions.c.ingested_at <= now if paginate else true(),
                    eis_notice_versions.c.deadline <= now,
                )
            )
            if search_scope == "NOT_EXPIRED_OR_UNKNOWN"
            else 0
        )
        current_count = total_current_count - int(expired_count or 0)
        # Count from ledger keys rather than probing every canonical purchase.
        # Receipt-only corruption still holds the whole tenant, including rows
        # without a corresponding ledger key.
        held_keys = union_all(
            *(
                select(table.c.purchase_number, table.c.version_number).where(
                    table.c.company_id == company_id
                )
                for table in (eis_notice_variants, eis_notice_variant_origins)
            )
        ).subquery("held_keys")
        held_rows = (
            select(func.count(func.distinct(eis_notice_versions.c.purchase_number)))
            .select_from(
                eis_notice_versions.join(
                    held_keys,
                    and_(
                        held_keys.c.purchase_number == eis_notice_versions.c.purchase_number,
                        held_keys.c.version_number >= eis_notice_versions.c.version_number,
                    ),
                )
            )
            .where(eis_notice_versions.c.company_id == company_id, current, scope, held)
            .scalar_subquery()
        )
        held_count = connection.scalar(
            select(
                case(
                    (notice_receipt_integrity_hold_clause(company_id), current_count),
                    else_=held_rows,
                )
            )
        )
        key_count = connection.execute(
            select(func.count())
            .select_from(eis_notice_search_keys)
            .where(
                eis_notice_search_keys.c.company_id == company_id,
                exists(select(1).where(key_join, eis_notice_versions.c.ingested_at <= now))
                if paginate
                else true(),
            )
        ).scalar_one()
        candidates = (
            union_all(
                indexed_candidates,
                # Missing derivations must never silently remove a possible match.
                select(
                    eis_notice_versions.c.purchase_number, eis_notice_versions.c.version_number
                ).where(
                    and_(
                        eis_notice_versions.c.company_id == company_id,
                        current,
                        scope,
                        ~indexed,
                        ~held,
                    )
                ),
            )
            if version_count > key_count
            else indexed_candidates
        ).subquery("candidates")
        completed_windows = (
            select(eis_feed_windows.c.window_key)
            .where(
                eis_feed_windows.c.company_id == company_id,
                eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
            )
            .distinct()
            .subquery("completed_windows")
        )
        region_code = func.split_part(eis_sync_targets.c.window_key, "/", 3)
        regional_counts = connection.execute(
            select(
                region_code,
                func.count(),
                func.count().filter(completed_windows.c.window_key.is_(None)),
            )
            .select_from(
                eis_sync_targets.outerjoin(
                    completed_windows,
                    completed_windows.c.window_key == eis_sync_targets.c.window_key,
                )
            )
            .where(eis_sync_targets.c.company_id == company_id)
            .group_by(region_code)
        ).all()
        planned_windows = sum(row[1] for row in regional_counts)
        pending_windows = sum(row[2] for row in regional_counts)
        requested_region_codes = len(regional_counts)
        indexed_windows, latest_ingested_at = connection.execute(
            select(
                func.count(func.distinct(eis_feed_windows.c.window_key)),
                func.max(eis_feed_windows.c.ingested_at),
            ).where(
                eis_feed_windows.c.company_id == company_id,
                eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
            )
        ).one()
        statement = (
            select(eis_notice_versions)
            .join(
                candidates,
                and_(
                    candidates.c.purchase_number == eis_notice_versions.c.purchase_number,
                    candidates.c.version_number == eis_notice_versions.c.version_number,
                ),
            )
            .where(eis_notice_versions.c.company_id == company_id)
            .order_by(eis_notice_versions.c.purchase_number)
        )
        with _stream_notice_rows(connection, statement, batch_size) as batches:
            for rows in batches:
                notices = []
                window_by_digest: dict[str, str] = {}
                for row in rows:
                    data = {key: row[key] for key in _SNAPSHOT_FIELDS}
                    snapshot = _SNAPSHOT.validate_python(data)
                    notices.append(snapshot)
                    window_by_digest[snapshot.xml_sha256] = row["window_key"]
                evaluated_count += len(notices)
                events_by_number: dict[str, list[EisProcedureEvent]] = {}
                event_rows = connection.execute(
                    select(eis_procedure_events).where(
                        and_(
                            eis_procedure_events.c.company_id == company_id,
                            eis_procedure_events.c.purchase_number.in_(
                                [notice.purchase_number for notice in notices]
                            ),
                        )
                    )
                ).mappings()
                for row in event_rows:
                    event = _EVENT.validate_python({key: row[key] for key in _EVENT_FIELDS})
                    events_by_number.setdefault(event.purchase_number, []).append(event)
                states = {
                    number: resolve_procedure_state(events, purchase_number=number, now=now)
                    for number, events in events_by_number.items()
                }
                compared = compare_indexed_notices(notices, query, now=now, procedure_states=states)
                matched_count += len(compared.matched_notices)
                strong_count += sum(
                    item.match_quality == "STRONG" for item in compared.matched_notices
                )
                eligible = [
                    item
                    for item in compared.matched_notices
                    if (not require_documents or item.snapshot.attachments)
                    and (not exclude_failed or item.application_status != "FAIL")
                ]
                eligible_count += len(eligible)
                if pager is not None:
                    eligible = [
                        item
                        for item in eligible
                        if pager.observe(
                            _rank_key(item),
                            {
                                "comparison": _COMPARED.dump_python(item, mode="json"),
                                "window": window_by_digest[item.snapshot.xml_sha256],
                            },
                        )
                    ]
                source_windows.update(
                    (item.snapshot.xml_sha256, window_by_digest[item.snapshot.xml_sha256])
                    for item in eligible
                )
                leaders.extend(eligible)
                leaders.sort(key=_rank_key)
                del leaders[limit:]
                kept_digests = {item.snapshot.xml_sha256 for item in leaders}
                source_windows = {
                    digest: window
                    for digest, window in source_windows.items()
                    if digest in kept_digests
                }
    output = tuple(
        EisIndexedLead(
            purchase_number=item.snapshot.purchase_number,
            document_type=item.snapshot.document_type,
            version_number=item.snapshot.version_number,
            title=item.snapshot.title,
            notice_url=(
                "https://zakupki.gov.ru/epz/order/notice/"
                f"{_NOTICE_PAGES[item.snapshot.document_type]}"
                "/view/common-info.html"
                f"?regNumber={item.snapshot.purchase_number}"
            ),
            nmck_rub=item.snapshot.nmck_rub,
            deadline=item.snapshot.deadline,
            application_status=item.application_status,
            economic_status=item.economics_status,
            match_quality=item.match_quality,
            matched_terms=item.matched_terms,
            match_locator=item.match_locator,
            term_evidence=item.term_evidence,
            reasons=item.reasons,
            source_window=source_windows[item.snapshot.xml_sha256],
            source_member=item.snapshot.source_member,
            xml_sha256=item.snapshot.xml_sha256,
            lot_items=tuple(
                EisIndexedLotItem(
                    name=lot.name,
                    ktru_code=lot.ktru_code,
                    okpd2_code=lot.okpd2_code,
                    quantity=lot.quantity,
                    unit=lot.unit,
                    locator=lot.locator,
                )
                for lot in item.snapshot.lot_items
            ),
            attachments=tuple(
                EisIndexedAttachment(
                    filename=attachment.filename,
                    url=attachment.url,
                    locator=attachment.locator,
                )
                for attachment in item.snapshot.attachments
            ),
        )
        for item in leaders
    )
    fingerprint, next_cursor = (
        pager.finish(
            _rank_key(leaders[-1]) if leaders else None,
            len(leaders),
        )
        if pager is not None
        else (None, None)
    )
    return EisIndexedSearchResult(
        query=query,
        inspected_current_notices=current_count,
        search_scope=search_scope,
        total_current_notices=total_current_count,
        excluded_expired_current_notices=int(expired_count or 0),
        held_current_notices=held_count,
        matched_count=matched_count,
        strong_matched_count=strong_count,
        partial_matched_count=matched_count - strong_count,
        indexed_windows=indexed_windows,
        latest_ingested_at=latest_ingested_at,
        matched=output,
        planned_windows=planned_windows,
        pending_windows=pending_windows,
        requested_region_codes=requested_region_codes,
        evaluated_candidate_notices=evaluated_count,
        unindexed_versions=version_count - key_count,
        latest_source_publication=latest_source_publication,
        compared_at=now,
        search_elapsed_ms=(perf_counter_ns() - started) // 1_000_000,
        eligible_count=eligible_count,
        next_cursor=next_cursor,
        page_snapshot_sha256=fingerprint,
        snapshot_at=now if pager is not None else None,
    )
