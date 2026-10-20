"""General source metadata never manufactures eligibility, price or file completeness."""

from datetime import UTC, datetime

import pytest

from procurement.sources.eis_223_documents import manifest223
from procurement.sources.eis_223_policy import deadline223, unavailable223
from procurement.storage.eis_223_index import compare_notice223
from test_eis_223_general_archive import general_xml, parse
from test_eis_mixed_comparison import row223
from test_eis_source_estimate import compute, request

NOW = datetime(2026, 10, 3, tzinfo=UTC)


@pytest.mark.parametrize(
    "extra",
    [
        "<t:prevDocument><t:guid>old</t:guid></t:prevDocument>",
        "<t:additionalDocumentsCount>1</t:additionalDocumentsCount>",
    ],
)
def test_unresolved_manifest_never_allows_complete_set(extra):
    notice = parse(general_xml(manifest_extra=extra))
    assert manifest223(notice).status == "UNKNOWN"
    assert manifest223(notice).source_manifest_coverage == "UNKNOWN"


@pytest.mark.parametrize("flag", ["true", "malformed"])
def test_not_placement_is_not_downloadable(flag):
    notice = parse(general_xml(document_flag=f"<t:notPlacement>{flag}</t:notPlacement>"))
    manifest = manifest223(notice)
    assert manifest.status == "UNKNOWN" and manifest.documents[0].source_url is None


def test_lot_oriented_deadline_does_not_block_from_notice_deadline():
    notice = parse(general_xml(lot_oriented="true", deadline="2026-10-01T00:00:00Z"))
    assert notice.deadline.value < NOW and deadline223(notice).value is None
    lead = compare_notice223(
        notice,
        "бумага",
        now=NOW,
        source_window="test",
        source_response_sha256="a" * 64,
        archive_sha256="b" * 64,
    )
    assert lead and lead.application_status == "UNKNOWN"


@pytest.mark.parametrize(
    "raw,reason",
    [
        (general_xml(hide="true"), "SOURCE_PURCHASE_HIDDEN"),
        (general_xml().replace(b"<p:status>P", b"<p:status>I"), "SOURCE_RECORD_INVALIDATED"),
        (
            general_xml().replace(
                b"<p:status>P</p:status>",
                b"<p:status>P</p:status><p:hidePurchaseCustomerAccredited>true</p:hidePurchaseCustomerAccredited>",
            ),
            "SOURCE_PURCHASE_ACCREDITED_ONLY",
        ),
    ],
)
def test_confirmed_unavailable_source_blocks_search(raw, reason):
    notice = parse(raw)
    assert reason in unavailable223(notice)
    lead = compare_notice223(
        notice,
        "бумага",
        now=NOW,
        source_window="test",
        source_response_sha256="a" * 64,
        archive_sha256="b" * 64,
    )
    assert lead and lead.application_status == "FAIL" and reason in lead.reasons


def test_max_price_estimate_is_unknown_and_carries_quality_warning(monkeypatch):
    notice = parse(general_xml(price="<t:maxContractPrice>999999</t:maxContractPrice>"))
    chosen = request("223")
    chosen = chosen.model_copy(
        update={"notice": chosen.notice.model_copy(update={"notice_xml_sha256": notice.xml_sha256})}
    )
    row = row223().model_copy(
        update={
            "notice": notice,
            "source_schema_status": "FAIL",
            "reasons": ("Ошибка XSD источника требует проверки; это не supplier hard gate.",),
        }
    )
    result = compute(monkeypatch, chosen, lotrow=row)
    assert result.source_schema_status == "FAIL"
    assert result.source_price_kind == "MAX_CONTRACT_PRICE"
    assert result.ceiling_rub is None and result.ceiling.value is None
    assert result.estimate.status == "UNKNOWN" and not result.estimate.scenarios
    assert result.source_reasons == row.reasons and not result.blocking_reasons


def test_known_initial_price_preliminary_keeps_schema_fail_separate(monkeypatch):
    notice = parse(general_xml())
    chosen = request("223")
    chosen = chosen.model_copy(
        update={"notice": chosen.notice.model_copy(update={"notice_xml_sha256": notice.xml_sha256})}
    )
    row = row223().model_copy(update={"notice": notice, "source_schema_status": "FAIL"})
    result = compute(monkeypatch, chosen, lotrow=row)
    assert result.source_schema_status == "FAIL" and len(result.estimate.scenarios) == 3
    assert result.eligibility == "UNKNOWN" and result.estimate.recommendation == "needs_analysis"
