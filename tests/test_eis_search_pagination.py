"""Continuation never mixes tenants, queries, deadlines or changed result evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from procurement.storage.eis_search_pagination import SearchPageError, SearchPagination

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
