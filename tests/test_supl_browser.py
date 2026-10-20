"""Предложения площадки остаются неподтверждёнными кандидатами."""

import pytest

from procurement.sources.supl_browser import SUPL_PUMPS_URL, parse_supl_catalog, supl_covers


def card(
    title="Центробежный насос EMS210/2.2",
    url="/tsentrobezhnyij-nasos-ems210-2-2-p34928760/",
    seller_url="https://supl.biz/profiles/2341314/",
):
    return (
        '<section itemscope itemtype="http://schema.org/Product" id="proposal-preview-34928760">'
        f'<h3 itemprop="name"><a itemprop="url" href="{url}">{title}</a></h3>'
        f'<a href="{seller_url}">ООО АКВАСТРОНГ РУС</a>'
        "</section>"
    )


def html(contents=None):
    return ("<html><body>" + (contents or card()) + "</body></html>").encode()


def test_only_structured_offer_and_seller_are_parsed():
    content = '<a href="https://evil.invalid/">Реклама</a>'.encode() + html()
    rows = parse_supl_catalog(content)
    assert len(rows) == 1
    assert rows[0].title == "Центробежный насос EMS210/2.2"
    assert rows[0].seller_name == "ООО АКВАСТРОНГ РУС"
    assert rows[0].seller_url == "https://supl.biz/profiles/2341314/"
    assert rows[0].source_item_index == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/nasos-p1/", "/catalog/other/", "/nasos-p1/?q=x",
        "/nasos-p1/#tab", "/../nasos-p1/", "/nasos-%2e%2e-p1/",
        "http://supl.biz/nasos-p1/", "https://user:pass@supl.biz/nasos-p1/",
    ],
)
def test_foreign_or_unexpected_product_url_rejected(url):
    with pytest.raises(ValueError):
        parse_supl_catalog(html(card(url=url)))


@pytest.mark.parametrize(
    "seller_url",
    ["https://evil.invalid/profiles/1/", "https://supl.biz/profiles/1/?x=1", "/orders/1/"],
)
def test_untrusted_seller_url_rejected(seller_url):
    with pytest.raises(ValueError):
        parse_supl_catalog(html(card(seller_url=seller_url)))


@pytest.mark.parametrize(
    "content",
    [b"<html>captcha</html>", html(card() + card()), html(card().replace('itemprop="url"', "")),
     html()[:-15], b"x" * (3 * 1024 * 1024 + 1)],
    ids=["challenge", "duplicate", "missing-url", "unclosed", "oversized"],
)
def test_changed_schema_is_not_empty_success(content):
    with pytest.raises(ValueError):
        parse_supl_catalog(content)


def test_only_pump_query_is_covered():
    assert supl_covers("Насос центробежный")
    assert not supl_covers("Ноутбук")
    assert SUPL_PUMPS_URL.endswith("-category4240/")
