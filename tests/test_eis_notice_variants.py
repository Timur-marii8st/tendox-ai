"""Typed evidence-only ledger tests; fake storage only, no database or source calls."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import pytest

import procurement.storage.eis_notice_variants as subject
from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_rejected_evidence import EisRejectedEvidence
from procurement.storage.eis_notice_variants import (
    EisNoticeVariantFacts,
    EisNoticeVariantOrigin,
    EisNoticeVariantState,
    read_notice_variant_state,
    store_notice_variants,
)
from test_eis_notice_conflicts import TOKEN, bundle, notice


def inputs(*, missing_id: bool = False):
    archives = (
        bundle(("a.xml", notice(document_id=None if missing_id else "44105096"))),
        bundle(("b.xml", notice(document_id=None if missing_id else "44105096"))),
    )
    diagnosis = diagnose_notice_conflicts(archives, TOKEN)
    evidence = EisRejectedEvidence(
        status="RETAINED",
        reason="NOTICE_VERSION_CONFLICT",
        company_id="tenant-a",
        window_key="getDocsIP/PRIZ/77/2026-10-02+03:00/epNotificationEF2020",
        observed_at=datetime(2026, 10, 4, 10, tzinfo=timezone(timedelta(hours=3))),
        response_sha256="a" * 64,
        prepared_response_sha256="b" * 64,
        archive_urls=("https://example.invalid/a", "https://example.invalid/b"),
        archive_sha256s=diagnosis.archive_sha256s,
        manifest_sha256="c" * 64,
        relative_manifest_path="tenant-a/rejected/evidence/manifest.json",
        complete_set=True,
    )
    return evidence, diagnosis


class NoTransactionStorage:
    @contextmanager
    def transaction(self, *args, **kwargs):
        pytest.fail("invalid preflight must fail before transaction")
        yield


def test_preflight_builds_distinct_immutable_facts_and_every_origin():
    evidence, diagnosis = inputs()
    variants, origins = subject._preflight("tenant-a", evidence, diagnosis, "variant-ledger")
    assert len(variants) == 1 and len(origins) == diagnosis.occurrence_count == 2
    facts = variants[0].model_dump(mode="json")
    assert "archive_ordinal" not in facts and "member_filename" not in facts
    assert {origin.archive_ordinal for origin in origins} == {0, 1}
    assert variants[0].document_id == "44105096"


def test_missing_document_id_remains_unknown_evidence_and_is_not_rejected():
    evidence, diagnosis = inputs(missing_id=True)
    variants, _ = subject._preflight("tenant-a", evidence, diagnosis, "actor")
    assert variants[0].document_id is None


def test_incomplete_occurrence_or_archive_mismatch_rejects_whole_ledger_before_write():
    evidence, diagnosis = inputs()
    incomplete = diagnosis.model_copy(
        update={
            "occurrences": (
                diagnosis.occurrences[0].model_copy(update={"purchase_number": None}),
                *diagnosis.occurrences[1:],
            )
        }
    )
    with pytest.raises(ValueError):
        store_notice_variants(
            NoTransactionStorage(), "tenant-a", evidence, incomplete, actor_id="actor"
        )
    mismatched = evidence.model_copy(update={"archive_sha256s": ("d" * 64, "e" * 64)})
    with pytest.raises(ValueError, match="NOTICE_VARIANT_LEDGER_INVALID"):
        store_notice_variants(
            NoTransactionStorage(), "tenant-a", mismatched, diagnosis, actor_id="actor"
        )


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def one(self):
        return self.rows


class ReadConnection:
    def __init__(self, responses):
        self.responses = iter(responses)

    def execute(self, statement, params=None):
        return Result(next(self.responses))


class ReadStorage:
    def __init__(self, responses):
        self.connection = ReadConnection(responses)

    @contextmanager
    def transaction(self, company, *, consistent_read=False):
        assert company == "tenant-a" and consistent_read is True
        yield self.connection


def facts(xml_sha: str = "1" * 64):
    return EisNoticeVariantFacts(
        purchase_number="0373100047426001450",
        version_number=1,
        document_type="epNotificationEF2020",
        xml_sha256=xml_sha,
        non_timing_sha256="2" * 64,
        document_id="44105096",
        published_raw="2026-10-01T10:00:00+03:00",
        start_raw="2026-10-01T10:00:00+03:00",
        published_at=datetime(2026, 10, 1, 7, tzinfo=UTC),
        start_at=datetime(2026, 10, 1, 7, tzinfo=UTC),
    )


def origin(selected: EisNoticeVariantFacts):
    return EisNoticeVariantOrigin(
        receipt_id="receipt-a",
        archive_ordinal=0,
        member_filename="notice.xml",
        archive_sha256="3" * 64,
        purchase_number=selected.purchase_number,
        version_number=selected.version_number,
        document_type=selected.document_type,
        xml_sha256=selected.xml_sha256,
    )


def fact_row(selected: EisNoticeVariantFacts):
    payload = selected.model_dump(mode="json")
    return {
        **subject._variant_key(selected),
        "facts": payload,
        "facts_sha256": subject._sha(payload),
    }


def test_reader_has_typed_none_complete_and_ambiguity_without_canonical_selection(monkeypatch):
    monkeypatch.setattr(subject, "_verify_state_source_bindings", lambda *args: True)
    none = read_notice_variant_state(ReadStorage([[]]), "tenant-a", "0373100047426001450", 1)
    assert none.status == "NONE" and none.ambiguity is None
    selected = facts()
    selected_origin = origin(selected)
    complete = read_notice_variant_state(
        ReadStorage(
            [
                [fact_row(selected)],
                [{"company_id": "tenant-a", **selected_origin.model_dump(mode="json")}],
            ]
        ),
        "tenant-a",
        selected.purchase_number,
        1,
    )
    assert complete.status == "COMPLETE" and complete.ambiguity is False
    assert complete.resolution == "UNKNOWN" and complete.canonical_admission == "NOT_ENABLED"
    other = facts("4" * 64)
    ambiguous = read_notice_variant_state(
        ReadStorage(
            [
                [
                    fact_row(selected),
                    fact_row(other),
                ],
                [
                    {"company_id": "tenant-a", **origin(selected).model_dump(mode="json")},
                    {"company_id": "tenant-a", **origin(other).model_dump(mode="json")},
                ],
            ]
        ),
        "tenant-a",
        selected.purchase_number,
        1,
    )
    assert ambiguous.status == "COMPLETE" and ambiguous.ambiguity is True


def test_reader_overflow_returns_no_subset(monkeypatch):
    monkeypatch.setattr(subject, "MAX_VARIANTS", 1)
    rows = [
        fact_row(facts("1" * 64)),
        fact_row(facts("2" * 64)),
    ]
    result = read_notice_variant_state(ReadStorage([rows]), "tenant-a", "0373100047426001450", 1)
    assert result == EisNoticeVariantState(
        purchase_number="0373100047426001450",
        version_number=1,
        status="OVERFLOW",
        ambiguity=None,
    )
    assert result.variants == result.origins == ()


def test_origin_overflow_returns_no_subset(monkeypatch):
    monkeypatch.setattr(subject, "MAX_ORIGINS", 1)
    selected = facts()
    first = origin(selected)
    second = first.model_copy(update={"receipt_id": "receipt-b"})
    result = read_notice_variant_state(
        ReadStorage(
            [
                [fact_row(selected)],
                [
                    {"company_id": "tenant-a", **first.model_dump(mode="json")},
                    {"company_id": "tenant-a", **second.model_dump(mode="json")},
                ],
            ]
        ),
        "tenant-a",
        selected.purchase_number,
        1,
    )
    assert result.status == "OVERFLOW" and not result.variants and not result.origins


def test_reader_rejects_fact_hash_or_semantic_key_mismatch():
    selected = facts()
    corrupted = fact_row(selected)
    corrupted["facts_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="NOTICE_VARIANT_FACT_ROW_INVALID"):
        read_notice_variant_state(
            ReadStorage([[corrupted]]), "tenant-a", selected.purchase_number, 1
        )


@pytest.mark.parametrize("filename", ["../notice.xml", "dir/notice.xml", "notice.txt"])
def test_origin_filename_is_strictly_bounded(filename):
    selected = facts()
    with pytest.raises(ValueError, match="NOTICE_VARIANT_ORIGIN_INVALID"):
        origin(selected).model_copy(update={"member_filename": filename}).__class__.model_validate(
            {**origin(selected).model_dump(), "member_filename": filename}
        )


def test_receipt_hash_is_stable_after_typed_datetime_roundtrip():
    evidence, diagnosis = inputs()
    variants, pending = subject._preflight("tenant-a", evidence, diagnosis, "actor")
    receipt_id = "receipt-a"
    origins = tuple(item.model_copy(update={"receipt_id": receipt_id}) for item in pending)
    row = subject._receipt_row(
        receipt_id,
        evidence,
        diagnosis,
        len(variants),
        "retention-audit",
        "diagnosis-audit",
        "ledger-audit",
    )
    digest = subject._receipt_sha(row, variants, origins)
    typed = subject.EisNoticeVariantReceipt.model_validate(
        {
            "company_id": "tenant-a",
            **row,
            "receipt_sha256": digest,
            "variants": variants,
            "origins": origins,
        }
    )
    assert digest == subject._receipt_sha(
        subject._receipt_payload_from_model(typed), typed.variants, typed.origins
    )


def typed_receipt(*, evidence_utc: bool = False):
    evidence, diagnosis = inputs()
    if evidence_utc:
        evidence = evidence.model_copy(update={"observed_at": evidence.observed_at.astimezone(UTC)})
    variants, pending = subject._preflight("tenant-a", evidence, diagnosis, "actor")
    receipt_id = "receipt-a"
    origins = tuple(item.model_copy(update={"receipt_id": receipt_id}) for item in pending)
    row = subject._receipt_row(
        receipt_id,
        evidence,
        diagnosis,
        len(variants),
        "retention-audit",
        "diagnosis-audit",
        "ledger-audit",
    )
    digest = subject._receipt_sha(row, variants, origins)
    return subject.EisNoticeVariantReceipt.model_validate(
        {
            "company_id": "tenant-a",
            **row,
            "receipt_sha256": digest,
            "variants": variants,
            "origins": origins,
        }
    )


@pytest.mark.parametrize("evidence_utc", [False, True])
def test_receipt_hash_uses_same_json_for_utc_and_non_utc_evidence(evidence_utc):
    receipt = typed_receipt(evidence_utc=evidence_utc)
    assert receipt.receipt_sha256 == subject._receipt_sha(
        subject._receipt_payload_from_model(receipt), receipt.variants, receipt.origins
    )


def test_receipt_model_rejects_missing_origin_count():
    receipt = typed_receipt()
    payload = receipt.model_dump()
    payload["origins"] = payload["origins"][:-1]
    with pytest.raises(ValueError, match="NOTICE_VARIANT_RECEIPT_INVALID"):
        subject.EisNoticeVariantReceipt.model_validate(payload)


def test_state_receipt_count_cap_stops_before_full_json_fetch(monkeypatch):
    monkeypatch.setattr(subject, "MAX_RECEIPTS", 1)
    connection = ReadConnection([(2, 1)])
    assert (
        subject._verify_state_source_bindings(connection, "tenant-a", (origin(facts()),)) is False
    )


def test_receipt_audit_byte_cap_stops_before_basis_fetch(monkeypatch):
    monkeypatch.setattr(subject, "MAX_READ_PAYLOAD_BYTES", 10)
    connection = ReadConnection([(3, 11)])
    with pytest.raises(ValueError, match="NOTICE_VARIANT_RECEIPT_READ_OVERFLOW"):
        subject._verify_receipt_audits(connection, typed_receipt())


def test_forged_ledger_audit_basis_is_rejected():
    receipt = typed_receipt()
    evidence_basis = {
        "evidence": receipt.evidence.model_dump(mode="json"),
        "coverage": "UNKNOWN",
    }
    rows = {
        receipt.retention_audit_event_id: (
            "EIS_REJECTED_WINDOW_EVIDENCE",
            "eis_sync_target",
            receipt.window_key,
            evidence_basis,
        ),
        receipt.diagnosis_audit_event_id: (
            "EIS_NOTICE_CONFLICT_DIAGNOSIS",
            "eis_sync_target",
            receipt.window_key,
            {
                "evidence": evidence_basis["evidence"],
                "diagnosis": {"sha256": receipt.diagnosis_sha256},
            },
        ),
        receipt.ledger_audit_event_id: (
            "EIS_NOTICE_VARIANT_LEDGER_RECORDED",
            "eis_notice_variant_receipt",
            receipt.receipt_id,
            {"forged": True},
        ),
    }
    with pytest.raises(ValueError, match="NOTICE_VARIANT_LEDGER_AUDIT_INVALID"):
        subject._validate_receipt_audits(receipt, rows)
