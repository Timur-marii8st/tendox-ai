"""Global order must find rows outside the legacy page and bind every filter."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from procurement.storage.eis_global_price import GlobalPriceCollector, GlobalPriceOptions
from procurement.storage.eis_search_pagination import SearchPageError

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def test_global_top_and_continuation_are_bounded_exact_and_cross_law():
    options = GlobalPriceOptions(query="бумага", law="all")

    def collect(cursor=None):
        c = GlobalPriceCollector("tenant", options, now=NOW, cursor=cursor, limit=37)
        for i in range(205):
            law = "44" if i % 2 else "223"
            c.observe(
                law,
                f"{i:019d}" if law == "44" else f"{i:011d}",
                False,
                Decimal(i) + Decimal("0.000000000000000001"),
                {"i": i},
                i,
            )
            assert len(c.leaders) <= 37
        return c.finish()

    first, token, _ = collect()
    assert first == list(range(204, 167, -1))
    all_rows = first[:]
    while token:
        rows, token, _ = collect(token)
        all_rows.extend(rows)
    assert all_rows == list(range(204, -1, -1))


def test_blocked_and_unknown_prices_never_outrank_confirmed_unblocked():
    c = GlobalPriceCollector(
        "tenant", GlobalPriceOptions(query="бумага"), now=NOW, cursor=None, limit=100
    )
    for number, blocked, price in [
        ("1", True, Decimal("999999")),
        ("2", False, None),
        ("3", False, Decimal("1")),
        ("4", False, Decimal("1.000000000000000001")),
    ]:
        c.observe("44", number.zfill(19), blocked, price, {"n": number}, number)
    assert c.finish()[0] == ["4", "3", "2", "1"]


@pytest.mark.parametrize(
    "changed",
    [
        {"law": "44"},
        {"delivery_region": "Москва"},
        {"include_unknown_region": True},
        {"query": "мыло"},
    ],
)
def test_cursor_cannot_cross_filters(changed):
    c = GlobalPriceCollector(
        "tenant", GlobalPriceOptions(query="бумага"), now=NOW, cursor=None, limit=1
    )
    for i in range(2):
        c.observe("44", str(i).zfill(19), False, Decimal(i), {"i": i}, i)
    token = c.finish()[1]
    with pytest.raises(SearchPageError, match="INVALID"):
        GlobalPriceCollector(
            "tenant",
            GlobalPriceOptions(query="бумага").model_copy(update=changed),
            now=NOW,
            cursor=token,
            limit=1,
        )


def test_huge_decimal_ranking_does_not_round_under_default_context():
    c = GlobalPriceCollector(
        "tenant", GlobalPriceOptions(query="бумага"), now=NOW, cursor=None, limit=100
    )
    c.observe(
        "44", "0".zfill(19), False, Decimal("999999999999999999999999999999.00000001"), {}, "low"
    )
    c.observe(
        "44", "1".zfill(19), False, Decimal("999999999999999999999999999999.00000002"), {}, "high"
    )
    assert c.finish()[0] == ["high", "low"]


def test_late_evidence_and_tenant_change_invalidate_global_cursor():
    opts = GlobalPriceOptions(query="бумага")

    def collect(changed=False, cursor=None):
        c = GlobalPriceCollector("tenant", opts, now=NOW, cursor=cursor, limit=1)
        for i in range(3):
            c.observe("44", str(i).zfill(19), False, Decimal(i), {"i": i, "hold": changed}, i)
        return c.finish()

    token = collect()[1]
    with pytest.raises(SearchPageError, match="CHANGED"):
        collect(True, token)
    with pytest.raises(SearchPageError, match="INVALID"):
        GlobalPriceCollector("other-tenant", opts, now=NOW, cursor=token, limit=1)


@pytest.mark.parametrize(
    "code,numeric,expected",
    [("RUB", "643", Decimal("100.25")), ("RUR", "643", Decimal("100.25")), ("USD", "840", None)],
)
def test_only_source_rub_prices_are_comparable(code, numeric, expected):
    from procurement.sources.eis_223_archive import parse_notice223_xml
    from procurement.storage.eis_223_index import compare_notice223
    from procurement.storage.eis_global_price import source_price223
    from test_eis_223_archive import xml

    notice = parse_notice223_xml(xml(code=code, numeric=numeric), source_member="test.xml")
    lead = compare_notice223(
        notice,
        "бумага",
        now=NOW,
        source_window="source",
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )
    assert lead is not None and source_price223(lead) == expected
