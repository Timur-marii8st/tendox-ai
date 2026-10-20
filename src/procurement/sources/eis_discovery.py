"""Read-only triage of exact EIS notice exports and their public attachments.

An EIS notice is a lead, not a verified procurement case. Unknown status,
deadline, document completeness and supplier economics stay unknown.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field

from procurement.documents.bundle import DocumentBundleRejected, extract_document_bundle
from procurement.documents.extraction import DocumentInput, DocumentRejected, extract_document

MAX_EXPORT_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_EXPORT_MEMBERS = 100
MAX_TOTAL_XML_BYTES = 40 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
_NOTICE_ROOT = re.compile(r"^(?:epNotification|fcsNotification)[A-Za-z0-9_]*$")
_EXPORT_NAMESPACE = "http://zakupki.gov.ru/oos/export/1"
_PURCHASE_NUMBER = re.compile(r"^[0-9]{19,23}$")
_WORD = re.compile(r"[\w]+", re.UNICODE)
_INTENT_WORDS = frozenset(
    {"хочу", "хотим", "купить", "продать", "перепродавать", "ищи", "найди", "закупки", "тендеры"}
)
_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".zip"}


class EisExportError(ValueError):
    """A bounded, non-sensitive reason why an export cannot be trusted."""


class EisAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    url: str
    locator: str


class EisNoticeLead(BaseModel):
    model_config = ConfigDict(frozen=True)
    purchase_number: str
    notice_type: str | None = None
    version_number: int | None = None
    published_at: datetime | None = None
    title: str
    customer: str | None = None
    nmck: Decimal | None = None
    nmck_currency: str | None = None
    deadline: datetime | None = None
    application_status: str = "UNKNOWN"
    economic_status: str = "UNKNOWN"
    match_quality: str
    match_locator: str
    explanation: tuple[str, ...]
    relevance_points: int = Field(ge=0)
    notice_url: str
    attachments: tuple[EisAttachment, ...]
    export_member: str
    xml_sha256: str
    export_sha256: str


class EisDiscoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    query: str
    export_sha256: str
    inspected_notices: int
    rejected_members: int
    matched: tuple[EisNoticeLead, ...]
    coverage: str = "UPLOADED_EXPORT_ONLY"
    source_authenticity: str = "UNKNOWN"


class EisDocumentPreview(BaseModel):
    model_config = ConfigDict(frozen=True)
    url: str
    filename: str
    sha256: str
    byte_count: int
    extraction_status: str
    extraction_reasons: tuple[str, ...]
    text_preview: str
    preview_truncated: bool
    bundle_members: tuple[str, ...] = ()


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _field(root: ET.Element, names: tuple[str, ...]) -> str | None:
    """Only seek within the notice header, never an unrelated lot/attachment."""
    headers = [root]
    headers.extend(
        child for child in root if _name(child) in {"commonInfo", "notificationInfo", "generalInfo"}
    )
    for header in headers:
        elements = list(header) if header is root else list(header.iter())
        for element in elements:
            if _name(element) in names and element.text and element.text.strip():
                return element.text.strip()
    return None


def _aware_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None and value.utcoffset() is not None else None


def _amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def _structured_nmck_rub(root: ET.Element) -> Decimal | None:
    """Read amount and currency from the same official maxPriceInfo block."""
    values: list[Decimal] = []
    for block in root.iter():
        if _name(block) != "maxPriceInfo":
            continue
        amount_element = next((item for item in block if _name(item) == "maxPrice"), None)
        currency_element = next((item for item in block if _name(item) == "currency"), None)
        if amount_element is None or currency_element is None:
            continue
        code = next(
            ((item.text or "").strip() for item in currency_element if _name(item) == "code"),
            None,
        )
        if code not in {"RUB", "643", "RUR"}:
            continue
        amount = _amount(amount_element.text)
        if amount is not None:
            values.append(amount)
    if values and len(set(values)) == 1:
        return values[0]
    return None


def _search_key(word: str) -> str:
    """A narrow Russian inflection hint for discovery, not semantic equivalence."""
    lowered = word.casefold().replace("ё", "е")
    if len(lowered) >= 6 and re.fullmatch(r"[а-я]+", lowered):
        return lowered[:5]
    return lowered


def _direct_child(parent: ET.Element, name: str) -> ET.Element | None:
    matches = [child for child in parent if _name(child) == name]
    return matches[0] if len(matches) == 1 else None


def _best_lot_match(root: ET.Element, words: tuple[str, ...]) -> tuple[tuple[str, ...], str]:
    if _name(root) not in {
        "epNotificationEF2020",
        "epNotificationEZK2020",
        "epNotificationEOK2020",
    }:
        return (), ""
    notification = _direct_child(root, "notificationInfo")
    objects = (
        _direct_child(notification, "purchaseObjectsInfo") if notification is not None else None
    )
    goods = _direct_child(objects, "notDrugPurchaseObjectsInfo") if objects is not None else None
    if goods is None:
        return (), ""
    items = [child for child in goods if _name(child) == "purchaseObject"]
    if len(items) > 1000:
        return (), ""
    best: tuple[str, ...] = ()
    locator = ""
    for ordinal, item in enumerate(items, 1):
        name = _direct_child(item, "name")
        if name is None or not name.text:
            continue
        item_keys = {_search_key(token) for token in _WORD.findall(name.text)}
        hits = tuple(word for word in words if _search_key(word) in item_keys)
        if len(hits) > len(best):
            best = hits
            locator = (
                f"{_name(root)}/notificationInfo/purchaseObjectsInfo/"
                f"notDrugPurchaseObjectsInfo/purchaseObject[{ordinal}]/name"
            )
    return best, locator


def _official_attachment_url(raw: str) -> bool:
    try:
        parsed = urlparse(raw)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"zakupki.gov.ru", "www.zakupki.gov.ru"}
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and (
                parsed.path.startswith("/epz/")
                or parsed.path.startswith("/44fz/filestore/public/1.0/download/")
            )
            and not parsed.fragment
        )
    except ValueError:
        return False


def _attachments(root: ET.Element) -> tuple[EisAttachment, ...]:
    result: list[EisAttachment] = []
    seen: set[str] = set()
    ordinals: dict[str, int] = {}
    for element in root.iter():
        tag = _name(element)
        if tag not in {"attachment", "attachmentInfo", "document", "file"}:
            continue
        ordinals[tag] = ordinals.get(tag, 0) + 1
        fields = {_name(child): (child.text or "").strip() for child in element.iter()}
        url = next(
            (fields.get(name) for name in ("url", "urlAttachment", "fileUrl") if fields.get(name)),
            None,
        )
        filename = next(
            (fields.get(name) for name in ("fileName", "filename", "name") if fields.get(name)),
            None,
        )
        if not url or not filename or not _official_attachment_url(url) or url in seen:
            continue
        if tag == "attachmentInfo":
            uid = fields.get("publishedContentId")
            if not uid or parse_qs(urlparse(url).query) != {"uid": [uid]}:
                continue
        if len(filename) > 255 or re.search(r"[/\\\x00]", filename):
            continue
        seen.add(url)
        result.append(
            EisAttachment(filename=filename, url=url, locator=f"{tag}[{ordinals[tag]}]/url")
        )
    return tuple(result[:100])


def _notice(
    xml: bytes, member: str, export_sha256: str, words: tuple[str, ...], now: datetime
) -> EisNoticeLead | None:
    if len(xml) > MAX_XML_BYTES or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.I):
        raise EisExportError("UNSAFE_XML")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise EisExportError("INVALID_XML") from error
    if root.tag == f"{{{_EXPORT_NAMESPACE}}}export":
        if len(root) != 1 or not _NOTICE_ROOT.fullmatch(_name(root[0])):
            raise EisExportError("UNSUPPORTED_EXPORT_ENVELOPE")
        root = root[0]
    if not _NOTICE_ROOT.fullmatch(_name(root)):
        raise EisExportError("UNSUPPORTED_NOTICE_TYPE")
    number = _field(root, ("purchaseNumber",))
    title = (
        _field(root, ("purchaseObjectInfo",))
        or _field(root, ("purchaseName",))
        or _field(root, ("name",))
    )
    if not number or not _PURCHASE_NUMBER.fullmatch(number) or not title:
        raise EisExportError("MISSING_NOTICE_ID_OR_TITLE")
    title_words = {_search_key(word) for word in _WORD.findall(title)}
    matched = tuple(word for word in words if _search_key(word) in title_words)
    match_locator = f"{_name(root)}/commonInfo/purchaseObjectInfo"
    lot_matched, lot_locator = _best_lot_match(root, words)
    if len(lot_matched) > len(matched):
        matched, match_locator = lot_matched, lot_locator
    if not matched:
        return None
    deadline = _aware_datetime(_field(root, ("endDT", "endDate", "submissionCloseDateTime")))
    status = _field(root, ("state", "status", "isCanceled"))
    application_status = "UNKNOWN"
    if (status and status.casefold() in {"cancelled", "canceled", "true", "аннулировано"}) or (
        deadline is not None and deadline <= now
    ):
        application_status = "FAIL"
    # A future deadline does not establish that an application window is open.
    raw_nmck = _field(root, ("maxPrice", "maxPriceValue", "initialSum"))
    currency = _field(root, ("currency", "currencyCode"))
    nmck = _amount(raw_nmck)
    structured_nmck = _structured_nmck_rub(root)
    ruble_nmck = nmck is not None and currency in {"RUB", "643", "руб", "RUR"}
    if structured_nmck is not None:
        nmck = structured_nmck
        ruble_nmck = True
    match_quality = "STRONG" if len(matched) == len(words) else "PARTIAL"
    reasons = [f"Совпадение слов: {', '.join(matched)} (XML: {match_locator})."]
    if match_quality == "PARTIAL":
        reasons.append("Совпала только часть запроса; товар в лоте требует проверки.")
    if deadline is None:
        reasons.append("Срок подачи не подтверждён с часовым поясом.")
    elif application_status == "FAIL":
        reasons.append("Срок подачи истёк или извещение отменено.")
    else:
        reasons.append("Указанный срок ещё не истёк; текущий этап требует проверки.")
    if not ruble_nmck:
        reasons.append("Сопоставимая НМЦК в рублях не подтверждена.")
    reasons.append("Прибыль неизвестна: нет полного ТЗ, КП и всех расходов по сделке.")
    raw_version = _field(root, ("versionNumber",))
    version_number = int(raw_version) if raw_version and raw_version.isdecimal() else None
    return EisNoticeLead(
        purchase_number=number,
        notice_type=_name(root),
        version_number=version_number,
        published_at=_aware_datetime(_field(root, ("publishDTInEIS",))),
        title=title[:4000],
        customer=_field(root, ("fullName", "customerName")),
        nmck=nmck if ruble_nmck else None,
        nmck_currency="RUB" if ruble_nmck else None,
        deadline=deadline,
        application_status=application_status,
        match_quality=match_quality,
        match_locator=match_locator,
        explanation=tuple(reasons),
        relevance_points=len(matched),
        notice_url=(
            f"https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString={number}"
        ),
        attachments=_attachments(root),
        export_member=member,
        xml_sha256=hashlib.sha256(xml).hexdigest(),
        export_sha256=export_sha256,
    )


def discover_from_export(
    content: bytes, query: str, *, now: datetime | None = None
) -> EisDiscoveryResult:
    """Inspect one EIS XML or bounded ZIP and rank matching notice leads.

    >>> discover_from_export(b"bad", "бумага")  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    procurement.sources.eis_discovery.EisExportError: INVALID_XML
    """
    if not content or len(content) > MAX_EXPORT_BYTES:
        raise EisExportError("EXPORT_SIZE_INVALID")
    words = tuple(
        dict.fromkeys(
            word.casefold()
            for word in _WORD.findall(query)
            if len(word) >= 3 and word.casefold() not in _INTENT_WORDS
        )
    )
    if not 1 <= len(words) <= 8 or len(query) > 120:
        raise EisExportError("QUERY_INVALID")
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    digest = hashlib.sha256(content).hexdigest()
    members: list[tuple[str, bytes]] = []
    if content.startswith(b"PK\x03\x04"):
        try:
            with ZipFile(BytesIO(content)) as archive:
                infos = archive.infolist()
                if not infos or len(infos) > MAX_EXPORT_MEMBERS:
                    raise EisExportError("ZIP_MEMBER_LIMIT")
                if sum(info.file_size for info in infos) > MAX_TOTAL_XML_BYTES:
                    raise EisExportError("ZIP_EXPANSION_LIMIT")
                for info in infos:
                    if info.is_dir():
                        continue
                    if info.flag_bits & 1 or info.file_size > MAX_XML_BYTES:
                        raise EisExportError("UNSAFE_ZIP_MEMBER")
                    if not info.filename.lower().endswith(".xml"):
                        continue
                    members.append((info.filename, archive.read(info)))
        except (BadZipFile, RuntimeError) as error:
            raise EisExportError("INVALID_ZIP") from error
    else:
        members.append(("uploaded.xml", content))
    if not members:
        raise EisExportError("NO_XML_NOTICES")
    leads: list[EisNoticeLead] = []
    rejected = 0
    for member, xml in members:
        try:
            lead = _notice(xml, member, digest, words, current)
        except EisExportError:
            rejected += 1
            continue
        if lead is not None:
            leads.append(lead)
    if len(members) == rejected:
        raise EisExportError("NO_VALID_NOTICES")
    ranked = sorted(
        leads,
        key=lambda lead: (
            lead.application_status == "FAIL",
            lead.match_quality != "STRONG",
            -lead.relevance_points,
            lead.deadline or datetime.max.replace(tzinfo=UTC),
            lead.purchase_number,
        ),
    )
    return EisDiscoveryResult(
        query=query,
        export_sha256=digest,
        inspected_notices=len(members) - rejected,
        rejected_members=rejected,
        matched=tuple(ranked[:100]),
    )


def inspect_official_attachment(
    url: str, filename: str, *, fetcher: Callable[[str], bytes] | None = None
) -> EisDocumentPreview:
    """Fetch a bounded public EIS document and run the existing native extractor."""
    if not _official_attachment_url(url):
        raise EisExportError("ATTACHMENT_URL_INVALID")
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in _DOCUMENT_EXTENSIONS or re.search(r"[/\\\x00]", filename):
        raise EisExportError("ATTACHMENT_FILENAME_INVALID")
    if fetcher is None:
        from procurement.sources.eis_public import EisPublicError, download_public_attachment

        try:
            content = download_public_attachment(url)
        except EisPublicError as error:
            raise EisExportError(str(error)) from error
    else:
        content = fetcher(url)
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise EisExportError("ATTACHMENT_TOO_LARGE")
    if not content:
        raise EisExportError("ATTACHMENT_EMPTY")
    media = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".zip": "application/zip",
    }[suffix]
    try:
        document = DocumentInput(
            document_id=hashlib.sha256(content).hexdigest(),
            filename=filename,
            declared_media_type=media,
            content=content,
        )
        if suffix == ".zip":
            bundle = extract_document_bundle(document)
            status = bundle.status.value
            reasons = tuple(reason.value for reason in bundle.reasons)
            preview = "\n".join(
                block.text for member in bundle.members for block in member.extraction.blocks
            )
            bundle_members = tuple(member.archive_path for member in bundle.members)
        else:
            result = extract_document(document)
            status = result.status.value
            reasons = tuple(reason.value for reason in result.reasons)
            preview = "\n".join(block.text for block in result.blocks)
            bundle_members = ()
    except (DocumentRejected, DocumentBundleRejected) as error:
        raise EisExportError(f"ATTACHMENT_{error.code.value}") from error
    return EisDocumentPreview(
        url=url,
        filename=filename,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        extraction_status=status,
        extraction_reasons=reasons,
        text_preview=preview[:4000],
        preview_truncated=len(preview) > 4000,
        bundle_members=bundle_members,
    )
