"""A public hint never bypasses exact XML admission or tenant scope."""

import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from procurement.sources.eis_feed_sync import SOAP_NS
from procurement.sources.eis_number_sync import EisNumberSyncResult
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_index import bind_ready_window, ingest_ready_window
from test_eis_feed import _IP_NS, _xml
from test_eis_no_data_evidence import NOW, TOKEN, retain
from test_eis_no_data_public_check import DAY, card, controls
from test_eis_notice_index import _responses, _zip

spec = importlib.util.spec_from_file_location(
    "public_recovery", Path(__file__).parents[1] / "scripts/server-eis-public-candidate-recovery.py"
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
NUMBER = "0848300054826000911"
FOREIGN = "0848300054826000912"
SHA = "a" * 64


def candidate(number=NUMBER, route="ea20"):
    return SimpleNamespace(
        purchase_number=number,
        detail_url=(
            f"https://zakupki.gov.ru/epz/order/notice/{route}/view/common-info.html?regNumber={number}"
        ),
    )


def input_report(candidates):
    return SimpleNamespace(
        not_indexed_candidates=tuple(c.purchase_number for c in candidates),
        page=SimpleNamespace(candidates=candidates),
        artifact=SimpleNamespace(sha256="b" * 64),
        observed_at=NOW,
    )


def proof_fixture(tmp_path, monkeypatch):
    public = m.public_module()
    root = tmp_path / "raw"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(root))
    receipt = retain(root, company_id=m.COMPANY)
    body = (controls() + card(NUMBER)).encode()
    artifact = public.retain_page(tmp_path / "public-no-data" / m.COMPANY, body, TOKEN)
    page = public.parse_page(body, DAY)
    report = public.Report(
        observed_at=NOW,
        since=NOW - timedelta(hours=1),
        target=public.Target(
            audit_event_id=uuid4(),
            journal_attempt_id=uuid4(),
            journal_attempted_at=NOW,
            receipt=receipt,
            day=DAY,
        ),
        page=page,
        artifact=artifact,
        indexed_numbers=(),
        not_indexed_candidates=(NUMBER,),
        pg_snapshot="1:2:",
    )
    path = tmp_path / "input.json"
    raw = report.model_dump_json().encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), report


def test_exact_input_reparse_and_soap_receipt(tmp_path, monkeypatch):
    path, digest, report = proof_fixture(tmp_path, monkeypatch)
    assert m.load_input(path, digest, NOW).model_dump() == report.model_dump()
    assert m.load_input(path, digest, NOW).coverage == "UNKNOWN"


@pytest.mark.parametrize("mutation", ["sha", "dom", "page", "raw", "future", "stale"])
def test_input_corruption_stops_before_transport(tmp_path, monkeypatch, mutation):
    path, digest, report = proof_fixture(tmp_path, monkeypatch)
    now = NOW
    if mutation == "sha":
        digest = "f" * 64
    elif mutation == "dom":
        (tmp_path / "public-no-data" / m.COMPANY / report.artifact.relative_path).write_bytes(b"x")
    elif mutation == "page":
        data = json.loads(path.read_bytes())
        data["page"]["candidates"][0]["detail_url"] += "&evil=1"
        path.write_text(json.dumps(data))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    elif mutation == "raw":
        monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(tmp_path / "missing"))
    elif mutation == "future":
        now = NOW - timedelta(seconds=1)
    else:
        now = NOW + timedelta(days=8)
    with pytest.raises(ValueError):
        m.load_input(path, digest, now)


class Transport:
    def __init__(self, mode="notice", *, xml_number=NUMBER):
        self.mode = mode
        self.xml_number = xml_number
        self.calls = 0
        self.downloads = 0
        self.original = None
        self.url = None

    async def post(self, raw):
        self.calls += 1
        payload = next(iter(ET.fromstring(raw).find(f"{{{SOAP_NS}}}Body")))
        req = payload.findtext("index/id")
        if payload.tag.endswith("getDocsByReestrNumberRequest"):
            self.original = req
            self.url = (
                "https://int.zakupki.gov.ru/dstore/common/download/compound"
                f"?docRequestUid={req}&compoundUid={'1' * 32}"
            )
            if self.mode == "empty":
                branch = "<dataInfo><noData>true</noData></dataInfo>"
            elif self.mode == "error":
                branch = (
                    "<dataInfo><errorInfo><code>13</code>"
                    "<message>quota</message></errorInfo></dataInfo>"
                )
            else:
                branch = (
                    f"<dataInfo><archiveUrl>{self.url.replace('&', '&amp;')}"
                    "</archiveUrl></dataInfo>"
                )
            return 200, _xml("getDocsByReestrNumberResponse", branch, ref=req, namespace=_IP_NS)
        ready = "false" if self.mode == "pending" else "true"
        branch = f"<docRequestUid>{self.original}</docRequestUid><dataInfo>"
        branch += f"<isPreparationCompleted>{ready}</isPreparationCompleted>"
        if ready == "true":
            branch += f"<preparedPartInfo><dsUid>{'1' * 32}</dsUid>"
            branch += f"<url>{self.url.replace('&', '&amp;')}</url></preparedPartInfo>"
        return 200, _xml(
            "getPreparedPartResponse", branch + "</dataInfo>", ref=req, namespace=_IP_NS
        )

    async def download(self, url, token):
        self.downloads += 1
        assert url == self.url and token == TOKEN
        if self.mode == "unsupported":
            stream = BytesIO()
            with ZipFile(stream, "w") as archive:
                archive.writestr(
                    "unsupported.xml",
                    '<export xmlns="http://zakupki.gov.ru/oos/export/1"><epUnsupported/></export>',
                )
            return 200, stream.getvalue()
        return 200, _zip(self.xml_number)


def test_budget_counts_attempts_and_rejected_received_bytes(monkeypatch):
    class Failed:
        async def post(self, xml):
            raise OSError("secret")

        async def download(self, url, token):
            return 200, b"12345"

    budget = m.Budget()
    transport = m.CaptureTransport(Failed(), budget, TOKEN)
    with pytest.raises(OSError):
        asyncio.run(transport.post(b"x"))
    assert budget.posts == 1
    budget.posts = m.MAX_POSTS
    with pytest.raises(ValueError, match="SOAP_BUDGET_EXHAUSTED"):
        asyncio.run(transport.post(b"x"))
    monkeypatch.setattr(m, "MAX_BYTES", 4)
    with pytest.raises(ValueError, match="ARCHIVE_BATCH_SIZE_LIMIT"):
        asyncio.run(transport.download("url", TOKEN))
    assert budget.bytes == 5 and budget.accepted_bytes == 0 and budget.downloads == 1
    with pytest.raises(ValueError, match="ARCHIVE_BATCH_SIZE_LIMIT"):
        asyncio.run(transport.download("url", TOKEN))
    assert budget.downloads == 1


def test_shared_deadline_and_download_limit():
    budget = m.Budget()
    budget.deadline = 0
    with pytest.raises(ValueError, match="NETWORK_BUDGET_EXHAUSTED"):
        asyncio.run(m.CaptureTransport(None, budget, TOKEN).post(b"x"))
    budget = m.Budget()
    budget.downloads = m.MAX_DOWNLOADS
    with pytest.raises(ValueError, match="DOWNLOAD_BUDGET_EXHAUSTED"):
        asyncio.run(m.CaptureTransport(None, budget, TOKEN).download("url", TOKEN))


def test_candidate_scheduling_rechecks_known_and_bounds_three(monkeypatch):
    numbers = [str(int(NUMBER) + n).zfill(19) for n in range(7)]
    candidates = [candidate(n, "ezt20" if i == 0 else "ea20") for i, n in enumerate(numbers)]
    monkeypatch.setattr(
        m,
        "read_indexed",
        lambda _, number: m.Indexed(
            versions=1 if number == numbers[1] else 0,
            lexical_rows=0,
        ),
    )
    called = []

    async def one(storage, c, transport, budget, token, before, input_sha):
        called.append(c.purchase_number)
        return m.Outcome(
            purchase_number=c.purchase_number,
            route_hint="ea20",
            status="NO_DATA",
            before=before,
            after=before,
        )

    monkeypatch.setattr(m, "recover_one", one)
    report = asyncio.run(m.recover(None, input_report(candidates), TOKEN, SHA, transport=object()))
    assert called == numbers[2:5]
    assert report.attempted_numbers == 3
    by_number = {o.purchase_number: o.status for o in report.outcomes}
    assert [by_number[n] for n in numbers] == [
        "ROUTE_UNSUPPORTED",
        "ALREADY_INDEXED",
        "NO_DATA",
        "NO_DATA",
        "NO_DATA",
        "DEFERRED",
        "DEFERRED",
    ]
    assert report.coverage == report.participation == "UNKNOWN"


def test_candidate_order_samples_each_route_before_duplicates():
    values = [
        candidate(NUMBER, "ok20"),
        candidate(FOREIGN, "ok20"),
        candidate("0848300054826000913", "zk20"),
        candidate("0848300054826000914", "ea20"),
    ]
    assert [c.purchase_number for c in m.candidate_order(values)][:3] == [
        NUMBER,
        "0848300054826000913",
        "0848300054826000914",
    ]


def test_capture_requires_complete_and_original_bound_archive_set():
    transport = Transport()
    capture = m.CaptureTransport(transport, m.Budget(), TOKEN)
    initial, prepared = _responses()
    capture.initial = replace(initial, kind="BY_NUMBER")
    capture.prepared = prepared
    assert capture.bound_window(NUMBER) is None
    capture.archives = {initial.archive_urls[0]: _zip(NUMBER)}
    assert capture.bound_window(NUMBER).window_key.endswith(NUMBER)
    capture.prepared = replace(prepared, doc_request_uid="foreign")
    assert capture.bound_window(NUMBER) is None


def test_model_rejects_false_queue_foreign_refs_and_completeness():
    before = m.Indexed(versions=0, lexical_rows=0)
    values = dict(
        purchase_number=NUMBER, route_hint="ea20", status="NO_DATA", before=before, after=before
    )
    with pytest.raises(ValidationError):
        m.Outcome(**values, document_queue="PLANNED")
    with pytest.raises(ValidationError):
        m.Outcome(
            **values,
            document_ref=NoticeDocumentRef(
                purchase_number=FOREIGN,
                version_number=1,
                notice_xml_sha256=SHA,
            ),
        )
    with pytest.raises(ValidationError):
        m.Outcome(**values, audit_status="RECORDED")
    assert m.safe_reason(ValueError(TOKEN)) == "RECOVERY_UNAVAILABLE"


def test_post_ingest_hold_is_not_zero_writes_or_queue(monkeypatch):
    before = m.Indexed(versions=0, lexical_rows=0)
    after = m.Indexed(versions=1, lexical_rows=1)
    monkeypatch.setattr(m, "source_guard", lambda _: None)
    monkeypatch.setattr(m, "read_indexed", lambda *_: after)
    monkeypatch.setattr(m, "record_outcome", lambda _, out, __: out)

    async def held(*args, **kwargs):
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")

    monkeypatch.setattr(m, "sync_eis_number", held)
    out = asyncio.run(m.recover_one(None, candidate(), object(), m.Budget(), TOKEN, before, SHA))
    assert out.after.versions == 1 and out.status == "UNKNOWN"
    assert out.document_queue == "NOT_REQUESTED" and out.rejection_evidence is None


def test_queue_failure_preserves_synced_fact(monkeypatch):
    indexed = m.Indexed(versions=1, lexical_rows=1)
    monkeypatch.setattr(m, "source_guard", lambda _: None)
    monkeypatch.setattr(m, "read_indexed", lambda *_: indexed)
    monkeypatch.setattr(m, "record_outcome", lambda _, out, __: out)

    async def synced(*args, **kwargs):
        return EisNumberSyncResult(NUMBER, "SYNCED", latest_version_number=1, latest_xml_sha256=SHA)

    def queue(*args, **kwargs):
        raise ValueError("NOTICE_VERSION_STALE")

    monkeypatch.setattr(m, "sync_eis_number", synced)
    monkeypatch.setattr(m, "plan_document_job", queue)
    out = asyncio.run(m.recover_one(None, candidate(), object(), m.Budget(), TOKEN, indexed, SHA))
    assert out.status == "SYNCED" and out.document_queue == "UNKNOWN"
    assert out.document_queue_reason == "NOTICE_VERSION_STALE"


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
    shell = Path(__file__).parents[1] / "scripts/server-eis-public-candidate-recovery.sh"
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


@pytest.mark.parametrize("mode", ["notice", "foreign", "unsupported", "empty", "error"])
def test_isolated_pg_exact_intake_queue_and_rejection(tmp_path, monkeypatch, mode):
    app_url = os.getenv("DATABASE_URL")
    admin_url = os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL required")
    if any("procurement_eis_test_" not in url for url in (app_url, admin_url)):
        pytest.fail("explicit isolated DB required")
    from sqlalchemy import create_engine, select

    from procurement.storage.models import audit_events, eis_document_jobs
    from procurement.storage.repository import PostgresStorage

    engine = create_engine(app_url)
    storage = PostgresStorage(engine)
    number = str(
        int(NUMBER)
        + {"notice": 10, "foreign": 20, "unsupported": 30, "empty": 40, "error": 50}[mode]
    ).zfill(19)
    # The same registry number in another tenant must not suppress this request.
    initial, prepared = _responses()
    ingest_ready_window(
        storage,
        f"foreign-s201-{mode}",
        bind_ready_window(
            "getDocsIP/PRIZ/50/2026-09-25/17+03:00",
            initial,
            prepared,
            {initial.archive_urls[0]: _zip(number)},
        ),
        actor_id="synthetic",
    )
    monkeypatch.setattr(m, "source_guard", lambda _: None)
    monkeypatch.setenv("EIS_REJECTED_EVIDENCE_DIR", str(tmp_path / "evidence"))
    transport = Transport(
        "notice" if mode == "foreign" else mode, xml_number=FOREIGN if mode == "foreign" else number
    )
    try:
        report = asyncio.run(
            m.recover(storage, input_report([candidate(number)]), TOKEN, SHA, transport=transport)
        )
        out = report.outcomes[0]
        assert out.before.versions == 0 and out.audit_status == "RECORDED"
        assert transport.calls == (1 if mode in {"empty", "error"} else 2)
        with storage.transaction(m.COMPANY, consistent_read=True) as conn:
            event = conn.execute(
                select(audit_events.c.basis).where(
                    audit_events.c.company_id == m.COMPANY,
                    audit_events.c.event_id == out.audit_event_id,
                )
            ).scalar_one()
            jobs = (
                conn.execute(
                    select(eis_document_jobs).where(
                        eis_document_jobs.c.company_id == m.COMPANY,
                        eis_document_jobs.c.purchase_number == number,
                    )
                )
                .mappings()
                .all()
            )
        assert event["input_sha256"] == SHA
        if mode == "notice":
            assert out.status == "SYNCED" and out.after.versions == out.after.lexical_rows == 1
            assert out.document_queue == "PLANNED" and len(jobs) == 1
            assert jobs[0]["notice_xml_sha256"] == out.after.latest.notice_xml_sha256
        else:
            assert out.after.versions == out.after.lexical_rows == 0 and not jobs
            if mode in {"foreign", "unsupported"}:
                assert out.status == "REJECTED" and out.rejection_evidence.status == "RETAINED"
                assert out.reason == (
                    "BY_NUMBER_PURCHASE_MISMATCH"
                    if mode == "foreign"
                    else "DOCUMENT_TYPE_UNSUPPORTED"
                )
                manifest = tmp_path / "evidence" / out.rejection_evidence.relative_manifest_path
                assert (
                    hashlib.sha256(manifest.read_bytes()).hexdigest()
                    == out.rejection_evidence.manifest_sha256
                )
            else:
                assert out.status == ("NO_DATA" if mode == "empty" else "SERVICE_ERROR")
                assert out.rejection_evidence is None
    finally:
        engine.dispose()
