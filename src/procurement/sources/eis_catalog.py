"""Официальный advisory каталог типов; он не меняет allowlist загрузчика."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_feed import EisFeedContractError, validate_eis_archive_url

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
IP_NS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"
CATALOG_CODES = {"44": "nsiDocumentTypes", "223": "nsiDocumentTypes223"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CATALOG_ARCHIVES = 4
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 20
MAX_ENTRIES = 2000
EXPORT_NS = "http://zakupki.gov.ru/oos/export/1"
TYPES_NS = "http://zakupki.gov.ru/oos/types/1"
REFERENCE223_NS = "http://zakupki.gov.ru/223fz/reference/1"
TYPES223_NS = "http://zakupki.gov.ru/223fz/types/1"


class EisCatalogError(ValueError):
    """Фиксированный безопасный код ошибки, без текста внешнего источника."""


class CatalogModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisCatalogArchive(CatalogModel):
    url: str
    name: str
    locator: str


class EisCatalogResponse(CatalogModel):
    request_id: str
    response_id: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_time_raw: str
    created_at: datetime | None
    state: Literal["READY", "NO_DATA", "SERVICE_ERROR"]
    archives: tuple[EisCatalogArchive, ...] = ()
    error_code: int | None = None
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


class EisCatalogSourceField(CatalogModel):
    name: str
    raw_value: str
    provenance: Provenance


class EisCatalogEntry(CatalogModel):
    law: Literal["44", "223"]
    document_type: str
    document_name: str
    subsystem: str
    distributed_publicly: Literal["PASS", "FAIL", "UNKNOWN"]
    actual: Literal["PASS", "FAIL", "UNKNOWN"]
    updated_at: datetime | None
    source_member: str
    source_xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fields: tuple[EisCatalogSourceField, ...]
    adapter_admission: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


class EisCatalogInspection(CatalogModel):
    law: Literal["44", "223"]
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_locator: str
    entries: tuple[EisCatalogEntry, ...]
    contract_basis: Literal["XSD_16_3_AND_LIVE", "OBSERVED_LIVE_223"]
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


def _guid(value: str) -> str:
    if not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", value):
        raise EisCatalogError("CATALOG_GUID_INVALID")
    return str(UUID(value))


def _xml(raw: bytes, limit: int) -> ET.Element:
    if not 0 < len(raw) <= limit:
        raise EisCatalogError("CATALOG_XML_SIZE_INVALID")
    # Reject UTF-16/32 too: otherwise a byte-level declaration guard can be bypassed.
    if b"\x00" in raw or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise EisCatalogError("CATALOG_XML_DECLARATION_UNTRUSTED")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as error:
        raise EisCatalogError("CATALOG_XML_INVALID") from error


def _fields(parent: ET.Element, expected: tuple[str, ...]) -> None:
    if tuple(child.tag for child in parent) != expected:
        raise EisCatalogError("CATALOG_FIELDS_INVALID")


def _text(parent: ET.Element, name: str, *, limit: int = 4096) -> str:
    found = parent.findall(name)
    if len(found) != 1 or len(found[0]):
        raise EisCatalogError("CATALOG_FIELD_MISSING_OR_DUPLICATE")
    value = (found[0].text or "").strip()
    if not value or len(value) > limit:
        raise EisCatalogError("CATALOG_FIELD_EMPTY_OR_LARGE")
    return value


def catalog_request(token: str, request_id: str, law: Literal["44", "223"]) -> bytes:
    """Только два фиксированных full NSI запроса; исходящий token не сохраняется."""
    if law not in CATALOG_CODES or not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token):
        raise EisCatalogError("CATALOG_REQUEST_INVALID")
    envelope = ET.Element(f"{{{SOAP_NS}}}Envelope")
    header = ET.SubElement(envelope, f"{{{SOAP_NS}}}Header")
    ET.SubElement(header, "individualPerson_token").text = token
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    payload = ET.SubElement(body, f"{{{IP_NS}}}getNsiRequest")
    index = ET.SubElement(payload, "index")
    for name, value in (
        ("id", _guid(request_id)),
        ("createDateTime", datetime.now(UTC).isoformat()),
        ("mode", "PROD"),
    ):
        ET.SubElement(index, name).text = value
    params = ET.SubElement(payload, "selectionParams")
    ET.SubElement(params, f"nsiCode{law}").text = CATALOG_CODES[law]
    ET.SubElement(params, "nsiKind").text = "all"
    serialized = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    assert isinstance(serialized, bytes)
    return serialized


def parse_catalog_response(raw: bytes, *, request_id: str) -> EisCatalogResponse:
    """getNsiResponse содержит готовые архивы; getPreparedPart не применяется."""
    root = _xml(raw, MAX_RESPONSE_BYTES)
    if root.tag != f"{{{SOAP_NS}}}Envelope":
        raise EisCatalogError("CATALOG_SOAP_INVALID")
    if tuple(child.tag for child in root) not in (
        (f"{{{SOAP_NS}}}Body",),
        (f"{{{SOAP_NS}}}Header", f"{{{SOAP_NS}}}Body"),
    ):
        raise EisCatalogError("CATALOG_SOAP_INVALID")
    bodies = root.findall(f"{{{SOAP_NS}}}Body")
    if len(bodies) != 1 or len(bodies[0]) != 1:
        raise EisCatalogError("CATALOG_SOAP_INVALID")
    payload = bodies[0][0]
    if payload.tag != f"{{{IP_NS}}}getNsiResponse":
        raise EisCatalogError("CATALOG_RESPONSE_TYPE_INVALID")
    _fields(payload, ("index", "dataInfo"))
    index, data = payload
    _fields(index, ("id", "refId", "createDateTime", "mode"))
    if _guid(_text(index, "refId")) != _guid(request_id):
        raise EisCatalogError("CATALOG_REQUEST_MISMATCH")
    if _text(index, "mode") != "PROD":
        raise EisCatalogError("CATALOG_MODE_INVALID")
    source_time = _text(index, "createDateTime")
    try:
        parsed_time = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
    except ValueError as error:
        raise EisCatalogError("CATALOG_TIME_INVALID") from error
    created_at = parsed_time if parsed_time.utcoffset() is not None else None
    common = dict(
        request_id=_guid(request_id),
        response_id=_guid(_text(index, "id")),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        source_time_raw=source_time,
        created_at=created_at,
    )
    branches = tuple(child.tag for child in data)
    if branches == ("noData",) and _text(data, "noData") in {"true", "1"}:
        return EisCatalogResponse(**common, state="NO_DATA")
    if branches == ("errorInfo",):
        _fields(data[0], ("code", "message"))
        value = _text(data[0], "code", limit=12)
        if not re.fullmatch(r"-?[0-9]+", value):
            raise EisCatalogError("CATALOG_ERROR_CODE_INVALID")
        _text(data[0], "message")  # Untrusted error text is never surfaced as instructions/logs.
        return EisCatalogResponse(**common, state="SERVICE_ERROR", error_code=int(value))
    if not 0 < len(data) <= MAX_CATALOG_ARCHIVES or set(branches) != {"nsiArchiveInfo"}:
        raise EisCatalogError("CATALOG_BRANCH_INVALID")
    archives = []
    for offset, item in enumerate(data, 1):
        _fields(item, ("archiveUrl", "archiveName"))
        try:
            url = validate_eis_archive_url(_text(item, "archiveUrl"), doc_request_uid=request_id)
        except EisFeedContractError as error:
            raise EisCatalogError("CATALOG_ARCHIVE_URL_INVALID") from error
        name = _text(item, "archiveName", limit=150)
        if "/" in name or "\\" in name or not name.lower().endswith(".zip"):
            raise EisCatalogError("CATALOG_ARCHIVE_NAME_INVALID")
        archives.append(
            EisCatalogArchive(
                url=url, name=name, locator=f"getNsiResponse/dataInfo/nsiArchiveInfo[{offset}]"
            )
        )
    if len({a.url for a in archives}) != len(archives):
        raise EisCatalogError("CATALOG_ARCHIVE_DUPLICATE")
    return EisCatalogResponse(**common, state="READY", archives=tuple(archives))


def _flag(parent: ET.Element, name: str) -> Literal["PASS", "FAIL", "UNKNOWN"]:
    found = parent.findall(name)
    if len(found) != 1 or len(found[0]):
        return "UNKNOWN"
    value = (found[0].text or "").strip()
    if value in {"true", "1"}:
        return "PASS"
    return "FAIL" if value in {"false", "0"} else "UNKNOWN"


def _entries(raw: bytes, member: str, law: Literal["44", "223"]) -> list[EisCatalogEntry]:
    root = _xml(raw, MAX_EXPANDED_BYTES)
    if law == "44":
        if root.tag != f"{{{EXPORT_NS}}}export":
            raise EisCatalogError("CATALOG_ROOT_INVALID")
        _fields(root, (f"{{{EXPORT_NS}}}nsiDocumentTypesList",))
        container = root[0]
        item_tag = f"{{{EXPORT_NS}}}nsiDocumentTypes"
        ns = TYPES_NS
        subsystem, public, actual, updated = (
            "subsystemType",
            "isDistributedPublicly",
            "isActual",
            "updateDate",
        )
        allowed = {"documentType", "documentName", subsystem, public, actual, updated}
        prefix = "export/nsiDocumentTypesList/nsiDocumentTypes"
    else:
        if root.tag != f"{{{REFERENCE223_NS}}}nsiDocumentTypes223":
            raise EisCatalogError("CATALOG_ROOT_INVALID")
        _fields(root, (f"{{{TYPES223_NS}}}header", f"{{{REFERENCE223_NS}}}body"))
        container = root[1]
        item_tag = f"{{{REFERENCE223_NS}}}item"
        ns = REFERENCE223_NS
        subsystem, public, actual, updated = (
            "subsystem",
            "distributedPublicly",
            "actual",
            "lastUpdateDate",
        )
        allowed = {"documentType", "documentName", subsystem, public, actual, updated, "createDate"}
        prefix = "nsiDocumentTypes223/body/item"
    if not 0 < len(container) <= MAX_ENTRIES or any(e.tag != item_tag for e in container):
        raise EisCatalogError("CATALOG_ITEMS_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    result = []
    for offset, item in enumerate(container, 1):
        if len(item) > 20 or any(
            e.tag not in {f"{{{ns}}}{name}" for name in allowed} or len(e.text or "") > 4096
            for e in item
        ):
            raise EisCatalogError("CATALOG_ENTRY_FIELDS_INVALID")
        code = _text(item, f"{{{ns}}}documentType", limit=100)
        system = _text(item, f"{{{ns}}}{subsystem}", limit=20)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}", code) or not re.fullmatch(
            r"[A-Z][A-Z0-9]{0,19}", system
        ):
            raise EisCatalogError("CATALOG_CODE_INVALID")
        fields = tuple(
            EisCatalogSourceField(
                name=e.tag.rsplit("}", 1)[-1],
                raw_value=(e.text or "").strip(),
                provenance=Provenance(
                    document_id=digest,
                    locator=f"{member} :: {prefix}[{offset}]/{e.tag.rsplit('}', 1)[-1]}"
                    + f"[source-field-{field_offset}]",
                    extractor=Extractor.API,
                ),
            )
            for field_offset, e in enumerate(item, 1)
        )
        updated_fields = item.findall(f"{{{ns}}}{updated}")
        updated_at = None
        if len(updated_fields) == 1 and not len(updated_fields[0]):
            try:
                parsed = datetime.fromisoformat(
                    (updated_fields[0].text or "").replace("Z", "+00:00")
                )
                updated_at = parsed if parsed.utcoffset() is not None else None
            except ValueError:
                pass
        result.append(
            EisCatalogEntry(
                law=law,
                document_type=code,
                document_name=_text(item, f"{{{ns}}}documentName"),
                subsystem=system,
                distributed_publicly=_flag(item, f"{{{ns}}}{public}"),
                actual=_flag(item, f"{{{ns}}}{actual}"),
                updated_at=updated_at,
                source_member=member,
                source_xml_sha256=digest,
                fields=fields,
            )
        )
    return result


def inspect_catalog_archive(
    raw: bytes,
    *,
    law: Literal["44", "223"],
    response: EisCatalogResponse,
    reference: EisCatalogArchive,
    forbidden_bytes: bytes | None = None,
) -> EisCatalogInspection:
    """Все XML members разбираются целиком; неполный snapshot не возвращается."""
    if law not in CATALOG_CODES or response.state != "READY" or reference not in response.archives:
        raise EisCatalogError("CATALOG_ARCHIVE_BINDING_INVALID")
    if not 0 < len(raw) <= MAX_ARCHIVE_BYTES or not raw.startswith(b"PK\x03\x04"):
        raise EisCatalogError("CATALOG_ARCHIVE_SIZE_INVALID")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            if not 0 < len(members) <= MAX_MEMBERS or len(set(names)) != len(names):
                raise EisCatalogError("CATALOG_MEMBERS_INVALID")
            if sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
                raise EisCatalogError("CATALOG_EXPANSION_LIMIT")
            entries: list[EisCatalogEntry] = []
            for member in members:
                path = PurePosixPath(member.orig_filename)
                if (
                    member.is_dir()
                    or member.flag_bits & 1
                    or member.compress_type not in {0, 8}
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in member.orig_filename
                    or ":" in member.orig_filename
                    or "\x00" in member.orig_filename
                    or len(member.orig_filename) > 200
                    or not member.filename.lower().endswith(".xml")
                    or member.file_size <= 0
                    or member.file_size > MAX_EXPANDED_BYTES
                    or (member.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise EisCatalogError("CATALOG_MEMBER_INVALID")
                # Stream cap protects against inconsistent ZIP size metadata too.
                with archive.open(member) as stream:
                    content = stream.read(MAX_EXPANDED_BYTES + 1)
                if len(content) != member.file_size:
                    raise EisCatalogError("CATALOG_MEMBER_SIZE_INVALID")
                if forbidden_bytes and forbidden_bytes in content:
                    raise EisCatalogError("CATALOG_SECRET_REFLECTION")
                entries.extend(_entries(content, member.filename, law))
                if len(entries) > MAX_ENTRIES:
                    raise EisCatalogError("CATALOG_ENTRY_LIMIT")
    except (BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        raise EisCatalogError("CATALOG_ARCHIVE_INVALID") from error
    if len({e.document_type for e in entries}) != len(entries):
        raise EisCatalogError("CATALOG_ENTRY_DUPLICATE")
    return EisCatalogInspection(
        law=law,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
        source_response_sha256=response.source_sha256,
        source_locator=reference.locator,
        entries=tuple(entries),
        contract_basis="XSD_16_3_AND_LIVE" if law == "44" else "OBSERVED_LIVE_223",
    )
