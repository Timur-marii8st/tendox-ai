"""Exact 223 attachment manifest and one public browser download; no inferred size."""

from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_public import EisPublicError, _browser_download, _host_lease


class Notice223DocumentRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    version_number: int = Field(ge=1)
    notice_xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest223Item(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ordinal: int
    content_uid: str | None
    filename: str | None
    source_url: str | None
    source_locator: str
    status: Literal["READY", "UNKNOWN"]
    reasons: tuple[str, ...]
    declared_byte_count: None = None


class Manifest223(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    notice: Notice223DocumentRef
    status: Literal["READY", "UNKNOWN"]
    reasons: tuple[str, ...]
    documents: tuple[Manifest223Item, ...]
    source_manifest_coverage: Literal["UNKNOWN"] = "UNKNOWN"


def public223_attachment_url(url: str, uid: str) -> bool:
    try:
        parts = urlsplit(url)
        return bool(re.fullmatch(r"[0-9A-F]{32}", uid)) and (
            parts.scheme == "https"
            and parts.netloc == "zakupki.gov.ru"
            and parts.path == "/223/filestore/public/1.0/download/fz223/file.html"
            and not parts.fragment
            and parse_qs(parts.query, keep_blank_values=True) == {"uid": [uid]}
        )
    except ValueError:
        return False


def manifest223(notice: Eis223NoticeSnapshot) -> Manifest223:
    ref = Notice223DocumentRef(
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
    )
    duplicates = Counter(a.content_uid.value for a in notice.attachments)
    documents = []
    for ordinal, attachment in enumerate(notice.attachments, 1):
        uid, filename, url = (
            attachment.content_uid.value,
            attachment.filename.value,
            attachment.url.value,
        )
        reasons = []
        if not uid or not re.fullmatch(r"[0-9A-F]{32}", uid):
            reasons.append("CONTENT_UID_UNKNOWN")
        elif duplicates[uid] != 1:
            reasons.append("DUPLICATE_CONTENT_UID")
        if (
            not filename
            or len(filename) > 255
            or any(c in filename for c in "/\\\x00")
            or filename in {".", ".."}
        ):
            reasons.append("FILENAME_UNKNOWN_OR_UNSAFE")
        if not uid or not url or not public223_attachment_url(url, uid):
            reasons.append("PUBLIC_URL_UNKNOWN_OR_UNSAFE")
        documents.append(
            Manifest223Item(
                ordinal=ordinal,
                content_uid=uid,
                filename=filename,
                source_url=url,
                source_locator=attachment.url.provenance.locator,
                status="UNKNOWN" if reasons else "READY",
                reasons=tuple(reasons),
            )
        )
    reasons = []
    if notice.manifest_status != "COUNT_CONSISTENT" or not documents:
        reasons.append("MANIFEST_COUNT_UNKNOWN")
    if notice.document_type == "purchaseNotice":
        if notice.manifest_references:
            reasons.append("MANIFEST_REFERENCE_BRANCHES_UNRESOLVED")
        additional = notice.manifest_additional_count
        if additional is None or additional.value not in {None, "0"}:
            reasons.append("ADDITIONAL_DOCUMENTS_UNRESOLVED")
        if any(
            a.not_placement_raw and a.not_placement_raw.value not in {None, "false", "0"}
            for a in notice.attachments
        ):
            reasons.append("NON_PUBLIC_DOCUMENT_REFERENCES")
    if len(documents) > 32:
        reasons.append("DOCUMENT_SET_RESOURCE_LIMIT")
    if any(d.status != "READY" for d in documents):
        reasons.append("DOCUMENT_REFERENCES_UNKNOWN")
    return Manifest223(
        notice=ref,
        status="UNKNOWN" if reasons else "READY",
        reasons=tuple(reasons),
        documents=tuple(documents),
    )


def download_public223_attachment(url: str, uid: str) -> bytes:
    if not public223_attachment_url(url, uid):
        raise EisPublicError("ATTACHMENT_URL_INVALID")
    with _host_lease() as retry_at:
        if retry_at:
            raise EisPublicError("ROBOTS_CRAWL_DELAY")
        loop_factory = (
            asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
        )
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            return runner.run(_browser_download(url))
