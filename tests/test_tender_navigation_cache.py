"""Request-local source binding and bounded ZIP reader reuse."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from time import perf_counter
from zipfile import ZipFile

import pytest

from procurement.storage import eis_global_price as search_module
from procurement.storage import tender_navigation as module
from procurement.storage.eis_index_query import EisIndexedLead, EisIndexedSearchResult
from procurement.storage.eis_mixed_comparison import MixedNoticeRef
from test_beta_quote import NOW
from test_eis_223_archive import parse_notice223_xml
from test_eis_223_archive import xml as xml223
from test_eis_feed_archive import _archive, _inspect, _notice

COMPANY = "cache-tenant"
WINDOW = "getDocsIP/PRIZ/50/2026-09-25/17+03:00"
RESPONSE = "a" * 64


def flattened_parameters(value):
    if isinstance(value, list | tuple):
        return [item for nested in value for item in flattened_parameters(nested)]
    return [value]


class Result:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def first(self):
        return next(iter(self.rows), None)

    def all(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class Storage:
    def __init__(self, raw, rows):
        self.rows = rows
        self.raw = raw
        self.archive_queries = 0
        self.archive_size = len(raw)
        self.origin = (COMPANY, sha256(raw).hexdigest(), WINDOW, RESPONSE)

    @contextmanager
    def transaction(self, company, **kwargs):
        yield self

    def execute(self, statement):
        source = statement.get_final_froms()[0]
        table = source.left.name if hasattr(source, "left") else source.name
        if table == module.eis_notice_versions.name:
            return Result(self.rows)
        assert table in {module.eis_feed_archives.name, module.eis_223_blobs.name}
        self.archive_queries += 1
        parameters = flattened_parameters(tuple(statement.compile().params.values()))
        origin = self.origin if table == module.eis_feed_archives.name else self.origin[:2]
        if not all(value in parameters for value in origin):
            return Result(())
        if "bytes" in statement.selected_columns:
            row = {
                "company_id": self.origin[0],
                "archive_sha256": self.origin[1],
                "window_key": self.origin[2],
                "response_sha256": self.origin[3],
                "bytes": self.archive_size,
            }
            if "content" in statement.selected_columns:
                row["content"] = self.raw
            return Result((row,))
        return Result(((self.archive_size, self.raw),))


def corpus(count=2):
    raw = _archive(*((f"{i}.xml", _notice(f"{i + 1:019d}")) for i in range(count)))
    rows = [
        asdict(record)
        | {
            "company_id": COMPANY,
            "window_key": WINDOW,
            "response_sha256": RESPONSE,
            "archive_sha256": sha256(raw).hexdigest(),
        }
        for record in _inspect(raw).records
    ]
    refs = [
        MixedNoticeRef(
            law="44",
            purchase_number=row["purchase_number"],
            version_number=row["version_number"],
            notice_xml_sha256=row["xml_sha256"],
        )
        for row in rows
    ]
    return Storage(raw, rows), refs


def cache_for(storage, refs):
    return module.NavigationReadCache(
        sources={
            (ref.law, ref.purchase_number, ref.version_number, ref.notice_xml_sha256): row
            for ref, row in zip(refs, storage.rows, strict=True)
        },
        company=COMPANY,
        connection=storage,
    )


def track_zip(monkeypatch):
    readers = []
    counters = {"opens": 0, "directory_scans": 0}

    class TrackedZip(ZipFile):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            readers.append(self)
            counters["opens"] += 1

        def infolist(self):
            counters["directory_scans"] += 1
            return super().infolist()

    monkeypatch.setattr(module, "ZipFile", TrackedZip)
    return readers, counters


def test_repeated_archive_reads_keep_one_reader_and_release_it(monkeypatch):
    storage, refs = corpus()
    cache = cache_for(storage, refs)
    readers, counts = track_zip(monkeypatch)
    try:
        first = module.read_navigation(storage, COMPANY, refs[0], cache=cache)
        second = module.read_navigation(storage, COMPANY, refs[1], cache=cache)
        repeated = module.read_navigation(storage, COMPANY, refs[0], cache=cache)
        assert first == repeated and second.purchase_number != first.purchase_number
        assert counts == {"opens": 1, "directory_scans": 1}
        assert storage.archive_queries == 1
        assert readers[0].fp is not None
    finally:
        if hasattr(cache, "close"):
            cache.close()
    assert readers[0].fp is None


@pytest.mark.parametrize("field", ["window_key", "response_sha256"])
def test_same_digest_different_origin_is_revalidated_and_old_reader_closed(monkeypatch, field):
    storage, refs = corpus()
    cache = cache_for(storage, refs)
    readers, _ = track_zip(monkeypatch)
    try:
        module.read_navigation(storage, COMPANY, refs[0], cache=cache)
        storage.rows[1][field] = "other-origin"
        with pytest.raises(LookupError, match="NAVIGATION_ARCHIVE_NOT_FOUND"):
            module.read_navigation(storage, COMPANY, refs[1], cache=cache)
        assert storage.archive_queries == 2
        assert readers[0].fp is None
    finally:
        if hasattr(cache, "close"):
            cache.close()


@pytest.mark.parametrize("wrong_context", ["company", "connection"])
def test_cache_rejects_another_tenant_or_transaction(wrong_context):
    storage, refs = corpus()
    cache = cache_for(storage, refs)
    company = "other-tenant" if wrong_context == "company" else COMPANY
    if wrong_context == "connection":
        cache.connection = object()
    with pytest.raises(ValueError, match="NAVIGATION_CACHE_CONTEXT"):
        module.read_navigation(storage, company, refs[0], cache=cache)
    assert storage.archive_queries == 0


def test_replacement_closes_prior_reader_and_retains_only_one_archive(monkeypatch):
    storage, refs = corpus()
    cache = cache_for(storage, refs)
    readers, counts = track_zip(monkeypatch)
    with cache:
        module.read_navigation(storage, COMPANY, refs[0], cache=cache)
        storage.raw = _archive(("1.xml", _notice(refs[1].purchase_number)))
        storage.archive_size = len(storage.raw)
        storage.rows[1]["archive_sha256"] = sha256(storage.raw).hexdigest()
        storage.origin = (COMPANY, storage.rows[1]["archive_sha256"], WINDOW, RESPONSE)
        module.read_navigation(storage, COMPANY, refs[1], cache=cache)
        assert counts == {"opens": 2, "directory_scans": 2}
        assert readers[0].fp is None and readers[1].fp is not None
        buffer = cache._buffer
    assert all(reader.fp is None for reader in readers)
    assert buffer.closed
    assert cache.archive_key is None and cache.sources is None and cache.catalog is None


def test_same_archive_digest_different_law_requires_new_verified_binding(monkeypatch):
    storage, refs = corpus(1)
    raw223 = xml223()
    snapshot = parse_notice223_xml(raw223, source_member="223.xml")
    storage.raw = _archive(("0.xml", _notice(refs[0].purchase_number)), ("223.xml", raw223))
    storage.archive_size = len(storage.raw)
    digest = sha256(storage.raw).hexdigest()
    storage.origin = (COMPANY, digest, WINDOW, RESPONSE)
    storage.rows[0]["archive_sha256"] = digest
    ref223 = MixedNoticeRef(
        law="223",
        purchase_number=snapshot.purchase_number,
        version_number=snapshot.version_number,
        notice_xml_sha256=snapshot.xml_sha256,
    )
    row223 = {"snapshot": snapshot.model_dump(mode="json"), "archive_sha256": digest}
    cache = cache_for(storage, refs)
    cache.sources[
        ("223", ref223.purchase_number, ref223.version_number, ref223.notice_xml_sha256)
    ] = row223
    readers, counts = track_zip(monkeypatch)
    with cache:
        module.read_navigation(storage, COMPANY, refs[0], cache=cache)
        result = module.read_navigation(storage, COMPANY, ref223, cache=cache)
        assert result.law == "223" and result.xml_sha256 == snapshot.xml_sha256
        assert counts["opens"] == 2 and storage.archive_queries == 2
        assert readers[0].fp is None and readers[1].fp is not None
    assert all(reader.fp is None for reader in readers)


@pytest.mark.parametrize("problem", ["duplicate", "missing", "directory", "xml_hash"])
def test_member_ambiguity_and_wrong_source_never_supply_navigation(problem):
    storage, refs = corpus(1)
    row = storage.rows[0]
    if problem == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            storage.raw = _archive(("0.xml", _notice(refs[0].purchase_number)), ("0.xml", b"other"))
    elif problem == "missing":
        row["source_member"] = "absent.xml"
    elif problem == "directory":
        storage.raw = _archive(("0.xml/", b""))
        row["source_member"] = "0.xml/"
    else:
        storage.raw = _archive(("0.xml", _notice(refs[0].purchase_number, version=2)))
    row["archive_sha256"] = sha256(storage.raw).hexdigest()
    storage.origin = (COMPANY, row["archive_sha256"], WINDOW, RESPONSE)
    storage.archive_size = len(storage.raw)
    cache = cache_for(storage, refs)
    try:
        with pytest.raises(ValueError, match="NAVIGATION_"):
            module.read_navigation(storage, COMPANY, refs[0], cache=cache)
    finally:
        if hasattr(cache, "close"):
            cache.close()


@pytest.mark.parametrize("problem", ["archive_hash", "truncated_zip", "oversized_archive"])
def test_archive_integrity_and_size_are_checked_before_navigation(problem):
    storage, refs = corpus(1)
    if problem == "archive_hash":
        storage.raw += b"changed"
        expected = "NAVIGATION_ARCHIVE_DIGEST"
    elif problem == "truncated_zip":
        storage.raw = storage.raw[:40]
        digest = sha256(storage.raw).hexdigest()
        storage.rows[0]["archive_sha256"] = digest
        storage.origin = (COMPANY, digest, WINDOW, RESPONSE)
        expected = "NAVIGATION_ARCHIVE_INVALID"
    else:
        storage.archive_size = 50 * 1024**2 + 1
        expected = "NAVIGATION_ARCHIVE_LIMIT"
    cache = cache_for(storage, refs)
    try:
        with pytest.raises(ValueError, match=expected):
            module.read_navigation(storage, COMPANY, refs[0], cache=cache)
    finally:
        if hasattr(cache, "close"):
            cache.close()


@pytest.mark.parametrize("problem", ["oversized_member", "truncated_member"])
def test_member_size_checks_survive_reader_reuse(monkeypatch, problem):
    storage, refs = corpus(1)

    class BrokenMemberZip(ZipFile):
        def infolist(self):
            members = super().infolist()
            if problem == "oversized_member":
                members[0].file_size = 32 * 1024**2 + 1
            return members

        def open(self, *args, **kwargs):
            if problem == "truncated_member":
                return BytesIO(b"truncated")
            return super().open(*args, **kwargs)

    monkeypatch.setattr(module, "ZipFile", BrokenMemberZip)
    cache = cache_for(storage, refs)
    try:
        with pytest.raises(ValueError, match=r"NAVIGATION_MEMBER_(LIMIT|SIZE)"):
            module.read_navigation(storage, COMPANY, refs[0], cache=cache)
    finally:
        if hasattr(cache, "close"):
            cache.close()


@pytest.mark.parametrize("interrupted", [False, True])
def test_global_query_releases_reader_on_success_and_exception(monkeypatch, interrupted):
    storage, _refs = corpus(1)
    readers, _ = track_zip(monkeypatch)
    row = storage.rows[0]
    lead = EisIndexedLead(
        **{
            key: row[key]
            for key in (
                "purchase_number",
                "document_type",
                "version_number",
                "title",
                "nmck_rub",
                "deadline",
                "source_member",
                "xml_sha256",
                "lot_items",
                "attachments",
            )
        },
        notice_url="https://zakupki.gov.ru/notice",
        application_status="UNKNOWN",
        economic_status="UNKNOWN",
        match_quality="STRONG",
        matched_terms=("бумага",),
        match_locator="/title",
        reasons=(),
        source_window=WINDOW,
    )

    def search(shared, company, query, *, on_matches, **kwargs):
        on_matches((lead,))
        if interrupted:
            raise RuntimeError("synthetic-query-interrupted")
        return EisIndexedSearchResult(
            query=query,
            inspected_current_notices=1,
            matched_count=1,
            indexed_windows=1,
            latest_ingested_at=NOW,
            matched=(lead,),
        )

    monkeypatch.setattr(search_module, "search_eis_index", search)
    options = search_module.GlobalPriceOptions(query="бумага", law="44", delivery_region="Москва")
    if interrupted:
        with pytest.raises(RuntimeError, match="synthetic-query-interrupted"):
            search_module.search_global_price(storage, COMPANY, options, now=NOW)
    else:
        result = search_module.search_global_price(storage, COMPANY, options, now=NOW)
        assert result.matched_count == 0 and result.unknown_region_count == 1
    assert len(readers) == 1 and readers[0].fp is None


def test_synthetic_reuse_operation_counts(monkeypatch):
    storage, refs = corpus(100)
    readers, counts = track_zip(monkeypatch)
    adapter_factory = module.TypeAdapter
    builds = []

    def counted_adapter(*args, **kwargs):
        builds.append(1)
        return adapter_factory(*args, **kwargs)

    monkeypatch.setattr(module, "TypeAdapter", counted_adapter)
    cache = module.NavigationReadCache()
    started = perf_counter()
    try:
        module.prime_navigation_cache(storage, COMPANY, refs, cache)
        for _ in range(3):
            for ref in refs:
                result = module.read_navigation(storage, COMPANY, ref, cache=cache)
                assert result.xml_sha256 == ref.notice_xml_sha256
    finally:
        if hasattr(cache, "close"):
            cache.close()
    evidence = counts | {
        "adapter_builds": len(builds),
        "seconds": round(perf_counter() - started, 6),
        "notice_count": len(refs),
        "reads": 3 * len(refs),
        "archive_queries": storage.archive_queries,
    }
    print("SYNTHETIC_NAVIGATION_BENCHMARK " + json.dumps(evidence, sort_keys=True))
    assert counts == {"opens": 1, "directory_scans": 1}
    assert len(builds) <= 1
    assert all(reader.fp is None for reader in readers)


class ManyOriginsStorage:
    def __init__(self, count=20):
        self.rows = []
        self.raws = {}
        self.refs = []
        self.singleton_queries = 0
        self.metadata_queries = 0
        self.content_queries = 0
        self.chunk_bytes = []
        self.results = []
        self.metadata_sizes = {}
        self.corrupt = set()
        self.duplicate = set()
        for i in range(count):
            raw = _archive((f"{i}.xml", _notice(f"{i + 1:019d}")))
            record = _inspect(raw).records[0]
            row = asdict(record) | {
                "company_id": COMPANY,
                "window_key": WINDOW + str(i),
                "response_sha256": f"{i + 1:064x}",
                "archive_sha256": sha256(raw).hexdigest(),
            }
            self.rows.append(row)
            self.raws[self.key(row)] = raw
            self.refs.append(
                MixedNoticeRef(
                    law="44",
                    purchase_number=record.purchase_number,
                    version_number=record.version_number,
                    notice_xml_sha256=record.xml_sha256,
                )
            )

    @staticmethod
    def key(row):
        return (
            row["company_id"],
            "44",
            row["archive_sha256"],
            row["window_key"],
            row["response_sha256"],
        )

    @contextmanager
    def transaction(self, company, **kwargs):
        yield self

    def execute(self, statement):
        parameters = flattened_parameters(tuple(statement.compile().params.values()))
        if statement.get_final_froms()[0] is module.eis_notice_versions:
            result = Result(self.rows)
        else:
            matched = [
                (key, raw)
                for key, raw in self.raws.items()
                if all(value in parameters for value in (key[0], *key[2:]))
            ]
            columns = list(statement.selected_columns.keys())
            if "bytes" not in columns:
                self.singleton_queries += 1
                result = Result([(len(raw), raw) for _, raw in matched])
            else:
                content = "content" in columns
                if content:
                    self.content_queries += 1
                    self.chunk_bytes.append(
                        sum(
                            len(raw)
                            for key, raw in matched
                            if self.metadata_sizes.get(key, len(raw)) == len(raw)
                        )
                    )
                    sql = str(statement)
                    assert "navigation_archive_batch.expected_bytes" in sql
                    assert "CASE WHEN" in sql
                else:
                    self.metadata_queries += 1
                rows = []
                for key, raw in matched:
                    size = self.metadata_sizes.get(key, len(raw))
                    row = {
                        "company_id": key[0],
                        "archive_sha256": key[2],
                        "window_key": key[3],
                        "response_sha256": key[4],
                        "bytes": len(raw) if content else size,
                    }
                    if content:
                        row["content"] = (raw[:-1] + b"!") if key in self.corrupt else raw
                        if size != len(raw):
                            row["content"] = None
                    rows.append(row)
                    if key in self.duplicate:
                        rows.append(dict(row))
                result = Result(rows)
        self.results.append(result)
        return result


def navigation_batch(storage, cache):
    if hasattr(module, "read_navigation_batch"):
        return module.read_navigation_batch(storage, COMPANY, storage.refs, cache)
    # Run the existing serial path before the batch implementation exists.
    return (module.read_navigation(storage, COMPANY, ref, cache=cache) for ref in storage.refs)


def test_many_origins_use_one_bounded_content_select_in_original_order(monkeypatch):
    storage = ManyOriginsStorage()
    cache = module.NavigationReadCache()
    readers, _ = track_zip(monkeypatch)
    with cache:
        module.prime_navigation_cache(storage, COMPANY, storage.refs, cache)
        reports = list(navigation_batch(storage, cache))
        assert [report.xml_sha256 for report in reports] == [
            r.notice_xml_sha256 for r in storage.refs
        ]
    assert storage.singleton_queries == 0
    assert storage.metadata_queries == 1 and storage.content_queries == 1
    assert all(reader.fp is None for reader in readers)
    assert all(result.closed for result in storage.results[1:])


@pytest.mark.parametrize(
    "problem", ["metadata_size", "content_hash", "ambiguous_origin", "wrong_response"]
)
def test_batch_origin_or_content_failure_keeps_neighbor_valid_and_unknown(problem):
    storage = ManyOriginsStorage(2)
    key = storage.key(storage.rows[0])
    if problem == "metadata_size":
        storage.metadata_sizes[key] = len(storage.raws[key]) - 1
    elif problem == "content_hash":
        storage.corrupt.add(key)
    elif problem == "ambiguous_origin":
        storage.duplicate.add(key)
    else:
        storage.rows[0]["response_sha256"] = "f" * 64
    with module.NavigationReadCache() as cache:
        module.prime_navigation_cache(storage, COMPANY, storage.refs, cache)
        reports = list(navigation_batch(storage, cache))
    assert reports[0] is None
    assert reports[1].xml_sha256 == storage.refs[1].notice_xml_sha256


def test_batch_buffer_boundary_and_large_archive_are_separate(monkeypatch):
    storage = ManyOriginsStorage(3)
    limit = 2 * len(next(iter(storage.raws.values())))
    monkeypatch.setattr(module, "NAVIGATION_BATCH_BYTES", limit, raising=False)
    row = storage.rows[2]
    old_key = storage.key(row)
    raw = _archive(
        (row["source_member"], _notice(row["purchase_number"])), ("padding.bin", b"x" * limit)
    )
    del storage.raws[old_key]
    row["archive_sha256"] = sha256(raw).hexdigest()
    storage.raws[storage.key(row)] = raw
    with module.NavigationReadCache() as cache:
        module.prime_navigation_cache(storage, COMPANY, storage.refs, cache)
        assert all(navigation_batch(storage, cache))
    assert storage.chunk_bytes == [limit, len(raw)]
    assert storage.singleton_queries == 0


def test_interrupted_batch_closes_results_and_active_archive(monkeypatch):
    storage = ManyOriginsStorage(3)
    readers, _ = track_zip(monkeypatch)
    with module.NavigationReadCache() as cache:
        module.prime_navigation_cache(storage, COMPANY, storage.refs, cache)
        iterator = navigation_batch(storage, cache)
        assert next(iterator).xml_sha256 == storage.refs[0].notice_xml_sha256
        iterator.close()
        assert all(reader.fp is None for reader in readers)
        assert all(result.closed for result in storage.results[1:])
