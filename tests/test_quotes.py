"""Критические неизвестные и неточные деньги не становятся подтверждённым КП."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from case_support import paper_case
from procurement.domain.quotes import Quote


@pytest.mark.parametrize("field", ["amount_ex_vat", "nds_rate"])
@pytest.mark.parametrize("value", [1.5, True, "NaN", Decimal("Infinity")])
def test_quote_rejects_inexact_or_nonfinite_money(field: str, value: object) -> None:
    quote = paper_case().selected_quote
    assert quote is not None
    payload = quote.model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError):
        Quote.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ["nds_rate", "covers_full_scope", "availability_terms", "delivery_terms", "payment_terms"],
)
def test_unknown_term_is_incomplete(field: str) -> None:
    quote = paper_case().selected_quote
    assert quote is not None
    payload = quote.model_dump(mode="python")
    payload[field] = None
    assert not Quote.model_validate(payload).is_complete


@pytest.mark.parametrize("field", ["issued_at", "valid_until"])
def test_quote_rejects_naive_times(field: str) -> None:
    quote = paper_case().selected_quote
    assert quote is not None
    payload = quote.model_dump(mode="python")
    payload[field] = payload[field].replace(tzinfo=None)
    with pytest.raises(ValidationError):
        Quote.model_validate(payload)


def test_invalid_quote_window_is_rejected() -> None:
    quote = paper_case().selected_quote
    assert quote is not None
    payload = quote.model_dump(mode="python")
    payload["valid_until"] = payload["issued_at"]
    with pytest.raises(ValidationError):
        Quote.model_validate(payload)


def test_currency_is_not_guessed() -> None:
    quote = paper_case().selected_quote
    assert quote is not None
    payload = quote.model_dump(mode="python")
    del payload["currency"]
    with pytest.raises(ValidationError):
        Quote.model_validate(payload)


def test_blank_terms_are_not_confirmation() -> None:
    quote = paper_case().selected_quote
    assert quote is not None
    payload = quote.model_dump(mode="python")
    payload["payment_terms"] = "   "
    with pytest.raises(ValidationError):
        Quote.model_validate(payload)
