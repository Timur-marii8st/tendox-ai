"""One-hour sync must admit only a complete, correlated official response."""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from datetime import date
from io import BytesIO
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from procurement.sources.eis_feed_sync import (
    SOAP_NS,
    EisDateSelection,
    EisHourSelection,
    EisSyncError,
    _proxy_server,
    _request,
    sync_eis_hour,
    sync_eis_window,
)
from procurement.storage.eis_notice_index import EisIngestReport, preflight_ready_window


@pytest.mark.parametrize("configured,expected", [(None, 2.0), ("2", 2.0), ("1.25", 1.25)])
def test_browser_pacing_covers_posts_downloads_and_session_restarts(
    monkeypatch, configured, expected
):
    from procurement.sources import eis_feed_sync as module

    if configured is None:
        monkeypatch.delenv("EIS_BROWSER_REQUEST_GAP_SECONDS", raising=False)
    else:
        monkeypatch.setenv("EIS_BROWSER_REQUEST_GAP_SECONDS", configured)
    clock = 0.0
    starts = []
    requests = []

    async def sleep(seconds):
        nonlocal clock
        assert seconds == expected
        clock += seconds

    async def evaluate(script, argument):
        starts.append(clock)
        requests.append(argument)
        return 200

    class Pending:
        async def __aenter__(self):
            self.value = asyncio.get_running_loop().create_future()
            self.value.set_result(
                SimpleNamespace(
                    status=200, headers={}, body=AsyncMock(return_value=b"retained-bytes")
                )
            )
            return self

        async def __aexit__(self, *args):
            return False

    async def exercise():
        page = Mock(
            evaluate=AsyncMock(side_effect=evaluate),
            expect_response=Mock(side_effect=lambda *a, **kw: Pending()),
        )
        for index in range(3000):
            # Recreating the browser must not bypass the first-call delay.
            transport = module._BrowserTransport(page)
            if index % 3:
                result = await transport.post(b"<unchanged-request/>")
            else:
                result = await transport.download(
                    "https://int.zakupki.gov.ru/archive.zip", "private-token"
                )
            assert result == (200, b"retained-bytes")

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    asyncio.run(exercise())
    assert starts[0] == expected
    assert all(b - a == expected for a, b in pairwise(starts))
    assert requests[0]["token"] == "private-token"
    assert requests[1]["xml"] == "<unchanged-request/>"
    # Closed rolling intervals deliberately count both boundary requests.
    for period, limit in [(60, 49), (3600, 2881)]:
        active = deque()
        for at in starts:
            active.append(at)
            while active[0] < at - period:
                active.popleft()
            assert len(active) <= limit


@pytest.mark.parametrize("configured", ["", "0", "1", "1.249", "nan", "inf", "-2", "2.0"])
def test_browser_pacing_rejects_unapproved_values_before_source_io(monkeypatch, configured):
    from procurement.sources import eis_feed_sync as module

    monkeypatch.setenv("EIS_BROWSER_REQUEST_GAP_SECONDS", configured)
    page = Mock()
    with pytest.raises(EisSyncError, match=r"^REQUEST_PACING_INVALID$"):
        module._BrowserTransport(page)
    assert not page.mock_calls


@pytest.fixture(autouse=True)
def disable_real_no_data_store(monkeypatch):
    # Synthetic fixtures must never enter a developer/server persistent volume.
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", "")


def test_browser_session_is_lazy_reuses_origin_and_closes_on_cancel(monkeypatch) -> None:
    from procurement.sources import eis_feed_sync as module

    class BrowserError(Exception):
        pass

    browser = Mock(new_page=AsyncMock(), close=AsyncMock())
    page = Mock(url=module.WSDL, goto=AsyncMock(return_value=SimpleNamespace(status=200)))
    browser.new_page.return_value = page
    chromium = Mock(launch=AsyncMock(return_value=browser))
    manager = Mock(
        __aenter__=AsyncMock(return_value=SimpleNamespace(chromium=chromium)),
        __aexit__=AsyncMock(return_value=False),
    )
    monkeypatch.setitem(
        sys.modules,
        "playwright.async_api",
        SimpleNamespace(
            Error=BrowserError, TimeoutError=BrowserError, async_playwright=lambda: manager
        ),
    )
    monkeypatch.setattr(module, "_proxy_server", lambda: None)
    post = AsyncMock(return_value=(200, b"synthetic"))
    monkeypatch.setattr(module._BrowserTransport, "post", post)

    async def exercise():
        async with module.eis_browser_transport():
            pass
        chromium.launch.assert_not_awaited()
        with pytest.raises(asyncio.CancelledError):
            async with module.eis_browser_transport() as transport:
                assert await transport.post(b"one") == (200, b"synthetic")
                await transport.post(b"two")
                assert chromium.launch.await_count == page.goto.await_count == 1
                raise asyncio.CancelledError()

    asyncio.run(exercise())
    assert post.await_count == 2
    browser.close.assert_awaited_once()
    manager.__aexit__.assert_awaited_once()


def test_browser_session_maps_request_failure_and_closes(monkeypatch) -> None:
    from procurement.sources import eis_feed_sync as module

    class BrowserError(Exception):
        pass

    page = Mock(url=module.WSDL, goto=AsyncMock(return_value=SimpleNamespace(status=200)))
    browser = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock())
    manager = Mock(
        __aenter__=AsyncMock(
            return_value=SimpleNamespace(chromium=Mock(launch=AsyncMock(return_value=browser)))
        ),
        __aexit__=AsyncMock(return_value=False),
    )
    monkeypatch.setitem(
        sys.modules,
        "playwright.async_api",
        SimpleNamespace(
            Error=BrowserError, TimeoutError=BrowserError, async_playwright=lambda: manager
        ),
    )
    monkeypatch.setattr(module, "_proxy_server", lambda: None)
    monkeypatch.setattr(
        module._BrowserTransport, "post", AsyncMock(side_effect=BrowserError("secret"))
    )

    async def exercise():
        async with module.eis_browser_transport() as transport:
            with pytest.raises(EisSyncError, match=r"^SOURCE_TRANSPORT_FAILED$"):
                await transport.post(b"one")

    asyncio.run(exercise())
    browser.close.assert_awaited_once()


TOKEN = "11111111-1111-4111-8111-111111111111"
NS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"
RESP = "22222222-2222-4222-8222-222222222222"
UID = "A" * 32
SELECTION = EisHourSelection("50", date(2026, 9, 25), 17, 3)


@pytest.mark.parametrize(
    "value",
    [
        "socks5://user:secret@proxy:1080",
        "ftp://proxy:21",
        "http://proxy",
        "http://proxy:bad",
        "http://proxy:80/path",
        "http://proxy:80?secret=x",
    ],
)
def test_proxy_rejects_credentials_and_invalid_routes(monkeypatch, value: str) -> None:
    monkeypatch.setenv("EIS_BROWSER_PROXY", value)
    with pytest.raises(EisSyncError, match=r"^PROXY_CONFIG_INVALID$"):
        _proxy_server()


def test_proxy_is_explicit_and_optional(monkeypatch) -> None:
    monkeypatch.delenv("EIS_BROWSER_PROXY", raising=False)
    assert _proxy_server() is None
    monkeypatch.setenv("EIS_BROWSER_PROXY", "socks5://eis-proxy:1080")
    assert _proxy_server() == "socks5://eis-proxy:1080"


def test_quotation_request_uses_selected_type_and_distinct_checkpoint() -> None:
    selection = EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationEZK2020")
    request = ET.fromstring(_request(TOKEN, "request", selection=selection))
    params = request.find(f"{{{SOAP_NS}}}Body/{{{NS}}}getDocsByOrgRegionRequest/selectionParams")
    assert params is not None
    assert params.findtext("documentType44") == "epNotificationEZK2020"
    assert selection.window_key.endswith("/epNotificationEZK2020")
    with pytest.raises(ValueError, match="SOURCE_WINDOW_INVALID"):
        EisDateSelection("50", date(2026, 9, 25), 3, "unknown")


def _response(name: str, content: str, ref: str) -> bytes:
    return (
        f'<e:{name} xmlns:e="{NS}"><index><id>{RESP}</id><refId>{ref}</refId>'
        "<createDateTime>2026-09-27T12:00:00</createDateTime><mode>PROD</mode>"
        f"</index>{content}</e:{name}>"
    ).encode()


def _archive() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "notice.xml",
            b'<export xmlns="http://zakupki.gov.ru/oos/export/1">'
            b"<epNotificationEF2020><versionNumber>1</versionNumber>"
            b"<commonInfo><purchaseNumber>0848300054826000154</purchaseNumber>"
            b"<purchaseObjectInfo>Paper</purchaseObjectInfo></commonInfo>"
            b"<notificationInfo/></epNotificationEF2020></export>",
        )
    return buffer.getvalue()


class FakeTransport:
    def __init__(
        self,
        *,
        state: str = "READY",
        wrong_request: bool = False,
        ready_url_changed: bool = False,
        expect_date: bool = False,
        download_statuses: tuple[int, ...] = (200,),
    ) -> None:
        self.state = state
        self.wrong_request = wrong_request
        self.ready_url_changed = ready_url_changed
        self.expect_date = expect_date
        self.download_statuses = download_statuses
        self.posts = 0
        self.downloads = 0
        self.original_request_id = ""
        self.url = ""
        self.prepared_url = ""

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        assert TOKEN.encode() in xml
        self.posts += 1
        root = ET.fromstring(xml)
        method = next(item for item in root.iter() if item.tag.startswith(f"{{{NS}}}"))
        if method.tag.endswith("getDocsByOrgRegionRequest"):
            self.original_request_id = method.findtext("index/id") or ""
            assert method.findtext("selectionParams/documentType44") == "epNotificationEF2020"
            if self.expect_date:
                assert method.findtext("selectionParams/periodInfo/exactDate") == "2026-09-25+03:00"
                assert method.find("selectionParams/periodInfo/oneHourInfo") is None
            else:
                assert (
                    method.findtext("selectionParams/periodInfo/oneHourInfo/offsetTimeZone") == "+3"
                )
            self.url = (
                "https://int.zakupki.gov.ru/dstore/common/download/compound"
                f"?docRequestUid={self.original_request_id}&compoundUid={UID}"
            )
            if self.state == "NO_DATA":
                content = "<dataInfo><noData>true</noData></dataInfo>"
            else:
                content = (
                    f"<dataInfo><archiveUrl>{self.url.replace('&', '&amp;')}"
                    "</archiveUrl></dataInfo>"
                )
            return 200, _response("getDocsByOrgRegionResponse", content, self.original_request_id)
        assert method.tag.endswith("getPreparedPartRequest")
        original = method.findtext("docRequestUid")
        assert original == self.original_request_id
        if self.state == "PREPARING":
            content = (
                f"<docRequestUid>{original}</docRequestUid><dataInfo>"
                "<isPreparationCompleted>false</isPreparationCompleted></dataInfo>"
            )
        else:
            correlated = RESP if self.wrong_request else original
            prepared_url = self.url.replace(original, correlated)
            if self.ready_url_changed:
                prepared_url = prepared_url.replace(
                    "https://int.zakupki.gov.ru", "https://int44.zakupki.gov.ru"
                )
            self.prepared_url = prepared_url
            content = (
                f"<docRequestUid>{correlated}</docRequestUid><dataInfo>"
                "<isPreparationCompleted>true</isPreparationCompleted>"
                f"<preparedPartInfo><dsUid>{UID}</dsUid>"
                f"<url>{prepared_url.replace('&', '&amp;')}</url></preparedPartInfo></dataInfo>"
            )
        poll_request_id = method.findtext("index/id") or ""
        return 200, _response("getPreparedPartResponse", content, poll_request_id)

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        assert (url, token) == (self.prepared_url, TOKEN)
        self.downloads += 1
        status = self.download_statuses[min(self.downloads - 1, len(self.download_statuses) - 1)]
        return status, _archive() if status == 200 else b"not ready"


def test_hour_request_and_successful_complete_sync() -> None:
    transport = FakeTransport(ready_url_changed=True)
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
    ):
        ingest.return_value = EisIngestReport(SELECTION.window_key, 1, 1, 1, False)
        result = asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, transport))
        bound = ingest.call_args.args[2]
    assert result.status == "SYNCED" and result.notice_count == 1
    assert result.corpus_coverage == "UNKNOWN"
    assert transport.posts == 2 and transport.downloads == 1
    assert bound.window_key == SELECTION.window_key
    assert bound.archives == (_archive(),)


@pytest.mark.parametrize("sink", ["disabled", "retained", "audit_failure", "sink_failure"])
def test_rejected_window_preserves_original_conflict_and_complete_source_provenance(
    monkeypatch, sink
):
    from procurement.sources import eis_feed_sync as module
    from procurement.sources.eis_feed_archive import EisFeedArchiveError

    transport = FakeTransport()
    retained = Mock(
        return_value=SimpleNamespace(status="DISABLED" if sink == "disabled" else "RETAINED")
    )
    if sink == "sink_failure":
        retained.side_effect = RuntimeError("secret-sink-details")
    audit = Mock(side_effect=RuntimeError("secret-db-details") if sink == "audit_failure" else None)
    monkeypatch.setattr(module, "has_ingested_window", lambda *a: False)
    ingest = Mock(side_effect=EisFeedArchiveError("DUPLICATE_NOTICE_VERSION"))
    monkeypatch.setattr(module, "ingest_ready_window", ingest)
    monkeypatch.setattr(module, "retain_rejected_window", retained)
    monkeypatch.setattr(module, "record_rejected_evidence", audit)
    with pytest.raises(
        module.EisRejectedWindowError, match=r"^DUPLICATE_NOTICE_VERSION$"
    ) as caught:
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, transport))
    error = caught.value
    assert error.source_response_sha256 == retained.call_args.args[0].response_sha256
    assert retained.call_args.args[0].archives == (_archive(),)
    assert transport.posts == 2 and transport.downloads == 1 and ingest.call_count == 1
    assert error.audit_status == (
        "NOT_REQUIRED"
        if sink == "disabled"
        else "FAILED"
        if sink in {"audit_failure", "sink_failure"}
        else "RECORDED"
    )
    assert "secret" not in str(error)
    assert audit.call_count == (0 if sink in {"disabled", "sink_failure"} else 1)


def test_other_rejections_never_enter_duplicate_retention(monkeypatch):
    from procurement.sources import eis_feed_sync as module
    from procurement.sources.eis_feed_archive import EisFeedArchiveError

    monkeypatch.setattr(module, "has_ingested_window", lambda *a: False)
    monkeypatch.setattr(
        module, "ingest_ready_window", Mock(side_effect=EisFeedArchiveError("MEMBER_UNSUPPORTED"))
    )
    retained = Mock()
    monkeypatch.setattr(module, "retain_rejected_window", retained)
    with pytest.raises(EisFeedArchiveError, match="MEMBER_UNSUPPORTED"):
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, FakeTransport()))
    retained.assert_not_called()


@pytest.mark.parametrize("failure", [None, "classify", "audit"])
def test_diagnosis_requires_audited_retention_and_never_changes_rejection(monkeypatch, failure):
    from procurement.sources import eis_feed_sync as module
    from procurement.storage.eis_notice_index import EisReadyWindow

    evidence = SimpleNamespace(status="RETAINED", manifest_sha256="d" * 64, retention_reason=None)
    inspected = SimpleNamespace(
        sha256="e" * 64,
        safe_summary=lambda: {
            "status": "COMPLETE",
            "coverage": "UNKNOWN",
            "diagnosis_sha256": "e" * 64,
            "divergent_groups": 1,
        },
    )
    monkeypatch.setattr(module, "retain_rejected_window", Mock(return_value=evidence))
    retained_audit = Mock()
    monkeypatch.setattr(module, "record_rejected_evidence", retained_audit)
    classify = Mock(
        return_value=inspected,
        side_effect=RuntimeError("secret-xml") if failure == "classify" else None,
    )
    audit = Mock(side_effect=RuntimeError("secret-db") if failure == "audit" else None)
    monkeypatch.setattr(module, "diagnose_notice_conflicts", classify)
    monkeypatch.setattr(module, "record_notice_conflict_diagnosis", audit)
    window = EisReadyWindow("getDocsIP/PRIZ/77/2026-09-29+03:00", "a" * 64, 1, (_archive(),))
    error = module.rejection_error(
        None, "tenant-a", "worker", window, TOKEN, "DUPLICATE_NOTICE_VERSION"
    )
    assert str(error) == "DUPLICATE_NOTICE_VERSION" and error.audit_status == "RECORDED"
    assert classify.call_args.args == (window.archives, TOKEN)
    assert error.diagnosis_audit_status == ("FAILED" if failure else "RECORDED")
    summary = error.safe_metadata()["conflict_diagnosis"]
    assert summary["coverage"] == "UNKNOWN"
    assert summary["status"] == ("UNAVAILABLE" if failure else "COMPLETE")
    assert "secret" not in str(error.safe_metadata())
    assert audit.call_count == (0 if failure == "classify" else 1)
    retained_audit.side_effect = RuntimeError("secret-retention")
    classify.reset_mock()
    audit.reset_mock()
    error = module.rejection_error(
        None, "tenant-a", "worker", window, TOKEN, "DUPLICATE_NOTICE_VERSION"
    )
    assert error.audit_status == "FAILED" and error.diagnosis_audit_status == "NOT_REQUIRED"
    classify.assert_not_called()
    audit.assert_not_called()


def test_exact_date_backfill_uses_separate_checkpoint_and_complete_archive() -> None:
    selection = EisDateSelection("50", date(2026, 9, 25), 3)
    transport = FakeTransport(expect_date=True)
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
    ):
        ingest.return_value = EisIngestReport(selection.window_key, 1, 1, 1, False)
        result = asyncio.run(
            sync_eis_window(None, "tenant-a", "worker", selection, TOKEN, transport)
        )
        bound = ingest.call_args.args[2]
    assert result.status == "SYNCED"
    assert selection.window_key == "getDocsIP/PRIZ/50/2026-09-25+03:00"
    assert preflight_ready_window(bound).notice_count == 1


def test_completed_window_skips_source_and_no_data_is_not_checkpointed() -> None:
    skipped = FakeTransport()
    with patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=True):
        result = asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, skipped))
    assert result.status == "SKIPPED" and skipped.posts == 0
    no_data = FakeTransport(state="NO_DATA")
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
    ):
        result = asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, no_data))
        ingest.assert_not_called()
    assert result.status == "NO_DATA" and result.corpus_coverage == "UNKNOWN"


def test_no_data_body_retained_audited_and_cli_serializable(tmp_path, monkeypatch):
    import json

    from procurement.sources.eis_no_data_evidence import verify_no_data_reply

    root = tmp_path / "private"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(root))
    transport = FakeTransport(state="NO_DATA")
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
        patch(
            "procurement.sources.eis_feed_sync.record_no_data_evidence", return_value="audit-id"
        ) as audit,
    ):
        result = asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, transport))
    ingest.assert_not_called()
    assert transport.posts == 1 and transport.downloads == 0
    assert result.status == "NO_DATA" and result.corpus_coverage == "UNKNOWN"
    assert result.no_data_retention_status == "RETAINED"
    assert result.no_data_retention_audit_status == "RECORDED"
    assert TOKEN not in json.dumps(result.__dict__)
    receipt = audit.call_args.args[2]
    verified = verify_no_data_reply(
        root, "tenant-a", SELECTION.window_key, result.source_response_sha256
    )
    assert (
        verified.status == "PASS"
        and verified.manifest.request_id.hex == transport.original_request_id.replace("-", "")
    )
    assert receipt.manifest_sha256 == verified.manifest_sha256 == result.no_data_manifest_sha256


def test_no_data_failed_audit_does_not_become_successful_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(tmp_path / "private"))
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch(
            "procurement.sources.eis_feed_sync.record_no_data_evidence",
            side_effect=RuntimeError("opaque"),
        ),
    ):
        result = asyncio.run(
            sync_eis_hour(
                None, "tenant-a", "worker", SELECTION, TOKEN, FakeTransport(state="NO_DATA")
            )
        )
    assert (
        result.no_data_retention_status == "RETAINED"
        and result.no_data_retention_audit_status == "FAILED"
    )
    assert result.status == "NO_DATA" and result.corpus_coverage == "UNKNOWN"


def test_no_data_quota_failure_audited_and_observation_stays_unknown(tmp_path, monkeypatch):
    from procurement.sources import eis_no_data_evidence as evidence

    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(evidence, "MAX_RECORDS", 0)
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch(
            "procurement.sources.eis_feed_sync.record_no_data_evidence", return_value="audit-id"
        ) as audit,
    ):
        result = asyncio.run(
            sync_eis_hour(
                None, "tenant-a", "worker", SELECTION, TOKEN, FakeTransport(state="NO_DATA")
            )
        )
    assert (
        result.no_data_retention_status == "FAILED"
        and result.no_data_retention_reason == "QUOTA_REACHED"
    )
    assert audit.call_args.args[2].status == "FAILED"
    assert result.status == "NO_DATA" and result.corpus_coverage == "UNKNOWN"


def test_refresh_reads_completed_window_and_retains_response_evidence() -> None:
    transport = FakeTransport()
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=True),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
    ):
        ingest.return_value = EisIngestReport(SELECTION.window_key, 1, 1, 0, True)
        result = asyncio.run(
            sync_eis_window(None, "tenant-a", "worker", SELECTION, TOKEN, transport, refresh=True)
        )
        assert result.source_response_sha256 == ingest.call_args.args[2].response_sha256
    assert transport.posts == 2 and transport.downloads == 1
    assert result.status == "SYNCED" and result.new_versions == 0
    assert result.corpus_coverage == "UNKNOWN"


def test_pending_or_wrong_prepared_response_never_ingests() -> None:
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
    ):
        pending = asyncio.run(
            sync_eis_hour(
                None,
                "tenant-a",
                "worker",
                SELECTION,
                TOKEN,
                FakeTransport(state="PREPARING"),
                poll_attempts=2,
                poll_delay_seconds=0,
            )
        )
        assert pending.status == "PREPARING"
        with pytest.raises(EisSyncError, match="PREPARED_REQUEST_MISMATCH"):
            asyncio.run(
                sync_eis_hour(
                    None, "tenant-a", "worker", SELECTION, TOKEN, FakeTransport(wrong_request=True)
                )
            )
        ingest.assert_not_called()


def test_invalid_selection_or_credential_is_rejected_before_network() -> None:
    with pytest.raises(ValueError, match="SOURCE_WINDOW_INVALID"):
        EisHourSelection("50", date(2026, 9, 25), 24, 3)
    with pytest.raises(EisSyncError, match="REQUEST_CONFIG_INVALID"):
        _request("bad", "id", selection=SELECTION)
    with pytest.raises(EisSyncError, match="SYNC_CONFIG_INVALID"):
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, "bad", FakeTransport()))


def test_archive_eventual_consistency_retries_only_temporary_status() -> None:
    transport = FakeTransport(download_statuses=(404, 200))
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
    ):
        ingest.return_value = EisIngestReport(SELECTION.window_key, 1, 1, 1, False)
        result = asyncio.run(
            sync_eis_hour(
                None,
                "tenant-a",
                "worker",
                SELECTION,
                TOKEN,
                transport,
                archive_retry_delay_seconds=0,
            )
        )
    assert result.status == "SYNCED" and transport.downloads == 2
    denied = FakeTransport(download_statuses=(403,))
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        pytest.raises(EisSyncError, match="ARCHIVE_DOWNLOAD_HTTP_403"),
    ):
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, denied))
    assert denied.downloads == 1


def test_window_budget_stops_download_without_checkpoint() -> None:
    too_many = FakeTransport()
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.MAX_WINDOW_ARCHIVES", 0),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
        pytest.raises(EisSyncError, match="ARCHIVE_WINDOW_COUNT_LIMIT"),
    ):
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, too_many))
    assert too_many.downloads == 0
    ingest.assert_not_called()

    oversized = FakeTransport()
    with (
        patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
        patch("procurement.sources.eis_feed_sync.MAX_WINDOW_COMPRESSED_BYTES", 1),
        patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
        pytest.raises(EisSyncError, match="ARCHIVE_WINDOW_SIZE_LIMIT"),
    ):
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, oversized))
    assert oversized.downloads == 1
    ingest.assert_not_called()


@pytest.mark.parametrize(
    "reason",
    [
        "DUPLICATE_NOTICE_VERSION",
        "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
        "NOTICE_VERSION_CONFLICT",
        "TRANSPORT_WINDOW_NOT_CANONICAL",
    ],
)
@pytest.mark.parametrize("replayed", [False, True])
def test_conflict_hook_reuses_archives_and_preserves_rejection(monkeypatch, reason, replayed):
    from procurement.sources import eis_feed_sync as module
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport
    from procurement.storage.eis_notice_index import EisIndexConflict
    from procurement.storage.eis_notice_projection import EisNoticeProjectionReport

    transport = FakeTransport()
    evidence = SimpleNamespace(status="RETAINED", manifest_sha256="d" * 64, retention_reason=None)
    diagnosis = SimpleNamespace(safe_summary=lambda: {"coverage": "UNKNOWN"})
    projected = EisNoticeProjectionReport(
        batch_id="batch",
        receipt_id="receipt",
        archive_count=1,
        occurrence_count=2,
        pair_count=1,
        projected_count=1,
        replayed_count=0,
        held_count=0,
        replayed=replayed,
        audit_event_id="projection-audit",
    )
    partial = EisVariantIntakeReport(
        status="PARTIAL",
        stage="COMPLETE",
        reason=None,
        ledger_receipt_id="receipt",
        ledger_audit_event_id="ledger-audit",
        projection=projected,
    )
    intake = Mock(return_value=partial)
    monkeypatch.setattr(module, "has_ingested_window", lambda *args: False)
    monkeypatch.setattr(module, "ingest_ready_window", Mock(side_effect=EisIndexConflict(reason)))
    retained = Mock(return_value=evidence)
    monkeypatch.setattr(module, "retain_rejected_window", retained)
    reuse = Mock(return_value=(SimpleNamespace(evidence=evidence), diagnosis))
    monkeypatch.setattr(module, "read_reusable_notice_transport", reuse)
    monkeypatch.setattr(module, "record_rejected_evidence", Mock())
    monkeypatch.setattr(module, "diagnose_notice_conflicts", Mock(return_value=diagnosis))
    monkeypatch.setattr(module, "record_notice_conflict_diagnosis", Mock())
    monkeypatch.setattr(module, "intake_notice_variants", intake)
    with pytest.raises(module.EisRejectedWindowError, match=f"^{reason}$") as caught:
        asyncio.run(sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, transport))
    error = caught.value
    assert transport.posts == 2 and transport.downloads == 1
    if reason == "TRANSPORT_WINDOW_NOT_CANONICAL":
        window = reuse.call_args.args[2]
        retained.assert_not_called()
        module.record_rejected_evidence.assert_not_called()
        module.diagnose_notice_conflicts.assert_not_called()
        module.record_notice_conflict_diagnosis.assert_not_called()
    else:
        window = retained.call_args.args[0]
        reuse.assert_not_called()
    assert intake.call_args.args == (None, "tenant-a", evidence, diagnosis, window.archives)
    assert intake.call_args.args[-1] is window.archives
    assert error.variant_intake.new_versions == (0 if replayed else 1)
    assert error.safe_metadata()["variant_intake"] == partial.model_dump(mode="json")
    assert error.safe_metadata()["reason"] == reason


@pytest.mark.parametrize("stage", ["disabled", "retention", "diagnosis", "failed_sink"])
def test_intake_hook_requires_both_successful_audits(monkeypatch, stage):
    from sqlalchemy.exc import OperationalError

    from procurement.sources import eis_feed_sync as module
    from procurement.storage.eis_notice_index import EisReadyWindow

    evidence = SimpleNamespace(
        status="DISABLED"
        if stage == "disabled"
        else "FAILED"
        if stage == "failed_sink"
        else "RETAINED"
    )
    monkeypatch.setattr(module, "retain_rejected_window", Mock(return_value=evidence))
    failure = OperationalError("secret-sql", {"password": "secret"}, RuntimeError("dsn"))
    monkeypatch.setattr(
        module,
        "record_rejected_evidence",
        Mock(side_effect=failure if stage == "retention" else None),
    )
    monkeypatch.setattr(module, "diagnose_notice_conflicts", Mock(return_value=object()))
    monkeypatch.setattr(
        module,
        "record_notice_conflict_diagnosis",
        Mock(side_effect=failure if stage == "diagnosis" else None),
    )
    intake = Mock()
    monkeypatch.setattr(module, "intake_notice_variants", intake)
    window = EisReadyWindow("getDocsIP/PRIZ/77/2026-09-29+03:00", "a" * 64, 1, (_archive(),))
    error = module.rejection_error(
        None, "tenant-a", "worker", window, TOKEN, "NOTICE_VERSION_CONFLICT"
    )
    intake.assert_not_called()
    report = error.variant_intake
    if stage == "disabled":
        assert report.status == "NOT_ATTEMPTED"
    else:
        assert report.status == "FAILED"
        assert report.reason == (
            "RETENTION_FAILED" if stage == "failed_sink" else "DATABASE_FAILED"
        )
    assert "secret" not in report.model_dump_json() and "dsn" not in report.model_dump_json()
    assert str(error) == "NOTICE_VERSION_CONFLICT"


def test_manually_constructed_rejection_defaults_to_not_attempted():
    from procurement.sources.eis_feed_sync import EisRejectedWindowError

    error = EisRejectedWindowError("NOTICE_VERSION_CONFLICT", "a" * 64, None, "NOT_REQUIRED")
    assert error.variant_intake.status == "NOT_ATTEMPTED"
    assert error.variant_intake.new_versions == 0
    assert error.safe_metadata()["variant_intake"]["coverage"] == "UNKNOWN"


@pytest.mark.parametrize("database", [False, True])
def test_transport_reuse_failure_never_falls_back_to_new_retention(monkeypatch, database):
    from sqlalchemy.exc import OperationalError

    from procurement.sources import eis_feed_sync as module
    from procurement.storage.eis_notice_index import EisReadyWindow

    failure = (
        OperationalError("secret SQL", {}, RuntimeError("secret DSN"))
        if database
        else ValueError("SECRET_BINDING_DETAILS")
    )
    monkeypatch.setattr(module, "read_reusable_notice_transport", Mock(side_effect=failure))
    operations = [
        "retain_rejected_window",
        "record_rejected_evidence",
        "diagnose_notice_conflicts",
        "record_notice_conflict_diagnosis",
        "intake_notice_variants",
    ]
    for operation in operations:
        monkeypatch.setattr(module, operation, Mock())
    window = EisReadyWindow("getDocsIP/PRIZ/77/2026-09-29+03:00", "a" * 64, 1, (_archive(),))
    error = module.rejection_error(
        None, "tenant-a", "worker", window, TOKEN, "TRANSPORT_WINDOW_NOT_CANONICAL"
    )
    assert str(error) == "TRANSPORT_WINDOW_NOT_CANONICAL"
    assert error.source_response_sha256 == window.response_sha256
    assert error.evidence is None and error.audit_status == "NOT_REQUIRED"
    assert error.variant_intake.status == "FAILED" and error.variant_intake.stage == "DIAGNOSIS"
    assert error.variant_intake.reason == ("DATABASE_FAILED" if database else "DIAGNOSIS_FAILED")
    assert "secret" not in str(error.safe_metadata()).lower()
    for operation in operations:
        getattr(module, operation).assert_not_called()
