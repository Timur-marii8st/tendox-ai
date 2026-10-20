"""Browser preview: блокировки, provenance, tenant isolation и реальный DOM."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from procurement.sources import browser_catalog as module
from procurement.sources.browser_catalog import (
    BrowserAttempt,
    BrowserOptions,
    BrowserSite,
    BrowserStatus,
    classify_page,
    cursor_path,
    preview_browser_catalog,
    profile_directory,
    profile_lease,
)
from procurement.sources.servermall import SERVERMALL_HPE_GEN12_URL


def _html() -> str:
    graph = {
        "@graph": [
            {
                "@type": "OfferCatalog",
                "itemListElement": [
                    {
                        "@type": "Offer",
                        "name": "HPE DL360 Gen12",
                        "url": "https://servermall.ru/catalog/servers/dl360/",
                    }
                ],
            }
        ]
    }
    return (
        '<html><body>Каталог<script type="application/ld+json">'
        + json.dumps(graph)
        + ('</script><div style="height:6000px">Карточки</div></body></html>')
    )


def _base() -> BrowserAttempt:
    return BrowserAttempt(
        company_id="test-company",
        site=BrowserSite.SERVERMALL,
        query="DL360",
        source_url=SERVERMALL_HPE_GEN12_URL,
        status=BrowserStatus.SOURCE_ERROR,
        observed_at=datetime.now(UTC),
        query_mode="TITLE_TERMS",
    )


@pytest.mark.parametrize(
    ("status", "url", "title", "text", "expected"),
    [
        (403, "/", "", "", BrowserStatus.BLOCKED),
        (429, "/", "", "", BrowserStatus.RATE_LIMITED),
        (401, "/", "", "", BrowserStatus.AUTH_REQUIRED),
        (503, "/", "", "", BrowserStatus.SOURCE_ERROR),
        (200, "/showcaptcha?token=secret", "", "", BrowserStatus.BLOCKED),
        (200, "/", "Just a moment...", "", BrowserStatus.BLOCKED),
        (200, "/", "", "Подтвердите, что вы не робот", BrowserStatus.BLOCKED),
        (200, "/", "", "Verify you are human", BrowserStatus.BLOCKED),
        (200, "/login", "", "", BrowserStatus.AUTH_REQUIRED),
        (200, "/", "Каталог", "captcha integration documentation", None),
    ],
)
def test_challenge_is_not_zero_results(status, url, title, text, expected) -> None:
    assert classify_page(status, "https://example.com" + url, title, text) == expected


def test_cursor_stays_inside_viewport_and_slows_at_ends() -> None:
    points = cursor_path((0, 0), (900, 600), rng=random.Random(42))
    assert points[-1][:2] == (900, 600)
    assert all(0 <= x <= 900 and 0 <= y <= 600 and 0 < delay < 0.1 for x, y, delay in points)
    assert points[0][0] < points[len(points) // 2][0] - points[len(points) // 2 - 1][0]
    assert cursor_path((0, 0), (900, 600), rng=random.Random(43)) != points


def test_profiles_are_company_and_site_scoped(tmp_path: Path) -> None:
    a = profile_directory(tmp_path, "a", BrowserSite.SERVERMALL)
    b = profile_directory(tmp_path, "b", BrowserSite.SERVERMALL)
    c = profile_directory(tmp_path, "a", BrowserSite.YANDEX_BUSINESS)
    malicious = profile_directory(tmp_path, "../../outside", BrowserSite.SERVERMALL)
    assert len({a, b, c, malicious}) == 4
    assert malicious.is_relative_to(tmp_path.resolve())
    with profile_lease(a), pytest.raises(FileExistsError), profile_lease(a):
        pytest.fail("concurrent profile access")
    assert not (a / "preview.lock").exists()


def test_cooldown_survives_new_options_and_does_not_call_browser(tmp_path, monkeypatch) -> None:
    calls = []

    async def launch(directory, base, options):
        calls.append(directory)
        return base.model_copy(
            update={
                "status": BrowserStatus.BLOCKED,
                "retry_at": datetime.now(UTC) + timedelta(minutes=15),
            }
        )

    monkeypatch.setattr(module, "_launch", launch)

    def run(company):
        return asyncio.run(
            preview_browser_catalog(
                company_id=company,
                site=BrowserSite.SERVERMALL,
                query="DL360",
                options=BrowserOptions(profile_root=tmp_path),
            )
        )

    first = run("company-a")
    assert first.status == BrowserStatus.BLOCKED
    second = run("company-a")
    assert second.status == BrowserStatus.COOLDOWN
    assert second.retry_at == first.retry_at
    assert run("company-b").status == BrowserStatus.BLOCKED
    assert len(calls) == 2


def test_busy_profile_does_not_erase_another_process_lock(tmp_path) -> None:
    directory = profile_directory(tmp_path, "a", BrowserSite.SERVERMALL)
    with profile_lease(directory):
        result = asyncio.run(
            preview_browser_catalog(
                company_id="a",
                site=BrowserSite.SERVERMALL,
                query="DL360",
                options=BrowserOptions(profile_root=tmp_path),
            )
        )
        assert result.status == BrowserStatus.PROFILE_BUSY
        assert (directory / "preview.lock").exists()


def test_unmapped_query_does_not_create_profile(tmp_path) -> None:
    result = asyncio.run(
        preview_browser_catalog(
            company_id="a",
            site=BrowserSite.YANDEX_BUSINESS,
            query="Сервер",
            options=BrowserOptions(profile_root=tmp_path),
        )
    )
    assert result.status == BrowserStatus.QUERY_NOT_COVERED
    assert list(tmp_path.iterdir()) == []


def test_corrupt_cooldown_fails_closed(tmp_path, monkeypatch) -> None:
    directory = profile_directory(tmp_path, "a", BrowserSite.SERVERMALL)
    directory.mkdir(parents=True)
    (directory / "cooldown.json").write_text('{"company_id":"b"}', encoding="utf-8")
    monkeypatch.setattr(module, "_launch", lambda *args: pytest.fail("must not access network"))
    result = asyncio.run(
        preview_browser_catalog(
            company_id="a",
            site=BrowserSite.SERVERMALL,
            query="DL360",
            options=BrowserOptions(profile_root=tmp_path),
        )
    )
    assert result.reason == "PROFILE_STATE_UNAVAILABLE"
    assert not (directory / "preview.lock").exists()


def test_retry_after_respects_date_and_seconds() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    assert module._retry_at("3600", now) == now + timedelta(hours=1)
    assert module._retry_at("Tue, 22 Sep 2026 02:00:00 GMT", now) == now + timedelta(hours=2)
    assert module._retry_at("invalid", now) > now


@pytest.mark.parametrize(
    ("suffix", "allowed"),
    [
        ("", True),
        ("?hid=15774673&rs=opaque-session-value", True),
        ("?hid=999&rs=x", False),
        ("?hid=15774673&hid=999&rs=x", False),
        ("?hid=15774673&page=2", False),
        ("?rs=x", False),
        ("#different", False),
    ],
)
def test_yandex_redirect_is_bound_to_same_category(suffix, allowed) -> None:
    assert (
        module.catalog_navigation_allowed(
            BrowserSite.YANDEX_BUSINESS, module.YANDEX_BUSINESS_PUMPS_URL + suffix
        )
        is allowed
    )
    assert (
        module.catalog_navigation_allowed(BrowserSite.SERVERMALL, "https://evil.example/") is False
    )


def test_timeout_cancels_browser_and_releases_lease(tmp_path, monkeypatch) -> None:
    closed = []
    original_wait = asyncio.wait_for

    async def launch(directory, base, options):
        try:
            await asyncio.sleep(10)
        finally:
            closed.append(True)

    async def short_wait(coro, timeout):
        return await original_wait(coro, timeout=0.01)

    monkeypatch.setattr(module, "_launch", launch)
    monkeypatch.setattr(module.asyncio, "wait_for", short_wait)
    result = asyncio.run(
        preview_browser_catalog(
            company_id="a",
            site=BrowserSite.SERVERMALL,
            query="DL360",
            options=BrowserOptions(profile_root=tmp_path),
        )
    )
    assert result.status == BrowserStatus.TIMEOUT
    assert closed == [True]
    directory = profile_directory(tmp_path, "a", BrowserSite.SERVERMALL)
    assert not (directory / "preview.lock").exists()
    assert (directory / "cooldown.json").exists()


@pytest.fixture
def browser_page():
    """Все запросы перехвачены: тесты никогда не обращаются к реальной площадке."""
    playwright = pytest.importorskip("playwright.async_api")

    async def run(html, status=200, *, query="DL360", motion=False, site=BrowserSite.SERVERMALL):
        async with playwright.async_playwright() as runtime:
            try:
                browser = await runtime.chromium.launch()
            except playwright.Error:
                pytest.skip("Chromium is not installed; run playwright install chromium")
            try:
                context = await browser.new_context()
                await context.route(
                    "**/*",
                    lambda route: route.fulfill(
                        status=status,
                        content_type="text/html",
                        body=html,
                        headers={"Retry-After": "3600"} if status == 429 else {},
                    ),
                )
                page = await context.new_page()
                base = _base().model_copy(
                    update={"query": query, "site": site, "source_url": module._URLS[site]}
                )
                result = await module._run_page(page, base, BrowserOptions(natural_motion=motion))
                return result, await page.content(), await page.evaluate("window.motionCount || 0")
            finally:
                await browser.close()

    return run


def test_real_browser_delayed_hydration_and_dom_evidence(browser_page) -> None:
    html = (
        "<html><body><script>setTimeout(() => {document.body.innerHTML="
        + json.dumps(_html().split("<body>")[1].split("</body>")[0]).replace(
            "</script>", "<\\/script>"
        )
        + ";}, 700);</script></body></html>"
    )
    result, dom, _ = asyncio.run(browser_page(html))
    assert result.status == BrowserStatus.COMPLETED
    assert len(result.candidates) == 1
    assert result.candidates[0].suitability == "UNKNOWN"
    assert result.dom_sha256 == hashlib.sha256(dom.encode()).hexdigest()
    assert result.dom_byte_size == len(dom.encode())


@pytest.mark.parametrize("status", [403, 429])
def test_real_browser_http_refusal_wins_over_valid_cards(browser_page, status) -> None:
    result, _, _ = asyncio.run(browser_page(_html(), status))
    assert result.status == (BrowserStatus.BLOCKED if status == 403 else BrowserStatus.RATE_LIMITED)
    assert result.candidates == ()
    assert result.dom_sha256 is None
    assert result.retry_at is not None
    if status == 429:
        assert result.retry_at > datetime.now(UTC) + timedelta(minutes=59)


def test_real_browser_200_captcha_is_blocked(browser_page) -> None:
    result, _, _ = asyncio.run(browser_page(_html().replace("Каталог", "Verify you are human")))
    assert result.status == BrowserStatus.BLOCKED
    assert result.candidates == ()


def test_real_browser_no_matches_requires_valid_catalog(browser_page) -> None:
    result, _, _ = asyncio.run(browser_page(_html(), query="DL380"))
    assert result.status == BrowserStatus.COMPLETED
    assert result.candidates == ()
    assert result.dom_sha256 is not None


def test_real_browser_supl_category_preserves_seller_claim(browser_page) -> None:
    html = (
        '<html><head><meta charset="utf-8"></head><body>'
        '<section itemscope itemtype="http://schema.org/Product" '
        'id="proposal-preview-34928760"><h3 itemprop="name">'
        '<a itemprop="url" href="/tsentrobezhnyij-nasos-ems210-2-2-p34928760/">'
        'Центробежный насос EMS210/2.2</a></h3>'
        '<a href="https://supl.biz/profiles/2341314/">ООО АКВАСТРОНГ РУС</a>'
        '</section></body></html>'
    )
    result, _, _ = asyncio.run(
        browser_page(html, query="Насос центробежный EMS210/2.2", site=BrowserSite.SUPL_BIZ)
    )
    assert result.status == BrowserStatus.COMPLETED
    assert result.scanned_count == 1 and len(result.candidates) == 1
    assert result.candidates[0].seller_name == "ООО АКВАСТРОНГ РУС"
    assert result.candidates[0].seller_url == "https://supl.biz/profiles/2341314/"
    assert result.candidates[0].suitability == "UNKNOWN"
    assert result.candidates[0].source_sha256 == result.dom_sha256
    assert not module.catalog_navigation_allowed(
        BrowserSite.SUPL_BIZ, "https://supl.biz/proposals/search/?query=насос"
    )


def test_real_browser_motion_emits_events(browser_page) -> None:
    html = _html().replace(
        "<body>",
        "<body><script>window.motionCount=0;"
        "document.addEventListener('mousemove',()=>window.motionCount++);"
        "document.addEventListener('wheel',()=>window.motionCount++);</script>",
    )
    result, _, events = asyncio.run(browser_page(html, motion=True))
    assert result.status == BrowserStatus.COMPLETED
    assert events > 30


def test_real_browser_oversized_dom_is_not_empty_catalog(browser_page) -> None:
    result, _, _ = asyncio.run(browser_page("<html><body>" + "x" * (3 * 1024 * 1024) + "</body>"))
    assert result.status == BrowserStatus.SOURCE_CHANGED
    assert result.reason == "DOM_SIZE_LIMIT"


def test_real_browser_missing_schema_is_not_empty_results(browser_page) -> None:
    result, _, _ = asyncio.run(browser_page("<html><body>Каталог загружается</body></html>"))
    assert result.status == BrowserStatus.SOURCE_CHANGED
    assert result.reason == "CATALOG_SCHEMA_NOT_READY"
    assert result.candidates == ()
    assert result.dom_sha256 is None


@pytest.mark.parametrize("hid", ["15774673", "999"])
def test_real_browser_yandex_navigation_keeps_category_and_hides_rs(browser_page, hid) -> None:
    graph = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "item": {
                    "@type": "Product",
                    "name": "Насос",
                    "url": "https://market.yandex.ru/card/test/123",
                },
            }
        ],
    }
    html = (
        '<html><body><script type="application/ld+json">'
        + json.dumps(graph)
        + '</script><script>history.replaceState(null,"","?hid='
        + hid
        + '&rs=private-value");</script></body></html>'
    )
    result, _, _ = asyncio.run(browser_page(html, query="Насос", site=BrowserSite.YANDEX_BUSINESS))
    assert "private-value" not in result.model_dump_json()
    if hid == "15774673":
        assert result.status == BrowserStatus.COMPLETED
        assert len(result.candidates) == 1
        assert result.navigation_url_sha256 is not None
    else:
        assert result.status == BrowserStatus.SOURCE_CHANGED
        assert result.candidates == ()


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [(["--help"], 0), (["--company-id", "a", "--site", "servermall", "--query", ""], 2)],
)
def test_cli_handles_russian_help_and_errors_on_windows(arguments, expected) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "preview-browser-catalog.py"
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert result.returncode == expected, result.stderr
    assert "UnicodeEncodeError" not in result.stderr
