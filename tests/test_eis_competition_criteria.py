"""Synthetic top-level and conditional weights; nested indicator values must not leak."""

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from procurement.sources.eis_competition_criteria import (
    EP_NS,
    EXPORT_NS,
    SCHEMA_SHA,
    extract_competition_criteria,
)
from procurement.sources.eis_feed_archive import EisNoticeSnapshot

NUMBER = "0848300054826000154"


def criterion(code="CP", weight="60.00", *, kind="cost", value_xml=None, extra=""):
    values = value_xml if value_xml is not None else f"<p:value>{weight}</p:value>"
    branch = "costCriterionInfo" if kind == "cost" else "qualitativeCriterionInfo"
    return (
        f"<p:criterionInfo><p:{branch}><p:code>{code}</p:code>"
        f"<p:valueInfo>{values}</p:valueInfo>{extra}</p:{branch}></p:criterionInfo>"
    )


def source(*items, extra_block=""):
    if not items:
        items = (criterion(), criterion("QO", "40.00", kind="quality"))
    return (
        f'<e:export xmlns:e="{EXPORT_NS}" xmlns:p="{EP_NS}">'
        "<e:epNotificationEOK2020><p:versionNumber>2</p:versionNumber><p:commonInfo>"
        f"<p:purchaseNumber>{NUMBER}</p:purchaseNumber></p:commonInfo><p:notificationInfo>"
        "<p:criteriaInfo>" + "".join(items) + extra_block + "</p:criteriaInfo>"
        "</p:notificationInfo></e:epNotificationEOK2020></e:export>"
    ).encode()


def notice(raw):
    return EisNoticeSnapshot(
        purchase_number=NUMBER,
        document_type="epNotificationEOK2020",
        version_number=2,
        title="Synthetic",
        published_at=None,
        deadline=None,
        nmck_rub=None,
        xml_sha256=hashlib.sha256(raw).hexdigest(),
        source_member="synthetic.xml",
    )


def extract(raw):
    return extract_competition_criteria(raw, notice(raw))


def test_standard_source_weights_are_decimal_with_separate_code_and_schema_provenance():
    result = extract(source())
    assert result.source_status == "EXTRACTED" and result.weight_integrity == "CONSISTENT"
    assert [e.code for e in result.criteria] == ["CP", "QO"]
    assert [e.weights[0].value_percent for e in result.criteria] == [
        Decimal("60.00"),
        Decimal("40.00"),
    ]
    assert (
        result.supplier_score_status
        == result.qualification_status
        == result.review_status
        == "UNKNOWN"
    )
    for e in result.criteria:
        assert e.code_provenance.document_id == result.source_xml_sha256
        assert e.code_provenance.locator.endswith("/code")
        assert e.label_provenance.document_id == SCHEMA_SHA
        assert e.weights[0].provenance.document_id == result.source_xml_sha256
        assert "/valueInfo/value[1]" in e.weights[0].provenance.locator


def test_nested_weights_and_codes_have_other_denominators():
    nested = (
        "<p:indicatorsInfo><p:indicatorInfo><p:code>nested</p:code><p:value>90</p:value>"
        "<p:detailIndicatorsInfo><p:value>100</p:value></p:detailIndicatorsInfo>"
        "</p:indicatorInfo></p:indicatorsInfo>"
    )
    result = extract(source(criterion(), criterion("QO", "40", kind="quality", extra=nested)))
    assert result.weight_integrity == "CONSISTENT"
    assert result.criteria[1].code == "QO" and result.criteria[1].weights[
        0
    ].value_percent == Decimal(40)
    assert result.criteria[1].indicators_status == "PRESENT_UNREVIEWED"


def test_conditional_weights_keep_each_discount_band_and_separate_sum():
    cp = (
        "<p:valueLess25MaxPrice>60</p:valueLess25MaxPrice>"
        "<p:valueMore25MaxPrice>50</p:valueMore25MaxPrice>"
    )
    qo = (
        "<p:valueLess25MaxPrice>40</p:valueLess25MaxPrice>"
        "<p:valueMore25MaxPrice>50</p:valueMore25MaxPrice>"
    )
    result = extract(source(criterion(value_xml=cp), criterion("QO", kind="quality", value_xml=qo)))
    assert result.weight_integrity == "CONSISTENT"
    assert [w.band for w in result.criteria[0].weights] == [
        "DISCOUNT_BELOW_25",
        "DISCOUNT_AT_LEAST_25",
    ]
    assert [w.value_percent for w in result.criteria[0].weights] == [Decimal(60), Decimal(50)]
    bad = extract(
        source(
            criterion(value_xml=cp),
            criterion("QO", kind="quality", value_xml=qo.replace(">50<", ">40<")),
        )
    )
    assert bad.weight_integrity == "UNKNOWN" and "CRITERIA_WEIGHT_SUM_UNKNOWN" in bad.reasons


@pytest.mark.parametrize(
    "value", ["", "NaN", "Infinity", "1e2", "60,00", "-1", "101", "not a weight"]
)
def test_invalid_or_missing_percentage_does_not_become_a_numeric_weight(value):
    result = extract(source(criterion(weight=value), criterion("QO", "40", kind="quality")))
    assert (
        result.weight_integrity == "UNKNOWN" and result.criteria[0].weights[0].value_percent is None
    )


@pytest.mark.parametrize(
    "items",
    [
        (criterion(weight="50"), criterion("QO", "40", kind="quality")),
        (criterion(weight="60"), criterion(weight="40")),
        (criterion("unknown", "60"), criterion("QO", "40", kind="quality")),
        (
            criterion(value_xml="<p:value>60</p:value><p:value>60</p:value>"),
            criterion("QO", "40", kind="quality"),
        ),
        (
            criterion(
                value_xml="<p:value>60</p:value><p:valueLess25MaxPrice>60</p:valueLess25MaxPrice>"
            ),
            criterion("QO", "40", kind="quality"),
        ),
        (
            criterion(
                value_xml="<p:valueLess25MaxPrice>60</p:valueLess25MaxPrice><p:valueMore25MaxPrice>60</p:valueMore25MaxPrice>"
            ),
            criterion("QO", "40", kind="quality"),
        ),
    ],
)
def test_inconsistent_ambiguous_or_mixed_regimes_remain_unknown(items):
    result = extract(source(*items))
    assert result.source_status == result.weight_integrity == "UNKNOWN"


def test_duplicate_value_block_and_duplicate_code_are_unknown():
    for raw in [
        source().replace(
            b"</p:costCriterionInfo>",
            b"<p:valueInfo><p:value>60</p:value></p:valueInfo></p:costCriterionInfo>",
        ),
        source().replace(b"<p:code>CP</p:code>", b"<p:code>CP</p:code><p:code>TC</p:code>"),
    ]:
        assert extract(raw).weight_integrity == "UNKNOWN"


def test_exact_digest_identity_and_version_are_required():
    raw = source()
    for wrong in [
        replace(notice(raw), xml_sha256="a" * 64),
        replace(notice(raw), version_number=3),
        replace(notice(raw), purchase_number="0848300054826000155"),
    ]:
        with pytest.raises(ValueError):
            extract_competition_criteria(raw, wrong)


def test_empty_missing_wrong_namespace_and_untrusted_xml_do_not_become_price_only():
    for raw in [
        source().replace(b"criteriaInfo", b"otherBlock"),
        source().replace(EP_NS.encode(), b"urn:untrusted"),
        source().replace(
            source().split(b"<p:criteriaInfo>")[1].split(b"</p:criteriaInfo>")[0], b""
        ),
        b'<!DOCTYPE x [<!ENTITY x "unsafe">]>' + source(),
    ]:
        result = extract(raw)
        assert result.source_status == result.weight_integrity == "UNKNOWN"
        assert not result.criteria


def test_other_procedure_is_not_applicable_not_an_empty_pass():
    raw = source()
    result = extract_competition_criteria(
        raw, replace(notice(raw), document_type="epNotificationEF2020")
    )
    assert result.source_status == result.weight_integrity == "NOT_APPLICABLE"
    assert result.review_status == result.supplier_score_status == "UNKNOWN"


def test_serialized_consistency_claim_cannot_hide_empty_or_changed_evidence():
    from procurement.sources.eis_competition_criteria import EisCompetitionCriteria

    payload = extract(source()).model_dump()
    for mutation in [
        {**payload, "criteria": ()},
        {**payload, "source_xml_sha256": "a" * 64},
        {**payload, "source_status": "NOT_APPLICABLE"},
    ]:
        with pytest.raises(ValueError):
            EisCompetitionCriteria.model_validate(mutation)


def test_wrong_kind_cannot_receive_official_code_label_provenance():
    result = extract(
        source(criterion("CP", "60", kind="quality"), criterion("QO", "40", kind="quality"))
    )
    assert result.weight_integrity == "UNKNOWN"
    assert result.criteria[0].label == "Неизвестный критерий"
    assert result.criteria[0].label_provenance is None
