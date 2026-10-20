from __future__ import annotations

import asyncio
import base64
import io
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from procurement.sources import supplier_captcha_browser as c
from procurement.sources import supplier_serp_browser as headed
from procurement.sources.supplier_serp import SearchEngine, build_supplier_query, source_url

QUERY = build_supplier_query("Бумага офисная")


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


class _Mouse:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls

    async def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))

    async def wheel(self, x: int, y: int) -> None:
        self.calls.append(("wheel", x, y))


class _Keyboard:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls

    async def type(self, text: str) -> None:
        self.calls.append(("type", text))

    async def press(self, key: str) -> None:
        self.calls.append(("key", key))


class _Page:
    def __init__(self, markup: str = "unusual traffic") -> None:
        self.url = source_url(SearchEngine.BING, QUERY)
        self.markup = markup
        self.calls: list[tuple[object, ...]] = []
        self.mouse = _Mouse(self.calls)
        self.keyboard = _Keyboard(self.calls)

    async def content(self) -> str:
        return self.markup

    async def evaluate(self, expression: str) -> str | None:
        assert str(c.MAX_DOM_BYTES) in expression and "outerHTML" in expression
        return self.markup if len(self.markup.encode()) <= c.MAX_DOM_BYTES else None


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1280, 720), "white").save(output, "JPEG", quality=70)
    return output.getvalue()


class _Cdp:
    async def send(self, method: str, payload: object) -> object:
        assert method == "Page.captureScreenshot"
        assert isinstance(payload, dict) and payload["clip"] == {
            "x": 0,
            "y": 0,
            "width": 1280,
            "height": 720,
            "scale": 1,
        }
        return {"data": base64.b64encode(_jpeg()).decode("ascii")}


def _fake_browser(page: _Page, cleaned: asyncio.Event):
    @asynccontextmanager
    async def open_browser(session: object, profile: Path, root: Path):
        del profile, root
        session.current_http_status = 200
        session.manual_navigation_count = 1
        try:
            yield c._BrowserHandle(page=page, cdp=_Cdp())
        finally:
            cleaned.set()

    return open_browser


async def _wait_status(
    manager: c.CaptchaBrowserManager,
    session_id: object,
    expected: c.CaptchaSessionStatus,
) -> c.CaptchaSessionView:
    for _ in range(100):
        view = await manager.status("tenant-a", "actor-a", session_id)
        if view.status == expected:
            return view
        await asyncio.sleep(0.005)
    raise AssertionError(f"session did not reach {expected}")


def test_manual_allowlist_is_exact_public_https_and_captcha_only() -> None:
    exact = source_url(SearchEngine.GOOGLE, QUERY)
    assert c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        exact + "&hl=ru",
        "document",
        navigation=True,
        main_frame=True,
    )
    assert c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        "https://www.google.com/sorry/index?continue=opaque",
        "document",
        navigation=True,
        main_frame=True,
    )
    assert c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        "https://www.google.com/recaptcha/api2/anchor?k=public",
        "document",
        navigation=True,
        main_frame=False,
    )
    assert c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        "https://www.gstatic.com/recaptcha/releases/a/script.js",
        "script",
        navigation=False,
        main_frame=False,
    )
    assert c.manual_request_allowed(
        SearchEngine.YANDEX,
        QUERY,
        "https://smartcaptcha.yandexcloud.net/captcha.js",
        "script",
        navigation=False,
        main_frame=False,
    )
    for url in (
        "http://www.google.com/search?q=x",
        "https://127.0.0.1/search",
        "https://accounts.google.com/login",
        "https://www.google.com/search?q=other",
        "https://supplier.ru/offer",
    ):
        assert not c.manual_request_allowed(
            SearchEngine.GOOGLE,
            QUERY,
            url,
            "document",
            navigation=True,
            main_frame=True,
        )
    assert not c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        exact,
        "websocket",
        navigation=False,
        main_frame=False,
    )
    assert not c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        "https://www.google.com/offer/page",
        "document",
        navigation=True,
        main_frame=False,
    )
    assert not c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        "https://www.google.com/search?q=other",
        "xhr",
        navigation=False,
        main_frame=False,
    )
    assert not c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        "https://www.google.com/search?q=other",
        "xhr",
        navigation=False,
        main_frame=False,
        method="POST",
    )
    assert not c.manual_request_allowed(
        SearchEngine.GOOGLE,
        QUERY,
        exact,
        "document",
        navigation=True,
        main_frame=True,
        method="POST",
    )


def test_input_models_reject_out_of_view_or_unbounded_values() -> None:
    for model, payload in (
        (c.ClickInput, {"x": 1280, "y": 0}),
        (c.ClickInput, {"x": 0, "y": 720}),
        (c.TypeInput, {"text": "x" * 129}),
        (c.TypeInput, {"text": "line\nbreak"}),
        (c.KeyInput, {"key": "Control+L"}),
        (c.WheelInput, {"delta_y": 7201}),
    ):
        with pytest.raises(ValidationError):
            model(**payload)


def test_manual_reservation_preserves_cooldowns_and_returns_exact_hashes(tmp_path: Path) -> None:
    profile = headed.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    headed._private_dir(profile)
    now = datetime.now(UTC)
    global_path, tenant_path, global_scope, tenant_scope = c._pacing_paths(
        tmp_path, profile, SearchEngine.BING
    )
    cooldown = now + timedelta(hours=1)
    headed._write_state(
        global_path,
        global_scope,
        now - timedelta(seconds=1),
        cooldown,
        cooldown_reason="BLOCKED",
    )
    headed._write_state(
        tenant_path,
        tenant_scope,
        now - timedelta(seconds=1),
        cooldown,
        cooldown_reason="BLOCKED",
    )
    snapshots = c._manual_reserve(tmp_path, profile, SearchEngine.BING, now)
    assert snapshots == (c._file_sha256(global_path), c._file_sha256(tenant_path))
    assert headed._state(global_path, global_scope)[1] == cooldown
    assert headed._state(tenant_path, tenant_scope)[1] == cooldown
    assert c._manual_reserve(tmp_path, profile, SearchEngine.BING, now) is None


def test_manual_reservation_rejects_rate_limit_and_legacy_unknown(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    cooldown = now + timedelta(minutes=15)
    for company, engine, reason, rate_limit in (
        ("rate-limited", SearchEngine.BING, "RATE_LIMITED", cooldown),
        ("legacy-unknown", SearchEngine.GOOGLE, None, None),
    ):
        profile = headed.profile_directory(tmp_path, company, engine)
        headed._private_dir(profile)
        global_path, tenant_path, global_scope, tenant_scope = c._pacing_paths(
            tmp_path, profile, engine
        )
        headed._write_state(
            global_path,
            global_scope,
            now - timedelta(seconds=1),
            cooldown,
            cooldown_reason=reason,
            rate_limit_until=rate_limit,
        )
        headed._write_state(
            tenant_path,
            tenant_scope,
            now - timedelta(seconds=1),
            cooldown,
            cooldown_reason=reason,
            rate_limit_until=rate_limit,
        )
        assert c._manual_reserve(tmp_path, profile, engine, now) is None


def test_browser_temp_stays_short_with_long_persistent_root(tmp_path: Path) -> None:
    long_root = tmp_path.joinpath(*(["persistent-state-segment"] * 12))
    long_root.mkdir(parents=True)
    temp = c._private_temp()
    try:
        assert not temp.is_relative_to(long_root)
        assert temp.parent == c._temp_parent()
        assert temp.name.startswith("syu-cap-") and len(temp.name) <= 24
        assert temp in c._OWNED_TEMP_PATHS
        if c.os.name != "nt":
            assert temp.stat().st_mode & 0o777 == 0o700
    finally:
        assert c._safe_remove_temp(temp)
    assert not temp.exists() and temp not in c._OWNED_TEMP_PATHS

    unrelated = tmp_path / "syu-cap-not-owned"
    unrelated.mkdir()
    assert not c._safe_remove_temp(unrelated)
    assert unrelated.is_dir()


@async_test
async def test_prepare_browser_sets_exact_click_and_screenshot_viewport() -> None:
    calls: list[tuple[object, ...]] = []

    class Page:
        url = "about:blank"

        async def set_viewport_size(self, size: dict[str, int]) -> None:
            calls.append(("viewport", size))

    page = Page()

    class Session:
        async def send(self, method: str, payload: object = None) -> None:
            calls.append((method, payload))

    class Context:
        def __init__(self) -> None:
            self.pages = [page]

        async def new_cdp_session(self, selected: object) -> Session:
            assert selected is page
            calls.append(("page-cdp",))
            return Session()

    context = Context()

    class Browser:
        def __init__(self) -> None:
            self.contexts = [context]

        async def new_browser_cdp_session(self) -> Session:
            return Session()

    selected_context, selected_page, _ = await c._prepare_browser(Browser())
    assert selected_context is context and selected_page is page
    assert calls == [
        ("Browser.setDownloadBehavior", {"behavior": "deny"}),
        ("viewport", {"width": 1280, "height": 720}),
        ("page-cdp",),
        ("Network.enable", None),
        ("Network.setBypassServiceWorker", {"bypass": True}),
    ]


@async_test
async def test_start_is_nonblocking_single_slot_and_owner_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, cleaned = _Page(), asyncio.Event()
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(page, cleaned))
    manager = c.CaptchaBrowserManager(tmp_path)
    run_id = uuid4()
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, run_id)
    assert view.status == "STARTING" and view.run_id == run_id
    assert "query" not in view.model_dump()
    with pytest.raises(RuntimeError, match="CAPTCHA_BROWSER_BUSY"):
        await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.WAITING)
    for company, actor in (("tenant-b", "actor-a"), ("tenant-a", "actor-b")):
        with pytest.raises(LookupError, match="CAPTCHA_SESSION_NOT_FOUND"):
            await manager.status(company, actor, view.session_id)
    cancelled = await manager.cancel("tenant-a", "actor-a", view.session_id)
    assert cancelled.status == "CANCELLED" and cleaned.is_set()


@async_test
async def test_frame_and_human_input_are_serialized_bounded_and_rate_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, cleaned = _Page(), asyncio.Event()
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(page, cleaned))
    manager = c.CaptchaBrowserManager(tmp_path)
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.WAITING)
    frame = await manager.frame("tenant-a", "actor-a", view.session_id)
    assert (frame.mime_type, frame.width, frame.height) == ("image/jpeg", 1280, 720)
    assert len(base64.b64decode(frame.data)) <= c.MAX_JPEG_BYTES
    with pytest.raises(RuntimeError, match="CAPTCHA_FRAME_RATE_LIMITED"):
        await manager.frame("tenant-a", "actor-a", view.session_id)
    await manager.input(
        "tenant-a", "actor-a", view.session_id, c.ClickInput(x=1279, y=719)
    )
    with pytest.raises(RuntimeError, match="CAPTCHA_INPUT_RATE_LIMITED"):
        await manager.input(
            "tenant-a", "actor-a", view.session_id, c.KeyInput(key="Enter")
        )
    await asyncio.sleep(c.INPUT_INTERVAL_SECONDS)
    await manager.input(
        "tenant-a", "actor-a", view.session_id, c.WheelInput(delta_y=300)
    )
    await asyncio.sleep(c.INPUT_INTERVAL_SECONDS)
    await manager.input(
        "tenant-a", "actor-a", view.session_id, c.TypeInput(text="human response")
    )
    assert page.calls == [
        ("click", 1279, 719),
        ("wheel", 0, 300),
        ("type", "human response"),
    ]
    await manager.shutdown()
    assert cleaned.is_set()


@async_test
async def test_false_verify_stays_waiting_then_verified_proof_closes_and_unlocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, cleaned = _Page(), asyncio.Event()
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(page, cleaned))
    manager = c.CaptchaBrowserManager(tmp_path)
    run_id = uuid4()
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, run_id)
    await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.WAITING)
    false = await manager.verify("tenant-a", "actor-a", view.session_id)
    assert false.status == "WAITING" and false.reason_code == "ACCESS_BLOCKED"
    with pytest.raises(RuntimeError, match="CAPTCHA_PROOF_UNAVAILABLE"):
        await manager.proof("tenant-a", "actor-a", view.session_id)

    page.markup = (
        '<input id="sb_form_q" value="'
        + QUERY
        + '"><li class="b_algo"><h2><a href="https://supplier.ru/item">'
        + 'Supplier</a></h2><div class="b_caption"><p>Public result</p></div></li>'
    )
    verified = await manager.verify("tenant-a", "actor-a", view.session_id)
    assert verified.status == "VERIFIED" and verified.reason_code is None and cleaned.is_set()
    proof = await manager.proof("tenant-a", "actor-a", view.session_id)
    assert proof.run_id == run_id and proof.attempt.status == "COMPLETED"
    assert proof.content == page.markup.encode() and proof.manual_navigation_count == 1
    assert proof.pacing_sha256 and proof.dom_sha256 == proof.attempt.dom_sha256
    profile = headed.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    with headed._lease(profile / "profile.lock"):
        pass


@async_test
async def test_subresource_429_stops_session_and_persists_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, cleaned = _Page(), asyncio.Event()

    @asynccontextmanager
    async def rate_limited_browser(session: object, profile: Path, root: Path):
        del profile, root
        session.current_http_status = 200
        session.manual_navigation_count = 1
        request = SimpleNamespace(
            is_navigation_request=lambda: False,
            frame=object(),
        )
        c._record_response(session, page, SimpleNamespace(request=request, status=429))
        try:
            yield c._BrowserHandle(page=page, cdp=_Cdp())
        finally:
            cleaned.set()

    monkeypatch.setattr(c, "_open_manual_browser", rate_limited_browser)
    manager = c.CaptchaBrowserManager(tmp_path)
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    failed = await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.FAILED)
    assert failed.reason_code == "RATE_LIMITED" and cleaned.is_set()
    profile = headed.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    _, tenant_path, _, tenant_scope = c._pacing_paths(tmp_path, profile, SearchEngine.BING)
    _, cooldown = headed._state(tenant_path, tenant_scope)
    assert cooldown is not None and cooldown > datetime.now(UTC)
    assert c._cooldown_metadata(tenant_path)[1] == cooldown


@async_test
async def test_startup_429_is_persisted_before_profile_lease_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def startup_429(session: object, profile: Path, root: Path):
        del profile, root
        session.rate_limited = True
        session.stop.set()
        raise RuntimeError("synthetic startup failure")
        yield  # pragma: no cover

    mark_calls = 0
    original_mark = headed._mark

    def transient_mark(*args: object, **kwargs: object) -> None:
        nonlocal mark_calls
        mark_calls += 1
        if mark_calls == 1:
            raise FileExistsError("synthetic pacing contention")
        original_mark(*args, **kwargs)

    monkeypatch.setattr(c, "_open_manual_browser", startup_429)
    monkeypatch.setattr(headed, "_mark", transient_mark)
    manager = c.CaptchaBrowserManager(tmp_path)
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    failed = await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.FAILED)
    assert failed.reason_code == "RATE_LIMITED" and mark_calls == 2
    profile = headed.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    _, tenant_path, _, tenant_scope = c._pacing_paths(tmp_path, profile, SearchEngine.BING)
    _, cooldown = headed._state(tenant_path, tenant_scope)
    assert cooldown is not None and cooldown > datetime.now(UTC)
    with headed._lease(profile / "profile.lock"):
        pass


@async_test
async def test_verify_rate_limit_is_terminal_and_oversize_dom_stays_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, cleaned = _Page(), asyncio.Event()
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(page, cleaned))
    manager = c.CaptchaBrowserManager(tmp_path)
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.WAITING)
    page.markup = "x" * (c.MAX_DOM_BYTES + 1)
    oversized = await manager.verify("tenant-a", "actor-a", view.session_id)
    assert oversized.status == "WAITING" and oversized.reason_code == "DOM_LIMIT"
    page.markup = "rate limited"
    manager._sessions[view.session_id].current_http_status = 429
    limited = await manager.verify("tenant-a", "actor-a", view.session_id)
    assert limited.status == "FAILED" and limited.reason_code == "RATE_LIMITED"
    assert cleaned.is_set()


@async_test
async def test_expiration_waits_for_cleanup_and_releases_single_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_cleaned = asyncio.Event()
    monkeypatch.setattr(c, "SESSION_SECONDS", 0.03)
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(_Page(), first_cleaned))
    manager = c.CaptchaBrowserManager(tmp_path)
    first = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    expired = await _wait_status(manager, first.session_id, c.CaptchaSessionStatus.EXPIRED)
    assert expired.status == "EXPIRED" and first_cleaned.is_set()

    second_cleaned = asyncio.Event()
    monkeypatch.setattr(
        c, "_open_manual_browser", _fake_browser(_Page(), second_cleaned)
    )
    second = await manager.start("tenant-b", "actor-b", SearchEngine.BING, QUERY, uuid4())
    assert second.status == "STARTING"
    await manager.shutdown()


@async_test
async def test_operation_deadline_is_checked_and_stalled_cdp_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, cleaned = _Page(), asyncio.Event()
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(page, cleaned))
    manager = c.CaptchaBrowserManager(tmp_path)
    view = await manager.start("tenant-a", "actor-a", SearchEngine.BING, QUERY, uuid4())
    await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.WAITING)
    manager._sessions[view.session_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(RuntimeError, match="CAPTCHA_SESSION_EXPIRED"):
        await manager.frame("tenant-a", "actor-a", view.session_id)
    await _wait_status(manager, view.session_id, c.CaptchaSessionStatus.EXPIRED)
    assert cleaned.is_set()

    class SlowCdp:
        async def send(self, method: str, payload: object) -> object:
            del method, payload
            await asyncio.sleep(1)
            return {}

    second_cleaned = asyncio.Event()
    monkeypatch.setattr(c, "_open_manual_browser", _fake_browser(_Page(), second_cleaned))
    monkeypatch.setattr(c, "OPERATION_SECONDS", 0.01)
    second = await manager.start("tenant-b", "actor-b", SearchEngine.GOOGLE, QUERY, uuid4())
    for _ in range(100):
        second_view = await manager.status("tenant-b", "actor-b", second.session_id)
        if second_view.status == c.CaptchaSessionStatus.WAITING:
            break
        await asyncio.sleep(0.005)
    manager._sessions[second.session_id].handle.cdp = SlowCdp()  # type: ignore[union-attr]
    with pytest.raises(RuntimeError, match="CAPTCHA_FRAME_FAILED"):
        await manager.frame("tenant-b", "actor-b", second.session_id)
    await manager.shutdown()


@async_test
async def test_cancelled_cleanup_finishes_before_returning() -> None:
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Context:
        async def __aexit__(self, *args: object) -> None:
            started.set()
            await release.wait()
            finished.set()

    task = asyncio.create_task(c._close_browser_context(Context()))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and not finished.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()

