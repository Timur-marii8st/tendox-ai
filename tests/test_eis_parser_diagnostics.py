"""Parser diagnostics disclose categories and provenance, never source attachment text."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import Mock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from procurement.sources import eis_parser_diagnostics as subject
from procurement.storage.eis_notice_index import EisReadyWindow
from test_eis_feed_archive import _archive, _notice, _notice_with_attachments

TOKEN = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 10, 6, tzinfo=UTC)
NUMBER = "0848300054826000154"


def window(*archives):
    return EisReadyWindow("getDocsIP/PRIZ/50/2026-09-25+03:00", "a" * 64, len(archives), archives)


def diagnose(source, **kwargs):
    return subject.diagnose_eis_parser_window(
        source, company_id="tenant-a", observed_at=NOW, token=TOKEN, **kwargs
    )


def test_multiple_predicates_preserve_canonical_reason_and_hide_source_values():
    xml = _notice_with_attachments(NUMBER, 1)
    xml = xml.replace(b"00000000000000000000000000000001", b"lowercase-secret-uid")
    xml = xml.replace(b"document-1.pdf", b"private\\filename.pdf")
    xml = xml.replace(b"<fileSize>1</fileSize>", b"<fileSize>not-a-number</fileSize>")
    xml = xml.replace(b"https://zakupki.gov.ru/", b"https://secret.invalid/")
    archive = _archive(("secret-member.xml", xml))
    report = diagnose(window(archive))
    assert report.archives[0].parser_reason == "ATTACHMENT_REFERENCE_INVALID"
    finding = report.findings[0]
    assert set(finding.failure_flags) == {
        "UID_INVALID",
        "FILENAME_BACKSLASH_OR_NUL",
        "FILE_SIZE_INVALID",
        "URL_BINDING_INVALID",
    }
    assert finding.archive_sha256 == hashlib.sha256(archive).hexdigest()
    assert finding.xml_sha256 == hashlib.sha256(xml).hexdigest()
    assert finding.member_name_sha256 == hashlib.sha256(b"secret-member.xml").hexdigest()
    assert finding.attachment_ordinal == finding.member_ordinal == 1
    assert finding.locator == "epNotificationEF2020/attachmentsInfo/attachmentInfo[1]"
    output = report.model_dump_json()
    for raw in (
        "lowercase-secret-uid",
        "private\\filename.pdf",
        "secret.invalid",
        "secret-member.xml",
        TOKEN,
    ):
        assert raw not in output
    assert report.coverage == "UNKNOWN" and report.canonical_admission == "NOT_ENABLED"
    assert report.source_requests == 0 and report.response_sha256 == "a" * 64


def test_duplicate_uid_and_truncated_samples_still_count_all_findings():
    xml = _notice_with_attachments(NUMBER, 3, duplicate_last_uid=True)
    xml = xml.replace(b"document-2.pdf", b"path\\document-2.pdf")
    report = diagnose(window(_archive(("a.xml", xml))), max_findings=1)
    assert report.finding_count == 2 and len(report.findings) == 1 and report.truncated
    full = diagnose(window(_archive(("a.xml", xml))))
    assert "DUPLICATE_UID" in full.findings[1].failure_flags
    assert full.known_attachment_count == full.inspected_attachment_count == 3


@pytest.mark.parametrize(
    "xml, reason",
    [(b"<broken", "XML_INVALID"), (b'<!DOCTYPE a [<!ENTITY b "secret">]><a>&b;</a>', "XML_UNSAFE")],
)
def test_invalid_or_unsafe_xml_does_not_reparse_attachments(monkeypatch, xml, reason):
    diagnostics = Mock(side_effect=AssertionError("unsafe XML must not be reparsed"))
    monkeypatch.setattr(subject, "_attachment_findings", diagnostics)
    report = diagnose(window(_archive(("a.xml", xml))))
    assert report.archives[0].parser_reason == reason
    assert not report.inspection_complete and not report.attachment_census_complete
    diagnostics.assert_not_called()


@pytest.mark.parametrize(
    "encrypted, oversized, path", [(True, False, False), (False, True, False), (True, True, True)]
)
def test_unsafe_metadata_never_opens_member(monkeypatch, encrypted, oversized, path):
    archive = _archive(("safe.xml", _notice(NUMBER)))
    original = subject.ZipFile.infolist

    def metadata(self):
        infos = original(self)
        for info in infos:
            if encrypted:
                info.flag_bits |= 1
            if oversized:
                info.file_size = subject.parser._MAX_XML_BYTES + 1
            if path:
                info.filename = "private/path.bin"
        return infos

    monkeypatch.setattr(subject.ZipFile, "infolist", metadata)
    reader = Mock(side_effect=AssertionError("unsafe metadata must not decompress"))
    monkeypatch.setattr(subject.ZipFile, "open", reader)
    report = diagnose(window(archive))
    assert report.archives[0].parser_reason == "MEMBER_UNSUPPORTED"
    assert report.inspected_xml_count == 0 and report.archives[0].skipped_member_count == 1
    flags = report.findings[0].failure_flags
    assert ("MEMBER_ENCRYPTED" in flags) == encrypted
    assert ("MEMBER_XML_SIZE_LIMIT" in flags) == oversized
    assert report.findings[0].xml_sha256 is None
    reader.assert_not_called()


def test_bad_archive_is_explicit_incomplete_census():
    report = diagnose(window(b"PK\x03\x04garbage"))
    assert report.archives[0].parser_reason == "ARCHIVE_INVALID"
    assert not report.census_complete and report.known_member_count == 0


def test_member_count_limit_does_not_decompress(monkeypatch):
    archive = _archive(*((f"{i}.xml", b"x") for i in range(1001)))
    reader = Mock(side_effect=AssertionError("count limit must not decompress"))
    monkeypatch.setattr(subject.ZipFile, "open", reader)
    report = diagnose(window(archive))
    assert report.archives[0].parser_reason == "MEMBER_COUNT_INVALID"
    assert report.known_member_count == 1001 and report.inspected_xml_count == 0
    reader.assert_not_called()


def test_window_resource_limits_and_incomplete_archive_set(monkeypatch):
    source = window(_archive(("a.xml", _notice(NUMBER))))
    with pytest.raises(ValueError, match="ARCHIVE_SET_INCOMPLETE"):
        diagnose(replace(source, expected_archive_count=2))
    with pytest.raises(ValueError, match="ARCHIVE_COUNT_INVALID"):
        diagnose(replace(source, expected_archive_count=21))
    monkeypatch.setattr(subject, "MAX_WINDOW_COMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="ARCHIVE_WINDOW_SIZE_LIMIT"):
        diagnose(source)


def test_expansion_limit_checked_before_member_read(monkeypatch):
    source = window(_archive(("a.xml", _notice(NUMBER))))
    monkeypatch.setattr(subject, "MAX_WINDOW_EXPANDED_BYTES", 1)
    reader = Mock(side_effect=AssertionError("expansion limit must not decompress"))
    monkeypatch.setattr(subject.ZipFile, "open", reader)
    with pytest.raises(ValueError, match="ARCHIVE_WINDOW_EXPANSION_LIMIT"):
        diagnose(source)
    reader.assert_not_called()


@pytest.mark.parametrize("where", ["xml", "member", "company"])
def test_token_reflection_rejected_without_sensitive_error(where):
    xml = (
        _notice(NUMBER).replace(b"</export>", f"<!--{TOKEN}--></export>".encode())
        if where == "xml"
        else _notice(NUMBER)
    )
    member = f"{TOKEN}.xml" if where == "member" else "safe.xml"
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(member, xml)
    with pytest.raises(subject.EisParserDiagnosticError, match=r"^TOKEN_REFLECTION$"):
        subject.diagnose_eis_parser_window(
            window(buffer.getvalue()),
            company_id=TOKEN if where == "company" else "tenant",
            observed_at=NOW,
            token=TOKEN,
        )


@pytest.mark.parametrize(
    "company, now, limit",
    [
        ("", NOW, 1),
        ("../tenant", NOW, 1),
        ("tenant", NOW.replace(tzinfo=None), 1),
        ("tenant", NOW, 0),
        ("tenant", NOW, 101),
    ],
)
def test_input_validation(company, now, limit):
    with pytest.raises(ValueError, match="DIAGNOSTIC_INPUT_INVALID"):
        subject.diagnose_eis_parser_window(
            window(b"x"), company_id=company, observed_at=now, token=TOKEN, max_findings=limit
        )


def test_no_parser_error_is_not_canonical_admission():
    report = diagnose(window(_archive(("a.xml", _notice(NUMBER)))))
    assert report.archives[0].parser_status == "NO_ERROR_OBSERVED"
    assert report.finding_count == 0 and not report.truncated
    assert report.canonical_admission == "NOT_ENABLED" and report.coverage == "UNKNOWN"


def test_complete_window_expansion_preflight_precedes_first_xml_read(monkeypatch):
    first = _archive(("first.xml", _notice(NUMBER)))
    second = _archive(("second.xml", _notice(NUMBER)))
    with ZipFile(BytesIO(first)) as archive:
        first_size = sum(info.file_size for info in archive.infolist())
    monkeypatch.setattr(subject, "MAX_WINDOW_EXPANDED_BYTES", first_size + 1)
    reader = Mock(side_effect=AssertionError("later ZIP expansion must stop before first XML"))
    monkeypatch.setattr(subject.ZipFile, "open", reader)
    with pytest.raises(ValueError, match="ARCHIVE_WINDOW_EXPANSION_LIMIT"):
        diagnose(window(first, second))
    reader.assert_not_called()


@pytest.mark.parametrize(
    "shape, flag", [("nodes", "DIAGNOSTIC_XML_NODE_LIMIT"), ("depth", "DIAGNOSTIC_XML_DEPTH_LIMIT")]
)
def test_streaming_shape_caps_precede_both_full_tree_parsers(monkeypatch, shape, flag):
    if shape == "nodes":
        xml = b"<root>" + b"<node/>" * subject.MAX_XML_NODES + b"</root>"
    else:
        xml = b"<node>" * (subject.MAX_XML_DEPTH + 1) + b"</node>" * (subject.MAX_XML_DEPTH + 1)
    notice_parser = Mock(side_effect=AssertionError("full notice parsing forbidden"))
    tree_parser = Mock(side_effect=AssertionError("full tree parsing forbidden"))
    monkeypatch.setattr(subject.parser, "_notice", notice_parser)
    monkeypatch.setattr(subject.ET, "fromstring", tree_parser)
    report = diagnose(window(_archive(("dense.xml", xml))))
    assert report.archives[0].parser_status == "NOT_RUN"
    assert report.archives[0].parser_reason is None
    assert report.findings[0].inspection_status == "UNKNOWN"
    assert report.findings[0].failure_flags == (flag,)
    assert not report.inspection_complete and report.inspected_xml_count == 0
    notice_parser.assert_not_called()
    tree_parser.assert_not_called()


def test_utf16_doctype_is_stopped_by_stream_target_before_full_tree(monkeypatch):
    xml = '<!DOCTYPE a [<!ENTITY b "unsafe">]><a>&b;</a>'.encode("utf-16")
    notice_parser = Mock(side_effect=AssertionError("DTD cannot reach full parser"))
    monkeypatch.setattr(subject.parser, "_notice", notice_parser)
    report = diagnose(window(_archive(("unsafe.xml", xml))))
    assert report.findings[0].failure_flags == ("DIAGNOSTIC_XML_DTD_UNSAFE",)
    assert report.archives[0].parser_status == "NOT_RUN"
    notice_parser.assert_not_called()


def test_decoded_token_reflection_is_rejected_in_streaming_guard():
    encoded = "".join(f"&#{ord(char)};" for char in TOKEN)
    xml = _notice(NUMBER).replace(
        b"</export>", f"<!--normal--><secret>{encoded}</secret></export>".encode()
    )
    with pytest.raises(subject.EisParserDiagnosticError, match=r"^TOKEN_REFLECTION$"):
        diagnose(window(_archive(("safe.xml", xml))))


def test_forward_slash_source_display_label_matches_shared_parser_predicate():
    xml = _notice_with_attachments(NUMBER, 1).replace(
        b"document-1.pdf", b"source/display-label.pdf"
    )
    report = diagnose(window(_archive(("safe.xml", xml))))
    assert not subject.parser._attachment_filename_invalid("source/display-label.pdf")
    assert report.archives[0].parser_status == "NO_ERROR_OBSERVED"
    assert report.finding_count == 0 and report.inspected_attachment_count == 1
    assert "source/display-label.pdf" not in report.model_dump_json()
