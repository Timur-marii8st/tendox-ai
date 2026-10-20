"""Bounded exact reader and offline schema evidence for RI223 rejection events."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import datetime
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
from procurement.sources.eis_223_schema import (
    SCHEMAS,
    VALIDATOR,
    SchemaDiagnostic,
    SchemaTree,
)

EVENT_TYPE: Literal["purchaseRejection"] = "purchaseRejection"
BASE = "purchaseRejection/p:body/p:item/p:purchaseRejectionData"
HEADER_BASE = "purchaseRejection/t:header"
ITEM_GUID_PATH = "purchaseRejection/p:body/p:item/t:guid"
_GUID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")


class Eis223EventContractError(ValueError):
    """The exact event bytes do not satisfy the bounded metadata contract."""


class EventModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Eis223PurchaseRejection(EventModel):
    event_type: Literal["purchaseRejection"] = EVENT_TYPE
    event_guid: TextFact
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    purchase_number_provenance: Provenance
    created_at: TimeFact
    publication_at: TimeFact
    rejection_at: TimeFact
    cause: TextFact
    placer_inn: TextFact
    placer_kpp: TextFact
    header_guid: TextFact
    header_created_at: TimeFact
    item_guid: TextFact
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_member: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _exact_source(self) -> Eis223PurchaseRejection:
        if self.event_guid.value is None or not _GUID.fullmatch(self.event_guid.raw or ""):
            raise ValueError("EVENT_GUID_INVALID")
        if self.event_guid.value != (self.event_guid.raw or "").lower():
            raise ValueError("EVENT_GUID_NORMALIZATION_INVALID")

        def check(value: object) -> None:
            if isinstance(value, Provenance):
                if value.document_id != self.xml_sha256:
                    raise ValueError("EVENT_PROVENANCE_INVALID")
                if not (
                    value.locator == BASE
                    or value.locator.startswith(BASE + "/")
                    or value.locator.startswith(HEADER_BASE + "/")
                    or value.locator == ITEM_GUID_PATH
                ):
                    raise ValueError("EVENT_LOCATOR_INVALID")
            elif isinstance(value, BaseModel):
                for name in type(value).model_fields:
                    check(getattr(value, name))

        for name in type(self).model_fields:
            check(getattr(self, name))
        return self


class Eis223EventArchiveInspection(EventModel):
    company_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1, max_length=500)
    records: tuple[Eis223PurchaseRejection, ...]
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"


class Eis223EventSchemaCheck(EventModel):
    event_guid: str = Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_release: Literal["16.2", "16.3"]
    package_sha256: str
    root_sha256: str
    tree_sha256: str
    validator_version: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    status: Literal["PASS", "FAIL"]
    diagnostics: tuple[SchemaDiagnostic, ...] = Field(max_length=4)
    checked_at: datetime

    @model_validator(mode="after")
    def _bound(self) -> Eis223EventSchemaCheck:
        if (self.package_sha256, self.root_sha256, self.tree_sha256) != SCHEMAS[
            self.schema_release
        ]:
            raise ValueError("SCHEMA_POLICY_MISMATCH")
        if (self.status == "FAIL") != bool(self.diagnostics):
            raise ValueError("SCHEMA_DIAGNOSTICS_MISMATCH")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        return self


class Eis223RejectionState(EventModel):
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    checked_at: datetime
    evidence_status: Literal["PASS", "UNKNOWN"]
    application_status: Literal["FAIL", "UNKNOWN"]
    current_procedure_status: Literal["UNKNOWN"] = "UNKNOWN"
    operation_hold: bool
    reason_codes: tuple[str, ...]
    events: tuple[Eis223PurchaseRejection, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def _state_invariants(self) -> Eis223RejectionState:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        if self.evidence_status == "PASS" and (
            self.application_status != "FAIL" or not self.operation_hold or not self.events
        ):
            raise ValueError("REJECTION_STATE_INVALID")
        if self.application_status == "FAIL" and self.evidence_status != "PASS":
            raise ValueError("REJECTION_STATE_INVALID")
        if self.operation_hold and not self.reason_codes:
            raise ValueError("REJECTION_HOLD_REASON_MISSING")
        return self


def resolve_purchase_rejection_state(
    purchase_number: str,
    events: Iterable[Eis223PurchaseRejection],
    schema_checks: Iterable[Eis223EventSchemaCheck],
    *,
    now: datetime,
    reason_codes: tuple[str, ...] = (),
    event_limit: int = 100,
) -> Eis223RejectionState:
    """Resolve immutable rejection evidence without inferring current procedure state."""
    if not re.fullmatch(r"[0-9]{11}", purchase_number, flags=re.ASCII):
        raise ValueError("PURCHASE_NUMBER_INVALID")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if event_limit != 100:
        raise ValueError("EVENT_LIMIT_POLICY_INVALID")
    supplied_reasons = set(reason_codes)
    material = tuple(events)
    if len(material) > event_limit or "EVENT_EVIDENCE_LIMIT" in supplied_reasons:
        reasons = tuple(
            sorted(
                supplied_reasons
                | {"EVENT_EVIDENCE_LIMIT", "PURCHASE_REJECTION_REVIEW_REQUIRED"}
            )
        )
        return Eis223RejectionState(
            purchase_number=purchase_number,
            checked_at=now,
            evidence_status="UNKNOWN",
            application_status="UNKNOWN",
            operation_hold=True,
            reason_codes=reasons,
            events=(),
        )
    identities = [(item.event_guid.value, item.xml_sha256) for item in material]
    if len(set(identities)) != len(identities):
        raise ValueError("EVENT_VARIANT_DUPLICATE")
    direct_guids = {
        item.event_guid.value for item in material if item.purchase_number == purchase_number
    }
    if any(
        item.purchase_number != purchase_number and item.event_guid.value not in direct_guids
        for item in material
    ):
        raise ValueError("EVENT_ASSOCIATION_INVALID")
    ordered = tuple(
        sorted(material, key=lambda item: (item.event_guid.value or "", item.xml_sha256))
    )
    if not ordered:
        reasons = tuple(sorted(supplied_reasons | {"NO_REJECTION_EVENT_EVIDENCE"}))
        return Eis223RejectionState(
            purchase_number=purchase_number,
            checked_at=now,
            evidence_status="UNKNOWN",
            application_status="UNKNOWN",
            operation_hold=False,
            reason_codes=reasons,
            events=(),
        )
    reason_set = set(supplied_reasons)
    grouped: dict[str, set[str]] = {}
    for item in ordered:
        grouped.setdefault(item.event_guid.value or "", set()).add(item.xml_sha256)
        if item.purchase_number != purchase_number:
            reason_set.add("EVENT_GUID_TARGET_CONFLICT")
    if any(len(digests) > 1 for digests in grouped.values()):
        reason_set.add("EVENT_GUID_VARIANTS")
    checks_by_variant: dict[tuple[str, str], dict[str, str]] = {}
    variants_by_identity = {
        (item.event_guid.value or "", item.xml_sha256): item for item in ordered
    }
    for check in schema_checks:
        identity = (check.event_guid, check.xml_sha256)
        event = variants_by_identity.get(identity)
        if event is None or check.purchase_number != event.purchase_number:
            raise ValueError("EVENT_SCHEMA_ASSOCIATION_INVALID")
        releases = checks_by_variant.setdefault(identity, {})
        if check.schema_release in releases:
            raise ValueError("EVENT_SCHEMA_CHECK_DUPLICATE")
        releases[check.schema_release] = check.status
    all_qualified = not reason_set.intersection(
        {"EVENT_GUID_VARIANTS", "EVENT_GUID_TARGET_CONFLICT"}
    )
    for item in ordered:
        releases = checks_by_variant.get((item.event_guid.value or "", item.xml_sha256), {})
        times = (item.created_at.value, item.publication_at.value, item.rejection_at.value)
        if releases != {"16.2": "PASS", "16.3": "PASS"} or any(
            value is None or value > now for value in times
        ):
            all_qualified = False
            reason_set.add("REJECTION_EVIDENCE_INCOMPLETE")
        created, publication, rejection = times
        if publication is not None and (
            (created is not None and created > publication)
            or (rejection is not None and rejection > publication)
        ):
            all_qualified = False
            reason_set.add("REJECTION_EVENT_TIME_ORDER_UNRESOLVED")
    reason_set.add(
        "PURCHASE_REJECTION_CONFIRMED"
        if all_qualified
        else "PURCHASE_REJECTION_REVIEW_REQUIRED"
    )
    return Eis223RejectionState(
        purchase_number=purchase_number,
        checked_at=now,
        evidence_status="PASS" if all_qualified else "UNKNOWN",
        application_status="FAIL" if all_qualified else "UNKNOWN",
        operation_hold=True,
        reason_codes=tuple(sorted(reason_set)),
        events=ordered,
    )


def _children(parent: ET.Element, namespace: str, name: str) -> list[ET.Element]:
    matches = [item for item in parent if item.tag.rsplit("}", 1)[-1] == name]
    if any(item.tag != f"{{{namespace}}}{name}" for item in matches):
        raise Eis223EventContractError("FIELD_NAMESPACE_INVALID")
    return matches


def _one(parent: ET.Element, namespace: str, name: str) -> ET.Element:
    matches = _children(parent, namespace, name)
    if len(matches) != 1:
        raise Eis223EventContractError("FIELD_MISSING_OR_DUPLICATE")
    return matches[0]


def _optional(parent: ET.Element, namespace: str, name: str) -> ET.Element | None:
    matches = _children(parent, namespace, name)
    if len(matches) > 1:
        raise Eis223EventContractError("FIELD_DUPLICATE")
    return matches[0] if matches else None


def _raw(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    if len(element):
        raise Eis223EventContractError("SCALAR_NESTED")
    return (element.text or "").strip() or None


def _provenance(sha: str, path: str) -> Provenance:
    return Provenance(document_id=sha, locator=path, extractor=Extractor.API)


def _text(parent: ET.Element, namespace: str, name: str, sha: str, path: str) -> TextFact:
    raw = _raw(_optional(parent, namespace, name))
    if raw is not None and len(raw) > 10000:
        raise Eis223EventContractError("TEXT_LIMIT")
    return TextFact(value=raw, raw=raw, provenance=_provenance(sha, path))


def _time(
    parent: ET.Element,
    namespace: str,
    name: str,
    sha: str,
    path: str,
    *,
    required: bool,
) -> TimeFact:
    element = _one(parent, namespace, name) if required else _optional(parent, namespace, name)
    raw = _raw(element)
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
        provenance=_provenance(sha, path),
        status="AWARE" if value is not None else "UNKNOWN",
    )


def _guid(parent: ET.Element, namespace: str, name: str, sha: str, path: str) -> TextFact:
    raw = _raw(_one(parent, namespace, name))
    if raw is None or not _GUID.fullmatch(raw):
        raise Eis223EventContractError("EVENT_GUID_INVALID")
    return TextFact(value=raw.lower(), raw=raw, provenance=_provenance(sha, path))


def parse_purchase_rejection_xml(raw: bytes, *, source_member: str) -> Eis223PurchaseRejection:
    if (
        not raw
        or len(raw) > MAX_XML_BYTES
        or b"\x00" in raw
        or any(marker in raw.upper() for marker in (b"<!DOCTYPE", b"<!ENTITY"))
    ):
        raise Eis223EventContractError("XML_REJECTED")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise Eis223EventContractError("XML_INVALID") from error
    if root.tag != f"{{{PURCHASE_NS}}}{EVENT_TYPE}":
        raise Eis223EventContractError("DOCUMENT_TYPE_UNSUPPORTED")
    body = _one(root, PURCHASE_NS, "body")
    item = _one(body, PURCHASE_NS, "item")
    data = _one(item, PURCHASE_NS, "purchaseRejectionData")
    sha = hashlib.sha256(raw).hexdigest()
    number = _raw(_one(data, PURCHASE_NS, "cancelNoticeRegistrationNumber")) or ""
    if not re.fullmatch(r"[0-9]{11}", number, flags=re.ASCII):
        raise Eis223EventContractError("PURCHASE_NUMBER_INVALID")
    header = _one(root, TYPES_NS, "header")
    placer = _one(data, PURCHASE_NS, "placer")
    main = _one(placer, TYPES_NS, "mainInfo")
    return Eis223PurchaseRejection(
        event_guid=_guid(data, PURCHASE_NS, "guid", sha, BASE + "/p:guid"),
        purchase_number=number,
        purchase_number_provenance=_provenance(
            sha, BASE + "/p:cancelNoticeRegistrationNumber"
        ),
        created_at=_time(
            data, PURCHASE_NS, "createDateTime", sha, BASE + "/p:createDateTime", required=True
        ),
        publication_at=_time(
            data,
            PURCHASE_NS,
            "publicationDateTime",
            sha,
            BASE + "/p:publicationDateTime",
            required=False,
        ),
        rejection_at=_time(
            data, PURCHASE_NS, "rejectionDate", sha, BASE + "/p:rejectionDate", required=True
        ),
        cause=_text(data, PURCHASE_NS, "causeForRejection", sha, BASE + "/p:causeForRejection"),
        placer_inn=_text(main, TYPES_NS, "inn", sha, BASE + "/p:placer/t:mainInfo/t:inn"),
        placer_kpp=_text(main, TYPES_NS, "kpp", sha, BASE + "/p:placer/t:mainInfo/t:kpp"),
        header_guid=_guid(header, TYPES_NS, "guid", sha, HEADER_BASE + "/t:guid"),
        header_created_at=_time(
            header,
            TYPES_NS,
            "createDateTime",
            sha,
            HEADER_BASE + "/t:createDateTime",
            required=True,
        ),
        item_guid=_guid(item, TYPES_NS, "guid", sha, ITEM_GUID_PATH),
        xml_sha256=sha,
        source_member=source_member,
    )


def inspect_purchase_rejection_archive(
    raw: bytes,
    *,
    company_id: str,
    source_response_sha256: str,
    source_locator: str,
) -> Eis223EventArchiveInspection:
    if not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise Eis223EventContractError("ARCHIVE_BYTES_LIMIT")
    records: list[Eis223PurchaseRejection] = []
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                not members
                or len(members) > MAX_MEMBERS
                or sum(member.file_size for member in members) > MAX_EXPANDED_BYTES
            ):
                raise Eis223EventContractError("ARCHIVE_EXPANSION_LIMIT")
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
                    raise Eis223EventContractError("ARCHIVE_MEMBER_REJECTED")
                seen.add(name)
                with archive.open(member) as stream:
                    content = stream.read(MAX_XML_BYTES + 1)
                if len(content) != member.file_size:
                    raise Eis223EventContractError("XML_BYTES_INVALID")
                records.append(parse_purchase_rejection_xml(content, source_member=name))
    except (BadZipFile, RuntimeError, NotImplementedError) as error:
        raise Eis223EventContractError("ARCHIVE_INVALID") from error
    identities = [(item.event_guid.value, item.xml_sha256) for item in records]
    if len(set(identities)) != len(identities):
        raise Eis223EventContractError("EVENT_VARIANT_DUPLICATE")
    return Eis223EventArchiveInspection(
        company_id=company_id,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
        source_response_sha256=source_response_sha256,
        source_locator=source_locator,
        records=tuple(records),
    )


def validate_purchase_rejection_schema(
    event: Eis223PurchaseRejection,
    raw: bytes,
    tree: SchemaTree,
    *,
    now: datetime,
) -> Eis223EventSchemaCheck:
    parsed = parse_purchase_rejection_xml(raw, source_member=event.source_member)
    if (parsed.event_guid.value, parsed.purchase_number, parsed.xml_sha256) != (
        event.event_guid.value,
        event.purchase_number,
        event.xml_sha256,
    ):
        raise ValueError("EVENT_SCHEMA_XML_IDENTITY_MISMATCH")
    valid = tree.compiled.validate(
        E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True))
    )
    diagnostics = (
        ()
        if valid
        else tuple(
            SchemaDiagnostic(
                line=max(0, error.line),
                path=(error.path or "")[:300],
                type_name=error.type_name[:100],
                message=error.message[:300],
            )
            for error in list(tree.compiled.error_log)[:4]
        )
    )
    package, root_sha, digest = SCHEMAS[tree.release]
    return Eis223EventSchemaCheck(
        event_guid=event.event_guid.value,
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
