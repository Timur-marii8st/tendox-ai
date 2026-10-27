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


def test_unit_profit_reverses_total_profit_and_keeps_units_separate(monkeypatch):
    setup(monkeypatch)
    from procurement.domain.provenance import Extractor, Provenance
    from procurement.sources.eis_223_archive import DecimalFact, TextFact

    def read(storage, company, reference, **kwargs):
        index = int(reference.notice.purchase_number)
        data = quote(amount_ex_vat="10000" if index == 1 else "20000")
        source = Provenance(
            document_id="a" * 64, locator="/position/quantity", extractor=Extractor.API
        )
        return BetaQuoteReport(
            ref=reference,
            record_id=f"unit-{index}",
            input=data,
            calculation=calculate(data),
            source_status="CHECKED",
            unit_quantity=DecimalFact(
                value=Decimal("1000" if index == 1 else "10"), raw=None, provenance=source
            ),
            quantity_unit=TextFact(value="шт" if index < 3 else "кг", raw=None, provenance=source),
        )

    monkeypatch.setattr(module, "quote_report", read)
    request = dict(notices=(ref(1), ref(2), ref(3)))
    total = shortlist(
        object(), "tenant-a", BetaShortlistRequest(**request), actor="operator", now=NOW
    )
    assert total.financial_order[0] == "unit-1"
    unit = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(**request, ranking="UNIT_PROFIT"),
        actor="operator",
        now=NOW,
    )
    assert unit.financial_order == ()  # No fictitious common rank for kilograms and pieces.
    groups = {g.unit: g.record_ids for g in unit.unit_orders}
    assert groups == {"шт": ("unit-2", "unit-1"), "кг": ("unit-3",)}
    assert unit.rows[1].unit_profit > unit.rows[0].unit_profit
    assert unit.eligibility == "UNKNOWN"


def test_unit_profit_missing_source_denominator_is_unknown(monkeypatch):
    setup(monkeypatch)
    result = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(notices=(ref(1),), ranking="UNIT_PROFIT"),
        actor="operator",
        now=NOW,
    )
    assert result.financial_order == ()
    assert result.unit_orders == ()
    assert result.rows[0].unit_profit is None
    assert "UNIT_PROFIT_BASIS_UNKNOWN" in result.rows[0].reasons


@pytest.mark.parametrize(
    "quantity,unit,sha",
    [
        ("0", "шт", "a" * 64),
        (None, "шт", "a" * 64),
        ("10", " ", "a" * 64),
        ("10", "шт", "b" * 64),
    ],
)
def test_unit_profit_rejects_unknown_zero_or_unbound_source(monkeypatch, quantity, unit, sha):
    from procurement.domain.provenance import Extractor, Provenance
    from procurement.sources.eis_223_archive import DecimalFact, TextFact

    setup(monkeypatch)
    read = module.quote_report
    evidence = Provenance(document_id=sha, locator="/quantity", extractor=Extractor.API)

    def source(*args, **kwargs):
        return read(*args, **kwargs).model_copy(
            update={
                "unit_quantity": DecimalFact(value=quantity, raw=None, provenance=evidence),
                "quantity_unit": TextFact(value=unit, raw=None, provenance=evidence),
            }
        )

    monkeypatch.setattr(module, "quote_report", source)
    result = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(notices=(ref(1),), ranking="UNIT_PROFIT"),
        actor="operator",
        now=NOW,
    )
    assert result.unit_orders == ()
    assert result.rows[0].unit_profit is None
    assert result.eligibility == "UNKNOWN"


def test_shared_source_corpus_does_not_replace_private_quote_tenant(monkeypatch):
    setup(monkeypatch)
    read = module.quote_report
    calls = []

    def private_quote(storage, company, reference, **kwargs):
        calls.append((company, kwargs["source_company"]))
        return read(storage, company, reference, **kwargs)

    def public_navigation(storage, company, reference):
        assert company == "public-corpus"
        return SimpleNamespace(delivery_regions=())

    monkeypatch.setattr(module, "quote_report", private_quote)
    monkeypatch.setattr(module, "read_navigation", public_navigation)
    result = shortlist(
        object(),
        "tenant-a",
        BetaShortlistRequest(notices=(ref(1),)),
        actor="operator",
        now=NOW,
        source_company="public-corpus",
    )
    assert calls == [("tenant-a", "public-corpus")]
    assert result.financial_order
    assert result.profile.company_id == "tenant-a"
