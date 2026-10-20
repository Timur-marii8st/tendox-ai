from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.documents import (
    RequirementEntryDisposition,
    RequirementSetCoverageAssessment,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetRecord,
    ServerOfferBomLineInput,
    ServerOfferBomScopeAssessment,
    ServerOfferCommercialAssessment,
    ServerOfferCommercialTermsInput,
    ServerOfferEvidenceKind,
    ServerOfferEvidenceRef,
    ServerOfferPartKind,
    ServerOfferRequirementDecision,
    ServerOfferReviewDecision,
    ServerOfferReviewEvidence,
    ServerOfferReviewRecord,
    build_reviewed_requirement_set_decision,
    build_reviewed_requirement_set_proposal,
    build_server_offer_proposal,
    build_server_offer_review_decision,
    canonical_json_sha256,
)
from procurement.domain.compliance import Verdict
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


def evidence(
    *,
    valid_until: datetime = datetime(2026, 10, 20, tzinfo=UTC),
    complete: bool = True,
) -> ServerOfferReviewEvidence:
    provenance = Provenance(
        document_id="tz-1", locator="table 1 row 1", extractor=Extractor.MANUAL
    )
    proposal = build_reviewed_requirement_set_proposal(
        company_id="tenant-a",
        set_id="set-1",
        source_document_id="tz-1",
        source_document_sha256="a" * 64,
        declared_scope="all rows",
        expected_entry_count=1,
        entries=(
            ReviewedRequirementEntry(
                ordinal=1,
                raw_name="CPU",
                raw_value="16 cores",
                provenance=provenance,
                disposition=RequirementEntryDisposition.MANUAL_REVIEW_REQUIRED,
                review_note="manual",
            ),
        ),
        prepared_by="operator-r",
        prepared_at=NOW,
    )
    decision = build_reviewed_requirement_set_decision(
        proposal,
        coverage_assessment=RequirementSetCoverageAssessment.CONFIRMED,
        normalization_assessment=RequirementSetNormalizationAssessment.REVIEWED,
        status=Verdict.PASS,
        reason="complete",
        reviewed_by="requirement-reviewer",
        reviewed_at=NOW,
    )
    offer = build_server_offer_proposal(
        company_id="tenant-a",
        offer_id="offer-1",
        case_id="case-1",
        case_version=1,
        requirement_set_binding_id="binding-1",
        requirement_set_binding_sha256="b" * 64,
        sourcing_run_id="run-1",
        lead_id="lead-1",
        lead_product_name="Server",
        lead_product_url="https://example.com/server",
        lead_source_sha256="c" * 64,
        source_document_id="quote-1",
        source_document_sha256="d" * 64,
        bom_lines=(
            ServerOfferBomLineInput(
                ordinal=1,
                kind=ServerOfferPartKind.CPU,
                manufacturer="AMD",
                sku="EPYC",
                description="16-core CPU",
                quantity="1",
                unit="pcs",
                unit_price_ex_vat="100",
                line_total_ex_vat="100",
                source_locator="table 1 row 1",
            ),
        ),
        commercial_terms=ServerOfferCommercialTermsInput(
            quote_number="Q-1",
            supplier_id="supplier-1",
            supplier_name="Supplier",
            amount_ex_vat="100",
            nds_rate="0.20" if complete else None,
            issued_at=NOW,
            valid_until=valid_until,
            covers_full_scope=True if complete else None,
            availability_terms="stock" if complete else None,
            delivery_terms="10 days" if complete else None,
            payment_terms="postpay" if complete else None,
            source_locator="page 1 total",
        ),
        prepared_by="offer-operator",
        prepared_at=NOW,
    )
    return ServerOfferReviewEvidence(
        proposal=offer,
        requirement_set=ReviewedRequirementSetRecord(proposal=proposal, decision=decision),
    )


def row(
    status: Verdict = Verdict.PASS, *, ordinal: int = 1, bom: int = 1
) -> ServerOfferRequirementDecision:
    refs = () if status is Verdict.UNKNOWN else (
        ServerOfferEvidenceRef(kind=ServerOfferEvidenceKind.BOM_LINE, bom_line_ordinal=bom),
    )
    return ServerOfferRequirementDecision(
        requirement_ordinal=ordinal, status=status, reason="checked", evidence=refs
    )


def decide(
    source: ServerOfferReviewEvidence,
    *,
    requirement_decisions: tuple[ServerOfferRequirementDecision, ...] | None = None,
    bom_scope_assessment: ServerOfferBomScopeAssessment = (
        ServerOfferBomScopeAssessment.CONFIRMED_COMPLETE
    ),
    commercial_terms_assessment: ServerOfferCommercialAssessment = (
        ServerOfferCommercialAssessment.CONFIRMED
    ),
    reviewed_by: str = "offer-reviewer",
) -> ServerOfferReviewDecision:
    return build_server_offer_review_decision(
        source,
        requirement_decisions=(row(),) if requirement_decisions is None else requirement_decisions,
        bom_scope_assessment=bom_scope_assessment,
        commercial_terms_assessment=commercial_terms_assessment,
        reason="review complete",
        reviewed_by=reviewed_by,
        reviewed_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


def test_complete_exact_review_can_pass() -> None:
    result = decide(evidence())
    assert result.status is Verdict.PASS
    assert result.quote_gate_status is Verdict.PASS
    assert len(result.decision_sha256) == 64


def test_any_row_fail_or_incomplete_scope_blocks() -> None:
    assert decide(evidence(), requirement_decisions=(row(Verdict.FAIL),)).status is Verdict.FAIL
    assert (
        decide(
            evidence(),
            bom_scope_assessment=ServerOfferBomScopeAssessment.CONFIRMED_INCOMPLETE,
        ).status
        is Verdict.FAIL
    )


def test_unresolved_inputs_stay_unknown() -> None:
    assert (
        decide(evidence(), requirement_decisions=(row(Verdict.UNKNOWN),)).status
        is Verdict.UNKNOWN
    )
    assert decide(evidence(complete=False)).status is Verdict.UNKNOWN


def test_expired_quote_is_fail() -> None:
    result = decide(evidence(valid_until=datetime(2026, 9, 21, tzinfo=UTC)))
    assert result.status is Verdict.FAIL
    assert result.quote_gate_status is Verdict.FAIL


def test_review_requires_all_rows_existing_bom_and_independent_actor() -> None:
    with pytest.raises(ValueError, match="every requirement"):
        decide(evidence(), requirement_decisions=())
    with pytest.raises(ValueError, match="missing BOM"):
        decide(evidence(), requirement_decisions=(row(bom=2),))
    with pytest.raises(ValueError, match="must differ"):
        decide(evidence(), reviewed_by="offer-operator")


def test_known_row_requires_offer_evidence() -> None:
    with pytest.raises(ValidationError, match="requires offer evidence"):
        ServerOfferRequirementDecision(requirement_ordinal=1, status=Verdict.PASS, reason="checked")


def test_record_recomputes_server_status_instead_of_trusting_stored_json() -> None:
    source = evidence()
    valid = decide(source)
    payload = valid.model_dump(mode="json", exclude={"decision_sha256"})
    payload["status"] = "FAIL"
    forged = valid.model_validate(
        payload | {"decision_sha256": canonical_json_sha256(payload)}
    )
    with pytest.raises(ValidationError, match="does not match offer evidence"):
        ServerOfferReviewRecord(evidence=source, decision=forged)
