"""Synthetic regression for explicit KESMBO by-number intake, never active-state inference."""

from dataclasses import replace
from datetime import date

import pytest

from procurement.sources.eis_223_archive import (
    SUPPORTED_DOCUMENT_TYPES,
    notice223_request,
    parse_notice223_xml,
)
from procurement.storage.eis_223_index import (
    bind_notice223_window,
    compare_notice223,
    preflight_notice223_window,
)
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import NOW, URL, responses, window

FAMILY = "purchaseNoticeKESMBO"
NUMBER = "32600000001"
KEY = f"getDocsIP/RI223/by-number/{NUMBER}/{FAMILY}"


def kesmbo_xml(*, version=1, number=NUMBER):
    raw = xml(
        extra="<p:guid>synthetic-purchase-guid</p:guid>"
        "<p:forSmallOrMiddle>true</p:forSmallOrMiddle>"
    )
    return (
        raw.replace(b"purchaseNoticeAESMBO", FAMILY.encode())
        .replace(b"32600000001", number.encode())
        .replace(b"<p:version>1</p:version>", f"<p:version>{version}</p:version>".encode())
        .replace(
            b"<t:ordinalNumber>1</t:ordinalNumber>",
            b"<t:guid>synthetic-lot-guid</t:guid><t:ordinalNumber>1</t:ordinalNumber>",
            1,
        )
    )


def targeted_window(raw=None):
    return window(zip_bytes([("kesmbo.xml", raw or kesmbo_xml())])).model_copy(
        update={"window_key": KEY}
    )


def test_actual_gap_shape_keeps_unknown_time_state_and_family_provenance():
    notice = parse_notice223_xml(kesmbo_xml(), source_member="kesmbo.xml", document_type=FAMILY)
    assert notice.document_type == FAMILY and notice.purchase_number == NUMBER
    assert notice.purchase_guid.value == "synthetic-purchase-guid"
    assert notice.for_small_or_middle_raw.value == "true"
    assert notice.lots[0].guid.value == "synthetic-lot-guid"
    assert notice.deadline.value is None and notice.deadline.status == "UNKNOWN"
    assert notice.application_status == "UNKNOWN"
    assert notice.title.provenance.locator.startswith(FAMILY + "/")
    assert notice.lots[0].initial_sum_rub is not None
    # V52 explicitly admits regular KESMBO; targeted identity guards still apply.
    assert FAMILY in SUPPORTED_DOCUMENT_TYPES
    request = notice223_request(
        "synthetic-token-123",
        "11111111-1111-4111-8111-111111111111",
        "50",
        date(2026, 10, 8),
        document_type=FAMILY,
    )
    assert b"<documentType223>purchaseNoticeKESMBO</documentType223>" in request


def test_number_binding_checks_full_set_and_all_records_without_fabricating_region_day():
    initial, prepared = responses()
    ready = bind_notice223_window(
        KEY, replace(initial, kind="BY_NUMBER"), prepared, {URL: targeted_window().archives[0]}
    )
    inspections, _ = preflight_notice223_window("tenant-a", ready)
    assert inspections[0].source_locator == KEY
    assert inspections[0].records[0].purchase_number == NUMBER
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        bind_notice223_window(KEY, initial, prepared, {URL: ready.archives[0]})
    with pytest.raises(ValueError, match="ARCHIVE_SET_MISMATCH"):
        bind_notice223_window(KEY, replace(initial, kind="BY_NUMBER"), prepared, {})


@pytest.mark.parametrize("number", ["32600000002", "32600000000"])
def test_other_number_in_full_archive_cannot_enter_target_checkpoint(number):
    with pytest.raises(ValueError, match="BY_NUMBER_PURCHASE_MISMATCH"):
        preflight_notice223_window("tenant-a", targeted_window(kesmbo_xml(number=number)))


def test_mixed_family_and_forged_day_selection_are_rejected():
    raw = zip_bytes([("kesmbo.xml", kesmbo_xml()), ("other.xml", xml())])
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_notice223_window("tenant-a", window(raw).model_copy(update={"window_key": KEY}))
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window(
            "tenant-a",
            targeted_window().model_copy(
                update={"window_key": "getDocsIP/RI223/50/2026-10-08+03:00/" + FAMILY}
            ),
        )


@pytest.mark.parametrize(
    "key",
    [
        "getDocsIP/RI223/by-number/32600000001/purchaseNotice",
        "getDocsIP/RI223/by-number/3260000000/purchaseNoticeKESMBO",
        "getDocsIP/RI223/by-number/32600000001/purchaseNoticeZPESMBO",
    ],
)
def test_targeted_support_does_not_admit_unverified_families_or_identities(key):
    # ZP now has an admitted key shape, but an unbound legacy KES payload
    # cannot acquire the new family's authenticated source permission.
    error = "SOURCE_BINDING_INVALID" if key.endswith("/purchaseNoticeZPESMBO") else "WINDOW_INVALID"
    with pytest.raises(ValueError, match=error):
        preflight_notice223_window(
            "tenant-a", targeted_window().model_copy(update={"window_key": key})
        )


@pytest.mark.parametrize("number", ["32616445250", "32616445747"])
def test_exact_number_search_keeps_cached_kesmbo_unknown_and_identity_evidence(number):
    notice = parse_notice223_xml(
        kesmbo_xml(number=number), source_member="synthetic-kesmbo.xml", document_type=FAMILY
    )
    lead = compare_notice223(
        notice,
        " " + number + " ",
        now=NOW,
        source_window=f"getDocsIP/RI223/by-number/{number}/{FAMILY}",
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )
    assert lead is not None and lead.notice.purchase_number == number
    assert lead.match_quality == "STRONG"
    assert lead.application_status == "UNKNOWN"
    assert lead.term_evidence[0].value_kind == "PURCHASE_NUMBER"
    assert lead.term_evidence[0].source_value == number
    assert lead.term_evidence[0].locator.startswith(FAMILY + "/")
    assert (
        compare_notice223(
            notice,
            "32699999999",
            now=NOW,
            source_window=f"getDocsIP/RI223/by-number/{number}/{FAMILY}",
            source_response_sha256="b" * 64,
            archive_sha256="c" * 64,
        )
        is None
    )
