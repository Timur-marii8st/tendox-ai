from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

from procurement.sources import supplier_serp_browser as b
from procurement.sources.supplier_serp import SearchEngine, build_supplier_query, source_url

QUERY = build_supplier_query("Бумага офисная")
NOW = datetime(2026, 10, 6, tzinfo=UTC)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def capture(status: b.CaptureStatus = "CAPTURED") -> b.HeadedSerpCapture:
    url = source_url(SearchEngine.BING, QUERY)
    return b.HeadedSerpCapture(
        engine=SearchEngine.BING,
        source_url=url,
        final_url=url,
        observed_at=NOW,
        http_status=200 if status == "CAPTURED" else None,
        content=b"<html>result</html>" if status == "CAPTURED" else None,
        status=status,
        navigation_count=1 if status == "CAPTURED" else 0,
        elapsed_ms=10,
        browser_version="Chrome/153",
    )


def test_profiles_are_stable_tenant_and_origin_scoped(tmp_path: Path) -> None:
    first = b.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    same = b.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    other = b.profile_directory(tmp_path, "tenant-b", SearchEngine.BING)
    google = b.profile_directory(tmp_path, "tenant-a", SearchEngine.GOOGLE)
    assert first == same and len(first.parent.name) == 64
    assert len(first.name) == 64 and first != other and first != google
    assert "tenant-a" not in str(first)
    with pytest.raises(ValueError):
        b.profile_directory(tmp_path, "", SearchEngine.BING)


def test_profile_lock_is_nonblocking_and_process_owned(tmp_path: Path) -> None:
    lock = tmp_path / "profile.lock"
    with (
        b._lease(lock),
        pytest.raises(FileExistsError, match="HEADED_PROFILE_BUSY"),
        b._lease(lock),
    ):
        pytest.fail("concurrent lease must not enter")
    with b._lease(lock):
        pass


@async_test
async def test_capture_reserves_durable_pacing_before_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def fake(*args: object, **kwargs: object) -> b.HeadedSerpCapture:
        nonlocal calls
        calls += 1
        return capture()

    monkeypatch.setattr(b, "_capture_with_processes", fake)
    first = await b.capture_headed_serp("tenant-a", SearchEngine.BING, QUERY, root=tmp_path)
    second = await b.capture_headed_serp("tenant-a", SearchEngine.BING, QUERY, root=tmp_path)
    assert first.status == "CAPTURED" and second.status == "COOLDOWN"
    assert calls == 1
    assert list(tmp_path.glob("state/global/*.json"))
    assert list(tmp_path.glob("profiles/*/*/pacing.json"))


def test_global_and_tenant_cooldowns_preserve_longest_window(tmp_path: Path) -> None:
    profile = b.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    assert b._reserve(tmp_path, profile, SearchEngine.BING, NOW)
    b._mark(tmp_path, profile, SearchEngine.BING, "RATE_LIMITED", NOW)
    assert not b._reserve(tmp_path, profile, SearchEngine.BING, NOW + timedelta(minutes=14))
    b._mark(tmp_path, profile, SearchEngine.BING, "BLOCKED", NOW)
    assert not b._reserve(tmp_path, profile, SearchEngine.BING, NOW + timedelta(minutes=59))
    assert b._reserve(tmp_path, profile, SearchEngine.BING, NOW + timedelta(hours=1, seconds=1))


def test_prelaunch_reservation_guarantees_navigation_spacing(tmp_path: Path) -> None:
    profile = b.profile_directory(tmp_path, "tenant-spacing", SearchEngine.BING)
    assert b._reserve(tmp_path, profile, SearchEngine.BING, NOW)
    assert not b._reserve(
        tmp_path,
        profile,
        SearchEngine.BING,
        NOW + timedelta(seconds=b.RESERVATION_SECONDS - 1),
    )
    assert b._reserve(
        tmp_path,
        profile,
        SearchEngine.BING,
        NOW + timedelta(seconds=b.RESERVATION_SECONDS + 1),
    )


def test_corrupt_or_wrong_scope_pacing_fails_closed(tmp_path: Path) -> None:
    profile = b.profile_directory(tmp_path, "tenant-a", SearchEngine.BING)
    assert b._reserve(tmp_path, profile, SearchEngine.BING, NOW)
    path = profile / "pacing.json"
    path.write_text(json.dumps({"version": b.STATE_VERSION, "scope": "other"}))
    with pytest.raises(ValueError, match="HEADED_PACING_STATE_INVALID"):
        b._reserve(tmp_path, profile, SearchEngine.BING, NOW + timedelta(minutes=1))


@async_test
async def test_disabled_engine_never_reaches_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> b.HeadedSerpCapture:
        raise AssertionError("browser must not run")

    monkeypatch.setattr(b, "_capture_with_processes", forbidden)
    with pytest.raises(ValueError, match="ENGINE_DISABLED"):
        await b.capture_headed_serp("tenant-a", SearchEngine.BRAVE, QUERY, root=tmp_path)


@async_test
async def test_post_navigation_failure_preserves_navigation_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failed(*args: object, **kwargs: object) -> b.HeadedSerpCapture:
        raise b._CaptureFailure(1)

    monkeypatch.setattr(b, "_capture_with_processes", failed)
    result = await b.capture_headed_serp("tenant-a", SearchEngine.BING, QUERY, root=tmp_path)
    assert result.status == "SOURCE_ERROR"
    assert result.navigation_count == 1 and result.content is None


@async_test
async def test_post_navigation_mark_lock_failure_is_not_reported_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def completed(
        engine: object,
        query: object,
        profile: object,
        observed: object,
        progress: dict[str, int],
    ) -> b.HeadedSerpCapture:
        progress["navigation_count"] = 1
        return capture("BLOCKED").__class__(
            **(
                capture("BLOCKED").__dict__
                | {"navigation_count": 1, "final_url": source_url(SearchEngine.BING, QUERY)}
            )
        )

    monkeypatch.setattr(b, "_capture_with_processes", completed)
    monkeypatch.setattr(
        b,
        "_mark",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileExistsError("busy")),
    )
    with pytest.raises(FileExistsError, match="busy"):
        await b.capture_headed_serp("tenant-mark", SearchEngine.BING, QUERY, root=tmp_path)


def test_chrome_arguments_are_headed_local_cdp_and_fixed(tmp_path: Path) -> None:
    args = b._chrome_args(Path("/trusted/chrome"), tmp_path / "profile")
    assert args[0] == str(Path("/trusted/chrome"))
    assert "--remote-debugging-address=127.0.0.1" in args
    assert "--remote-debugging-port=0" in args
    assert "--disable-background-networking" in args
    assert "--disable-component-extensions-with-background-pages" in args
    assert "--disable-extensions" in args
    assert any(item.startswith("--disable-features=ServiceWorker") for item in args)
    assert "--disable-blink-features=ServiceWorker" in args
    if getattr(b.os, "geteuid", lambda: -1)() == 0:
        assert "--no-sandbox" in args
    assert not any("headless" in item or "proxy" in item for item in args)
    assert "--no-startup-window" in args
    assert "about:blank" not in args


def test_browser_environment_excludes_runner_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    monkeypatch.setenv("HTTPS_PROXY", "secret-proxy")
    monkeypatch.setenv("PATH", "trusted-path")
    env = b._browser_environment(":77")
    assert env["PATH"] == "trusted-path" and env["DISPLAY"] == ":77"
    assert "DATABASE_URL" not in env and "HTTPS_PROXY" not in env


def test_service_worker_rejection_includes_private_bounded_urls() -> None:
    context = SimpleNamespace(
        service_workers=[SimpleNamespace(url="chrome-extension://abc/background.js")]
    )
    with pytest.raises(
        RuntimeError,
        match=r"PERSISTED_SERVICE_WORKER_FORBIDDEN:chrome-extension://abc/background.js",
    ):
        b._reject_service_workers(context)


def test_stale_devtools_file_is_removed_before_restart(tmp_path: Path) -> None:
    path = tmp_path / "DevToolsActivePort"
    path.write_text("4444\nstale")
    b._remove_stale_devtools(tmp_path)
    assert not path.exists()


def test_singleton_lock_is_detected_but_never_removed(tmp_path: Path) -> None:
    path = tmp_path / "SingletonLock"
    path.write_text("other-container")
    assert b._singleton_lock_present(tmp_path)
    assert path.read_text() == "other-container"


def test_captcha_redirect_detection_is_structural() -> None:
    assert b._captcha_redirect("https://www.google.com/sorry/index")
    assert b._captcha_redirect("https://yandex.ru/showcaptcha?x=1")
    assert not b._captcha_redirect("https://supplier.ru/apology-product")


@async_test
async def test_cdp_preparation_denies_downloads_before_using_blank_page() -> None:
    calls: list[tuple[str, object]] = []

    class Session:
        async def send(self, method: str, payload: object) -> None:
            calls.append((method, payload))

    page = SimpleNamespace(url="about:blank")
    context = SimpleNamespace(pages=[page])

    class Browser:
        def __init__(self) -> None:
            self.contexts = [context]

        async def new_browser_cdp_session(self) -> Session:
            return Session()

    selected_context, selected_page = await b._prepare_cdp_browser(Browser())
    assert calls == [("Browser.setDownloadBehavior", {"behavior": "deny"})]
    assert selected_context is context and selected_page is page


@async_test
async def test_cdp_preparation_creates_blank_page_after_no_startup_window() -> None:
    class Session:
        async def send(self, method: str, payload: object) -> None:
            pass

    page = SimpleNamespace(url="about:blank")

    class Context:
        def __init__(self) -> None:
            self.pages: list[object] = []

        async def new_page(self) -> object:
            return page

    context = Context()

    class Browser:
        contexts = (context,)

        async def new_browser_cdp_session(self) -> Session:
            return Session()

    selected_context, selected_page = await b._prepare_cdp_browser(Browser())
    assert selected_context is context and selected_page is page


@async_test
async def test_cdp_preparation_closes_and_rejects_restored_tabs() -> None:
    closed: list[str] = []

    class Session:
        async def send(self, method: str, payload: object) -> None:
            pass

    class Page:
        def __init__(self, url: str) -> None:
            self.url = url

        async def close(self) -> None:
            closed.append(self.url)

    pages = [Page("about:blank"), Page("https://restored.invalid/")]
    context = SimpleNamespace(pages=pages)

    class Browser:
        def __init__(self) -> None:
            self.contexts = [context]

        async def new_browser_cdp_session(self) -> Session:
            return Session()

    with pytest.raises(
        RuntimeError,
        match=r"PERSISTED_PAGE_STATE_INVALID:about:blank,https://restored.invalid/",
    ):
        await b._prepare_cdp_browser(Browser())
    assert closed == ["about:blank", "https://restored.invalid/"]


@async_test
async def test_attached_browser_closes_chrome_while_transport_is_alive() -> None:
    events: list[str] = []

    class Session:
        async def send(self, method: str) -> None:
            events.append(method)

    class Browser:
        async def new_browser_cdp_session(self) -> Session:
            events.append("new-session")
            return Session()

        async def close(self) -> None:
            events.append("browser.close")

    browser = Browser()

    class Chromium:
        async def connect_over_cdp(self, endpoint: str) -> Browser:
            events.append(f"connect:{endpoint}")
            return browser

    playwright = SimpleNamespace(chromium=Chromium())
    async with b._attached_browser(playwright, 4321) as attached:
        assert attached is browser
        events.append("yield")
    assert events == [
        "connect:http://127.0.0.1:4321",
        "yield",
        "new-session",
        "Browser.close",
        "browser.close",
    ]


@async_test
async def test_timeout_after_navigation_preserves_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def timeout(
        engine: object,
        query: object,
        profile: object,
        observed: object,
        progress: dict[str, int],
    ) -> b.HeadedSerpCapture:
        progress["navigation_count"] = 1
        raise TimeoutError

    monkeypatch.setattr(b, "_capture_with_processes", timeout)
    result = await b.capture_headed_serp("tenant-timeout", SearchEngine.BING, QUERY, root=tmp_path)
    assert result.status == "TIMEOUT" and result.navigation_count == 1


@async_test
async def test_timeout_after_known_captcha_redirect_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def timeout(
        engine: object,
        query: object,
        profile: object,
        observed: object,
        progress: dict[str, int],
    ) -> b.HeadedSerpCapture:
        progress.update(navigation_count=1, blocked_redirect=1)
        raise TimeoutError

    monkeypatch.setattr(b, "_capture_with_processes", timeout)
    result = await b.capture_headed_serp(
        "tenant-captcha", SearchEngine.GOOGLE, QUERY, root=tmp_path
    )
    assert result.status == "BLOCKED" and result.navigation_count == 1


@async_test
async def test_missing_runtime_fails_closed_and_creates_private_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SUPPLIER_SERP_CHROME_PATH", raising=False)
    monkeypatch.delenv("SUPPLIER_SERP_XVFB_PATH", raising=False)
    result = await b.capture_headed_serp("tenant-missing", SearchEngine.BING, QUERY, root=tmp_path)
    assert result.status == "BROWSER_UNAVAILABLE" and result.navigation_count == 0
    profile = b.profile_directory(tmp_path, "tenant-missing", SearchEngine.BING)
    for path in (tmp_path, tmp_path / "profiles", profile.parent, profile):
        assert path.is_dir()
        if b.os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o700
    for path in tmp_path.rglob("*.json"):
        if b.os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600


@async_test
async def test_devtools_port_rejects_nonlocal_file_content(tmp_path: Path) -> None:
    process = SimpleNamespace(returncode=None)
    (tmp_path / "DevToolsActivePort").write_text("not-a-port\n/devtools/x")
    with pytest.raises(RuntimeError, match="CDP_PORT_INVALID"):
        await b._devtools_port(tmp_path, process)  # type: ignore[arg-type]


def test_capture_invariants_and_transport_revision() -> None:
    saved = capture()
    assert saved.transport_version == b.TRANSPORT_VERSION
    assert saved.browser_version == "Chrome/153"
    data = saved.__dict__ | {"content": None}
    with pytest.raises(ValueError, match="HEADED_CAPTURE_INCOMPLETE"):
        b.HeadedSerpCapture(**data)
    data = saved.__dict__ | {"content": b"x" * (b.MAX_DOM_BYTES + 1)}
    with pytest.raises(ValueError, match="HEADED_CAPTURE_CONTENT_INVALID"):
        b.HeadedSerpCapture(**data)


@async_test
async def test_stop_terminates_then_kills_stuck_process() -> None:
    class Process:
        returncode = None
        terminated = False
        killed = False

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            if not self.killed:
                await asyncio.sleep(2)
            return -9

    process = Process()
    await b._stop(process)  # type: ignore[arg-type]
    assert process.terminated and process.killed


@async_test
async def test_stop_allows_graceful_browser_exit_before_terminate() -> None:
    class Process:
        returncode = None
        terminated = False

        def terminate(self) -> None:
            self.terminated = True

        async def wait(self) -> int:
            self.returncode = 0
            return 0

    process = Process()
    await b._stop(process, graceful_wait_seconds=2)  # type: ignore[arg-type]
    assert process.returncode == 0 and not process.terminated


@async_test
async def test_stop_grace_timeout_uses_terminate_fallback() -> None:
    class Process:
        returncode = None
        terminated = False

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.returncode = -9

        async def wait(self) -> int:
            if not self.terminated:
                await asyncio.sleep(1)
            self.returncode = 0
            return 0

    process = Process()
    await b._stop(process, graceful_wait_seconds=0.01)  # type: ignore[arg-type]
    assert process.terminated and process.returncode == 0


@async_test
async def test_stop_delays_cancellation_until_process_is_confirmed_dead() -> None:
    exited = asyncio.Event()

    class Process:
        returncode = None

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

        async def wait(self) -> int:
            await exited.wait()
            self.returncode = -9
            return 0

    task = asyncio.create_task(b._stop(Process()))  # type: ignore[arg-type]
    await asyncio.sleep(1.05)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    exited.set()
    with pytest.raises(asyncio.CancelledError):
        await task
