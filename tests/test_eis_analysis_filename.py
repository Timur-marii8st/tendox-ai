"""Source labels remain evidence; unsafe processing names never reach extractors."""

from unittest.mock import Mock

import pytest

from procurement.sources import eis_analysis as analysis
from procurement.sources.eis_document_sync import assess_notice_document_set
from procurement.sources.eis_feed_archive import EisNoticeSnapshot, EisOfficialAttachment


@pytest.mark.parametrize(
    "name", ["Часть 1/2.pdf", "../document.pdf", "C:document.pdf", "a\\b.pdf", "a\x00.pdf"]
)
def test_source_label_requires_review_before_extractor(monkeypatch, name):
    constructor = Mock(side_effect=AssertionError("extractor input must not be constructed"))
    monkeypatch.setattr(analysis, "DocumentInput", constructor)
    result = analysis.analyze_document(b"source", name, "https://example.invalid/doc")
    assert result.status == "UNKNOWN"
    assert result.reasons == ("ATTACHMENT_FILENAME_REQUIRES_REVIEW",)
    assert result.filename == name and result.byte_count == 6
    constructor.assert_not_called()


def test_complete_listed_bytes_do_not_make_slash_label_extracted():
    item = EisOfficialAttachment(
        "A" * 32, "Часть 1/2.pdf", 6, "https://example.invalid/doc", None, "attachmentInfo[1]"
    )
    notice = EisNoticeSnapshot(
        "0373100047426001450",
        "epNotificationEF2020",
        1,
        "paper",
        None,
        None,
        None,
        "a" * 64,
        "notice.xml",
        (item,),
    )
    result = assess_notice_document_set(notice, {item.content_uid: b"source"})
    assert result.download_status == "COMPLETE_LISTED_SET"
    assert result.extraction_status == result.review_status == "UNKNOWN"
    assert result.documents[0].filename == item.filename
    assert result.documents[0].extraction_reasons == ("ATTACHMENT_FILENAME_REQUIRES_REVIEW",)
