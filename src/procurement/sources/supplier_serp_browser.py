"""Single-host headed Chrome transport for bounded supplier SERP capture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from procurement.sources.supplier_serp import (
    ENGINES,
    MAX_DOM_BYTES,
    SearchEngine,
    parse_supplier_serp,
    request_allowed,
    source_url,
)

CaptureStatus = Literal[
    "CAPTURED",
    "COOLDOWN",
    "BUSY",
    "BLOCKED",
    "RATE_LIMITED",
    "TIMEOUT",
    "BROWSER_UNAVAILABLE",
    "SOURCE_ERROR",
    "SOURCE_CHANGED",
]

ATTEMPT_SECONDS = 20
PACE_SECONDS = 15
RESERVATION_SECONDS = ATTEMPT_SECONDS + PACE_SECONDS
BLOCKED_SECONDS = 60 * 60
RATE_LIMIT_SECONDS = 15 * 60
STATE_VERSION = "supplier-serp-headed-v1"
TRANSPORT_VERSION = "headed-chrome-cdp-v1"


class _CaptureFailure(RuntimeError):
    def __init__(self, navigation_count: Literal[0, 1]) -> None:
        super().__init__("HEADED_CAPTURE_FAILED")
        self.navigation_count = navigation_count


@dataclass(frozen=True)
class HeadedSerpCapture:
    engine: SearchEngine
    source_url: str
    final_url: str
    observed_at: datetime
    http_status: int | None
    content: bytes | None
    status: CaptureStatus
    navigation_count: Literal[0, 1]
    elapsed_ms: int
    browser_version: str | None = None
    transport_version: Literal["headed-chrome-cdp-v1"] = TRANSPORT_VERSION

    def __post_init__(self) -> None:
        if self.engine not in ENGINES or self.source_url != source_url(
            self.engine, _query(self.source_url)
        ):
            raise ValueError("HEADED_CAPTURE_SOURCE_INVALID")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("HEADED_CAPTURE_TIME_INVALID")
        if not 0 <= self.elapsed_ms <= ATTEMPT_SECONDS * 1000:
            raise ValueError("HEADED_CAPTURE_ELAPSED_INVALID")
        if self.content is not None and not 1 <= len(self.content) <= MAX_DOM_BYTES:
            raise ValueError("HEADED_CAPTURE_CONTENT_INVALID")
        if self.status == "CAPTURED" and (self.content is None or self.navigation_count != 1):
            raise ValueError("HEADED_CAPTURE_INCOMPLETE")
        if self.status in {"COOLDOWN", "BUSY", "BROWSER_UNAVAILABLE"} and (
            self.content is not None or self.navigation_count != 0
        ):
            raise ValueError("HEADED_CAPTURE_UNAVAILABLE_EVIDENCE")


def _query(url: str) -> str:
    from urllib.parse import parse_qs

    parts = urlsplit(url)
    values = parse_qs(parts.query).get("text" if "yandex" in parts.netloc else "q", [])
    if len(values) != 1:
        raise ValueError("HEADED_CAPTURE_QUERY_INVALID")
    return values[0]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def profile_directory(root: Path, company_id: str, engine: SearchEngine) -> Path:
    if not company_id or len(company_id) > 200 or engine not in ENGINES:
        raise ValueError("HEADED_PROFILE_SCOPE_INVALID")
    resolved = root.resolve()
    directory = (
        resolved
        / "profiles"
        / _hash(company_id)
        / _hash(source_url(engine, "x производитель поставщик купить оптом").split("?", 1)[0])
    ).resolve()
    if not directory.is_relative_to(resolved):
        raise ValueError("HEADED_PROFILE_PATH_INVALID")
    return directory


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _private_file(path: Path) -> None:
    path.chmod(0o600)


@contextmanager
def _lease(path: Path) -> Iterator[None]:
    _private_dir(path.parent)
    if not path.exists():
        path.write_bytes(b"0")
    _private_file(path)
    handle = path.open("r+b")
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError) as exc:
            raise FileExistsError("HEADED_PROFILE_BUSY") from exc
        yield
    finally:
        try:
            if acquired and os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif acquired:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _state(path: Path, scope: str) -> tuple[datetime | None, datetime | None]:
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        if data.get("version") != STATE_VERSION or data.get("scope") != scope:
            raise ValueError
        values = []
        for name in ("next_allowed_at", "cooldown_until"):
            raw = data.get(name)
            value = datetime.fromisoformat(raw) if raw is not None else None
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError
            values.append(value)
        return values[0], values[1]
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("HEADED_PACING_STATE_INVALID") from exc


def _write_state(
    path: Path,
    scope: str,
    next_allowed: datetime | None,
    cooldown_until: datetime | None,
    *,
    cooldown_reason: str | None = None,
    rate_limit_until: datetime | None = None,
) -> None:
    _private_dir(path.parent)
    previous = json.loads(path.read_text()) if path.exists() else {}
    reason = cooldown_reason or previous.get("cooldown_reason", "UNKNOWN")
    rate_until = (
        rate_limit_until.isoformat() if rate_limit_until else previous.get("rate_limit_until")
    )
    payload = json.dumps(
        {
            "version": STATE_VERSION,
            "scope": scope,
            "next_allowed_at": next_allowed.isoformat() if next_allowed else None,
            "cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
            "cooldown_reason": reason if cooldown_until else None,
            "rate_limit_until": rate_until,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _private_file(temporary)
    temporary.replace(path)
    _private_file(path)


def _reserve(
    root: Path, profile: Path, engine: SearchEngine, now: datetime, query: str | None = None
) -> bool:
    origin = urlsplit(source_url(engine, "x производитель поставщик купить оптом")).netloc
    origin_hash = _hash(origin)
    global_path = root.resolve() / "state" / "global" / f"{origin_hash}.json"
    tenant_path = profile / "pacing.json"
    with _lease(global_path.with_suffix(".lock")), _lease(profile / "pacing.lock"):
        states = (
            (global_path, f"global:{origin_hash}"),
            (tenant_path, f"tenant-origin:{profile.parent.name}:{origin_hash}"),
        )
        loaded = [(path, scope, *_state(path, scope)) for path, scope in states]
        # Human verification grants one exact retry; a newer pacing write invalidates it.
        if any(next_at is not None and next_at > now for _, _, next_at, _ in loaded):
            return False
        from procurement.sources.supplier_captcha_recovery import take_retry

        recovered = take_retry(profile, engine, query, (global_path, tenant_path), now)
        if (
            any(
                max(filter(None, (next_at, cooldown)), default=now) > now
                for _, _, next_at, cooldown in loaded
            )
            and not recovered
        ):
            return False
        reserved = now + timedelta(seconds=RESERVATION_SECONDS)
        for path, scope, _, cooldown in loaded:
            _write_state(path, scope, reserved, cooldown)
    return True


def _mark(
    root: Path, profile: Path, engine: SearchEngine, status: CaptureStatus, now: datetime
) -> None:
    seconds = (
        BLOCKED_SECONDS
        if status == "BLOCKED"
        else RATE_LIMIT_SECONDS
        if status == "RATE_LIMITED"
        else 0
    )
    if not seconds:
        return
    origin = urlsplit(source_url(engine, "x производитель поставщик купить оптом")).netloc
    origin_hash = _hash(origin)
    global_path = root.resolve() / "state" / "global" / f"{origin_hash}.json"
    tenant_path = profile / "pacing.json"
    until = now + timedelta(seconds=seconds)
    with _lease(global_path.with_suffix(".lock")), _lease(profile / "pacing.lock"):
        for path, scope in (
            (global_path, f"global:{origin_hash}"),
            (tenant_path, f"tenant-origin:{profile.parent.name}:{origin_hash}"),
        ):
            next_at, old = _state(path, scope)
            _write_state(
                path,
                scope,
                next_at,
                max(filter(None, (old, until))),
                cooldown_reason=status if not old or until >= old else None,
                rate_limit_until=until if status == "RATE_LIMITED" else None,
            )


def _chrome_args(executable: Path, profile: Path) -> tuple[str, ...]:
    args = [
        str(executable),
        f"--user-data-dir={profile}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-features=ServiceWorker,OptimizationHints,MediaRouter",
        "--disable-blink-features=ServiceWorker",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-pings",
        "--window-size=1280,720",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-startup-window",
    ]
    if getattr(os, "geteuid", lambda: -1)() == 0:
        args.append("--no-sandbox")
    return tuple(args)


def _configured_executable(name: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        raise FileNotFoundError(name)
    path = Path(raw)
    if not path.is_absolute() or not path.is_file():
        raise FileNotFoundError(name)
    return path.resolve()


async def _stop(
    process: asyncio.subprocess.Process | None, *, graceful_wait_seconds: float = 0
) -> None:
    if process is None or process.returncode is not None:
        return
    if graceful_wait_seconds:
        try:
            await asyncio.wait_for(process.wait(), graceful_wait_seconds)
            return
        except TimeoutError:
            pass
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 1)
    except TimeoutError:
        process.kill()
        waiter = asyncio.create_task(process.wait())
        cancelled = False
        while not waiter.done():
            try:
                await asyncio.shield(waiter)
            except asyncio.CancelledError:
                cancelled = True
        await waiter
        if cancelled:
            raise asyncio.CancelledError from None


async def _display(xvfb: asyncio.subprocess.Process, read_fd: int) -> str:
    raw = await asyncio.wait_for(asyncio.to_thread(os.read, read_fd, 32), 5)
    value = raw.decode("ascii", errors="strict").strip()
    if not value.isdigit() or xvfb.returncode is not None:
        raise RuntimeError("XVFB_DISPLAY_INVALID")
    return ":" + value


async def _devtools_port(profile: Path, chrome: asyncio.subprocess.Process) -> int:
    path = profile / "DevToolsActivePort"
    for _ in range(100):
        if chrome.returncode is not None:
            raise RuntimeError("CHROME_EXITED")
        if path.exists():
            line = path.read_text(encoding="ascii").splitlines()[0]
            if line.isdigit() and 1 <= int(line) <= 65535:
                return int(line)
            raise RuntimeError("CDP_PORT_INVALID")
        await asyncio.sleep(0.05)
    raise TimeoutError("CDP_PORT_TIMEOUT")


def _remove_stale_devtools(profile: Path) -> None:
    path = profile / "DevToolsActivePort"
    if path.exists():
        path.unlink()


def _singleton_lock_present(profile: Path) -> bool:
    path = profile / "SingletonLock"
    return path.exists() or path.is_symlink()


def _captcha_redirect(url: str) -> bool:
    folded = url.casefold()
    return "/sorry" in folded or "showcaptcha" in folded


async def _prepare_cdp_browser(browser: object) -> tuple[object, object]:
    session = await browser.new_browser_cdp_session()  # type: ignore[attr-defined]
    await session.send("Browser.setDownloadBehavior", {"behavior": "deny"})
    contexts = browser.contexts  # type: ignore[attr-defined]
    if len(contexts) != 1:
        raise RuntimeError("PERSISTED_CONTEXT_COUNT_INVALID")
    context = contexts[0]
    pages = tuple(context.pages)
    if len(pages) > 1 or any(page.url != "about:blank" for page in pages):
        urls = ",".join(str(page.url)[:500] for page in pages[:10])
        for page in pages:
            with suppress(Exception):
                await page.close()
        raise RuntimeError(f"PERSISTED_PAGE_STATE_INVALID:{urls}")
    page = pages[0] if pages else await context.new_page()
    return context, page


@asynccontextmanager
async def _attached_browser(playwright: object, port: int):
    browser = await playwright.chromium.connect_over_cdp(  # type: ignore[attr-defined]
        f"http://127.0.0.1:{port}"
    )
    try:
        yield browser
    finally:
        with suppress(Exception):
            session = await browser.new_browser_cdp_session()
            await asyncio.wait_for(session.send("Browser.close"), 1)
        with suppress(Exception):
            await asyncio.wait_for(browser.close(), 1)


def _reject_service_workers(context: object) -> None:
    workers = tuple(context.service_workers)  # type: ignore[attr-defined]
    if workers:
        urls = ",".join(str(worker.url)[:500] for worker in workers[:10])
        raise RuntimeError(f"PERSISTED_SERVICE_WORKER_FORBIDDEN:{urls}")


def _browser_environment(display: str | None = None) -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "XDG_RUNTIME_DIR",
        "LD_LIBRARY_PATH",
        "FONTCONFIG_FILE",
        "FONTCONFIG_PATH",
    }
    env = {name: value for name, value in os.environ.items() if name in allowed}
    if display is not None:
        env["DISPLAY"] = display
    return env


async def _capture_with_processes(
    engine: SearchEngine,
    query: str,
    profile: Path,
    observed_at: datetime,
    progress: dict[str, int],
) -> HeadedSerpCapture:
    from playwright.async_api import async_playwright

    chrome_path = _configured_executable("SUPPLIER_SERP_CHROME_PATH")
    xvfb_path = _configured_executable("SUPPLIER_SERP_XVFB_PATH")
    _private_dir(profile)
    _remove_stale_devtools(profile)
    read_fd, write_fd = os.pipe()
    xvfb = chrome = None
    browser = None
    navigation: Literal[0, 1] = 0
    blocked_redirect = False
    started = asyncio.get_running_loop().time()
    try:
        xvfb = await asyncio.create_subprocess_exec(
            str(xvfb_path),
            "-displayfd",
            str(write_fd),
            "-screen",
            "0",
            "1280x720x24",
            "-nolisten",
            "tcp",
            pass_fds=(write_fd,),
            env=_browser_environment(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        os.close(write_fd)
        write_fd = -1
        display = await _display(xvfb, read_fd)
        env = _browser_environment(display)
        chrome = await asyncio.create_subprocess_exec(
            *_chrome_args(chrome_path, profile),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        port = await _devtools_port(profile, chrome)
        async with async_playwright() as playwright, _attached_browser(playwright, port) as browser:
            context, page = await _prepare_cdp_browser(browser)
            _reject_service_workers(context)
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.enable")
            await cdp.send("Network.setBypassServiceWorker", {"bypass": True})

            async def route_request(route: object) -> None:
                nonlocal blocked_redirect
                request = route.request  # type: ignore[attr-defined]
                if request.is_navigation_request() and _captcha_redirect(request.url):
                    blocked_redirect = True
                    progress["blocked_redirect"] = 1
                allowed = request_allowed(
                    engine,
                    query,
                    request.url,
                    request.resource_type,
                    navigation=request.is_navigation_request(),
                    main_frame=request.frame == page.main_frame,
                )
                await (route.continue_() if allowed else route.abort())  # type: ignore[attr-defined]

            await context.route("**/*", route_request)
            navigation = 1
            progress["navigation_count"] = 1
            response = await page.goto(
                source_url(engine, query), wait_until="domcontentloaded", timeout=10000
            )
            readiness = {
                SearchEngine.BING: "li.b_algo, li.b_no, #captcha, .b_captcha",
                SearchEngine.YANDEX: "#captcha, .smart-captcha, [class*=serp]",
                SearchEngine.GOOGLE: "#captcha, .g-recaptcha, #search",
            }[engine]
            with suppress(Exception):
                await page.wait_for_selector(readiness, timeout=2500)
            _reject_service_workers(context)
            markup = await page.evaluate(
                """() => {
                    const s=document.documentElement.outerHTML;
                    return new TextEncoder().encode(s).length <= MAX_BYTES ? s : null;
                }""".replace("MAX_BYTES", str(MAX_DOM_BYTES))
            )
            http_status = response.status if response else 0
            if not isinstance(markup, str):
                return HeadedSerpCapture(
                    engine,
                    source_url(engine, query),
                    page.url,
                    observed_at,
                    http_status,
                    None,
                    "SOURCE_CHANGED",
                    navigation,
                    min(
                        20000,
                        int((asyncio.get_running_loop().time() - started) * 1000),
                    ),
                    browser.version,
                )
            content = markup.encode("utf-8")
            parsed = parse_supplier_serp(
                engine,
                query,
                content,
                final_url=page.url,
                observed_at=observed_at,
                http_status=http_status,
            )
            status: CaptureStatus = (
                parsed.status if parsed.status in {"BLOCKED", "RATE_LIMITED"} else "CAPTURED"
            )  # type: ignore[assignment]
            return HeadedSerpCapture(
                engine,
                source_url(engine, query),
                page.url,
                observed_at,
                http_status,
                content,
                status,
                navigation,
                min(20000, int((asyncio.get_running_loop().time() - started) * 1000)),
                browser.version,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if navigation and blocked_redirect:
            return HeadedSerpCapture(
                engine,
                source_url(engine, query),
                source_url(engine, query),
                observed_at,
                None,
                None,
                "BLOCKED",
                1,
                min(20000, int((asyncio.get_running_loop().time() - started) * 1000)),
                browser.version if browser is not None else None,
            )
        if navigation:
            raise _CaptureFailure(navigation) from exc
        raise
    finally:
        try:
            await _stop(chrome, graceful_wait_seconds=2)
            await _stop(xvfb)
            if _singleton_lock_present(profile):
                raise RuntimeError("PROFILE_SINGLETON_LOCK_RETAINED")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if navigation:
                raise _CaptureFailure(navigation) from exc
            raise
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


async def capture_headed_serp(
    company_id: str, engine: SearchEngine, query: str, *, root: Path
) -> HeadedSerpCapture:
    """Capture one exact active-engine SERP with durable single-host pacing."""
    if engine not in ENGINES:
        raise ValueError("ENGINE_DISABLED")
    expected = source_url(engine, query)
    observed = datetime.now(UTC)
    started = asyncio.get_running_loop().time()
    profile = profile_directory(root, company_id, engine)
    resolved_root = root.resolve()
    for directory in (
        resolved_root,
        resolved_root / "profiles",
        profile.parent,
        profile,
        resolved_root / "state",
        resolved_root / "state" / "global",
    ):
        _private_dir(directory)
    progress = {"navigation_count": 0, "blocked_redirect": 0}
    try:
        with _lease(profile / "profile.lock"):
            if not _reserve(root, profile, engine, observed, query):
                return HeadedSerpCapture(
                    engine, expected, expected, observed, None, None, "COOLDOWN", 0, 0
                )
            try:
                async with asyncio.timeout(ATTEMPT_SECONDS):
                    result = await _capture_with_processes(
                        engine, query, profile, observed, progress
                    )
            except TimeoutError:
                timed_out_status: CaptureStatus = (
                    "BLOCKED" if progress["blocked_redirect"] else "TIMEOUT"
                )
                result = HeadedSerpCapture(
                    engine,
                    expected,
                    expected,
                    observed,
                    None,
                    None,
                    timed_out_status,
                    1 if progress["navigation_count"] else 0,
                    ATTEMPT_SECONDS * 1000,
                )
            except (FileNotFoundError, ImportError):
                result = HeadedSerpCapture(
                    engine,
                    expected,
                    expected,
                    observed,
                    None,
                    None,
                    "BROWSER_UNAVAILABLE",
                    0,
                    _elapsed(started),
                )
            except _CaptureFailure as exc:
                result = HeadedSerpCapture(
                    engine,
                    expected,
                    expected,
                    observed,
                    None,
                    None,
                    "SOURCE_ERROR",
                    exc.navigation_count,
                    _elapsed(started),
                )
            except Exception:
                result = HeadedSerpCapture(
                    engine,
                    expected,
                    expected,
                    observed,
                    None,
                    None,
                    "SOURCE_ERROR",
                    0,
                    _elapsed(started),
                )
            _mark(root, profile, engine, result.status, datetime.now(UTC))
            return result
    except FileExistsError:
        if progress["navigation_count"]:
            raise
        return HeadedSerpCapture(
            engine, expected, expected, observed, None, None, "BUSY", 0, _elapsed(started)
        )


def _elapsed(started: float) -> int:
    return min(ATTEMPT_SECONDS * 1000, int((asyncio.get_running_loop().time() - started) * 1000))
