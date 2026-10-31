import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from procurement.sources.gosplan_pagination import collect_batch
from procurement.sources.gosplan_queue import GosplanQueue, Scope

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def row(number):
    return {"purchase_number": number, "purchase_type": "purchaseNotice", "updated_at": None}


def test_pages_are_committed_before_advancing_and_tenant_scoped(tmp_path):
    offsets = []

    def handler(request):
        offset = int(request.url.params["skip"])
        offsets.append(offset)
        data = [row("32616349722"), row("32616349723")] if offset == 0 else [row("32616349724")]
        return httpx.Response(200, json=data)

    scope = Scope("one", "223", NOW - timedelta(days=1), NOW, 0, 2)
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_batch(client, "secret", queue, scope, max_pages=3)
    assert (result.status, result.reason, result.pages_recorded, result.next_offset) == (
        "STOPPED",
        "SHORT_PAGE",
        2,
        None,
    )
    assert result.coverage == "UNKNOWN" and offsets == [0, 2]
    assert len(queue.pending("one")) == 3 and queue.pending("other") == []
    queue.close()
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    assert len(queue.pending("one")) == 3
    queue.close()


def test_error_retains_prior_page_and_returns_failed_offset(tmp_path):
    def handler(request):
        if request.url.params["skip"] == "0":
            return httpx.Response(200, json=[row("32616349722")])
        return httpx.Response(429, text="secret must not appear")

    scope = Scope("one", "223", NOW - timedelta(days=1), NOW, 0, 1)
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_batch(client, "secret", queue, scope, max_pages=3)
    assert (result.status, result.reason, result.pages_recorded, result.next_offset) == (
        "UNKNOWN",
        "HTTP_429",
        1,
        1,
    )
    assert "secret" not in repr(result) and len(queue.pending("one")) == 1
    queue.close()


def test_budget_stops_and_invalid_budget_makes_no_request(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=json.dumps([row("32616349722")]).encode())

    scope = Scope("one", "223", NOW - timedelta(days=1), NOW, 0, 1)
    queue = GosplanQueue(tmp_path / "queue.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            collect_batch(client, "secret", queue, scope, max_pages=11)
        assert not calls
        result = collect_batch(client, "secret", queue, scope, max_pages=1)
    assert (result.reason, result.next_offset, result.pages_recorded) == ("PAGE_BUDGET", 1, 1)
    queue.close()


@pytest.mark.parametrize("offset,limit,budget", [(1000, 1, 1), (1000, 1, 2), (990, 20, 2)])
def test_full_page_at_provider_boundary_is_unknown_without_overflow(
    tmp_path, offset, limit, budget
):
    calls = []

    def handler(request):
        calls.append(int(request.url.params["skip"]))
        return httpx.Response(200, json=[row(str(32616349000 + i)) for i in range(limit)])

    scope = Scope("one", "223", NOW - timedelta(days=1), NOW, offset, limit)
    queue = GosplanQueue(tmp_path / "boundary.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_batch(client, "secret", queue, scope, max_pages=budget)
    assert calls == [offset]
    assert (result.status, result.reason, result.next_offset, result.coverage) == (
        "UNKNOWN",
        "OFFSET_LIMIT",
        None,
        "UNKNOWN",
    )
    assert len(queue.pending("one")) == limit
    queue.close()


def test_batch_can_reach_1000_and_short_page_ends_normally(tmp_path):
    calls = []

    def handler(request):
        offset = int(request.url.params["skip"])
        calls.append(offset)
        rows = [row(str(32616349000 + i)) for i in range(100)] if offset == 900 else []
        return httpx.Response(200, json=rows)

    queue = GosplanQueue(tmp_path / "short.sqlite")
    scope = Scope("one", "223", NOW - timedelta(days=1), NOW, 900, 100)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_batch(client, "secret", queue, scope, max_pages=2)
    assert calls == [900, 1000]
    assert (result.status, result.reason, result.coverage) == ("STOPPED", "SHORT_PAGE", "UNKNOWN")
    queue.close()
