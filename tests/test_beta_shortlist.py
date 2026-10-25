from decimal import Decimal
from types import SimpleNamespace

import pytest

from procurement.domain.company_profile_snapshot import (
    ProfileFactInput,
    ProfileSaveCommand,
    new_snapshot,
)
from procurement.storage import beta_shortlist as module
from procurement.storage.beta_quote import BetaQuoteRef, BetaQuoteReport
from procurement.storage.beta_shortlist import BetaShortlistRequest, shortlist
from test_beta_quote import NOW, calculate, quote


def setup(monkeypatch, *, min_margin=None):
    changes = {
        "geography.all_russia": ProfileFactInput(knowledge="KNOWN", value=True),
        "supplied_goods": ProfileFactInput(knowledge="KNOWN", value=("Бумага",)),
    }
    if min_margin is not None:
        changes["finance.min_margin"] = ProfileFactInput(knowledge="KNOWN", value=min_margin)
    snapshot = new_snapshot(
        "tenant-a",
        "operator",
        ProfileSaveCommand(
            expected_version=0,
            changes=changes,
        ),
        None,
        "audit-1",
    )
    monkeypatch.setattr(
        module,
        "read_selection",
        lambda *args: SimpleNamespace(
            profile_ref=SimpleNamespace(version=1, snapshot_sha256=snapshot.snapshot_sha256)
        ),
    )
    monkeypatch.setattr(module, "read_profile", lambda *args: snapshot)
    monkeypatch.setattr(
        module, "read_navigation", lambda *args: SimpleNamespace(delivery_regions=())
    )

    def read(storage, company, ref, **kwargs):
        cost = Decimal(10000) + Decimal(ref.notice.purchase_number[-2:]) * 100
        return BetaQuoteReport(
            ref=ref,
            record_id=ref.notice.purchase_number + str(ref.lot_index),
            input=quote(amount_ex_vat=cost),
            calculation=calculate(quote(amount_ex_vat=cost)),
            source_status="CHECKED",
        )

    monkeypatch.setattr(module, "quote_report", read)


def ref(index, lot=None):
    return BetaQuoteRef.model_validate(
        {
            "notice": {
                "law": "223" if lot else "44",
                "purchase_number": str(index).zfill(11 if lot else 19),
                "version_number": 1,
                "notice_xml_sha256": "a" * 64,
            },
            "lot_index": lot,
        }
    )


def test_financial_order_is_bounded_and_unknown_gates_do_not_become_pass(monkeypatch):
    setup(monkeypatch)
    result = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(notices=tuple(ref(i) for i in range(10, 0, -1))),
        actor="operator",
        now=NOW,
    )
    assert len(result.financial_order) == 5
    assert result.financial_order[0] == str(1).zfill(19) + "None"
    assert all(row.profile_status == "UNKNOWN" for row in result.rows)
    assert result.eligibility == "UNKNOWN"


def test_lots_of_one_purchase_cannot_fill_multiple_shortlist_positions(monkeypatch):
    setup(monkeypatch)
    result = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(notices=(ref(1, 1), ref(1, 2), ref(2, 1))),
        actor="operator",
        now=NOW,
    )
    assert len(result.financial_order) == 2


def test_duplicate_source_identity_is_rejected(monkeypatch):
    setup(monkeypatch)
    with pytest.raises(ValueError, match="DUPLICATE_SHORTLIST_NOTICE"):
        shortlist(
            object(),
            "tenant-a",
            BetaShortlistRequest(notices=(ref(1), ref(1))),
            actor="operator",
            now=NOW,
        )


def test_unknown_delivery_region_is_excluded_without_claiming_profile_fail(monkeypatch):
    setup(monkeypatch)
    result = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(notices=(ref(1),), region="Moscow"),
        actor="operator",
        now=NOW,
    )
    assert not result.financial_order
    assert result.rows[0].profile_status == "UNKNOWN"
    assert "SELECTED_DELIVERY_REGION_NOT_CONFIRMED" in result.rows[0].reasons


def test_financial_loss_without_known_profile_rules_is_not_a_profile_fail(monkeypatch):
    setup(monkeypatch)

    def read(storage, company, reference, **kwargs):
        data = quote(amount_ex_vat="100000")
        return BetaQuoteReport(
            ref=reference,
            record_id="synthetic-loss",
            input=data,
            calculation=calculate(data),
            source_status="CHECKED",
        )

    monkeypatch.setattr(module, "quote_report", read)
    result = shortlist(
        object(), "tenant-a", BetaShortlistRequest(notices=(ref(1),)), actor="operator", now=NOW
    )
    assert not result.financial_order
    assert result.rows[0].profile_status == "UNKNOWN"
    assert "CONSERVATIVE_NOT_PROFITABLE" in result.rows[0].reasons


@pytest.mark.parametrize(
    ("cost", "min_margin", "failed"),
    [
        ("85004", "0.15", True),
        ("85000", "0.15", False),
        ("84999.99", "0.15", False),
        ("85004", None, False),
    ],
)
def test_profile_min_margin_uses_exact_profit_and_revenue(monkeypatch, cost, min_margin, failed):
    setup(monkeypatch, min_margin=min_margin)
    data = quote(
        amount_ex_vat=cost,
        output_vat_rate="0",
        realistic_discount="0",
        conservative_discount="0",
        conservative_cost_growth="0",
    )
    calculation = calculate(data, nmck_gross=Decimal("100000"))
    realistic = next(s for s in calculation.scenarios if s.kind == "realistic")
    assert realistic.revenue_net == Decimal("100000")
    assert realistic.profit == Decimal("100000") - Decimal(cost)
    # All three nearby values have the same displayed margin.
    assert realistic.margin == Decimal("0.1500")
    monkeypatch.setattr(
        module,
        "quote_report",
        lambda storage, company, reference, **kwargs: BetaQuoteReport(
            ref=reference,
            record_id="synthetic-margin",
            input=data,
            calculation=calculation,
            source_status="CHECKED",
        ),
    )

    result = shortlist(
        object(), "tenant-a", BetaShortlistRequest(notices=(ref(1),)), actor="operator", now=NOW
    )

    assert result.rows[0].profile_status == ("FAIL" if failed else "UNKNOWN")
    assert ("PROFILE_MIN_MARGIN_FAIL" in result.rows[0].reasons) is failed
    assert result.financial_order == (() if failed else ("synthetic-margin",))
    assert result.eligibility == "UNKNOWN"
    if min_margin is None:
        assert "PROFILE_MIN_MARGIN_UNKNOWN" in result.rows[0].reasons
