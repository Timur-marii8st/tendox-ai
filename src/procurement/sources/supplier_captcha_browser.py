"""Bounded human-assisted CAPTCHA session for one exact supplier SERP.

The manager owns an in-process, single-slot browser.  It exposes screenshots and
restricted human input, but never exposes navigation, script evaluation, browser
state, cookies, or the exact query in its JSON-facing models.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from PIL import Image
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from procurement.sources import supplier_serp_browser as headed
from procurement.sources.supplier_serp import (
    ENGINES,
    MAX_DOM_BYTES,
    EngineAttempt,
    SearchEngine,
    parse_supplier_serp,
    source_url,
)

SESSION_SECONDS = 10 * 60
STARTUP_SECONDS = 20
FRAME_INTERVAL_SECONDS = 0.5
INPUT_INTERVAL_SECONDS = 0.1
OPERATION_SECONDS = 5
MAX_JPEG_BYTES = 512 * 1024
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720
MAX_RETAINED_SESSIONS = 16
_OWNED_TEMP_PATHS: set[Path] = set()


class CaptchaSessionStatus(StrEnum):
    STARTING = "STARTING"
    WAITING = "WAITING"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class _JsonModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CaptchaSessionView(_JsonModel):
    session_id: UUID
    run_id: UUID
    engine: SearchEngine
    status: CaptchaSessionStatus
    expires_at: AwareDatetime
    reason_code: Literal[
        "PROFILE_BUSY",
        "PACING_ACTIVE",
        "BROWSER_UNAVAILABLE",
        "STARTUP_FAILED",
        "CLEANUP_FAILED",
        "ACCESS_BLOCKED",
        "RATE_LIMITED",
        "DOM_LIMIT",
        "QUERY_BINDING_INVALID",
        "ORGANIC_STRUCTURE_UNVERIFIED",
        "SOURCE_ERROR",
    ] | None = None
    retry_after_seconds: int = Field(default=0, ge=0, le=SESSION_SECONDS, strict=True)


class CaptchaFrame(_JsonModel):
    data: str = Field(min_length=1)
    mime_type: Literal["image/jpeg"] = "image/jpeg"
    width: int = Field(ge=1, le=VIEWPORT_WIDTH, strict=True)
    height: int = Field(ge=1, le=VIEWPORT_HEIGHT, strict=True)

    @field_validator("data")
    @classmethod
    def bounded_jpeg(cls, value: str) -> str:
        try:
            raw = base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise ValueError("CAPTCHA_FRAME_INVALID") from exc
        if not raw.startswith(b"\xff\xd8") or len(raw) > MAX_JPEG_BYTES:
            raise ValueError("CAPTCHA_FRAME_INVALID")
        return value


class ClickInput(_JsonModel):
    kind: Literal["click"] = "click"
    x: int = Field(ge=0, lt=VIEWPORT_WIDTH, strict=True)
    y: int = Field(ge=0, lt=VIEWPORT_HEIGHT, strict=True)


class WheelInput(_JsonModel):
    kind: Literal["wheel"] = "wheel"
    delta_y: int = Field(ge=-7200, le=7200, strict=True)


class TypeInput(_JsonModel):
    kind: Literal["type"] = "type"
    text: str = Field(min_length=1, max_length=128)

    @field_validator("text")
    @classmethod
    def visible_text(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("CAPTCHA_INPUT_TEXT_INVALID")
        return value


_ALLOWED_KEYS = frozenset(
    {
        "Enter",
        "Escape",
        "Tab",
        "Backspace",
        "Delete",
        "Space",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
    }
)


class KeyInput(_JsonModel):
    kind: Literal["key"] = "key"
    key: str = Field(min_length=1, max_length=16)

    @field_validator("key")
    @classmethod
    def allowed_key(cls, value: str) -> str:
        if value not in _ALLOWED_KEYS:
            raise ValueError("CAPTCHA_INPUT_KEY_INVALID")
        return value


CaptchaInput = Annotated[
    ClickInput | WheelInput | TypeInput | KeyInput, Field(discriminator="kind")
]


@dataclass(frozen=True)
class CaptchaVerificationProof:
    """Backend-only verified evidence; the API must not serialize ``content``."""

    session_id: UUID
    run_id: UUID
    engine: SearchEngine
    observed_at: datetime
    http_status: int
    dom_sha256: str
    content: bytes
    attempt: EngineAttempt
    pacing_sha256: tuple[str, str]
    manual_navigation_count: int


@dataclass
class _BrowserHandle:
    page: object
    cdp: object


@dataclass
class _Session:
    session_id: UUID
    company_id: str
    actor_id: str
    engine: SearchEngine
    query: str
    run_id: UUID
    expires_at: datetime
    status: CaptchaSessionStatus = CaptchaSessionStatus.STARTING
    reason_code: str | None = None
    handle: _BrowserHandle | None = None
    task: asyncio.Task[None] | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    current_http_status: int | None = None
    manual_navigation_count: int = 0
    pacing_sha256: tuple[str, str] | None = None
    proof: CaptchaVerificationProof | None = None
    expiry_requested: bool = False
    rate_limited: bool = False
    last_frame_at: float | None = None
    last_input_at: float | None = None


def _validate_owner(company_id: str, actor_id: str) -> None:
    for value in (company_id, actor_id):
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 200
            or any(ord(character) < 33 for character in value)
        ):
            raise ValueError("CAPTCHA_OWNER_INVALID")


def _public_https(parts: object) -> bool:
    try:
        split = parts
        host = (split.hostname or "").encode("idna").decode("ascii").lower()
        if (
            split.scheme != "https"
            or split.username
            or split.password
            or split.port
            or not host
        ):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            return True
    except (AttributeError, UnicodeError, ValueError):
        return False


def _host_under(host: str, roots: tuple[str, ...]) -> bool:
    return any(host == root or host.endswith("." + root) for root in roots)


def _captcha_endpoint(engine: SearchEngine, host: str, path: str) -> bool:
    folded = path.casefold()
    if engine == SearchEngine.GOOGLE:
        return (
            host in {"google.com", "www.google.com"}
            and (folded.startswith("/sorry/") or folded.startswith("/recaptcha/"))
        ) or (host == "www.gstatic.com" and folded.startswith("/recaptcha/"))
    if engine == SearchEngine.YANDEX:
        return (
            host in {"yandex.ru", "www.yandex.ru", "captcha-api.yandex.ru"}
            and ("showcaptcha" in folded or "captcha" in folded)
        ) or (host == "smartcaptcha.yandexcloud.net" and folded.startswith("/"))
    return False


def _bound_search(engine: SearchEngine, query: str, url: str) -> bool:
    parts = urlsplit(url)
    expected = urlsplit(source_url(engine, query))
    parameter = "text" if engine == SearchEngine.YANDEX else "q"
    return (
        not parts.fragment
        and parts.scheme == expected.scheme
        and parts.netloc == expected.netloc
        and parts.path == expected.path
        and parse_qs(parts.query).get(parameter) == [query]
    )


def _captcha_asset(engine: SearchEngine, host: str, path: str) -> bool:
    folded = path.casefold()
    if _captcha_endpoint(engine, host, path):
        return True
    if engine == SearchEngine.GOOGLE:
        return host == "www.gstatic.com" and folded.startswith("/recaptcha/")
    if engine == SearchEngine.YANDEX:
        return (
            host == "smartcaptcha.yandexcloud.net"
            or (
                (host.endswith(".yastatic.net") or host == "yastatic.net")
                and ("captcha" in folded or folded.startswith("/s3/passport-static/"))
            )
        )
    if engine == SearchEngine.BING:
        return _host_under(host, ("bing.com", "bing.net")) and folded.startswith(
            ("/rp/", "/fd/", "/sa/", "/images/")
        )
    return False


def manual_request_allowed(
    engine: SearchEngine,
    query: str,
    url: str,
    resource_type: str,
    *,
    navigation: bool,
    main_frame: bool,
    method: str = "GET",
) -> bool:
    """Allow only the bound SERP and known CAPTCHA resources on public HTTPS."""
    if engine not in ENGINES or method not in {"GET", "POST"}:
        return False
    try:
        source_url(engine, query)
        parts = urlsplit(url)
        if not _public_https(parts) or resource_type in {
            "websocket",
            "eventsource",
            "manifest",
            "other",
        }:
            return False
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        path = parts.path or "/"
        folded = path.casefold()
        if any(part in folded for part in ("/login", "/signin", "/account", "/auth/")):
            return False
        roots = {
            SearchEngine.BING: ("bing.com", "bing.net"),
            SearchEngine.GOOGLE: ("google.com", "gstatic.com"),
            SearchEngine.YANDEX: ("yandex.ru", "yastatic.net", "yandexcloud.net"),
        }[engine]
        if not _host_under(host, roots):
            return False
        captcha = _captcha_endpoint(engine, host, path)
        bound_search = _bound_search(engine, query, url)
        if navigation:
            return captcha or (method == "GET" and main_frame and bound_search)
        if method == "POST":
            return captcha
        if resource_type == "document":
            return False
        return bound_search or _captcha_asset(engine, host, path)
    except (KeyError, UnicodeError, ValueError):
        return False


def _pacing_paths(root: Path, profile: Path, engine: SearchEngine) -> tuple[Path, Path, str, str]:
    origin = urlsplit(source_url(engine, "x производитель поставщик купить оптом")).netloc
    origin_hash = headed._hash(origin)
    global_path = root.resolve() / "state" / "global" / f"{origin_hash}.json"
    tenant_path = profile / "pacing.json"
    return (
        global_path,
        tenant_path,
        f"global:{origin_hash}",
        f"tenant-origin:{profile.parent.name}:{origin_hash}",
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cooldown_metadata(path: Path) -> tuple[str | None, datetime | None]:
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, None
        value = data.get("cooldown_reason")
        raw_rate_limit = data.get("rate_limit_until")
        rate_limit = (
            datetime.fromisoformat(raw_rate_limit)
            if isinstance(raw_rate_limit, str)
            else None
        )
        if rate_limit is not None and (
            rate_limit.tzinfo is None or rate_limit.utcoffset() is None
        ):
            return None, datetime.max.replace(tzinfo=UTC)
        return value if isinstance(value, str) else None, rate_limit
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, datetime.max.replace(tzinfo=UTC)


def _manual_reserve(
    root: Path, profile: Path, engine: SearchEngine, now: datetime
) -> tuple[str, str] | None:
    """Reserve normal spacing while retaining both existing cooldown values."""
    global_path, tenant_path, global_scope, tenant_scope = _pacing_paths(root, profile, engine)
    with headed._lease(global_path.with_suffix(".lock")), headed._lease(profile / "pacing.lock"):
        global_next, global_cooldown = headed._state(global_path, global_scope)
        tenant_next, tenant_cooldown = headed._state(tenant_path, tenant_scope)
        if any(
            next_at is not None and next_at > now for next_at in (global_next, tenant_next)
        ):
            return None
        for path, cooldown in (
            (global_path, global_cooldown),
            (tenant_path, tenant_cooldown),
        ):
            reason, rate_limit = _cooldown_metadata(path)
            if rate_limit is not None and rate_limit > now:
                return None
            if cooldown is not None and cooldown > now and reason != "BLOCKED":
                return None
        reserved = now + timedelta(seconds=headed.RESERVATION_SECONDS)
        headed._write_state(global_path, global_scope, reserved, global_cooldown)
        headed._write_state(tenant_path, tenant_scope, reserved, tenant_cooldown)
        return _file_sha256(global_path), _file_sha256(tenant_path)


def _temp_parent() -> Path:
    if os.name != "nt" and Path("/tmp").is_dir():
        return Path("/tmp").resolve()
    return Path(tempfile.gettempdir()).resolve()


def _private_temp() -> Path:
    parent = _temp_parent()
    temp = Path(tempfile.mkdtemp(prefix="syu-cap-", dir=parent))
    if (
        not temp.is_absolute()
        or temp.is_symlink()
        or temp.parent.resolve() != parent
        or not temp.name.startswith("syu-cap-")
    ):
        raise RuntimeError("CAPTCHA_TEMP_INVALID")
    headed._private_dir(temp)
    _OWNED_TEMP_PATHS.add(temp)
    return temp


def _safe_remove_temp(temp: Path) -> bool:
    parent = _temp_parent()
    if (
        temp in _OWNED_TEMP_PATHS
        and temp.is_absolute()
        and not temp.is_symlink()
        and temp.parent.resolve() == parent
        and temp.name.startswith("syu-cap-")
    ):
        shutil.rmtree(temp, ignore_errors=True)
        if not temp.exists():
            _OWNED_TEMP_PATHS.discard(temp)
            return True
    return False


async def _prepare_browser(browser: object) -> tuple[object, object, object]:
    session = await browser.new_browser_cdp_session()  # type: ignore[attr-defined]
    await session.send("Browser.setDownloadBehavior", {"behavior": "deny"})
    contexts = browser.contexts  # type: ignore[attr-defined]
    if len(contexts) != 1:
        raise RuntimeError("CAPTCHA_CONTEXT_INVALID")
    context = contexts[0]
    pages = tuple(context.pages)
    if len(pages) > 1 or any(page.url != "about:blank" for page in pages):
        for page in pages:
            with suppress(Exception):
                await page.close()
        raise RuntimeError("CAPTCHA_PAGE_STATE_INVALID")
    page = pages[0] if pages else await context.new_page()
    await page.set_viewport_size(  # type: ignore[attr-defined]
        {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
    )
    cdp = await context.new_cdp_session(page)
    await cdp.send("Network.enable")
    await cdp.send("Network.setBypassServiceWorker", {"bypass": True})
    return context, page, cdp


def _record_response(session: _Session, page: object, response: object) -> None:
    request = response.request  # type: ignore[attr-defined]
    status = int(response.status)  # type: ignore[attr-defined]
    if status == 429:
        session.rate_limited = True
        session.proof = None
        session.stop.set()
    if request.is_navigation_request() and request.frame == page.main_frame:  # type: ignore[attr-defined]
        session.current_http_status = status


@asynccontextmanager
async def _open_manual_browser(
    session: _Session, profile: Path, root: Path
) -> AsyncIterator[_BrowserHandle]:
    from playwright.async_api import async_playwright

    chrome_path = headed._configured_executable("SUPPLIER_SERP_CHROME_PATH")
    xvfb_path = headed._configured_executable("SUPPLIER_SERP_XVFB_PATH")
    headed._private_dir(profile)
    headed._remove_stale_devtools(profile)
    temp = _private_temp()
    read_fd, write_fd = os.pipe()
    xvfb = chrome = browser = playwright = None
    try:
        xvfb = await asyncio.create_subprocess_exec(
            str(xvfb_path),
            "-displayfd",
            str(write_fd),
            "-screen",
            "0",
            f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}x24",
            "-nolisten",
            "tcp",
            pass_fds=(write_fd,),
            env=headed._browser_environment(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        os.close(write_fd)
        write_fd = -1
        display = await headed._display(xvfb, read_fd)
        environment = headed._browser_environment(display)
        environment.update({"TMPDIR": str(temp), "TMP": str(temp), "TEMP": str(temp)})
        chrome = await asyncio.create_subprocess_exec(
            *headed._chrome_args(chrome_path, profile),
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        port = await headed._devtools_port(profile, chrome)
        playwright = await async_playwright().start()
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context, page, cdp = await _prepare_browser(browser)
        if tuple(context.service_workers):
            raise RuntimeError("CAPTCHA_SERVICE_WORKER_FORBIDDEN")

        async def route_request(route: object) -> None:
            request = route.request  # type: ignore[attr-defined]
            is_navigation = request.is_navigation_request()
            main_frame = request.frame == page.main_frame
            allowed = manual_request_allowed(
                session.engine,
                session.query,
                request.url,
                request.resource_type,
                navigation=is_navigation,
                main_frame=main_frame,
                method=request.method,
            )
            if allowed and is_navigation and main_frame:
                session.manual_navigation_count += 1
            await (route.continue_() if allowed else route.abort())  # type: ignore[attr-defined]

        def response_seen(response: object) -> None:
            _record_response(session, page, response)

        async def close_popup(popup: object) -> None:
            with suppress(Exception):
                await popup.close()  # type: ignore[attr-defined]

        context.on("page", lambda popup: asyncio.create_task(close_popup(popup)))
        page.on("response", response_seen)
        if hasattr(context, "route_web_socket"):

            async def deny_web_socket(route: object) -> None:
                await route.close()  # type: ignore[attr-defined]

            await context.route_web_socket("**/*", deny_web_socket)
        await context.route("**/*", route_request)
        response = await page.goto(
            source_url(session.engine, session.query),
            wait_until="domcontentloaded",
            timeout=10000,
        )
        if response is not None:
            session.current_http_status = int(response.status)
        if tuple(context.service_workers):
            raise RuntimeError("CAPTCHA_SERVICE_WORKER_FORBIDDEN")
        yield _BrowserHandle(page=page, cdp=cdp)
    finally:
        cleanup_failed = False
        if browser is not None:
            with suppress(Exception):
                closing = await browser.new_browser_cdp_session()
                await asyncio.wait_for(closing.send("Browser.close"), 1)
            with suppress(Exception):
                await asyncio.wait_for(browser.close(), 1)
        if playwright is not None:
            with suppress(Exception):
                await playwright.stop()
        try:
            await headed._stop(chrome, graceful_wait_seconds=2)
        except Exception:
            cleanup_failed = True
        try:
            await headed._stop(xvfb)
        except Exception:
            cleanup_failed = True
        if headed._singleton_lock_present(profile):
            cleanup_failed = True
        with suppress(OSError):
            os.close(read_fd)
        if write_fd >= 0:
            with suppress(OSError):
                os.close(write_fd)
        if not _safe_remove_temp(temp):
            cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError("CAPTCHA_CLEANUP_FAILED")


def _encode_frame(raw: bytes) -> CaptchaFrame:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            if image.size != (VIEWPORT_WIDTH, VIEWPORT_HEIGHT):
                image = image.resize(
                    (VIEWPORT_WIDTH, VIEWPORT_HEIGHT), Image.Resampling.LANCZOS
                )
            width, height = image.size
            for quality in (65, 55, 45, 35, 25):
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                encoded = output.getvalue()
                if len(encoded) <= MAX_JPEG_BYTES:
                    return CaptchaFrame(
                        data=base64.b64encode(encoded).decode("ascii"),
                        width=width,
                        height=height,
                    )
    except (OSError, ValueError) as exc:
        raise RuntimeError("CAPTCHA_FRAME_FAILED") from exc
    raise RuntimeError("CAPTCHA_FRAME_TOO_LARGE")


async def _close_browser_context(browser_cm: object) -> None:
    """Finish cleanup before propagating cancellation to the profile lease."""
    task = asyncio.create_task(browser_cm.__aexit__(None, None, None))  # type: ignore[attr-defined]
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    await task
    if cancelled:
        raise asyncio.CancelledError from None


async def _persist_rate_limit(
    root: Path, profile: Path, engine: SearchEngine
) -> None:
    deadline = asyncio.get_running_loop().time() + 1
    while True:
        try:
            headed._mark(root, profile, engine, "RATE_LIMITED", datetime.now(UTC))
            return
        except FileExistsError:
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("CAPTCHA_RATE_LIMIT_PERSIST_FAILED") from None
            await asyncio.sleep(0.05)


class CaptchaBrowserManager:
    """Own one non-blocking, ten-minute manual CAPTCHA browser session."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._sessions: dict[UUID, _Session] = {}
        self._active_id: UUID | None = None
        self._lock = asyncio.Lock()

    async def start(
        self,
        company_id: str,
        actor_id: str,
        engine: SearchEngine,
        query: str,
        run_id: UUID,
    ) -> CaptchaSessionView:
        _validate_owner(company_id, actor_id)
        if engine not in ENGINES or not isinstance(run_id, UUID):
            raise ValueError("CAPTCHA_BINDING_INVALID")
        source_url(engine, query)
        async with self._lock:
            if self._active_id is not None:
                active = self._sessions[self._active_id]
                if active.task is not None and not active.task.done():
                    raise RuntimeError("CAPTCHA_BROWSER_BUSY")
                self._active_id = None
            terminal = [
                value
                for value in self._sessions.values()
                if value.task is None or value.task.done()
            ]
            for old in terminal[: max(0, len(self._sessions) - MAX_RETAINED_SESSIONS + 1)]:
                old.proof = None
                self._sessions.pop(old.session_id, None)
            session_id = uuid4()
            session = _Session(
                session_id=session_id,
                company_id=company_id,
                actor_id=actor_id,
                engine=engine,
                query=query,
                run_id=run_id,
                expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS),
            )
            self._sessions[session_id] = session
            self._active_id = session_id
            session.task = asyncio.create_task(self._run(session))
            return self._view(session)

    async def status(
        self, company_id: str, actor_id: str, session_id: UUID
    ) -> CaptchaSessionView:
        async with self._lock:
            return self._view(self._owned(company_id, actor_id, session_id))

    async def frame(self, company_id: str, actor_id: str, session_id: UUID) -> CaptchaFrame:
        async with self._lock:
            session = self._waiting(company_id, actor_id, session_id)
            now = asyncio.get_running_loop().time()
            if (
                session.last_frame_at is not None
                and now - session.last_frame_at < FRAME_INTERVAL_SECONDS
            ):
                raise RuntimeError("CAPTCHA_FRAME_RATE_LIMITED")
            session.last_frame_at = now
            assert session.handle is not None
            try:
                result = await asyncio.wait_for(
                    session.handle.cdp.send(  # type: ignore[attr-defined]
                        "Page.captureScreenshot",
                        {
                            "format": "jpeg",
                            "quality": 65,
                            "fromSurface": True,
                            "captureBeyondViewport": False,
                            "clip": {
                                "x": 0,
                                "y": 0,
                                "width": VIEWPORT_WIDTH,
                                "height": VIEWPORT_HEIGHT,
                                "scale": 1,
                            },
                        },
                    ),
                    OPERATION_SECONDS,
                )
            except Exception:
                raise RuntimeError("CAPTCHA_FRAME_FAILED") from None
            data = result.get("data") if isinstance(result, dict) else None
            if not isinstance(data, str):
                raise RuntimeError("CAPTCHA_FRAME_FAILED")
            try:
                raw = base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise RuntimeError("CAPTCHA_FRAME_FAILED") from exc
            return _encode_frame(raw)

    async def input(
        self,
        company_id: str,
        actor_id: str,
        session_id: UUID,
        event: CaptchaInput,
    ) -> CaptchaSessionView:
        async with self._lock:
            session = self._waiting(company_id, actor_id, session_id)
            now = asyncio.get_running_loop().time()
            if (
                session.last_input_at is not None
                and now - session.last_input_at < INPUT_INTERVAL_SECONDS
            ):
                raise RuntimeError("CAPTCHA_INPUT_RATE_LIMITED")
            session.last_input_at = now
            assert session.handle is not None
            page = session.handle.page
            if not isinstance(event, (ClickInput, WheelInput, TypeInput, KeyInput)):
                raise ValueError("CAPTCHA_INPUT_INVALID")
            try:
                if isinstance(event, ClickInput):
                    operation = page.mouse.click(event.x, event.y)  # type: ignore[attr-defined]
                elif isinstance(event, WheelInput):
                    operation = page.mouse.wheel(0, event.delta_y)  # type: ignore[attr-defined]
                elif isinstance(event, TypeInput):
                    operation = page.keyboard.type(event.text)  # type: ignore[attr-defined]
                elif isinstance(event, KeyInput):
                    operation = page.keyboard.press(event.key)  # type: ignore[attr-defined]
                await asyncio.wait_for(operation, OPERATION_SECONDS)
            except Exception:
                raise RuntimeError("CAPTCHA_INPUT_FAILED") from None
            return self._view(session)

    async def verify(
        self, company_id: str, actor_id: str, session_id: UUID
    ) -> CaptchaSessionView:
        task: asyncio.Task[None]
        async with self._lock:
            session = self._waiting(company_id, actor_id, session_id)
            assert session.handle is not None and session.task is not None
            try:
                content_text = await asyncio.wait_for(
                    session.handle.page.evaluate(  # type: ignore[attr-defined]
                        f"""() => {{
                            const value = document.documentElement.outerHTML;
                            return new TextEncoder().encode(value).length <= {MAX_DOM_BYTES}
                                ? value : null;
                        }}"""
                    ),
                    OPERATION_SECONDS,
                )
            except Exception:
                session.reason_code = "SOURCE_ERROR"
                return self._view(session)
            if not isinstance(content_text, str):
                session.reason_code = "DOM_LIMIT"
                return self._view(session)
            content = content_text.encode("utf-8")
            http_status = session.current_http_status
            if len(content) > MAX_DOM_BYTES or http_status is None:
                return self._view(session)
            try:
                attempt = parse_supplier_serp(
                    session.engine,
                    session.query,
                    content,
                    final_url=str(session.handle.page.url),  # type: ignore[attr-defined]
                    observed_at=datetime.now(UTC),
                    http_status=http_status,
                )
            except Exception:
                session.reason_code = "SOURCE_ERROR"
                return self._view(session)
            if attempt.status == "RATE_LIMITED":
                session.rate_limited = True
                session.proof = None
                session.reason_code = "RATE_LIMITED"
                session.stop.set()
                task = session.task
            elif attempt.status not in {"COMPLETED", "EMPTY"} or session.pacing_sha256 is None:
                session.reason_code = attempt.reason_code
                return self._view(session)
            else:
                if datetime.now(UTC) >= session.expires_at:
                    session.expiry_requested = True
                    session.stop.set()
                    raise RuntimeError("CAPTCHA_SESSION_EXPIRED")
                session.proof = CaptchaVerificationProof(
                    session_id=session.session_id,
                    run_id=session.run_id,
                    engine=session.engine,
                    observed_at=attempt.observed_at,
                    http_status=http_status,
                    dom_sha256=attempt.dom_sha256 or "",
                    content=content,
                    attempt=attempt,
                    pacing_sha256=session.pacing_sha256,
                    manual_navigation_count=session.manual_navigation_count,
                )
                session.status = CaptchaSessionStatus.VERIFIED
                session.reason_code = None
                session.stop.set()
                task = session.task
        await task
        async with self._lock:
            return self._view(self._owned(company_id, actor_id, session_id))

    async def proof(
        self, company_id: str, actor_id: str, session_id: UUID
    ) -> CaptchaVerificationProof:
        async with self._lock:
            session = self._owned(company_id, actor_id, session_id)
            if session.status != CaptchaSessionStatus.VERIFIED or session.proof is None:
                raise RuntimeError("CAPTCHA_PROOF_UNAVAILABLE")
            return session.proof

    async def cancel(
        self, company_id: str, actor_id: str, session_id: UUID
    ) -> CaptchaSessionView:
        task: asyncio.Task[None] | None
        async with self._lock:
            session = self._owned(company_id, actor_id, session_id)
            if session.status in {
                CaptchaSessionStatus.VERIFIED,
                CaptchaSessionStatus.CANCELLED,
                CaptchaSessionStatus.EXPIRED,
                CaptchaSessionStatus.FAILED,
            }:
                return self._view(session)
            session.status = CaptchaSessionStatus.CANCELLED
            session.stop.set()
            task = session.task
        if task is not None:
            await task
        async with self._lock:
            return self._view(self._owned(company_id, actor_id, session_id))

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = []
            for session in self._sessions.values():
                if session.task is not None and not session.task.done():
                    if session.status in {
                        CaptchaSessionStatus.STARTING,
                        CaptchaSessionStatus.WAITING,
                    }:
                        session.status = CaptchaSessionStatus.CANCELLED
                    session.stop.set()
                    tasks.append(session.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, session: _Session) -> None:
        profile = headed.profile_directory(self._root, session.company_id, session.engine)
        for directory in (
            self._root,
            self._root / "profiles",
            profile.parent,
            profile,
            self._root / "state",
            self._root / "state" / "global",
        ):
            headed._private_dir(directory)
        browser_cm = None
        browser_entered = False
        try:
            with headed._lease(profile / "profile.lock"):
                session.pacing_sha256 = _manual_reserve(
                    self._root, profile, session.engine, datetime.now(UTC)
                )
                if session.pacing_sha256 is None:
                    session.status = CaptchaSessionStatus.FAILED
                    session.reason_code = "PACING_ACTIVE"
                    return
                browser_cm = _open_manual_browser(session, profile, self._root)
                try:
                    session.handle = await asyncio.wait_for(
                        browser_cm.__aenter__(), timeout=STARTUP_SECONDS
                    )
                except Exception:
                    if session.rate_limited:
                        await _persist_rate_limit(self._root, profile, session.engine)
                    raise
                browser_entered = True
                if session.status == CaptchaSessionStatus.STARTING:
                    session.status = CaptchaSessionStatus.WAITING
                remaining = max(0.0, (session.expires_at - datetime.now(UTC)).total_seconds())
                try:
                    try:
                        await asyncio.wait_for(session.stop.wait(), timeout=remaining)
                    except TimeoutError:
                        expired = session.status == CaptchaSessionStatus.WAITING
                    else:
                        expired = session.expiry_requested
                    rate_limited = session.rate_limited
                    if rate_limited:
                        await _persist_rate_limit(self._root, profile, session.engine)
                finally:
                    session.handle = None
                    closing_cm = browser_cm
                    browser_cm = None
                    await _close_browser_context(closing_cm)
                if expired:
                    session.status = CaptchaSessionStatus.EXPIRED
                elif rate_limited:
                    session.proof = None
                    session.status = CaptchaSessionStatus.FAILED
                    session.reason_code = "RATE_LIMITED"
        except FileExistsError:
            session.status = CaptchaSessionStatus.FAILED
            session.reason_code = "PROFILE_BUSY"
        except (FileNotFoundError, ImportError):
            session.status = CaptchaSessionStatus.FAILED
            session.reason_code = "BROWSER_UNAVAILABLE"
        except asyncio.CancelledError:
            if browser_cm is not None:
                session.handle = None
                closing_cm = browser_cm
                browser_cm = None
                try:
                    await _close_browser_context(closing_cm)
                except Exception:
                    session.status = CaptchaSessionStatus.FAILED
                    session.reason_code = "CLEANUP_FAILED"
            if session.status not in {
                CaptchaSessionStatus.CANCELLED,
                CaptchaSessionStatus.VERIFIED,
            }:
                session.status = CaptchaSessionStatus.CANCELLED
            raise
        except Exception:
            session.handle = None
            session.proof = None
            session.status = CaptchaSessionStatus.FAILED
            session.reason_code = (
                "RATE_LIMITED"
                if session.rate_limited
                else "CLEANUP_FAILED"
                if browser_entered
                else "STARTUP_FAILED"
            )
            if browser_cm is not None:
                closing_cm = browser_cm
                browser_cm = None
                with suppress(Exception):
                    await _close_browser_context(closing_cm)
        finally:
            session.handle = None
            async with self._lock:
                if self._active_id == session.session_id:
                    self._active_id = None

    def _owned(self, company_id: str, actor_id: str, session_id: UUID) -> _Session:
        _validate_owner(company_id, actor_id)
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.company_id != company_id
            or session.actor_id != actor_id
        ):
            raise LookupError("CAPTCHA_SESSION_NOT_FOUND")
        return session

    def _waiting(self, company_id: str, actor_id: str, session_id: UUID) -> _Session:
        session = self._owned(company_id, actor_id, session_id)
        if session.status != CaptchaSessionStatus.WAITING or session.handle is None:
            raise RuntimeError("CAPTCHA_SESSION_NOT_WAITING")
        if session.rate_limited:
            session.stop.set()
            raise RuntimeError("CAPTCHA_SESSION_RATE_LIMITED")
        if datetime.now(UTC) >= session.expires_at:
            session.expiry_requested = True
            session.stop.set()
            raise RuntimeError("CAPTCHA_SESSION_EXPIRED")
        return session

    @staticmethod
    def _view(session: _Session) -> CaptchaSessionView:
        return CaptchaSessionView(
            session_id=session.session_id,
            run_id=session.run_id,
            engine=session.engine,
            status=session.status,
            expires_at=session.expires_at,
            reason_code=session.reason_code,  # type: ignore[arg-type]
        )
