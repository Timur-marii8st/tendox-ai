"""Atomic, tenant-scoped intake of a complete downloaded EIS archive set.

The source's own corpus completeness remains UNKNOWN. A READY response and an
exact archive count only prove that this particular request was downloaded.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit
from zipfile import BadZipFile, ZipFile

from sqlalchemy import and_, insert, select, text

from procurement.sources.eis_feed import EisFeedContractError, validate_eis_archive_url
from procurement.sources.eis_feed_archive import (
    DEFAULT_NOTICE_TYPE,
    SUPPORTED_NOTICE_TYPES,
    EisArchiveInspection,
    EisNoticeSnapshot,
    inspect_eis_auction_archive,
)
from procurement.storage.eis_search_index import insert_search_keys
from procurement.storage.models import (
    audit_events,
    eis_feed_archive_sources,
    eis_feed_archives,
    eis_feed_windows,
    eis_notice_versions,
    eis_procedure_events,
)

if TYPE_CHECKING:
    from procurement.sources.eis_feed import EisFeedResponse
    from procurement.storage.repository import PostgresStorage

_WINDOW = re.compile(
    r"^getDocsIP/PRIZ/(?:[0-9]{1,2}/[0-9]{4}-[0-9]{2}-[0-9]{2}(?:/[0-9]{2})?[+-][0-9]{2}:[0-9]{2}(?:/(?:epNotificationEZK2020|epNotificationEOK2020|epNotificationCancel|epNotificationCancelFailure))?|by-number/[0-9]{19,23})$"
)
_BY_NUMBER = re.compile(r"^getDocsIP/PRIZ/by-number/(?P<number>[0-9]{19,23})$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_WINDOW_ARCHIVES = 20
MAX_WINDOW_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_WINDOW_EXPANDED_BYTES = 320 * 1024 * 1024


class EisIndexConflict(ValueError):
    """The source window or notice version has contradictory bytes."""


@dataclass(frozen=True)
class EisReadyWindow:
    window_key: str
    response_sha256: str
    expected_archive_count: int
    archives: tuple[bytes, ...]
    prepared_response_sha256: str | None = None
    archive_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class EisWindowPreflight:
    inspections: tuple[EisArchiveInspection, ...]
    manifest_sha256: str
    notice_count: int
    coverage: str = "UNKNOWN"


@dataclass(frozen=True)
class EisIngestReport:
    window_key: str
    archive_count: int
    notice_count: int
    new_versions: int
    replayed: bool
    coverage: str = "UNKNOWN"
    new_events: int = 0


def has_ingested_window(storage: PostgresStorage, company_id: str, window_key: str) -> bool:
    """A successful exact window is a checkpoint for ordinary backfill runs."""
    if not company_id.strip() or not _WINDOW.fullmatch(window_key):
        raise ValueError("TENANT_OR_WINDOW_INVALID")
    with storage.transaction(company_id) as connection:
        return (
            connection.execute(
                select(eis_feed_windows.c.window_key)
                .where(
                    and_(
                        eis_feed_windows.c.company_id == company_id,
                        eis_feed_windows.c.window_key == window_key,
                        eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
                    )
                )
                .limit(1)
            ).first()
            is not None
        )


def bind_ready_window(
    window_key: str,
    initial: EisFeedResponse,
    prepared: EisFeedResponse,
    downloaded: dict[str, bytes],
) -> EisReadyWindow:
    """Bind exact downloaded URLs to one prepared official IP request."""
    by_number = _BY_NUMBER.fullmatch(window_key) is not None
    if (
        initial.service != "IP"
        or initial.kind != ("BY_NUMBER" if by_number else "BY_REGION")
        or initial.state != "LINKS_PENDING"
        or initial.source_mode != "PROD"
        or prepared.service != "IP"
        or prepared.kind != "PREPARED"
        or prepared.state != "READY"
        or prepared.source_mode != "PROD"
        or not initial.archive_urls
        or initial.request_id != prepared.doc_request_uid
        or not _WINDOW.fullmatch(window_key)
    ):
        raise EisIndexConflict("SOURCE_NOT_READY_OR_MISMATCHED")
    initial_uids = tuple(
        parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower()
        for url in initial.archive_urls
    )
    prepared_by_uid = {
        item.archive_uid: item.url
        for item in (*prepared.prepared_archives, *prepared.not_downloaded_archives)
    }
    if (
        len(set(initial_uids)) != len(initial_uids)
        or set(initial_uids) != set(prepared_by_uid)
        or set(downloaded) != set(prepared_by_uid.values())
    ):
        raise EisIndexConflict("ARCHIVE_URL_SET_MISMATCH")
    return EisReadyWindow(
        window_key=window_key,
        response_sha256=initial.source_sha256,
        expected_archive_count=len(initial.archive_urls),
        archives=tuple(downloaded[prepared_by_uid[uid]] for uid in initial_uids),
        prepared_response_sha256=prepared.source_sha256,
        archive_urls=tuple(prepared_by_uid[uid] for uid in initial_uids),
    )


def preflight_ready_window(window: EisReadyWindow) -> EisWindowPreflight:
    """Reject a partial response before opening a database transaction."""
    if not _WINDOW.fullmatch(window.window_key) or not _SHA.fullmatch(window.response_sha256):
        raise EisIndexConflict("SOURCE_COORDINATES_INVALID")
    if not 1 <= window.expected_archive_count <= MAX_WINDOW_ARCHIVES:
        raise EisIndexConflict("ARCHIVE_COUNT_INVALID")
    if len(window.archives) != window.expected_archive_count:
        raise EisIndexConflict("ARCHIVE_SET_INCOMPLETE")
    if sum(len(content) for content in window.archives) > MAX_WINDOW_COMPRESSED_BYTES:
        raise EisIndexConflict("ARCHIVE_WINDOW_SIZE_LIMIT")
    expanded_bytes = 0
    try:
        for content in window.archives:
            with ZipFile(BytesIO(content)) as archive:
                expanded_bytes += sum(info.file_size for info in archive.infolist())
            if expanded_bytes > MAX_WINDOW_EXPANDED_BYTES:
                raise EisIndexConflict("ARCHIVE_WINDOW_EXPANSION_LIMIT")
    except BadZipFile as error:
        raise EisIndexConflict("ARCHIVE_INVALID") from error
    if bool(window.prepared_response_sha256) != bool(window.archive_urls):
        raise EisIndexConflict("ARCHIVE_PROVENANCE_INCOMPLETE")
    if window.archive_urls:
        if (
            len(window.archive_urls) != window.expected_archive_count
            or window.prepared_response_sha256 is None
            or not _SHA.fullmatch(window.prepared_response_sha256)
        ):
            raise EisIndexConflict("ARCHIVE_PROVENANCE_INVALID")
        try:
            first_request_id = parse_qs(urlsplit(window.archive_urls[0]).query)["docRequestUid"][0]
            urls = tuple(
                validate_eis_archive_url(url, doc_request_uid=first_request_id)
                for url in window.archive_urls
            )
        except (EisFeedContractError, KeyError, IndexError) as error:
            raise EisIndexConflict("ARCHIVE_PROVENANCE_INVALID") from error
        if len(set(urls)) != len(urls):
            raise EisIndexConflict("ARCHIVE_PROVENANCE_INVALID")
    number_match = _BY_NUMBER.fullmatch(window.window_key)
    inspections = tuple(
        inspect_eis_auction_archive(
            content,
            source_locator=window.window_key,
            source_response_sha256=window.response_sha256,
            expected_document_type=(
                None
                if number_match is not None
                else window.window_key.rsplit("/", 1)[-1]
                if window.window_key.rsplit("/", 1)[-1] in SUPPORTED_NOTICE_TYPES
                else DEFAULT_NOTICE_TYPE
            ),
            allow_companion_documents=number_match is not None,
        )
        for content in window.archives
    )
    hashes = [item.archive_sha256 for item in inspections]
    if len(set(hashes)) != len(hashes):
        raise EisIndexConflict("DUPLICATE_ARCHIVE")
    seen: dict[tuple[str, int], str] = {}
    seen_events: set[tuple[str, str]] = set()
    for inspection in inspections:
        for notice in inspection.records:
            if number_match is not None and notice.purchase_number != number_match.group("number"):
                raise EisIndexConflict("BY_NUMBER_PURCHASE_MISMATCH")
            key = notice.purchase_number, notice.version_number
            if key in seen:
                raise EisIndexConflict("DUPLICATE_NOTICE_VERSION_IN_WINDOW")
            seen[key] = notice.xml_sha256
        for event in inspection.events:
            if number_match is not None and event.purchase_number != number_match.group("number"):
                raise EisIndexConflict("BY_NUMBER_PURCHASE_MISMATCH")
            event_key = event.document_type, event.document_id
            if event_key in seen_events:
                raise EisIndexConflict("DUPLICATE_PROCEDURE_EVENT_IN_WINDOW")
            seen_events.add(event_key)
    if number_match is not None and not seen and not seen_events:
        raise EisIndexConflict("BY_NUMBER_EMPTY_ARCHIVES")
    manifest = hashlib.sha256(
        json.dumps(sorted(hashes), separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return EisWindowPreflight(
        inspections=inspections,
        manifest_sha256=manifest,
        notice_count=len(seen) + len(seen_events),
    )


def _notice_values(
    tenant: str,
    window: EisReadyWindow,
    inspection: EisArchiveInspection,
    notice: EisNoticeSnapshot,
    ingested_at: datetime,
) -> dict[str, object]:
    def json_value(value: object) -> object:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_value(item) for item in value]
        return value

    return {
        "company_id": tenant,
        "purchase_number": notice.purchase_number,
        "version_number": notice.version_number,
        "xml_sha256": notice.xml_sha256,
        "window_key": window.window_key,
        "response_sha256": window.response_sha256,
        "archive_sha256": inspection.archive_sha256,
        "source_member": notice.source_member,
        "document_type": notice.document_type,
        "title": notice.title,
        "published_at": notice.published_at,
        "deadline": notice.deadline,
        "nmck_rub": notice.nmck_rub,
        "lot_parse_status": notice.lot_parse_status,
        "lot_items": json_value([asdict(item) for item in notice.lot_items]),
        "attachments": json_value([asdict(item) for item in notice.attachments]),
        "ingested_at": ingested_at,
    }


def ingest_ready_window(
    storage: PostgresStorage,
    company_id: str,
    window: EisReadyWindow,
    *,
    actor_id: str,
    received_at: datetime | None = None,
) -> EisIngestReport:
    """Insert the exact archive set and all notice versions or roll it all back."""
    if not company_id.strip() or not actor_id.strip():
        raise ValueError("TENANT_OR_ACTOR_MISSING")
    ingested_at = received_at or datetime.now(UTC)
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError("RECEIVED_AT_TIMEZONE_MISSING")
    preflight = preflight_ready_window(window)
    with storage.transaction(company_id) as connection:
        # The same window cannot be admitted in parallel with a conflicting
        # manifest. The lock is scoped to this transaction and tenant.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company_id},
        )
        existing_window = (
            connection.execute(
                select(eis_feed_windows).where(
                    and_(
                        eis_feed_windows.c.company_id == company_id,
                        eis_feed_windows.c.window_key == window.window_key,
                        eis_feed_windows.c.response_sha256 == window.response_sha256,
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing_window is not None:
            if existing_window["intake_kind"] != "LEGACY_CANONICAL":
                raise EisIndexConflict("TRANSPORT_WINDOW_NOT_CANONICAL")
            if (
                existing_window["manifest_sha256"] != preflight.manifest_sha256
                or existing_window["archive_count"] != len(window.archives)
                or existing_window["notice_count"] != preflight.notice_count
            ):
                raise EisIndexConflict("WINDOW_REPLAY_CONFLICT")
            return EisIngestReport(
                window_key=window.window_key,
                archive_count=len(window.archives),
                notice_count=preflight.notice_count,
                new_versions=0,
                replayed=True,
            )
        connection.execute(
            insert(eis_feed_windows).values(
                company_id=company_id,
                window_key=window.window_key,
                response_sha256=window.response_sha256,
                manifest_sha256=preflight.manifest_sha256,
                archive_count=len(window.archives),
                notice_count=preflight.notice_count,
                coverage="UNKNOWN",
                ingested_at=ingested_at,
            )
        )
        new_versions = 0
        new_events = 0
        for archive_index, (content, inspection) in enumerate(
            zip(window.archives, preflight.inspections, strict=True)
        ):
            connection.execute(
                insert(eis_feed_archives).values(
                    company_id=company_id,
                    window_key=window.window_key,
                    response_sha256=window.response_sha256,
                    archive_sha256=inspection.archive_sha256,
                    content=content,
                    record_count=len(inspection.records) + len(inspection.events),
                )
            )
            if window.prepared_response_sha256 is not None:
                connection.execute(
                    insert(eis_feed_archive_sources).values(
                        company_id=company_id,
                        window_key=window.window_key,
                        response_sha256=window.response_sha256,
                        archive_sha256=inspection.archive_sha256,
                        prepared_response_sha256=window.prepared_response_sha256,
                        source_url=window.archive_urls[archive_index],
                        received_at=ingested_at,
                    )
                )
            for notice in inspection.records:
                existing_notice = connection.execute(
                    select(eis_notice_versions.c.xml_sha256).where(
                        and_(
                            eis_notice_versions.c.company_id == company_id,
                            eis_notice_versions.c.purchase_number == notice.purchase_number,
                            eis_notice_versions.c.version_number == notice.version_number,
                        )
                    )
                ).scalar_one_or_none()
                if existing_notice == notice.xml_sha256:
                    continue
                if existing_notice is not None:
                    raise EisIndexConflict("NOTICE_VERSION_CONFLICT")
                connection.execute(
                    insert(eis_notice_versions).values(
                        **_notice_values(company_id, window, inspection, notice, ingested_at)
                    )
                )
                insert_search_keys(
                    connection,
                    company_id,
                    notice.purchase_number,
                    notice.version_number,
                    notice.title,
                    (item.name for item in notice.lot_items),
                )
                from procurement.storage.eis_position_projection import derive_new_drug_positions

                derive_new_drug_positions(
                    connection, company_id, notice, content, actor_id=actor_id
                )
                new_versions += 1
            for event in inspection.events:
                existing_event = connection.execute(
                    select(eis_procedure_events.c.xml_sha256).where(
                        and_(
                            eis_procedure_events.c.company_id == company_id,
                            eis_procedure_events.c.document_type == event.document_type,
                            eis_procedure_events.c.document_id == event.document_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing_event == event.xml_sha256:
                    continue
                if existing_event is not None:
                    raise EisIndexConflict("PROCEDURE_EVENT_CONFLICT")
                connection.execute(
                    insert(eis_procedure_events).values(
                        **asdict(event),
                        company_id=company_id,
                        window_key=window.window_key,
                        response_sha256=window.response_sha256,
                        archive_sha256=inspection.archive_sha256,
                        ingested_at=ingested_at,
                    )
                )
                new_events += 1
        connection.execute(
            insert(audit_events).values(
                event_id=str(uuid.uuid4()),
                company_id=company_id,
                actor_id=actor_id,
                event_type="EIS_WINDOW_INGESTED",
                object_type="EIS_SOURCE_WINDOW",
                object_id=window.window_key,
                object_version=None,
                basis={
                    "response_sha256": window.response_sha256,
                    "manifest_sha256": preflight.manifest_sha256,
                    "archive_count": len(window.archives),
                    "notice_count": preflight.notice_count,
                    "new_versions": new_versions,
                    "new_events": new_events,
                    "prepared_response_sha256": window.prepared_response_sha256,
                    "coverage": "UNKNOWN",
                },
                occurred_at=ingested_at,
            )
        )
    return EisIngestReport(
        window_key=window.window_key,
        archive_count=len(window.archives),
        notice_count=preflight.notice_count,
        new_versions=new_versions,
        replayed=False,
        new_events=new_events,
    )
