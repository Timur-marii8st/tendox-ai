"""RFQ draft inputs remain Decimal-safe, manual and explicitly non-dispatching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from procurement.domain.manufacturer_review import LegalIdentity
from procurement.domain.manufacturer_rfq import (
    ManufacturerRfqCommand,
    RfqRegistrySnapshot,
    canonical_quantity,
    render_rfq_text,
)

NOW = datetime.now(UTC)


def command(**changes: object) -> ManufacturerRfqCommand:
    payload: dict[str, object] = {
        "command_id": "00000000-0000-0000-0000-000000000001",
        "run_id": "00000000-0000-0000-0000-000000000002",
        "record_id": "6582fb75a4a4b05007bb2d05",
        "proposal_id": "00000000-0000-0000-0000-000000000003",
        "decision_id": "00000000-0000-0000-0000-000000000004",
        "quantity": "100.00",
        "unit_raw": "шт.",
        "quantity_basis_raw": "Количество введено оператором для запроса",
        "requirements": ["Новый товар", "Гарантия не менее 12 месяцев"],
        "delivery_address_raw": "Москва, тестовый адрес",
        "desired_delivery_raw": "30 календарных дней",
        "reply_due_at": (NOW + timedelta(days=7)).isoformat(),
    }
    payload.update(changes)
    return ManufacturerRfqCommand.model_validate(payload)


@pytest.mark.parametrize(
    "value",
    [0, True, 1.5, "NaN", "Infinity", "0", "-1", "1e1000000", "1e-1000000"],
)
def test_quantity_rejects_non_string_nonfinite_nonpositive_or_expanding(value: object) -> None:
    with pytest.raises((ValidationError, ValueError)):
        command(quantity=value)


def test_quantity_preserves_more_than_decimal_context_precision() -> None:
    value = "123456789012345678901234567890.1000"
    assert canonical_quantity(value) == "123456789012345678901234567890.1"
    assert command(quantity=value).quantity == value


def test_past_aware_deadline_is_parseable_for_exact_historical_replay() -> None:
    result = command(reply_due_at=(NOW - timedelta(days=1)).isoformat())
    assert result.reply_due_at < NOW
    with pytest.raises(ValidationError):
        command(reply_due_at="2026-10-06T12:00:00")


def test_render_contains_required_request_and_no_dispatch_claim() -> None:
    text = render_rfq_text(
        LegalIdentity(
            legal_name="Factory LLC", country_code="RU", identifier_scheme="INN",
            registration_id="123",
        ),
        RfqRegistrySnapshot(
            record_id="6582fb75a4a4b05007bb2d05", registry_number="1",
            product_name="Насос", source_manufacturer_name="Factory",
            record_url="https://example.test/record", document_expires_on="2027-01-01",
        ),
        command(),
    )
    for phrase in (
        "Черновик запроса коммерческого предложения", "цену за единицу", "НДС",
        "MOQ", "наличие", "срок производства", "упаковку", "условия оплаты",
        "доставки", "гарантию", "срок действия коммерческого предложения",
        "DRAFT_NO_DISPATCH",
    ):
        assert phrase in text
    assert "не являются полностью проверенным ТЗ" in text
