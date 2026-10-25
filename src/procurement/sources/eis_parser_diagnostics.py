"""Pure bounded diagnostics of retained EIS parser rejections; no source or storage I/O."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from io import BytesIO
from typing import Literal
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field

from procurement.sources import eis_feed_archive as parser
from procurement.sources.eis_notice_conflicts import MAX_XML_DEPTH, MAX_XML_NODES
from procurement.storage.eis_notice_index import (
    _BY_NUMBER,
    _SHA,
    _WINDOW,
    MAX_WINDOW_ARCHIVES,
    MAX_WINDOW_COMPRESSED_BYTES,
    MAX_WINDOW_EXPANDED_BYTES,
    EisReadyWindow,
)


class EisParserDiagnosticError(ValueError):
    """Only fixed, non-sensitive diagnostic failure codes escape this boundary."""


class DiagnosticModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisParserFinding(DiagnosticModel):
    archive_ordinal: int = Field(ge=0, lt=MAX_WINDOW_ARCHIVES)
    archive_sha256: str
    member_ordinal: int | None = Field(default=None, ge=1)
    member_name_sha256: str | None = None
    member_name_length: int | None = Field(default=None, ge=0)
    declared_xml_bytes: int | None = Field(default=None, ge=0)
    xml_sha256: str | None = None
    attachment_ordinal: int | None = Field(default=None, ge=1)
    locator: str | None = None
    reason: str
    inspection_status: Literal["INSPECTED", "UNKNOWN"] = "INSPECTED"
    failure_flags: tuple[str, ...]
    filename_length: int | None = None
    uid_length: int | None = None
    url_length: int | None = None
    file_size_length: int | None = None


class EisParserArchiveDiagnostic(DiagnosticModel):
    archive_ordinal: int
    archive_sha256: str
    member_count: int | None
    declared_expanded_bytes: int | None
    inspected_xml_count: int
    skipped_member_count: int | None
    parser_status: Literal["REJECTED", "NO_ERROR_OBSERVED", "NOT_RUN", "ERROR"]
    parser_reason: str | None


class EisParserDiagnosticReport(DiagnosticModel):
    company_id: str
    window_key: str
    response_sha256: str
    observed_at: datetime
    archives: tuple[EisParserArchiveDiagnostic, ...]
    archive_count: int
    known_member_count: int
    inspected_xml_count: int
    inspected_attachment_count: int
    known_attachment_count: int
    attachment_census_complete: bool
    census_complete: bool
    inspection_complete: bool
    finding_count: int
    findings: tuple[EisParserFinding, ...]
    truncated: bool
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    canonical_admission: Literal["NOT_ENABLED"] = "NOT_ENABLED"
    source_requests: Literal[0] = 0


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _XmlShapeLimit(ValueError):
    pass


class _CountingXmlTarget:
    """Streaming target: count structural events without retaining an element tree."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.nodes = self.depth = 0
        self.tail = ""

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        self.nodes += 1
        self.depth += 1
        if self.nodes > MAX_XML_NODES:
            raise _XmlShapeLimit("DIAGNOSTIC_XML_NODE_LIMIT")
        if self.depth > MAX_XML_DEPTH:
            raise _XmlShapeLimit("DIAGNOSTIC_XML_DEPTH_LIMIT")
        if any(self.token in value for value in (tag, *attrs.keys(), *attrs.values())):
            raise EisParserDiagnosticError("TOKEN_REFLECTION")

    def end(self, tag: str) -> None:
        self.depth -= 1

    def data(self, text: str) -> None:
        value = self.tail + text
        if self.token in value:
            raise EisParserDiagnosticError("TOKEN_REFLECTION")
        self.tail = value[-(len(self.token) - 1) :]

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise _XmlShapeLimit("DIAGNOSTIC_XML_DTD_UNSAFE")

    def close(self) -> None:
        return None


def _stream_xml_guard(xml: bytes, token: str) -> str | None:
    # Match the existing parser's early unsafe-XML predicate before streaming too.
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.I):
        return "XML_UNSAFE"
    stream_parser = ET.XMLParser(target=_CountingXmlTarget(token))
    try:
        for offset in range(0, len(xml), 64 * 1024):
            stream_parser.feed(xml[offset : offset + 64 * 1024])
        stream_parser.close()
    except _XmlShapeLimit as error:
        return str(error)
    except ET.ParseError:
        return "XML_INVALID"
    return None


def _member_flags(info: ZipInfo) -> tuple[str, ...]:
    # These are the six exact MEMBER_UNSUPPORTED predicates in the canonical parser.
    return tuple(
        flag
        for flag, failed in (
            ("MEMBER_DIRECTORY", info.is_dir()),
            ("MEMBER_ENCRYPTED", bool(info.flag_bits & 1)),
            ("MEMBER_XML_SIZE_LIMIT", info.file_size > parser._MAX_XML_BYTES),
            ("MEMBER_EXTENSION_UNSUPPORTED", not info.filename.lower().endswith(".xml")),
            ("MEMBER_FORWARD_SLASH", "/" in info.filename),
            ("MEMBER_BACKSLASH", "\\" in info.filename),
        )
        if failed
    )


def _attachment_findings(xml: bytes) -> tuple[int, int, list[dict[str, object]]]:
    # Call only after _notice has applied the existing unsafe-XML and envelope guards.
    root = ET.fromstring(xml)
    notice = root[0]
    kind = parser._name(notice)
    if kind not in parser.SUPPORTED_NOTICE_TYPES or kind in parser.EVENT_TYPES:
        return 0, 0, []
    try:
        block = parser._optional_child(notice, "attachmentsInfo")
    except parser.EisFeedArchiveError:
        return (
            0,
            0,
            [{"reason": "FIELD_DUPLICATE", "failure_flags": ("ATTACHMENT_BLOCK_DUPLICATE",)}],
        )
    if block is None:
        return 0, 0, []
    entries = [element for element in block if parser._name(element) == "attachmentInfo"]
    if len(entries) > parser._MAX_ATTACHMENT_METADATA_ENTRIES:
        return (
            len(entries),
            0,
            [
                {
                    "reason": "ATTACHMENT_METADATA_COUNT_LIMIT",
                    "failure_flags": ("ATTACHMENT_METADATA_COUNT_LIMIT",),
                }
            ],
        )
    seen: dict[str, dict[str, str]] = {}
    findings: list[dict[str, object]] = []
    for ordinal, element in enumerate(entries, 1):
        flags: list[str] = []
        fields: dict[str, str] = {}
        for name, category in (
            ("publishedContentId", "UID"),
            ("fileName", "FILENAME"),
            ("url", "URL"),
            ("fileSize", "FILE_SIZE"),
        ):
            try:
                fields[name] = parser._value(element, name)
            except parser.EisFeedArchiveError as error:
                flags.append(f"{category}_{error!s}")
        uid, filename, url, size = (
            fields.get(key) for key in ("publishedContentId", "fileName", "url", "fileSize")
        )
        if uid is not None and not parser._FILE_UID.fullmatch(uid):
            flags.append("UID_INVALID")
        if filename is not None and parser._attachment_filename_invalid(filename):
            if len(filename) > parser._MAX_ATTACHMENT_FILENAME_CHARS:
                flags.append("FILENAME_LENGTH_LIMIT")
            if re.search(r"[\\\x00]", filename):
                flags.append("FILENAME_BACKSLASH_OR_NUL")
        if size is not None and not size.isdecimal():
            flags.append("FILE_SIZE_INVALID")
        # Nonnegative decimal strings cannot have int(value)<0. Avoid converting unbounded digits.
        if uid is not None and url is not None and not parser._official_url(url, uid):
            flags.append("URL_BINDING_INVALID")
        reason = "ATTACHMENT_REFERENCE_INVALID"
        if uid is not None:
            if uid in seen:
                previous = seen[uid]
                if not flags and (previous.get("url"), previous.get("fileSize")) == (url, size):
                    reason = "ATTACHMENT_REFERENCE_ALIAS"
                flags.append("DUPLICATE_UID")
            if not flags:
                seen[uid] = fields
        if flags:
            findings.append(
                dict(
                    attachment_ordinal=ordinal,
                    locator=f"{kind}/attachmentsInfo/attachmentInfo[{ordinal}]",
                    reason=reason,
                    failure_flags=tuple(flags),
                    filename_length=len(filename) if filename is not None else None,
                    uid_length=len(uid) if uid is not None else None,
                    url_length=len(url) if url is not None else None,
                    file_size_length=len(size) if size is not None else None,
                )
            )
    return len(entries), len(entries), findings


def diagnose_eis_parser_window(
    window: EisReadyWindow,
    *,
    company_id: str,
    observed_at: datetime,
    token: str,
    max_findings: int = 100,
) -> EisParserDiagnosticReport:
    """Inspect every safely readable member; keep first canonical archive failure separately."""
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", company_id)
        or observed_at.utcoffset() is None
        or not 1 <= max_findings <= 100
        or not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token)
    ):
        raise EisParserDiagnosticError("DIAGNOSTIC_INPUT_INVALID")
    if not _WINDOW.fullmatch(window.window_key) or not _SHA.fullmatch(window.response_sha256):
        raise EisParserDiagnosticError("SOURCE_COORDINATES_INVALID")
    if not 1 <= window.expected_archive_count <= MAX_WINDOW_ARCHIVES:
        raise EisParserDiagnosticError("ARCHIVE_COUNT_INVALID")
    if len(window.archives) != window.expected_archive_count:
        raise EisParserDiagnosticError("ARCHIVE_SET_INCOMPLETE")
    if sum(len(value) for value in window.archives) > MAX_WINDOW_COMPRESSED_BYTES:
        raise EisParserDiagnosticError("ARCHIVE_WINDOW_SIZE_LIMIT")
    secrets = (token.encode(), token.encode("utf-16-le"), token.encode("utf-16-be"))

    def reflect(value: bytes) -> None:
        if any(secret in value for secret in secrets):
            raise EisParserDiagnosticError("TOKEN_REFLECTION")

    for value in (
        company_id,
        window.window_key,
        window.response_sha256,
        window.prepared_response_sha256 or "",
        *window.archive_urls,
    ):
        reflect(value.encode())
    # Inspect the complete transport's metadata before decompressing even one XML.
    # Invalid archives are diagnosed below; their unknown census is never called complete.
    total_expanded = 0
    for content in window.archives:
        reflect(content)
        if (
            not content
            or len(content) > parser._MAX_ZIP_BYTES
            or not content.startswith(b"PK\x03\x04")
        ):
            continue
        try:
            with ZipFile(BytesIO(content)) as archive:
                infos = archive.infolist()
                total_expanded += sum(info.file_size for info in infos)
                if total_expanded > MAX_WINDOW_EXPANDED_BYTES:
                    raise EisParserDiagnosticError("ARCHIVE_WINDOW_EXPANSION_LIMIT")
        except BadZipFile:
            continue
    expected = (
        None
        if _BY_NUMBER.fullmatch(window.window_key)
        else window.window_key.rsplit("/", 1)[-1]
        if window.window_key.rsplit("/", 1)[-1] in parser.SUPPORTED_NOTICE_TYPES
        else parser.DEFAULT_NOTICE_TYPE
    )
    samples: list[EisParserFinding] = []
    finding_count = 0
    attachments_count = 0
    known_attachments = 0
    attachment_census_complete = True
    reports: list[EisParserArchiveDiagnostic] = []
    census_complete = inspection_complete = True
    for archive_ordinal, content in enumerate(window.archives):
        reflect(content)
        digest = _sha(content)

        def finding(
            _ordinal: int = archive_ordinal, _digest: str = digest, /, **values: object
        ) -> None:
            nonlocal finding_count
            finding_count += 1
            if len(samples) < max_findings:
                samples.append(
                    EisParserFinding(archive_ordinal=_ordinal, archive_sha256=_digest, **values)
                )

        count: int | None = None
        expanded: int | None = None
        inspected = 0
        first_reason: str | None = None
        status: Literal["REJECTED", "NO_ERROR_OBSERVED", "NOT_RUN", "ERROR"] = "NO_ERROR_OBSERVED"
        skipped: int | None = None
        notice_keys: list[tuple[str, int]] = []
        event_keys: list[tuple[str, str]] = []
        try:
            if (
                not content
                or len(content) > parser._MAX_ZIP_BYTES
                or not content.startswith(b"PK\x03\x04")
            ):
                raise parser.EisFeedArchiveError("ARCHIVE_SIZE_OR_TYPE_INVALID")
            with ZipFile(BytesIO(content)) as archive:
                infos = archive.infolist()
                count = len(infos)
                expanded = sum(info.file_size for info in infos)
                if not infos or len(infos) > parser._MAX_MEMBERS:
                    raise parser.EisFeedArchiveError("MEMBER_COUNT_INVALID")
                if expanded > parser._MAX_UNCOMPRESSED_BYTES:
                    raise parser.EisFeedArchiveError("ARCHIVE_EXPANSION_LIMIT")
                for member_ordinal, info in enumerate(infos, 1):
                    reflect(info.filename.encode("utf-8", errors="replace"))
                    base = dict(
                        member_ordinal=member_ordinal,
                        member_name_sha256=_sha(info.filename.encode("utf-8", errors="replace")),
                        member_name_length=len(info.filename),
                        declared_xml_bytes=info.file_size,
                    )
                    flags = _member_flags(info)
                    if flags:
                        first_reason = first_reason or "MEMBER_UNSUPPORTED"
                        finding(**base, reason="MEMBER_UNSUPPORTED", failure_flags=flags)
                        inspection_complete = False
                        continue
                    try:
                        with archive.open(info) as stream:
                            xml = stream.read(parser._MAX_XML_BYTES + 1)
                        if len(xml) != info.file_size or len(xml) > parser._MAX_XML_BYTES:
                            raise EisParserDiagnosticError("MEMBER_SIZE_MISMATCH")
                        reflect(xml)
                        base["xml_sha256"] = _sha(xml)
                        guard_reason = _stream_xml_guard(xml, token)
                        if guard_reason is not None:
                            if guard_reason in {"XML_UNSAFE", "XML_INVALID"}:
                                first_reason = first_reason or guard_reason
                            elif first_reason is None:
                                status = "NOT_RUN"
                            finding(
                                **base,
                                reason=guard_reason,
                                inspection_status="UNKNOWN",
                                failure_flags=(guard_reason,),
                            )
                            inspection_complete = attachment_census_complete = False
                            continue
                        inspected += 1
                        parse_reason = None
                        try:
                            document = parser._notice(xml, info.filename, expected)
                            if isinstance(document, parser.EisProcedureEvent):
                                event_keys.append((document.document_type, document.document_id))
                            else:
                                notice_keys.append(
                                    (document.purchase_number, document.version_number)
                                )
                        except parser.EisFeedArchiveError as error:
                            parse_reason = str(error)
                            first_reason = first_reason or parse_reason
                        except (ValueError, OverflowError, RecursionError):
                            parse_reason = "PARSER_EVALUATION_FAILED"
                            first_reason = first_reason or parse_reason
                            inspection_complete = False
                            status = "ERROR"
                        detailed: list[dict[str, object]] = []
                        if parse_reason not in {
                            "XML_UNSAFE",
                            "XML_INVALID",
                            "EXPORT_ENVELOPE_INVALID",
                            "DOCUMENT_TYPE_UNSUPPORTED",
                            "PARSER_EVALUATION_FAILED",
                        }:
                            known_count, seen_count, detailed = _attachment_findings(xml)
                            known_attachments += known_count
                            attachments_count += seen_count
                            if known_count != seen_count:
                                inspection_complete = False
                        else:
                            attachment_census_complete = False
                            inspection_complete = False
                        if detailed:
                            for detail in detailed:
                                finding(**base, **detail)
                        elif parse_reason:
                            finding(**base, reason=parse_reason, failure_flags=(parse_reason,))
                    except (BadZipFile, RuntimeError, NotImplementedError, EOFError):
                        first_reason = first_reason or "ARCHIVE_INVALID"
                        inspection_complete = False
                        finding(
                            **base, reason="ARCHIVE_INVALID", failure_flags=("MEMBER_READ_FAILED",)
                        )
                skipped = count - inspected
                if first_reason is None and len(set(notice_keys)) != len(notice_keys):
                    first_reason = "DUPLICATE_NOTICE_VERSION"
                    finding(reason=first_reason, failure_flags=(first_reason,))
                if first_reason is None and len(set(event_keys)) != len(event_keys):
                    first_reason = "DUPLICATE_PROCEDURE_EVENT"
                    finding(reason=first_reason, failure_flags=(first_reason,))
        except parser.EisFeedArchiveError as error:
            first_reason = str(error)
            finding(reason=first_reason, failure_flags=(first_reason,))
            inspection_complete = False
        except BadZipFile:
            first_reason = "ARCHIVE_INVALID"
            finding(reason=first_reason, failure_flags=(first_reason,))
            inspection_complete = False
        if count is None:
            census_complete = False
        if skipped is None and count is not None:
            skipped = count - inspected
        if status == "NOT_RUN":
            first_reason = None
        elif first_reason and status != "ERROR":
            status = "REJECTED"
        reports.append(
            EisParserArchiveDiagnostic(
                archive_ordinal=archive_ordinal,
                archive_sha256=digest,
                member_count=count,
                declared_expanded_bytes=expanded,
                inspected_xml_count=inspected,
                skipped_member_count=skipped,
                parser_status=status,
                parser_reason=first_reason,
            )
        )
    return EisParserDiagnosticReport(
        company_id=company_id,
        window_key=window.window_key,
        response_sha256=window.response_sha256,
        observed_at=observed_at,
        archives=tuple(reports),
        archive_count=len(reports),
        known_member_count=sum(r.member_count or 0 for r in reports),
        inspected_xml_count=sum(r.inspected_xml_count for r in reports),
        inspected_attachment_count=attachments_count,
        known_attachment_count=known_attachments,
        attachment_census_complete=attachment_census_complete and inspection_complete,
        census_complete=census_complete,
        inspection_complete=inspection_complete,
        finding_count=finding_count,
        findings=tuple(samples),
        truncated=finding_count > len(samples),
    )
