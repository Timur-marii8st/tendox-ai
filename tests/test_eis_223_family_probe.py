"""Synthetic probe tests; test XSD is deliberately smaller than official XSD."""

from dataclasses import replace
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from lxml import etree as E

from procurement.sources.eis_223_archive import PURCHASE_NS
from procurement.sources.eis_feed import EisArchiveReference
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import ARCHIVE_UID, UID, URL, responses


@pytest.fixture
def probe():
    spec = spec_from_file_location(
        "family_probe_test", Path(__file__).parents[1] / "scripts/server-eis-223-family-probe.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schema(family):
    return E.XMLSchema(
        E.fromstring(
            f'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
        targetNamespace="{PURCHASE_NS}" elementFormDefault="qualified">
        <xs:element name="{family}"><xs:complexType><xs:sequence>
        <xs:element name="body" type="xs:anyType"/></xs:sequence></xs:complexType></xs:element>
        </xs:schema>'''.encode()
        )
    )


def sample(family):
    # Remove synthetic header so the intentionally tiny test schema has only body.
    return (
        xml()
        .replace(b"purchaseNoticeAESMBO", family.encode())
        .replace(
            b"<t:header><t:guid>synthetic</t:guid></t:header>",
            b"",
        )
    )


@pytest.mark.parametrize("family", ["purchaseNotice", "purchaseNoticeZKESMBO"])
def test_request_and_root_data_inventory_remain_family_exact(probe, family):
    root = ET.fromstring(probe.request("synthetic-token-123", UID, family, date(2026, 10, 1)))
    assert root.findtext(".//documentType223") == family
    assert root.find(".//documentType44") is None
    result = probe.inspect(
        zip_bytes([("notice.xml", sample(family))]), family, (schema(family),), "unused-token"
    )
    record = result["records"][0]
    assert record["purchase_number"] == "32600000001" and record["version_number"] == 2
    assert record["data_locator"].endswith(f"p:{family}Data")
    assert result["coverage"] == record["admission"] == record["economics"] == "UNKNOWN"


def test_unknown_family_and_mismatched_xml_are_rejected(probe):
    with pytest.raises(ValueError):
        probe.request("synthetic-token-123", UID, "privateType", date(2026, 10, 1))
    with pytest.raises(ValueError, match="SOURCE_FAMILY_MISMATCH"):
        probe.inspect(
            zip_bytes([("notice.xml", xml())]),
            "purchaseNotice",
            (schema("purchaseNotice"),),
            "unused",
        )


@pytest.mark.parametrize("mutation", ["path", "duplicate", "dtd", "identity", "secret", "schema"])
def test_archive_security_and_schema_mismatch_fail_closed(probe, mutation):
    family = "purchaseNotice"
    raw = sample(family)
    name = "notice.xml"
    token = "unused"
    schemas = (schema(family),)
    if mutation == "path":
        name = "../notice.xml"
    elif mutation == "dtd":
        raw = b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + raw
    elif mutation == "identity":
        raw = raw.replace(b"32600000001", b"bad")
    elif mutation == "secret":
        token = "32600000001"
    elif mutation == "schema":
        schemas = (schema("differentFamily"),)
    entries = [(name, raw)]
    if mutation == "duplicate":
        entries.append(("other.xml", raw))
    with pytest.raises(ValueError):
        probe.inspect(zip_bytes(entries), family, schemas, token)


def test_ready_archive_set_is_bound_and_immutable_write_refuses_overwrite(probe, tmp_path):
    initial, prepared = responses()
    assert probe.ready_refs(initial, prepared, UID) == prepared.prepared_archives
    path = tmp_path / "proof.json"
    probe.write(path, b"synthetic")
    with pytest.raises(ValueError, match="LOCAL_REPLAY_CONFLICT"):
        probe.write(path, b"different")
    assert path.read_bytes() == b"synthetic"


@pytest.mark.parametrize("mutation", ["test", "request", "empty", "extra", "url", "duplicate"])
def test_source_binding_blocks_untrusted_gets(probe, mutation):
    initial, prepared = responses()
    if mutation == "test":
        initial = replace(initial, source_mode="TEST")
    elif mutation == "request":
        prepared = replace(prepared, doc_request_uid="22222222-2222-4222-8222-222222222222")
    elif mutation == "empty":
        prepared = replace(prepared, prepared_archives=())
    elif mutation == "extra":
        prepared = replace(
            prepared,
            prepared_archives=(*prepared.prepared_archives, EisArchiveReference(URL, "b" * 32)),
        )
    elif mutation == "url":
        prepared = replace(
            prepared, prepared_archives=(EisArchiveReference("https://example.com/", ARCHIVE_UID),)
        )
    else:
        prepared = replace(prepared, prepared_archives=prepared.prepared_archives * 2)
    with pytest.raises(ValueError):
        probe.ready_refs(initial, prepared, UID)
