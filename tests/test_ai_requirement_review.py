"""Imported AI reports require exact source binding and independent full review."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from procurement.documents.ai_requirement_review import (
    AiRequirementCandidateDecision,
    AiRequirementReviewRecord,
    AiRequirementRunSnapshot,
    CandidateDisposition,
    CandidateKind,
    build_ai_requirement_review_decision,
    build_ai_requirement_run_snapshot,
)
from procurement.documents.ai_requirements import (
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    OpenRouterJsonResponse,
    analyze_requirements_with_model,
    validate_ai_requirement_report,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.documents.facts import CompletenessStatus
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 17, 10, tzinfo=UTC)


class _Client:
    def complete_json(self, **kwargs: object) -> OpenRouterJsonResponse:
        model = kwargs["model"]
        assert isinstance(model, str)
        content = json.dumps(
            {
                "items": [
                    {
                        "item_name": {"value": "Насос", "source_block_ids": ["b000001"]},
                        "okpd2_codes": [{"value": "28.13.14.110", "source_block_ids": ["b000001"]}],
                        "ktru_codes": [
                            {
                                "value": "28.13.14.110-00000001",
                                "source_block_ids": ["b000001"],
                            }
                        ],
                        "unit": {"value": "шт", "source_block_ids": ["b000002"]},
                        "quantity": {"value": "2,00", "source_block_ids": ["b000003"]},
                        "uncertainty": None,
                    }
                ],
                "requirements": [
                    {
                        "item_name": "Насос",
                        "property": "power",
                        "operator": ">=",
                        "value": "5",
                        "unit": "кВт",
                        "mandatory": True,
                        "source_block_ids": ["b000001"],
                        "uncertainty": None,
                    }
                ],
                "unresolved_block_ids": [],
                "document_notes": [],
            },
            ensure_ascii=False,
        )
        return OpenRouterJsonResponse(
            request_sha256="a" * 64,
            response_id="response-1",
            model=model,
            content=content,
        )


class _RawClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def complete_json(self, **kwargs: object) -> OpenRouterJsonResponse:
        model = kwargs["model"]
        assert isinstance(model, str)
        return OpenRouterJsonResponse(
            request_sha256="a" * 64,
            response_id="response-raw",
            model=model,
            content=self.content,
        )


def _block(text: str, locator: str) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        provenance=Provenance(
            document_id="doc-1",
            locator=locator,
            extractor=Extractor.NATIVE_DOCX,
            confidence=1,
        ),
    )


def _extraction() -> ExtractionResult:
    blocks = (
        _block(
            "Насос; мощность не менее 5 кВт; 28.13.14.110; 28.13.14.110-00000001",
            "table 1 row 2 cell 1",
        ),
        _block("шт", "table 1 row 2 cell 2"),
        _block("2,00", "table 1 row 2 cell 3"),
    )
    return ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=blocks,
        reasons=(),
        source_units_total=3,
        source_units_extracted=3,
        characters_extracted=sum(len(block.text) for block in blocks),
    )


def _v2_report() -> AiRequirementAnalysisReportV2:
    return analyze_requirements_with_model(
        _extraction(),
        company_id="company-a",
        source_sha256="b" * 64,
        authorization_reference="approved import",
        client=_Client(),
        created_at=NOW,
    )


def _v1_report() -> AiRequirementAnalysisReport:
    payload = _v2_report().model_dump(mode="json")
    payload["schema_version"] = "ai-requirement-analysis-v1"
    payload["prompt_version"] = "ai-requirements-v1"
    payload.pop("item_candidates")
    for chunk in payload["chunks"]:
        chunk.pop("item_candidates")
    payload["evidence_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "evidence_sha256"}
    )
    checked = validate_ai_requirement_report(payload)
    assert isinstance(checked, AiRequirementAnalysisReport)
    return checked


def _snapshot(
    report: AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
) -> AiRequirementRunSnapshot:
    return build_ai_requirement_run_snapshot(
        company_id="company-a",
        run_id="run-1",
        source_document_id="doc-1",
        source_sha256="b" * 64,
        extraction=_extraction(),
        report=report,
        submitted_by="operator-1",
        submitted_at=NOW,
    )


@pytest.mark.parametrize("version", [1, 2])
def test_snapshot_preserves_validated_report_version_and_unknown_completeness(
    version: int,
) -> None:
    report = _v1_report() if version == 1 else _v2_report()
    snapshot = _snapshot(report)

    assert type(snapshot.report) is type(report)
    assert snapshot.origin == "IMPORTED_REPORT"
    assert snapshot.extraction == _extraction()
    assert snapshot.report.completeness_status is CompletenessStatus.UNKNOWN
    assert snapshot.completeness_status is CompletenessStatus.UNKNOWN
    assert snapshot.evidence_sha256 == canonical_json_sha256(
        snapshot.model_dump(mode="json", exclude={"evidence_sha256"})
    )


@pytest.mark.parametrize("tamper", ["text", "provenance", "item_provenance"])
def test_recomputed_report_digest_cannot_hide_tampered_source_evidence(tamper: str) -> None:
    payload = _v2_report().model_dump(mode="json")
    if tamper in {"text", "provenance"}:
        for candidate in (
            payload["candidates"][0],
            payload["chunks"][0]["candidates"][0],
        ):
            evidence = candidate["evidence"][0]
            if tamper == "text":
                evidence["text"] = "Подменённый текст"
            else:
                evidence["provenance"]["locator"] = "tampered locator"
    else:
        for item in (
            payload["item_candidates"][0],
            payload["chunks"][0]["item_candidates"][0],
        ):
            item["item_name"]["evidence"][0]["provenance"]["locator"] = "tampered item locator"
    payload["evidence_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "evidence_sha256"}
    )
    forged = validate_ai_requirement_report(payload)

    with pytest.raises(ValueError, match="differs from stored extraction"):
        _snapshot(forged)


def test_snapshot_rejects_mismatched_source_and_extraction() -> None:
    report = _v2_report()
    with pytest.raises(ValueError, match="source identity"):
        build_ai_requirement_run_snapshot(
            company_id="other-company",
            run_id="run-1",
            source_document_id="doc-1",
            source_sha256="b" * 64,
            extraction=_extraction(),
            report=report,
            submitted_by="operator-1",
            submitted_at=NOW,
        )
    changed_block = _block("changed", "paragraph 1")
    changed = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(changed_block,),
        reasons=(),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=len(changed_block.text),
    )
    with pytest.raises(ValueError, match="extraction digest"):
        build_ai_requirement_run_snapshot(
            company_id="company-a",
            run_id="run-1",
            source_document_id="doc-1",
            source_sha256="b" * 64,
            extraction=changed,
            report=report,
            submitted_by="operator-1",
            submitted_at=NOW,
        )


@pytest.mark.parametrize("tamper", ["response_digest", "provider_model"])
def test_snapshot_rechecks_provider_response_envelope(tamper: str) -> None:
    payload = _v2_report().model_dump(mode="json")
    chunk = payload["chunks"][0]
    if tamper == "response_digest":
        chunk["response_sha256"] = "0" * 64
        expected_message = "response digest"
    else:
        chunk["provider_model"] = "untrusted/other-model"
        expected_message = "provider model"
    payload["evidence_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "evidence_sha256"}
    )
    forged = validate_ai_requirement_report(payload)

    with pytest.raises(ValueError, match=expected_message):
        _snapshot(forged)


def test_snapshot_rejects_non_native_extraction_even_when_report_is_rehashed() -> None:
    native = _extraction()
    ocr_blocks = tuple(
        block.model_copy(
            update={"provenance": block.provenance.model_copy(update={"extractor": Extractor.OCR})}
        )
        for block in native.blocks
    )
    ocr = native.model_copy(update={"blocks": ocr_blocks})
    payload = _v2_report().model_dump(mode="json")
    payload["extraction_sha256"] = canonical_json_sha256(ocr)
    for candidate in (
        *payload["candidates"],
        *payload["chunks"][0]["candidates"],
    ):
        for evidence in candidate["evidence"]:
            evidence["provenance"]["extractor"] = Extractor.OCR.value
    for item in (
        *payload["item_candidates"],
        *payload["chunks"][0]["item_candidates"],
    ):
        claims = [item["item_name"], *item["okpd2_codes"], *item["ktru_codes"]]
        if item["unit"] is not None:
            claims.append(item["unit"])
        if item["quantity"] is not None:
            claims.append(item["quantity"])
        for claim in claims:
            for evidence in claim["evidence"]:
                evidence["provenance"]["extractor"] = Extractor.OCR.value
    payload["evidence_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "evidence_sha256"}
    )
    forged = validate_ai_requirement_report(payload)

    with pytest.raises(ValueError, match="complete native"):
        build_ai_requirement_run_snapshot(
            company_id="company-a",
            run_id="run-1",
            source_document_id="doc-1",
            source_sha256="b" * 64,
            extraction=ocr,
            report=forged,
            submitted_by="operator-1",
            submitted_at=NOW,
        )


def _decisions(
    snapshot: AiRequirementRunSnapshot,
) -> tuple[AiRequirementCandidateDecision, ...]:
    decisions = [
        AiRequirementCandidateDecision(
            candidate_kind=CandidateKind.REQUIREMENT,
            candidate_id=candidate.candidate_id,
            disposition=CandidateDisposition.ACCEPTED,
            reason="evidence checked",
        )
        for candidate in snapshot.report.candidates
    ]
    if isinstance(snapshot.report, AiRequirementAnalysisReportV2):
        decisions.extend(
            AiRequirementCandidateDecision(
                candidate_kind=CandidateKind.PROCUREMENT_ITEM,
                candidate_id=candidate.candidate_id,
                disposition=CandidateDisposition.ACCEPTED,
                reason="field claims checked",
            )
            for candidate in snapshot.report.item_candidates
        )
    return tuple(decisions)


def test_terminal_review_requires_every_exact_candidate_once_and_independent_reviewer() -> None:
    snapshot = _snapshot(_v2_report())
    decisions = _decisions(snapshot)
    with pytest.raises(ValueError, match="every exact candidate"):
        build_ai_requirement_review_decision(
            snapshot,
            evidence_sha256=snapshot.evidence_sha256,
            candidate_decisions=decisions[:-1],
            reviewed_by="reviewer-1",
            reviewed_at=NOW,
        )
    with pytest.raises(ValueError, match="only once"):
        build_ai_requirement_review_decision(
            snapshot,
            evidence_sha256=snapshot.evidence_sha256,
            candidate_decisions=(*decisions, decisions[0]),
            reviewed_by="reviewer-1",
            reviewed_at=NOW,
        )
    unknown = decisions[1].model_copy(update={"candidate_id": "ai-item-0000000000000000"})
    with pytest.raises(ValueError, match="every exact candidate"):
        build_ai_requirement_review_decision(
            snapshot,
            evidence_sha256=snapshot.evidence_sha256,
            candidate_decisions=(decisions[0], unknown),
            reviewed_by="reviewer-1",
            reviewed_at=NOW,
        )
    with pytest.raises(ValueError, match="own run"):
        build_ai_requirement_review_decision(
            snapshot,
            evidence_sha256=snapshot.evidence_sha256,
            candidate_decisions=decisions,
            reviewed_by="operator-1",
            reviewed_at=NOW,
        )


def test_accepted_review_remains_unknown_and_has_no_executable_conversion() -> None:
    snapshot = _snapshot(_v2_report())
    decision = build_ai_requirement_review_decision(
        snapshot,
        evidence_sha256=snapshot.evidence_sha256,
        candidate_decisions=_decisions(snapshot),
        reviewed_by="reviewer-1",
        reviewed_at=NOW,
    )
    record = AiRequirementReviewRecord(snapshot=snapshot, decision=decision)

    assert all(
        item.disposition is CandidateDisposition.ACCEPTED for item in decision.candidate_decisions
    )
    assert decision.completeness_status is CompletenessStatus.UNKNOWN
    assert record.snapshot.report.completeness_status is CompletenessStatus.UNKNOWN
    assert not hasattr(record, "requirements")
    assert not hasattr(record, "line_items")


def test_terminal_review_rejects_incomplete_report_but_allows_empty_complete_report() -> None:
    incomplete = analyze_requirements_with_model(
        _extraction(),
        company_id="company-a",
        source_sha256="b" * 64,
        authorization_reference="approved import",
        client=_RawClient("{}"),
        created_at=NOW,
    )
    incomplete_snapshot = _snapshot(incomplete)
    with pytest.raises(ValueError, match="COMPLETE"):
        build_ai_requirement_review_decision(
            incomplete_snapshot,
            evidence_sha256=incomplete_snapshot.evidence_sha256,
            candidate_decisions=(),
            reviewed_by="reviewer-1",
            reviewed_at=NOW,
        )

    empty = analyze_requirements_with_model(
        _extraction(),
        company_id="company-a",
        source_sha256="b" * 64,
        authorization_reference="approved import",
        client=_RawClient(
            json.dumps(
                {
                    "items": [],
                    "requirements": [],
                    "unresolved_block_ids": [],
                    "document_notes": [],
                }
            )
        ),
        created_at=NOW,
    )
    empty_snapshot = _snapshot(empty)
    decision = build_ai_requirement_review_decision(
        empty_snapshot,
        evidence_sha256=empty_snapshot.evidence_sha256,
        candidate_decisions=(),
        reviewed_by="reviewer-1",
        reviewed_at=NOW,
    )
    assert decision.candidate_decisions == ()
    assert decision.completeness_status is CompletenessStatus.UNKNOWN
