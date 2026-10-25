"""Verify an exact EIS notice attachment list against downloaded source bytes.

Native extraction status is separate from document-set completeness and from
supplier compliance. Neither a missing file nor an ignored embedded part is PASS.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from procurement.sources.eis_analysis import DocumentAnalysis, analyze_document
from procurement.sources.eis_feed_archive import EisNoticeSnapshot

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class EisDocumentSetError(ValueError):
    """Downloaded bytes do not belong to this exact notice XML manifest."""


@dataclass(frozen=True)
class EisDocumentEvidence:
    content_uid: str
    filename: str
    kind_code: str | None
    source_url: str
    source_locator: str
    declared_byte_count: int
    received_byte_count: int | None
    sha256: str | None
    fetch_status: str
    extraction_status: str
    extraction_reasons: tuple[str, ...]
    analysis: DocumentAnalysis | None


@dataclass(frozen=True)
class EisDocumentSetReport:
    purchase_number: str
    version_number: int
    notice_xml_sha256: str
    listed_count: int
    received_count: int
    download_status: str
    extraction_status: str
    review_status: str
    source_manifest_coverage: str
    documents: tuple[EisDocumentEvidence, ...]


def assess_notice_document_set(
    notice: EisNoticeSnapshot,
    downloaded_by_uid: Mapping[str, bytes],
) -> EisDocumentSetReport:
    """Assess all listed attachments without inferring unlisted files exist or not."""
    listed_uids = {item.content_uid for item in notice.attachments}
    if set(downloaded_by_uid) - listed_uids:
        raise EisDocumentSetError("UNLISTED_DOCUMENT_UID")
    documents: list[EisDocumentEvidence] = []
    for item in notice.attachments:
        content = downloaded_by_uid.get(item.content_uid)
        base = dict(
            content_uid=item.content_uid,
            filename=item.filename,
            kind_code=item.kind_code,
            source_url=item.url,
            source_locator=item.locator,
            declared_byte_count=item.byte_count,
        )
        if item.reference_status == "UNKNOWN":
            documents.append(
                EisDocumentEvidence(
                    **base,
                    received_byte_count=None,
                    sha256=None,
                    fetch_status="BLOCKED",
                    extraction_status="UNKNOWN",
                    extraction_reasons=("ATTACHMENT_REFERENCE_REQUIRES_REVIEW",),
                    analysis=None,
                )
            )
            continue
        if content is None:
            documents.append(
                EisDocumentEvidence(
                    **base,
                    received_byte_count=None,
                    sha256=None,
                    fetch_status="MISSING",
                    extraction_status="UNKNOWN",
                    extraction_reasons=("FILE_NOT_DOWNLOADED",),
                    analysis=None,
                )
            )
            continue
        digest = hashlib.sha256(content).hexdigest()
        if not content or len(content) > MAX_DOCUMENT_BYTES or len(content) != item.byte_count:
            documents.append(
                EisDocumentEvidence(
                    **base,
                    received_byte_count=len(content),
                    sha256=digest,
                    fetch_status="SIZE_MISMATCH",
                    extraction_status="UNKNOWN",
                    extraction_reasons=("DECLARED_SIZE_MISMATCH_OR_LIMIT",),
                    analysis=None,
                )
            )
            continue
        analysis = analyze_document(content, item.filename, item.url)
        documents.append(
            EisDocumentEvidence(
                **base,
                received_byte_count=len(content),
                sha256=digest,
                fetch_status="RECEIVED",
                extraction_status=analysis.status,
                extraction_reasons=analysis.reasons,
                analysis=analysis,
            )
        )
    fetched = sum(item.fetch_status == "RECEIVED" for item in documents)
    all_extracted = (
        bool(documents)
        and fetched == len(documents)
        and all(item.extraction_status == "PASS" for item in documents)
    )
    return EisDocumentSetReport(
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
        listed_count=len(documents),
        received_count=fetched,
        download_status=(
            "COMPLETE_LISTED_SET"
            if documents and fetched == len(documents)
            else "INCOMPLETE"
            if documents
            else "UNKNOWN_MANIFEST"
        ),
        extraction_status="EXTRACTED" if all_extracted else "UNKNOWN",
        review_status="UNKNOWN",
        source_manifest_coverage="UNKNOWN",
        documents=tuple(documents),
    )
