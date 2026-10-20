"""Materialize a new case version from one exact reviewed-offer economics package."""

from __future__ import annotations

from procurement.documents.server_offer_economics import ServerOfferEconomicsRecord
from procurement.documents.server_offer_review import ServerOfferEvidenceKind
from procurement.domain.cases import (
    CaseAssessment,
    GateCheck,
    GateKind,
    ProcurementCase,
    case_input_digest,
)
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Provenance
from procurement.domain.quotes import Currency, Quote


def materialize_case_from_server_offer_economics(
    record: ServerOfferEconomicsRecord,
) -> ProcurementCase:
    """Build the next immutable version; unresolved non-technical gates remain absent."""
    package = record.package
    if package is None:
        raise ValueError("case materialization requires a complete economics package")
    source = record.evidence.case
    review = record.evidence.offer_review
    decision = review.decision
    assert decision is not None
    proposal = review.evidence.proposal
    if (
        package.case_version != source.version
        or package.case_input_sha256 != case_input_digest(source)
    ):
        raise ValueError("economics package does not match exact source case")
    terms = proposal.commercial_terms
    quote = Quote(
        quote_id=proposal.offer_id,
        version=1,
        company_id=source.company_id,
        tender_id=source.tender.tender_id,
        supplier_id=terms.supplier_id,
        amount_ex_vat=terms.amount_ex_vat,
        nds_rate=terms.nds_rate,
        currency=Currency.RUB,
        issued_at=terms.issued_at,
        valid_until=terms.valid_until,
        source=terms.provenance,
        covers_full_scope=terms.covers_full_scope,
        availability_terms=terms.availability_terms,
        delivery_terms=terms.delivery_terms,
        payment_terms=terms.payment_terms,
    )
    evidence: list[Provenance] = []
    for row in decision.requirement_decisions:
        for reference in row.evidence:
            item = (
                terms.provenance
                if reference.kind is ServerOfferEvidenceKind.COMMERCIAL_TERMS
                else proposal.bom_lines[(reference.bom_line_ordinal or 1) - 1].provenance
            )
            if item not in evidence:
                evidence.append(item)
    draft = source.model_copy(
        update={
            "version": source.version + 1,
            "selected_quote": quote,
            "scenarios": package.scenario_set,
            "assessment": None,
        }
    )
    technical = GateCheck(
        kind=GateKind.TECHNICAL,
        status=GateStatus.PASS,
        reason=f"exact server-offer review {decision.decision_sha256}",
        evidence=tuple(evidence),
    )
    assessment = CaseAssessment(
        reviewer_id=decision.reviewed_by,
        assessed_at=decision.reviewed_at,
        input_digest=case_input_digest(draft),
        checks=(technical,),
    )
    return ProcurementCase.model_validate(draft.model_copy(update={"assessment": assessment}))
