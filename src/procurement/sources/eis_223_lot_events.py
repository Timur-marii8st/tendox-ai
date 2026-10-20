"""Bounded exact reader for RI223 purchase-lot cancellation events."""

from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from datetime import date, datetime
from io import BytesIO
from typing import Literal
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from lxml import etree as E  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import (
    MAX_ARCHIVE_BYTES,
    MAX_EXPANDED_BYTES,
    MAX_MEMBERS,
    MAX_XML_BYTES,
    PURCHASE_NS,
    TYPES_NS,
    TextFact,
    TimeFact,
)
from procurement.sources.eis_223_events import Eis223EventSchemaCheck
from procurement.sources.eis_223_schema import SCHEMAS, VALIDATOR, SchemaDiagnostic, SchemaTree

EVENT_TYPE: Literal["purchaseLotCancellation"] = "purchaseLotCancellation"
BASE = f"{EVENT_TYPE}/p:body/p:item/p:{EVENT_TYPE}Data"
HEADER = f"{EVENT_TYPE}/t:header"
ITEM_GUID = f"{EVENT_TYPE}/p:body/p:item/t:guid"
_GUID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")


class Eis223LotEventContractError(ValueError):
    """The exact event bytes violate the bounded contract."""


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DateFact(Model):
    value: date | None
    raw: str | None
    timezone_raw: str | None
    provenance: Provenance
    status: Literal["DATE", "UNKNOWN"]

    @model_validator(mode="after")
    def _consistent(self) -> DateFact:
        if (self.value is None) != (self.status == "UNKNOWN"):
            raise ValueError("DATE_FACT_INVALID")
        return self


class Eis223CancelledLot(Model):
    lot_guid: TextFact
    ordinal: TextFact
    subject: TextFact
    joint_lot: TextFact
    cancellation_date: DateFact
    cancellation_cause: TextFact


class Eis223LotCancellation(Model):
    event_type: Literal["purchaseLotCancellation"] = EVENT_TYPE
    event_guid: TextFact
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    purchase_number_provenance: Provenance
    purchase_guid: TextFact
    created_at: TimeFact
    publication_at: TimeFact
    header_guid: TextFact
    header_created_at: TimeFact
    item_guid: TextFact
    description_type: Literal["COMMON", "VARIOUS"]
    description_type_provenance: Provenance
    common_cancellation_date: DateFact
    common_cancellation_cause: TextFact
    cancelled_lots: tuple[Eis223CancelledLot, ...] = Field(max_length=200)
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_member: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _bound_provenance(self) -> Eis223LotCancellation:
        guids = [self.event_guid, self.header_guid, self.item_guid]
        guids.extend(item.lot_guid for item in self.cancelled_lots)
        if self.purchase_guid.raw is not None:
            guids.append(self.purchase_guid)
        if any(
            fact.raw is None
            or not _GUID.fullmatch(fact.raw)
            or fact.value != fact.raw.lower()
            for fact in guids
        ):
            raise ValueError("GUID_NORMALIZATION_INVALID")

        def check(value: object) -> None:
            if isinstance(value, Provenance) and value.document_id != self.xml_sha256:
                raise ValueError("EVENT_PROVENANCE_INVALID")
            if isinstance(value, BaseModel):
                for name in type(value).model_fields:
                    check(getattr(value, name))
            if isinstance(value, tuple):
                for item in value:
                    check(item)

        for name in type(self).model_fields:
            check(getattr(self, name))
        return self


class Eis223LotEventArchiveInspection(Model):
    company_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1, max_length=500)
    records: tuple[Eis223LotCancellation, ...]
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"


def _children(parent: ET.Element, ns: str, name: str) -> list[ET.Element]:
    matches = [child for child in parent if child.tag.rsplit("}", 1)[-1] == name]
    if any(child.tag != f"{{{ns}}}{name}" for child in matches):
        raise Eis223LotEventContractError("FIELD_NAMESPACE_INVALID")
    return matches


def _one(parent: ET.Element, ns: str, name: str) -> ET.Element:
    values = _children(parent, ns, name)
    if len(values) != 1:
        raise Eis223LotEventContractError("FIELD_MISSING_OR_DUPLICATE")
    return values[0]


def _optional(parent: ET.Element, ns: str, name: str) -> ET.Element | None:
    values = _children(parent, ns, name)
    if len(values) > 1:
        raise Eis223LotEventContractError("FIELD_DUPLICATE")
    return values[0] if values else None


def _raw(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    if len(element):
        raise Eis223LotEventContractError("SCALAR_NESTED")
    return (element.text or "").strip() or None


def _prov(sha: str, locator: str) -> Provenance:
    return Provenance(document_id=sha, locator=locator, extractor=Extractor.API)


def _text(parent: ET.Element, ns: str, name: str, sha: str, path: str) -> TextFact:
    raw = _raw(_optional(parent, ns, name))
    if raw is not None and len(raw) > 10000:
        raise Eis223LotEventContractError("TEXT_LIMIT")
    return TextFact(value=raw, raw=raw, provenance=_prov(sha, path))


def _guid(parent: ET.Element, ns: str, name: str, sha: str, path: str) -> TextFact:
    raw = _raw(_one(parent, ns, name))
    if raw is None or not _GUID.fullmatch(raw):
        raise Eis223LotEventContractError("GUID_INVALID")
    return TextFact(value=raw.lower(), raw=raw, provenance=_prov(sha, path))


def _optional_guid(parent: ET.Element, ns: str, name: str, sha: str, path: str) -> TextFact:
    raw = _raw(_optional(parent, ns, name))
    if raw is not None and not _GUID.fullmatch(raw):
        raise Eis223LotEventContractError("GUID_INVALID")
    return TextFact(
        value=raw.lower() if raw is not None else None,
        raw=raw,
        provenance=_prov(sha, path),
    )


def _time(
    parent: ET.Element, ns: str, name: str, sha: str, path: str, *, required: bool = False
) -> TimeFact:
    raw = _raw(_one(parent, ns, name) if required else _optional(parent, ns, name))
    value = None
    if raw and len(raw) <= 100 and "T" in raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                value = parsed
        except ValueError:
            pass
    return TimeFact(
        value=value,
        raw=raw,
        provenance=_prov(sha, path),
        status="AWARE" if value else "UNKNOWN",
    )


def _date(parent: ET.Element, ns: str, name: str, sha: str, path: str) -> DateFact:
    raw = _raw(_optional(parent, ns, name))
    value = None
    timezone_raw = None
    match = re.fullmatch(
        r"([0-9]{4}-[0-9]{2}-[0-9]{2})(Z|[+-][0-9]{2}:[0-9]{2})?", raw or ""
    )
    if match:
        with suppress(ValueError):
            value = date.fromisoformat(match[1])
            timezone_raw = match[2]
    return DateFact(
        value=value,
        raw=raw,
        timezone_raw=timezone_raw,
        provenance=_prov(sha, path),
        status="DATE" if value else "UNKNOWN",
    )


def parse_purchase_lot_cancellation_xml(
    raw: bytes, *, source_member: str
) -> Eis223LotCancellation:
    if (
        not raw
        or len(raw) > MAX_XML_BYTES
        or b"\x00" in raw
        or any(marker in raw.upper() for marker in (b"<!DOCTYPE", b"<!ENTITY"))
    ):
        raise Eis223LotEventContractError("XML_REJECTED")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise Eis223LotEventContractError("XML_INVALID") from error
    if root.tag != f"{{{PURCHASE_NS}}}{EVENT_TYPE}":
        raise Eis223LotEventContractError("DOCUMENT_TYPE_UNSUPPORTED")
    header = _one(root, TYPES_NS, "header")
    item = _one(_one(root, PURCHASE_NS, "body"), PURCHASE_NS, "item")
    data = _one(item, PURCHASE_NS, "purchaseLotCancellationData")
    purchase = _one(data, PURCHASE_NS, "purchaseInfo")
    lots_parent = _one(data, PURCHASE_NS, "cancelledLots")
    lots_nodes = _children(lots_parent, PURCHASE_NS, "cancelledLot")
    if not 1 <= len(lots_nodes) <= 200:
        raise Eis223LotEventContractError("CANCELLED_LOT_COUNT_LIMIT")
    sha = hashlib.sha256(raw).hexdigest()
    number = _raw(_one(purchase, TYPES_NS, "purchaseNoticeNumber")) or ""
    if not re.fullmatch(r"[0-9]{11}", number, flags=re.ASCII):
        raise Eis223LotEventContractError("PURCHASE_NUMBER_INVALID")
    description = _raw(_one(data, PURCHASE_NS, "descriptionType")) or ""
    if description not in {"COMMON", "VARIOUS"}:
        raise Eis223LotEventContractError("DESCRIPTION_TYPE_INVALID")
    lots: list[Eis223CancelledLot] = []
    ordinals: set[int] = set()
    lot_guids: set[str | None] = set()
    for index, node in enumerate(lots_nodes, 1):
        path = f"{BASE}/p:cancelledLots/p:cancelledLot[{index}]"
        ordinal_raw = _raw(_one(node, PURCHASE_NS, "ordinalNumber")) or ""
        if not re.fullmatch(r"[0-9]+", ordinal_raw, flags=re.ASCII):
            raise Eis223LotEventContractError("LOT_ORDINAL_INVALID")
        ordinal = int(ordinal_raw)
        if ordinal <= 0 or ordinal in ordinals:
            raise Eis223LotEventContractError("LOT_ORDINAL_INVALID")
        ordinals.add(ordinal)
        joint_raw = _raw(_one(node, PURCHASE_NS, "jointLot"))
        if joint_raw not in {"true", "false", "1", "0"}:
            raise Eis223LotEventContractError("JOINT_LOT_INVALID")
        cancellation = _optional(node, PURCHASE_NS, "cancellation")
        cancellation_parent = cancellation if cancellation is not None else ET.Element("missing")
        lot_guid = _guid(node, PURCHASE_NS, "guid", sha, path + "/p:guid")
        if lot_guid.value in lot_guids:
            raise Eis223LotEventContractError("LOT_GUID_DUPLICATE")
        lot_guids.add(lot_guid.value)
        lots.append(
            Eis223CancelledLot(
                lot_guid=lot_guid,
                ordinal=TextFact(
                    value=ordinal_raw,
                    raw=ordinal_raw,
                    provenance=_prov(sha, path + "/p:ordinalNumber"),
                ),
                subject=_text(node, PURCHASE_NS, "subject", sha, path + "/p:subject"),
                joint_lot=TextFact(
                    value=joint_raw,
                    raw=joint_raw,
                    provenance=_prov(sha, path + "/p:jointLot"),
                ),
                cancellation_date=_date(
                    cancellation_parent,
                    TYPES_NS,
                    "cancelDate",
                    sha,
                    path + "/p:cancellation/t:cancelDate",
                ),
                cancellation_cause=_text(
                    cancellation_parent,
                    TYPES_NS,
                    "cancelInfo",
                    sha,
                    path + "/p:cancellation/t:cancelInfo",
                ),
            )
        )
    return Eis223LotCancellation(
        event_guid=_guid(data, PURCHASE_NS, "guid", sha, BASE + "/p:guid"),
        purchase_number=number,
        purchase_number_provenance=_prov(
            sha, BASE + "/p:purchaseInfo/t:purchaseNoticeNumber"
        ),
        purchase_guid=_optional_guid(
            purchase, TYPES_NS, "guid", sha, BASE + "/p:purchaseInfo/t:guid"
        ),
        created_at=_time(
            data,
            PURCHASE_NS,
            "createDateTime",
            sha,
            BASE + "/p:createDateTime",
            required=True,
        ),
        publication_at=_time(
            data, PURCHASE_NS, "publicationDateTime", sha, BASE + "/p:publicationDateTime"
        ),
        header_guid=_guid(header, TYPES_NS, "guid", sha, HEADER + "/t:guid"),
        header_created_at=_time(
            header,
            TYPES_NS,
            "createDateTime",
            sha,
            HEADER + "/t:createDateTime",
            required=True,
        ),
        item_guid=_guid(item, TYPES_NS, "guid", sha, ITEM_GUID),
        description_type=description,
        description_type_provenance=_prov(sha, BASE + "/p:descriptionType"),
        common_cancellation_date=_date(
            data, PURCHASE_NS, "cancelDate", sha, BASE + "/p:cancelDate"
        ),
        common_cancellation_cause=_text(
            data, PURCHASE_NS, "description", sha, BASE + "/p:description"
        ),
        cancelled_lots=tuple(lots),
        xml_sha256=sha,
        source_member=source_member,
    )


def inspect_purchase_lot_cancellation_archive(
    raw: bytes, *, company_id: str, source_response_sha256: str, source_locator: str
) -> Eis223LotEventArchiveInspection:
    if not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise Eis223LotEventContractError("ARCHIVE_BYTES_LIMIT")
    records: list[Eis223LotCancellation] = []
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                not members
                or len(members) > MAX_MEMBERS
                or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES
            ):
                raise Eis223LotEventContractError("ARCHIVE_EXPANSION_LIMIT")
            seen: set[str] = set()
            for member in members:
                name = member.orig_filename
                if (
                    name != member.filename
                    or name in seen
                    or not re.fullmatch(r"[^/\\:\x00]+\.xml", name)
                    or name in {".xml", "..xml"}
                    or member.flag_bits & 1
                    or member.compress_type not in {0, 8}
                    or (member.external_attr >> 16) & 0o170000 == 0o120000
                    or member.file_size > MAX_XML_BYTES
                ):
                    raise Eis223LotEventContractError("ARCHIVE_MEMBER_REJECTED")
                seen.add(name)
                with archive.open(member) as stream:
                    content = stream.read(MAX_XML_BYTES + 1)
                if len(content) != member.file_size:
                    raise Eis223LotEventContractError("XML_BYTES_INVALID")
                records.append(parse_purchase_lot_cancellation_xml(content, source_member=name))
    except (BadZipFile, RuntimeError, NotImplementedError) as error:
        raise Eis223LotEventContractError("ARCHIVE_INVALID") from error
    identities = [(item.event_guid.value, item.xml_sha256) for item in records]
    if len(set(identities)) != len(identities):
        raise Eis223LotEventContractError("EVENT_VARIANT_DUPLICATE")
    return Eis223LotEventArchiveInspection(
        company_id=company_id,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
        source_response_sha256=source_response_sha256,
        source_locator=source_locator,
        records=tuple(records),
    )


def validate_purchase_lot_cancellation_schema(
    event: Eis223LotCancellation, raw: bytes, tree: SchemaTree, *, now: datetime
) -> Eis223EventSchemaCheck:
    parsed = parse_purchase_lot_cancellation_xml(raw, source_member=event.source_member)
    if (parsed.event_guid.value, parsed.purchase_number, parsed.xml_sha256) != (
        event.event_guid.value,
        event.purchase_number,
        event.xml_sha256,
    ):
        raise ValueError("EVENT_SCHEMA_XML_IDENTITY_MISMATCH")
    valid = tree.compiled.validate(
        E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True))
    )
    diagnostics = () if valid else tuple(
        SchemaDiagnostic(
            line=max(0, error.line),
            path=(error.path or "")[:300],
            type_name=error.type_name[:100],
            message=error.message[:300],
        )
        for error in list(tree.compiled.error_log)[:4]
    )
    package, root_sha, digest = SCHEMAS[tree.release]
    return Eis223EventSchemaCheck(
        event_guid=event.event_guid.value or "",
        purchase_number=event.purchase_number,
        xml_sha256=event.xml_sha256,
        schema_release=tree.release,
        package_sha256=package,
        root_sha256=root_sha,
        tree_sha256=digest,
        validator_version=VALIDATOR,
        status="PASS" if valid else "FAIL",
        diagnostics=diagnostics,
        checked_at=now,
    )
