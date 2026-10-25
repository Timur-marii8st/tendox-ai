"""Отказы источника не теряют код и не раскрывают сообщения/секреты."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_event_sync import fetch_purchase_rejection_day
from procurement.sources.eis_223_lot_event_sync import fetch_purchase_lot_cancellation_day
from procurement.sources.eis_223_sync import fetch_notice223_day
from procurement.sources.eis_feed_sync import EisSyncError, _parsed_post
from test_eis_feed_sync import SOAP_NS, TOKEN, _response


@pytest.mark.parametrize(
    "fetcher",
    [fetch_notice223_day, fetch_purchase_rejection_day, fetch_purchase_lot_cancellation_day],
)
@pytest.mark.parametrize("phase", ["INITIAL", "PREPARED"])
def test_service_code_survives_both_response_phases(fetcher, phase):
    class Transport:
        async def post(self, raw):
            p = next(iter(ET.fromstring(raw).find(f"{{{SOAP_NS}}}Body")))
            uid = p.findtext("index/id")
            info = "<errorInfo><code>13</code><message>private-message</message></errorInfo>"
            if p.tag.endswith("getDocsByOrgRegionRequest"):
                self.uid = uid
                content = (
                    f"<dataInfo>{info}</dataInfo>"
                    if phase == "INITIAL"
                    else (
                        "<dataInfo><archiveUrl>https://int.zakupki.gov.ru/dstore/common/download/compound"
                        f"?docRequestUid={uid}&amp;compoundUid={'A' * 32}</archiveUrl></dataInfo>"
                    )
                )
                return 200, _response("getDocsByOrgRegionResponse", content, uid)
            return 200, _response(
                "getPreparedPartResponse", f"<docRequestUid>{self.uid}</docRequestUid>{info}", uid
            )

    result = asyncio.run(
        fetcher("tenant", date(2026, 10, 1), TOKEN, Transport(), poll_delay_seconds=0)
    )
    assert result.status == "SERVICE_ERROR"
    assert result.source_error.service_code == 13
    assert result.source_error.phase == phase
    assert "private-message" not in repr(result)
    assert result.source_error.persisted_reason("SERVICE_ERROR") == f"SERVICE_ERROR_{phase}_CODE_13"


@pytest.mark.parametrize(
    "status,raw,category",
    [
        (503, b"private-message", "HTTP_STATUS"),
        (200, TOKEN.encode(), "TOKEN_REFLECTION"),
        (200, b"x" * (2 * 1024 * 1024 + 1), "RESPONSE_SIZE"),
    ],
    ids=["http", "reflection", "size"],
)
def test_rejected_response_preserves_safe_subtype(status, raw, category):
    transport = AsyncMock()
    transport.post.return_value = status, raw
    with pytest.raises(EisSyncError, match=r"^SOURCE_RESPONSE_REJECTED$") as caught:
        asyncio.run(_parsed_post(transport, b"request", TOKEN))
    detail = caught.value.source_error
    assert detail.http_status == status and detail.category == category
    assert TOKEN not in repr(detail) and "private-message" not in repr(detail)


@pytest.mark.parametrize("phase", ["WSDL", "SOAP", "ARCHIVE"])
def test_browser_failure_keeps_phase_and_allowlisted_code(monkeypatch, phase):
    import sys
    from contextlib import AsyncExitStack
    from types import SimpleNamespace

    from procurement.sources import eis_feed_sync as m

    class BrowserError(Exception):
        pass

    class BrowserTimeout(BrowserError):
        pass

    monkeypatch.setitem(
        sys.modules,
        "playwright.async_api",
        SimpleNamespace(Error=BrowserError, TimeoutError=BrowserTimeout),
    )
    error = BrowserError("net::ERR_CONNECTION_CLOSED https://secret/ " + TOKEN)

    async def exercise():
        async with AsyncExitStack() as stack:
            session = m._BrowserSession(stack)
            transport = SimpleNamespace(
                post=AsyncMock(side_effect=error), download=AsyncMock(side_effect=error)
            )

            async def ready():
                if phase == "WSDL":
                    session.phase = "WSDL"
                    raise error
                return transport

            session._ready = ready
            with pytest.raises(EisSyncError) as caught:
                await session._invoke(xml=b"request" if phase != "ARCHIVE" else None)
            detail = caught.value.source_error
            assert detail.phase == phase and detail.network_code == "ERR_CONNECTION_CLOSED"
            assert TOKEN not in repr(detail) and "https://secret" not in repr(detail)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "field,value",
    [
        ("network_code", "SECRET"),
        ("http_status", 999),
        ("phase", "SECRET"),
        ("service_code", 10**30),
        ("service_code", True),
    ],
)
def test_unsafe_error_metadata_is_rejected(field, value):
    from procurement.sources.eis_feed_sync import EisSourceError

    with pytest.raises(ValueError):
        EisSourceError(**({"phase": "SOAP"} | {field: value}))


@pytest.mark.parametrize("failure", ["service", "transport", "http"])
def test_refresh_persists_same_safe_reason_as_report(monkeypatch, failure):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from procurement.sources.eis_223_sync import Eis223Observation, Eis223RefreshTarget
    from procurement.sources.eis_feed_sync import EisSourceError
    from test_eis_223_sync import runner as runner_fixture

    runner = runner_fixture.__wrapped__()
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
        lambda *a, **k: (Eis223RefreshTarget(date(2026, 10, 1), "purchaseNoticeAESMBO"),),
    )
    detail = {
        "service": EisSourceError("INITIAL", service_code=13),
        "transport": EisSourceError(
            "WSDL", category="NETWORK", network_code="ERR_CONNECTION_CLOSED"
        ),
        "http": EisSourceError("SOAP", http_status=503, category="HTTP_STATUS"),
    }[failure]
    base = {
        "service": "SERVICE_ERROR",
        "transport": "SOURCE_TRANSPORT_FAILED",
        "http": "SOURCE_RESPONSE_REJECTED",
    }[failure]

    @asynccontextmanager
    async def session():
        yield object()

    async def fetch(*a, **k):
        if failure == "service":
            return Eis223Observation("SERVICE_ERROR", "a" * 64, source_error=detail)
        raise EisSyncError(base, source_error=detail)

    writes = []
    monkeypatch.setattr(runner, "eis_browser_transport", session)
    monkeypatch.setattr(runner, "fetch_notice223_day", fetch)
    monkeypatch.setattr(runner, "record_attempt", lambda *a, **k: writes.append(k))
    result = asyncio.run(runner.run())
    assert result["attempted"] == len(writes) == 1
    assert result["outcomes"][0]["reason"] == writes[0]["reason"] == detail.persisted_reason(base)
    assert result["outcomes"][0]["source_error"] == detail.safe_metadata()
    assert TOKEN not in str(result)


@pytest.mark.parametrize("kind", ["notice", "event", "lot"])
def test_archive_http_error_preserves_status(kind):
    from test_eis_223_event_sync import Transport as EventTransport
    from test_eis_223_lot_event_sync import Transport as LotTransport
    from test_eis_223_sync import Transport as NoticeTransport

    fetcher, transport_type = {
        "notice": (fetch_notice223_day, NoticeTransport),
        "event": (fetch_purchase_rejection_day, EventTransport),
        "lot": (fetch_purchase_lot_cancellation_day, LotTransport),
    }[kind]
    transport = transport_type()
    transport.download = AsyncMock(return_value=(503, b"private-message"))
    with pytest.raises(EisSyncError) as caught:
        asyncio.run(fetcher("tenant", date(2026, 10, 1), TOKEN, transport, poll_delay_seconds=0))
    assert caught.value.source_error.phase == "ARCHIVE"
    assert caught.value.source_error.http_status == 503


@pytest.mark.parametrize("failure", ["http", "timeout"])
def test_real_session_setup_records_wsdl_failure(monkeypatch, failure):
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock

    from procurement.sources import eis_feed_sync as m

    class BrowserError(Exception):
        pass

    class BrowserTimeout(BrowserError):
        pass

    goto = AsyncMock(return_value=SimpleNamespace(status=503))
    if failure == "timeout":
        goto.side_effect = BrowserTimeout(TOKEN)
    page = SimpleNamespace(url=m.WSDL, goto=goto)
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
            Error=BrowserError, TimeoutError=BrowserTimeout, async_playwright=lambda: manager
        ),
    )
    monkeypatch.setattr(m, "_proxy_server", lambda: None)

    async def exercise():
        async with m.eis_browser_transport() as session:
            with pytest.raises(EisSyncError) as caught:
                await session.post(b"request")
            detail = caught.value.source_error
            assert detail.phase == "WSDL"
            assert (
                detail.http_status == 503 if failure == "http" else detail.network_code == "TIMEOUT"
            )
            assert TOKEN not in repr(detail)

    asyncio.run(exercise())
    browser.close.assert_awaited_once()
