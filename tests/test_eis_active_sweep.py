"""Synthetic partition, checkpoint, legacy compatibility and pacing regressions."""

import asyncio
import hashlib
import importlib.util
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_eis_hybrid_recovery import html as query_html
from test_eis_hybrid_recovery import stock_outcome

spec = importlib.util.spec_from_file_location(
    "sweep_test", Path(__file__).parents[1] / "scripts/server-eis-active-sweep.py"
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
h = m.hybrid
NOW = datetime(2026, 10, 24, 10, tzinfo=UTC)
DAY = NOW.date()
NUMBER = "0122100003226000999"


def html(scope, *, count=50, total="более 54 000 записей", page=1, offset=0):
    raw = query_html(scope, page=page).decode().replace('value="PRICE"', 'value="PUBLISH_DATE"')
    raw = raw.replace(
        'name="publishDateFrom" value=""',
        'name="publishDateFrom" value="'
        + (scope.publish_from.strftime("%d.%m.%Y") if scope.publish_from else "")
        + '"',
    )
    raw = raw.replace(
        'name="publishDateTo" value=""',
        'name="publishDateTo" value="' + scope.publish_to.strftime("%d.%m.%Y") + '"',
    )
    raw = raw.replace(
        "Любое название без совпадения",
        "Любое название без совпадения Размещено " + scope.publish_to.strftime("%d.%m.%Y"),
    )
    head, card = raw.split('<div class="search-registry-entry-block">', 1)
    cards = "".join(
        '<div class="search-registry-entry-block">'
        + card.replace(NUMBER, str(int(NUMBER) + n + offset).zfill(19))
        for n in range(count)
    )
    return (
        head
        + cards
        + '<div class="search-results__total">'
        + total
        + "</div>"
        + ("" if count else "Ничего не найдено")
    ).encode()


def observation(state, key=None, **kwargs):
    key = key or m.choose_partition(state)
    scope = state.partitions[key].queue.scope
    raw = html(scope, **kwargs)
    page = h.parse_page(raw, scope, DAY, kwargs.get("page", 1), NOW)
    return page, m.source_count(raw)


def test_empty_query_requires_explicit_all_active_scope():
    with pytest.raises(ValueError):
        h.Scope(query="")
    with pytest.raises(ValueError):
        h.Scope(query="", all_active=True)
    with pytest.raises(ValueError):
        h.Scope(query="бумага", all_active=True, publish_to=DAY)
    assert "searchString=&" in h.search_url(
        m.initial(DAY).partitions[m.choose_partition(m.initial(DAY))].queue.scope, DAY, 1
    )


def test_legacy_scope_key_and_page_bytes_unchanged():
    scope = h.Scope(query="бумага")
    legacy = '{"company_id":"local-eis-supplier","query":"бумага","max_pages":3,"law":"44"}'
    assert scope.key() == hashlib.sha256(legacy.encode()).hexdigest()
    page = h.parse_page(query_html(), scope, DAY, 1, NOW)
    assert page.coverage == "BOUNDED_QUERY_PAGE"
    assert "all_active" not in page.model_dump_json()
    state = h.State.model_validate({"scope": json.loads(legacy), "next_page": 1, "items": {}})
    assert state.scope.key() == scope.key()
    assert json.loads(state.model_dump_json())["scope"] == json.loads(legacy)


@pytest.mark.parametrize(
    "lo,hi", [(None, DAY), (DAY - timedelta(days=30), DAY), (DAY - timedelta(days=1), DAY)]
)
def test_split_preserves_entire_parent_without_overlap(lo, hi):
    scope = h.Scope(query="", all_active=True, publish_from=lo, publish_to=hi, max_pages=20)
    recent, older = m.split_scope(scope)
    assert older.publish_from == lo and recent.publish_to == hi
    assert older.publish_to + timedelta(days=1) == recent.publish_from
    assert recent.publish_from > older.publish_to


def test_overflow_children_and_pending_parent_commit_together(tmp_path):
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state)
    changed = m.observe(state, key, page, frozenset(), count)
    assert changed.partitions[key].status == "SPLIT" and len(changed.partitions) == 3
    assert len(changed.partitions[key].queue.items) == 50
    path = tmp_path / "sweep.json"
    m.save(path, changed)
    assert m.load(path, DAY) == changed and changed.coverage == "UNKNOWN"
    broken = changed.model_dump()
    del broken["partitions"][changed.partitions[key].children[0]]
    with pytest.raises(ValueError, match="SPLIT_CHILD_MISSING"):
        m.Sweep.model_validate(broken)


def test_single_day_overflow_is_not_completed():
    scope = h.Scope(query="", all_active=True, publish_from=DAY, publish_to=DAY, max_pages=20)
    state = m.Sweep(as_of=DAY, partitions={scope.key(): m.Partition(queue=h.State(scope=scope))})
    page, count = observation(state)
    after = m.observe(state, scope.key(), page, frozenset(), count)
    assert after.partitions[scope.key()].status == "SCANNING"
    part = after.partitions[scope.key()]
    after.partitions[scope.key()] = part.model_copy(
        update={"queue": part.queue.model_copy(update={"next_page": 20})}
    )
    page, count = observation(after, page=20, offset=100)
    after = m.observe(after, scope.key(), page, frozenset(), count)
    assert after.partitions[scope.key()].status == "SATURATED_UNKNOWN"
    assert after.coverage == "UNKNOWN" and m.choose_partition(after) is None


def test_short_page_is_only_observed_pages_not_source_completeness():
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state, count=1, total="1 запись")
    after = m.observe(state, key, page, frozenset(), count)
    assert after.partitions[key].status == "OBSERVED_PAGES" and after.coverage == "UNKNOWN"


def test_count_change_and_unparsed_never_become_complete():
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state, total="60 записей")
    state = m.observe(state, key, page, frozenset(), count)
    page, count = observation(state, count=1, total="61 запись", page=2, offset=50)
    after = m.observe(state, key, page, frozenset(), count)
    assert after.partitions[key].count_changed
    scope = m.initial(DAY).partitions[key].queue.scope
    raw = html(scope, count=1).replace("Размещено".encode(), "Другая дата".encode())
    page = h.parse_page(raw, scope, DAY, 1, NOW)
    assert page.unparsed_cards == 1
    after = m.observe(m.initial(DAY), key, page, frozenset(), m.source_count(raw))
    assert after.partitions[key].status == "UNPARSED_UNKNOWN"


@pytest.mark.parametrize("field", ["publishDateFrom", "publishDateTo", "searchString", "sortBy"])
def test_all_active_filter_echo_must_match(field):
    state = m.initial(DAY)
    scope = state.partitions[m.choose_partition(state)].queue.scope
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        h.parse_page(
            html(scope).replace(('name="' + field + '"').encode(), b'name="wrong"'),
            scope,
            DAY,
            1,
            NOW,
        )


def test_placed_day_outside_partition_is_rejected():
    state = m.initial(DAY)
    scope = state.partitions[m.choose_partition(state)].queue.scope
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        h.parse_page(
            html(scope).replace(b"24.10.2026</div>", b"25.10.2026</div>"), scope, DAY, 1, NOW
        )


def test_global_dedup_refreshes_owner_preserving_attempts_and_backoff():
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state)
    state = m.observe(state, key, page, frozenset(), count)
    old = state.partitions[key].queue.items[NUMBER]
    retry = NOW + timedelta(days=3)
    state.partitions[key].queue.items[NUMBER] = old.model_copy(
        update={"status": "RETRY", "attempts": 2, "retry_at": retry}
    )
    child = m.choose_partition(state)
    page, count = observation(state, child, count=1, total="1 запись")
    page = page.model_copy(update={"observed_at": retry})
    state = m.observe(state, child, page, frozenset(), count)
    assert NUMBER not in state.partitions[key].queue.items
    item = state.partitions[child].queue.items[NUMBER]
    assert item.last_seen == retry and item.first_seen == NOW
    assert item.attempts == 2 and item.retry_at == retry and item.status == "RETRY"
    assert h.due_items(state.partitions[child].queue, retry) == [item]


def test_cross_partition_audit_debt_retains_original_evidence():
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state)
    state = m.observe(state, key, page, frozenset(), count)
    old = h.outcome_item(state.partitions[key].queue.items[NUMBER], stock_outcome(), NOW)
    state.partitions[key].queue.items[NUMBER] = old
    child = m.choose_partition(state)
    page, count = observation(state, child, count=1, total="1 запись")
    state = m.observe(state, child, page, frozenset({NUMBER}), count)
    assert state.partitions[key].queue.items[NUMBER] == old
    assert not state.partitions[child].queue.items


@pytest.mark.parametrize("same_partition", [False, True])
def test_non_synced_audit_repair_applies_fresh_observation_atomically(tmp_path, same_partition):
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(
        state, total="60 записей" if same_partition else "более 54000 записей"
    )
    state = m.observe(state, key, page, frozenset(), count)
    failure = stock_outcome().model_copy(
        update={"status": "NO_DATA", "after": stock_outcome().before}
    )
    old = h.outcome_item(state.partitions[key].queue.items[NUMBER], failure, NOW)
    state.partitions[key].queue.items[NUMBER] = old
    child = key if same_partition else m.choose_partition(state)
    page, count = observation(
        state, child, count=1, total="1 запись", page=2 if same_partition else 1
    )
    fresh_time = NOW + timedelta(days=3)
    page = page.model_copy(update={"observed_at": fresh_time})
    state = m.observe(state, child, page, frozenset(), count)
    assert state.partitions[key].queue.items[NUMBER] == old
    path = tmp_path / "sweep.json"
    m.save(path, state)
    state = m.load(path, DAY)
    repaired = h.outcome_item(
        old,
        failure.model_copy(update={"audit_status": "RECORDED", "audit_event_id": "synthetic"}),
        fresh_time,
    )
    state.partitions[key].queue.items[NUMBER] = repaired
    state = m.apply_deferred(state)
    m.save(path, state)
    state = m.load(path, DAY)
    assert not state.deferred
    item = state.partitions[child].queue.items[NUMBER]
    assert item.last_seen == fresh_time and item.status == "RETRY" and item.pending_audit is None
    assert h.due_items(state.partitions[child].queue, item.retry_at) == [item]
    assert item.observation_sha256 == hashlib.sha256(page.model_dump_json().encode()).hexdigest()


def test_cycle_date_cannot_multiply_root_queue_budget(tmp_path):
    m.bind_cycle(tmp_path, DAY)
    m.bind_cycle(tmp_path, DAY)
    with pytest.raises(ValueError, match="SWEEP_CYCLE_MISMATCH"):
        m.bind_cycle(tmp_path, DAY + timedelta(days=1))
    assert len(list(tmp_path.iterdir())) == 1


def test_global_cap_not_multiplied_by_partitions(monkeypatch):
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state)
    state = m.observe(state, key, page, frozenset(), count)
    monkeypatch.setattr(h, "MAX_QUEUE", 50)
    child = m.choose_partition(state)
    page, count = observation(state, child, count=1, offset=100, total="1 запись")
    with pytest.raises(ValueError, match="GLOBAL_QUEUE_CAPACITY_OR_DUPLICATE"):
        m.observe(state, child, page, frozenset(), count)
    assert len(state.partitions[key].queue.items) == 50


def test_partition_cap_is_explicit_unknown(monkeypatch):
    monkeypatch.setattr(m, "MAX_PARTITIONS", 1)
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state)
    after = m.observe(state, key, page, frozenset(), count)
    assert after.partitions[key].status == "LIMIT_UNKNOWN"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1 запись", (1, True)),
        ("более 1 000 записей", (1000, False)),
        ("???", (None, False)),
        ("0 записей", (0, True)),
    ],
)
def test_count_parsing(value, expected):
    assert (
        m.source_count(('<div class="search-results__total">' + value + "</div>").encode())
        == expected
    )


def test_pacing_wait_is_bounded_and_no_request_before_retry(monkeypatch):
    calls = []
    now = datetime.now(UTC)

    @contextmanager
    def lease():
        calls.append("lease")
        yield now + timedelta(seconds=1) if len(calls) == 1 else None

    async def sleep(delay):
        calls.append("sleep")
        assert 0 < delay < 2

    async def fetch(url):
        calls.append("fetch")
        return b"body"

    monkeypatch.setattr(h, "_host_lease", lease)
    monkeypatch.setattr(h.asyncio, "sleep", sleep)
    monkeypatch.setattr(h, "_browser_html", fetch)
    assert asyncio.run(h.fetch_page("unused", wait_seconds=61)) == b"body"
    assert calls == ["lease", "sleep", "lease", "fetch"]
    calls.clear()
    with pytest.raises(ValueError, match="ROBOTS_CRAWL_DELAY"):
        asyncio.run(h.fetch_page("unused"))
    assert calls == ["lease"]


def test_global_checkpoint_written_before_network_and_survives_crash(tmp_path, monkeypatch):
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state, count=1, total="1 запись")
    state = m.observe(state, key, page, frozenset(), count)
    item = state.partitions[key].queue.items[NUMBER]
    now = datetime.now(UTC)
    state.partitions[key].queue.items[NUMBER] = item.model_copy(
        update={
            "last_seen": now,
            "candidate": item.candidate.model_copy(
                update={"deadline_day": (now + timedelta(days=1)).date()}
            ),
        }
    )
    path = tmp_path / "sweep.json"
    monkeypatch.setattr(h, "verify_item", lambda *args: None)
    before = SimpleNamespace(latest=None, lexical_rows=0)

    async def recover(*args):
        saved = m.load(path, DAY)
        i = saved.partitions[key].queue.items[NUMBER]
        assert i.attempts == 1 and i.status == "IN_FLIGHT" and i.retry_at > now
        raise OSError("simulated process failure")

    recovery = SimpleNamespace(
        Budget=lambda: SimpleNamespace(deadline=h.time.monotonic() + 180),
        read_indexed=lambda *args: before,
        route_hint=lambda *args: "ea20",
        recover_one=recover,
    )
    with pytest.raises(OSError):
        asyncio.run(
            m.drain_queues(
                state,
                tmp_path,
                path,
                None,
                recovery,
                SimpleNamespace(can_start=lambda **kwargs: True),
                "synthetic",
                None,
            )
        )
    assert not h.due_items(m.load(path, DAY).partitions[key].queue, now)


def test_tenant_and_cycle_mismatch_rejected(tmp_path):
    path = tmp_path / "sweep.json"
    state = m.initial(DAY)
    m.save(path, state)
    with pytest.raises(ValueError, match="SWEEP_DATE_MISMATCH"):
        m.load(path, DAY + timedelta(days=1))
    value = state.model_dump(mode="json")
    value["company_id"] = "foreign"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.load(path, DAY)


def test_eight_attempts_share_one_budget_and_global_checkpoint(tmp_path, monkeypatch):
    state = m.initial(DAY)
    key = m.choose_partition(state)
    page, count = observation(state, count=12, total="12 записей")
    state = m.observe(state, key, page, frozenset(), count)
    now = datetime.now(UTC)
    for n, item in list(state.partitions[key].queue.items.items()):
        state.partitions[key].queue.items[n] = item.model_copy(
            update={
                "last_seen": now,
                "candidate": item.candidate.model_copy(
                    update={"deadline_day": (now + timedelta(days=1)).date()}
                ),
            }
        )
    monkeypatch.setattr(h, "verify_item", lambda *args: None)
    stock = h.recovery_module()
    before = stock.Indexed(versions=0, lexical_rows=0)
    calls = []
    budgets = []
    path = tmp_path / "sweep.json"

    async def recover(storage, candidate, transport, budget, *args):
        assert (
            m.load(path, DAY).partitions[key].queue.items[candidate.purchase_number].status
            == "IN_FLIGHT"
        )
        calls.append(candidate.purchase_number)
        budgets.append(id(budget))
        return stock.Outcome(
            purchase_number=candidate.purchase_number,
            route_hint="ea20",
            status="NO_DATA",
            before=before,
            after=before,
        )

    recovery = SimpleNamespace(
        Budget=stock.Budget,
        read_indexed=lambda *args: before,
        route_hint=lambda *args: "ea20",
        recover_one=recover,
    )
    state, outcomes = asyncio.run(
        m.drain_queues(
            state,
            tmp_path,
            path,
            None,
            recovery,
            SimpleNamespace(can_start=lambda **kwargs: True),
            "synthetic",
            None,
        )
    )
    assert len(calls) == len(set(calls)) == len(outcomes) == 8 and len(set(budgets)) == 1
    assert sum(i.attempts for i in state.partitions[key].queue.items.values()) == 8


def test_discovery_failure_retains_prior_recovery_outcome(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    today = datetime.now(m.ZoneInfo("Europe/Moscow")).date()
    stock = h.recovery_module()
    before = stock.Indexed(versions=0, lexical_rows=0)
    out = stock.Outcome(
        purchase_number=NUMBER, route_hint="ea20", status="NO_DATA", before=before, after=before
    )

    @asynccontextmanager
    async def transport():
        yield None

    @contextmanager
    def joint(*args):
        yield SimpleNamespace(can_start=lambda **kwargs: True)

    engine = SimpleNamespace(dispose=lambda: None)
    monkeypatch.setattr(m, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(h, "PostgresStorage", lambda *args: None)
    monkeypatch.setattr(h, "JointStartBudget", joint)
    monkeypatch.setattr(stock, "source_guard", lambda *args: None)
    monkeypatch.setattr(stock, "eis_browser_transport", transport)
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setenv("EIS_BROWSER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", "synthetic-secret")

    async def drain(state, folder, path, *args, **kwargs):
        m.save(path, state)
        return state, [out]

    async def fail(*args, **kwargs):
        raise ValueError("ROBOTS_CRAWL_DELAY")

    monkeypatch.setattr(m, "drain_queues", drain)
    monkeypatch.setattr(h, "fetch_page", fail)
    report = asyncio.run(m.run(today, apply=True, root=tmp_path))
    assert report.discovery_status == "DEFERRED" and report.discovery_reason == "ROBOTS_CRAWL_DELAY"
    assert report.outcomes == (out,) and report.page is None
    saved = m.load(tmp_path / today.isoformat() / "sweep.json", today)
    assert saved == m.initial(today)
