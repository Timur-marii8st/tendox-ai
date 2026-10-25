"""Bounded, query-independent parsing of a 44-FZ EIS notice archive.

Only explicitly selected, verified EF2020/EZK2020/EOK2020 shapes are admitted.
An accepted archive is still not proof of a complete regional/hourly corpus.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit
from zipfile import BadZipFile, ZipFile

from pydantic import Field

_EXPORT_NS = "http://zakupki.gov.ru/oos/export/1"
_NUMBER = re.compile(r"^[0-9]{19,23}$")
_MAX_ZIP_BYTES = 50 * 1024 * 1024
_MAX_XML_BYTES = 64 * 1024 * 1024
_MAX_MEMBERS = 1000
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_FILE_UID = re.compile(r"^[0-9A-F]{32}$")
_MAX_ATTACHMENT_FILENAME_CHARS = 1024
# This bounds source metadata parsing; document download budgets belong to the
# separate document worker.  The XML/member limits remain the outer byte bound.
_MAX_ATTACHMENT_METADATA_ENTRIES = 4096
DEFAULT_NOTICE_TYPE = "epNotificationEF2020"
EVENT_TYPES = ("epNotificationCancel", "epNotificationCancelFailure")
COMPANION_TYPES = (
    "epClarificationDoc",
    "epProtocolEOK2020FirstSections",
    "epProtocolEOK2020SecondSections",
    "epProtocolEOK2020Final",
    "fcsPlacementResult",
    "fcsProposalsResult",
)
SUPPORTED_NOTICE_TYPES = (
    DEFAULT_NOTICE_TYPE,
    "epNotificationEZK2020",
    "epNotificationEOK2020",
    *EVENT_TYPES,
)


class EisFeedArchiveError(ValueError):
    """Archive cannot be indexed as an exact, fully parsed source window."""


@dataclass(frozen=True)
class EisAttachmentAlias:
    filename: str
    kind_code: str | None
    locator: str


@dataclass(frozen=True)
class EisOfficialAttachment:
    content_uid: str
    filename: str
    byte_count: int
    url: str
    kind_code: str | None
    locator: str
    aliases: tuple[EisAttachmentAlias, ...] = ()

    @property
    def reference_status(self) -> Literal["PASS", "UNKNOWN"]:
        """Совпадение URL/размера не разрешает неоднозначное имя или назначение."""
        return (
            "UNKNOWN"
            if any(
                (alias.filename, alias.kind_code) != (self.filename, self.kind_code)
                for alias in self.aliases
            )
            else "PASS"
        )


@dataclass(frozen=True)
class EisConcreteValue:
    value: Decimal | None
    raw: str
    locator: str


@dataclass(frozen=True)
class EisCharacteristicValue:
    quality_description: str | None
    minimum: Decimal | None
    minimum_operator: str | None
    maximum: Decimal | None
    maximum_operator: str | None
    unit: str | None
    locator: str
    concrete_values: tuple[EisConcreteValue, ...] = ()
    minimum_raw: str | None = None
    maximum_raw: str | None = None
    range_source_complete: Annotated[bool, Field(strict=True)] = False
    range_structure_unknown: Annotated[bool, Field(strict=True)] = False


@dataclass(frozen=True)
class EisCharacteristic:
    name: str
    source_kind: str
    filling_instruction_code: str | None
    values: tuple[EisCharacteristicValue, ...]
    locator: str


@dataclass(frozen=True)
class EisLotItem:
    name: str
    ktru_code: str | None
    okpd2_code: str | None
    quantity: Decimal | None
    unit: str | None
    unit_price_rub: Decimal | None
    line_sum_rub: Decimal | None
    foreign_goods_prohibited: bool | None
    locator: str
    characteristics: tuple[EisCharacteristic, ...] = ()


@dataclass(frozen=True)
class EisNoticeSnapshot:
    purchase_number: str
    document_type: str
    version_number: int
    title: str
    published_at: datetime | None
    deadline: datetime | None
    nmck_rub: Decimal | None
    xml_sha256: str
    source_member: str
    attachments: tuple[EisOfficialAttachment, ...] = ()
    lot_items: tuple[EisLotItem, ...] = ()
    lot_parse_status: str = "UNKNOWN"


@dataclass(frozen=True)
class EisProcedureEvent:
    purchase_number: str
    document_type: str
    document_id: str
    published_at: datetime | None
    recovery_stage: str | None
    xml_sha256: str
    source_member: str
    locator: str
    parser_version: str = "eis-procedure-event-v1"


@dataclass(frozen=True)
class EisArchiveInspection:
    archive_sha256: str
    source_response_sha256: str
    source_locator: str
    records: tuple[EisNoticeSnapshot, ...]
    corpus_coverage: str = "UNKNOWN"
    events: tuple[EisProcedureEvent, ...] = ()


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(parent: ET.Element, name: str) -> ET.Element:
    matches = [item for item in parent if _name(item) == name]
    if len(matches) != 1:
        raise EisFeedArchiveError("FIELD_MISSING_OR_DUPLICATE")
    return matches[0]


def _optional_child(parent: ET.Element, name: str) -> ET.Element | None:
    matches = [item for item in parent if _name(item) == name]
    if len(matches) > 1:
        raise EisFeedArchiveError("FIELD_DUPLICATE")
    return matches[0] if matches else None


def _value(parent: ET.Element, name: str) -> str:
    text = (_child(parent, name).text or "").strip()
    if not text:
        raise EisFeedArchiveError("FIELD_EMPTY")
    return text


def _aware(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _price(notification: ET.Element) -> Decimal | None:
    conditions = _optional_child(notification, "contractConditionsInfo")
    if conditions is None:
        return None
    block = _optional_child(conditions, "maxPriceInfo")
    if block is None:
        return None
    currency = _optional_child(block, "currency")
    if currency is None or _value(currency, "code") not in {"RUB", "643", "RUR"}:
        return None
    try:
        value = Decimal(_value(block, "maxPrice"))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def _optional_value(parent: ET.Element, name: str) -> str | None:
    child = _optional_child(parent, name)
    if child is None:
        return None
    return (child.text or "").strip() or None


def _decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def _characteristic_decimal(raw: str | None) -> Decimal | None:
    """Physical characteristics may be signed; malformed text remains unknown."""
    if raw is None or len(raw) > 128:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() and abs(value.adjusted()) <= 100 else None


def _range_source(
    value: ET.Element,
) -> tuple[str | None, str | None, str | None, str | None, bool, bool]:
    """Retain exact bound text and attest only one narrowly recognized range shape."""
    range_sets = [child for child in value if _name(child) == "rangeSet"]
    if not range_sets:
        return None, None, None, None, False, False
    if len(range_sets) != 1:
        return None, None, None, None, False, True
    range_set = range_sets[0]
    ranges = [child for child in range_set if _name(child) == "valueRange"]
    value_range = ranges[0] if len(ranges) == 1 else None
    if value_range is None:
        return None, None, None, None, False, True

    allowed = {"min", "minMathNotation", "max", "maxMathNotation"}
    groups: dict[str, list[ET.Element]] = {name: [] for name in allowed}
    structure_complete = (
        len(range_set) == 1
        and _name(range_set[0]) == "valueRange"
        and len(value_range) > 0
        and not range_set.attrib
        and not value_range.attrib
        and not (range_set.text or "").strip()
        and not (value_range.text or "").strip()
        and not (value_range.tail or "").strip()
    )
    for child in value_range:
        name = _name(child)
        if name not in allowed:
            structure_complete = False
            continue
        groups[name].append(child)
        if len(child) != 0 or child.attrib or (child.tail or "").strip():
            structure_complete = False
    if any(len(items) > 1 for items in groups.values()):
        structure_complete = False
    if not structure_complete:
        return None, None, None, None, False, True

    value_children: dict[str, list[ET.Element]] = {}
    for child in value:
        value_children.setdefault(_name(child), []).append(child)
    permitted = {"sid", "externalSid", "valueFormat", "OKEI", "rangeSet"}
    complete = (
        not (value.text or "").strip()
        and all(name in permitted for name in value_children)
        and all(not (child.tail or "").strip() for child in value)
    )
    for metadata_name in ("sid", "externalSid", "valueFormat"):
        metadata = value_children.get(metadata_name, [])
        if len(metadata) > 1 or any(len(child) or child.attrib for child in metadata):
            complete = False
    formats = value_children.get("valueFormat", [])
    if formats and (formats[0].text or "").strip() != "N":
        complete = False
    for identifier_name in ("sid", "externalSid"):
        identifiers = value_children.get(identifier_name, [])
        if identifiers and not (identifiers[0].text or "").strip():
            complete = False

    def raw(name: str) -> str | None:
        items = groups[name]
        return (items[0].text or "").strip() if len(items) == 1 else None

    return (
        raw("min"),
        raw("minMathNotation"),
        raw("max"),
        raw("maxMathNotation"),
        complete,
        False,
    )


def _official_url(url: str, uid: str) -> bool:
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, strict_parsing=True)
        return (
            parts.scheme == "https"
            and parts.hostname == "zakupki.gov.ru"
            and parts.port in {None, 443}
            and parts.username is None
            and parts.password is None
            and parts.path == "/44fz/filestore/public/1.0/download/priz/file.html"
            and not parts.fragment
            and query == {"uid": [uid]}
        )
    except ValueError:
        return False


def _attachment_filename_invalid(filename: str) -> bool:
    # Source display metadata is never a filesystem path. Forward slashes are
    # preserved verbatim; document processing applies its own basename gate.
    return len(filename) > _MAX_ATTACHMENT_FILENAME_CHARS or bool(re.search(r"[\\\x00]", filename))


def _attachments(notice: ET.Element) -> tuple[EisOfficialAttachment, ...]:
    block = _optional_child(notice, "attachmentsInfo")
    if block is None:
        return ()
    attachments = [child for child in block if _name(child) == "attachmentInfo"]
    if len(attachments) > _MAX_ATTACHMENT_METADATA_ENTRIES:
        raise EisFeedArchiveError("ATTACHMENT_METADATA_COUNT_LIMIT")
    result: list[EisOfficialAttachment] = []
    seen: dict[str, int] = {}
    for ordinal, element in enumerate(attachments, 1):
        uid = _value(element, "publishedContentId")
        filename = _value(element, "fileName")
        url = _value(element, "url")
        raw_size = _value(element, "fileSize")
        if (
            not _FILE_UID.fullmatch(uid)
            or not raw_size.isdecimal()
            or int(raw_size) < 0
            or _attachment_filename_invalid(filename)
            or not _official_url(url, uid)
        ):
            raise EisFeedArchiveError("ATTACHMENT_REFERENCE_INVALID")
        kind = _optional_child(element, "docKindInfo")
        attachment = EisOfficialAttachment(
            content_uid=uid,
            filename=filename,
            byte_count=int(raw_size),
            url=url,
            kind_code=_optional_value(kind, "code") if kind is not None else None,
            locator=f"{_name(notice)}/attachmentsInfo/attachmentInfo[{ordinal}]",
        )
        if uid in seen:
            index = seen[uid]
            previous = result[index]
            if (previous.url, previous.byte_count) != (attachment.url, attachment.byte_count):
                raise EisFeedArchiveError("ATTACHMENT_REFERENCE_INVALID")
            alias = EisAttachmentAlias(filename, attachment.kind_code, attachment.locator)
            result[index] = replace(previous, aliases=(*previous.aliases, alias))
        else:
            seen[uid] = len(result)
            result.append(attachment)
    return tuple(result)


def _characteristics(item: ET.Element, item_locator: str) -> tuple[EisCharacteristic, ...]:
    ktru = _optional_child(item, "KTRU")
    block = _optional_child(ktru, "characteristics") if ktru is not None else None
    if block is None:
        return ()
    result: list[EisCharacteristic] = []
    kind_counts: dict[str, int] = {}
    for characteristic in block:
        kind = _name(characteristic)
        if kind not in {"characteristicsUsingReferenceInfo", "characteristicsUsingTextForm"}:
            continue
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        locator = f"{item_locator}/KTRU/characteristics/{kind}[{kind_counts[kind]}]"
        values_block = _optional_child(characteristic, "values")
        values: list[EisCharacteristicValue] = []
        if values_block is not None:
            for value_ordinal, value in enumerate(values_block, 1):
                if _name(value) != "value":
                    continue
                (
                    minimum_raw,
                    minimum_operator,
                    maximum_raw,
                    maximum_operator,
                    range_complete,
                    range_structure_unknown,
                ) = _range_source(value)
                okei = _optional_child(value, "OKEI")
                value_set = _optional_child(value, "valueSet")
                value_locator = f"{locator}/values/value[{value_ordinal}]"
                concrete_values = (
                    tuple(
                        EisConcreteValue(
                            value=_characteristic_decimal((element.text or "").strip()),
                            raw=(element.text or "").strip(),
                            locator=f"{value_locator}/valueSet/concreteValue[{i}]",
                        )
                        for i, element in enumerate(
                            (e for e in value_set if _name(e) == "concreteValue"), 1
                        )
                    )
                    if value_set is not None
                    else ()
                )
                values.append(
                    EisCharacteristicValue(
                        quality_description=_optional_value(value, "qualityDescription"),
                        minimum=_characteristic_decimal(minimum_raw),
                        minimum_operator=minimum_operator,
                        maximum=_characteristic_decimal(maximum_raw),
                        maximum_operator=maximum_operator,
                        unit=_optional_value(okei, "name") if okei is not None else None,
                        locator=value_locator,
                        concrete_values=concrete_values,
                        minimum_raw=minimum_raw,
                        maximum_raw=maximum_raw,
                        range_source_complete=range_complete,
                        range_structure_unknown=range_structure_unknown,
                    )
                )
        instruction = _optional_child(characteristic, "characteristicsFillingInstruction")
        result.append(
            EisCharacteristic(
                name=_value(characteristic, "name"),
                source_kind=kind,
                filling_instruction_code=(
                    _optional_value(instruction, "code") if instruction is not None else None
                ),
                values=tuple(values),
                locator=locator,
            )
        )
    return tuple(result)


def _lot_items(notification: ET.Element, document_type: str) -> tuple[tuple[EisLotItem, ...], str]:
    block = _optional_child(notification, "purchaseObjectsInfo")
    goods = _optional_child(block, "notDrugPurchaseObjectsInfo") if block is not None else None
    if goods is None:
        return (), "UNKNOWN"
    objects = [child for child in goods if _name(child) == "purchaseObject"]
    if not objects or len(objects) > 1000:
        return (), "UNKNOWN"
    items: list[EisLotItem] = []
    for ordinal, element in enumerate(objects, 1):
        ktru = _optional_child(element, "KTRU")
        okpd2 = _optional_child(ktru, "OKPD2") if ktru is not None else None
        okei = _optional_child(element, "OKEI")
        quantity = _optional_child(element, "quantity")
        restrictions = _optional_child(element, "restrictionsInfo")
        foreign = (
            _optional_value(restrictions, "isProhibitionForeignPurchaseObjects")
            if restrictions is not None
            else None
        )
        item_locator = (
            f"{document_type}/notificationInfo/purchaseObjectsInfo/"
            f"notDrugPurchaseObjectsInfo/purchaseObject[{ordinal}]"
        )
        items.append(
            EisLotItem(
                name=_value(element, "name"),
                ktru_code=_optional_value(ktru, "code") if ktru is not None else None,
                okpd2_code=_optional_value(okpd2, "OKPDCode") if okpd2 is not None else None,
                quantity=(
                    _decimal(_optional_value(quantity, "value")) if quantity is not None else None
                ),
                unit=_optional_value(okei, "name") if okei is not None else None,
                unit_price_rub=_decimal(_optional_value(element, "price")),
                line_sum_rub=_decimal(_optional_value(element, "sum")),
                foreign_goods_prohibited=(
                    True if foreign == "true" else False if foreign == "false" else None
                ),
                locator=item_locator,
                characteristics=_characteristics(element, item_locator),
            )
        )
    return tuple(items), "PARSED"


def _notice(
    xml: bytes,
    member: str,
    expected_document_type: str | None,
    *,
    allow_companion_documents: bool = False,
) -> EisNoticeSnapshot | EisProcedureEvent:
    if len(xml) > _MAX_XML_BYTES or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.I):
        raise EisFeedArchiveError("XML_UNSAFE")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise EisFeedArchiveError("XML_INVALID") from error
    if root.tag != f"{{{_EXPORT_NS}}}export" or len(root) != 1:
        raise EisFeedArchiveError("EXPORT_ENVELOPE_INVALID")
    notice = root[0]
    document_type = _name(notice)
    if (
        allow_companion_documents
        and expected_document_type is None
        and document_type in COMPANION_TYPES
        and notice.tag == f"{{{_EXPORT_NS}}}{document_type}"
    ):
        # Metadata family, not a parsed award/price/participation decision. Every
        # byte remains in the source archive, and content identity keeps revisions.
        result_type = document_type in {"fcsPlacementResult", "fcsProposalsResult"}
        field_ns = (
            "http://zakupki.gov.ru/oos/types/1"
            if document_type == "fcsPlacementResult"
            else "http://zakupki.gov.ru/oos/EPtypes/1"
        )
        common = notice if result_type else _child(notice, "commonInfo")
        number = _value(common, "purchaseNumber")
        number_node = _child(common, "purchaseNumber")
        if number_node.tag != f"{{{field_ns}}}purchaseNumber" or len(number_node):
            raise EisFeedArchiveError("COMPANION_FIELD_NAMESPACE_INVALID")
        if not _NUMBER.fullmatch(number):
            raise EisFeedArchiveError("PURCHASE_NUMBER_INVALID")
        if not result_type and common.tag != f"{{{field_ns}}}commonInfo":
            raise EisFeedArchiveError("COMPANION_FIELD_NAMESPACE_INVALID")
        publication = (
            "docPublishDTInEIS" if document_type == "epClarificationDoc" else "publishDTInEIS"
        )
        published = None if result_type else _optional_child(common, publication)
        if published is not None and (
            published.tag != f"{{{field_ns}}}{publication}" or len(published)
        ):
            raise EisFeedArchiveError("COMPANION_FIELD_NAMESPACE_INVALID")
        digest = hashlib.sha256(xml).hexdigest()
        return EisProcedureEvent(
            purchase_number=number,
            document_type=document_type,
            document_id=f"sha256:{digest}",
            published_at=_aware(published.text if published is not None else None),
            recovery_stage=None,
            xml_sha256=digest,
            source_member=member,
            locator=(
                f"{document_type}/"
                + ("purchaseNumber" if result_type else "commonInfo/purchaseNumber")
            ),
            parser_version="eis-companion-document-v1",
        )
    if (
        document_type not in SUPPORTED_NOTICE_TYPES
        or notice.tag != f"{{{_EXPORT_NS}}}{document_type}"
        or (expected_document_type is not None and document_type != expected_document_type)
    ):
        raise EisFeedArchiveError("DOCUMENT_TYPE_UNSUPPORTED")
    number = _value(_child(notice, "commonInfo"), "purchaseNumber")
    if not _NUMBER.fullmatch(number):
        raise EisFeedArchiveError("PURCHASE_NUMBER_INVALID")
    if document_type in EVENT_TYPES:
        common = _child(notice, "commonInfo")
        digest = hashlib.sha256(xml).hexdigest()
        identifier = (
            _optional_value(notice, "id")
            or _optional_value(common, "docNumber")
            or f"sha256:{digest}"
        )
        if len(identifier) > 200 or re.search(r"[\x00-\x1f]", identifier):
            raise EisFeedArchiveError("EVENT_ID_INVALID")
        recovery = None
        if document_type == "epNotificationCancel":
            _child(notice, "cancelReasonInfo")
        else:
            recovery = _value(_child(notice, "cancelFailureInfo"), "recoveryToStage")
            if recovery not in {"NP", "AP", "CW", "FO", "CO"}:
                raise EisFeedArchiveError("RECOVERY_STAGE_INVALID")
        return EisProcedureEvent(
            purchase_number=number,
            document_type=document_type,
            document_id=identifier,
            published_at=_aware(_optional_value(common, "docPublishDTInEIS")),
            recovery_stage=recovery,
            xml_sha256=digest,
            source_member=member,
            locator=f"{document_type}/commonInfo/purchaseNumber",
        )
    raw_version = _value(notice, "versionNumber")
    if not raw_version.isdecimal() or int(raw_version) < 1:
        raise EisFeedArchiveError("VERSION_INVALID")
    common = _child(notice, "commonInfo")
    title = _value(common, "purchaseObjectInfo")
    if len(title) > 4000:
        raise EisFeedArchiveError("TITLE_LIMIT")
    notification = _child(notice, "notificationInfo")
    procedure = _optional_child(notification, "procedureInfo")
    collecting = _optional_child(procedure, "collectingInfo") if procedure is not None else None
    end = _optional_child(collecting, "endDT") if collecting is not None else None
    published = _optional_child(common, "publishDTInEIS")
    lot_items, lot_parse_status = _lot_items(notification, document_type)
    return EisNoticeSnapshot(
        purchase_number=number,
        document_type=document_type,
        version_number=int(raw_version),
        title=title,
        published_at=_aware(published.text if published is not None else None),
        deadline=_aware(end.text if end is not None else None),
        nmck_rub=_price(notification),
        xml_sha256=hashlib.sha256(xml).hexdigest(),
        source_member=member,
        attachments=_attachments(notice),
        lot_items=lot_items,
        lot_parse_status=lot_parse_status,
    )


def inspect_eis_auction_archive(
    content: bytes,
    *,
    source_locator: str,
    source_response_sha256: str,
    expected_document_type: str | None = DEFAULT_NOTICE_TYPE,
    allow_companion_documents: bool = False,
) -> EisArchiveInspection:
    """Read every XML member or fail the entire archive; never silently skip one."""
    if expected_document_type is not None and expected_document_type not in SUPPORTED_NOTICE_TYPES:
        raise EisFeedArchiveError("DOCUMENT_TYPE_UNSUPPORTED")
    if not content or len(content) > _MAX_ZIP_BYTES or not content.startswith(b"PK\x03\x04"):
        raise EisFeedArchiveError("ARCHIVE_SIZE_OR_TYPE_INVALID")
    if not source_locator or not re.fullmatch(r"[0-9a-f]{64}", source_response_sha256):
        raise EisFeedArchiveError("PROVENANCE_INVALID")
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_MEMBERS:
                raise EisFeedArchiveError("MEMBER_COUNT_INVALID")
            if sum(info.file_size for info in infos) > _MAX_UNCOMPRESSED_BYTES:
                raise EisFeedArchiveError("ARCHIVE_EXPANSION_LIMIT")
            records: list[EisNoticeSnapshot] = []
            events: list[EisProcedureEvent] = []
            for info in infos:
                if (
                    info.is_dir()
                    or info.flag_bits & 1
                    or info.file_size > _MAX_XML_BYTES
                    or not info.filename.lower().endswith(".xml")
                    or "/" in info.filename
                    or "\\" in info.filename
                ):
                    raise EisFeedArchiveError("MEMBER_UNSUPPORTED")
                document = _notice(
                    archive.read(info),
                    info.filename,
                    expected_document_type,
                    allow_companion_documents=allow_companion_documents,
                )
                if isinstance(document, EisProcedureEvent):
                    events.append(document)
                else:
                    records.append(document)
    except (BadZipFile, RuntimeError) as error:
        raise EisFeedArchiveError("ARCHIVE_INVALID") from error
    if len({(item.purchase_number, item.version_number) for item in records}) != len(records):
        raise EisFeedArchiveError("DUPLICATE_NOTICE_VERSION")
    if len({(item.document_type, item.document_id) for item in events}) != len(events):
        raise EisFeedArchiveError("DUPLICATE_PROCEDURE_EVENT")
    return EisArchiveInspection(
        archive_sha256=hashlib.sha256(content).hexdigest(),
        source_response_sha256=source_response_sha256,
        source_locator=source_locator,
        records=tuple(records),
        events=tuple(events),
    )
