"""Read exact tenant archive/member, including notices indexed before navigation existed."""

from __future__ import annotations

import hashlib
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import TypeAdapter
from sqlalchemy import Integer, and_, case, column, func, select, tuple_, values
from sqlalchemy.engine import Connection

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_223_regions import RegionCatalog, inspect_region_catalog
from procurement.sources.eis_feed_archive import EisNoticeSnapshot
from procurement.sources.tender_navigation import (
    TenderNavigation,
    bind_gar_regions,
    extract_navigation,
)
from procurement.storage.eis_document_store import NoticeDocumentRef, load_notice
from procurement.storage.eis_mixed_comparison import MixedNoticeRef
from procurement.storage.eis_notice_hold import notice_variant_hold_clause
from procurement.storage.models import (
    eis_223_blobs,
    eis_223_notice_versions,
    eis_223_region_catalogs,
    eis_feed_archives,
    eis_notice_versions,
)
from procurement.storage.repository import PostgresStorage

_NOTICE_SNAPSHOT_ADAPTER = TypeAdapter(EisNoticeSnapshot)
NAVIGATION_BATCH_BYTES = 16 * 1024**2
_ARCHIVE_LIMIT = 50 * 1024**2


@dataclass
class NavigationReadCache:
    """One verified archive per read-only search; no cross-request evidence cache."""

    archive_key: tuple[str, ...] | None = None
    catalog_loaded: bool = False
    catalog: RegionCatalog | None = None
    sources: dict[tuple[str, str, int, str], dict[str, Any]] | None = None
    company: str | None = None
    connection: Connection | None = None
    _reader: ZipFile | None = field(default=None, init=False, repr=False)
    _buffer: BytesIO | None = field(default=None, init=False, repr=False)
    _members: dict[str, ZipInfo | None] = field(default_factory=dict, init=False, repr=False)

    def __enter__(self) -> NavigationReadCache:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def bind(self, company: str, connection: Connection) -> None:
        """Bind evidence to exactly one tenant and read transaction."""
        if self.company is not None and (
            self.company != company or self.connection is not connection
        ):
            raise ValueError("NAVIGATION_CACHE_CONTEXT")
        self.company, self.connection = company, connection

    def close_archive(self) -> None:
        """Release the previous archive before loading its replacement."""
        try:
            if self._reader is not None:
                self._reader.close()
        finally:
            self._reader = None
            if self._buffer is not None:
                self._buffer.close()
            self._buffer = None
            self._members.clear()
            self.archive_key = None

    def close(self) -> None:
        """Release all request-local source data, including on query failure."""
        try:
            self.close_archive()
        finally:
            self.catalog = None
            self.catalog_loaded = False
            self.sources = None
            self.company = None
            self.connection = None

    def open_archive(self, key: tuple[str, ...], raw: bytes) -> None:
        """Index one already hash-verified archive; duplicate names stay unusable."""
        self.close_archive()
        self._buffer = BytesIO(raw)
        try:
            self._reader = ZipFile(self._buffer)
            for member in self._reader.infolist():
                self._members[member.filename] = (
                    None if member.filename in self._members else member
                )
            self.archive_key = key
        except BaseException:
            self.close_archive()
            raise

    def read_member(self, name: str) -> bytes:
        """Read only one unambiguous, bounded member from the verified archive."""
        member = self._members.get(name)
        if member is None or member.is_dir() or member.file_size > 32 * 1024**2:
            raise ValueError("NAVIGATION_MEMBER_LIMIT")
        if self._reader is None:
            raise ValueError("NAVIGATION_ARCHIVE_INVALID")
        with self._reader.open(member) as stream:
            xml = stream.read(32 * 1024**2 + 1)
        if len(xml) != member.file_size:
            raise ValueError("NAVIGATION_MEMBER_SIZE")
        return xml


def read_navigation(
    storage: PostgresStorage,
    company: str,
    ref: MixedNoticeRef,
    *,
    cache: NavigationReadCache | None = None,
) -> TenderNavigation:
    """No network or writes; tenant/identity/hash/size checks precede parsing."""
    if cache is None:
        with NavigationReadCache() as local_cache:
            return read_navigation(storage, company, ref, cache=local_cache)
    with storage.transaction(company, consistent_read=True) as conn:
        cache.bind(company, conn)
        n = eis_notice_versions if ref.law == "44" else eis_223_notice_versions
        if cache.sources is not None:
            source = cache.sources.get(
                (ref.law, ref.purchase_number, ref.version_number, ref.notice_xml_sha256)
            )
        else:
            if ref.law == "44":
                load_notice(conn, company, NoticeDocumentRef(**ref.model_dump(exclude={"law"})))
            else:
                # 223 identity checked below; navigation is not submission eligibility.
                pass
            source_row = (
                conn.execute(
                    select(n).where(
                        n.c.company_id == company,
                        n.c.purchase_number == ref.purchase_number,
                        n.c.version_number == ref.version_number,
                        n.c.xml_sha256 == ref.notice_xml_sha256,
                    )
                )
                .mappings()
                .first()
            )
            source = dict(source_row) if source_row is not None else None
        if source is None:
            raise LookupError("NAVIGATION_NOTICE_NOT_FOUND")
        if ref.law == "223":
            snapshot = Eis223NoticeSnapshot.model_validate(source["snapshot"])
            if (snapshot.purchase_number, snapshot.version_number, snapshot.xml_sha256) != (
                ref.purchase_number,
                ref.version_number,
                ref.notice_xml_sha256,
            ):
                raise ValueError("NAVIGATION_SNAPSHOT_IDENTITY")
            source_member = snapshot.source_member
        else:
            source_member = source["source_member"]
        if ref.law == "44":
            a = eis_feed_archives
            identity = and_(
                a.c.company_id == company,
                a.c.window_key == source["window_key"],
                a.c.response_sha256 == source["response_sha256"],
                a.c.archive_sha256 == source["archive_sha256"],
            )
        else:
            a = eis_223_blobs
            identity = and_(
                a.c.company_id == company, a.c.archive_sha256 == source["archive_sha256"]
            )
        # Include the complete archive binding: a digest alone cannot prove an origin.
        cache_key = (company, ref.law, source["archive_sha256"]) + (
            (source["window_key"], source["response_sha256"]) if ref.law == "44" else ()
        )
        if cache.archive_key != cache_key:
            cache.close_archive()
            size_expression = func.octet_length(a.c.content)
            archive_row = conn.execute(
                select(
                    size_expression,
                    case((size_expression <= 50 * 1024**2, a.c.content), else_=None),
                ).where(identity)
            ).first()
            if archive_row is None:
                raise LookupError("NAVIGATION_ARCHIVE_NOT_FOUND")
            size, content = archive_row
            if size is None or size > 50 * 1024**2:
                raise ValueError("NAVIGATION_ARCHIVE_LIMIT")
            if content is None:
                raise LookupError("NAVIGATION_ARCHIVE_NOT_FOUND")
            raw = bytes(content)
            if hashlib.sha256(raw).hexdigest() != source["archive_sha256"]:
                raise ValueError("NAVIGATION_ARCHIVE_DIGEST")
            try:
                cache.open_archive(cache_key, raw)
            except (BadZipFile, RuntimeError) as error:
                raise ValueError("NAVIGATION_ARCHIVE_INVALID") from error
    try:
        xml = cache.read_member(source_member)
    except (BadZipFile, RuntimeError) as error:
        raise ValueError("NAVIGATION_ARCHIVE_INVALID") from error
    navigation = extract_navigation(
        xml,
        law=ref.law,
        number=ref.purchase_number,
        version=ref.version_number,
        xml_sha256=ref.notice_xml_sha256,
    )

    if navigation.delivery_addresses and cache is not None and cache.catalog_loaded:
        return bind_gar_regions(navigation, cache.catalog) if cache.catalog else navigation
    if navigation.delivery_addresses:
        c = eis_223_region_catalogs
        with storage.transaction(company, consistent_read=True) as conn:
            row = (
                conn.execute(
                    select(c)
                    .where(c.c.company_id == company, func.octet_length(c.c.content) <= 8 * 1024**2)
                    .order_by(c.c.observed_at.desc(), c.c.catalog_sha256)
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is not None:
            catalog = inspect_region_catalog(
                bytes(row["content"]),
                source_url=row["source_url"],
                response_sha256=row["response_sha256"],
                observed_at=row["observed_at"],
            )
            if catalog.catalog_sha256 != row["catalog_sha256"] or catalog.regions != row["regions"]:
                raise ValueError("NAVIGATION_REGION_CATALOG_MISMATCH")
            navigation = bind_gar_regions(navigation, catalog)
            if cache is not None:
                cache.catalog = catalog
        if cache is not None:
            cache.catalog_loaded = True
    return navigation


def prime_navigation_cache(
    storage: PostgresStorage,
    company: str,
    refs: Sequence[MixedNoticeRef],
    cache: NavigationReadCache,
) -> None:
    """Validate a bounded source batch with the unchanged live hold predicate."""
    if len(refs) > 500:
        raise ValueError("NAVIGATION_BATCH_LIMIT")
    with storage.transaction(company, consistent_read=True) as conn:
        cache.bind(company, conn)
        cache.sources = {}
        for law in ("44", "223"):
            selected = [r for r in refs if r.law == law]
            if not selected:
                continue
            n = eis_notice_versions if law == "44" else eis_223_notice_versions
            identities = [
                (r.purchase_number, r.version_number, r.notice_xml_sha256) for r in selected
            ]
            identity = and_(
                n.c.company_id == company,
                tuple_(n.c.purchase_number, n.c.version_number, n.c.xml_sha256).in_(identities),
            )
            statement = select(n).where(identity)
            if law == "44":
                scope = (
                    select(n.c.company_id, n.c.purchase_number, n.c.version_number)
                    .where(identity)
                    .cte("navigation_source_scope")
                    .prefix_with("MATERIALIZED", dialect="postgresql")
                )
                statement = statement.where(
                    ~notice_variant_hold_clause(
                        company, n.c.purchase_number, n.c.version_number, _resolution_scope=scope
                    )
                )
            for row in conn.execute(statement).mappings():
                if law == "44":
                    snapshot = _NOTICE_SNAPSHOT_ADAPTER.validate_python(
                        {key: row[key] for key in EisNoticeSnapshot.__dataclass_fields__}
                    )
                    if snapshot.xml_sha256 != row["xml_sha256"]:
                        raise ValueError("NAVIGATION_SNAPSHOT_IDENTITY")
                cache.sources[
                    (law, row["purchase_number"], row["version_number"], row["xml_sha256"])
                ] = dict(row)


def _archive_key(company: str, law: str, source: Mapping[str, Any]) -> tuple[str, ...]:
    return (company, law, source["archive_sha256"]) + (
        (source["window_key"], source["response_sha256"]) if law == "44" else ()
    )


def _archive_rows(conn: Connection, statement: Any) -> list[Any]:
    result = conn.execute(statement)
    try:
        return list(result.mappings().all())
    finally:
        result.close()


def read_navigation_batch(
    storage: PostgresStorage,
    company: str,
    refs: Sequence[MixedNoticeRef],
    cache: NavigationReadCache,
) -> Generator[TenderNavigation | None, None, None]:
    """Read primed origins in bounded byte batches without changing reference order.

    One active ZIP plus a 16MiB transient SQL buffer is retained. An archive above
    that buffer budget is fetched alone under the existing 50MiB source cap.
    Missing, ambiguous or corrupt evidence yields UNKNOWN navigation for its ref.
    """
    if len(refs) > 500:
        raise ValueError("NAVIGATION_BATCH_LIMIT")
    if not refs:
        return
    law = refs[0].law
    if any(ref.law != law for ref in refs):
        raise ValueError("NAVIGATION_BATCH_LAW")
    with storage.transaction(company, consistent_read=True) as conn:
        cache.bind(company, conn)
        if cache.sources is None:
            raise ValueError("NAVIGATION_BATCH_NOT_PRIMED")
        origins = []
        for ref in refs:
            source = cache.sources.get(
                (law, ref.purchase_number, ref.version_number, ref.notice_xml_sha256)
            )
            origins.append(_archive_key(company, law, source) if source is not None else None)
        requested = {key for key in origins if key is not None}
        a = eis_feed_archives if law == "44" else eis_223_blobs
        names = (
            ("archive_sha256", "window_key", "response_sha256")
            if law == "44"
            else ("archive_sha256",)
        )
        columns = [a.c[name] for name in names]
        size = func.octet_length(a.c.content)
        sizes: dict[tuple[str, ...], int | None] = {}
        if requested:
            metadata = _archive_rows(
                conn,
                select(a.c.company_id, *columns, size.label("bytes")).where(
                    a.c.company_id == company,
                    tuple_(*columns).in_([key[2:] for key in sorted(requested)]),
                ),
            )
            for row in metadata:
                key = _archive_key(row["company_id"], law, row)
                if key not in requested:
                    continue
                amount = row["bytes"]
                sizes[key] = (
                    amount
                    if key not in sizes
                    and isinstance(amount, int)
                    and not isinstance(amount, bool)
                    and 0 <= amount <= _ARCHIVE_LIMIT
                    else None
                )

        blobs: dict[tuple[str, ...], bytes | None] = {}
        try:
            start = 0
            while start < len(refs):
                end, used = start, 0
                chunk: dict[tuple[str, ...], int] = {}
                while end < len(refs):
                    key = origins[end]
                    amount = sizes.get(key) if key is not None else None
                    if amount is not None and key not in chunk:
                        if chunk and used + amount > NAVIGATION_BATCH_BYTES:
                            break
                        chunk[key] = amount
                        used += amount
                    end += 1
                    if used > NAVIGATION_BATCH_BYTES:
                        break  # A large archive is always the only fetched origin.
                cache.close_archive()
                blobs.clear()
                if chunk:
                    expected = values(
                        *(column(name, a.c[name].type) for name in names),
                        column("expected_bytes", Integer),
                        name="navigation_archive_batch",
                    ).data([(*key[2:], amount) for key, amount in chunk.items()])
                    statement = (
                        select(
                            a.c.company_id,
                            *columns,
                            size.label("bytes"),
                            case(
                                (
                                    and_(size == expected.c.expected_bytes, size <= _ARCHIVE_LIMIT),
                                    a.c.content,
                                ),
                                else_=None,
                            ).label("content"),
                        )
                        .select_from(
                            a.join(expected, and_(*(a.c[n] == expected.c[n] for n in names)))
                        )
                        .where(a.c.company_id == company)
                    )
                    for row in _archive_rows(conn, statement):
                        key = _archive_key(row["company_id"], law, row)
                        if key not in chunk:
                            continue
                        raw = row["content"]
                        if (
                            key in blobs
                            or row["bytes"] != chunk[key]
                            or not isinstance(raw, bytes | bytearray | memoryview)
                            or len(raw) != chunk[key]
                        ):
                            blobs[key] = None
                            continue
                        raw = bytes(raw)
                        blobs[key] = raw if hashlib.sha256(raw).hexdigest() == key[2] else None
                    # Do not retain the final SQL row or its content outside this chunk.
                    row = raw = None
                for ref, key in zip(refs[start:end], origins[start:end], strict=True):
                    raw = blobs.get(key) if key is not None else None
                    if raw is None:
                        cache.close_archive()
                        yield None
                        continue
                    try:
                        if cache.archive_key != key:
                            cache.open_archive(key, raw)
                    except (BadZipFile, RuntimeError):
                        report = None
                    else:
                        try:
                            report = read_navigation(storage, company, ref, cache=cache)
                        except (ValueError, LookupError):
                            report = None
                    raw = None
                    yield report
                start = end
        finally:
            blobs.clear()
            cache.close_archive()
