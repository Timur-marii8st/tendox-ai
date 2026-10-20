from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.documents import (
    ServerOfferBomLineInput,
    ServerOfferCommercialTermsInput,
    ServerOfferPartKind,
    build_server_offer_proposal,
)
from procurement.domain.compliance import Verdict

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


def line(ordinal: int, total: str | None = None) -> ServerOfferBomLineInput:
    return ServerOfferBomLineInput(
        ordinal=ordinal,
        kind=ServerOfferPartKind.CHASSIS if ordinal == 1 else ServerOfferPartKind.CPU,
        manufacturer="HPE",
        sku=f"P-{ordinal}",
        description=f"part {ordinal}",
        quantity="1",
        unit="шт",
        unit_price_ex_vat=total,
        line_total_ex_vat=total,
        source_locator=f"table 1 row {ordinal}",
    )


def terms(amount: str = "1200.00") -> ServerOfferCommercialTermsInput:
    return ServerOfferCommercialTermsInput(
        quote_number="Q-42",
        supplier_id="supplier-1",
        supplier_name="Поставщик",
        amount_ex_vat=amount,
        nds_rate="0.20",
        issued_at=NOW,
        valid_until=datetime(2026, 10, 20, 12, tzinfo=UTC),
        covers_full_scope=True,
        availability_terms="На складе",
        delivery_terms="10 рабочих дней",
        payment_terms="Оплата после поставки",
        source_locator="page 1 quote total",
    )


def proposal(*lines: ServerOfferBomLineInput, amount: str = "1200.00"):
    return build_server_offer_proposal(
        company_id="tenant-a",
        offer_id="offer-1",
        case_id="case-1",
        case_version=2,
        requirement_set_binding_id="binding-1",
        requirement_set_binding_sha256="a" * 64,
        sourcing_run_id="run-1",
        lead_id="lead-1",
        lead_product_name="HPE DL360 Gen12",
        lead_product_url="https://example.com/server",
        lead_source_sha256="b" * 64,
        source_document_id="quote-doc-1",
        source_document_sha256="c" * 64,
        bom_lines=lines,
        commercial_terms=terms(amount),
        prepared_by="operator-a",
        prepared_at=NOW,
    )


def test_builds_exact_pending_proposal_with_source_bound_evidence() -> None:
    result = proposal(line(1, "1000.00"), line(2, "200.00"))

    assert result.technical_status is Verdict.UNKNOWN
    assert result.review_status == "PENDING_REVIEW"
    assert result.commercial_terms.is_complete
    assert all(item.provenance.document_id == "quote-doc-1" for item in result.bom_lines)
    assert len(result.proposal_sha256) == 64


def test_rejects_non_contiguous_bom_and_mismatched_itemized_total() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        proposal(line(2))
    with pytest.raises(ValidationError, match="must equal quote amount"):
        proposal(line(1, "100.00"), amount="1200.00")
    bad_line = line(1, "100.00").model_dump(mode="python")
    bad_line["quantity"] = "2"
    with pytest.raises(ValidationError, match="multiplied by quantity"):
        ServerOfferBomLineInput.model_validate(bad_line)


def test_allows_lump_sum_quote_without_fake_line_prices() -> None:
    result = proposal(line(1), line(2))
    assert result.commercial_terms.amount_ex_vat == 1200
    assert all(item.line_total_ex_vat is None for item in result.bom_lines)


def test_quote_dates_require_timezone_and_forward_window() -> None:
    payload = terms().model_dump(mode="python")
    payload["valid_until"] = NOW
    with pytest.raises(ValidationError, match="after issued_at"):
        ServerOfferCommercialTermsInput.model_validate(payload)
