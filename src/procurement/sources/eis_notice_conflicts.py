"""Offline, bounded inventory of conflicting 44-FZ notice source documents."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eis_feed_archive import EVENT_TYPES, SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_rejected_evidence import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVES,
    MAX_COMPRESSED_BYTES,
    MAX_EXPANDED_BYTES,
    MAX_MEMBERS,
    MAX_XML_BYTES,
)

EXPORT_NS = "http://zakupki.gov.ru/oos/export/1"
NOTICE_NS = "http://zakupki.gov.ru/oos/EPtypes/1"
COMMON_NS = "http://zakupki.gov.ru/oos/common/1"
BASE_NS = "http://zakupki.gov.ru/oos/base/1"
ALLOWED_NAMESPACES = frozenset((EXPORT_NS, NOTICE_NS, COMMON_NS, BASE_NS))
SUPPORTED_CONFLICT_TYPES = frozenset(set(SUPPORTED_NOTICE_TYPES) - set(EVENT_TYPES))
MAX_TOTAL_MEMBERS = 2000
MAX_MEMBER_FILENAME_CHARS = 255
MAX_DIAGNOSIS_BYTES = 2 * 1024 * 1024
MAX_XML_NODES = 50_000
MAX_XML_DEPTH = 128
_NUMBER = re.compile(r"^[0-9]{19,23}$")
_UNSAFE_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.I)
_XML_ENCODING = re.compile(
    rb"^\s*<\?xml\s+[^?]*encoding\s*=\s*['\"]([^'\"]+)['\"]",
    re.I,
)


class EisNoticeConflictError(ValueError):
    """A complete conflict inventory could not be produced safely."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ConflictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisNoticeOccurrence(ConflictModel):
    archive_ordinal: int = Field(ge=0, lt=MAX_ARCHIVES)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_filename: str
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    non_timing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purchase_number: str | None
    version_number: int | None
    document_type: str | None
    document_id: str | None
    published_raw: str | None = Field(default=None, max_length=64)
    start_raw: str | None = Field(default=None, max_length=64)
    published_at: datetime | None
    start_at: datetime | None

    @model_validator(mode="after")
    def _source_facts_consistent(self) -> EisNoticeOccurrence:
        if self.purchase_number is not None and not _NUMBER.fullmatch(self.purchase_number):
            raise ValueError("OCCURRENCE_PURCHASE_NUMBER_INVALID")
        if self.version_number is not None and not 1 <= self.version_number <= 2**31 - 1:
            raise ValueError("OCCURRENCE_VERSION_INVALID")
        if self.document_type is not None and self.document_type not in SUPPORTED_CONFLICT_TYPES:
            raise ValueError("OCCURRENCE_DOCUMENT_TYPE_INVALID")
        if self.document_id is not None and _bounded_integer(
            self.document_id, -(2**63), 2**63 - 1
        ) is None:
            raise ValueError("OCCURRENCE_DOCUMENT_ID_INVALID")
        if self.published_at != _aware(self.published_raw) or self.start_at != _aware(
            self.start_raw
        ):
            raise ValueError("OCCURRENCE_TIMESTAMP_INVALID")
        return self


class EisNoticeDuplicateGroup(ConflictModel):
    classification: Literal["BYTE_IDENTICAL", "DIVERGENT"]
    document_identity: Literal["SAME", "DIFFERENT", "UNKNOWN"]
    purchase_number: str
    version_number: int
    document_types: tuple[str, ...] = Field(min_length=1)
    occurrences: tuple[EisNoticeOccurrence, ...] = Field(min_length=2)
    changed_fields: tuple[Literal["publication", "start"], ...] = ()
    other_fields_differ: bool
    difference_category_count: int = Field(ge=0)


class EisNoticeConflictDiagnosis(ConflictModel):
    status: Literal["COMPLETE"] = "COMPLETE"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    archive_sha256s: tuple[str, ...]
    archive_count: int = Field(ge=1, le=MAX_ARCHIVES)
    member_count: int = Field(ge=1, le=MAX_TOTAL_MEMBERS)
    occurrence_count: int = Field(ge=1, le=MAX_TOTAL_MEMBERS)
    duplicate_group_count: int = Field(ge=0)
    duplicate_occurrence_count: int = Field(ge=0)
    occurrences: tuple[EisNoticeOccurrence, ...]
    duplicate_groups: tuple[EisNoticeDuplicateGroup, ...]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _canonical_hash(self) -> EisNoticeConflictDiagnosis:
        payload = self.model_dump(mode="json", exclude={"sha256"})
        encoded = _canonical(payload)
        if len(encoded) > MAX_DIAGNOSIS_BYTES:
            raise ValueError("DIAGNOSIS_BYTES_LIMIT")
        if hashlib.sha256(encoded).hexdigest() != self.sha256:
            raise ValueError("DIAGNOSIS_SHA256_INVALID")
        if (
            self.archive_count != len(self.archive_sha256s)
            or self.member_count != len(self.occurrences)
            or self.occurrence_count != len(self.occurrences)
            or self.duplicate_group_count != len(self.duplicate_groups)
            or self.duplicate_occurrence_count
            != sum(len(group.occurrences) for group in self.duplicate_groups)
        ):
            raise ValueError("DIAGNOSIS_COUNTS_INVALID")
        ordinals = [item.archive_ordinal for item in self.occurrences]
        if ordinals != sorted(ordinals) or set(ordinals) != set(range(self.archive_count)):
            raise ValueError("DIAGNOSIS_ARCHIVE_ORDER_INVALID")
        if any(
            item.archive_sha256 != self.archive_sha256s[item.archive_ordinal]
            for item in self.occurrences
        ):
            raise ValueError("DIAGNOSIS_ARCHIVE_MEMBERSHIP_INVALID")
        self._validate_duplicate_groups()
        return self

    def _validate_duplicate_groups(self) -> None:
        expected: dict[tuple[str, int], list[EisNoticeOccurrence]] = defaultdict(list)
        for occurrence in self.occurrences:
            if occurrence.purchase_number is not None and occurrence.version_number is not None:
                expected[(occurrence.purchase_number, occurrence.version_number)].append(occurrence)
        expected = {key: value for key, value in expected.items() if len(value) > 1}
        actual_keys = [
            (group.purchase_number, group.version_number) for group in self.duplicate_groups
        ]
        if actual_keys != sorted(expected):
            raise ValueError("DIAGNOSIS_GROUP_KEYS_INVALID")
        for group in self.duplicate_groups:
            key = (group.purchase_number, group.version_number)
            occurrences = expected[key]
            if Counter(_occurrence_key(item) for item in group.occurrences) != Counter(
                _occurrence_key(item) for item in occurrences
            ):
                raise ValueError("DIAGNOSIS_GROUP_MEMBERSHIP_INVALID")
            document_types = tuple(
                sorted({item.document_type for item in occurrences if item.document_type})
            )
            classification = (
                "BYTE_IDENTICAL"
                if len({item.xml_sha256 for item in occurrences}) == 1
                else "DIVERGENT"
            )
            identities = {(item.document_type, item.document_id) for item in occurrences}
            if any(None in identity for identity in identities):
                identity_status = "UNKNOWN"
            elif len(identities) == 1:
                identity_status = "SAME"
            else:
                identity_status = "DIFFERENT"
            changed = tuple(
                field
                for field, values in (
                    ("publication", {item.published_raw for item in occurrences}),
                    ("start", {item.start_raw for item in occurrences}),
                )
                if len(values) > 1
            )
            other = len({item.non_timing_sha256 for item in occurrences}) > 1
            if (
                group.document_types != document_types
                or group.classification != classification
                or group.document_identity != identity_status
                or group.changed_fields != changed
                or group.other_fields_differ != other
                or group.difference_category_count != len(changed) + int(other)
            ):
                raise ValueError("DIAGNOSIS_GROUP_CLASSIFICATION_INVALID")

    def safe_summary(self) -> dict[str, object]:
        classes = Counter(group.classification for group in self.duplicate_groups)
        identities = Counter(group.document_identity for group in self.duplicate_groups)
        return {
            "status": self.status,
            "coverage": self.coverage,
            "archive_count": self.archive_count,
            "member_count": self.member_count,
            "occurrence_count": self.occurrence_count,
            "duplicate_group_count": self.duplicate_group_count,
            "duplicate_occurrence_count": self.duplicate_occurrence_count,
            "byte_identical_groups": classes["BYTE_IDENTICAL"],
            "divergent_groups": classes["DIVERGENT"],
            "same_identity_groups": identities["SAME"],
            "different_identity_groups": identities["DIFFERENT"],
            "unknown_identity_groups": identities["UNKNOWN"],
            "diagnosis_sha256": self.sha256,
        }


def diagnose_notice_conflicts(
    archives: tuple[bytes, ...], token: str
) -> EisNoticeConflictDiagnosis:
    """Inventory every supported notice occurrence without selecting a winner."""
    if not token:
        raise EisNoticeConflictError("TOKEN_MISSING")
    if not 1 <= len(archives) <= MAX_ARCHIVES:
        raise EisNoticeConflictError("ARCHIVE_COUNT_LIMIT")
    if sum(map(len, archives)) > MAX_COMPRESSED_BYTES:
        raise EisNoticeConflictError("COMPRESSED_BYTES_LIMIT")
    secret = token.encode()
    headers: list[tuple[int, str, str, bytes]] = []
    archive_sha256s: list[str] = []
    expanded = 0
    total_members = 0
    try:
        for archive_ordinal, raw in enumerate(archives):
            if not raw or len(raw) > MAX_ARCHIVE_BYTES or secret in raw:
                code = "TOKEN_REFLECTION" if secret in raw else "ARCHIVE_RESOURCE_LIMIT"
                raise EisNoticeConflictError(code)
            archive_sha = hashlib.sha256(raw).hexdigest()
            archive_sha256s.append(archive_sha)
            with ZipFile(BytesIO(raw)) as bundle:
                members = bundle.infolist()
                if not members or len(members) > MAX_MEMBERS:
                    raise EisNoticeConflictError("MEMBER_COUNT_LIMIT")
                names = [member.filename for member in members]
                if len(set(names)) != len(names):
                    raise EisNoticeConflictError("DUPLICATE_MEMBER_NAME")
                total_members += len(members)
                if total_members > MAX_TOTAL_MEMBERS:
                    raise EisNoticeConflictError("TOTAL_MEMBER_COUNT_LIMIT")
                for member in members:
                    if (
                        member.is_dir()
                        or member.flag_bits & 1
                        or member.file_size > MAX_XML_BYTES
                        or not _safe_member(member.filename)
                    ):
                        raise EisNoticeConflictError("MEMBER_UNSAFE")
                    expanded += member.file_size
                    if expanded > MAX_EXPANDED_BYTES:
                        raise EisNoticeConflictError("EXPANDED_BYTES_LIMIT")
                for member in members:
                    with bundle.open(member) as stream:
                        content = stream.read(MAX_XML_BYTES + 1)
                    if len(content) != member.file_size:
                        raise EisNoticeConflictError("MEMBER_SIZE_MISMATCH")
                    if secret in member.filename.encode(errors="replace") or secret in content:
                        raise EisNoticeConflictError("TOKEN_REFLECTION")
                    if _UNSAFE_XML.search(content):
                        raise EisNoticeConflictError("XML_UNSAFE")
                    try:
                        content.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise EisNoticeConflictError("XML_ENCODING_UNSUPPORTED") from error
                    declaration_source = (
                        content[3:] if content.startswith(b"\xef\xbb\xbf") else content
                    )
                    encoding = _XML_ENCODING.match(declaration_source)
                    if b"\x00" in content or (
                        encoding is not None
                        and encoding.group(1).lower() not in {b"utf-8", b"utf8"}
                    ):
                        raise EisNoticeConflictError("XML_ENCODING_UNSUPPORTED")
                    headers.append((archive_ordinal, archive_sha, member.filename, content))
    except (BadZipFile, RuntimeError) as error:
        raise EisNoticeConflictError("ARCHIVE_INVALID") from error

    parsed = tuple(_occurrence(*item, token) for item in headers)
    grouped: dict[tuple[str, int], list[tuple[EisNoticeOccurrence, bytes]]] = defaultdict(list)
    for occurrence, (_, _, _, content) in zip(parsed, headers, strict=True):
        if (
            occurrence.purchase_number is not None
            and occurrence.version_number is not None
        ):
            grouped[(occurrence.purchase_number, occurrence.version_number)].append(
                (occurrence, content)
            )
    groups = tuple(
        _group(key, values)
        for key, values in sorted(grouped.items())
        if len(values) > 1
    )
    payload: dict[str, object] = {
        "status": "COMPLETE",
        "coverage": "UNKNOWN",
        "archive_sha256s": archive_sha256s,
        "archive_count": len(archives),
        "member_count": total_members,
        "occurrence_count": len(parsed),
        "duplicate_group_count": len(groups),
        "duplicate_occurrence_count": sum(len(group.occurrences) for group in groups),
        "occurrences": [item.model_dump(mode="json") for item in parsed],
        "duplicate_groups": [group.model_dump(mode="json") for group in groups],
    }
    encoded = _canonical(payload)
    if len(encoded) > MAX_DIAGNOSIS_BYTES:
        raise EisNoticeConflictError("DIAGNOSIS_BYTES_LIMIT")
    digest = hashlib.sha256(encoded).hexdigest()
    return EisNoticeConflictDiagnosis.model_validate({**payload, "sha256": digest})


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        name.lower().endswith(".xml")
        and "\\" not in name
        and not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) == 1
        and len(name) <= MAX_MEMBER_FILENAME_CHARS
    )


def _occurrence(
    archive_ordinal: int, archive_sha: str, member: str, content: bytes, token: str
) -> EisNoticeOccurrence:
    try:
        root = _parse_xml(content)
    except ET.ParseError as error:
        raise EisNoticeConflictError("XML_INVALID") from error
    if root.tag != f"{{{EXPORT_NS}}}export" or len(root) != 1:
        raise EisNoticeConflictError("EXPORT_ENVELOPE_INVALID")
    if _decoded_reflection(root, token):
        raise EisNoticeConflictError("TOKEN_REFLECTION")
    notice = root[0]
    namespace, document_type = _split(notice.tag)
    if namespace != EXPORT_NS or document_type not in SUPPORTED_CONFLICT_TYPES:
        raise EisNoticeConflictError("DOCUMENT_TYPE_UNSUPPORTED")
    _validate_namespaces(notice)
    common = _one(notice, NOTICE_NS, "commonInfo")
    notification = _one(notice, NOTICE_NS, "notificationInfo")
    procedure = _one(notification, NOTICE_NS, "procedureInfo") if notification is not None else None
    collecting = _one(procedure, NOTICE_NS, "collectingInfo") if procedure is not None else None
    number = _leaf_text(_one(common, NOTICE_NS, "purchaseNumber")) if common is not None else None
    if number is not None and not _NUMBER.fullmatch(number):
        number = None
    raw_version = _leaf_text(_one(notice, NOTICE_NS, "versionNumber"))
    version_value = _bounded_integer(raw_version, -(2**31), 2**31 - 1)
    version = version_value if version_value is not None and version_value >= 1 else None
    raw_id = _leaf_text(_one(notice, NOTICE_NS, "id"))
    document_id = raw_id if _bounded_integer(raw_id, -(2**63), 2**63 - 1) is not None else None
    published_raw = _leaf_source_text(_one(common, NOTICE_NS, "publishDTInEIS"))
    start_raw = _leaf_source_text(_one(collecting, NOTICE_NS, "startDT"))
    published = (
        _aware(published_raw)
        if common is not None
        else None
    )
    start = (
        _aware(start_raw)
        if collecting is not None
        else None
    )
    return EisNoticeOccurrence(
        archive_ordinal=archive_ordinal,
        archive_sha256=archive_sha,
        member_filename=member,
        xml_sha256=hashlib.sha256(content).hexdigest(),
        non_timing_sha256=hashlib.sha256(_without_timing(content)).hexdigest(),
        purchase_number=number,
        version_number=version,
        document_type=document_type,
        document_id=document_id,
        published_raw=published_raw,
        start_raw=start_raw,
        published_at=published,
        start_at=start,
    )


def _group(
    key: tuple[str, int], values: list[tuple[EisNoticeOccurrence, bytes]]
) -> EisNoticeDuplicateGroup:
    occurrences = tuple(item[0] for item in values)
    xml_hashes = {item.xml_sha256 for item in occurrences}
    identities = [(item.document_type, item.document_id) for item in occurrences]
    identity: Literal["SAME", "DIFFERENT", "UNKNOWN"]
    if any(
        document_id is None or document_type is None
        for document_type, document_id in identities
    ):
        identity = "UNKNOWN"
    elif len(set(identities)) == 1:
        identity = "SAME"
    else:
        identity = "DIFFERENT"
    changed: list[Literal["publication", "start"]] = []
    if len({item.published_raw for item in occurrences}) > 1:
        changed.append("publication")
    if len({item.start_raw for item in occurrences}) > 1:
        changed.append("start")
    stripped = {_without_timing(content) for _, content in values}
    other = len(stripped) > 1
    return EisNoticeDuplicateGroup(
        classification="BYTE_IDENTICAL" if len(xml_hashes) == 1 else "DIVERGENT",
        document_identity=identity,
        purchase_number=key[0],
        version_number=key[1],
        document_types=tuple(
            sorted({item.document_type for item in occurrences if item.document_type})
        ),
        occurrences=occurrences,
        changed_fields=tuple(changed),
        other_fields_differ=other,
        difference_category_count=len(changed) + int(other),
    )


def _without_timing(content: bytes) -> bytes:
    root = _parse_xml(content)
    notice = root[0]
    common = _one(notice, NOTICE_NS, "commonInfo")
    notification = _one(notice, NOTICE_NS, "notificationInfo")
    procedure = _one(notification, NOTICE_NS, "procedureInfo")
    collecting = _one(procedure, NOTICE_NS, "collectingInfo")
    for element in (
        _one(common, NOTICE_NS, "publishDTInEIS"),
        _one(collecting, NOTICE_NS, "startDT"),
    ):
        if element is not None:
            element.text = ""
    return bytes(ET.tostring(root, encoding="utf-8"))


def _validate_namespaces(element: ET.Element) -> None:
    for child in element.iter():
        namespace, _ = _split(child.tag)
        if namespace not in ALLOWED_NAMESPACES:
            raise EisNoticeConflictError("NAMESPACE_UNSUPPORTED")


def _one(parent: ET.Element | None, namespace: str, name: str) -> ET.Element | None:
    if parent is None:
        return None
    matches = [child for child in parent if child.tag == f"{{{namespace}}}{name}"]
    if len(matches) > 1:
        raise EisNoticeConflictError("DIRECT_CHILD_AMBIGUOUS")
    return matches[0] if matches else None


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _leaf_text(element: ET.Element | None) -> str | None:
    if element is None or len(element):
        return None
    return _text(element)


def _leaf_source_text(element: ET.Element | None) -> str | None:
    if element is None or len(element):
        return None
    return element.text


def _bounded_integer(raw: str | None, minimum: int, maximum: int) -> int | None:
    if raw is None or len(raw) > 64 or re.fullmatch(r"[+-]?[0-9]+", raw) is None:
        return None
    value = int(raw)
    return value if minimum <= value <= maximum else None


def _decoded_reflection(root: ET.Element, token: str) -> bool:
    return any(
        token in value
        for element in root.iter()
        for value in (element.tag, *element.attrib.keys(), *element.attrib.values())
    ) or any(token in (text or "") for text in root.itertext())


class _BoundedTreeBuilder(ET.TreeBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.nodes = 0
        self.depth = 0

    def start(self, tag: str, attrs: dict[str, str]) -> ET.Element:
        self.nodes += 1
        self.depth += 1
        if self.nodes > MAX_XML_NODES:
            raise EisNoticeConflictError("XML_NODE_LIMIT")
        if self.depth > MAX_XML_DEPTH:
            raise EisNoticeConflictError("XML_DEPTH_LIMIT")
        return super().start(tag, attrs)

    def end(self, tag: str) -> ET.Element:
        element = super().end(tag)
        self.depth -= 1
        return element


def _parse_xml(content: bytes) -> ET.Element:
    target = _BoundedTreeBuilder()
    parser = ET.XMLParser(target=target)
    try:
        parser.feed(content)
        return parser.close()
    except ET.ParseError as error:
        raise EisNoticeConflictError("XML_INVALID") from error


def _occurrence_key(occurrence: EisNoticeOccurrence) -> bytes:
    return _canonical(occurrence.model_dump(mode="json"))


def _aware(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise EisNoticeConflictError("TIMESTAMP_INVALID") from error
    return value if value.tzinfo is not None and value.utcoffset() is not None else None


def _split(tag: str) -> tuple[str, str]:
    if not tag.startswith("{") or "}" not in tag:
        return "", tag
    namespace, name = tag[1:].split("}", 1)
    return namespace, name


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
