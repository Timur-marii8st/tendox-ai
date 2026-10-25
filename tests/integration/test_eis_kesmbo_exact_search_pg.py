"""Isolated cached KESMBO identity search; no EIS requests or synthetic production rows."""

from uuid import uuid4

import pytest
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as storage

from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from test_eis_223_archive import zip_bytes
from test_eis_223_index import NOW, window
from test_eis_223_targeted_kesmbo import FAMILY, kesmbo_xml


@pytest.mark.parametrize("number", ["32616445250", "32616445747"])
def test_cached_kesmbo_exact_search_keeps_tenant_evidence_unknown_and_no_writes(storage, number):
    company = "kesmbo-exact-" + uuid4().hex
    raw = kesmbo_xml(number=number)
    ready = window(zip_bytes([("synthetic-kesmbo.xml", raw)])).model_copy(
        update={"window_key": f"getDocsIP/RI223/by-number/{number}/{FAMILY}"}
    )
    for tenant in (company, company + "-foreign"):
        ingest_notice223_window(storage, tenant, ready, actor_id="synthetic-test", now=NOW)
    before = counts(storage, company)
    result = search_notice223_index(storage, company, " " + number + " ", now=NOW, paginate=True)
    assert result.matched_count == 1
    lead = result.matched[0]
    assert lead.notice.purchase_number == number
    assert lead.notice.document_type == FAMILY
    assert lead.application_status == "UNKNOWN"
    assert lead.term_evidence[0].value_kind == "PURCHASE_NUMBER"
    assert lead.term_evidence[0].source_value == number
    assert lead.term_evidence[0].locator.startswith(FAMILY + "/")
    assert search_notice223_index(storage, company + "-absent", number, now=NOW).matched_count == 0
    assert search_notice223_index(storage, company, "32699999999", now=NOW).matched_count == 0
    assert counts(storage, company) == before
