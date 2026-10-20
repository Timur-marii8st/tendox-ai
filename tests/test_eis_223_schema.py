"""Only synthetic XML/XSD; official source bytes remain on the VPS."""

from datetime import UTC, datetime

import pytest
from lxml import etree as E  # type: ignore[import-untyped]

from procurement.sources.eis_223_archive import PURCHASE_NS, parse_notice223_xml
from procurement.sources.eis_223_schema import (
    Eis223SchemaCheck,
    SchemaTree,
    load_schema_tree,
    schema_quality,
    validate_notice223_schema,
)
from test_eis_223_archive import xml

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def check(*, valid=True, release="16.3"):
    kind = "xs:anyType" if valid else "xs:string"
    schema = E.XMLSchema(
        E.fromstring(
            (
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
                f'targetNamespace="{PURCHASE_NS}"><xs:element name="purchaseNoticeAESMBO" '
                f'type="{kind}"/></xs:schema>'
            ).encode()
        )
    )
    raw = xml()
    notice = parse_notice223_xml(raw, source_member="notice.xml")
    return validate_notice223_schema(notice, raw, SchemaTree(release, schema), now=NOW)


def test_full_schema_status_is_source_quality_and_requires_both_releases():
    success = check()
    failure = check(valid=False)
    assert success.status == "PASS" and not success.diagnostics
    assert failure.status == "FAIL" and failure.diagnostics
    assert schema_quality(()) == schema_quality((success,)) == "UNKNOWN"
    assert schema_quality((success, check(release="16.2"))) == "PASS"
    assert schema_quality((success, failure)) == "FAIL"


@pytest.mark.parametrize(
    "change", [{"xml_sha256": "f" * 64}, {"version_number": 3}, {"purchase_number": "32600000002"}]
)
def test_other_source_identity_or_version_cannot_receive_this_check(change):
    notice = parse_notice223_xml(xml(), source_member="notice.xml").model_copy(update=change)
    with pytest.raises(ValueError, match="SCHEMA_XML_IDENTITY_MISMATCH"):
        validate_notice223_schema(notice, xml(), SchemaTree("16.3", None), now=NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"tree_sha256": "a" * 64},
        {"root_sha256": "b" * 64},
        {"package_sha256": "c" * 64},
        {"checked_at": datetime(2026, 10, 2)},
        {"status": "FAIL"},
    ],
)
def test_missing_diagnostics_timezone_or_changed_policy_rejects_observation(change):
    with pytest.raises(ValueError):
        Eis223SchemaCheck.model_validate({**check().model_dump(), **change})


@pytest.mark.parametrize(
    "location",
    ["https://example.invalid/a.xsd", "../outside.xsd", "file:///etc/passwd", "other.xsd"],
)
def test_local_schema_does_not_fetch_external_or_unknown_dependency(tmp_path, location):
    (tmp_path / "purchase.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        f'<xs:include schemaLocation="{location}"/></xs:schema>'
    )
    with pytest.raises(ValueError, match="SCHEMA_TREE_REJECTED"):
        load_schema_tree(tmp_path, "16.3")


def test_modified_tree_is_not_an_official_release(tmp_path):
    (tmp_path / "purchase.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'
    )
    with pytest.raises(ValueError, match="SCHEMA_POLICY_MISMATCH"):
        load_schema_tree(tmp_path, "16.3")
