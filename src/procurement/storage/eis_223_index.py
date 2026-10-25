"""Immutable 223-FZ source intake and read-only, lot-preserving metadata search."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, func, insert, select, text, true, tuple_

from procurement.sources.eis_223_archive import (
    PARSABLE_DOCUMENT_TYPES,
    Eis223ArchiveInspection,
    Eis223ContractError,
    Eis223DocumentType,
    Eis223NoticeSnapshot,
    inspect_notice223_archive,
)
from procurement.sources.eis_223_events import Eis223RejectionState
from procurement.sources.eis_223_lot_event_policy import Eis223LotCancellationState
from procurement.sources.eis_223_policy import deadline223, unavailable223
from procurement.sources.eis_223_schema import Eis223SchemaCheck, schema_quality
from procurement.sources.eis_223_window_limits import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_EXPANDED_BYTES,
    MAX_ARCHIVE_MEMBERS,
    MAX_NOTICE_ARCHIVES,
    MAX_NOTICE_COMPRESSED_BYTES,
    MAX_NOTICE_EXPANDED_BYTES,
    MAX_NOTICE_MEMBERS,
    MAX_XML_BYTES,
)
from procurement.sources.eis_feed import validate_eis_archive_url
from procurement.sources.eis_index_search import (
    EisSearchTermEvidence,
    exact_purchase_number,
    match_search_terms,
    search_keys_v1,
    search_query_keys_v1,
    search_query_terms,
)
from procurement.storage.eis_223_events import read_event223_states
from procurement.storage.eis_223_lot_events import read_lot_event223_states
from procurement.storage.eis_search_pagination import PAGE_COMPARISONS, SearchPagination
from procurement.storage.models import (
    audit_events,
    eis_223_archive_sources,
    eis_223_blobs,
    eis_223_notice_versions,
    eis_223_schema_checks,
    eis_223_windows,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

    from procurement.sources.eis_feed import EisFeedResponse
    from procurement.storage.repository import PostgresStorage

_WINDOW = re.compile(
    r"^getDocsIP/RI223/(?:(?:0[1-9]|[1-9][0-9])/"
    r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})\+03:00/"
    r"(?P<family>purchaseNoticeAESMBO|purchaseNoticeZKESMBO|purchaseNotice)"
    r"|by-number/(?P<number>[0-9]{11})/(?P<target_family>purchaseNoticeKESMBO))$"
)
_SEARCH_BATCH_SIZE = 200
_SEARCH_RESULT_LIMIT = 100


class Eis223IndexConflict(ValueError):
    """Contradictory source bytes cannot replace a saved version."""


class IndexModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Eis223ReadyWindow(IndexModel):
    window_key: str
    response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prepared_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archives: tuple[bytes, ...] = Field(min_length=1, max_length=MAX_NOTICE_ARCHIVES)
    archive_urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_NOTICE_ARCHIVES)


class Eis223IngestReport(IndexModel):
    window_key: str
    archive_count: int
    record_count: int
    new_versions: int
    replayed: bool
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


class Eis223SearchLead(IndexModel):
    cancellation_state: Eis223RejectionState | None = None
    lot_cancellation_state: Eis223LotCancellationState | None = None
    notice: Eis223NoticeSnapshot
    source_window: str
    source_response_sha256: str
    archive_sha256: str
    match_quality: Literal["STRONG", "PARTIAL"]
    matched_terms: tuple[str, ...]
    term_evidence: tuple[EisSearchTermEvidence, ...]
    matched_lot_ordinal: str | None
    application_status: Literal["FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]
    source_schema_status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    source_schema_checks: tuple[Eis223SchemaCheck, ...] = ()


class Eis223SearchResult(IndexModel):
    query: str
    checked_at: datetime
    indexed_current_notices: int
    indexed_windows: int
    evaluated_candidates: int
    compared_candidates: int = 0
    reused_candidates: int = 0
    matched_count: int
    matched: tuple[Eis223SearchLead, ...]
    latest_ingested_at: datetime | None
    law: Literal["223"] = "223"
    document_types: tuple[Eis223DocumentType, ...] = PARSABLE_DOCUMENT_TYPES
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"
    economics_status: Literal["UNKNOWN"] = "UNKNOWN"
    next_cursor: str | None = None
    page_snapshot_sha256: str | None = None
    snapshot_at: datetime | None = None


def bind_notice223_window(
    window_key: str,
    initial: EisFeedResponse,
    prepared: EisFeedResponse,
    downloaded: dict[str, bytes],
) -> Eis223ReadyWindow:
    match = _WINDOW.fullmatch(window_key)
    if match is None:
        raise Eis223IndexConflict("WINDOW_INVALID")
    if match["day"] is not None:
        date.fromisoformat(match["day"])
    if (
        initial.service != "IP"
        or initial.kind != ("BY_NUMBER" if match["number"] else "BY_REGION")
        or initial.state != "LINKS_PENDING"
        or initial.source_mode != "PROD"
        or prepared.service != "IP"
        or prepared.kind != "PREPARED"
        or prepared.state != "READY"
        or prepared.source_mode != "PROD"
        or initial.request_id != prepared.doc_request_uid
    ):
        raise Eis223IndexConflict("SOURCE_BINDING_INVALID")
    initial_uids = []
    for url in initial.archive_urls:
        validate_eis_archive_url(url, doc_request_uid=initial.request_id)
        initial_uids.append(
            parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower()
        )
    references = prepared.prepared_archives
    reference_uids = [reference.archive_uid for reference in references]
    reference_urls = [reference.url for reference in references]
    if (
        not initial_uids
        or not references
        or len(set(initial_uids)) != len(initial_uids)
        or len(set(reference_uids)) != len(reference_uids)
        or len(set(reference_urls)) != len(reference_urls)
        or set(initial_uids) != set(reference_uids)
        or set(downloaded) != set(reference_urls)
    ):
        raise Eis223IndexConflict("ARCHIVE_SET_MISMATCH")
    if len(initial_uids) > MAX_NOTICE_ARCHIVES:
        raise Eis223IndexConflict("ARCHIVE_COUNT_LIMIT")
    by_uid = {r.archive_uid: r.url for r in references}
    for uid, url in by_uid.items():
        validate_eis_archive_url(url, doc_request_uid=initial.request_id)
        if parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower() != uid:
            raise Eis223IndexConflict("ARCHIVE_UID_MISMATCH")
    urls = tuple(by_uid[uid] for uid in initial_uids)
    return Eis223ReadyWindow(
        window_key=window_key,
        response_sha256=initial.source_sha256,
        prepared_sha256=prepared.source_sha256,
        archive_urls=urls,
        archives=tuple(downloaded[url] for url in urls),
    )


def preflight_notice223_window(
    company: str, window: Eis223ReadyWindow
) -> tuple[tuple[Eis223ArchiveInspection, ...], str]:
    match = _WINDOW.fullmatch(window.window_key)
    if match is None or len(window.archives) != len(window.archive_urls):
        raise Eis223IndexConflict("WINDOW_INVALID")
    if match["day"] is not None:
        date.fromisoformat(match["day"])
    if sum(len(a) for a in window.archives) > MAX_NOTICE_COMPRESSED_BYTES:
        raise Eis223IndexConflict("WINDOW_BYTES_LIMIT")
    if len(set(window.archive_urls)) != len(window.archive_urls):
        raise Eis223IndexConflict("ARCHIVE_URL_DUPLICATE")
    for url in window.archive_urls:
        validate_eis_archive_url(url)
    expanded_bytes = 0
    member_count = 0
    try:
        for raw in window.archives:
            if len(raw) > MAX_ARCHIVE_BYTES:
                raise Eis223IndexConflict("ARCHIVE_RESOURCE_LIMIT")
            with ZipFile(BytesIO(raw)) as bundle:
                members = bundle.infolist()
                archive_expanded = sum(member.file_size for member in members)
                if (
                    len(members) > MAX_ARCHIVE_MEMBERS
                    or archive_expanded > MAX_ARCHIVE_EXPANDED_BYTES
                    or any(member.file_size > MAX_XML_BYTES for member in members)
                ):
                    raise Eis223IndexConflict("ARCHIVE_RESOURCE_LIMIT")
                member_count += len(members)
                expanded_bytes += archive_expanded
                if member_count > MAX_NOTICE_MEMBERS:
                    raise Eis223IndexConflict("WINDOW_MEMBER_LIMIT")
                if expanded_bytes > MAX_NOTICE_EXPANDED_BYTES:
                    raise Eis223IndexConflict("WINDOW_EXPANDED_LIMIT")
    except BadZipFile as exc:
        raise Eis223IndexConflict("ARCHIVE_INVALID") from exc
    inspections = tuple(
        inspect_notice223_archive(
            a,
            company_id=company,
            source_response_sha256=window.response_sha256,
            source_locator=window.window_key,
            document_type=match["family"] or match["target_family"],
        )
        for a in window.archives
    )
    if len({a.archive_sha256 for a in inspections}) != len(inspections):
        raise Eis223IndexConflict("ARCHIVE_DIGEST_DUPLICATE")
    identities = set()
    for archive in inspections:
        for notice in archive.records:
            if match["number"] is not None and notice.purchase_number != match["number"]:
                raise Eis223IndexConflict("BY_NUMBER_PURCHASE_MISMATCH")
            key = (notice.purchase_number, notice.version_number)
            if key in identities:
                raise Eis223IndexConflict("NOTICE_VERSION_DUPLICATE")
            identities.add(key)
    manifest = [
        {"sha256": a.archive_sha256, "url": url, "records": len(a.records)}
        for a, url in zip(inspections, window.archive_urls, strict=True)
    ]
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return inspections, digest


def _notice_keys(notice: Eis223NoticeSnapshot) -> list[str]:
    values = [notice.title.value or ""]
    for lot in notice.lots:
        values.append(lot.subject.value or "")
        values.extend(item.description.value or "" for item in lot.items)
    return sorted({k for value in values for k in search_keys_v1(value)})


def ingest_notice223_window(
    storage: PostgresStorage,
    company: str,
    window: Eis223ReadyWindow,
    *,
    actor_id: str,
    now: datetime | None = None,
) -> Eis223IngestReport:
    inspections, manifest = preflight_notice223_window(company, window)
    at = now or datetime.now(UTC)
    if not actor_id.strip() or at.tzinfo is None or at.utcoffset() is None:
        raise Eis223IndexConflict("ACTOR_OR_TIME_INVALID")
    count = sum(len(a.records) for a in inspections)
    with storage.transaction(company) as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "eis223:" + company},
        )
        predicate = and_(
            eis_223_windows.c.company_id == company,
            eis_223_windows.c.window_key == window.window_key,
            eis_223_windows.c.response_sha256 == window.response_sha256,
        )
        existing = connection.execute(select(eis_223_windows).where(predicate)).mappings().first()
        if existing:
            if existing["manifest_sha256"] != manifest or existing["record_count"] != count:
                raise Eis223IndexConflict("WINDOW_REPLAY_CONFLICT")
            return Eis223IngestReport(
                window_key=window.window_key,
                archive_count=len(inspections),
                record_count=count,
                new_versions=0,
                replayed=True,
            )
        connection.execute(
            insert(eis_223_windows).values(
                company_id=company,
                window_key=window.window_key,
                response_sha256=window.response_sha256,
                prepared_sha256=window.prepared_sha256,
                manifest_sha256=manifest,
                archive_count=len(inspections),
                record_count=count,
                ingested_at=at,
            )
        )
        new = 0
        for inspection, content, url in zip(
            inspections, window.archives, window.archive_urls, strict=True
        ):
            old_blob = connection.execute(
                select(eis_223_blobs.c.archive_sha256).where(
                    eis_223_blobs.c.company_id == company,
                    eis_223_blobs.c.archive_sha256 == inspection.archive_sha256,
                )
            ).scalar_one_or_none()
            if old_blob is None:
                connection.execute(
                    insert(eis_223_blobs).values(
                        company_id=company,
                        archive_sha256=inspection.archive_sha256,
                        content=content,
                    )
                )
            connection.execute(
                insert(eis_223_archive_sources).values(
                    company_id=company,
                    window_key=window.window_key,
                    response_sha256=window.response_sha256,
                    archive_sha256=inspection.archive_sha256,
                    source_url=url,
                )
            )
            for notice in inspection.records:
                old = connection.execute(
                    select(eis_223_notice_versions.c.xml_sha256).where(
                        eis_223_notice_versions.c.company_id == company,
                        eis_223_notice_versions.c.purchase_number == notice.purchase_number,
                        eis_223_notice_versions.c.version_number == notice.version_number,
                    )
                ).scalar_one_or_none()
                if old == notice.xml_sha256:
                    continue
                if old is not None:
                    raise Eis223IndexConflict("NOTICE_VERSION_CONFLICT")
                connection.execute(
                    insert(eis_223_notice_versions).values(
                        company_id=company,
                        purchase_number=notice.purchase_number,
                        version_number=notice.version_number,
                        xml_sha256=notice.xml_sha256,
                        window_key=window.window_key,
                        response_sha256=window.response_sha256,
                        archive_sha256=inspection.archive_sha256,
                        snapshot=notice.model_dump(mode="json"),
                        search_keys=_notice_keys(notice),
                        ingested_at=at,
                    )
                )
                new += 1
        connection.execute(
            insert(audit_events).values(
                event_id=str(uuid4()),
                company_id=company,
                actor_id=actor_id,
                event_type="EIS_223_WINDOW_INGESTED",
                object_type="EIS_223_SOURCE_WINDOW",
                object_id=window.window_key,
                object_version=None,
                basis={
                    "response_sha256": window.response_sha256,
                    "prepared_sha256": window.prepared_sha256,
                    "manifest_sha256": manifest,
                    "archive_count": len(inspections),
                    "record_count": count,
                    "new_versions": new,
                    "coverage": "UNKNOWN",
                    "law": "223",
                    "document_type": inspections[0].records[0].document_type,
                },
                occurred_at=at,
            )
        )
    return Eis223IngestReport(
        window_key=window.window_key,
        archive_count=len(inspections),
        record_count=count,
        new_versions=new,
        replayed=False,
    )


def compare_notice223(
    notice: Eis223NoticeSnapshot,
    query: str,
    *,
    now: datetime,
    source_window: str,
    source_response_sha256: str,
    archive_sha256: str,
) -> Eis223SearchLead | None:
    query = query.strip()
    number = exact_purchase_number(query)
    terms = search_query_terms(query)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if number is not None and notice.purchase_number != number:
        return None
    evidence = (
        (
            EisSearchTermEvidence(
                number,
                notice.identity_provenance[0].locator,
                notice.purchase_number,
                "PURCHASE_NUMBER",
            ),
        )
        if number is not None
        else match_search_terms(
            ((notice.title.value or "", notice.title.provenance.locator, "TITLE"),), query
        )
    )
    ordinal = None
    for lot in () if number is not None else notice.lots:
        candidates = [
            match_search_terms(
                ((lot.subject.value or "", lot.subject.provenance.locator, "TITLE"),), query
            )
        ]
        candidates.extend(
            match_search_terms(
                ((item.description.value or "", item.description.provenance.locator, "ITEM_NAME"),),
                query,
            )
            for item in lot.items
        )
        for candidate in candidates:
            if len(candidate) > len(evidence):
                evidence = candidate
                ordinal = lot.ordinal.value
    if not evidence:
        return None
    deadline = deadline223(notice)
    expired = deadline.value is not None and deadline.value <= now
    unavailable = unavailable223(notice)
    reasons = [
        "223-ФЗ: требования, МСП-статус, отмены и полнота комплекта не проверены.",
        "Цены каждого лота и валюта показаны отдельно; прибыль UNKNOWN.",
        (
            "Найден точный регистрационный номер; соответствие ТЗ UNKNOWN."
            if number is not None
            else "Найдены слова в одном заголовке, одном предмете лота или одной позиции; "
            "соответствие ТЗ UNKNOWN."
        ),
    ]
    if expired:
        reasons.append("Срок подачи истёк; кандидат заблокирован.")
    elif deadline.value is None:
        reasons.append("Срок без подтверждённого часового пояса; действующая подача UNKNOWN.")
    else:
        reasons.append("Срок ещё не истёк; текущая стадия и доступность участия UNKNOWN.")
    reasons.extend(unavailable)
    return Eis223SearchLead(
        notice=notice,
        source_window=source_window,
        source_response_sha256=source_response_sha256,
        archive_sha256=archive_sha256,
        match_quality="STRONG" if len(evidence) == len(terms) else "PARTIAL",
        matched_terms=tuple(e.term for e in evidence),
        term_evidence=evidence,
        matched_lot_ordinal=ordinal,
        application_status="FAIL" if expired or unavailable else "UNKNOWN",
        reasons=tuple(reasons),
    )


def search_notice223_index(
    storage: PostgresStorage,
    company: str,
    query: str,
    *,
    now: datetime | None = None,
    paginate: bool = False,
    cursor: str | None = None,
    limit: int = 100,
    on_matches: Callable[[tuple[Eis223SearchLead, ...]], None] | None = None,
) -> Eis223SearchResult:
    query = query.strip()
    number = exact_purchase_number(query)
    search_query_terms(query)
    at = now or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if not 1 <= limit <= 100:
        raise ValueError("SEARCH_PAGE_INVALID")
    pager = (
        SearchPagination(
            company=company, law="223", query=query, scope="ALL_CACHED", now=at, cursor=cursor
        )
        if paginate
        else None
    )
    if cursor is not None and pager is None:
        raise ValueError("SEARCH_PAGE_INVALID")
    if pager is not None:
        at = pager.at
    table = eis_223_notice_versions
    newer = table.alias("newer223")
    current = and_(
        table.c.company_id == company,
        table.c.ingested_at <= at if paginate else true(),
        ~exists(
            select(1).where(
                newer.c.company_id == company,
                newer.c.purchase_number == table.c.purchase_number,
                newer.c.version_number > table.c.version_number,
                newer.c.ingested_at <= at if paginate else true(),
            )
        ),
    )
    with storage.transaction(company, consistent_read=True) as connection:
        total = connection.execute(
            select(func.count()).select_from(table).where(current)
        ).scalar_one()
        windows, last = connection.execute(
            select(func.count(), func.max(eis_223_windows.c.ingested_at)).where(
                eis_223_windows.c.company_id == company
            )
        ).one()
        scan_cursor: str | None = None
        evaluated = matched_count = 0
        reused_count = 0
        matched: list[Eis223SearchLead] = []
        keys = list(search_query_keys_v1(query))
        while True:
            statement = (
                select(table)
                .where(
                    current,
                    table.c.purchase_number == number
                    if number is not None
                    else table.c.search_keys.overlap(keys),
                )
                .order_by(table.c.purchase_number)
                .limit(_SEARCH_BATCH_SIZE)
            )
            if scan_cursor is not None:
                statement = statement.where(table.c.purchase_number > scan_cursor)
            rows = connection.execute(statement).mappings().all()
            if not rows:
                break
            evaluated += len(rows)
            states = read_event223_states(
                connection, company, tuple(r["purchase_number"] for r in rows), now=at
            )
            lot_states = read_lot_event223_states(
                connection, company, tuple(r["purchase_number"] for r in rows), now=at
            )
            batch_leads: list[Eis223SearchLead] = []
            notices = []
            for row in rows:
                notice = Eis223NoticeSnapshot.model_validate(row["snapshot"])
                if (notice.purchase_number, notice.version_number, notice.xml_sha256) != (
                    row["purchase_number"],
                    row["version_number"],
                    row["xml_sha256"],
                ):
                    raise Eis223ContractError("PERSISTED_IDENTITY_MISMATCH")
                notices.append(notice)
            sources = tuple(
                (row["window_key"], row["response_sha256"], row["archive_sha256"]) for row in rows
            )
            if pager is not None:
                base_leads, reused = _compare_page_notices223(
                    company, tuple(notices), query, at, sources
                )
                reused_count += len(rows) if reused else 0
            else:
                base_leads = tuple(
                    compare_notice223(
                        notice,
                        query,
                        now=at,
                        source_window=source[0],
                        source_response_sha256=source[1],
                        archive_sha256=source[2],
                    )
                    for notice, source in zip(notices, sources, strict=True)
                )
            for notice, lead in zip(notices, base_leads, strict=True):
                if lead:
                    state = states[notice.purchase_number]
                    lot_state = lot_states[notice.purchase_number]
                    lead = lead.model_copy(
                        update={
                            "cancellation_state": state,
                            "lot_cancellation_state": lot_state,
                            "application_status": "FAIL"
                            if state.application_status == "FAIL"
                            else lead.application_status,
                            "reasons": lead.reasons
                            + (state.reason_codes if state.operation_hold else ())
                            + (lot_state.reason_codes if lot_state.operation_hold else ()),
                        }
                    )
                    matched_count += 1
                    batch_leads.append(lead)
            if pager is not None or on_matches is not None:
                batch_leads = _with_schema_quality(connection, company, batch_leads)
            if on_matches is not None:
                on_matches(tuple(batch_leads))
            if pager is not None:
                batch_leads = [
                    lead
                    for lead in batch_leads
                    if pager.observe(_search_order(lead), lead.model_dump(mode="json"))
                ]
            matched.extend(batch_leads)
            matched.sort(key=_search_order)
            del matched[limit:]
            scan_cursor = rows[-1]["purchase_number"]
            # The whole query is visited; the response limit never stops comparison.
            if len(rows) < _SEARCH_BATCH_SIZE:
                break
        if pager is None:
            matched = _with_schema_quality(connection, company, matched)
    fingerprint, next_cursor = (
        pager.finish(_search_order(matched[-1]) if matched else None, len(matched))
        if pager is not None
        else (None, None)
    )
    return Eis223SearchResult(
        next_cursor=next_cursor,
        page_snapshot_sha256=fingerprint,
        snapshot_at=at if pager is not None else None,
        query=query,
        checked_at=at,
        indexed_current_notices=total,
        indexed_windows=windows,
        latest_ingested_at=last,
        evaluated_candidates=evaluated,
        compared_candidates=evaluated - reused_count,
        reused_candidates=reused_count,
        matched_count=matched_count,
        matched=tuple(matched),
    )


def _compare_page_notices223(
    company: str,
    notices: tuple[Eis223NoticeSnapshot, ...],
    query: str,
    at: datetime,
    sources: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[Eis223SearchLead | None, ...], bool]:
    key = PAGE_COMPARISONS.key(
        company,
        "223",
        query,
        at,
        json.dumps(sources).encode(),
        chunks=(notice.model_dump_json().encode() for notice in notices),
    )
    cached = PAGE_COMPARISONS.get(key)
    if cached is not None:
        data = json.loads(cached)
        return tuple(
            Eis223SearchLead.model_validate(dict(record, notice=notice)) if record else None
            for record, notice in zip(data, notices, strict=True)
        ), True
    leads = tuple(
        compare_notice223(
            notice,
            query,
            now=at,
            source_window=source[0],
            source_response_sha256=source[1],
            archive_sha256=source[2],
        )
        for notice, source in zip(notices, sources, strict=True)
    )
    PAGE_COMPARISONS.put(
        key,
        json.dumps(
            [lead.model_dump(mode="json", exclude={"notice"}) if lead else None for lead in leads],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode(),
    )
    return leads, False


def _with_schema_quality(
    connection: Connection, company: str, matched: list[Eis223SearchLead]
) -> list[Eis223SearchLead]:
    quality: dict[tuple[str, int, str], list[Eis223SchemaCheck]] = {}
    checks = eis_223_schema_checks
    if matched:
        for record in connection.execute(
            select(checks)
            .where(
                checks.c.company_id == company,
                tuple_(checks.c.purchase_number, checks.c.version_number, checks.c.xml_sha256).in_(
                    [
                        (r.notice.purchase_number, r.notice.version_number, r.notice.xml_sha256)
                        for r in matched
                    ]
                ),
            )
            .order_by(checks.c.schema_release, checks.c.validator_version, checks.c.tree_sha256)
        ).mappings():
            check = Eis223SchemaCheck.model_validate(record["report"])
            identity = (
                record["purchase_number"],
                record["version_number"],
                record["xml_sha256"],
            )
            if identity != (check.purchase_number, check.version_number, check.xml_sha256):
                raise Eis223ContractError("SCHEMA_EVIDENCE_IDENTITY_MISMATCH")
            quality.setdefault(identity, []).append(check)
    for index, lead in enumerate(matched):
        notice = lead.notice
        evidence = tuple(
            quality.get((notice.purchase_number, notice.version_number, notice.xml_sha256), [])
        )
        status = schema_quality(evidence)
        reasons = lead.reasons
        if status == "FAIL":
            reasons += (
                "Исходный XML не проходит полную официальную XSD; сведения требуют"
                " проверки. Это ошибка схемы источника, право участия UNKNOWN.",
            )
        matched[index] = lead.model_copy(
            update={
                "source_schema_status": status,
                "source_schema_checks": evidence,
                "reasons": reasons,
            }
        )
    return matched


def _search_order(lead: Eis223SearchLead) -> tuple[bool, bool, bool, int, str]:
    """Existing preliminary relevance order, independent of prices or schema grade."""
    return (
        lead.application_status == "FAIL",
        bool(
            (lead.cancellation_state and lead.cancellation_state.operation_hold)
            or (lead.lot_cancellation_state and lead.lot_cancellation_state.operation_hold)
        ),
        lead.match_quality != "STRONG",
        -len(lead.matched_terms),
        lead.notice.purchase_number,
    )
