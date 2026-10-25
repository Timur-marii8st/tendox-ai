"""Exact price order across the complete matching saved corpus, before page selection."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Connection

from procurement.sources.tender_navigation import TenderNavigation, region_name_key
from procurement.storage.eis_223_index import (
    Eis223SearchLead,
    Eis223SearchResult,
    search_notice223_index,
)
from procurement.storage.eis_index_query import (
    EisIndexedLead,
    EisIndexedSearchResult,
    search_eis_index,
)
from procurement.storage.eis_mixed_comparison import MixedNoticeRef
from procurement.storage.eis_search_pagination import GlobalRank, SearchPagination
from procurement.storage.repository import PostgresStorage
from procurement.storage.tender_navigation import (
    NavigationReadCache,
    prime_navigation_cache,
    read_navigation,
    read_navigation_batch,
)

T = TypeVar("T")


class GlobalPriceOptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str = Field(min_length=1, max_length=120)
    law: Literal["all", "44", "223"] = "all"
    delivery_region: str = Field(default="", max_length=200)
    include_unknown_region: bool = False


class GlobalPriceCollector:
    """Full evidence digest with only the best remaining page retained in memory."""

    def __init__(
        self,
        company: str,
        options: GlobalPriceOptions,
        *,
        now: datetime,
        cursor: str | None,
        limit: int,
    ) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("SEARCH_PAGE_INVALID")
        self.limit = limit
        self.pager = SearchPagination(
            company=company,
            law="all",
            query=options.query,
            scope="GLOBAL_PRICE_V1:" + options.model_dump_json(),
            now=now,
            cursor=cursor,
        )
        self.leaders: list[tuple[GlobalRank, Any]] = []
        self.count = 0

    def observe(
        self,
        law: Literal["44", "223"],
        number: str,
        blocked: bool,
        amount: Decimal | None,
        evidence: object,
        item: T,
    ) -> None:
        comparable = amount is not None and amount.is_finite() and amount >= 0
        rank: GlobalRank = (
            blocked,
            not comparable,
            amount.copy_negate() if comparable and amount is not None else Decimal(0),
            law,
            number,
        )
        self.count += 1
        if self.pager.observe(rank, evidence):
            self.leaders.append((rank, item))
            self.leaders.sort(key=lambda entry: entry[0])
            del self.leaders[self.limit :]

    def finish(self) -> tuple[list[Any], str | None, str]:
        fingerprint, cursor = self.pager.finish(
            self.leaders[-1][0] if self.leaders else None, len(self.leaders)
        )
        return [entry[1] for entry in self.leaders], cursor, fingerprint


class GlobalPriceResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str
    law: Literal["all", "44", "223"]
    delivery_region: str
    include_unknown_region: bool
    order: Literal["price_desc"] = "price_desc"
    result44: EisIndexedSearchResult | None = None
    result223: Eis223SearchResult | None = None
    navigation: dict[str, TenderNavigation]
    matched_count: int
    unknown_region_count: int
    next_cursor: str | None
    page_snapshot_sha256: str
    snapshot_at: datetime
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"


class _SharedReadStorage(PostgresStorage):
    """Reuse one tenant-scoped RR READ ONLY transaction for both laws and XML facts."""

    def __init__(self, company: str, connection: Connection) -> None:
        self.company, self.connection = company, connection

    @contextmanager
    def transaction(
        self, company_id: str, *, consistent_read: bool = False
    ) -> Iterator[Connection]:
        if company_id != self.company:
            raise ValueError("GLOBAL_SEARCH_TENANT_MISMATCH")
        yield self.connection


def source_price223(lead: Eis223SearchLead) -> Decimal | None:
    notice = lead.notice
    if len(notice.lots) != 1:
        return None
    lot = notice.lots[0]
    kind = lot.source_price_kind or (
        "UNKNOWN" if notice.document_type == "purchaseNotice" else "INITIAL_SUM"
    )
    currency = (
        lot.currency_letter_code.value if lot.currency_letter_code else None
    ) or lot.currency.value
    if (
        kind not in {"INITIAL_SUM", "MAX_CONTRACT_PRICE"}
        or currency not in {"RUB", "RUR"}
        or lot.currency_numeric.value not in {None, "643"}
        or (lot.source_price_kind is not None and lot.source_currency_status != "CONSISTENT")
        or lot.source_price_formula_present is True
        or lot.source_commodity_price_present is True
    ):
        return None
    return (
        (lot.source_amount.value if lot.source_amount else None)
        if lot.source_price_kind
        else lot.initial_sum.value
    )


def search_global_price(
    storage: PostgresStorage,
    company: str,
    options: GlobalPriceOptions,
    *,
    now: datetime,
    cursor: str | None = None,
    limit: int = 100,
) -> GlobalPriceResult:
    collector = GlobalPriceCollector(company, options, now=now, cursor=cursor, limit=limit)
    at = collector.pager.at
    unknown_regions = 0
    selected_region = region_name_key(options.delivery_region)
    with (
        storage.transaction(company, consistent_read=True) as connection,
        NavigationReadCache() as cache,
    ):
        shared = _SharedReadStorage(company, connection)

        def observe(
            law: Literal["44", "223"],
            lead: EisIndexedLead | Eis223SearchLead,
            navigation: TenderNavigation | None = None,
        ) -> None:
            nonlocal unknown_regions
            if isinstance(lead, EisIndexedLead):
                number = lead.purchase_number
                amount, blocked = lead.nmck_rub, lead.application_status == "FAIL"
                deadline = lead.deadline
            else:
                number = lead.notice.purchase_number
                amount = source_price223(lead)
                blocked = (
                    lead.application_status == "FAIL"
                    or lead.source_schema_status == "FAIL"
                    or bool(
                        (lead.cancellation_state and lead.cancellation_state.operation_hold)
                        or (
                            lead.lot_cancellation_state
                            and lead.lot_cancellation_state.operation_hold
                        )
                    )
                )
                fact = lead.notice.selected_deadline or (
                    None if lead.notice.document_type == "purchaseNotice" else lead.notice.deadline
                )
                deadline = fact.value if fact and fact.status == "AWARE" and fact.value else None
            blocked = blocked or (deadline is not None and deadline <= at)
            if options.delivery_region.strip():
                regions = navigation.delivery_regions if navigation else ()
                unknown_regions += not bool(regions)
                if regions:
                    if not any(region_name_key(f.value) == selected_region for f in regions):
                        return
                elif not options.include_unknown_region:
                    return
            collector.observe(
                law,
                number,
                blocked,
                amount,
                {
                    "lead": lead.model_dump(mode="json"),
                    "navigation": navigation.model_dump(mode="json") if navigation else None,
                },
                (law, lead, navigation),
            )

        def reference(
            law: Literal["44", "223"], lead: EisIndexedLead | Eis223SearchLead
        ) -> MixedNoticeRef:
            if isinstance(lead, EisIndexedLead):
                return MixedNoticeRef(
                    law=law,
                    purchase_number=lead.purchase_number,
                    version_number=lead.version_number,
                    notice_xml_sha256=lead.xml_sha256,
                )
            return MixedNoticeRef(
                law=law,
                purchase_number=lead.notice.purchase_number,
                version_number=lead.notice.version_number,
                notice_xml_sha256=lead.notice.xml_sha256,
            )

        def observe_batch(
            law: Literal["44", "223"], leads: Sequence[EisIndexedLead | Eis223SearchLead]
        ) -> None:
            ordered = list(leads)
            if options.delivery_region.strip():
                prime_navigation_cache(
                    shared, company, [reference(law, lead) for lead in leads], cache
                )
                sources = cache.sources or {}

                def archive_order(lead: EisIndexedLead | Eis223SearchLead) -> tuple[str, str]:
                    ref = reference(law, lead)
                    row = sources.get(
                        (law, ref.purchase_number, ref.version_number, ref.notice_xml_sha256), {}
                    )
                    return str(row.get("archive_sha256", "")), ref.purchase_number

                # One read per source archive in each batch; digest order stays deterministic.
                ordered.sort(key=archive_order)
                with closing(
                    read_navigation_batch(
                        shared, company, [reference(law, lead) for lead in ordered], cache
                    )
                ) as navigation:
                    for lead, nav in zip(ordered, navigation, strict=True):
                        observe(law, lead, nav)
            else:
                for lead in ordered:
                    observe(law, lead)

        part44 = (
            search_eis_index(
                shared,
                company,
                options.query,
                now=at,
                search_scope="NOT_EXPIRED_OR_UNKNOWN",
                paginate=True,
                on_matches=lambda leads: observe_batch("44", leads),
            )
            if options.law != "223"
            else None
        )
        part223 = (
            search_notice223_index(
                shared,
                company,
                options.query,
                now=at,
                paginate=True,
                on_matches=lambda leads: observe_batch("223", leads),
            )
            if options.law != "44"
            else None
        )
        selected, next_cursor, fingerprint = collector.finish()
        navigation = {}
        prime_navigation_cache(
            shared,
            company,
            [reference(law, lead) for law, lead, nav in selected if nav is None],
            cache,
        )
        for law, lead, nav in selected:
            if nav is None:
                if isinstance(lead, EisIndexedLead):
                    ref = MixedNoticeRef(
                        law=law,
                        purchase_number=lead.purchase_number,
                        version_number=lead.version_number,
                        notice_xml_sha256=lead.xml_sha256,
                    )
                else:
                    ref = MixedNoticeRef(
                        law=law,
                        purchase_number=lead.notice.purchase_number,
                        version_number=lead.notice.version_number,
                        notice_xml_sha256=lead.notice.xml_sha256,
                    )
                try:
                    nav = read_navigation(shared, company, ref, cache=cache)
                except (ValueError, LookupError):
                    continue
            navigation[f"{law}:{nav.purchase_number}:{nav.version_number}:{nav.xml_sha256}"] = nav
        return GlobalPriceResult(
            query=options.query,
            law=options.law,
            delivery_region=options.delivery_region,
            include_unknown_region=options.include_unknown_region,
            result44=part44.model_copy(
                update={
                    "matched": tuple(lead for law, lead, _ in selected if law == "44"),
                    "next_cursor": None,
                }
            )
            if part44
            else None,
            result223=part223.model_copy(
                update={
                    "matched": tuple(lead for law, lead, _ in selected if law == "223"),
                    "next_cursor": None,
                }
            )
            if part223
            else None,
            navigation=navigation,
            matched_count=collector.count,
            unknown_region_count=unknown_regions,
            next_cursor=next_cursor,
            page_snapshot_sha256=fingerprint,
            snapshot_at=at,
        )
