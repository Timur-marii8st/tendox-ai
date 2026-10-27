"""Regular KESMBO retains authenticated request kind and exact selection label."""

from dataclasses import replace
from datetime import date
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_archive import notice223_request
from procurement.sources.eis_223_sync import window_key
from procurement.storage.eis_223_index import bind_notice223_window, preflight_notice223_window
from test_eis_223_archive import zip_bytes
from test_eis_223_index import UID, URL, responses
from test_eis_223_targeted_kesmbo import FAMILY, KEY, NUMBER, kesmbo_xml, targeted_window

REGIONAL_KEY = "getDocsIP/RI223/02/2026-10-08+03:00/" + FAMILY


def regional_window():
    initial, prepared = responses()
    raw = zip_bytes([("kesmbo.xml", kesmbo_xml())])
    return bind_notice223_window(REGIONAL_KEY, initial, prepared, {URL: raw})


def test_regular_request_uses_exact_typed_selection():
    raw = notice223_request(
        "synthetic-token-123", UID, "02", date(2026, 10, 8), document_type=FAMILY
    )
    root = ET.fromstring(raw)
    assert root.findtext(".//selectionParams/orgRegion") == "02"
    assert root.findtext(".//selectionParams/documentType223") == FAMILY
    assert root.findtext(".//selectionParams/periodInfo/exactDate") == "2026-10-08+03:00"
    assert window_key(date(2026, 10, 8), FAMILY, region="02") == REGIONAL_KEY


def test_regular_full_set_passes_and_preserves_unknown_state():
    ready = regional_window()
    inspections, _ = preflight_notice223_window("tenant-a", ready)
    assert len(inspections) == 1 and len(inspections[0].records) == 1
    notice = inspections[0].records[0]
    assert notice.purchase_number == NUMBER and notice.document_type == FAMILY
    assert notice.deadline.value is None and notice.application_status == "UNKNOWN"
    assert inspections[0].source_locator == REGIONAL_KEY


def test_bound_by_number_cannot_be_retagged_as_regional():
    initial, prepared = responses()
    ready = bind_notice223_window(
        KEY, replace(initial, kind="BY_NUMBER"), prepared, {URL: targeted_window().archives[0]}
    )
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window(
            "tenant-a", ready.model_copy(update={"window_key": REGIONAL_KEY})
        )


def test_unbound_legacy_by_number_cannot_be_retagged_as_regional():
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window(
            "tenant-a", targeted_window().model_copy(update={"window_key": REGIONAL_KEY})
        )


@pytest.mark.parametrize(
    "key",
    [
        REGIONAL_KEY.replace("/02/", "/03/"),
        REGIONAL_KEY.replace("2026-10-08", "2026-10-09"),
        REGIONAL_KEY.replace(FAMILY, "purchaseNoticeAESMBO"),
        KEY,
    ],
)
def test_bound_regional_selection_cannot_be_relabelled(key):
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window(
            "tenant-a", regional_window().model_copy(update={"window_key": key})
        )


@pytest.mark.parametrize("field", ["response_sha256", "prepared_sha256"])
def test_bound_source_response_digest_cannot_be_changed(field):
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        preflight_notice223_window(
            "tenant-a", regional_window().model_copy(update={field: "d" * 64})
        )


def test_retagged_initial_number_response_never_enters_regular_factory():
    initial, prepared = responses()
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        bind_notice223_window(
            REGIONAL_KEY,
            replace(initial, kind="BY_NUMBER"),
            prepared,
            {URL: targeted_window().archives[0]},
        )
