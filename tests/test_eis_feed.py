"""Synthetic XSD 16.3 response shapes; no live EIS response is claimed."""

from datetime import timedelta

import pytest

from procurement.sources.eis_feed import (
    EisFeedContractError,
    parse_get_docs_ip_response,
    parse_get_docs_le_response,
)

_NS = "http://zakupki.gov.ru/fz44/get-docs-le/ws"
_IP_NS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"
_REQ = "11111111-1111-4111-8111-111111111111"
_RESP = "22222222-2222-4222-8222-222222222222"
_POLL = "33333333-3333-4333-8333-333333333333"
_DS = "A" * 32
_URL = (
    "https://int44-ttls-cert.zakupki.gov.ru/dstore/common/download/compound"
    f"?docRequestUid={_REQ}&compoundUid={_DS}"
)


def _xml(name: str, content: str, *, ref: str = _REQ, namespace: str = _NS) -> bytes:
    return (
        f'<e:{name} xmlns:e="{namespace}">'
        "<index>"
        f"<id>{_RESP}</id><refId>{ref}</refId>"
        "<createDateTime>2026-09-27T12:00:00+03:00</createDateTime><mode>PROD</mode>"
        "</index>"
        f"{content}</e:{name}>"
    ).encode()


def test_region_links_are_pending_until_preparation_completed() -> None:
    first = parse_get_docs_le_response(
        _xml(
            "getDocsByOrgRegionResponse",
            f"<dataInfo><archiveUrl>{_URL.replace('&', '&amp;')}</archiveUrl></dataInfo>",
        )
    )
    assert first.kind == "BY_REGION"
    assert first.service == "LE"
    assert first.state == "LINKS_PENDING"
    assert first.source_mode == "PROD"
    assert first.archive_urls == (_URL,)
    assert first.request_id == _REQ
    assert first.created_at.utcoffset() == timedelta(hours=3)
    assert len(first.source_sha256) == 64

    pending = parse_get_docs_le_response(
        _xml(
            "getPreparedPartResponse",
            f"<docRequestUid>{_REQ}</docRequestUid>"
            "<dataInfo><isPreparationCompleted>false</isPreparationCompleted></dataInfo>",
            ref=_POLL,
        )
    )
    assert pending.state == "PREPARING"
    assert pending.doc_request_uid == _REQ
    assert pending.prepared_archives == ()

    ready = parse_get_docs_le_response(
        _xml(
            "getPreparedPartResponse",
            f"<docRequestUid>{_REQ}</docRequestUid><dataInfo>"
            "<isPreparationCompleted>true</isPreparationCompleted>"
            f"<preparedPartInfo><dsUid>{_DS}</dsUid>"
            f"<url>{_URL.replace('&', '&amp;')}</url></preparedPartInfo></dataInfo>",
            ref=_POLL,
        )
    )
    assert ready.state == "READY"
    assert ready.prepared_archives[0].url == _URL
    assert ready.prepared_archives[0].archive_uid == _DS.lower()


def test_no_data_is_distinct_from_service_error() -> None:
    empty = parse_get_docs_le_response(
        _xml("getDocsByReestrNumberResponse", "<dataInfo><noData>true</noData></dataInfo>")
    )
    limited = parse_get_docs_le_response(
        _xml(
            "getDocsByReestrNumberResponse",
            "<dataInfo><errorInfo><code>13</code><message>limit</message></errorInfo></dataInfo>",
        )
    )
    assert empty.kind == "BY_NUMBER" and empty.state == "NO_DATA"
    assert limited.state == "SERVICE_ERROR" and limited.error_code == 13


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("<dataInfo><noData>false</noData></dataInfo>", "RESPONSE_BRANCH_INVALID"),
        ("<dataInfo><noData>true</noData><errorInfo/></dataInfo>", "RESPONSE_BRANCH_INVALID"),
        (
            "<dataInfo><archiveUrl>https://evil.example/file</archiveUrl></dataInfo>",
            "ARCHIVE_URL_UNTRUSTED",
        ),
        (
            "<dataInfo><archiveUrl>https://zakupki.gov.ru.evil.example/dstore/common/download/compound</archiveUrl></dataInfo>",
            "ARCHIVE_URL_UNTRUSTED",
        ),
    ],
)
def test_untrusted_or_ambiguous_response_fails_closed(payload: str, reason: str) -> None:
    with pytest.raises(EisFeedContractError, match=reason):
        parse_get_docs_le_response(_xml("getDocsByOrgRegionResponse", payload))


def test_prepared_archive_must_match_original_request() -> None:
    wrong = _URL.replace(_REQ, _POLL)
    xml = _xml(
        "getPreparedPartResponse",
        f"<docRequestUid>{_REQ}</docRequestUid><dataInfo>"
        "<isPreparationCompleted>true</isPreparationCompleted>"
        f"<preparedPartInfo><dsUid>{_DS}</dsUid>"
        f"<url>{wrong.replace('&', '&amp;')}</url></preparedPartInfo></dataInfo>",
    )
    with pytest.raises(EisFeedContractError, match="ARCHIVE_REQUEST_MISMATCH"):
        parse_get_docs_le_response(xml)


def test_ready_with_only_not_downloaded_archives() -> None:
    xml = _xml(
        "getPreparedPartResponse",
        f"<docRequestUid>{_REQ}</docRequestUid><dataInfo>"
        "<isPreparationCompleted>true</isPreparationCompleted>"
        f"<preparedNotDownloadPartInfo><dsUid>{_DS}</dsUid>"
        f"<url>{_URL.replace('&', '&amp;')}</url>"
        "</preparedNotDownloadPartInfo></dataInfo>",
    )
    result = parse_get_docs_ip_response(xml.replace(_NS.encode(), _IP_NS.encode()))
    assert result.state == "READY"
    assert len(result.prepared_archives) == 1
    assert result.not_downloaded_archives == result.prepared_archives


def test_no_dtd_and_unaware_source_time_remains_unknown() -> None:
    with pytest.raises(EisFeedContractError, match="XML_DECLARATION_UNTRUSTED"):
        parse_get_docs_le_response(b"<!DOCTYPE foo [<!ENTITY x 'bad'>]><foo/>")
    xml = _xml("getDocsByOrgRegionResponse", "<dataInfo><noData>true</noData></dataInfo>")
    observed = parse_get_docs_le_response(xml.replace(b"+03:00", b""))
    assert observed.created_at is None
    assert observed.source_time_status == "UNKNOWN_TZ"
    assert observed.source_time_raw == "2026-09-27T12:00:00"


def test_ip_namespace_and_unaware_live_response_shape() -> None:
    xml = _xml(
        "getDocsByReestrNumberResponse",
        f"<dataInfo><archiveUrl>{_URL.replace('&', '&amp;')}</archiveUrl></dataInfo>",
        namespace=_IP_NS,
    ).replace(b"+03:00", b"")
    result = parse_get_docs_ip_response(xml)
    assert result.service == "IP"
    assert result.state == "LINKS_PENDING"
    assert result.created_at is None
    assert result.source_time_status == "UNKNOWN_TZ"
    with pytest.raises(EisFeedContractError, match="RESPONSE_TYPE_UNKNOWN"):
        parse_get_docs_le_response(xml)


def test_soap_body_is_read_but_fault_is_not_no_data() -> None:
    payload = _xml("getDocsByReestrNumberResponse", "<dataInfo><noData>true</noData></dataInfo>")
    soap = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        b"<s:Body>" + payload + b"</s:Body></s:Envelope>"
    )
    assert parse_get_docs_le_response(soap).state == "NO_DATA"
    fault = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        b"<s:Body><s:Fault><faultcode>Server</faultcode></s:Fault></s:Body></s:Envelope>"
    )
    with pytest.raises(EisFeedContractError, match="RESPONSE_TYPE_UNKNOWN"):
        parse_get_docs_le_response(fault)
