"""Downloaded files and analyzed requirements have separate evidence states."""

from __future__ import annotations

from dataclasses import replace

import pytest

from procurement.sources.eis_document_sync import (
    EisDocumentSetError,
    assess_notice_document_set,
)
from procurement.sources.eis_feed_archive import EisNoticeSnapshot, EisOfficialAttachment

UID = "A" * 32
URL = f"https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid={UID}"


def _notice() -> EisNoticeSnapshot:
    return EisNoticeSnapshot(
        purchase_number="0848300054826000154",
        document_type="epNotificationEF2020",
        version_number=1,
        title="Поставка бумаги",
        published_at=None,
        deadline=None,
        nmck_rub=None,
        xml_sha256="b" * 64,
        source_member="notice.xml",
        attachments=(
            EisOfficialAttachment(
                content_uid=UID,
                filename="instructions.txt",
                byte_count=3,
                url=URL,
                kind_code="CAR",
                locator="epNotificationEF2020/attachmentsInfo/attachmentInfo[1]",
            ),
        ),
    )


def test_complete_download_is_not_complete_analysis() -> None:
    result = assess_notice_document_set(_notice(), {UID: b"abc"})
    assert result.listed_count == result.received_count == 1
    assert result.download_status == "COMPLETE_LISTED_SET"
    assert result.extraction_status == "UNKNOWN"
    assert result.review_status == "UNKNOWN"
    assert result.source_manifest_coverage == "UNKNOWN"
    assert result.documents[0].fetch_status == "RECEIVED"


def test_missing_and_mismatched_bytes_are_not_received() -> None:
    missing = assess_notice_document_set(_notice(), {})
    mismatch = assess_notice_document_set(_notice(), {UID: b"longer"})
    assert missing.download_status == mismatch.download_status == "INCOMPLETE"
    assert missing.documents[0].fetch_status == "MISSING"
    assert mismatch.documents[0].fetch_status == "SIZE_MISMATCH"
    assert mismatch.documents[0].analysis is None


def test_empty_manifest_does_not_prove_absence_of_documents() -> None:
    result = assess_notice_document_set(replace(_notice(), attachments=()), {})
    assert result.download_status == "UNKNOWN_MANIFEST"
    assert result.extraction_status == result.review_status == "UNKNOWN"


def test_unlisted_uid_is_rejected() -> None:
    with pytest.raises(EisDocumentSetError, match="UNLISTED_DOCUMENT_UID"):
        assess_notice_document_set(_notice(), {"B" * 32: b"abc"})


def test_ambiguous_reference_never_runs_native_analysis(monkeypatch):
    from procurement.sources import eis_document_sync
    from procurement.sources.eis_feed_archive import EisAttachmentAlias

    notice = _notice()
    attachment = replace(
        notice.attachments[0], aliases=(EisAttachmentAlias("other.pdf", None, "xml/attachment[2]"),)
    )
    notice = replace(notice, attachments=(attachment,))
    monkeypatch.setattr(
        eis_document_sync,
        "analyze_document",
        lambda *args: pytest.fail("ambiguous reference must not be analyzed"),
    )
    report = assess_notice_document_set(notice, {UID: b"abc"})
    assert report.extraction_status == "UNKNOWN"
    assert report.documents[0].analysis is None
    assert report.documents[0].extraction_reasons == ("ATTACHMENT_REFERENCE_REQUIRES_REVIEW",)
