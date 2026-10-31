import asyncio
from dataclasses import replace
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_number_sync import number_request, sync_223_number
from test_eis_223_index import URL, responses
from test_eis_223_zpesmbo import NUMBER, zp_zip

TOKEN = "synthetic-token-123"


def test_request_is_targeted_223_not_regional():
    root = ET.fromstring(number_request(TOKEN, "11111111-1111-4111-8111-111111111111", NUMBER))
    assert root.findtext(".//selectionParams/subsystemType") == "RI223"
    assert root.findtext(".//selectionParams/reestrNumber") == NUMBER
    assert root.find(".//selectionParams/orgRegion") is None


def test_unsupported_family_makes_no_source_calls():
    with pytest.raises(ValueError, match="NUMBER_SCOPE_INVALID"):
        asyncio.run(sync_223_number(None, "tenant", "actor", NUMBER, "purchaseNotice", TOKEN, None))


def test_full_bound_archive_is_verified_before_ingest(monkeypatch):
    from procurement.sources import eis_223_number_sync as mod

    initial, prepared = responses()
    requests = []

    async def post(transport, raw, token):
        root = ET.fromstring(raw)
        uid = root.findtext(".//index/id")
        requests.append(uid)
        if len(requests) == 1:
            return replace(initial, kind="BY_NUMBER", request_id=uid)
        return replace(prepared, request_id=uid, doc_request_uid=requests[0])

    class Transport:
        async def download(self, url, token):
            assert url == URL
            return 200, zp_zip()

    # The synthetic URL binds the fixed fixture UID; keep UUID deterministic.
    monkeypatch.setattr(mod, "uuid4", lambda: initial.request_id)

    async def no_delay(seconds):
        assert seconds == 10

    monkeypatch.setattr(mod.asyncio, "sleep", no_delay)
    monkeypatch.setattr(mod, "_parsed_post", post)
    seen = []

    def ingest(storage, company, ready, *, actor_id):
        from procurement.storage.eis_223_index import preflight_notice223_window

        records, _ = preflight_notice223_window(company, ready)
        seen.extend(r.version_number for r in records[0].records)
        return SimpleNamespace(archive_count=1, new_versions=4)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            return SimpleNamespace(first=lambda: (4, "a" * 64))

    class Storage:
        def transaction(self, *args, **kwargs):
            return Conn()

    monkeypatch.setattr(mod, "ingest_notice223_window", ingest)
    result = asyncio.run(
        sync_223_number(
            Storage(), "tenant", "actor", NUMBER, "purchaseNoticeZPESMBO", TOKEN, Transport()
        )
    )
    assert seen == [1, 2, 3, 4]
    assert result.status == "SYNCED"


def test_mixed_family_archive_is_rejected_without_ingest(monkeypatch):
    from procurement.sources import eis_223_number_sync as mod
    from procurement.storage.eis_223_index import preflight_notice223_window
    from test_eis_223_archive import xml, zip_bytes
    from test_eis_223_zpesmbo import zp_xml

    initial, prepared = responses()
    requests = []

    async def post(transport, raw, token):
        uid = ET.fromstring(raw).findtext(".//index/id")
        requests.append(uid)
        if len(requests) == 1:
            return replace(initial, kind="BY_NUMBER", request_id=uid)
        return replace(prepared, request_id=uid, doc_request_uid=requests[0])

    class Transport:
        async def download(self, url, token):
            return 200, zip_bytes([("zp.xml", zp_xml()), ("other.xml", xml())])

    async def no_delay(seconds):
        pass

    def ingest(storage, company, ready, *, actor_id):
        preflight_notice223_window(company, ready)
        raise AssertionError("mixed archive must not pass preflight")

    monkeypatch.setattr(mod, "uuid4", lambda: initial.request_id)
    monkeypatch.setattr(mod, "_parsed_post", post)
    monkeypatch.setattr(mod.asyncio, "sleep", no_delay)
    monkeypatch.setattr(mod, "ingest_notice223_window", ingest)
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        asyncio.run(
            sync_223_number(
                None, "tenant", "actor", NUMBER, "purchaseNoticeZPESMBO", TOKEN, Transport()
            )
        )
