from hashlib import sha256

import pytest

from procurement.sources.tender_navigation import extract_navigation


def xml223(extra="", hidden="false"):
    return f"""<purchaseNotice xmlns="http://zakupki.gov.ru/223fz/purchase/1" xmlns:t="http://zakupki.gov.ru/223fz/types/1">
<body><item><purchaseNoticeData><registrationNumber>32612345678</registrationNumber>
<version>1</version>
<hidePurchase>{hidden}</hidePurchase>
<urlEIS>https://zakupki.gov.ru/223/purchase/public/purchase/info/common-info.html?regNumber=32612345678</urlEIS>
<urlVSRZ>https://trade.example/auction/1</urlVSRZ>
<electronicPlaceInfo><t:name>Тестовая площадка</t:name><t:url>https://trade.example</t:url></electronicPlaceInfo>
<customer><t:region>Москва</t:region></customer>
<lots><t:lot><t:lotData><t:deliveryPlace>
<t:region>Республика Татарстан</t:region></t:deliveryPlace>
</t:lotData></t:lot></lots>{extra}
</purchaseNoticeData></item></body></purchaseNotice>""".encode()


def extract(raw, law="223", number="32612345678"):
    return extract_navigation(
        raw, law=law, number=number, version=1, xml_sha256=sha256(raw).hexdigest()
    )


def test_delivery_is_separate_from_customer_and_links_have_exact_source():
    report = extract(xml223())
    assert [f.value for f in report.delivery_regions] == ["Республика Татарстан"]
    assert report.delivery_regions[0].provenance.document_id == report.xml_sha256
    assert "deliveryPlace" in report.delivery_regions[0].provenance.locator
    assert report.eis_url.value.endswith("regNumber=32612345678")
    assert report.platform_url.value == "https://trade.example/auction/1"
    assert report.platform_name.value == "Тестовая площадка"


@pytest.mark.parametrize("hidden", ["true", "1", "unexpected"])
def test_hidden_or_ambiguous_flag_hides_every_navigation_link(hidden):
    result = extract(xml223(hidden=hidden))
    assert result.eis_url is None and result.platform_url is None


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://u:p@trade.example",
        "https://127.0.0.1/x",
        "https://localhost/x",
    ],
)
def test_unsafe_platform_link_stays_unknown(url):
    raw = xml223().replace(b"https://trade.example/auction/1", url.encode())
    assert extract(raw).platform_url is None


def test_duplicate_field_and_private_eis_url_are_not_fallback_links():
    raw = xml223("<urlVSRZ>https://other.example/x</urlVSRZ>").replace(
        b"/223/purchase/public/", b"/223/purchase/private/"
    )
    result = extract(raw)
    assert result.platform_url is None and result.eis_url is None


def test_wrong_eis_purchase_number_is_rejected():
    raw = xml223().replace(b"regNumber=32612345678", b"regNumber=32612345679")
    assert extract(raw).eis_url is None


def test_source_digest_and_identity_are_checked_before_using_fields():
    with pytest.raises(ValueError):
        extract_navigation(
            xml223(), law="223", number="32612345679", version=1, xml_sha256="a" * 64
        )
    with pytest.raises(ValueError):
        extract(xml223().replace(b"<version>1", b"<version>2"))


def test_44_does_not_infer_delivery_from_customer_or_free_text():
    raw = b'<export xmlns="http://zakupki.gov.ru/oos/export/1"><epNotificationEF2020><versionNumber>1</versionNumber><commonInfo><purchaseNumber>0123456789012345678</purchaseNumber></commonInfo><notificationInfo><customer><region>Moscow</region></customer></notificationInfo></epNotificationEF2020></export>'
    report = extract(raw, "44", "0123456789012345678")
    assert report.delivery_regions == ()
    assert report.platform_url is None


def test_published_http_platform_is_not_silently_rewritten():
    raw = xml223().replace(b"https://trade.example/auction/1", b"http://trade.example/auction/1")
    assert extract(raw).platform_url.value == "http://trade.example/auction/1"


def test_gar_first_component_requires_unambiguous_official_catalogue_match():
    from datetime import UTC, datetime

    from procurement.domain.provenance import Extractor, Provenance
    from procurement.sources.eis_223_regions import RegionCatalog
    from procurement.sources.tender_navigation import (
        NavigationFact,
        TenderNavigation,
        bind_gar_regions,
    )

    source = Provenance(document_id="a" * 64, locator="/GARAddress", extractor=Extractor.API)
    nav = TenderNavigation(
        law="44",
        purchase_number="1" * 19,
        version_number=1,
        xml_sha256="a" * 64,
        delivery_addresses=(
            NavigationFact(value="г. Севастополь, улица Пример", provenance=source),
        ),
    )
    cat = RegionCatalog(
        catalog_sha256="b" * 64,
        source_url="https://zakupki.gov.ru/catalog",
        response_sha256="b" * 64,
        observed_at=datetime.now(UTC),
        regions={"92": "Севастополь г"},
    )
    result = bind_gar_regions(nav, cat)
    assert result.delivery_regions[0].value == "Севастополь г"
    assert result.delivery_regions[0].supporting_sources[0].document_id == "b" * 64
    assert result.delivery_coverage == "UNKNOWN"
    other = nav.model_copy(
        update={
            "delivery_addresses": (
                NavigationFact(value="ул. Севастопольская, Москва", provenance=source),
            )
        }
    )
    assert bind_gar_regions(other, cat).delivery_regions == ()


def xml44_ep(kind="epNotificationEZK2020"):
    # Synthetic content, but the namespace/path profile matches saved official XML.
    return f"""<e:export xmlns:e="http://zakupki.gov.ru/oos/export/1"
      xmlns:ep="http://zakupki.gov.ru/oos/EPtypes/1"
      xmlns:b="http://zakupki.gov.ru/oos/base/1"
      xmlns:c="http://zakupki.gov.ru/oos/common/1"><e:{kind}>
      <ep:versionNumber>1</ep:versionNumber><ep:commonInfo>
      <ep:purchaseNumber>0123456789012345678</ep:purchaseNumber>
      <ep:ETP><b:name>Площадка примера</b:name><b:url>http://trade.example</b:url></ep:ETP>
      </ep:commonInfo><ep:notificationInfo><ep:customerRequirementsInfo>
      <ep:customerRequirementInfo><ep:contractConditionsInfo><ep:deliveryPlacesInfo>
      <ep:byGARInfo><c:GARInfo><c:GARAddress>г. Севастополь, улица Пример</c:GARAddress>
      </c:GARInfo></ep:byGARInfo></ep:deliveryPlacesInfo></ep:contractConditionsInfo>
      </ep:customerRequirementInfo></ep:customerRequirementsInfo></ep:notificationInfo>
      </e:{kind}></e:export>""".encode()


@pytest.mark.parametrize(
    "kind", ["epNotificationEF2020", "epNotificationEZK2020", "epNotificationEOK2020"]
)
def test_44_official_namespace_profile_keeps_exact_identity_and_source_paths(kind):
    raw = xml44_ep(kind)
    report = extract(raw, "44", "0123456789012345678")
    assert report.platform_url.value == "http://trade.example"
    assert report.platform_name.value == "Площадка примера"
    assert report.delivery_addresses[0].value == "г. Севастополь, улица Пример"
    assert report.platform_url.provenance.document_id == sha256(raw).hexdigest()
    assert report.delivery_addresses[0].provenance.document_id == sha256(raw).hexdigest()
    assert report.delivery_addresses[0].provenance.locator.endswith("GARInfo/GARAddress")
    assert report.delivery_regions == () and report.delivery_coverage == "UNKNOWN"


@pytest.mark.parametrize("field", ["versionNumber", "purchaseNumber"])
def test_44_mixed_identity_namespace_is_rejected(field):
    raw = xml44_ep().replace(f"ep:{field}".encode(), f"e:{field}".encode())
    with pytest.raises(ValueError, match="NAVIGATION_NOTICE_IDENTITY"):
        extract(raw, "44", "0123456789012345678")


@pytest.mark.parametrize("namespace", ["base", "common"])
def test_44_foreign_namespace_does_not_supply_platform_or_address(namespace):
    raw = xml44_ep().replace(f"http://zakupki.gov.ru/oos/{namespace}/1".encode(), b"urn:foreign")
    report = extract(raw, "44", "0123456789012345678")
    if namespace == "base":
        assert report.platform_url is None and report.platform_name is None
    else:
        assert report.delivery_addresses == ()


def test_44_duplicate_common_profiles_never_select_an_identity():
    raw = xml44_ep().replace(
        b"</ep:commonInfo>",
        b"</ep:commonInfo><e:commonInfo><e:purchaseNumber>0123456789012345678"
        b"</e:purchaseNumber></e:commonInfo>",
    )
    with pytest.raises(ValueError, match="NAVIGATION_NOTICE_IDENTITY"):
        extract(raw, "44", "0123456789012345678")
