"""Explicit ZP request/admission; no unsupported-family alias or coordinate inference."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_archive import (
    SUPPORTED_DOCUMENT_TYPES,
    Eis223ContractError,
    notice223_request,
    parse_notice223_xml,
)
from procurement.sources.eis_223_sync import window_key
from procurement.storage.eis_223_index import (
    bind_notice223_window,
    compare_notice223,
    preflight_notice223_window,
)
from procurement.storage.eis_223_regions import FAMILIES, plan_targets
from test_eis_223_archive import zip_bytes
from test_eis_223_index import NOW, UID, URL, responses, window
from test_eis_223_targeted_kesmbo import kesmbo_xml

FAMILY = "purchaseNoticeZPESMBO"
NUMBER = "32600000001"
REGIONAL = f"getDocsIP/RI223/02/2026-10-08+03:00/{FAMILY}"
TARGETED = f"getDocsIP/RI223/by-number/{NUMBER}/{FAMILY}"


def zp_xml(*, number=NUMBER, version=1):
    return (
        kesmbo_xml(number=number)
        .replace(b"purchaseNoticeKESMBO", FAMILY.encode())
        .replace(b"<p:version>2</p:version>", f"<p:version>{version}</p:version>".encode())
    )


def zp_zip(*, number=NUMBER):
    return zip_bytes([(f"zp-{v}.xml", zp_xml(number=number, version=v)) for v in range(1, 5)])


def zp_ready(*, targeted=False, number=NUMBER):
    initial, prepared = responses()
    key = TARGETED if targeted else REGIONAL
    if targeted:
        initial = replace(initial, kind="BY_NUMBER")
    return bind_notice223_window(key, initial, prepared, {URL: zp_zip(number=number)})


def test_native_zp_shape_retains_explicit_family_raw_naive_deadline_and_decimal():
    n = parse_notice223_xml(zp_xml(), source_member="zp.xml", document_type=FAMILY)
    assert n.document_type == FAMILY and n.purchase_number == NUMBER
    assert n.title.provenance.locator.startswith(FAMILY + "/")
    assert n.purchase_guid.value == "synthetic-purchase-guid"
    assert n.deadline.value is None and n.deadline.status == "UNKNOWN"
    assert n.application_status == "UNKNOWN"
    assert isinstance(n.lots[0].initial_sum.value, Decimal)
    assert FAMILY in SUPPORTED_DOCUMENT_TYPES


def test_zp_regular_request_and_target_key_keep_exact_source_coordinates():
    raw = notice223_request(
        "synthetic-token-123", UID, "02", date(2026, 10, 8), document_type=FAMILY
    )
    root = ET.fromstring(raw)
    assert root.findtext(".//selectionParams/orgRegion") == "02"
    assert root.findtext(".//selectionParams/documentType223") == FAMILY
    assert root.findtext(".//selectionParams/periodInfo/exactDate") == "2026-10-08+03:00"
    assert window_key(date(2026, 10, 8), FAMILY, region="02") == REGIONAL


@pytest.mark.parametrize("targeted", [False, True])
def test_authentic_factory_admits_whole_four_version_archive_in_its_exact_scope(targeted):
    ready = zp_ready(targeted=targeted)
    inspected, _ = preflight_notice223_window("tenant-a", ready)
    assert [n.version_number for n in inspected[0].records] == [1, 2, 3, 4]
    assert {n.document_type for n in inspected[0].records} == {FAMILY}
    assert {n.purchase_number for n in inspected[0].records} == {NUMBER}
    assert ready.source_binding is not None
    assert ready.source_binding.selection_key == (TARGETED if targeted else REGIONAL)


@pytest.mark.parametrize("key", [REGIONAL, TARGETED])
def test_new_zp_does_not_inherit_legacy_unbound_ready_admission(key):
    ready = window(zp_zip()).model_copy(update={"window_key": key})
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window("tenant-a", ready)


@pytest.mark.parametrize(
    "key",
    [
        TARGETED,
        REGIONAL.replace("/02/", "/14/"),
        REGIONAL.replace("2026-10-08", "2026-10-09"),
        REGIONAL.replace(FAMILY, "purchaseNoticeKESMBO"),
        REGIONAL.replace(FAMILY, "purchaseNoticeAESMBO"),
    ],
)
def test_bound_zp_region_day_family_or_request_kind_cannot_be_retagged(key):
    ready = zp_ready()
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window("tenant-a", ready.model_copy(update={"window_key": key}))


def test_bound_zp_number_response_cannot_be_retagged_as_regional():
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window(
            "tenant-a", zp_ready(targeted=True).model_copy(update={"window_key": REGIONAL})
        )


def test_number_scope_rejects_other_purchase_in_the_full_bound_archive():
    with pytest.raises(ValueError, match="BY_NUMBER_PURCHASE_MISMATCH"):
        preflight_notice223_window("tenant-a", zp_ready(targeted=True, number="32600000002"))


def test_whole_archive_rejects_a_sibling_family_instead_of_selecting_only_zp():
    initial, prepared = responses()
    raw = zip_bytes([("zp.xml", zp_xml()), ("kes.xml", kesmbo_xml())])
    ready = bind_notice223_window(REGIONAL, initial, prepared, {URL: raw})
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_notice223_window("tenant-a", ready)


def test_factory_rejects_missing_archives_before_any_source_checkpoint():
    initial, prepared = responses()
    with pytest.raises(ValueError, match="ARCHIVE_SET_MISMATCH"):
        bind_notice223_window(REGIONAL, initial, prepared, {})


def test_factory_rejects_a_prepared_response_for_another_uid():
    initial, prepared = responses()
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        bind_notice223_window(
            REGIONAL,
            initial,
            replace(prepared, doc_request_uid="22222222-2222-4222-8222-222222222222"),
            {URL: zp_zip()},
        )


@pytest.mark.parametrize("field", ["response_sha256", "prepared_sha256"])
def test_zp_response_hashes_remain_bound_through_preflight(field):
    ready = zp_ready()
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window("tenant-a", ready.model_copy(update={field: "d" * 64}))


def test_zp_expands_regular_scope_to_seven_families_without_removing_old_six():
    planned = plan_targets(("02", "14"), date(2026, 10, 7), date(2026, 10, 8))
    assert len(FAMILIES) == 7 and len(planned) == 28
    assert sum(t.document_type == FAMILY for t in planned) == 4
    assert set(FAMILIES) == {
        "purchaseNoticeAESMBO",
        "purchaseNoticeZKESMBO",
        "purchaseNotice",
        "purchaseNoticeKESMBO",
        FAMILY,
        "purchaseRejection",
        "purchaseLotCancellation",
    }


def test_zp_number_search_uses_explicit_identity_provenance_not_an_alias():
    n = parse_notice223_xml(zp_xml(), source_member="zp.xml", document_type=FAMILY)
    lead = compare_notice223(
        n,
        NUMBER,
        now=NOW,
        source_window=TARGETED,
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )
    assert lead is not None and lead.notice.document_type == FAMILY
    assert lead.application_status == "UNKNOWN" and lead.match_quality == "STRONG"
    assert lead.term_evidence[0].locator.startswith(FAMILY + "/")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.replace(b"http://zakupki.gov.ru/223fz/purchase/1", b"urn:untrusted"),
        lambda raw: raw.replace(
            b"<p:purchaseNoticeZPESMBOData>", b"<t:purchaseNoticeZPESMBOData>"
        ).replace(b"</p:purchaseNoticeZPESMBOData>", b"</t:purchaseNoticeZPESMBOData>"),
        lambda raw: raw.replace(b"purchaseNoticeZPESMBOData", b"purchaseNoticeKESMBOData"),
        lambda raw: raw.replace(b"<p:version>1</p:version>", b"<t:version>1</t:version>"),
        lambda raw: raw.replace(
            b"<p:version>1</p:version>", b"<p:version>1</p:version><p:version>2</p:version>"
        ),
    ],
)
def test_zp_rejects_wrong_root_data_and_identity_qnames(mutation):
    with pytest.raises(Eis223ContractError):
        parse_notice223_xml(mutation(zp_xml()), source_member="zp.xml", document_type=FAMILY)
