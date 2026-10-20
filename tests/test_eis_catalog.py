"""Синтетические official-shape fixtures, без реальных XML/токенов ЕИС."""

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from procurement.sources.eis_catalog import (
    EXPORT_NS,
    IP_NS,
    REFERENCE223_NS,
    SOAP_NS,
    TYPES223_NS,
    TYPES_NS,
    EisCatalogError,
    catalog_request,
    inspect_catalog_archive,
    parse_catalog_response,
)
from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES

UID = "11111111-1111-1111-1111-111111111111"
RESPONSE_UID = "22222222-2222-2222-2222-222222222222"
URL = (
    "https://int.zakupki.gov.ru/dstore/common/download/compound"
    f"?docRequestUid={UID}&compoundUid={'A' * 32}"
)


def response_xml(branch: str = "", *, ref: str = UID, mode: str = "PROD") -> bytes:
    if not branch:
        branch = (
            f"<nsiArchiveInfo><archiveUrl>{URL.replace('&', '&amp;')}</archiveUrl>"
            "<archiveName>synthetic.zip</archiveName></nsiArchiveInfo>"
        )
    return (
        f'<s:Envelope xmlns:s="{SOAP_NS}"><s:Body><i:getNsiResponse xmlns:i="{IP_NS}">'
        f"<index><id>{RESPONSE_UID}</id><refId>{ref}</refId>"
        f"<createDateTime>2026-10-02T08:00:00+03:00</createDateTime><mode>{mode}</mode>"
        f"</index><dataInfo>{branch}</dataInfo></i:getNsiResponse></s:Body></s:Envelope>"
    ).encode()


def archive(raw: bytes, name: str = "synthetic.xml") -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as z:
        info = ZipInfo(name)
        info.filename = name  # Preserve intentionally unsafe raw ZIP names on Windows too.
        info.compress_type = ZIP_DEFLATED
        z.writestr(info, raw)
    return stream.getvalue()


def catalog44(
    *,
    flag: str = "<t:isDistributedPublicly>true</t:isDistributedPublicly>",
    code: str = "syntheticNotice",
) -> bytes:
    return (
        f'<e:export xmlns:e="{EXPORT_NS}" xmlns:t="{TYPES_NS}"><e:nsiDocumentTypesList>'
        f"<e:nsiDocumentTypes><t:documentType>{code}</t:documentType>"
        "<t:documentName>Синтетическое извещение</t:documentName>"
        "<t:subsystemType>PRIZ</t:subsystemType>"
        f"{flag}<t:updateDate>2026-10-01T00:00:00</t:updateDate><t:isActual>true</t:isActual>"
        "</e:nsiDocumentTypes></e:nsiDocumentTypesList></e:export>"
    ).encode()


def catalog223() -> bytes:
    return (
        f'<r:nsiDocumentTypes223 xmlns:r="{REFERENCE223_NS}" xmlns:t="{TYPES223_NS}">'
        "<t:header><t:guid>33333333-3333-3333-3333-333333333333</t:guid></t:header><r:body>"
        "<r:item><r:documentType>synthetic223</r:documentType><r:subsystem>RI223</r:subsystem>"
        "<r:documentName>Синтетический протокол</r:documentName>"
        "<r:distributedPublicly>false</r:distributedPublicly>"
        "<r:actual>true</r:actual><r:createDate>2026-09-01T00:00:00</r:createDate>"
        "<r:lastUpdateDate>2026-10-01T01:00:00+03:00</r:lastUpdateDate>"
        "</r:item></r:body></r:nsiDocumentTypes223>"
    ).encode()


def inspect(raw: bytes, *, law: str = "44", name: str = "synthetic.xml"):
    reply = parse_catalog_response(response_xml(), request_id=UID)
    return inspect_catalog_archive(
        archive(raw, name), law=law, response=reply, reference=reply.archives[0]
    )


@pytest.mark.parametrize("law,code", [("44", "nsiDocumentTypes"), ("223", "nsiDocumentTypes223")])
def test_fixed_request_contract(law, code):
    token = "synthetic-private-token"
    raw = catalog_request(token, UID, law)
    payload = ET.fromstring(raw).find(f"{{{SOAP_NS}}}Body")[0]
    params = payload.find("selectionParams")
    assert [(c.tag, c.text) for c in params] == [(f"nsiCode{law}", code), ("nsiKind", "all")]
    assert payload.tag == f"{{{IP_NS}}}getNsiRequest"


def test_ready_direct_archive_has_response_binding():
    reply = parse_catalog_response(response_xml(), request_id=UID)
    assert reply.state == "READY"
    assert reply.coverage == "UNKNOWN"
    assert reply.archives[0].url == URL
    assert reply.archives[0].locator.endswith("[1]")


@pytest.mark.parametrize(
    "branch,state",
    [
        ("<noData>true</noData>", "NO_DATA"),
        (
            "<errorInfo><code>7</code><message>untrusted error</message></errorInfo>",
            "SERVICE_ERROR",
        ),
    ],
)
def test_no_data_or_service_error_never_claim_coverage(branch, state):
    reply = parse_catalog_response(response_xml(branch), request_id=UID)
    assert reply.state == state
    assert reply.coverage == "UNKNOWN" and not reply.archives


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.replace(UID.encode(), RESPONSE_UID.encode()),
        lambda b: b.replace(b"PROD", b"TEST"),
        lambda b: b.replace(b"getNsiResponse", b"getPreparedPartResponse"),
        lambda b: b.replace(b"<dataInfo>", b"<dataInfo><noData>true</noData>"),
        lambda b: b.replace(b"</index>", b"<mode>PROD</mode></index>"),
        lambda b: b.replace(b"int.zakupki.gov.ru", b"example.org"),
        lambda b: b.replace(b"/dstore/common/download/compound", b"/unverified/path"),
        lambda b: b.replace(b"synthetic.zip", b"../synthetic.zip"),
        lambda b: b.replace(b"</s:Body>", b"<unexpected/></s:Body>"),
        lambda b: b'<!DOCTYPE foo [<!ENTITY x "untrusted">]>' + b,
        lambda b: b.decode().encode("utf-16"),
    ],
)
def test_reject_mismatched_or_ambiguous_response(mutation):
    with pytest.raises(EisCatalogError):
        parse_catalog_response(mutation(response_xml()), request_id=UID)


def test_catalog44_every_fact_retains_exact_xml_and_field_locator():
    before = tuple(SUPPORTED_NOTICE_TYPES)
    result = inspect(catalog44())
    entry = result.entries[0]
    assert entry.distributed_publicly == entry.actual == "PASS"
    assert entry.updated_at is None  # Source timezone absent: preserve raw value only.
    assert entry.adapter_admission == "NOT_EVALUATED"
    assert result.coverage == "UNKNOWN"
    assert len(entry.fields) == 6
    for fact in entry.fields:
        assert fact.provenance.document_id == entry.source_xml_sha256
        assert fact.name in fact.provenance.locator
        assert (
            "synthetic.xml :: export/nsiDocumentTypesList/nsiDocumentTypes[1]/"
            in fact.provenance.locator
        )
    assert before == SUPPORTED_NOTICE_TYPES


def test_catalog223_has_separate_namespace_and_contract_basis():
    result = inspect(catalog223(), law="223")
    entry = result.entries[0]
    assert result.contract_basis == "OBSERVED_LIVE_223"
    assert entry.distributed_publicly == "FAIL" and entry.actual == "PASS"
    assert entry.updated_at.utcoffset() is not None
    assert entry.subsystem == "RI223"
    assert all("nsiDocumentTypes223/body/item[1]/" in f.provenance.locator for f in entry.fields)
    with pytest.raises(EisCatalogError, match="ROOT_INVALID"):
        inspect(catalog223())


@pytest.mark.parametrize(
    "flag",
    [
        "",
        "<t:isDistributedPublicly>TRUE</t:isDistributedPublicly>",
        "<t:isDistributedPublicly>true</t:isDistributedPublicly><t:isDistributedPublicly>false</t:isDistributedPublicly>",
        "<t:isDistributedPublicly><t:value>true</t:value></t:isDistributedPublicly>",
    ],
)
def test_missing_ambiguous_or_nested_flag_is_unknown(flag):
    assert inspect(catalog44(flag=flag)).entries[0].distributed_publicly == "UNKNOWN"


@pytest.mark.parametrize(
    "name",
    [
        "../synthetic.xml",
        "/synthetic.xml",
        "dir\\synthetic.xml",
        "C:synthetic.xml",
        "unexpected.txt",
    ],
)
def test_archive_path_and_unexpected_member_rejected(name):
    with pytest.raises(EisCatalogError, match="MEMBER_INVALID"):
        inspect(catalog44(), name=name)


def test_duplicate_code_cannot_be_resolved_by_last_wins():
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("a.xml", catalog44())
        z.writestr(
            "b.xml", catalog44(flag="<t:isDistributedPublicly>false</t:isDistributedPublicly>")
        )
    reply = parse_catalog_response(response_xml(), request_id=UID)
    with pytest.raises(EisCatalogError, match="ENTRY_DUPLICATE"):
        inspect_catalog_archive(
            stream.getvalue(), law="44", response=reply, reference=reply.archives[0]
        )


def test_symlink_and_expansion_rejected(monkeypatch):
    import procurement.sources.eis_catalog as module

    stream = BytesIO()
    with ZipFile(stream, "w") as z:
        info = ZipInfo("synthetic.xml")
        info.external_attr = 0o120777 << 16
        z.writestr(info, catalog44())
    reply = parse_catalog_response(response_xml(), request_id=UID)
    with pytest.raises(EisCatalogError, match="MEMBER_INVALID"):
        inspect_catalog_archive(
            stream.getvalue(), law="44", response=reply, reference=reply.archives[0]
        )
    monkeypatch.setattr(module, "MAX_EXPANDED_BYTES", 32)
    with pytest.raises(EisCatalogError, match="EXPANSION_LIMIT"):
        inspect(catalog44())


def test_unknown_root_namespace_and_duplicate_identity_rejected():
    for raw in [
        catalog44().replace(TYPES_NS.encode(), b"urn:untrusted"),
        catalog44().replace(
            b"<t:subsystemType>", b"<t:documentType>other</t:documentType><t:subsystemType>"
        ),
    ]:
        with pytest.raises(EisCatalogError):
            inspect(raw)


def test_secret_reflection_inside_compressed_member_is_rejected():
    secret = b"synthetic-private-token"
    raw = catalog44().replace("Синтетическое извещение".encode(), secret)
    compressed = archive(raw)
    assert secret not in compressed  # Checking only compressed bytes would miss reflection.
    reply = parse_catalog_response(response_xml(), request_id=UID)
    with pytest.raises(EisCatalogError, match="SECRET_REFLECTION"):
        inspect_catalog_archive(
            compressed,
            law="44",
            response=reply,
            reference=reply.archives[0],
            forbidden_bytes=secret,
        )


def test_partial_or_ambiguous_actual_flag_never_becomes_current():
    for raw in [
        catalog44().replace(b"<t:isActual>true</t:isActual>", b""),
        catalog44().replace(
            b"<t:isActual>true</t:isActual>",
            b"<t:isActual>true</t:isActual><t:isActual>false</t:isActual>",
        ),
    ]:
        assert inspect(raw).entries[0].actual == "UNKNOWN"


def test_duplicate_archive_urls_and_false_no_data_are_rejected():
    for raw in [
        response_xml().replace(
            b"</dataInfo>",
            response_xml().split(b"<dataInfo>")[1].split(b"</dataInfo>")[0] + b"</dataInfo>",
        ),
        response_xml("<noData>false</noData>"),
        response_xml().replace(b"</s:Envelope>", b"<s:Body/></s:Envelope>"),
    ]:
        with pytest.raises(EisCatalogError):
            parse_catalog_response(raw, request_id=UID)
