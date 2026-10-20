"""Read-only parsing of getDocsIP/getDocsLE responses from official EIS XSD 16.3.

This module does not authenticate, fetch archives, or assert corpus coverage.
Until a permitted live response is captured, tests use labelled synthetic XML.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

_NS_BY_SERVICE = {
    "LE": "http://zakupki.gov.ru/fz44/get-docs-le/ws",
    "IP": "http://zakupki.gov.ru/fz44/get-docs-ip/ws",
}
_SOAP_NS = {
    "http://schemas.xmlsoap.org/soap/envelope/",
    "http://www.w3.org/2003/05/soap-envelope",
}
_INITIAL = {"getDocsByReestrNumberResponse", "getDocsByOrgRegionResponse"}
_PREPARED = "getPreparedPartResponse"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_INITIAL_URLS = {"getDocsByReestrNumberResponse": 10, "getDocsByOrgRegionResponse": 1000}
_UID32 = re.compile(r"^[0-9A-F]{32}$")
_ARCHIVE_HOSTS = {
    "int.zakupki.gov.ru",
    "int44.zakupki.gov.ru",
    "int44-ttls-cert.zakupki.gov.ru",
}


class EisFeedContractError(ValueError):
    """The source response cannot be interpreted under the verified XSD contract."""


@dataclass(frozen=True)
class EisArchiveReference:
    url: str
    archive_uid: str


@dataclass(frozen=True)
class EisFeedResponse:
    service: Literal["LE", "IP"]
    kind: Literal["BY_NUMBER", "BY_REGION", "PREPARED"]
    state: Literal["LINKS_PENDING", "NO_DATA", "SERVICE_ERROR", "PREPARING", "READY"]
    source_mode: Literal["PROD", "TEST"]
    response_id: str
    request_id: str
    created_at: datetime | None
    source_time_raw: str
    source_time_status: Literal["AWARE", "UNKNOWN_TZ"]
    source_sha256: str
    archive_urls: tuple[str, ...] = ()
    prepared_archives: tuple[EisArchiveReference, ...] = ()
    not_downloaded_archives: tuple[EisArchiveReference, ...] = ()
    doc_request_uid: str | None = None
    error_code: int | None = None


def _one(parent: ET.Element, name: str) -> ET.Element:
    children = parent.findall(name)
    if len(children) != 1:
        raise EisFeedContractError("FIELD_MISSING_OR_DUPLICATE")
    return children[0]


def _text(parent: ET.Element, name: str) -> str:
    value = (_one(parent, name).text or "").strip()
    if not value:
        raise EisFeedContractError("FIELD_EMPTY")
    return value


def _guid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise EisFeedContractError("INVALID_GUID") from error


def validate_eis_archive_url(value: str, *, doc_request_uid: str | None = None) -> str:
    parts = urlsplit(value.strip())
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError as error:
        raise EisFeedContractError("ARCHIVE_URL_UNTRUSTED") from error
    if (
        parts.scheme != "https"
        or host not in _ARCHIVE_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.path != "/dstore/common/download/compound"
        or parts.fragment
    ):
        raise EisFeedContractError("ARCHIVE_URL_UNTRUSTED")
    try:
        query = parse_qs(parts.query, strict_parsing=True)
    except ValueError as error:
        raise EisFeedContractError("ARCHIVE_URL_UNTRUSTED") from error
    if set(query) != {"docRequestUid", "compoundUid"} or any(
        len(values) != 1 for values in query.values()
    ):
        raise EisFeedContractError("ARCHIVE_URL_UNTRUSTED")
    request_uid = _guid(query["docRequestUid"][0])
    compound_uid = query["compoundUid"][0]
    if not (_UID32.fullmatch(compound_uid) or _is_guid(compound_uid)):
        raise EisFeedContractError("ARCHIVE_URL_UNTRUSTED")
    if doc_request_uid is not None and request_uid != doc_request_uid:
        raise EisFeedContractError("ARCHIVE_REQUEST_MISMATCH")
    return value.strip()


def _is_guid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _payload(xml: bytes) -> ET.Element:
    if not xml or len(xml) > _MAX_RESPONSE_BYTES:
        raise EisFeedContractError("RESPONSE_SIZE_INVALID")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.IGNORECASE):
        raise EisFeedContractError("XML_DECLARATION_UNTRUSTED")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise EisFeedContractError("XML_INVALID") from error
    if root.tag.startswith("{") and root.tag.rsplit("}", 1)[0][1:] in _SOAP_NS:
        body = _one(root, root.tag.replace("Envelope", "Body"))
        if len(body) != 1:
            raise EisFeedContractError("SOAP_BODY_INVALID")
        return body[0]
    return root


def parse_get_docs_le_response(xml: bytes) -> EisFeedResponse:
    return _parse_get_docs_response(xml, service="LE")


def parse_get_docs_ip_response(xml: bytes) -> EisFeedResponse:
    return _parse_get_docs_response(xml, service="IP")


def _parse_get_docs_response(xml: bytes, *, service: Literal["LE", "IP"]) -> EisFeedResponse:
    """Parse only the documented response branches, preserving raw provenance."""
    payload = _payload(xml)
    if not payload.tag.startswith("{"):
        raise EisFeedContractError("RESPONSE_NAMESPACE_UNKNOWN")
    namespace, name = payload.tag[1:].split("}", 1)
    if namespace != _NS_BY_SERVICE[service] or name not in (*_INITIAL, _PREPARED):
        raise EisFeedContractError("RESPONSE_TYPE_UNKNOWN")

    index = _one(payload, "index")
    response_id = _guid(_text(index, "id"))
    request_id = _guid(_text(index, "refId"))
    source_time_raw = _text(index, "createDateTime")
    try:
        parsed_time = datetime.fromisoformat(source_time_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EisFeedContractError("RESPONSE_TIME_INVALID") from exc
    time_aware = parsed_time.tzinfo is not None and parsed_time.utcoffset() is not None
    created_at = parsed_time if time_aware else None
    source_time_status: Literal["AWARE", "UNKNOWN_TZ"] = "AWARE" if time_aware else "UNKNOWN_TZ"
    mode = _text(index, "mode")
    if mode not in {"PROD", "TEST"}:
        raise EisFeedContractError("RESPONSE_MODE_UNKNOWN")
    source_mode: Literal["PROD", "TEST"] = "PROD" if mode == "PROD" else "TEST"
    digest = hashlib.sha256(xml).hexdigest()

    if name in _INITIAL:
        data = _one(payload, "dataInfo")
        branches = [child.tag for child in data]
        if not branches or len(set(branches)) != 1:
            raise EisFeedContractError("RESPONSE_BRANCH_INVALID")
        branch = branches[0]
        kind: Literal["BY_NUMBER", "BY_REGION", "PREPARED"] = (
            "BY_NUMBER" if name == "getDocsByReestrNumberResponse" else "BY_REGION"
        )
        base = EisFeedResponse(
            service=service,
            kind=kind,
            state="NO_DATA",
            source_mode=source_mode,
            response_id=response_id,
            request_id=request_id,
            created_at=created_at,
            source_time_raw=source_time_raw,
            source_time_status=source_time_status,
            source_sha256=digest,
        )
        if branch == "archiveUrl":
            if len(data) > _MAX_INITIAL_URLS[name]:
                raise EisFeedContractError("TOO_MANY_ARCHIVES")
            urls = tuple(
                validate_eis_archive_url(child.text or "", doc_request_uid=request_id)
                for child in data
            )
            if len(set(urls)) != len(urls):
                raise EisFeedContractError("DUPLICATE_ARCHIVE_URL")
            return replace(base, state="LINKS_PENDING", archive_urls=urls)
        if len(data) != 1:
            raise EisFeedContractError("RESPONSE_BRANCH_INVALID")
        if branch == "noData" and (data[0].text or "").strip() in {"true", "1"}:
            return base
        if branch == "errorInfo":
            try:
                code = int(_text(data[0], "code"))
            except ValueError as exc:
                raise EisFeedContractError("ERROR_CODE_INVALID") from exc
            _text(data[0], "message")
            return replace(base, state="SERVICE_ERROR", error_code=code)
        raise EisFeedContractError("RESPONSE_BRANCH_INVALID")

    doc_request_uid = _guid(_text(payload, "docRequestUid"))
    prepared_data = payload.find("dataInfo")
    error_info = payload.find("errorInfo")
    if (prepared_data is None) == (error_info is None):
        raise EisFeedContractError("RESPONSE_BRANCH_INVALID")
    base = EisFeedResponse(
        service=service,
        kind="PREPARED",
        state="PREPARING",
        source_mode=source_mode,
        response_id=response_id,
        request_id=request_id,
        created_at=created_at,
        source_time_raw=source_time_raw,
        source_time_status=source_time_status,
        source_sha256=digest,
        doc_request_uid=doc_request_uid,
    )
    if error_info is not None:
        try:
            code = int(_text(error_info, "code"))
        except ValueError as exc:
            raise EisFeedContractError("ERROR_CODE_INVALID") from exc
        _text(error_info, "message")
        return replace(base, state="SERVICE_ERROR", error_code=code)
    assert prepared_data is not None
    completed = _text(prepared_data, "isPreparationCompleted")
    if completed not in {"true", "false", "1", "0"}:
        raise EisFeedContractError("PREPARATION_STATE_INVALID")
    if any(
        child.tag
        not in {"isPreparationCompleted", "preparedPartInfo", "preparedNotDownloadPartInfo"}
        for child in prepared_data
    ):
        raise EisFeedContractError("PREPARATION_FIELD_UNKNOWN")

    def archive_refs(tag: str) -> tuple[EisArchiveReference, ...]:
        refs: list[EisArchiveReference] = []
        for item in prepared_data.findall(tag):
            uid = _text(item, "dsUid")
            if not _UID32.fullmatch(uid):
                raise EisFeedContractError("ARCHIVE_UID_INVALID")
            url = validate_eis_archive_url(_text(item, "url"), doc_request_uid=doc_request_uid)
            compound_uid = parse_qs(urlsplit(url).query)["compoundUid"][0]
            if UUID(compound_uid).hex != uid.lower():
                raise EisFeedContractError("ARCHIVE_UID_MISMATCH")
            refs.append(EisArchiveReference(url=url, archive_uid=uid.lower()))
        if len({ref.archive_uid for ref in refs}) != len(refs):
            raise EisFeedContractError("DUPLICATE_ARCHIVE_UID")
        return tuple(refs)

    all_prepared = archive_refs("preparedPartInfo")
    not_downloaded = archive_refs("preparedNotDownloadPartInfo")
    by_uid = {ref.archive_uid: ref for ref in all_prepared}
    for ref in not_downloaded:
        if ref.archive_uid in by_uid and by_uid[ref.archive_uid] != ref:
            raise EisFeedContractError("ARCHIVE_REFERENCE_CONFLICT")
        by_uid[ref.archive_uid] = ref
    if completed in {"true", "1"} and not by_uid:
        raise EisFeedContractError("PREPARED_WITHOUT_ARCHIVES")
    return replace(
        base,
        state="READY" if completed in {"true", "1"} else "PREPARING",
        prepared_archives=tuple(by_uid.values()),
        not_downloaded_archives=not_downloaded,
    )
