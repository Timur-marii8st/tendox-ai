"""Bounded retained notice projection tests; synthetic archives only."""

from dataclasses import replace

import pytest

import procurement.sources.eis_notice_projection as subject
from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_notice_projection import (
    EisNoticeProjectionError,
    prepare_notice_projection,
)
from test_eis_notice_conflicts import TOKEN, bundle, notice


def diagnosis(archives):
    return diagnose_notice_conflicts(archives, TOKEN)


def test_singleton_is_fully_parsed_and_bound_to_exact_origin():
    archives = (bundle(("only.xml", notice())),)
    result = prepare_notice_projection(archives, diagnosis(archives))
    assert result.occurrence_count == 1
    assert result.archive_member_counts == (1,)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.reason is None and candidate.snapshot is not None
    assert candidate.snapshot.xml_sha256 == candidate.xml_sha256
    assert candidate.snapshot.source_member == candidate.member_filename == "only.xml"


def test_byte_identical_copies_make_one_deterministic_candidate():
    xml = notice()
    archives = (bundle(("z.xml", xml)), bundle(("a.xml", xml)))
    result = prepare_notice_projection(archives, diagnosis(archives))
    assert result.occurrence_count == 2 and result.archive_member_counts == (1, 1)
    assert len(result.candidates) == 1
    assert result.candidates[0].archive_ordinal == 0
    assert result.candidates[0].member_filename == "z.xml"
    assert result.candidates[0].snapshot is not None


def test_divergent_pair_is_explicit_hold_without_winner():
    archives = (
        bundle(("first.xml", notice())),
        bundle(("second.xml", notice(start="2026-10-01T10:01:27+03:00"))),
    )
    result = prepare_notice_projection(archives, diagnosis(archives))
    candidate = result.candidates[0]
    assert candidate.snapshot is None
    assert candidate.reason == "DIVERGENT_VARIANT_REVIEW_REQUIRED"


def test_unknown_source_id_is_hold_even_when_bytes_are_otherwise_parseable():
    archives = (bundle(("only.xml", notice(document_id=None))),)
    candidate = prepare_notice_projection(archives, diagnosis(archives)).candidates[0]
    assert candidate.snapshot is None and candidate.reason == "SOURCE_ID_UNKNOWN"


def test_parser_failure_is_an_explicit_candidate_hold():
    archives = (bundle(("only.xml", notice(title=""))),)
    candidate = prepare_notice_projection(archives, diagnosis(archives)).candidates[0]
    assert candidate.snapshot is None
    assert candidate.reason == "NOTICE_PARSE_FAILED:FIELD_EMPTY"


def test_diagnosis_from_another_exact_archive_set_rejects_whole_batch():
    archives = (bundle(("only.xml", notice())),)
    other = (bundle(("other.xml", notice(title="Other"))),)
    with pytest.raises(EisNoticeProjectionError, match="DIAGNOSIS_BINDING_MISMATCH"):
        prepare_notice_projection(archives, diagnosis(other))


def test_unknown_semantic_identity_rejects_whole_inventory():
    nested = notice().replace(b"0373100047426001450", b"<ep:value>0373100047426001450</ep:value>")
    archives = (bundle(("only.xml", nested)),)
    with pytest.raises(EisNoticeProjectionError, match="SEMANTIC_IDENTITY_UNKNOWN"):
        prepare_notice_projection(archives, diagnosis(archives))


def test_snapshot_payload_limit_fails_closed(monkeypatch):
    archives = (bundle(("only.xml", notice())),)
    monkeypatch.setattr(subject, "MAX_PROJECTION_SNAPSHOT_BYTES", 1)
    with pytest.raises(EisNoticeProjectionError, match="PROJECTION_SNAPSHOT_BYTES_LIMIT"):
        prepare_notice_projection(archives, diagnosis(archives))


def test_snapshot_budget_uses_compact_utf8_without_ascii_escape_inflation(monkeypatch):
    archives = (bundle(("only.xml", notice(title="Поставка оборудования"))),)
    parsed = prepare_notice_projection(archives, diagnosis(archives)).candidates[0].snapshot
    assert parsed is not None
    compact_utf8 = subject._snapshot_payload_bytes(parsed)
    ascii_size = len(
        subject.json.dumps(
            subject.asdict(parsed), default=str, sort_keys=True, ensure_ascii=True
        ).encode()
    )
    assert compact_utf8 < ascii_size
    monkeypatch.setattr(subject, "MAX_PROJECTION_SNAPSHOT_BYTES", compact_utf8)
    assert prepare_notice_projection(archives, diagnosis(archives)).candidates[0].snapshot


def test_candidate_validator_rejects_snapshot_identity_drift():
    archives = (bundle(("only.xml", notice())),)
    candidate = prepare_notice_projection(archives, diagnosis(archives)).candidates[0]
    assert candidate.snapshot is not None
    with pytest.raises(ValueError, match="PROJECTION_SNAPSHOT_BINDING_INVALID"):
        replace(candidate, snapshot=replace(candidate.snapshot, version_number=2))
