"""Synthetic SOAP/ZIP checks for the bounded event fetcher."""

import asyncio
from datetime import date
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_event_sync import event_window_key, fetch_purchase_rejection_day
from test_eis_223_events import event_xml, zip_bytes
from test_eis_feed_sync import SOAP_NS, TOKEN, UID, _response


class Transport:
    def __init__(self, state="READY", failure=None, region="50"):
        self.state, self.failure = state, failure
        self.region = region
        self.initial_uid = None
        self.downloads = self.posts = 0

    async def post(self, raw):
        self.posts += 1
        root = ET.fromstring(raw)
        payload = next(iter(root.find(f"{{{SOAP_NS}}}Body")))
        uid = payload.findtext("index/id")
        if payload.tag.endswith("getDocsByOrgRegionRequest"):
            params = payload.find("selectionParams")
            assert params.findtext("documentType223") == "purchaseRejection"
            assert params.findtext("subsystemType") == "RI223"
            assert params.findtext("orgRegion") == self.region
            assert params.findtext("periodInfo/exactDate") == "2026-10-01+03:00"
            self.initial_uid = uid
            self.url = (
                "https://int44.zakupki.gov.ru/dstore/common/download/compound"
                f"?docRequestUid={uid}&compoundUid={UID}"
            )
            content = (
                "<dataInfo><noData>true</noData></dataInfo>"
                if self.state == "NO_DATA"
                else "<dataInfo><archiveUrl>"
                + self.url.replace("&", "&amp;")
                + "</archiveUrl></dataInfo>"
            )
            result = _response("getDocsByOrgRegionResponse", content, uid)
            if self.failure == "initial_uid":
                result = result.replace(uid.encode(), b"22222222-2222-4222-8222-222222222222")
            return 200, result
        assert payload.findtext("docRequestUid") == self.initial_uid
        content = f"<docRequestUid>{self.initial_uid}</docRequestUid>"
        if self.state == "SERVICE_ERROR":
            content += "<errorInfo><code>1</code><message>synthetic</message></errorInfo>"
        elif self.state == "PREPARING":
            content += "<dataInfo><isPreparationCompleted>false</isPreparationCompleted></dataInfo>"
        else:
            archive_uid = "B" * 32 if self.failure == "archive_set" else UID
            url = self.url.replace(UID, archive_uid)
            content += (
                "<dataInfo><isPreparationCompleted>true</isPreparationCompleted>"
                f"<preparedPartInfo><dsUid>{archive_uid}</dsUid>"
                f"<url>{url.replace('&', '&amp;')}</url></preparedPartInfo></dataInfo>"
            )
        return 200, _response("getPreparedPartResponse", content, uid)

    async def download(self, url, token):
        self.downloads += 1
        assert token == TOKEN and url == self.url
        if self.failure == "http":
            return 404, b"synthetic"
        raw = event_xml()
        if self.failure == "token":
            raw = raw.replace(b"synthetic", TOKEN.encode())
        if self.failure == "root":
            raw = raw.replace(b"purchaseRejection", b"purchaseNotice")
        return 200, zip_bytes([("event.xml", raw)])


def fetch(transport, polls=1, region="50"):
    return asyncio.run(
        fetch_purchase_rejection_day(
            "tenant-a",
            date(2026, 10, 1),
            TOKEN,
            transport,
            region=region,
            poll_attempts=polls,
            poll_delay_seconds=0,
        )
    )


def test_exact_public_family_returns_complete_preflighted_window():
    transport = Transport()
    result = fetch(transport)
    assert result.status == "SYNCED" and result.window is not None
    assert result.window.window_key.endswith("/purchaseRejection")
    assert result.window.response_sha256 == result.response_sha256
    assert transport.downloads == 1


@pytest.mark.parametrize("state", ["NO_DATA", "PREPARING", "SERVICE_ERROR"])
def test_non_ready_states_never_download_or_publish_partial_window(state):
    transport = Transport(state)
    result = fetch(transport, polls=2)
    assert result.status == state and result.window is None
    assert transport.downloads == 0 and len(result.response_sha256) == 64


@pytest.mark.parametrize("failure", ["initial_uid", "archive_set", "http", "token", "root"])
def test_mismatch_or_unsafe_content_fails_closed(failure):
    transport = Transport(failure=failure)
    with pytest.raises(ValueError):
        fetch(transport)
    if failure in {"initial_uid", "archive_set"}:
        assert transport.downloads == 0


@pytest.mark.parametrize("polls", [0, 5])
def test_poll_budget_fails_before_source_call(polls):
    transport = Transport()
    with pytest.raises(ValueError, match="POLL_CONFIG_INVALID"):
        fetch(transport, polls)
    assert transport.posts == transport.downloads == 0


def test_region_changes_exact_rejection_request_and_window_key():
    transport = Transport(state="NO_DATA", region="77")
    result = fetch(transport, region="77")
    assert result.status == "NO_DATA" and transport.posts == 1
    assert event_window_key(date(2026, 10, 1), region="77").split("/")[2] == "77"


@pytest.mark.parametrize("region", ["00", "1", "100", "٠١", " 50"])
def test_invalid_region_fails_before_rejection_source_call(region):
    transport = Transport()
    with pytest.raises(ValueError, match="REGION_INVALID"):
        fetch(transport, region=region)
    assert transport.posts == transport.downloads == 0
