"""The exact-number request must use the official selection contract."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_feed import EisFeedResponse
from procurement.sources.eis_feed_sync import SOAP_NS, EisSyncError
from procurement.sources.eis_number_sync import _number_request, sync_eis_number

TOKEN = "11111111-1111-4111-8111-111111111111"
NUMBER = "0848300054826000154"
IP_NS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"


def test_number_request_has_exact_selection_without_source_credentials_in_body() -> None:
    xml = _number_request(TOKEN, "22222222-2222-4222-8222-222222222222", NUMBER)
    root = ET.fromstring(xml)
    params = root.find(f"{{{SOAP_NS}}}Body/{{{IP_NS}}}getDocsByReestrNumberRequest/selectionParams")
    assert params is not None
    assert params.findtext("subsystemType") == "PRIZ"
    assert params.findtext("reestrNumber") == NUMBER
    assert params.find("documentType44") is None
    with pytest.raises(EisSyncError, match="NUMBER_REQUEST_INVALID"):
        _number_request(TOKEN, "request", "../../other")


def test_no_data_stays_explicit_and_does_not_touch_storage() -> None:
    async def parsed(_transport: object, request: bytes, _token: str) -> EisFeedResponse:
        root = ET.fromstring(request)
        payload = root.find(f"{{{SOAP_NS}}}Body/{{{IP_NS}}}getDocsByReestrNumberRequest")
        assert payload is not None
        request_id = payload.findtext("index/id") or ""
        return EisFeedResponse(
            service="IP",
            kind="BY_NUMBER",
            state="NO_DATA",
            source_mode="PROD",
            response_id="response",
            request_id=request_id,
            created_at=None,
            source_time_raw="2026-09-29T10:00:00",
            source_time_status="UNKNOWN_TZ",
            source_sha256="a" * 64,
        )

    with patch("procurement.sources.eis_number_sync._parsed_post", side_effect=parsed):
        result = asyncio.run(sync_eis_number(None, "tenant-a", "worker", NUMBER, TOKEN, None))
    assert result.status == "NO_DATA"
    assert result.coverage == "ONE_NUMBER_ONLY"
    assert result.latest_xml_sha256 is None


def test_wrong_kind_response_is_rejected() -> None:
    async def parsed(_transport: object, request: bytes, _token: str) -> EisFeedResponse:
        root = ET.fromstring(request)
        payload = root.find(f"{{{SOAP_NS}}}Body/{{{IP_NS}}}getDocsByReestrNumberRequest")
        assert payload is not None
        return replace(
            EisFeedResponse(
                service="IP",
                kind="BY_NUMBER",
                state="NO_DATA",
                source_mode="PROD",
                response_id="response",
                request_id=payload.findtext("index/id") or "",
                created_at=None,
                source_time_raw="2026-09-29T10:00:00",
                source_time_status="UNKNOWN_TZ",
                source_sha256="a" * 64,
            ),
            kind="BY_REGION",
        )

    with (
        patch("procurement.sources.eis_number_sync._parsed_post", side_effect=parsed),
        pytest.raises(EisSyncError, match="NUMBER_RESPONSE_MISMATCH"),
    ):
        asyncio.run(sync_eis_number(None, "tenant-a", "worker", NUMBER, TOKEN, None))


@pytest.mark.parametrize(
    "latest, held", [((3, "b" * 64), True), (None, True), ((3, "b" * 64), False)]
)
def test_latest_claim_requires_source_guard(latest, held):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from procurement.sources import eis_number_sync as module

    class Storage:
        @contextmanager
        def transaction(self, *args, **kwargs):
            yield connection

    connection = Mock()
    connection.execute.return_value.first.return_value = latest
    initial = None

    async def parsed(_transport, request, _token):
        nonlocal initial
        payload = ET.fromstring(request).find(
            f"{{{SOAP_NS}}}Body/{{{IP_NS}}}getDocsByReestrNumberRequest"
        )
        if payload is not None:
            initial = SimpleNamespace(
                service="IP",
                kind="BY_NUMBER",
                state="LINKS_PENDING",
                request_id=payload.findtext("index/id"),
                source_mode="PROD",
                archive_urls=("url",),
                source_sha256="a" * 64,
            )
            return initial
        return SimpleNamespace(
            kind="PREPARED",
            doc_request_uid=initial.request_id,
            source_mode="PROD",
            state="READY",
            prepared_archives=(SimpleNamespace(url="url"),),
        )

    guard = Mock(side_effect=ValueError("NOTICE_VARIANT_REVIEW_REQUIRED") if held else None)
    with (
        patch.object(module, "_parsed_post", side_effect=parsed),
        patch.object(module, "bind_ready_window", return_value=object()),
        patch.object(
            module,
            "ingest_ready_window",
            return_value=SimpleNamespace(archive_count=1, new_versions=0),
        ),
        patch.object(module, "assert_notice_source_usable", guard),
    ):
        operation = module.sync_eis_number(
            Storage(),
            "tenant-a",
            "worker",
            NUMBER,
            TOKEN,
            SimpleNamespace(download=AsyncMock(return_value=(200, b"PK\x03\x04data"))),
        )
        if held:
            with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
                asyncio.run(operation)
        else:
            result = asyncio.run(operation)
            assert result.latest_version_number == 3 and result.latest_xml_sha256 == "b" * 64
    guard.assert_called_once_with(connection, "tenant-a", NUMBER, latest[0] if latest else 1)
