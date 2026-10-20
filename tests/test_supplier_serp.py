import base64
import hashlib
from datetime import UTC, datetime
from html import escape

import pytest
from pydantic import ValidationError

from procurement.sources import supplier_serp as s

QUERY = s.build_supplier_query("Бумага офисная")
NOW = datetime(2026, 10, 6, tzinfo=UTC)


def row(url: str, title: str = "Документ", snippet: str = "Без проверки") -> str:
    return (
        f'<li class="b_algo"><h2><a href="{escape(url)}">{title}</a></h2>'
        f'<div class="b_caption"><p>{snippet}</p></div></li>'
    )


def google_row(url: str, title: str = "Документ", snippet: str = "Без проверки") -> str:
    return (
        '<div class="g"><a href="'
        + escape(url)
        + '"><h3>'
        + title
        + '</h3></a><div class="VwiC3b">'
        + snippet
        + "</div></div>"
    )


def yandex_row(
    url: str, title: str = "Документ", snippet: str = "Без проверки", *, outer_anchor: bool = False
) -> str:
    heading = (
        f'<a href="{escape(url)}"><h2>{title}</h2></a>'
        if outer_anchor
        else f'<h2><a href="{escape(url)}">{title}</a></h2>'
    )
    return (
        '<li class="serp-item">'
        + heading
        + f'<div class="OrganicTextContentSpan">{snippet}</div></li>'
    )


def current_yandex_row(
    url: str,
    title: str = "Документ",
    snippet: str = "Без проверки",
    *,
    marker: str = "",
) -> str:
    return (
        '<li class="generated-hash" data-dspwk="row"><div class="Organic">'
        '<div class="OrganicTitle OrganicTitle_size_l" data-initer="OrganicHeader">'
        f'<a class="Link OrganicTitle-Link link" href="{escape(url)}">'
        '<div class="Favicon"></div><h2 class="OrganicTitle-LinkText">'
        f'<span class="OrganicTitleContentSpan" role="text">{title}</span>'
        "</h2></a></div>"
        '<div class="Organic-Subtitle"><a class="Path-Item" href="https://path.ru/">'
        "path.ru</a></div>"
        '<div class="Organic-ContentWrapper"><div class="OrganicText">'
        f'<span class="OrganicTextContentSpan" role="text">{snippet}</span>'
        f"</div></div>{marker}</div></li>"
    )


def parse(
    html: str, engine: s.SearchEngine = s.SearchEngine.BING, **kwargs: object
) -> s.EngineAttempt:
    return s.parse_supplier_serp(
        engine,
        QUERY,
        html.encode(),
        observed_at=NOW,
        final_url=str(kwargs.pop("final_url", s.source_url(engine, QUERY))),
        **kwargs,
    )


def test_query_public_name_only() -> None:
    assert s.build_supplier_query("  Бумага   офисная ") == QUERY
    for name in ("", "unknown", "неизвестно", "a" * 151, "name\nprivate", "name\x00", "x\u200b"):
        with pytest.raises(ValueError):
            s.build_supplier_query(name)
    with pytest.raises(ValueError):
        s.observe_supplier_serp("arbitrary private query")


def test_offline_redirect_dedup_rank_and_unknown_facts() -> None:
    url = "https://supplier.ru/catalog?q=paper"
    wrapped = "https://www.bing.com/ck/a?u=a1" + base64.urlsafe_b64encode(
        url.encode()
    ).decode().rstrip("=")
    html = row(wrapped) + row(url) + row("https://reference.ru/page", "Энциклопедия")
    attempt = parse(html)
    assert attempt.status == "COMPLETED"
    assert attempt.scanned_count == 3 and attempt.returned_count == 2
    assert [link.rank for link in attempt.links] == [1, 3]
    assert attempt.links[0].url == url
    assert attempt.links[1].role_status == "UNKNOWN"
    assert attempt.links[0].price_status == attempt.links[0].technical_status == "UNKNOWN"
    assert attempt.dom_sha256 == hashlib.sha256(html.encode()).hexdigest()
    assert attempt.links[1].locator == 'locator("li.b_algo").nth(2).locator("h2 a")'


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/x",
        "http://[::1]/",
        "http://192.168.1.1/",
        "https://host.local/",
        "https://host.lan/",
        "https://user:pass@public.ru/",
        "https://public.ru:443/",
        "javascript:alert(1)",
        "https://www.bing.com/search?q=x",
        "https://public.ru\\@localhost/",
        "file:///tmp/x",
        "https://www.bing.com/ck/a?u=a1!!!!",
        "https://internal/",
        "https://google.com/url?q=x",
    ],
)
def test_unsafe_links_do_not_become_evidence(url: str) -> None:
    result = parse(row(url))
    assert result.status == "SOURCE_CHANGED" and result.links == ()


def test_count_caps_and_text_caps() -> None:
    result = parse("".join(row(f"https://vendor{i}.ru/", "a" * 400, "b" * 1300) for i in range(14)))
    assert result.scanned_count == 14 and result.returned_count == 10 and result.truncated
    assert len(result.links[0].title) == 300 and len(result.links[0].snippet) == 1200


@pytest.mark.parametrize(
    ("html", "status", "expected"),
    [
        ("unusual traffic", 200, "BLOCKED"),
        ("подозрительный трафик", 200, "BLOCKED"),
        ("", 403, "BLOCKED"),
        ("", 429, "RATE_LIMITED"),
        ("", 500, "SOURCE_ERROR"),
        ('<li class="b_no">No results</li>', 200, "EMPTY"),
        ("<html></html>", 200, "SOURCE_CHANGED"),
    ],
)
def test_explicit_statuses(html: str, status: int, expected: str) -> None:
    assert parse(html, http_status=status).status == expected


def test_query_binding() -> None:
    assert (
        parse(
            row("https://vendor.ru/"),
            final_url=s.source_url(s.SearchEngine.BING, s.build_supplier_query("other")),
        ).reason_code
        == "QUERY_BINDING_INVALID"
    )
    assert (
        parse('<input id="sb_form_q" value="other">' + row("https://vendor.ru/")).reason_code
        == "QUERY_BINDING_INVALID"
    )
    assert (
        parse("", s.SearchEngine.GOOGLE, final_url="https://www.google.com/sorry/index").status
        == "BLOCKED"
    )


def test_google_known_organic_rows_redirects_and_unknown_facts() -> None:
    target = "https://supplier.ru/catalog?q=paper"
    wrapped = "/url?q=" + target.replace("?", "%3F").replace("=", "%3D") + "&sa=U"
    html = (
        f'<input name="q" value="{escape(QUERY)}">'
        '<div id="search"><div id="tads">'
        + google_row("https://advertiser.ru/", "Реклама")
        + "</div>"
        + google_row(wrapped, "Бумага от поставщика", "Публичный фрагмент")
        + google_row(target, "Дубликат")
        + "</div>"
    )
    attempt = parse(html, s.SearchEngine.GOOGLE)
    assert attempt.status == "COMPLETED"
    assert attempt.scanned_count == 3 and attempt.returned_count == 1
    assert attempt.links[0].rank == 2 and attempt.links[0].url == target
    assert attempt.links[0].snippet == "Публичный фрагмент"
    assert attempt.links[0].locator == 'locator("#search a:has(h3)").nth(1)'
    assert attempt.links[0].role_status == "UNKNOWN"
    assert attempt.links[0].price_status == attempt.links[0].technical_status == "UNKNOWN"


def test_yandex_known_organic_rows_redirects_and_original_rank() -> None:
    target = "https://supplier.ru/catalog?q=paper"
    wrapped = "https://yandex.ru/clck/jump?url=" + target.replace(":", "%3A").replace(
        "/", "%2F"
    ).replace("?", "%3F").replace("=", "%3D")
    html = (
        f'<input name="text" value="{escape(QUERY)}"><ol>'
        '<li class="serp-item" data-fast-name="direct"><h2>'
        '<a href="https://advertiser.ru/">Реклама</a></h2></li>'
        + yandex_row(wrapped, "Поставщик бумаги", "Публичный фрагмент", outer_anchor=True)
        + "</ol>"
    )
    attempt = parse(html, s.SearchEngine.YANDEX)
    assert attempt.status == "COMPLETED"
    assert attempt.scanned_count == 2 and attempt.returned_count == 1
    assert attempt.links[0].rank == 2 and attempt.links[0].url == target
    assert attempt.links[0].locator == (
        'locator("li.serp-item").nth(1).locator("a:has(h2)").first()'
    )
    assert attempt.links[0].snippet == "Публичный фрагмент"


def test_yandex_current_semantic_organic_layout() -> None:
    html = (
        '<ul aria-label="Результаты поиска"><li class="module">Навигация</li>'
        + current_yandex_row(
            "https://advertiser.ru/", "Реклама", marker='<span class="AdvLabel"></span>'
        )
        + current_yandex_row(
            "https://supplier.ru/catalog", "Поставщик бумаги", "Публичный фрагмент"
        ).replace(
            '<div class="Organic">',
            '<a class="widget" href="https://widget.ru/"><h2>Виджет</h2></a><div class="Organic">',
            1,
        )
        + "</ul>"
    )
    attempt = parse(html, s.SearchEngine.YANDEX)
    assert attempt.status == "COMPLETED"
    assert attempt.scanned_count == 3 and attempt.returned_count == 1
    assert attempt.links[0].rank == 3
    assert attempt.links[0].url == "https://supplier.ru/catalog"
    assert attempt.links[0].title == "Поставщик бумаги"
    assert attempt.links[0].snippet == "Публичный фрагмент"
    assert attempt.links[0].locator == (
        "locator(\"ul[aria-label='Результаты поиска'] > li\").nth(2)"
        '.locator(":scope > div.Organic > '
        "div.OrganicTitle[data-initer='OrganicHeader'] > "
        'a.OrganicTitle-Link:has(> h2.OrganicTitle-LinkText)").first()'
    )
    assert len(attempt.links[0].locator) > 150


def test_yandex_current_layout_rejects_multiple_semantic_title_anchors() -> None:
    duplicate = (
        '<a class="OrganicTitle-Link" href="https://other.ru/">'
        '<h2 class="OrganicTitle-LinkText">Другой заголовок</h2></a>'
    )
    row_html = current_yandex_row("https://supplier.ru/").replace(
        "</h2></a></div>", "</h2></a>" + duplicate + "</div>", 1
    )
    attempt = parse(
        '<ul aria-label="Результаты поиска">' + row_html + "</ul>",
        s.SearchEngine.YANDEX,
    )
    assert attempt.status == "SOURCE_CHANGED"
    assert attempt.reason_code == "ORGANIC_STRUCTURE_UNVERIFIED"
    assert attempt.links == ()


def test_yandex_current_layout_requires_exact_semantic_title_chain() -> None:
    html = (
        '<ul aria-label="Результаты поиска"><li><div class="Organic">'
        '<div class="OrganicTitle"><a class="OrganicTitle-Link" href="https://supplier.ru/">'
        '<h2 class="OrganicTitle-LinkText">Lookalike</h2></a></div></div></li></ul>'
    )
    attempt = parse(html, s.SearchEngine.YANDEX)
    assert attempt.status == "SOURCE_CHANGED"
    assert attempt.reason_code == "ORGANIC_STRUCTURE_UNVERIFIED"
    assert attempt.links == ()


@pytest.mark.parametrize(
    ("engine", "html"),
    [
        (s.SearchEngine.GOOGLE, '<div id="search"><a href="https://vendor.ru/">plain</a></div>'),
        (s.SearchEngine.GOOGLE, '<h3><a href="https://vendor.ru/">outside</a></h3>'),
        (s.SearchEngine.YANDEX, '<li><h2><a href="https://vendor.ru/">x</a></h2></li>'),
        (
            s.SearchEngine.YANDEX,
            '<li class="serp-item"><h3><a href="https://vendor.ru/">x</a></h3></li>',
        ),
    ],
)
def test_unknown_google_yandex_structures_remain_unknown(engine: s.SearchEngine, html: str) -> None:
    attempt = parse(html, engine)
    assert attempt.status == "SOURCE_CHANGED"
    assert attempt.reason_code == "ORGANIC_STRUCTURE_UNVERIFIED"
    assert attempt.links == () and attempt.scanned_count == 0


@pytest.mark.parametrize(
    ("engine", "html"),
    [
        (
            s.SearchEngine.GOOGLE,
            '<div id="topstuff">Your search did not match any documents</div>',
        ),
        (
            s.SearchEngine.YANDEX,
            '<div class="EmptySearchResults">По вашему запросу ничего не найдено</div>',
        ),
    ],
)
def test_only_known_empty_markers_are_empty(engine: s.SearchEngine, html: str) -> None:
    assert parse(html, engine).status == "EMPTY"
    assert parse(f"<p>{html}</p>", engine).status == "EMPTY"
    phrase_only = (
        "Your search did not match any documents"
        if engine == s.SearchEngine.GOOGLE
        else "По вашему запросу ничего не найдено"
    )
    assert parse(phrase_only, engine).status == "SOURCE_CHANGED"


@pytest.mark.parametrize("engine", (s.SearchEngine.GOOGLE, s.SearchEngine.YANDEX))
def test_engine_input_mismatch_and_captcha_dominate_organic(engine: s.SearchEngine) -> None:
    healthy = (
        '<div id="search">' + google_row("https://vendor.ru/") + "</div>"
        if engine == s.SearchEngine.GOOGLE
        else yandex_row("https://vendor.ru/")
    )
    field = "q" if engine == s.SearchEngine.GOOGLE else "text"
    assert parse(f'<input name="{field}" value="other">' + healthy, engine).reason_code == (
        "QUERY_BINDING_INVALID"
    )
    blocked = parse(healthy + '<div class="g-recaptcha"></div>', engine)
    assert blocked.status == "BLOCKED" and blocked.links == ()


@pytest.mark.parametrize(
    ("engine", "html"),
    [
        (
            s.SearchEngine.GOOGLE,
            '<div id="search"><script>'
            + google_row("https://script.ru/")
            + "</script><div hidden>"
            + google_row("https://hidden.ru/")
            + "</div>"
            + google_row("https://visible.ru/")
            + "</div>",
        ),
        (
            s.SearchEngine.YANDEX,
            "<script>"
            + yandex_row("https://script.ru/")
            + '</script><ol><li class="serp-item sponsored"><h2>'
            '<a href="https://advertiser.ru/">ad</a></h2></li>'
            + yandex_row("https://visible.ru/")
            + "</ol>",
        ),
    ],
)
def test_scripts_hidden_and_sponsored_rows_are_not_links(engine: s.SearchEngine, html: str) -> None:
    attempt = parse(html, engine)
    assert attempt.status == "COMPLETED"
    assert [link.url for link in attempt.links] == ["https://visible.ru/"]


@pytest.mark.parametrize(
    ("engine", "html"),
    [
        (
            s.SearchEngine.GOOGLE,
            '<div id="search">'
            + google_row("/url?q=http%3A%2F%2F127.0.0.1%2Fprivate")
            + google_row("https://www.google.com/goto?url=opaque")
            + "</div>",
        ),
        (
            s.SearchEngine.YANDEX,
            yandex_row("https://yandex.ru/clck/jump?url=http%3A%2F%2Flocalhost%2Fprivate"),
        ),
    ],
)
def test_google_yandex_unsafe_or_opaque_redirects_are_not_evidence(
    engine: s.SearchEngine, html: str
) -> None:
    attempt = parse(html, engine)
    assert attempt.status == "SOURCE_CHANGED"
    assert attempt.links == () and attempt.scanned_count == 0


@pytest.mark.parametrize("engine", (s.SearchEngine.GOOGLE, s.SearchEngine.YANDEX))
def test_google_yandex_caps_preserve_original_container_rank(engine: s.SearchEngine) -> None:
    rows = [
        (
            google_row(f"https://vendor{i}.ru/")
            if engine == s.SearchEngine.GOOGLE
            else yandex_row(f"https://vendor{i}.ru/")
        )
        for i in range(51)
    ]
    html = (
        '<div id="search">' + "".join(rows) + "</div>"
        if engine == s.SearchEngine.GOOGLE
        else "".join(rows)
    )
    attempt = parse(html, engine)
    assert attempt.scanned_count == 50 and attempt.returned_count == 10 and attempt.truncated
    assert [link.rank for link in attempt.links] == list(range(1, 11))


def test_dom_bound_time_and_capture_binding() -> None:
    assert s.MAX_DOM_BYTES == 8 * 1024 * 1024
    at_limit_html = "a" * s.MAX_DOM_BYTES
    at_limit = parse(at_limit_html)
    assert at_limit.status == "SOURCE_CHANGED"
    assert at_limit.reason_code == "ORGANIC_STRUCTURE_UNVERIFIED"
    assert at_limit.byte_count == s.MAX_DOM_BYTES
    assert at_limit.dom_sha256 == hashlib.sha256(at_limit_html.encode()).hexdigest()
    oversized = parse("a" * (s.MAX_DOM_BYTES + 1))
    assert oversized.reason_code == "DOM_LIMIT" and oversized.dom_sha256 is None
    with pytest.raises(ValueError):
        s.parse_supplier_serp(
            s.SearchEngine.BING,
            QUERY,
            b"",
            final_url=s.source_url(s.SearchEngine.BING, QUERY),
            observed_at=datetime(2026, 1, 1),
        )
    attempts = [parse(" ", engine) for engine in s.ENGINES]
    batch = s._batch(QUERY, attempts, [b" "] * len(s.ENGINES))
    with pytest.raises(ValueError):
        s.SerpCapture(batch.batch, (b"changed", *(b" " for _ in s.ENGINES[1:])))
    with pytest.raises(ValidationError):
        s.SearchBatch(query=QUERY, attempts=tuple(reversed(attempts)), status="UNAVAILABLE")


def test_request_allowlist_no_candidate_navigation() -> None:
    def allowed(url: str, resource: str = "script", navigation: bool = False) -> bool:
        return s.request_allowed(
            s.SearchEngine.BING, QUERY, url, resource, navigation=navigation, main_frame=True
        )

    assert allowed("https://r.bing.com/asset.js")
    assert allowed(s.source_url(s.SearchEngine.BING, QUERY), "document", True)
    assert not allowed("https://supplier.ru/", "document", True)
    assert not allowed("https://bing.com.evil.ru/asset.js")
    assert not allowed("https://r.bing.com/image", "image")
    assert not allowed("https://www.bing.com/ck/a?u=anything", "document", True)


def test_browser_unavailable_preserves_all_engines_and_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    capture = s.observe_supplier_serp(QUERY, cooldowns=(s.SearchEngine.YANDEX,))
    assert tuple(a.engine for a in capture.batch.attempts) == s.ENGINES
    assert capture.batch.attempts[s.ENGINES.index(s.SearchEngine.YANDEX)].status == "COOLDOWN"
    assert capture.contents == (None,) * len(s.ENGINES)
    assert all(a.browser_navigation_count == 0 for a in capture.batch.attempts)
    assert "secret" not in capture.batch.model_dump_json()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scanned_count", True),
        ("returned_count", "1"),
        ("elapsed_ms", 90001),
        ("browser_navigation_count", True),
        ("truncated", 1),
        ("byte_count", 0),
        ("reason_code", "EXPLICIT_EMPTY"),
    ],
)
def test_strict_report_invariants(field: str, value: object) -> None:
    data = parse(row("https://vendor.ru/")).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        s.EngineAttempt.model_validate(data)


def test_script_challenge_words_are_not_visible_blocker() -> None:
    assert (
        parse('<script>const x="unusual traffic";</script>' + row("https://vendor.ru/")).status
        == "COMPLETED"
    )


@pytest.mark.parametrize(
    "cancel_phase", [None, "after_goto", "cleanup", "unexpected", "cleanup_error"]
)
def test_browser_sequence_retention_and_cooldown(
    monkeypatch: pytest.MonkeyPatch, cancel_phase: str | None
) -> None:
    import sys
    import types

    visits: list[str] = []
    closed: list[str] = []
    real_timeout = s.asyncio.timeout
    outer_timeout = None

    def timeout(delay: float) -> object:
        nonlocal outer_timeout
        context = real_timeout(delay)
        if delay == 75:
            outer_timeout = context
        return context

    async def expire_outer() -> None:
        assert outer_timeout is not None
        outer_timeout.reschedule(s.asyncio.get_running_loop().time())
        await s.asyncio.sleep(0.01)

    monkeypatch.setattr(s.asyncio, "timeout", timeout)

    class Page:
        url = ""
        main_frame = object()

        async def goto(self, url: str, **kwargs: object) -> object:
            self.url = url
            visits.append(url)
            return types.SimpleNamespace(status=200)

        async def evaluate(self, script: str) -> str:
            if cancel_phase == "unexpected":
                raise RuntimeError("unclassified post-dispatch error")
            if cancel_phase == "after_goto":
                await expire_outer()
            return row("https://vendor.ru/")

    class Context:
        async def new_page(self) -> Page:
            return Page()

        async def route(self, pattern: str, callback: object) -> None:
            assert pattern == "**/*"

        async def close(self) -> None:
            closed.append("context")
            if cancel_phase == "cleanup_error":
                raise RuntimeError("unclassified cleanup error")
            if cancel_phase == "cleanup":
                await expire_outer()

    class Browser:
        async def new_context(self, **kwargs: object) -> Context:
            assert kwargs == {"accept_downloads": False, "service_workers": "block"}
            return Context()

        async def close(self) -> None:
            closed.append("browser")

    class Chromium:
        async def launch(self, **kwargs: object) -> Browser:
            assert kwargs["headless"] is True
            return Browser()

    class Manager:
        async def __aenter__(self) -> object:
            return types.SimpleNamespace(chromium=Chromium())

        async def __aexit__(self, *args: object) -> None:
            pass

    fake = types.ModuleType("playwright.async_api")
    fake.async_playwright = Manager
    fake.TimeoutError = type("BrowserTimeout", (Exception,), {})
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    capture = s.observe_supplier_serp(QUERY, cooldowns=(s.SearchEngine.YANDEX,))
    if cancel_phase in {"after_goto", "cleanup"}:
        assert visits == [s.source_url(s.SearchEngine.BING, QUERY)]
        assert closed == ["context", "browser"]
        first = capture.batch.attempts[0]
        assert first.status == "TIMEOUT" and first.reason_code == "BATCH_TIMEOUT"
        assert first.browser_navigation_count == 1
        assert all(a.browser_navigation_count == 0 for a in capture.batch.attempts[1:])
        assert capture.contents == (None,) * len(s.ENGINES)
        return
    assert visits == [
        s.source_url(engine, QUERY) for engine in s.ENGINES if engine != s.SearchEngine.YANDEX
    ]
    assert closed == ["context"] * (len(s.ENGINES) - 1) + ["browser"]
    expected = (
        ["SOURCE_ERROR"] * len(s.ENGINES)
        if cancel_phase == "unexpected"
        else ["COMPLETED", "COOLDOWN", "SOURCE_CHANGED"]
    )
    expected[s.ENGINES.index(s.SearchEngine.YANDEX)] = "COOLDOWN"
    assert [a.status for a in capture.batch.attempts] == expected
    assert capture.contents[s.ENGINES.index(s.SearchEngine.YANDEX)] is None
    assert capture.batch.status == ("UNAVAILABLE" if cancel_phase == "unexpected" else "PARTIAL")
    assert capture.batch.attempts[0].browser_navigation_count == 1
    assert capture.batch.supplierpage_requests == 0


@pytest.mark.parametrize(
    "widget",
    [
        '<div id="captcha"></div>',
        '<div class="g-recaptcha"></div>',
        '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>',
    ],
)
def test_structural_challenge_dominates_organic_rows(widget: str) -> None:
    attempt = parse(widget + row("https://vendor.ru/"))
    assert attempt.status == "BLOCKED" and attempt.reason_code == "ACCESS_BLOCKED"
    assert attempt.links == () and attempt.scanned_count == 0 and not attempt.truncated


def test_success_requires_navigation_and_failures_cannot_claim_scan() -> None:
    data = parse(row("https://vendor.ru/")).model_dump()
    data["browser_navigation_count"] = 0
    with pytest.raises(ValidationError):
        s.EngineAttempt.model_validate(data)
    failed = parse("unusual traffic").model_dump()
    failed["scanned_count"] = 1
    with pytest.raises(ValidationError):
        s.EngineAttempt.model_validate(failed)


def test_unclassified_outer_failure_is_not_zero_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected(query: str, cooldowns: tuple[s.SearchEngine, ...]) -> s.SerpCapture:
        raise RuntimeError("post-dispatch report failure")

    monkeypatch.setattr(s, "_observe", unexpected)
    with pytest.raises(RuntimeError, match="post-dispatch"):
        s.observe_supplier_serp(QUERY)


def test_active_and_historical_engine_orders() -> None:
    assert s.ENGINES == (
        s.SearchEngine.BING,
        s.SearchEngine.YANDEX,
        s.SearchEngine.GOOGLE,
    )
    assert s.LEGACY_ENGINES == s.ENGINES
    assert s.HISTORICAL_EXPANDED_ENGINES == (
        s.SearchEngine.BING,
        s.SearchEngine.BRAVE,
        s.SearchEngine.DUCKDUCKGO,
        s.SearchEngine.MOJEEK,
        s.SearchEngine.YANDEX,
        s.SearchEngine.GOOGLE,
    )
    active = [parse(" ", engine) for engine in s.ENGINES]
    assert len(s._batch(QUERY, active, [b" "] * 3).batch.attempts) == 3
    historical = [
        s._failure(engine, QUERY, "SOURCE_ERROR", "SOURCE_ERROR", observed_at=NOW)
        for engine in s.HISTORICAL_EXPANDED_ENGINES
    ]
    assert s.SearchBatch(
        query=QUERY, attempts=tuple(historical), status="UNAVAILABLE"
    ).attempts == tuple(historical)


@pytest.mark.parametrize(
    "engine",
    (s.SearchEngine.BRAVE, s.SearchEngine.DUCKDUCKGO, s.SearchEngine.MOJEEK),
)
def test_historical_engines_are_disabled_for_io_and_parsing(engine: s.SearchEngine) -> None:
    url = s.source_url(engine, QUERY)
    assert not s.request_allowed(engine, QUERY, url, "document", navigation=True, main_frame=True)
    with pytest.raises(ValueError, match="ENGINE_DISABLED"):
        parse("<html></html>", engine)


def test_headed_configuration_requires_trusted_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", "/private/profiles")
    with pytest.raises(ValueError, match="BROWSER_CONFIG_INVALID"):
        s.observe_supplier_serp(QUERY)
    monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", "relative")
    with pytest.raises(ValueError, match="BROWSER_CONFIG_INVALID"):
        s.observe_supplier_serp(QUERY, company_id="tenant")


def test_headed_transport_preserves_parser_cooldown_and_navigation(monkeypatch, tmp_path):
    import sys
    import types

    calls = []
    content = (
        b'<html><li class="b_algo"><h2><a href="https://supplier.ru/">Paper</a></h2></li></html>'
    )

    async def capture(company_id, engine, query, *, root):
        calls.append((company_id, engine, query, str(root)))
        return types.SimpleNamespace(
            content=content if engine == s.SearchEngine.BING else None,
            final_url=s.source_url(engine, query),
            http_status=200,
            observed_at=NOW,
            elapsed_ms=100,
            navigation_count=1,
            status="CAPTURED" if engine == s.SearchEngine.BING else "BLOCKED",
        )

    monkeypatch.setitem(
        sys.modules,
        "procurement.sources.supplier_serp_browser",
        types.SimpleNamespace(capture_headed_serp=capture),
    )
    monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", str(tmp_path))
    result = s.observe_supplier_serp(
        QUERY, cooldowns=(s.SearchEngine.YANDEX,), company_id="tenant-a"
    )
    assert [a.status for a in result.batch.attempts] == ["COMPLETED", "COOLDOWN", "BLOCKED"]
    assert [a.browser_navigation_count for a in result.batch.attempts] == [1, 0, 1]
    assert result.contents == (content, None, None)
    assert len(calls) == 2 and all(c[0] == "tenant-a" for c in calls)
    assert result.batch.coverage == "UNKNOWN"
