"""A source window must be complete before it can change the index."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources.eis_feed import EisArchiveReference, EisFeedResponse
from procurement.storage import eis_notice_index
from procurement.storage.eis_notice_index import (
    EisIndexConflict,
    EisReadyWindow,
    bind_ready_window,
    preflight_ready_window,
)

WINDOW = "getDocsIP/PRIZ/50/2026-09-25/17+03:00"
RESPONSE = "a" * 64
URL = "https://int.zakupki.gov.ru/dstore/common/download/compound?docRequestUid=00000000-0000-0000-0000-000000000001&compoundUid=00000000000000000000000000000001"


def _zip(number: str, version: int = 1, *, member: str = "notice.xml") -> bytes:
    source = f"""<export xmlns="http://zakupki.gov.ru/oos/export/1">
<epNotificationEF2020><versionNumber>{version}</versionNumber>
<commonInfo><purchaseNumber>{number}</purchaseNumber>
<purchaseObjectInfo>Бумага для офиса</purchaseObjectInfo></commonInfo>
<notificationInfo><procedureInfo><collectingInfo>
<endDT>2026-10-05T10:00:00+03:00</endDT>
</collectingInfo></procedureInfo></notificationInfo>
</epNotificationEF2020></export>""".encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(member, source)
    return output.getvalue()


def _responses() -> tuple[EisFeedResponse, EisFeedResponse]:
    initial = EisFeedResponse(
        service="IP",
        kind="BY_REGION",
        state="LINKS_PENDING",
        source_mode="PROD",
        response_id="response",
        request_id="request",
        created_at=None,
        source_time_raw="2026-09-25T17:00:00",
        source_time_status="UNKNOWN_TZ",
        source_sha256=RESPONSE,
        archive_urls=(URL,),
    )
    prepared = EisFeedResponse(
        service="IP",
        kind="PREPARED",
        state="READY",
        source_mode="PROD",
        response_id="prepared",
        request_id="poll",
        created_at=None,
        source_time_raw="2026-09-25T17:00:10",
        source_time_status="UNKNOWN_TZ",
        source_sha256="b" * 64,
        doc_request_uid="request",
        prepared_archives=(EisArchiveReference(URL, "00000000000000000000000000000001"),),
    )
    return initial, prepared


def test_binds_ready_response_to_exact_downloaded_archive() -> None:
    initial, prepared = _responses()
    content = _zip("0848300054826000154")
    bound = bind_ready_window(WINDOW, initial, prepared, {URL: content})
    assert bound.archives == (content,)
    assert bound.response_sha256 == RESPONSE
    assert bound.prepared_response_sha256 == "b" * 64
    assert bound.archive_urls == (URL,)
    assert preflight_ready_window(bound).notice_count == 1


def test_by_number_accepts_exact_notice_and_rejects_other_number() -> None:
    number = "0848300054826000154"
    initial, prepared = _responses()
    initial = replace(initial, kind="BY_NUMBER")
    bound = bind_ready_window(
        f"getDocsIP/PRIZ/by-number/{number}", initial, prepared, {URL: _zip(number)}
    )
    assert preflight_ready_window(bound).notice_count == 1
    with pytest.raises(EisIndexConflict, match="BY_NUMBER_PURCHASE_MISMATCH"):
        preflight_ready_window(replace(bound, archives=(_zip("0848300064126000341"),)))
    with pytest.raises(EisIndexConflict, match="SOURCE_NOT_READY_OR_MISMATCHED"):
        bind_ready_window(WINDOW, initial, prepared, {URL: _zip(number)})


def test_document_types_have_separate_windows_and_cannot_be_mixed() -> None:
    from datetime import date

    from procurement.sources.eis_feed_sync import EisDateSelection

    auction = EisDateSelection("50", date(2026, 9, 25), 3)
    quotation = EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationEZK2020")
    competition = EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationEOK2020")
    assert len({auction.window_key, quotation.window_key, competition.window_key}) == 3
    content = _zip("0848300054826000154")
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_ready_window(EisReadyWindow(quotation.window_key, RESPONSE, 1, (content,)))
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_ready_window(EisReadyWindow(competition.window_key, RESPONSE, 1, (content,)))


def test_wrong_request_or_missing_download_fails_closed() -> None:
    initial, prepared = _responses()
    with pytest.raises(EisIndexConflict, match="SOURCE_NOT_READY_OR_MISMATCHED"):
        bind_ready_window(WINDOW, initial, replace(prepared, doc_request_uid="other"), {URL: b"x"})
    with pytest.raises(EisIndexConflict, match="ARCHIVE_URL_SET_MISMATCH"):
        bind_ready_window(WINDOW, initial, prepared, {})


def test_ready_url_can_change_but_archive_uid_must_match() -> None:
    initial, prepared = _responses()
    ready_url = URL.replace("https://int.zakupki.gov.ru", "https://int44.zakupki.gov.ru")
    ready = replace(
        prepared,
        prepared_archives=(EisArchiveReference(ready_url, "00000000000000000000000000000001"),),
    )
    content = _zip("0848300054826000154")
    assert bind_ready_window(WINDOW, initial, ready, {ready_url: content}).archives == (content,)
    wrong = replace(
        ready,
        prepared_archives=(EisArchiveReference(ready_url, "00000000000000000000000000000002"),),
    )
    with pytest.raises(EisIndexConflict, match="ARCHIVE_URL_SET_MISMATCH"):
        bind_ready_window(WINDOW, initial, wrong, {ready_url: content})


def test_archive_provenance_must_be_complete_and_official() -> None:
    content = _zip("0848300054826000154")
    with pytest.raises(EisIndexConflict, match="ARCHIVE_PROVENANCE_INCOMPLETE"):
        preflight_ready_window(EisReadyWindow(WINDOW, RESPONSE, 1, (content,), archive_urls=(URL,)))
    with pytest.raises(EisIndexConflict, match="ARCHIVE_PROVENANCE_INVALID"):
        preflight_ready_window(
            EisReadyWindow(
                WINDOW,
                RESPONSE,
                1,
                (content,),
                "b" * 64,
                ("https://example.com/secret",),
            )
        )


def test_all_archives_and_notices_enter_one_preflight() -> None:
    window = EisReadyWindow(
        WINDOW,
        RESPONSE,
        2,
        (_zip("0848300054826000154"), _zip("0848300064126000341", 2)),
    )
    result = preflight_ready_window(window)
    assert len(result.inspections) == 2
    assert result.notice_count == 2
    assert result.coverage == "UNKNOWN"
    assert result.manifest_sha256 == preflight_ready_window(window).manifest_sha256


def test_missing_archive_is_not_a_completed_window() -> None:
    with pytest.raises(EisIndexConflict, match="ARCHIVE_SET_INCOMPLETE"):
        preflight_ready_window(EisReadyWindow(WINDOW, RESPONSE, 2, (_zip("0848300054826000154"),)))


def test_window_expansion_budget_rejects_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eis_notice_index, "MAX_WINDOW_EXPANDED_BYTES", 1)
    with pytest.raises(EisIndexConflict, match="ARCHIVE_WINDOW_EXPANSION_LIMIT"):
        preflight_ready_window(EisReadyWindow(WINDOW, RESPONSE, 1, (_zip("0848300054826000154"),)))


def test_duplicate_notice_version_across_archives_rejected() -> None:
    first = _zip("0848300054826000154")
    second = _zip("0848300054826000154", 1, member="another.xml")
    with pytest.raises(EisIndexConflict, match="DUPLICATE_NOTICE_VERSION_IN_WINDOW"):
        preflight_ready_window(EisReadyWindow(WINDOW, RESPONSE, 2, (first, second)))


def test_invalid_source_coordinates_rejected() -> None:
    with pytest.raises(EisIndexConflict, match="SOURCE_COORDINATES_INVALID"):
        preflight_ready_window(
            EisReadyWindow(
                "getDocsIP/PRIZ/50/2026-09-25", RESPONSE, 1, (_zip("0848300054826000154"),)
            )
        )


def test_cancellation_has_separate_window_and_foreign_archive_fails() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "cancel.xml",
            """<export xmlns="http://zakupki.gov.ru/oos/export/1">
<epNotificationCancel><id>1</id><commonInfo>
<purchaseNumber>0848300054826000154</purchaseNumber></commonInfo>
<cancelReasonInfo/></epNotificationCancel></export>""",
        )
    key = WINDOW + "/epNotificationCancel"
    assert (
        preflight_ready_window(EisReadyWindow(key, RESPONSE, 1, (output.getvalue(),))).notice_count
        == 1
    )
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_ready_window(EisReadyWindow(key, RESPONSE, 1, (_zip("0848300054826000154"),)))
