"""Only synthetic source documents. Protect eligibility, exact source scope and receipts."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources.eis_223_regions import RegionCatalog
from procurement.sources.eis_contract_results import contract_result, notice_market
from procurement.sources.eis_contract_sync import OfficialBundle
from procurement.storage.eis_contract_results import qualify_contract
from test_eis_feed import _DS, _IP_NS, _POLL, _REQ, _URL, _xml

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
NUMBER = "1" * 19
REGISTRY = "2" * 19
CATALOG = RegionCatalog(
    catalog_sha256="c" * 64,
    source_url="https://zakupki.gov.ru/epz/nsi/kladr/chooseRegion.html",
    response_sha256="d" * 64,
    observed_at=NOW,
    regions={"77": "г. Москва", "50": "Московская область"},
)


def notice_xml(
    number=NUMBER,
    *,
    version=1,
    published="2026-10-01T09:00:00Z",
    quantity="10",
    sid="101",
    price="1000",
    product="99.99.99.999-00000001",
    region="г. Москва",
):
    return (
        f'<export xmlns="http://zakupki.gov.ru/oos/export/1">'
        f'<epNotificationEF2020 xmlns:e="http://zakupki.gov.ru/oos/EPtypes/1" '
        f'xmlns:c="http://zakupki.gov.ru/oos/common/1" '
        f'xmlns:b="http://zakupki.gov.ru/oos/base/1">\n    <e:commonInfo>'
        f"<e:purchaseNumber>{number}</e:purchaseNumber>"
        "<e:purchaseObjectInfo>Synthetic paper</e:purchaseObjectInfo>"
        f"<e:publishDTInEIS>{published}</e:publishDTInEIS></e:commonInfo>"
        f"<e:versionNumber>{version}</e:versionNumber>\n    <e:notificationInfo>"
        f"<e:purchaseObjectsInfo><e:notDrugPurchaseObjectsInfo>\n    <c:purchaseObject>"
        f"<c:sid>{sid}</c:sid><c:KTRU><b:code>{product}</b:code></c:KTRU>"
        f"<c:name>Synthetic object</c:name><c:OKEI><b:code>796</b:code></c:OKEI>"
        f"<c:volumeSpecifyingMethod>QF</c:volumeSpecifyingMethod><c:quantity>"
        f"<c:value>{quantity}</c:value></c:quantity><c:sum>{price}</c:sum>"
        f"</c:purchaseObject>"
        f"<e:quantityUndefined>false</e:quantityUndefined>\n    </e:notDrugPurchaseObjectsInfo>"
        f"</e:purchaseObjectsInfo>\n    <e:contractConditionsInfo><e:maxPriceInfo>"
        f"<e:maxPrice>{price}</e:maxPrice><e:currency><b:code>RUB</b:code></e:currency>"
        f"</e:maxPriceInfo></e:contractConditionsInfo>\n    <e:customerRequirementsInfo>"
        f"<e:customerRequirementInfo><e:contractConditionsInfo><e:deliveryPlacesInfo>"
        f"<e:byGARInfo><c:GARInfo><c:GARAddress>{region}, synthetic street</c:GARAddress>"
        f"</c:GARInfo></e:byGARInfo></e:deliveryPlacesInfo></e:contractConditionsInfo>"
        f"</e:customerRequirementInfo>"
        f"</e:customerRequirementsInfo>\n    </e:notificationInfo></epNotificationEF2020>"
        f"</export>"
    ).encode()


def contract_xml(
    registry=REGISTRY,
    number=NUMBER,
    *,
    version=0,
    price="700",
    price_type="P",
    currency="RUB",
    quantity="10",
    sid="101",
    product="99.99.99.999-00000001",
    region="г. Москва",
    sign="2026-10-20",
    extra="",
):
    return (
        f'<export xmlns="http://zakupki.gov.ru/oos/export/1">'
        f'<contract xmlns:t="http://zakupki.gov.ru/oos/types/1" '
        f'xmlns:c="http://zakupki.gov.ru/oos/common/1">\n    <t:regNum>{registry}</t:regNum>'
        f"<t:versionNumber>{version}</t:versionNumber>"
        f"<t:publishDate>2026-10-21T09:00:00Z</t:publishDate>"
        f"<t:signDate>{sign}</t:signDate>\n    <t:foundation><t:fcsOrder><t:order>"
        f"<t:notificationNumber>{number}</t:notificationNumber></t:order></t:fcsOrder>"
        f"</t:foundation>\n    <t:priceInfo><t:price>{price}</t:price>"
        f"<t:priceType>{price_type}</t:priceType><t:currency><t:code>{currency}</t:code>"
        f"</t:currency>{extra}</t:priceInfo>\n    <t:products><t:product>"
        f"<t:purchaseObjectSid>{sid}</t:purchaseObjectSid><t:KTRU>"
        f"<t:code>{product}</t:code></t:KTRU><t:name>Synthetic object</t:name>"
        f"<t:quantity>{quantity}</t:quantity><t:OKEI><t:code>796</t:code></t:OKEI>"
        f"<t:volumeSpecifyingMethod>QF</t:volumeSpecifyingMethod><t:sum>{price}</t:sum>"
        f"</t:product></t:products>\n    <t:deliveryPlaceInfo><c:byGARInfo><c:GARInfo>"
        f"<c:GARAddress>{region}, synthetic street</c:GARAddress></c:GARInfo>"
        f"</c:byGARInfo></t:deliveryPlaceInfo>\n    </contract></export>"
    ).encode()


def bundle(subsystem, number, *documents, not_downloaded=False):
    out = BytesIO()
    with ZipFile(out, "w") as zipped:
        for i, raw in enumerate(documents):
            zipped.writestr(f"source-{i}.xml", raw)
    first = _xml(
        "getDocsByReestrNumberResponse",
        f"<dataInfo><archiveUrl>{_URL.replace('&', '&amp;')}</archiveUrl></dataInfo>",
        namespace=_IP_NS,
    )
    field = "preparedNotDownloadPartInfo" if not_downloaded else "preparedPartInfo"
    ready = _xml(
        "getPreparedPartResponse",
        (
            f"<docRequestUid>{_REQ}</docRequestUid><dataInfo>"
            f"<isPreparationCompleted>true</isPreparationCompleted><{field}>"
            f"<dsUid>{_DS}</dsUid><url>{_URL.replace('&', '&amp;')}</url>"
            f"</{field}></dataInfo>"
        ),
        namespace=_IP_NS,
        ref=_POLL,
    )
    return OfficialBundle(
        subsystem,
        number,
        NOW,
        NOW,
        _REQ,
        hashlib.sha256(first).hexdigest(),
        hashlib.sha256(ready).hexdigest(),
        (first, ready),
        (out.getvalue(),),
    )


def qualify(*, notice=None, contract=None, extra_contracts=(), extra_notices=()):
    return qualify_contract(
        "tenant-a",
        bundle("RGK", REGISTRY, contract or contract_xml(), *extra_contracts),
        bundle("PRIZ", NUMBER, notice or notice_xml(), *extra_notices),
        CATALOG,
    )


def test_strict_real_namespace_profiles_and_direct_source_sid_form_a_nominal_observation():
    result = qualify()
    assert result.qualification_reasons == ("SOURCE_CURRENT_HISTORY_UNCONFIRMED",)
    assert result.current_result.value is None
    assert result.notice_lot_volume_link.value is result.rub_nominal_totals.value is True
    assert result.initial.value == Decimal("1000") and result.final.value == Decimal("700")
    assert result.price_basis == "RUB_NOMINAL_DECLARED_SIGNED_TOTALS"
    assert (
        result.concluded_at.value is None
        and result.concluded_date.value.isoformat() == "2026-10-20"
    )
    assert result.region.value == "г. Москва" and result.unit.value == "796"
    assert result.region.supporting_sources[0].document_id == CATALOG.catalog_sha256


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"sid": "999"}, "WHOLE_SOURCE_OBJECT_SCOPE_NOT_BOUND"),
        ({"quantity": "11"}, "SOURCE_OBJECT_QUANTITY_UNIT_OR_PRODUCT_CHANGED"),
        ({"product": "other"}, "SOURCE_OBJECT_QUANTITY_UNIT_OR_PRODUCT_CHANGED"),
        ({"price_type": "MP"}, "FIXED_CONTRACT_PRICE_NOT_CONFIRMED"),
        ({"currency": "USD"}, "CONTRACT_NATIVE_RUB_NOT_CONFIRMED"),
        ({"region": "Московская область"}, "CONTRACT_NOTICE_DELIVERY_REGION_NOT_BOUND"),
        ({"extra": "<t:rightToConcludeContractPriceInfo/>"}, "FORMULA_OR_RIGHT_TO_CONCLUDE_PRICE"),
        ({"extra": "<t:priceFormula>x</t:priceFormula>"}, "FORMULA_OR_RIGHT_TO_CONCLUDE_PRICE"),
    ],
)
def test_inapplicable_source_cannot_generate_verified_history(change, reason):
    result = qualify(contract=contract_xml(**change))
    assert result.current_result.value is None and reason in result.qualification_reasons


def test_source_day_ambiguity_does_not_select_the_previous_notice_revision():
    result = qualify(extra_notices=(notice_xml(version=2, published="2026-10-20T00:30:00Z"),))
    assert "NOTICE_VERSION_AT_SIGN_DATE_AMBIGUOUS" in result.qualification_reasons
    assert result.notice_lot_volume_link.value is None


def test_contract_changes_in_region_foundation_or_product_scope_invalidate_original():
    for changes in [
        {"region": "Московская область"},
        {"product": "other"},
        {"number": "3" * 19},
        {"sign": "2026-10-19"},
    ]:
        changed = contract_xml(version=1, **changes)
        result = qualify(extra_contracts=(changed,))
        assert "CONTRACT_COMMERCIAL_SCOPE_CHANGED" in result.qualification_reasons


def test_duplicate_conflicting_revisions_gaps_and_annulments_are_not_ignored():
    assert (
        "CONTRACT_VERSION_CONFLICT"
        in qualify(extra_contracts=(contract_xml(price="600"),)).qualification_reasons
    )
    assert (
        "CONTRACT_VERSION_GAP"
        in qualify(extra_contracts=(contract_xml(version=2),)).qualification_reasons
    )
    cancel = b'<export xmlns="http://zakupki.gov.ru/oos/export/1"><contractCancel/></export>'
    assert (
        "CONTRACT_ANNULMENT_IN_SOURCE" in qualify(extra_contracts=(cancel,)).qualification_reasons
    )
    assert (
        "NOTICE_VERSION_GAP"
        in qualify(extra_notices=(notice_xml(version=3),)).qualification_reasons
    )


def test_fixed_total_must_cover_whole_scope_not_an_individual_unit_or_partial_sum():
    bad = contract_xml().replace(b"<t:sum>700</t:sum>", b"<t:sum>70</t:sum>")
    assert "WHOLE_NOMINAL_TOTAL_SCOPE_MISMATCH" in qualify(contract=bad).qualification_reasons
    no_qty = notice_xml().replace(
        b"<e:quantityUndefined>false</e:quantityUndefined>",
        b"<e:quantityUndefined>true</e:quantityUndefined>",
    )
    assert "NOTICE_QUANTITY_DEFINITION_UNKNOWN" in qualify(notice=no_qty).qualification_reasons


def test_bundle_requires_every_part_but_ready_not_downloaded_parts_are_valid():
    good = bundle("RGK", REGISTRY, contract_xml(), not_downloaded=True)
    good.validate()
    with pytest.raises(ValueError, match="PARTS"):
        replace(good, archives=(good.archives[0], good.archives[0])).validate()
    with pytest.raises(ValueError, match="BINDING"):
        replace(good, initial_sha256="a" * 64).validate()


@pytest.mark.parametrize(
    "raw",
    [
        b'<!DOCTYPE export [<!ENTITY x "boom">]><export/>',
        b"<export>\x00</export>",
    ],
)
def test_unsafe_xml_is_rejected_before_interpretation(raw):
    with pytest.raises(ValueError, match="UNSAFE"):
        contract_result(raw, "source.xml")
    with pytest.raises(ValueError, match="UNSAFE"):
        bundle("RGK", REGISTRY, raw).xml_documents()


def test_namespace_and_scalar_ambiguity_do_not_supply_a_price_or_source_identity():
    n = notice_xml().replace(b"<b:code>RUB</b:code>", b"<b:code>RUB</b:code><b:code>USD</b:code>")
    with pytest.raises(ValueError, match="DUPLICATE"):
        notice_market(n, "notice.xml")
    wrong = notice_xml().replace(b"http://zakupki.gov.ru/oos/common/1", b"urn:wrong")
    assert not notice_market(wrong, "notice.xml").items


@pytest.mark.parametrize(
    "suffix",
    [
        "<t:isInvalid>true</t:isInvalid>",
        "<t:isInvalid>unrecognized</t:isInvalid>",
    ],
)
def test_invalid_contract_flags_in_any_revision_do_not_become_current(suffix):
    for version in [0, 1]:
        raw = contract_xml(version=version).replace(
            b"</contract>", suffix.encode() + b"</contract>"
        )
        result = qualify(contract=raw) if version == 0 else qualify(extra_contracts=(raw,))
        assert result.current_result.value is None
        assert "CONTRACT_INVALID_IN_SOURCE" in result.qualification_reasons


def test_undefined_contract_quantity_and_notice_formula_never_provide_fixed_totals():
    raw = contract_xml().replace(
        b"</t:products>", b"<t:quantityUndefined>true</t:quantityUndefined></t:products>"
    )
    assert "CONTRACT_UNDEFINED_VOLUME_NOT_SUPPORTED" in qualify(contract=raw).qualification_reasons
    raw = notice_xml().replace(
        b"</e:maxPriceInfo>",
        b"<e:isContractPriceFormula>true</e:isContractPriceFormula></e:maxPriceInfo>",
    )
    assert "NOTICE_FORMULA_PRICE_NOT_SUPPORTED" in qualify(notice=raw).qualification_reasons


def test_extreme_external_versions_are_bounded_and_never_imply_contiguous_history():
    enormous = 999999999999999999999
    result = qualify(extra_contracts=(contract_xml(version=enormous),))
    assert "CONTRACT_VERSION_GAP" in result.qualification_reasons
    result = qualify(extra_notices=(notice_xml(version=enormous),))
    assert "NOTICE_VERSION_GAP" in result.qualification_reasons
    assert result.current_result.value is None


def test_fetch_preserves_service_error_stage_and_code_without_printing_token(monkeypatch):
    import asyncio

    from procurement.sources import eis_contract_sync as module
    from procurement.sources.eis_feed_sync import EisSyncError

    async def no_delay(_):
        pass

    monkeypatch.setattr(module.asyncio, "sleep", no_delay)
    monkeypatch.setattr(module, "uuid4", lambda: _REQ)
    good = bundle("RGK", REGISTRY, contract_xml())
    for stage in ("INITIAL", "PREPARED"):
        name = "getDocsByReestrNumberResponse" if stage == "INITIAL" else "getPreparedPartResponse"
        error = _xml(
            name,
            (f"<docRequestUid>{_REQ}</docRequestUid>" if stage == "PREPARED" else "")
            + ("<dataInfo>" if stage == "INITIAL" else "")
            + "<errorInfo><code>13</code><message>limit</message></errorInfo>"
            + ("</dataInfo>" if stage == "INITIAL" else ""),
            namespace=_IP_NS,
        )

        class Transport:
            def __init__(self, replies):
                self.replies = iter(replies)

            async def post(self, xml):
                return 200, next(self.replies)

            async def download(self, url, token):
                pytest.fail("service refusal must not initiate archive download")

        with pytest.raises(EisSyncError) as caught:
            asyncio.run(
                module.fetch_official_bundle(
                    Transport([error] if stage == "INITIAL" else [good.responses[0], error]),
                    "synthetic-contract-token",
                    subsystem="RGK",
                    number=REGISTRY,
                )
            )
        assert caught.value.source_error.phase == stage
        assert caught.value.source_error.service_code == 13
        assert "synthetic-contract-token" not in str(caught.value)


def test_fetch_accepts_ready_parts_not_yet_downloaded_and_retains_only_responses(monkeypatch):
    import asyncio

    from procurement.sources import eis_contract_sync as module

    async def no_delay(_):
        pass

    monkeypatch.setattr(module.asyncio, "sleep", no_delay)
    monkeypatch.setattr(module, "uuid4", lambda: _REQ)
    expected = bundle("RGK", REGISTRY, contract_xml(), not_downloaded=True)

    class Transport:
        def __init__(self):
            self.replies = iter(expected.responses)

        async def post(self, xml):
            return 200, next(self.replies)

        async def download(self, url, token):
            return 200, expected.archives[0]

    actual = asyncio.run(
        module.fetch_official_bundle(
            Transport(),
            "synthetic-contract-token",
            subsystem="RGK",
            number=REGISTRY,
        )
    )
    assert actual.responses == expected.responses and actual.archives == expected.archives
    assert all(b"synthetic-contract-token" not in raw for raw in actual.responses)


def test_goods_notice_may_declare_numeric_quantity_without_work_service_method():
    numeric = notice_xml().replace(
        b"<c:volumeSpecifyingMethod>QF</c:volumeSpecifyingMethod>", b"<c:type>PRODUCT</c:type>"
    )
    assert "FIXED_PRODUCT_VOLUME_NOT_CONFIRMED" not in qualify(notice=numeric).qualification_reasons
    for bad in (
        numeric.replace(b"PRODUCT", b"WORK"),
        numeric.replace(b"<c:type>PRODUCT</c:type>", b""),
        numeric.replace(
            b"<c:type>PRODUCT</c:type>", b"<c:type>PRODUCT</c:type><c:volumeSpecifyingMethod/>"
        ),
        numeric.replace(
            b"<c:type>PRODUCT</c:type>",
            b"<c:type>PRODUCT</c:type><c:volumeSpecifyingMethod>VTF</c:volumeSpecifyingMethod>",
        ),
        numeric.replace(
            b"<c:value>10</c:value>", b"<c:value>10</c:value><c:undefined>true</c:undefined>"
        ),
    ):
        assert "FIXED_PRODUCT_VOLUME_NOT_CONFIRMED" in qualify(notice=bad).qualification_reasons
    undefined = numeric.replace(b"<e:quantityUndefined>false", b"<e:quantityUndefined>true")
    assert "NOTICE_QUANTITY_DEFINITION_UNKNOWN" in qualify(notice=undefined).qualification_reasons


def current_cards():
    from dataclasses import replace

    import test_eis_contract_cards as cards

    def aligned(html):
        return (
            html.replace(cards.REGISTRY, REGISTRY)
            .replace(cards.NOTICE, NUMBER)
            .replace("9 007 199 254 740 993,01", "700,00")
            .replace("270 000,00", "1 000,00")
            .replace("23.10.2026", "20.10.2026")
        )

    contract = cards.snapshot(aligned(cards.contract_html()))
    notice = cards.snapshot(aligned(cards.documents_html()), kind="documents")
    result = []
    for c in (contract, notice):
        result.append(
            replace(
                c,
                url=c.url.replace(cards.REGISTRY, REGISTRY).replace(cards.NOTICE, NUMBER),
                final_url=c.final_url.replace(cards.REGISTRY, REGISTRY).replace(
                    cards.NOTICE, NUMBER
                ),
                requested_at=NOW,
                checked_at=NOW,
                headers=(("Content-Type", "text/html"), ("Date", "Sun, 25 Oct 2026 12:00:00 GMT")),
            )
        )
    return tuple(result)


def test_current_cards_confirm_observed_currentness_without_asserting_complete_entity_history():
    c, n = current_cards()
    result = qualify_contract(
        "tenant-a",
        bundle("RGK", REGISTRY, contract_xml()),
        bundle("PRIZ", NUMBER, notice_xml()),
        CATALOG,
        contract_card=c,
        notice_card=n,
    )
    assert result.current_result.value is True and not result.qualification_reasons
    assert "complete entity history UNKNOWN" in result.current_result.source.locator


def test_current_cards_cannot_override_version_time_or_scope_conflicts():
    from datetime import timedelta

    c, n = current_cards()
    for cc, nn, raw, reason in (
        (
            replace(c, content=c.content.replace("Версия".encode(), b"Version")),
            n,
            contract_xml(),
            None,
        ),
        (
            replace(c, content=c.content.replace("Версия № 0".encode(), "Версия № 1".encode())),
            n,
            contract_xml(),
            "SOURCE_CURRENT_CARD_MISMATCH",
        ),
        (
            c,
            replace(n, content=n.content.replace(b"versionNumber=1", b"versionNumber=2")),
            contract_xml(),
            "SOURCE_CURRENT_CARD_MISMATCH",
        ),
        (
            replace(
                c,
                requested_at=NOW + timedelta(minutes=11),
                checked_at=NOW + timedelta(minutes=11),
                headers=(("Content-Type", "text/html"), ("Date", "Sun, 25 Oct 2026 12:11:00 GMT")),
            ),
            n,
            contract_xml(),
            "SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED",
        ),
        (c, n, contract_xml(quantity="11"), "SOURCE_OBJECT_QUANTITY_UNIT_OR_PRODUCT_CHANGED"),
    ):
        if reason is None:
            with pytest.raises(ValueError):
                qualify_contract(
                    "tenant-a",
                    bundle("RGK", REGISTRY, raw),
                    bundle("PRIZ", NUMBER, notice_xml()),
                    CATALOG,
                    contract_card=cc,
                    notice_card=nn,
                )
        else:
            result = qualify_contract(
                "tenant-a",
                bundle("RGK", REGISTRY, raw),
                bundle("PRIZ", NUMBER, notice_xml()),
                CATALOG,
                contract_card=cc,
                notice_card=nn,
            )
            assert result.current_result.value is None and reason in result.qualification_reasons


def test_public_card_capture_retains_safe_metadata_and_respects_shared_cooldown(
    monkeypatch, tmp_path
):
    import asyncio
    import sys
    from types import ModuleType, SimpleNamespace
    from typing import ClassVar

    browser_api = ModuleType("playwright.async_api")
    browser_api.Error = RuntimeError
    browser_api.TimeoutError = TimeoutError
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", browser_api)

    from procurement.sources.eis_contract_sync import CardCaptureError, capture_current_card

    monkeypatch.setenv("EIS_BROWSER_STATE_DIR", str(tmp_path))
    from procurement.sources import eis_public

    monkeypatch.setattr(eis_public, "_public_browser_proxy", lambda: None)
    launched = []

    class Response:
        status = 200
        headers: ClassVar = {
            "content-type": "text/html",
            "date": "Sun, 25 Oct 2026 12:00:00 GMT",
            "age": "0",
            "set-cookie": "not-retained-secret",
        }
        request = SimpleNamespace(redirected_from=None)

        async def body(self):
            return b"<html>synthetic contract source</html>"

    class Page:
        url = ""

        async def goto(self, url, **kwargs):
            self.url = url
            return Response()

    class Browser:
        async def new_page(self, *, accept_downloads):
            assert not accept_downloads
            return Page()

        async def close(self):
            pass

    async def launch(**kwargs):
        assert "ignore_https_errors" not in kwargs
        launched.append(kwargs)
        return Browser()

    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=launch))

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(browser_api, "async_playwright", Playwright, raising=False)
    card = asyncio.run(capture_current_card(number=REGISTRY, kind="CONTRACT"))
    assert card.http_status == 200 and card.url == card.final_url and len(launched) == 1
    assert not any("not-retained-secret" in value for _, value in card.headers)
    with pytest.raises(CardCaptureError, match="COOLDOWN") as caught:
        asyncio.run(capture_current_card(number=REGISTRY, kind="CONTRACT"))
    assert caught.value.retry_at is not None and len(launched) == 1

    monkeypatch.setenv("EIS_BROWSER_STATE_DIR", str(tmp_path / "separate-error-case"))

    async def broken_launch(**kwargs):
        raise RuntimeError("net::ERR_PROXY_CONNECTION_FAILED untrusted-secret-suffix")

    class BrokenPlaywright(Playwright):
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=broken_launch))

    monkeypatch.setattr(browser_api, "async_playwright", BrokenPlaywright)
    with pytest.raises(CardCaptureError) as failed:
        asyncio.run(capture_current_card(number=REGISTRY, kind="CONTRACT"))
    assert failed.value.phase == "PUBLIC_CARD"
    assert failed.value.network_code == "ERR_PROXY_CONNECTION_FAILED"
    assert "untrusted-secret-suffix" not in str(failed.value)
    import traceback

    assert "untrusted-secret-suffix" not in "".join(traceback.format_exception(failed.value))


def test_repeated_identical_delivery_addresses_do_not_exhaust_distinct_address_budget():
    raw = contract_xml()
    start = raw.index(b"<c:byGARInfo>")
    end = raw.index(b"</c:byGARInfo>") + len(b"</c:byGARInfo>")
    repeated = raw[:start] + raw[start:end] * 200 + raw[end:]
    result = qualify(contract=repeated)
    assert result.region.value == "г. Москва"
    assert result.notice_lot_volume_link.value is True
    over_limit = raw[:start] + raw[start:end] * 2001 + raw[end:]
    with pytest.raises(ValueError, match="REFERENCE_LIMIT"):
        qualify(contract=over_limit)


@pytest.mark.parametrize("value", ["", "garbled", "true", "1"])
@pytest.mark.parametrize(
    "path,reason",
    [
        ("isInvalid", "CONTRACT_INVALID_IN_SOURCE"),
        ("quantityUndefined", "CONTRACT_UNDEFINED_VOLUME_NOT_SUPPORTED"),
        ("maxPriceAndPriceFormulaSpecified", "FORMULA_OR_RIGHT_TO_CONCLUDE_PRICE"),
        ("conclusionContractSt95Ch17.1", "REPLACEMENT_CONTRACT_NOT_ORIGINAL_AWARD"),
    ],
)
def test_present_unconfirmed_boolean_never_means_false(path, reason, value):
    node = f"<t:{path}>{value}</t:{path}>".encode()
    raw = contract_xml()
    closing = (
        b"</t:products>"
        if path == "quantityUndefined"
        else b"</t:priceInfo>"
        if path == "maxPriceAndPriceFormulaSpecified"
        else b"</contract>"
    )
    result = contract_result(raw.replace(closing, node + closing), "synthetic.xml")
    assert reason in result.reasons


@pytest.mark.parametrize("value", ["", "garbled", "true", "1"])
def test_present_unconfirmed_notice_formula_flag_blocks(value):
    node = f"<e:isContractPriceFormula>{value}</e:isContractPriceFormula>".encode()
    raw = notice_xml().replace(b"</e:maxPriceInfo>", node + b"</e:maxPriceInfo>")
    assert "NOTICE_FORMULA_PRICE_NOT_SUPPORTED" in notice_market(raw, "synthetic.xml").reasons


def _with_format(raw, prefix, value):
    characteristic = (
        f"<{prefix}:characteristics><{prefix}:characteristicsUsingReferenceInfo>"
        f"<{prefix}:name>Формат</{prefix}:name><{prefix}:type>1</{prefix}:type>"
        f"<{prefix}:kind>1</{prefix}:kind><{prefix}:values><{prefix}:value>"
        f"<{prefix}:qualityDescription>{value}</{prefix}:qualityDescription>"
        f"</{prefix}:value></{prefix}:values>"
        f"</{prefix}:characteristicsUsingReferenceInfo></{prefix}:characteristics>"
    ).encode()
    return raw.replace(f"</{prefix}:KTRU>".encode(), characteristic + f"</{prefix}:KTRU>".encode())


def test_same_ktru_different_characteristics_never_bind_or_share_market_key():
    notice = _with_format(notice_xml(), "c", "A4")
    good = _with_format(contract_xml(), "t", "A4")
    changed = _with_format(contract_xml(), "t", "A3")
    assert qualify(notice=notice, contract=good).notice_lot_volume_link.value is True
    invalid = qualify(notice=notice, contract=changed)
    assert invalid.notice_lot_volume_link.value is None
    assert "SOURCE_PRODUCT_CHARACTERISTICS_NOT_BOUND" in invalid.qualification_reasons
    from procurement.storage.eis_contract_results import homogeneous_scope

    first = notice_market(notice, "n.xml").items
    second = notice_market(_with_format(notice_xml(), "c", "A3"), "n.xml").items
    assert homogeneous_scope(first)[0] != homogeneous_scope(second)[0]
    assert any(
        "characteristics" in source.locator for source in first[0].product_key.supporting_sources
    )
    assert qualify(notice=notice).notice_lot_volume_link.value is None


@pytest.mark.parametrize(
    "case", ["qualitative_numeric_fields", "unknown_values_child", "empty_kind"]
)
def test_malformed_characteristic_semantics_never_disappear(case):
    raw = _with_format(notice_xml(), "c", "A4")
    if case == "qualitative_numeric_fields":
        raw = raw.replace(b"</c:value>", b"<c:valueFormat>A</c:valueFormat><c:OKEI/></c:value>")
    elif case == "unknown_values_child":
        raw = raw.replace(
            b"</c:values>",
            b"<c:unknownSemanticField>contradiction</c:unknownSemanticField></c:values>",
        )
    else:
        raw = raw.replace(b"<c:kind>1</c:kind>", b"<c:kind/>")
    result = qualify(notice=raw, contract=_with_format(contract_xml(), "t", "A4"))
    assert result.current_result.value is None
    assert "SOURCE_PRODUCT_CHARACTERISTICS_UNSUPPORTED" in result.qualification_reasons
