"""Synthetic SOAP/ZIP only; no network or supplier admission in these tests."""

import asyncio
from datetime import date
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_archive import SUPPORTED_DOCUMENT_TYPES
from procurement.sources.eis_223_sync import Eis223RefreshTarget, fetch_notice223_day, window_key
from test_eis_223_archive import xml, zip_bytes
from test_eis_feed_sync import SOAP_NS, TOKEN, UID, _response


class Transport:
    def __init__(self, state="READY", failure=None, family="purchaseNoticeAESMBO", region="50"):
        self.family = family
        self.region = region
        self.state, self.failure = state, failure
        self.initial_uid = None
        self.downloads = 0
        self.posts = 0

    async def post(self, raw):
        self.posts += 1
        root = ET.fromstring(raw)
        payload = next(iter(root.find(f"{{{SOAP_NS}}}Body")))
        uid = payload.findtext("index/id")
        if payload.tag.endswith("getDocsByOrgRegionRequest"):
            params = payload.find("selectionParams")
            assert params.findtext("documentType223") == self.family
            assert params.findtext("subsystemType") == "RI223"
            assert params.findtext("orgRegion") == self.region
            assert params.findtext("periodInfo/exactDate") == "2026-10-01+03:00"
            assert params.find("documentType44") is None
            self.initial_uid = uid
            self.url = (
                "https://int44.zakupki.gov.ru/dstore/common/download/compound"
                f"?docRequestUid={uid}&compoundUid={UID}"
            )
            if self.state == "NO_DATA":
                content = "<dataInfo><noData>true</noData></dataInfo>"
            else:
                content = (
                    "<dataInfo><archiveUrl>"
                    f"{self.url.replace('&', '&amp;')}</archiveUrl></dataInfo>"
                )
            result = _response("getDocsByOrgRegionResponse", content, uid)
            if self.failure == "initial_uid":
                result = result.replace(uid.encode(), b"22222222-2222-4222-8222-222222222222")
        else:
            assert payload.findtext("docRequestUid") == self.initial_uid
            content = f"<docRequestUid>{self.initial_uid}</docRequestUid>"
            if self.state == "SERVICE_ERROR":
                content += "<errorInfo><code>1</code><message>synthetic</message></errorInfo>"
            elif self.state == "PREPARING":
                content += (
                    "<dataInfo><isPreparationCompleted>false</isPreparationCompleted></dataInfo>"
                )
            else:
                link = (
                    self.url.replace(UID, "B" * 32) if self.failure == "archive_set" else self.url
                )
                content += (
                    "<dataInfo><isPreparationCompleted>true</isPreparationCompleted>"
                    "<preparedPartInfo><dsUid>"
                    f"{'B' * 32 if self.failure == 'archive_set' else UID}</dsUid>"
                    f"<url>{link.replace('&', '&amp;')}</url></preparedPartInfo></dataInfo>"
                )
            result = _response("getPreparedPartResponse", content, uid)
            if self.failure == "prepared_uid":
                result = result.replace(
                    f"<refId>{uid}".encode(), b"<refId>22222222-2222-4222-8222-222222222222"
                )
        return 200, result

    async def download(self, url, token):
        self.downloads += 1
        assert url == self.url and token == TOKEN
        if self.failure == "http":
            return 404, b"synthetic"
        raw = xml().replace(b"purchaseNoticeAESMBO", self.family.encode())
        if self.failure == "token":
            raw = raw.replace(b"synthetic", TOKEN.encode())
        if self.failure == "law":
            raw = raw.replace(b"purchaseNoticeAESMBO", b"purchaseNotice")
        return 200, zip_bytes([("notice.xml", raw)])


class MultiArchiveTransport:
    def __init__(self, count: int):
        self.count = count
        self.initial_uid = None
        self.downloads = 0
        self.posts = 0
        self.urls = ()

    async def post(self, raw):
        self.posts += 1
        root = ET.fromstring(raw)
        payload = next(iter(root.find(f"{{{SOAP_NS}}}Body")))
        uid = payload.findtext("index/id")
        if payload.tag.endswith("getDocsByOrgRegionRequest"):
            self.initial_uid = uid
            self.urls = tuple(
                "https://int44.zakupki.gov.ru/dstore/common/download/compound"
                f"?docRequestUid={uid}&compoundUid={index:032x}"
                for index in range(1, self.count + 1)
            )
            content = (
                "<dataInfo>"
                + "".join(
                    f"<archiveUrl>{source_url.replace('&', '&amp;')}</archiveUrl>"
                    for source_url in self.urls
                )
                + "</dataInfo>"
            )
            return 200, _response("getDocsByOrgRegionResponse", content, uid)
        content = f"<docRequestUid>{self.initial_uid}</docRequestUid>"
        content += "<dataInfo><isPreparationCompleted>true</isPreparationCompleted>"
        content += "".join(
            "<preparedPartInfo>"
            f"<dsUid>{index:032x}</dsUid>"
            f"<url>{source_url.replace('&', '&amp;')}</url>"
            "</preparedPartInfo>"
            for index, source_url in enumerate(self.urls, 1)
        )
        content += "</dataInfo>"
        return 200, _response("getPreparedPartResponse", content, uid)

    async def download(self, source_url, token):
        self.downloads += 1
        assert source_url in self.urls and token == TOKEN
        index = self.urls.index(source_url) + 1
        raw = xml().replace(b"32600000001", f"326{index:08d}".encode())
        return 200, zip_bytes([(f"notice-{index}.xml", raw)])


def fetch(transport, polls=1, family="purchaseNoticeAESMBO", region="50"):
    return asyncio.run(
        fetch_notice223_day(
            "tenant-a",
            date(2026, 10, 1),
            TOKEN,
            transport,
            region=region,
            document_type=family,
            poll_attempts=polls,
            poll_delay_seconds=0,
        )
    )


def test_verified_complete_window_returns_bytes_without_ingesting():
    transport = Transport()
    result = fetch(transport)
    assert result.status == "SYNCED" and result.window is not None
    assert result.window.response_sha256 == result.response_sha256 and transport.downloads == 1


def test_four_archive_source_window_downloads_and_preflights_as_one_set():
    transport = MultiArchiveTransport(4)
    result = fetch(transport)
    assert result.status == "SYNCED" and result.window is not None
    assert len(result.window.archives) == 4 and transport.downloads == 4


def test_eight_archive_source_window_downloads_as_one_complete_set():
    transport = MultiArchiveTransport(8)
    result = fetch(transport)
    assert result.status == "SYNCED" and result.window is not None
    assert len(result.window.archives) == transport.downloads == 8


def test_nine_archive_source_set_fails_before_any_download():
    transport = MultiArchiveTransport(9)
    with pytest.raises(ValueError, match="ARCHIVE_COUNT_LIMIT"):
        fetch(transport)
    assert transport.downloads == 0


def test_cumulative_compressed_limit_stops_before_next_download(monkeypatch):
    import procurement.sources.eis_223_sync as subject

    transport = MultiArchiveTransport(4)
    first_size = len(zip_bytes([("notice-1.xml", xml())]))
    monkeypatch.setattr(subject, "MAX_NOTICE_COMPRESSED_BYTES", first_size + 1)
    with pytest.raises(ValueError, match="WINDOW_BYTES_LIMIT"):
        fetch(transport)
    assert transport.downloads == 2


@pytest.mark.parametrize("state", ["NO_DATA", "PREPARING", "SERVICE_ERROR"])
def test_non_ready_observation_has_evidence_without_window_or_get(state):
    transport = Transport(state)
    result = fetch(transport, polls=2)
    assert result.status == state and result.window is None and transport.downloads == 0
    assert len(result.response_sha256) == 64
    assert transport.posts <= 3


@pytest.mark.parametrize(
    "failure", ["initial_uid", "prepared_uid", "archive_set", "http", "token", "law"]
)
def test_mismatched_source_or_rejected_archive_never_returns_partial_window(failure):
    transport = Transport(failure=failure)
    with pytest.raises(ValueError):
        fetch(transport)
    if failure in {"initial_uid", "prepared_uid", "archive_set"}:
        assert transport.downloads == 0


@pytest.mark.parametrize("polls", [0, 5])
def test_poll_budget_fails_before_source_call(polls):
    transport = Transport()
    with pytest.raises(ValueError, match="POLL_CONFIG_INVALID"):
        fetch(transport, polls)
    assert transport.posts == 0


def test_region_changes_exact_request_and_window_key():
    transport = Transport(state="NO_DATA", region="77")
    result = fetch(transport, region="77")
    assert result.status == "NO_DATA" and transport.posts == 1
    assert window_key(date(2026, 10, 1), region="77").split("/")[2] == "77"


@pytest.mark.parametrize("region", ["00", "1", "100", "٠١", " 50"])
def test_invalid_region_fails_before_notice_source_call(region):
    transport = Transport()
    with pytest.raises(ValueError, match="REGION_INVALID"):
        fetch(transport, region=region)
    assert transport.posts == transport.downloads == 0


@pytest.fixture
def runner():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts/server-eis-223-refresh.py"
    spec = importlib.util.spec_from_file_location("refresh223_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.quality_report = lambda storage: {"reason": "NOT_DUE", "source_requests": 0}
    return module


@pytest.mark.parametrize("guard", ["database", "disk", "not_due"])
def test_refresh_guards_stop_before_browser_creation(monkeypatch, runner, guard):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = (
        runner.MAX_DB_BYTES if guard == "database" else 1
    )
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr(runner, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(runner, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=1 if guard == "disk" else runner.MIN_FREE_BYTES + 1),
    )
    monkeypatch.setattr(runner, "due_windows", lambda *a, **k: ())

    def no_browser():
        pytest.fail("source session must not be created")

    monkeypatch.setattr(runner, "eis_browser_transport", no_browser)
    quality_calls = []
    monkeypatch.setattr(
        runner, "quality_report", lambda storage: quality_calls.append(storage) or {}
    )
    result = asyncio.run(runner.run())
    assert result["attempted"] == 0
    assert (
        result["reason"]
        == {
            "database": "DATABASE_BUDGET_REACHED",
            "disk": "DISK_RESERVE_REACHED",
            "not_due": "NOT_DUE",
        }[guard]
    )
    engine.dispose.assert_called_once()
    assert len(quality_calls) == (1 if guard == "not_due" else 0)


@pytest.mark.parametrize(
    ("failure_reason", "failure_sha", "expected_reason", "expected_sha"),
    [
        ("SECRETUPPERCASEVALUE", "SECRETUPPERCASEVALUE", "SYNC_FAILED", None),
        ("WINDOW_EXPANDED_LIMIT", "d" * 64, "WINDOW_EXPANDED_LIMIT", "d" * 64),
    ],
)
def test_refresh_stops_after_failure_and_never_logs_exception_secret(
    monkeypatch,
    runner,
    failure_reason,
    failure_sha,
    expected_reason,
    expected_sha,
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = 1
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", TOKEN)
    monkeypatch.setattr(runner, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(runner, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(
        runner.shutil, "disk_usage", lambda _: SimpleNamespace(free=runner.MIN_FREE_BYTES + 1)
    )
    monkeypatch.setattr(
        runner,
        "due_windows",
        lambda *a, **k: (
            Eis223RefreshTarget(date(2026, 10, 2), "purchaseNoticeAESMBO"),
            Eis223RefreshTarget(date(2026, 10, 1), "purchaseNoticeZKESMBO"),
        ),
    )
    calls = []

    @asynccontextmanager
    async def session():
        yield object()

    class SourceFailure(ValueError):
        source_response_sha256: str

    async def failed(*a, **k):
        calls.append("source")
        error = SourceFailure(failure_reason)
        error.source_response_sha256 = failure_sha
        raise error

    monkeypatch.setattr(runner, "eis_browser_transport", session)
    monkeypatch.setattr(runner, "fetch_notice223_day", failed)
    monkeypatch.setattr(runner, "record_attempt", lambda *a, **k: calls.append(k))
    result = asyncio.run(runner.run())
    assert result["attempted"] == 1 and calls[0] == "source" and len(calls) == 2
    assert result["outcomes"][0]["status"] == "FAILED"
    assert "SECRETUPPERCASEVALUE" not in str(result)
    assert calls[1]["reason"] == result["outcomes"][0]["reason"] == expected_reason
    assert calls[1]["response_sha256"] == expected_sha
    assert result["outcomes"][0]["response_sha256"] == expected_sha


def test_quotation_request_reader_and_source_window_are_exactly_bound():
    family = "purchaseNoticeZKESMBO"
    transport = Transport(family=family)
    result = fetch(transport, family=family)
    assert result.status == "SYNCED"
    assert result.window.window_key.endswith("/" + family)
    assert transport.downloads == 1


def test_general_runtime_request_is_exact_before_storage_admission():
    family = "purchaseNotice"
    transport = Transport(state="NO_DATA", family=family)
    result = fetch(transport, family=family)
    assert result.status == "NO_DATA" and result.window is None
    assert transport.posts == 1 and transport.downloads == 0


def test_quotation_selection_cannot_receive_auction_xml():
    transport = Transport(family="purchaseNoticeZKESMBO")
    original = transport.download

    async def wrong(*args):
        status, _ = await original(*args)
        return status, zip_bytes([("notice.xml", xml())])

    transport.download = wrong
    with pytest.raises(ValueError):
        fetch(transport, family=transport.family)


@pytest.mark.parametrize("family", ["epNotificationEA44", "", "purchaseNoticeZKESMBO/extra"])
def test_non_admitted_family_fails_before_any_source_post(family):
    transport = Transport()
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        fetch(transport, family=family)
    assert transport.posts == transport.downloads == 0


def test_refresh_batch_caps_two_windows_and_passes_their_exact_family(monkeypatch, runner):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = 1
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", TOKEN)
    monkeypatch.setattr(runner, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(runner, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(
        runner.shutil, "disk_usage", lambda _: SimpleNamespace(free=runner.MIN_FREE_BYTES + 1)
    )
    assert SUPPORTED_DOCUMENT_TYPES == (
        "purchaseNoticeAESMBO",
        "purchaseNoticeZKESMBO",
        "purchaseNotice",
        "purchaseNoticeKESMBO",
        "purchaseNoticeZPESMBO",
    )
    targets = tuple(
        Eis223RefreshTarget(day, family)
        for day in (date(2026, 10, 2), date(2026, 10, 1))
        for family in SUPPORTED_DOCUMENT_TYPES
    )
    monkeypatch.setattr(runner, "due_windows", lambda *a, **k: targets)
    calls, records = [], []

    @asynccontextmanager
    async def session():
        yield object()

    async def no_data(company, day, token, transport, *, document_type, region):
        assert region == "50"
        calls.append((day, document_type))
        return SimpleNamespace(status="NO_DATA", response_sha256="a" * 64)

    monkeypatch.setattr(runner, "eis_browser_transport", session)
    monkeypatch.setattr(runner, "fetch_notice223_day", no_data)
    monkeypatch.setattr(runner, "record_attempt", lambda *a, **k: records.append(a[2]))
    result = asyncio.run(runner.run())
    assert calls == [(target.day, target.document_type) for target in targets[:2]]
    assert (
        result["attempted"] == 2 and result["due_windows"] == 10 and result["deferred_windows"] == 8
    )
    assert len(records) == 2 and records[0].endswith("purchaseNoticeAESMBO")


@pytest.mark.parametrize("outcome", ["NO_DATA", "SYNCED"])
@pytest.mark.parametrize("family", ["purchaseRejection", "purchaseLotCancellation"])
def test_refresh_routes_event_window_without_notice_version(monkeypatch, runner, outcome, family):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from procurement.storage.eis_223_sync import Eis223EventRefreshTarget

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = 1
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", TOKEN)
    monkeypatch.setattr(runner, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(runner, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(
        runner.shutil, "disk_usage", lambda _: SimpleNamespace(free=runner.MIN_FREE_BYTES + 1)
    )
    targets = (
        Eis223EventRefreshTarget(date(2026, 10, 2), family),
        Eis223RefreshTarget(date(2026, 10, 2), "purchaseNotice"),
    )

    def due(*args, **kwargs):
        assert kwargs == {"include_events": True}
        return targets

    monkeypatch.setattr(runner, "due_windows", due)
    calls = []
    ready = object()

    @asynccontextmanager
    async def session():
        yield object()

    async def event_fetch(company, day, token, transport, *, region):
        assert region == "50"
        calls.append("event-source")
        return SimpleNamespace(
            status=outcome, response_sha256="a" * 64, window=ready if outcome == "SYNCED" else None
        )

    async def notice_fetch(*args, **kwargs):
        assert kwargs == {"document_type": "purchaseNotice", "region": "50"}
        calls.append("notice-source")
        return SimpleNamespace(status="NO_DATA", response_sha256="b" * 64)

    def ingest(storage, company, window, *, actor_id):
        assert window is ready
        calls.append("event-intake")
        return SimpleNamespace(new_events=1)

    monkeypatch.setattr(runner, "eis_browser_transport", session)
    monkeypatch.setattr(
        runner,
        "fetch_purchase_lot_cancellation_day"
        if family == "purchaseLotCancellation"
        else "fetch_purchase_rejection_day",
        event_fetch,
    )
    monkeypatch.setattr(runner, "fetch_notice223_day", notice_fetch)
    monkeypatch.setattr(
        runner,
        "ingest_lot_event223_window"
        if family == "purchaseLotCancellation"
        else "ingest_event223_window",
        ingest,
    )
    monkeypatch.setattr(runner, "record_attempt", lambda *a, **k: calls.append(a[2].split("/")[-1]))
    monkeypatch.setattr(runner, "quality_report", lambda *a: {})
    result = asyncio.run(runner.run())
    assert result["attempted"] == 2
    assert result["outcomes"][0]["new_versions"] == 0
    assert result["outcomes"][0]["new_events"] == (1 if outcome == "SYNCED" else 0)
    expected = ["event-source"] + (["event-intake"] if outcome == "SYNCED" else [])
    assert calls == [*expected, family, "notice-source", "purchaseNotice"]
