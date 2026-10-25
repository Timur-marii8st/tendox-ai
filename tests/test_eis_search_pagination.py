"""Continuation never mixes tenants, queries, deadlines or changed result evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from procurement.storage.eis_search_pagination import (
    SearchComparisonMemo,
    SearchPageError,
    SearchPagination,
)

NOW = datetime(2026, 10, 7, 6, tzinfo=UTC)


def pager(cursor=None, **kwargs):
    return SearchPagination(
        **(
            {
                "company": "tenant-a",
                "law": "44",
                "query": "бумага",
                "scope": "ALL_CACHED",
                "now": NOW,
                "cursor": cursor,
            }
            | kwargs
        )
    )


def stream(p, size=237, changed=False):
    keys = []
    for i in range(size):
        key = (i % 7 == 0, i % 3 == 0, True, Decimal(0), -1, f"{i:019d}")
        evidence = {
            "number": key[-1],
            "verdict": "FAIL" if key[0] else "UNKNOWN",
            "value": "changed" if changed and i == 0 else "exact XML evidence",
        }
        if p.observe(key, evidence):
            keys.append(key)
    page = sorted(keys)[:100]
    fingerprint, next_cursor = p.finish(page[-1] if page else None, len(page))
    return page, fingerprint, next_cursor


def test_all_matches_beyond_100_are_traversed_once_in_exact_global_order():
    initial = pager()
    first, fingerprint, cursor = stream(initial)
    second, fingerprint2, cursor2 = stream(pager(cursor, now=NOW + timedelta(minutes=1)))
    third, fingerprint3, end = stream(pager(cursor2, now=NOW + timedelta(minutes=2)))
    all_keys = first + second + third
    assert len(first) == len(second) == 100 and len(third) == 37
    assert len(set(all_keys)) == 237 and all_keys == sorted(all_keys)
    assert fingerprint == fingerprint2 == fingerprint3 and end is None
    assert pager(cursor).at == NOW


@pytest.mark.parametrize(
    "change",
    [
        {"company": "tenant-b"},
        {"law": "223"},
        {"query": "сервер"},
        {"scope": "NOT_EXPIRED_OR_UNKNOWN"},
    ],
)
def test_cursor_cannot_cross_authenticated_tenant_law_query_or_scope(change):
    _, _, cursor = stream(pager())
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_INVALID"):
        pager(cursor, **change)


@pytest.mark.parametrize("clock", [NOW - timedelta(seconds=1), NOW + timedelta(minutes=16)])
def test_future_and_expired_snapshot_rejected(clock):
    _, _, cursor = stream(pager())
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_EXPIRED"):
        pager(cursor, now=clock)


def test_changed_evidence_even_before_page_boundary_forces_restart():
    _, _, cursor = stream(pager())
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_CHANGED"):
        stream(pager(cursor), changed=True)


def test_removed_boundary_or_matching_notice_does_not_silently_continue():
    _, _, cursor = stream(pager())
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_CHANGED"):
        stream(pager(cursor), size=200)


@pytest.mark.parametrize("value", ["", "!invalid", "e30", "a" * 2049])
def test_malformed_cursor_is_bounded_and_typed(value):
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_INVALID"):
        pager(value)


def test_memo_boundaries_expiry_and_eviction_are_misses_not_truncation(monkeypatch):
    import procurement.storage.eis_search_pagination as module

    clock = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    memo = SearchComparisonMemo(max_bytes=8, max_entries=2)
    key = memo.key("tenant-a", "44", "paper", NOW, b"source", b"events")
    for company, law, query, at, source, events in (
        ("tenant-b", "44", "paper", NOW, b"source", b"events"),
        ("tenant-a", "223", "paper", NOW, b"source", b"events"),
        ("tenant-a", "44", "other", NOW, b"source", b"events"),
        ("tenant-a", "44", "paper", NOW + timedelta(seconds=1), b"source", b"events"),
        ("tenant-a", "44", "paper", NOW, b"new-source", b"events"),
        ("tenant-a", "44", "paper", NOW, b"source", b"new-events"),
    ):
        assert memo.key(company, law, query, at, source, events) != key
    memo.put(key, b"1234")
    assert memo.get(key) == b"1234"
    memo.put("second", b"5678")
    memo.put("third", b"abcd")
    assert memo.get(key) is None
    assert memo.get("second") == b"5678"
    memo.put("oversize", b"123456789")
    assert memo.get("oversize") is None and memo.get("third") == b"abcd"
    clock[0] += 901
    assert memo.get("third") is None
    memo.clear()
    assert memo.get("second") is None


def test_cached_44_comparison_is_exact_and_changed_state_recompares(monkeypatch):
    from dataclasses import replace

    from procurement.sources.eis_procedure_state import EisProcedureState
    from procurement.storage import eis_index_query as query
    from test_eis_index_search import _notice

    notices = (
        replace(
            _notice("0848300054826000154", "Поставка бумаги А4"),
            deadline=NOW + timedelta(days=1),
        ),
    )
    memo = SearchComparisonMemo()
    monkeypatch.setattr(query, "PAGE_COMPARISONS", memo)
    original = query.compare_indexed_notices
    calls = []

    def compare(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(query, "compare_indexed_notices", compare)
    first, reused = query._compare_page_batch("a", notices, "бумага", NOW, {})
    second, reused2 = query._compare_page_batch("a", notices, "бумага", NOW, {})
    assert not reused and reused2 and first == second and len(calls) == 1
    assert first.matched_notices[0].application_status == "UNKNOWN"
    blocked, reused3 = query._compare_page_batch(
        "a",
        notices,
        "бумага",
        NOW,
        {notices[0].purchase_number: EisProcedureState("FAIL", ("cancel",))},
    )
    assert not reused3 and blocked.matched_notices[0].application_status == "FAIL"
    assert len(calls) == 2
