"""Exact identity searches use synthetic source facts, never title coincidence."""

from dataclasses import replace

import pytest

from procurement.sources.eis_223_archive import parse_notice223_xml
from procurement.sources.eis_index_search import compare_indexed_notices, exact_purchase_number
from procurement.storage.eis_223_index import compare_notice223
from test_eis_223_archive import xml
from test_eis_index_search import NOW, _notice


@pytest.mark.parametrize("number", ["32616445250", "32616445747", "00016445250"])
@pytest.mark.parametrize("padding", ["", " \t{}\n "])
def test_223_exact_number_independent_of_title_with_identity_evidence(number, padding):
    notice = parse_notice223_xml(
        xml().replace(b"32600000001", number.encode()), source_member="synthetic.xml"
    )
    query = padding.format(number) if padding else number
    lead = compare_notice223(
        notice,
        query,
        now=NOW,
        source_window="synthetic",
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )
    assert lead is not None
    assert lead.notice.purchase_number == number
    assert lead.match_quality == "STRONG"
    assert lead.matched_lot_ordinal is None
    assert lead.term_evidence[0].value_kind == "PURCHASE_NUMBER"
    assert lead.term_evidence[0].source_value == number
    assert lead.term_evidence[0].locator == notice.identity_provenance[0].locator
    assert lead.application_status == "UNKNOWN"


@pytest.mark.parametrize("number", ["0000000000000000001", "0848300054826000154"])
def test_44_exact_number_keeps_current_version_and_failure(number):
    older = _notice(number, "Поставка кранов шаровых")
    newer = replace(older, version_number=2, xml_sha256="2" * 64, deadline=NOW)
    lead = compare_indexed_notices((older, newer), f" {number} ", now=NOW).matched_notices[0]
    assert lead.snapshot.version_number == 2
    assert lead.application_status == "FAIL"
    assert lead.term_evidence[0].value_kind == "PURCHASE_NUMBER"
    assert lead.match_locator.endswith("/commonInfo/purchaseNumber")


def test_full_number_is_identity_even_if_another_title_contains_it():
    missing = "32616445747"
    notice = parse_notice223_xml(
        xml().replace("Поставка бумаги".encode(), missing.encode()), source_member="synthetic.xml"
    )
    assert (
        compare_notice223(
            notice,
            missing,
            now=NOW,
            source_window="synthetic",
            source_response_sha256="b" * 64,
            archive_sha256="c" * 64,
        )
        is None
    )
    assert not compare_indexed_notices(
        (_notice("0000000000000000001", "0848300054826000154"),),
        "0848300054826000154",
        now=NOW,
    ).matched_notices


def test_223_exact_number_retains_source_restrictions():
    from test_eis_223_general_archive import general_xml, parse

    notice = parse(general_xml(hide="true"))
    lead = compare_notice223(
        notice,
        notice.purchase_number,
        now=NOW,
        source_window="synthetic",
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )
    assert lead is not None and lead.application_status == "FAIL"
    assert "SOURCE_PURCHASE_HIDDEN" in lead.reasons


@pytest.mark.parametrize("length", [11, 19, 20, 21, 22, 23])
def test_full_ascii_number_lengths_preserve_zeroes(length):
    number = "0" * (length - 1) + "1"
    assert exact_purchase_number(" \t" + number + "\n ") == number


@pytest.mark.parametrize(
    "query",
    [
        "1234567890",
        "123456789012",
        "1" * 18,
        "1" * 24,
        "１２３４５６７８９０１",
        "32616 445250",
        "№32616445250",
    ],
)
def test_partial_or_decorated_number_keeps_text_contract(query):
    assert exact_purchase_number(query) is None
