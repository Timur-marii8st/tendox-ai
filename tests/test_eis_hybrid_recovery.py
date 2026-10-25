"""Synthetic source evidence: no false completion, no foreign URL or lost retries."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "hybrid_recovery", Path(__file__).parents[1] / "scripts/server-eis-hybrid-recovery.py"
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
NOW = datetime(2026, 10, 24, 10, tzinfo=UTC)
DAY = NOW.date()
NUMBER = "0122100003226000999"


def html(scope=None, page=1, number=NUMBER, deadline="27.11.2026"):
    scope = scope or m.Scope(query="бумага")
    values = dict(
        searchString=scope.query,
        pageNumber=str(page),
        recordsPerPage="_50",
        sortBy="PRICE",
        sortDirection="false",
        applSubmissionCloseDateFrom="24.10.2026",
        publishDateFrom="",
        publishDateTo="",
    )
    controls = "".join(f'<input name="{k}" value="{v}">' for k, v in values.items())
    controls += "".join(
        f'<input name="{k}" ' + ("checked" if k in ("fz44", "af") else "") + ">"
        for k in ("fz44", "fz223", "af", "ca", "pc", "pa")
    )
    card = f"""<div class="search-registry-entry-block">
 <div class="registry-entry__header-top__title">44-ФЗ Электронный аукцион</div>
 <div class="registry-entry__header-mid__number">
 <a href="/epz/order/notice/ea20/view/common-info.html?regNumber={number}">№{number}</a></div>
 <div class="registry-entry__header-mid__title">Подача заявок</div>
 <div class="registry-entry__body-value">Любое название без совпадения</div>
 <div><div class="data-block__title">Окончание подачи заявок</div>
 <div class="data-block__value">{deadline}</div></div></div>"""
    return (controls + card).encode()


def observed(raw=None, scope=None, page=1):
    scope = scope or m.Scope(query="бумага")
    return m.parse_page(raw or html(scope, page), scope, DAY, page, NOW)


def test_no_local_title_filter_and_no_publication_cutoff():
    page = observed()
    assert page.candidates[0].purchase_number == NUMBER
    assert "publishDateFrom" not in page.search_url and "fz223=on" not in page.search_url
    assert page.coverage == "BOUNDED_QUERY_PAGE"


@pytest.mark.parametrize(
    "name",
    [
        "searchString",
        "sortBy",
        "pageNumber",
        "recordsPerPage",
        "sortDirection",
        "applSubmissionCloseDateFrom",
        "publishDateFrom",
        "publishDateTo",
        "fz44",
        "fz223",
        "af",
        "ca",
        "pc",
        "pa",
    ],
)
def test_echo_missing_duplicate_or_changed_is_not_accepted(name):
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        observed(html().replace(f'name="{name}"'.encode(), b'name="other"'))
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        observed(html() + f'<input name="{name}">'.encode())


@pytest.mark.parametrize(
    "old,new",
    [
        (b"44-\xd0\xa4\xd0\x97", b"223-\xd0\xa4\xd0\x97"),
        ("Подача заявок".encode(), "Работа комиссии".encode()),
        (b"27.11.2026", b"01.10.2026"),
    ],
)
def test_wrong_law_stage_and_expired_date_fail(old, new):
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        observed(html().replace(old, new))


def test_unparsed_not_silently_empty_and_duplicate_not_complete():
    page = observed(html(deadline="неизвестно"))
    assert page.unparsed_cards == 1 and not page.candidates
    raw = html()
    card = raw[raw.index(b'<div class="search-registry-entry-block">') :]
    with pytest.raises(ValueError, match="DUPLICATE_PUBLIC_NUMBER"):
        observed(raw + card)


def test_number_in_url_and_domain_are_verified():
    with pytest.raises(ValueError, match="CANDIDATE_URL_MISMATCH"):
        observed(html().replace(("regNumber=" + NUMBER).encode(), b"regNumber=0122100003226000998"))
    page = observed(html().replace(b'href="/epz', b'href="https://evil.invalid/epz'))
    assert page.unparsed_cards == 1 and not page.candidates


def test_captcha_is_not_empty_results():
    with pytest.raises(ValueError, match="BLOCKED_PAGE"):
        observed(html() + "Подтвердите, что вы не робот".encode())


def test_scope_tenant_and_persisted_identity_fail_closed(tmp_path):
    scope = m.Scope(query="бумага")
    state = m.merge_page(m.State(scope=scope), observed())
    p = tmp_path / "state.json"
    m.atomic_write(p, state.model_dump_json().encode())
    assert m.load_state(p, scope) == state
    with pytest.raises(ValueError, match="STATE_SCOPE_MISMATCH"):
        m.load_state(p, m.Scope(query="картон"))
    raw = json.loads(p.read_bytes())
    raw["scope"]["company_id"] = "foreign"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        m.load_state(p, scope)
    raw["scope"]["company_id"] = m.COMPANY
    raw["items"]["different"] = raw["items"].pop(NUMBER)
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="STATE_BINDING_INVALID"):
        m.load_state(p, scope)


def test_durable_backoff_and_crash_retry_and_fairness():
    state = m.merge_page(m.State(scope=m.Scope(query="бумага")), observed())
    item = state.items[NUMBER].model_copy(
        update=dict(status="IN_FLIGHT", attempts=1, retry_at=NOW + timedelta(minutes=15))
    )
    state.items[NUMBER] = item
    assert not m.due_items(state, NOW) and m.due_items(state, NOW + timedelta(minutes=16)) == [item]
    out = SimpleNamespace(
        status="NO_DATA",
        audit_status="RECORDED",
        after=SimpleNamespace(latest=None, lexical_rows=0),
    )
    failed = m.outcome_item(item, out, NOW)
    assert failed.status == "RETRY" and failed.retry_at > NOW
    state.items[NUMBER] = failed
    updated = m.merge_page(state, observed())
    assert updated.items[NUMBER].attempts == 1 and updated.items[NUMBER].retry_at == failed.retry_at
    assert not m.due_items(updated, NOW + timedelta(days=3))


@pytest.mark.parametrize(
    "status,audit,lexical,expected",
    [
        ("SYNCED", "RECORDED", 1, "INDEXED"),
        ("SYNCED", "FAILED", 1, "RETRY"),
        ("REJECTED", "RECORDED", 1, "RETRY"),
        ("SYNCED", "RECORDED", 0, "RETRY"),
    ],
)
def test_indexed_requires_success_audit_and_search_projection(status, audit, lexical, expected):
    item = m.merge_page(m.State(scope=m.Scope(query="бумага")), observed()).items[NUMBER]
    out = SimpleNamespace(
        status=status,
        audit_status=audit,
        after=SimpleNamespace(latest=object(), lexical_rows=lexical),
    )
    assert m.outcome_item(item, out, NOW).status == expected


def test_drain_skips_existing_and_persists_before_network(tmp_path, monkeypatch):
    state = m.merge_page(m.State(scope=m.Scope(query="бумага")), observed())
    # Keep clock-independent live queue dates synthetic but relative to current clock.
    now = datetime.now(UTC)
    candidate = state.items[NUMBER].candidate.model_copy(
        update={"deadline_day": (now + timedelta(days=7)).date()}
    )
    state.items[NUMBER] = state.items[NUMBER].model_copy(
        update=dict(candidate=candidate, first_seen=now, last_seen=now)
    )
    path = tmp_path / "state.json"
    monkeypatch.setattr(m, "verify_item", lambda *args: None)
    calls = []
    before = SimpleNamespace(versions=0, latest=None, lexical_rows=0)

    class Recovery:
        @staticmethod
        def Budget():
            return SimpleNamespace(deadline=m.time.monotonic() + 180)

        @staticmethod
        def read_indexed(*args):
            return before

        @staticmethod
        def route_hint(*args):
            return "ea20"

        @staticmethod
        async def recover_one(*args):
            saved = m.load_state(path, state.scope)
            assert saved.items[NUMBER].status == "IN_FLIGHT" and saved.items[NUMBER].attempts == 1
            calls.append(args[1].purchase_number)
            return SimpleNamespace(
                status="SYNCED",
                audit_status="RECORDED",
                after=SimpleNamespace(latest=object(), lexical_rows=1),
            )

    joint = SimpleNamespace(can_start=lambda **kwargs: True)
    state, outcomes = asyncio.run(
        m.drain(
            None, state, path, recovery=Recovery, joint=joint, token="synthetic", transport=None
        )
    )
    assert calls == [NUMBER] and state.items[NUMBER].status == "INDEXED"
    state, outcomes = asyncio.run(
        m.drain(
            None, state, path, recovery=Recovery, joint=joint, token="synthetic", transport=None
        )
    )
    assert calls == [NUMBER] and not outcomes


def test_store_guard_and_symlinks(tmp_path):
    path = tmp_path / "state.json"
    target = tmp_path / "target"
    target.write_text("keep")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="STATE_PATH_UNSAFE"):
        m.atomic_write(path, b"change")
    assert target.read_text() == "keep"
    with pytest.raises(ValueError, match="EVIDENCE_CAPACITY_GUARD"):
        m.guarded_store(tmp_path)


def test_queued_source_is_reparsed_before_recovery(tmp_path):
    page = observed()
    state = m.merge_page(m.State(scope=m.Scope(query="бумага")), page)
    item = state.items[NUMBER]
    (tmp_path / (page.source_sha256 + ".html")).write_bytes(html())
    (tmp_path / (item.observation_sha256 + ".json")).write_text(page.model_dump_json())
    m.verify_item(item, tmp_path, state.scope)
    (tmp_path / (page.source_sha256 + ".html")).write_bytes(
        html().replace(NUMBER.encode(), b"0122100003226000998")
    )
    with pytest.raises(ValueError, match="QUEUE_SOURCE_MISMATCH"):
        m.verify_item(item, tmp_path, state.scope)


def test_same_dom_new_observation_does_not_invalidate_durable_old_queue(tmp_path):
    scope = m.Scope(query="бумага")
    first = observed()
    state = m.merge_page(m.State(scope=scope), first)
    old = state.items[NUMBER]
    later = m.parse_page(html(), scope, DAY, 1, NOW + timedelta(minutes=10))
    newer = m.merge_page(state, later)
    new = newer.items[NUMBER]
    assert (
        old.source_sha256 == new.source_sha256 and old.observation_sha256 != new.observation_sha256
    )
    m.atomic_write(tmp_path / (first.source_sha256 + ".html"), html())
    m.atomic_write(tmp_path / (old.observation_sha256 + ".json"), first.model_dump_json().encode())
    m.atomic_write(tmp_path / (new.observation_sha256 + ".json"), later.model_dump_json().encode())
    # Observe-only or crash after new observation leaves the old queue valid.
    m.verify_item(old, tmp_path, scope)
    m.verify_item(new, tmp_path, scope)


def stock_outcome(number=NUMBER, audit="FAILED"):
    recovery = m.recovery_module()
    ref = recovery.NoticeDocumentRef(
        purchase_number=number, version_number=1, notice_xml_sha256="a" * 64
    )
    before = recovery.Indexed(versions=0, lexical_rows=0)
    after = recovery.Indexed(versions=1, lexical_rows=1, latest=ref)
    return recovery.Outcome(
        purchase_number=number,
        route_hint="ea20",
        status="SYNCED",
        before=before,
        after=after,
        audit_status=audit,
        audit_event_id="synthetic-audit" if audit == "RECORDED" else None,
    )


def test_audit_failure_is_not_hidden_by_known_database_and_retries_without_network(
    tmp_path, monkeypatch
):
    state = m.merge_page(m.State(scope=m.Scope(query="бумага")), observed())
    item = m.outcome_item(state.items[NUMBER], stock_outcome(), NOW)
    state.items[NUMBER] = item
    merged = m.merge_page(state, observed(), frozenset({NUMBER}))
    assert merged.items[NUMBER].pending_audit and merged.items[NUMBER].status == "RETRY"
    now = datetime.now(UTC)
    merged.items[NUMBER] = item.model_copy(update={"retry_at": now - timedelta(seconds=1)})
    monkeypatch.setattr(m, "verify_item", lambda *args: None)
    calls = []
    recovery = SimpleNamespace(
        Budget=lambda: SimpleNamespace(deadline=m.time.monotonic() + 180),
        read_indexed=lambda *args: stock_outcome().after,
        record_outcome=lambda *args: calls.append("audit") or stock_outcome(audit="RECORDED"),
    )
    result, outcomes = asyncio.run(
        m.drain(
            None,
            merged,
            tmp_path / "state.json",
            recovery=recovery,
            joint=None,
            token="synthetic",
            transport=None,
        )
    )
    assert calls == ["audit"] and not outcomes
    assert result.items[NUMBER].pending_audit is None and result.items[NUMBER].status == "INDEXED"


@pytest.mark.parametrize("budget_allowed,expected", [(False, 0), (True, 3)])
def test_attempt_cap_budget_and_existing_database_skip(
    tmp_path, monkeypatch, budget_allowed, expected
):
    scope = m.Scope(query="бумага")
    state = m.State(scope=scope)
    now = datetime.now(UTC)
    sample = m.merge_page(state, observed()).items[NUMBER]
    for i in range(5):
        number = "01221000032260009" + str(90 + i)
        candidate = sample.candidate.model_copy(
            update={
                "purchase_number": number,
                "detail_url": sample.candidate.detail_url.replace(NUMBER, number),
                "deadline_day": (now + timedelta(days=7)).date(),
            }
        )
        state.items[number] = sample.model_copy(
            update={"candidate": candidate, "first_seen": now, "last_seen": now}
        )
    first = sorted(state.items)[0]
    calls = []
    monkeypatch.setattr(m, "verify_item", lambda *args: None)

    async def recover(*args):
        number = args[1].purchase_number
        calls.append(number)
        return stock_outcome(number, audit="RECORDED")

    recovery = SimpleNamespace(
        Budget=lambda: SimpleNamespace(deadline=m.time.monotonic() + 180),
        read_indexed=lambda storage, n: (
            stock_outcome().after if n == first else stock_outcome().before
        ),
        route_hint=lambda c: "ea20",
        recover_one=recover,
    )
    joint = SimpleNamespace(can_start=lambda **kwargs: budget_allowed)
    result, outcomes = asyncio.run(
        m.drain(
            None,
            state,
            tmp_path / "state.json",
            recovery=recovery,
            joint=joint,
            token="synthetic",
            transport=None,
        )
    )
    assert result.items[first].status == "INDEXED" and first not in calls and len(calls) == expected
    assert len(outcomes) == expected
    assert sum(x.status == "PENDING" for x in result.items.values()) == 4 - expected


@pytest.mark.parametrize("case", ["own", "foreign", "replaced", "busy"])
def test_linux_wrapper_preserves_foreign_marker_and_stops_before_source(tmp_path, case):
    if os.name == "nt":
        pytest.skip("Linux server wrapper required")
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    marker = tmp_path / "marker"
    if case == "foreign":
        marker.write_text("foreign-owner")
    shell = Path(__file__).parents[1] / "scripts/server-eis-hybrid-recovery.sh"
    rewritten = shell.read_text().replace("/home/syurai/vibe-seller-state", str(state))
    rewritten = rewritten.replace("/var/lib/eis-browser/eis-priority.request", str(marker))
    wrapper = scripts / "recovery.sh"
    wrapper.write_text(rewritten)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    stub = """#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
args=sys.argv[1:]
name=Path(sys.argv[0]).name
if name=='flock':
 sys.exit(1 if os.environ['CASE']=='busy' and args[-1]=='9' else 0)
if args[:2]==['-n','docker']: args=args[2:]
if args[0]=='inspect': print('healthy')
elif args[0]=='exec':
 at=args.index('-c')
 sys.exit(subprocess.run([sys.executable,'-c',*args[at+1:]],check=False).returncode)
elif args[0]=='compose':
 Path(os.environ['SOURCE_LOG']).write_text('called')
 if os.environ['CASE']=='replaced': Path(os.environ['MARKER']).write_text('replacement-owner')
 print(json.dumps({'status':'BATCH_CALLED'}))
else: sys.exit(99)
"""
    for name in ("sudo", "flock"):
        executable = binaries / name
        executable.write_text(stub)
        executable.chmod(0o700)
    source_log = tmp_path / "source-called"
    result = subprocess.run(
        ["bash", str(wrapper)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=os.environ
        | {
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "CASE": case,
            "SOURCE_LOG": str(source_log),
            "MARKER": str(marker),
        },
    )
    payload = json.loads(result.stdout)
    if case in {"own", "replaced"}:
        assert result.returncode == 0 and source_log.exists()
        assert payload["status"] == "BATCH_CALLED"
    else:
        assert result.returncode == 75 and not source_log.exists()
        assert payload["status"] == "UNKNOWN" and payload["soap_attempts"] == 0
    if case in {"own", "busy"}:
        assert not marker.exists()
    else:
        assert marker.read_text() == ("foreign-owner" if case == "foreign" else "replacement-owner")
