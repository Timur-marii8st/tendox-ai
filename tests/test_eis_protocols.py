"""Протокол не превращает строки/ранги/суммы в участников, прибыль или допуск."""

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from procurement.sources.eis_feed_archive import _notice
from procurement.sources.eis_protocols import (
    MAX_APPLICATION_ROWS,
    EisProtocolError,
    parse_protocol_facts,
)
from test_eis_mixed_number_archive import companion

FINAL = "epProtocolEOK2020Final"
PLACEMENT = "fcsPlacementResult"
PROPOSALS = "fcsProposalsResult"


def protocol_xml(kind=PROPOSALS, body=""):
    return companion(kind).replace(f"</{kind}>".encode(), f"{body}</{kind}>".encode())


def parse(xml):
    return parse_protocol_facts(
        xml, _notice(xml, "protocol.xml", None, allow_companion_documents=True)
    )


def result_row(app_id="17", *, kind=PROPOSALS, price="100.10", rank="1", result="CC"):
    field = "journalNumber" if kind == PLACEMENT else "appNumber"
    return (
        f"<n:application><n:{field}>{app_id}</n:{field}><n:appRating>{rank}</n:appRating>"
        f"<n:price>{price}</n:price><n:result>{result}</n:result></n:application>"
    )


def final_row(branch="singleAppAdmittedInfo", *, app_id="17", fields=""):
    return (
        f"<n:applicationInfo><n:commonInfo><n:appNumber>{app_id}</n:appNumber>"
        f"</n:commonInfo><n:admittedInfo><n:{branch}>{fields}</n:{branch}>"
        "</n:admittedInfo></n:applicationInfo>"
    )


@pytest.mark.parametrize("kind", [PLACEMENT, PROPOSALS])
def test_result_explicit_decimal_counts_raw_codes_and_provenance(kind):
    xml = protocol_xml(kind, "<n:applications>" + result_row(kind=kind) + "</n:applications>")
    report = parse(xml)
    row = report.applications[0]
    assert report.observed_rows.value == report.represented_applications.value == 1
    assert row.proposal.amount.value == Decimal("100.10")
    assert row.proposal.amount.evidence.xml_sha256 == hashlib.sha256(xml).hexdigest()
    assert row.proposal.amount.evidence.locator == f"{kind}/applications/application[1]/price"
    assert row.rank.value == 1 and row.result_code.value == "CC"
    assert row.supplier_identity == report.signed_contract == report.current_stage == "UNKNOWN"
    assert row.proposal.currency == row.proposal.tax_basis == "UNKNOWN"
    assert report.notice_version_link == report.competition_prediction == "UNKNOWN"
    assert report.published_at is None  # createDate is not publication.


def test_duplicate_application_rows_never_become_distinct_competitors():
    report = parse(
        protocol_xml(PROPOSALS, "<n:applications>" + result_row() * 2 + "</n:applications>")
    )
    assert report.observed_rows.value == 2
    assert report.represented_applications.status == "UNKNOWN"
    assert report.represented_applications.value is None
    assert len(report.applications) == 2
    assert report.applications[1].application_id.evidence.locator.endswith(
        "application[2]/appNumber"
    )


@pytest.mark.parametrize("body", ["", "<n:applications/>"])
def test_absent_or_empty_application_list_is_unknown_not_zero(body):
    report = parse(protocol_xml(PROPOSALS, body))
    assert report.observed_rows.value is report.represented_applications.value is None


def test_final_single_signed_negative_amount_preserves_right_to_contract_flag():
    fields = (
        "<n:admitted>true</n:admitted><n:finalPrice>-15.25</n:finalPrice>"
        "<n:rightConcludeContractPrice>true</n:rightConcludeContractPrice>"
    )
    report = parse(
        protocol_xml(
            FINAL,
            "<n:protocolInfo><n:applicationsInfo>"
            + final_row(fields=fields)
            + "</n:applicationsInfo></n:protocolInfo>",
        )
    )
    row = report.applications[0]
    assert row.proposal.amount.value == Decimal("-15.25")
    assert row.proposal.right_to_conclude_contract.value is True
    assert row.proposal.source_kind == "FINAL_PROPOSAL"
    assert row.rank.value is None  # single-app has no rank; never invent rank1.


def test_multi_application_criteria_amount_is_not_final_price():
    fields = (
        "<n:appRating>1</n:appRating><n:score>2.00</n:score>"
        "<n:conditionsScoringInfo><n:offer>900</n:offer></n:conditionsScoringInfo>"
    )
    report = parse(
        protocol_xml(
            FINAL,
            "<n:protocolInfo><n:applicationsInfo>"
            + final_row("appAdmittedInfo", fields=fields)
            + "</n:applicationsInfo></n:protocolInfo>",
        )
    )
    row = report.applications[0]
    assert row.rank.value == 1 and row.proposal.amount.status == "UNKNOWN"
    assert report.signed_contract == "UNKNOWN"
    assert row.admission.status == "UNKNOWN"


def test_rejected_branch_does_not_parse_descendant_price():
    report = parse(
        protocol_xml(
            FINAL,
            "<n:protocolInfo><n:applicationsInfo>"
            + final_row(
                "appNotAdmittedInfo", fields="<n:extra><n:finalPrice>500</n:finalPrice></n:extra>"
            )
            + "</n:applicationsInfo></n:protocolInfo>",
        )
    )
    assert report.applications[0].admission.value is False
    assert report.applications[0].proposal.amount.value is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e9", "1,234", "", "1.123456789012"])
def test_unusable_amount_is_unknown(value):
    report = parse(
        protocol_xml(PROPOSALS, "<n:applications>" + result_row(price=value) + "</n:applications>")
    )
    assert report.applications[0].proposal.amount.status == "UNKNOWN"


@pytest.mark.parametrize("rank", ["0", "-1", "1.5", ""])
def test_nonpositive_or_invalid_rank_is_not_rank_one(rank):
    report = parse(
        protocol_xml(
            PLACEMENT,
            "<n:applications>" + result_row(kind=PLACEMENT, rank=rank) + "</n:applications>",
        )
    )
    assert report.applications[0].rank.value is None


def test_blank_application_id_and_unknown_result_preserve_unknown():
    report = parse(
        protocol_xml(
            PROPOSALS,
            "<n:applications>" + result_row(app_id="", result="WINNER") + "</n:applications>",
        )
    )
    assert report.represented_applications.value is None
    assert report.applications[0].result_code.value is None


@pytest.mark.parametrize(
    "bad",
    [
        '<n:price xmlns:n="urn:forged">1</n:price>',
        "<n:price>1</n:price><n:price>2</n:price>",
    ],
)
def test_namespace_spoof_and_duplicate_singleton_block_document(bad):
    body = (
        "<n:applications>"
        + result_row().replace("<n:price>100.10</n:price>", bad)
        + "</n:applications>"
    )
    with pytest.raises(EisProtocolError, match="PROTOCOL_FIELD_AMBIGUOUS"):
        parse(protocol_xml(PROPOSALS, body))


def test_conflicting_final_admission_branches_rejected():
    row = final_row(fields="<n:admitted>true</n:admitted>").replace(
        "</n:admittedInfo>", "<n:appNotAdmittedInfo/></n:admittedInfo>"
    )
    with pytest.raises(EisProtocolError, match="PROTOCOL_ADMISSION_AMBIGUOUS"):
        parse(
            protocol_xml(
                FINAL,
                "<n:protocolInfo><n:applicationsInfo>"
                + row
                + "</n:applicationsInfo></n:protocolInfo>",
            )
        )


def test_wrong_xml_source_identity_rejected():
    xml = protocol_xml(PROPOSALS)
    event = _notice(xml, "protocol.xml", None, allow_companion_documents=True)
    with pytest.raises(EisProtocolError, match="PROTOCOL_SOURCE_MISMATCH"):
        parse_protocol_facts(xml, replace(event, xml_sha256="f" * 64))


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_other_encoding_cannot_bypass_dtd_guard(encoding):
    xml = protocol_xml(PROPOSALS)
    event = _notice(xml, "protocol.xml", None, allow_companion_documents=True)
    malicious = '<!DOCTYPE export [<!ENTITY price "123.45">]>' + xml.decode()
    with pytest.raises(EisProtocolError, match="PROTOCOL_XML_UNSAFE"):
        parse_protocol_facts(malicious.encode(encoding), event)


def test_source_member_bound_before_fact_allocation():
    xml = protocol_xml(PROPOSALS)
    event = _notice(xml, "protocol.xml", None, allow_companion_documents=True)
    with pytest.raises(EisProtocolError, match="PROTOCOL_MEMBER_NAME_LIMIT"):
        parse_protocol_facts(
            xml,
            replace(event, source_member="a" * 256),
        )


def test_official_docnumber_path_and_branch_specific_fields():
    xml = protocol_xml(FINAL).replace(
        b"</n:commonInfo>",
        b"<n:docNumber>protocol-17</n:docNumber><n:number>forged</n:number></n:commonInfo>",
    )
    report = parse(xml)
    assert report.protocol_number.value == "protocol-17"
    assert report.protocol_number.evidence.locator.endswith("commonInfo/docNumber")
    row = final_row(fields="<n:admitted>true</n:admitted><n:appRating>1</n:appRating>")
    report = parse(
        protocol_xml(
            FINAL,
            "<n:protocolInfo><n:applicationsInfo>" + row + "</n:applicationsInfo></n:protocolInfo>",
        )
    )
    assert report.applications[0].rank.status == "UNKNOWN"


def test_float_is_rejected_in_typed_money_fact():
    from pydantic import ValidationError

    from procurement.sources.eis_protocols import ProtocolFact

    report = parse(protocol_xml(PROPOSALS, "<n:applications>" + result_row() + "</n:applications>"))
    data = report.applications[0].proposal.amount.model_dump() | {"value": 0.1}
    with pytest.raises(ValidationError, match="PROTOCOL_FLOAT_NOT_ALLOWED"):
        ProtocolFact[Decimal].model_validate(data)


@pytest.mark.parametrize("kind", [FINAL, PROPOSALS])
def test_unsupported_foundation_and_lot_fields_are_not_fact_evidence(kind):
    xml = protocol_xml(
        kind,
        "<n:foundationProtocolNumber>forged</n:foundationProtocolNumber><n:lotNumber>2</n:lotNumber>",
    )
    report = parse(xml)
    assert report.foundation_protocol_number.status == report.lot_number.status == "UNKNOWN"


def test_application_and_xml_limits_reject_before_large_fact_output():
    with pytest.raises(EisProtocolError, match="PROTOCOL_APPLICATION_LIMIT"):
        parse(
            protocol_xml(
                PROPOSALS,
                "<n:applications>"
                + result_row() * (MAX_APPLICATION_ROWS + 1)
                + "</n:applications>",
            )
        )
    with pytest.raises(EisProtocolError, match="PROTOCOL_XML_UNSAFE"):
        xml = protocol_xml(PROPOSALS)
        parse_protocol_facts(
            b"<!DOCTYPE export>" + xml,
            _notice(xml, "protocol.xml", None, allow_companion_documents=True),
        )
