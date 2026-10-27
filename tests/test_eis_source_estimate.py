"""Synthetic source-bound economics, exact inputs, blockers and tenant routing."""

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module

import pytest
from pydantic import ValidationError

from procurement.access import AccessRole
from procurement.storage import eis_source_estimate as source
from test_eis_comparison import two_bridges
from test_eis_document_jobs_api import send
from test_eis_mixed_comparison import request as mixed_request
from test_eis_mixed_comparison import row223

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def request(law="44"):
    return source.SourceEstimateRequest.model_validate(
        {
            "notice": mixed_request().notices[0 if law == "44" else 1].model_dump(),
            "lot_index": None if law == "44" else 1,
            "costs": {
                "goods": "50",
                "expenses": "10",
                "vat_rate": "0.20",
                "realistic_discount": "0.05",
                "conservative_discount": "0.10",
                "conservative_cost_growth": "0.10",
                "basis": "Синтетическая проверка, не КП",
                "costs_complete_ack": True,
            },
        }
    )


def compute(monkeypatch, payload=None, *, bridge=None, lotrow=None, actor="operator"):
    transactions = []
    conn = object()

    class Storage:
        @contextmanager
        def transaction(self, company, *, consistent_read):
            transactions.append((company, consistent_read))
            yield conn

    def read44(connection, company, ref, *, now, include_competition_criteria):
        assert connection is conn and company == "tenant-a" and now == NOW
        assert include_competition_criteria is False
        return bridge or two_bridges()[0]

    def read223(connection, company, ref, *, now):
        assert connection is conn and company == "tenant-a" and now == NOW
        return lotrow or row223()

    monkeypatch.setattr(source, "read_eis_evidence_bridge", read44)
    monkeypatch.setattr(source, "read_comparison223_row", read223)
    result = source.get_source_estimate(
        Storage(), "tenant-a", payload or request(), actor_id=actor, now=NOW
    )
    assert transactions == [("tenant-a", True)]
    return result


@pytest.mark.parametrize(
    "change",
    [
        "44lot",
        "223no_lot",
        "bool_lot",
        "zero_lot",
        "float_money",
        "float_tax",
        "bool_ack",
        "tenant",
        "price",
        "blank_basis",
        "discount_order",
    ],
)
def test_exact_input_contract(change):
    body = request("223" if change in {"223no_lot", "bool_lot", "zero_lot"} else "44").model_dump(
        mode="json"
    )
    if change == "44lot":
        body["lot_index"] = 1
    elif change == "223no_lot":
        body.pop("lot_index")
    elif change == "bool_lot":
        body["lot_index"] = True
    elif change == "zero_lot":
        body["lot_index"] = 0
    elif change == "float_money":
        body["costs"]["goods"] = 50.5
    elif change == "float_tax":
        body["costs"]["vat_rate"] = 0.2
    elif change == "bool_ack":
        body["costs"]["costs_complete_ack"] = "true"
    elif change == "tenant":
        body["company_id"] = "other"
    elif change == "price":
        body["ceiling_rub"] = "999999"
    elif change == "blank_basis":
        body["costs"]["basis"] = " "
    else:
        body["costs"]["conservative_discount"] = "0.01"
    with pytest.raises(ValidationError):
        source.SourceEstimateRequest.model_validate(body)


def test_three_exact_scenarios_source_and_manual_provenance(monkeypatch):
    result = compute(monkeypatch, request("223"))
    assert result.ceiling_rub == Decimal("100.25")
    assert result.ceiling.provenance.locator.endswith("/t:initialSum")
    assert [s.kind for s in result.estimate.scenarios] == ["base", "realistic", "conservative"]
    assert [s.profit for s in result.estimate.scenarios] == [
        Decimal("23.54"),
        Decimal("19.37"),
        Decimal("9.19"),
    ]
    assert result.estimate.recommendation == "needs_analysis"
    assert result.quote_status == result.eligibility == result.profit_order_status == "UNKNOWN"
    assert result.manual_provenance.document_id.endswith(result.input_sha256)
    assert source.SourceEstimateResult.model_validate(result.model_dump(mode="json")) == result
    assert not any("НМЦК" in r for r in result.estimate.reasons)
    assert compute(monkeypatch, request("223"), actor="other").input_sha256 != result.input_sha256


@pytest.mark.parametrize(
    "reason", ["NOTICE_VERSION_STALE", "DEADLINE_EXPIRED", "PROCEDURE_BLOCKED"]
)
def test_high_budget_never_overrides44_source_blocker(monkeypatch, reason):
    bridge = two_bridges()[0]
    if reason == "NOTICE_VERSION_STALE":
        bridge = bridge.model_copy(
            update={"collection": bridge.collection.model_copy(update={"version_status": "STALE"})}
        )
    else:
        bridge = bridge.model_copy(
            update={"application_status": "FAIL", "application_reasons": (reason,)}
        )
    result = compute(monkeypatch, bridge=bridge)
    assert result.estimate.status == "BLOCKED" and not result.estimate.scenarios
    assert reason in result.blocking_reasons


def test223_selected_lot_not_sum_or_quantity_and_cancelled(monkeypatch):
    row = row223()
    lot = row.notice.lots[0]
    other = lot.model_copy(
        update={
            "initial_sum": lot.initial_sum.model_copy(update={"value": Decimal("240")}),
            "initial_sum_rub": Decimal("240"),
        }
    )
    row = row.model_copy(update={"notice": row.notice.model_copy(update={"lots": (lot, other)})})
    payload = request("223").model_copy(update={"lot_index": 2})
    result = compute(monkeypatch, payload, lotrow=row)
    assert result.ceiling_rub == Decimal("240") and result.estimate.scenarios[0].profit == Decimal(
        "140"
    )
    cancelled = other.model_copy(
        update={"cancelled_raw": other.cancelled_raw.model_copy(update={"value": "true"})}
    )
    blocked = compute(
        monkeypatch,
        payload,
        lotrow=row.model_copy(
            update={"notice": row.notice.model_copy(update={"lots": (lot, cancelled)})}
        ),
    )
    assert (
        blocked.blocking_reasons == ("SELECTED_LOT_CANCELLED",) and not blocked.estimate.scenarios
    )
    with pytest.raises(source.SourceLotError):
        compute(monkeypatch, payload.model_copy(update={"lot_index": 3}), lotrow=row)


def test_unknown_currency_and_unacknowledged_costs_remain_unknown(monkeypatch):
    row = row223()
    lot = row.notice.lots[0]
    foreign = lot.model_copy(
        update={
            "currency": lot.currency.model_copy(update={"value": "USD"}),
            "initial_sum_rub": None,
        }
    )
    result = compute(
        monkeypatch,
        request("223"),
        lotrow=row.model_copy(
            update={"notice": row.notice.model_copy(update={"lots": (foreign,)})}
        ),
    )
    assert result.ceiling.value == Decimal("100.25") and result.ceiling_rub is None
    assert result.estimate.status == "UNKNOWN" and not result.estimate.scenarios
    payload = request("223")
    result = compute(
        monkeypatch,
        payload.model_copy(
            update={"costs": payload.costs.model_copy(update={"costs_complete_ack": False})}
        ),
    )
    assert result.estimate.status == "UNKNOWN" and not result.estimate.scenarios


def test_naive_clock_rejected_before_storage():
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        source.get_source_estimate(
            None, "tenant-a", request(), actor_id="operator", now=NOW.replace(tzinfo=None)
        )


def test_api_operator_identity_and_no_store(monkeypatch):
    result = compute(monkeypatch, request("223"))
    calls = []

    def read(storage, company, payload, *, actor_id):
        calls.append((company, actor_id, payload))
        return result

    monkeypatch.setattr(import_module("procurement.api.app"), "get_source_estimate", read)
    path = "/v1/tender-discovery/eis-source-estimate"
    body = request("223").model_dump(mode="json")
    assert send("POST", path, body=body, token="invalid").status_code == 401
    assert send("POST", path, body=body, role=AccessRole.AUDITOR).status_code == 403
    response = send("POST", path, body=body)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", "operator", request("223"))]
    assert send("POST", path, body={**body, "actor_id": "other"}).status_code == 422


@pytest.mark.parametrize(
    "error,status",
    [
        (LookupError("secret"), 404),
        (ValueError("secret"), 409),
        (source.SourceLotError("secret"), 422),
    ],
)
def test_api_safe_errors(monkeypatch, error, status):
    def read(*args, **kwargs):
        raise error

    monkeypatch.setattr(import_module("procurement.api.app"), "get_source_estimate", read)
    response = send(
        "POST", "/v1/tender-discovery/eis-source-estimate", body=request().model_dump(mode="json")
    )
    assert response.status_code == status and "secret" not in response.text


@pytest.mark.parametrize("count,truncated", [(1, False), (2, False), (1, True)])
def test_unit_denominator_requires_complete_single_source_position(monkeypatch, count, truncated):
    from dataclasses import replace

    from procurement.sources.eis_position_evidence import positions44
    from test_eis_position_evidence import notice44

    bridge = two_bridges()[0]
    positions = positions44(
        replace(notice44(), xml_sha256=bridge.notice.notice_xml_sha256)
    ).model_copy(
        update={
            "positions_total": count,
            "positions_truncated": truncated,
        }
    )
    bridge = bridge.model_copy(update={"position_set": positions})
    result = compute(monkeypatch, bridge=bridge)
    if count == 1 and not truncated:
        assert result.unit_quantity == positions.positions[0].quantity
        assert result.quantity_unit == positions.positions[0].unit
    else:
        assert result.unit_quantity is result.quantity_unit is None


@pytest.mark.parametrize("count", [0, 1, 2])
def test_223_quantity_belongs_to_selected_lot_not_other_lots(monkeypatch, count):
    row = row223()
    lot = row.notice.lots[0]
    changed = lot.model_copy(update={"items": lot.items * count})
    row = row.model_copy(update={"notice": row.notice.model_copy(update={"lots": (changed, lot)})})
    result = compute(monkeypatch, request("223"), lotrow=row)
    if count == 1:
        assert result.unit_quantity == lot.items[0].quantity
        assert result.quantity_unit == lot.items[0].unit_name
    else:
        assert result.unit_quantity is result.quantity_unit is None
