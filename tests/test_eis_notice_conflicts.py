"""Synthetic offline conflict diagnosis; no source, database, or filesystem writes."""

import hashlib
import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import procurement.sources.eis_notice_conflicts as subject
from procurement.sources.eis_notice_conflicts import (
    EisNoticeConflictError,
    diagnose_notice_conflicts,
)

TOKEN = "SyntheticSecret-123"


def notice(
    *,
    document_type: str = "epNotificationEF2020",
    document_id: str | None = "44105096",
    version: str = "1",
    published: str = "2026-10-01T10:00:00+03:00",
    start: str = "2026-10-01T10:00:00+03:00",
    title: str = "Synthetic",
    extra: str = "",
) -> bytes:
    identifier = f"<ep:id>{document_id}</ep:id>" if document_id is not None else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<e:export xmlns:e="http://zakupki.gov.ru/oos/export/1"
 xmlns:ep="http://zakupki.gov.ru/oos/EPtypes/1"
 xmlns:c="http://zakupki.gov.ru/oos/common/1"
 xmlns:b="http://zakupki.gov.ru/oos/base/1">
 <e:{document_type}>
  {identifier}<ep:versionNumber>{version}</ep:versionNumber>
  <ep:commonInfo><ep:purchaseNumber>0373100047426001450</ep:purchaseNumber>
   <ep:publishDTInEIS>{published}</ep:publishDTInEIS><ep:purchaseObjectInfo>{title}</ep:purchaseObjectInfo>
  </ep:commonInfo>
  <ep:notificationInfo><ep:procedureInfo><ep:collectingInfo>
   <ep:startDT>{start}</ep:startDT>{extra}
  </ep:collectingInfo></ep:procedureInfo></ep:notificationInfo>
 </e:{document_type}>
</e:export>""".encode()


def bundle(*members: tuple[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


def test_same_document_id_divergent_timing_is_inventory_without_winner():
    first = notice()
    second = notice(
        published="2026-10-01T10:01:27+03:00",
        start="2026-10-01T10:01:27+03:00",
    )
    result = diagnose_notice_conflicts(
        (bundle(("first.xml", first)), bundle(("second.xml", second))), TOKEN
    )
    group = result.duplicate_groups[0]
    assert result.status == "COMPLETE" and result.coverage == "UNKNOWN"
    assert group.classification == "DIVERGENT" and group.document_identity == "SAME"
    assert group.changed_fields == ("publication", "start")
    assert group.other_fields_differ is False and group.difference_category_count == 2
    assert len(result.occurrences) == result.occurrence_count == 2
    assert result.archive_sha256s == tuple(
        hashlib.sha256(raw).hexdigest()
        for raw in (bundle(("first.xml", first)), bundle(("second.xml", second)))
    )


def test_exact_xml_bytes_across_archives_are_byte_identical():
    raw = notice()
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", raw)), bundle(("b.xml", raw))), TOKEN
    )
    group = result.duplicate_groups[0]
    assert group.classification == "BYTE_IDENTICAL"
    assert group.document_identity == "SAME" and group.difference_category_count == 0


@pytest.mark.parametrize(
    ("left_id", "right_id", "identity"),
    [("44105096", "44105097", "DIFFERENT"), (None, "44105096", "UNKNOWN")],
)
def test_document_identity_never_falls_back_to_member_name(left_id, right_id, identity):
    result = diagnose_notice_conflicts(
        (
            bundle(("same-name-a.xml", notice(document_id=left_id))),
            bundle(("same-name-b.xml", notice(document_id=right_id))),
        ),
        TOKEN,
    )
    assert result.duplicate_groups[0].document_identity == identity


@pytest.mark.parametrize("document_id", ["arbitrary", str(2**63), "1 2", "9" * 5000])
def test_malformed_or_out_of_range_document_id_is_unknown(document_id):
    result = diagnose_notice_conflicts(
        (
            bundle(("a.xml", notice(document_id=document_id))),
            bundle(("b.xml", notice(document_id=document_id))),
        ),
        TOKEN,
    )
    assert result.duplicate_groups[0].document_identity == "UNKNOWN"


def test_nested_document_id_is_not_a_valid_identity():
    nested = notice().replace(b"44105096", b"<ep:value>44105096</ep:value>")
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", nested)), bundle(("b.xml", nested))), TOKEN
    )
    assert result.duplicate_groups[0].document_identity == "UNKNOWN"


def test_nested_purchase_number_is_not_an_index_identity():
    nested = notice().replace(
        b"0373100047426001450", b"<ep:value>0373100047426001450</ep:value>"
    )
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", nested)), bundle(("b.xml", nested))), TOKEN
    )
    assert result.duplicate_group_count == 0
    assert all(item.purchase_number is None for item in result.occurrences)


@pytest.mark.parametrize("version", ["0", str(2**31), "arbitrary", "9" * 5000])
def test_invalid_runtime_version_is_inventory_but_not_a_duplicate_key(version):
    raw = notice(version=version)
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", raw)), bundle(("b.xml", raw))), TOKEN
    )
    assert result.occurrence_count == 2 and result.duplicate_group_count == 0
    assert all(item.version_number is None for item in result.occurrences)


def test_cross_document_type_collision_is_one_different_identity_group():
    result = diagnose_notice_conflicts(
        (
            bundle(("a.xml", notice())),
            bundle(("b.xml", notice(document_type="epNotificationEZK2020"))),
        ),
        TOKEN,
    )
    group = result.duplicate_groups[0]
    assert group.document_types == ("epNotificationEF2020", "epNotificationEZK2020")
    assert group.document_identity == "DIFFERENT"


def test_lexically_distinct_equal_instants_remain_a_timestamp_difference():
    result = diagnose_notice_conflicts(
        (
            bundle(("a.xml", notice(published="2026-10-01T10:00:00+03:00"))),
            bundle(("b.xml", notice(published="2026-10-01T07:00:00+00:00"))),
        ),
        TOKEN,
    )
    assert result.duplicate_groups[0].changed_fields == ("publication",)


def test_unrelated_nested_start_timestamp_is_not_stripped_as_allowed_timing():
    left = notice(extra="<ep:other><ep:startDT>2026-01-01T00:00:00+03:00</ep:startDT></ep:other>")
    right = notice(extra="<ep:other><ep:startDT>2026-01-02T00:00:00+03:00</ep:startDT></ep:other>")
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", left)), bundle(("b.xml", right))), TOKEN
    )
    group = result.duplicate_groups[0]
    assert group.changed_fields == () and group.other_fields_differ is True


def test_other_business_field_difference_is_only_reported_as_bounded_flag():
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", notice())), bundle(("b.xml", notice(title="Changed")))), TOKEN
    )
    group = result.duplicate_groups[0]
    assert group.other_fields_differ is True and group.changed_fields == ()
    assert group.difference_category_count == 1


def test_safe_summary_contains_counts_only_and_hash_is_canonical():
    result = diagnose_notice_conflicts((bundle(("secret-name.xml", notice())),), TOKEN)
    summary = result.safe_summary()
    encoded = json.dumps(summary, sort_keys=True)
    assert "secret-name" not in encoded and "0373100047426001450" not in encoded
    payload = result.model_dump(mode="json")
    claimed = payload.pop("sha256")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == claimed
    payload["sha256"] = claimed
    payload["occurrence_count"] = 2
    with pytest.raises(ValueError, match="DIAGNOSIS_SHA256_INVALID"):
        subject.EisNoticeConflictDiagnosis.model_validate(payload)


def test_rehashed_forged_duplicate_classification_is_rejected():
    result = diagnose_notice_conflicts(
        (bundle(("a.xml", notice())), bundle(("b.xml", notice()))), TOKEN
    )
    payload = result.model_dump(mode="json")
    payload["duplicate_groups"][0]["classification"] = "DIVERGENT"
    unsigned = {key: value for key, value in payload.items() if key != "sha256"}
    payload["sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="DIAGNOSIS_GROUP_CLASSIFICATION_INVALID"):
        subject.EisNoticeConflictDiagnosis.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda raw: raw.replace(b"xmlns:ep=", b"xmlns:epx="), "XML_INVALID"),
        (
            lambda raw: raw.replace(
                b"<ep:id>44105096</ep:id>",
                b"<ep:id>44105096</ep:id><ep:id>44105096</ep:id>",
            ),
            "DIRECT_CHILD_AMBIGUOUS",
        ),
        (
            lambda raw: raw.replace(
                b"<ep:id>44105096</ep:id>",
                b'<x:id xmlns:x="urn:spoof">44105096</x:id>',
            ),
            "NAMESPACE_UNSUPPORTED",
        ),
    ],
)
def test_namespace_spoof_or_direct_multiplicity_never_proves_identity(mutation, code):
    with pytest.raises(EisNoticeConflictError, match=code):
        diagnose_notice_conflicts((bundle(("notice.xml", mutation(notice()))),), TOKEN)


def test_invalid_final_archive_is_rejected_before_any_xml_parse(monkeypatch):
    def no_parse(*args, **kwargs):
        pytest.fail("XML parsing must wait for all archive headers and members")

    monkeypatch.setattr(subject, "_occurrence", no_parse)
    with pytest.raises(EisNoticeConflictError, match="ARCHIVE_INVALID"):
        diagnose_notice_conflicts((bundle(("first.xml", notice())), b"not-a-zip"), TOKEN)


def test_utf16_xml_is_rejected_before_identity_parsing():
    utf16 = notice().decode().encode("utf-16")
    with pytest.raises(EisNoticeConflictError, match="XML_ENCODING_UNSUPPORTED"):
        diagnose_notice_conflicts((bundle(("notice.xml", utf16)),), TOKEN)


@pytest.mark.parametrize(
    "raw",
    [
        notice().replace(b"Synthetic", b"Syn\x00thetic"),
        notice().replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"'),
        b"\xef\xbb\xbf"
        + notice().replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"'),
    ],
)
def test_nul_or_non_utf8_declaration_is_rejected_before_parse(raw):
    with pytest.raises(EisNoticeConflictError, match="XML_ENCODING_UNSUPPORTED"):
        diagnose_notice_conflicts((bundle(("notice.xml", raw)),), TOKEN)


def test_utf8_bom_with_utf8_declaration_is_allowed():
    result = diagnose_notice_conflicts(
        (bundle(("notice.xml", b"\xef\xbb\xbf" + notice())),), TOKEN
    )
    assert result.occurrence_count == 1


@pytest.mark.parametrize(
    ("limit_name", "extra", "code"),
    [
        ("MAX_XML_NODES", "<ep:a/><ep:b/>", "XML_NODE_LIMIT"),
        ("MAX_XML_DEPTH", "<ep:a><ep:b/></ep:a>", "XML_DEPTH_LIMIT"),
    ],
)
def test_xml_node_and_depth_are_bounded_during_parse(monkeypatch, limit_name, extra, code):
    monkeypatch.setattr(subject, limit_name, 6)
    with pytest.raises(EisNoticeConflictError, match=code):
        diagnose_notice_conflicts((bundle(("notice.xml", notice(extra=extra))),), TOKEN)


def test_character_reference_token_reflection_is_rejected_after_decode():
    reflected = notice(title="&#83;yntheticSecret-123")
    assert TOKEN.encode() not in reflected
    with pytest.raises(EisNoticeConflictError, match="TOKEN_REFLECTION"):
        diagnose_notice_conflicts((bundle(("notice.xml", reflected)),), TOKEN)


@pytest.mark.parametrize(
    ("archives", "code"),
    [
        ((bundle(("../notice.xml", notice())),), "MEMBER_UNSAFE"),
        ((bundle(("notice.xml", notice() + TOKEN.encode())),), "TOKEN_REFLECTION"),
        (
            (
                bundle(
                    ("notice.xml", b'<!DOCTYPE x [<!ENTITY y "z">]>' + notice())
                ),
            ),
            "XML_UNSAFE",
        ),
    ],
)
def test_member_security_and_reflection_are_fail_closed(archives, code):
    with pytest.raises(EisNoticeConflictError, match=code):
        diagnose_notice_conflicts(archives, TOKEN)


def test_duplicate_zip_member_names_and_full_window_bounds(monkeypatch):
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = bundle(("notice.xml", notice()), ("notice.xml", notice()))
    with pytest.raises(EisNoticeConflictError, match="DUPLICATE_MEMBER_NAME"):
        diagnose_notice_conflicts((duplicate,), TOKEN)
    monkeypatch.setattr(subject, "MAX_TOTAL_MEMBERS", 1)
    with pytest.raises(EisNoticeConflictError, match="TOTAL_MEMBER_COUNT_LIMIT"):
        diagnose_notice_conflicts((bundle(("a.xml", notice()), ("b.xml", notice())),), TOKEN)
    with pytest.raises(EisNoticeConflictError, match="MEMBER_UNSAFE"):
        diagnose_notice_conflicts((bundle(("x" * 252 + ".xml", notice())),), TOKEN)


def test_serialized_diagnosis_is_bounded(monkeypatch):
    monkeypatch.setattr(subject, "MAX_DIAGNOSIS_BYTES", 10)
    with pytest.raises(EisNoticeConflictError, match="DIAGNOSIS_BYTES_LIMIT"):
        diagnose_notice_conflicts((bundle(("notice.xml", notice())),), TOKEN)
