"""Ограниченный локальный browser preview; результаты не являются допуском/КП.

Профиль содержит секреты браузера и никогда не включается в результат.
Никакой модификации fingerprint, решения CAPTCHA или смены IP при отказе.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict

from procurement.sources.catalog_routes import (
    MAX_CATEGORY_PAGES,
    YANDEX_CATEGORIES,
    CatalogPageEvidence,
    category_navigation_allowed,
    category_page_url,
    servermall_covers,
    title_matches_query,
    yandex_route,
)
from procurement.sources.eaeu_registry import _validated_query
from procurement.sources.servermall import SERVERMALL_HPE_GEN12_URL, parse_servermall_hpe_gen12
from procurement.sources.supl_browser import SUPL_PUMPS_URL, parse_supl_catalog, supl_covers
from procurement.sources.yandex_business import (
    YANDEX_BUSINESS_PUMPS_URL,
    parse_yandex_business_category,
    yandex_business_category_for_query,
)
from procurement.sources.yandex_pagination import (
    CategoryContinuation,
    PaginationError,
    category_continuation,
)

if TYPE_CHECKING:
    from playwright.async_api import Page


class BrowserSite(StrEnum):
    SERVERMALL = "servermall"
    YANDEX_BUSINESS = "yandex_business"
    SUPL_BIZ = "supl_biz"


class BrowserStatus(StrEnum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    SOURCE_ERROR = "SOURCE_ERROR"
    TIMEOUT = "TIMEOUT"
    PROFILE_BUSY = "PROFILE_BUSY"
    COOLDOWN = "COOLDOWN"
    QUERY_NOT_COVERED = "QUERY_NOT_COVERED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    WORKER_BUSY = "WORKER_BUSY"
    PARTIAL = "PARTIAL"


class BrowserCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    url: str
    locator: str
    suitability: Literal["UNKNOWN"] = "UNKNOWN"
    source_page_url: str | None = None
    source_page_number: int | None = None
    source_sha256: str | None = None
    seller_name: str | None = None
    seller_url: str | None = None


class BrowserAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str
    site: BrowserSite
    query: str
    source_url: str
    status: BrowserStatus
    observed_at: AwareDatetime
    parser_version: Literal["browser-catalog-v5"] = "browser-catalog-v5"
    coverage: Literal["BOUNDED_CATEGORY_PAGES"] = "BOUNDED_CATEGORY_PAGES"
    query_mode: Literal["TITLE_TERMS", "CATEGORY_PREVIEW"]
    evidence_kind: Literal["RENDERED_DOM"] = "RENDERED_DOM"
    dom_sha256: str | None = None
    dom_byte_size: int | None = None
    navigation_url_sha256: str | None = None
    http_status: int | None = None
    retry_at: AwareDatetime | None = None
    reason: str | None = None
    candidates: tuple[BrowserCandidate, ...] = ()
    pages: tuple[CatalogPageEvidence, ...] = ()
    scanned_count: int | None = None
    has_next_page: bool = False
    catalog_fingerprint: str | None = None
    stop_reason: str | None = None
    continuation: Literal["NEXT_PAGE", "END_REPORTED", "UNKNOWN"] = "UNKNOWN"
    continuation_evidence: Literal["LINK", "PAGE_STATE", "LINK_AND_PAGE_STATE"] | None = None
    continuation_locator: str | None = None


@dataclass(frozen=True)
class BrowserOptions:
    """Настройки оператора, не из текста внешней страницы."""

    profile_root: Path = Path("data/browser-profiles")
    headed: bool = False
    channel: Literal["chromium", "chrome", "msedge"] = "chromium"
    natural_motion: bool = True
    timeout_seconds: float = 55

    def __post_init__(self) -> None:
        if not 10 <= self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 10 and 60")
        if self.channel not in {"chromium", "chrome", "msedge"}:
            raise ValueError("unsupported browser channel")


_URLS = {
    BrowserSite.SERVERMALL: SERVERMALL_HPE_GEN12_URL,
    BrowserSite.YANDEX_BUSINESS: YANDEX_BUSINESS_PUMPS_URL,
    BrowserSite.SUPL_BIZ: SUPL_PUMPS_URL,
}
_MAX_DOM_BYTES = 3 * 1024 * 1024
_CHALLENGE_TEXT = (
    "подтвердите, что вы не робот",
    "подтвердите, что вы человек",
    "докажите, что вы не робот",
    "verify you are human",
    "verify that you are human",
    "checking your browser",
    "доступ временно ограничен",
    "доступ ограничен",
)


def catalog_navigation_allowed(
    site: BrowserSite, url: str, expected_url: str | None = None
) -> bool:
    """Только известная категория; rs хранится лишь в digest адреса навигации."""
    if site != BrowserSite.YANDEX_BUSINESS:
        return url == _URLS[site]
    try:
        expected = urlsplit(expected_url or _URLS[site])
        number = int(parse_qs(expected.query).get("page", ["1"])[0])
        route = next(
            (r for r in YANDEX_CATEGORIES if r.url == expected._replace(query="").geturl()), None
        )
        return route is not None and category_navigation_allowed(route, url, number)
    except (ValueError, IndexError):
        return False


def classify_page(status: int, url: str, title: str, visible_text: str) -> BrowserStatus | None:
    """HTTP и видимая challenge-страница имеют приоритет над карточками."""
    if status == 429:
        return BrowserStatus.RATE_LIMITED
    if status == 401:
        return BrowserStatus.AUTH_REQUIRED
    if status in {403, 451}:
        return BrowserStatus.BLOCKED
    path = urlsplit(url).path.casefold()
    text = " ".join(visible_text.casefold().split())
    if (
        any(part in path for part in ("/captcha", "/showcaptcha", "/challenge"))
        or title.strip().casefold() in {"just a moment...", "access denied", "ой!"}
        or any(marker in text for marker in _CHALLENGE_TEXT)
    ):
        return BrowserStatus.BLOCKED
    if any(part in path.split("/") for part in ("login", "signin", "auth")):
        return BrowserStatus.AUTH_REQUIRED
    if status != 200:
        return BrowserStatus.SOURCE_ERROR
    return None


def cursor_path(
    start: tuple[float, float], end: tuple[float, float], *, rng: random.Random
) -> tuple[tuple[float, float, float], ...]:
    """Кривая Безье с разгоном/торможением; x, y и задержка в секундах.

    Модель движения для UI, не утверждение о неотличимости от человека.
    """
    distance = math.dist(start, end)
    steps = min(50, max(12, int(distance / 15)))
    duration = min(0.9, 0.22 + distance / 1800) * rng.uniform(0.9, 1.15)
    # Контрольная точка внутри прямоугольника: путь не вылетает за viewport.
    control = tuple(start[i] + (end[i] - start[i]) * rng.uniform(0.25, 0.75) for i in (0, 1))
    points: list[tuple[float, float, float]] = []
    for step in range(1, steps + 1):
        t = step / steps
        eased = t * t * (3 - 2 * t)
        xy = tuple(
            (1 - eased) ** 2 * start[i] + 2 * (1 - eased) * eased * control[i] + eased**2 * end[i]
            for i in (0, 1)
        )
        points.append((xy[0], xy[1], duration / steps))
    return tuple(points)


def profile_directory(root: Path, company_id: str, site: BrowserSite) -> Path:
    """Непересекающиеся имена профилей без path traversal из company_id."""
    if not company_id.strip() or len(company_id) > 200:
        raise ValueError("company_id must contain 1–200 characters")
    tenant_key = hashlib.sha256(company_id.encode()).hexdigest()
    resolved_root = root.resolve()
    directory = (resolved_root / tenant_key / site.value).resolve()
    if not directory.is_relative_to(resolved_root):
        raise ValueError("profile path escaped profile root")
    return directory


@contextmanager
def profile_lease(directory: Path) -> Iterator[None]:
    """Один процесс на профиль; файл остаётся после crash для явного разбора."""
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "preview.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(datetime.now(UTC).isoformat())
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _read_cooldown(directory: Path, company_id: str) -> datetime | None:
    path = directory / "cooldown.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    until = datetime.fromisoformat(record["retry_at"])
    if record["company_id"] != company_id or until.utcoffset() is None:
        raise ValueError("invalid profile cooldown")
    return until if until > datetime.now(UTC) else None


def _write_cooldown(directory: Path, company_id: str, until: datetime) -> None:
    temporary = directory / "cooldown.tmp"
    temporary.write_text(
        json.dumps({"company_id": company_id, "retry_at": until.isoformat()}), encoding="utf-8"
    )
    temporary.replace(directory / "cooldown.json")


def _retry_at(header: str | None, now: datetime) -> datetime:
    fallback = now + timedelta(minutes=15)
    if not header:
        return fallback
    try:
        if header.strip().isdigit():
            return max(fallback, now + timedelta(seconds=int(header)))
        moment = parsedate_to_datetime(header)
        if moment.utcoffset() is not None:
            return max(fallback, moment)
    except (ValueError, TypeError, OverflowError):
        # Некорректный Retry-After не запускает retry storm.
        return now + timedelta(days=1)
    return fallback


def _extract(site: BrowserSite, content: bytes, query: str) -> tuple[BrowserCandidate, ...]:
    if site == BrowserSite.SERVERMALL:
        leads = parse_servermall_hpe_gen12(content, query=query, observed_at=datetime.now(UTC))
        return tuple(
            BrowserCandidate(
                title=lead.product_name,
                url=lead.product_url,
                locator=f"OfferCatalog/Offer[url={lead.product_url}]",
            )
            for lead in leads
        )
    if site == BrowserSite.SUPL_BIZ:
        return tuple(
            BrowserCandidate(
                title=row.title,
                url=row.url,
                locator=f"Product[proposal-preview][{row.source_item_index}]",
                seller_name=row.seller_name,
                seller_url=row.seller_url,
            )
            for row in parse_supl_catalog(content)
        )
    _, rows = parse_yandex_business_category(content)
    return tuple(
        BrowserCandidate(
            title=row.title,
            url=row.url,
            locator=f"ItemList/itemListElement[{row.source_item_index}]",
        )
        for row in rows
    )


async def _page_status(page: Page, http_status: int) -> BrowserStatus | None:
    # Только видимый текст: слово captcha в JS-библиотеке не блокирует каталог.
    text = await page.locator("body").inner_text(timeout=1500)
    result = classify_page(http_status, page.url, await page.title(), text[:100_000])
    if result is not None:
        return result
    challenges = page.locator(
        'iframe[src*="captcha"], iframe[src*="challenges.cloudflare.com"], '
        'input[name="captcha"], #challenge-running'
    )
    for index in range(min(await challenges.count(), 5)):
        if await challenges.nth(index).is_visible():
            return BrowserStatus.BLOCKED
    return None


async def _browse_motion(page: Page) -> None:
    rng = random.Random()
    viewport = page.viewport_size or {"width": 1365, "height": 900}
    start = (0.0, 0.0)
    for _ in range(3):
        end = (
            viewport["width"] * rng.uniform(0.3, 0.7),
            viewport["height"] * rng.uniform(0.3, 0.65),
        )
        for x, y, delay in cursor_path(start, end, rng=rng):
            await page.mouse.move(x, y)
            await asyncio.sleep(delay)
        start = end
        await asyncio.sleep(rng.uniform(0.25, 0.65))
        # Порционная прокрутка запускает штатную lazy loading страницы.
        for _ in range(3):
            await page.mouse.wheel(0, rng.uniform(70, 130))
            await asyncio.sleep(rng.uniform(0.08, 0.16))
        await asyncio.sleep(rng.uniform(0.4, 0.8))


async def _run_page(page: Page, base: BrowserAttempt, options: BrowserOptions) -> BrowserAttempt:
    response = await page.goto(base.source_url, wait_until="domcontentloaded", timeout=25_000)
    status = response.status if response else 0
    base = base.model_copy(update={"http_status": status})
    headers = await response.all_headers() if response else {}

    async def blocked_result() -> BrowserAttempt | None:
        # HTTP-отказ не требует доступного body (например, пустой 403).
        failure = classify_page(status, page.url, "", "")
        if failure is None:
            failure = await _page_status(page, status)
        if failure is None:
            return None
        return base.model_copy(
            update={
                "status": failure,
                "http_status": status,
                "observed_at": datetime.now(UTC),
                "reason": "PAGE_REQUIRES_ATTENTION",
                "retry_at": _retry_at(headers.get("retry-after"), datetime.now(UTC)),
            }
        )

    failure = await blocked_result()
    if failure is not None:
        return failure
    if not catalog_navigation_allowed(base.site, page.url, base.source_url):
        return base.model_copy(
            update={
                "status": BrowserStatus.SOURCE_CHANGED,
                "reason": "UNEXPECTED_REDIRECT",
                "http_status": status,
            }
        )
    if options.natural_motion:
        await _browse_motion(page)
    # JSON-LD может появиться после hydration. Две одинаковые валидные выдачи
    # уменьшают риск чтения промежуточного состояния; hard timeout остаётся общим.
    deadline = asyncio.get_running_loop().time() + 12
    previous: tuple[BrowserCandidate, ...] | None = None
    while asyncio.get_running_loop().time() < deadline:
        failure = await blocked_result()
        if failure is not None:
            return failure
        if not catalog_navigation_allowed(base.site, page.url, base.source_url):
            return base.model_copy(
                update={"status": BrowserStatus.SOURCE_CHANGED, "reason": "UNEXPECTED_REDIRECT"}
            )
        content = (await page.content()).encode("utf-8")
        if len(content) > _MAX_DOM_BYTES:
            return base.model_copy(
                update={"status": BrowserStatus.SOURCE_CHANGED, "reason": "DOM_SIZE_LIMIT"}
            )
        try:
            candidates = _extract(base.site, content, base.query)
        except ValueError:
            previous = None
        else:
            if previous == candidates:
                digest = hashlib.sha256(content).hexdigest()
                route = (
                    yandex_route(base.query) if base.site == BrowserSite.YANDEX_BUSINESS else None
                )
                number = int(parse_qs(urlsplit(base.source_url).query).get("page", ["1"])[0])
                try:
                    continuation = (
                        category_continuation(content, route, number)
                        if route
                        else CategoryContinuation("UNKNOWN")
                    )
                except PaginationError:
                    return base.model_copy(
                        update={
                            "status": BrowserStatus.SOURCE_CHANGED,
                            "reason": "PAGINATION_STATE_INVALID",
                        }
                    )
                matches = tuple(
                    row.model_copy(
                        update={
                            "source_page_url": base.source_url,
                            "source_page_number": number,
                            "source_sha256": digest,
                        }
                    )
                    for row in candidates
                    if base.site == BrowserSite.SERVERMALL
                    or title_matches_query(row.title, base.query)
                )
                return base.model_copy(
                    update={
                        "status": BrowserStatus.COMPLETED,
                        "observed_at": datetime.now(UTC),
                        "http_status": status,
                        "dom_sha256": digest,
                        "dom_byte_size": len(content),
                        "navigation_url_sha256": hashlib.sha256(page.url.encode()).hexdigest(),
                        "candidates": matches,
                        "scanned_count": len(candidates)
                        if route or base.site == BrowserSite.SUPL_BIZ
                        else None,
                        "catalog_fingerprint": hashlib.sha256(
                            json.dumps(sorted(row.url for row in candidates)).encode()
                        ).hexdigest(),
                        "has_next_page": continuation.status == "NEXT_PAGE",
                        "continuation": continuation.status,
                        "continuation_evidence": continuation.evidence,
                        "continuation_locator": continuation.locator,
                    }
                )
            previous = candidates
        await asyncio.sleep(0.5)
    return base.model_copy(
        update={
            "status": BrowserStatus.SOURCE_CHANGED,
            "http_status": status,
            "reason": "CATALOG_SCHEMA_NOT_READY",
        }
    )


async def _run_pages(page: Page, base: BrowserAttempt, options: BrowserOptions) -> BrowserAttempt:
    """Частичный успех не теряется при timeout/блокировке следующей страницы."""
    route = yandex_route(base.query) if base.site == BrowserSite.YANDEX_BUSINESS else None
    budget = MAX_CATEGORY_PAGES if route else 1
    deadline = asyncio.get_running_loop().time() + max(1, options.timeout_seconds - 18)
    pages: list[CatalogPageEvidence] = []
    seen: set[str] = set()
    candidates: dict[str, BrowserCandidate] = {}
    first: BrowserAttempt | None = None
    stop_reason = "PAGE_LIMIT"
    result = base
    for number in range(1, budget + 1):
        url = category_page_url(route, number) if route else base.source_url
        if number > 1:
            await asyncio.sleep(1)
        attempt = base.model_copy(update={"source_url": url})
        try:
            result = await asyncio.wait_for(
                _run_page(page, attempt, options),
                timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
            )
        except TimeoutError:
            result = attempt.model_copy(
                update={"status": BrowserStatus.TIMEOUT, "reason": "PAGE_TIME_BUDGET"}
            )
        except Exception:
            result = attempt.model_copy(
                update={"status": BrowserStatus.SOURCE_ERROR, "reason": "PAGE_REQUEST_FAILED"}
            )
        if result.status == BrowserStatus.COMPLETED and result.catalog_fingerprint in seen:
            result = result.model_copy(
                update={
                    "status": BrowserStatus.SOURCE_CHANGED,
                    "reason": "REPEATED_PAGE",
                    "candidates": (),
                }
            )
        successful = result.status == BrowserStatus.COMPLETED
        pages.append(
            CatalogPageEvidence(
                page_number=number,
                source_url=url,
                observed_at=result.observed_at,
                status="COMPLETED" if successful else "SOURCE_ERROR",
                sha256=result.dom_sha256,
                byte_size=result.dom_byte_size,
                scanned_count=result.scanned_count or 0,
                matched_count=len(result.candidates) if successful else 0,
                error_code=None if successful else result.reason or result.status.value,
                continuation=result.continuation,
                continuation_evidence=result.continuation_evidence,
                continuation_locator=result.continuation_locator,
            )
        )
        if not successful:
            stop_reason = result.reason or result.status.value
            break
        first = first or result
        if result.catalog_fingerprint:
            seen.add(result.catalog_fingerprint)
        for candidate in result.candidates:
            candidates.setdefault(candidate.url, candidate)
        if not result.has_next_page:
            stop_reason = (
                "END_REPORTED" if result.continuation == "END_REPORTED" else "NO_NEXT_EVIDENCE"
            )
            break
    if first is None:
        return result.model_copy(update={"pages": tuple(pages), "stop_reason": stop_reason})
    return first.model_copy(
        update={
            "status": BrowserStatus.COMPLETED
            if result.status == BrowserStatus.COMPLETED
            else BrowserStatus.PARTIAL,
            "observed_at": datetime.now(UTC),
            "pages": tuple(pages),
            "candidates": tuple(candidates.values()),
            "retry_at": result.retry_at,
            "reason": result.reason,
            "stop_reason": stop_reason,
            "scanned_count": sum(p.scanned_count for p in pages if p.status == "COMPLETED")
            if route or base.site == BrowserSite.SUPL_BIZ
            else None,
            "has_next_page": result.has_next_page,
            "continuation": result.continuation,
            "continuation_evidence": result.continuation_evidence,
            "continuation_locator": result.continuation_locator,
        }
    )


async def _launch(directory: Path, base: BrowserAttempt, options: BrowserOptions) -> BrowserAttempt:
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright
    except ImportError:
        return base.model_copy(
            update={"status": BrowserStatus.BROWSER_UNAVAILABLE, "reason": "INSTALL_BROWSER_EXTRA"}
        )
    try:
        async with async_playwright() as playwright:
            try:
                context = await playwright.chromium.launch_persistent_context(
                    str(directory / options.channel),
                    channel=options.channel,
                    headless=not options.headed,
                    viewport={"width": 1365, "height": 900},
                    accept_downloads=False,
                    timeout=15_000,
                )
            except Error:
                return base.model_copy(
                    update={
                        "status": BrowserStatus.BROWSER_UNAVAILABLE,
                        "reason": "BROWSER_LAUNCH_FAILED",
                    }
                )
            try:
                # Новый tab не использует DOM от предыдущего запуска профиля.
                page = await context.new_page()
                page.set_default_timeout(5000)
                return await _run_pages(page, base, options)
            finally:
                await context.close()
    except TimeoutError:
        return base.model_copy(
            update={"status": BrowserStatus.TIMEOUT, "reason": "BROWSER_WAIT_TIMEOUT"}
        )
    except Error as error:
        # Исключения Playwright могут содержать URL/токены: не выводим их.
        network_code = re.search(r"net::(ERR_[A-Z_]+)", str(error))
        return base.model_copy(
            update={
                "status": BrowserStatus.SOURCE_ERROR,
                "reason": network_code.group(1) if network_code else "BROWSER_REQUEST_FAILED",
            }
        )


async def preview_browser_catalog(
    *, company_id: str, site: BrowserSite, query: str, options: BrowserOptions | None = None
) -> BrowserAttempt:
    """Один ручной read-only preview; повторные запросы автоматически не делаются."""
    options = options or BrowserOptions()
    normalized = " ".join(_validated_query(query))
    if not any(character.isalnum() for character in normalized):
        raise ValueError("query must contain a letter or digit")
    directory = profile_directory(options.profile_root, company_id, site)
    base = BrowserAttempt(
        company_id=company_id,
        site=site,
        query=normalized,
        source_url=(yandex_business_category_for_query(normalized) or _URLS[site])
        if site == BrowserSite.YANDEX_BUSINESS
        else _URLS[site],
        status=BrowserStatus.SOURCE_ERROR,
        observed_at=datetime.now(UTC),
        query_mode="TITLE_TERMS",
    )
    if (site == BrowserSite.YANDEX_BUSINESS and yandex_route(normalized) is None) or (
        site == BrowserSite.SERVERMALL and not servermall_covers(normalized)
    ) or (
        site == BrowserSite.SUPL_BIZ and not supl_covers(normalized)
    ):
        return base.model_copy(
            update={
                "status": BrowserStatus.QUERY_NOT_COVERED,
                "reason": "NO_VERIFIED_CATEGORY_FOR_QUERY",
            }
        )
    try:
        with profile_lease(directory):
            until = _read_cooldown(directory, company_id)
            if until:
                return base.model_copy(update={"status": BrowserStatus.COOLDOWN, "retry_at": until})
            # Сохраняем до сети: crash не разрешает немедленный повтор.
            until = datetime.now(UTC) + timedelta(seconds=60)
            _write_cooldown(directory, company_id, until)
            try:
                result = await asyncio.wait_for(
                    _launch(directory, base, options), timeout=options.timeout_seconds
                )
            except TimeoutError:
                result = base.model_copy(
                    update={"status": BrowserStatus.TIMEOUT, "reason": "TOTAL_TIME_BUDGET"}
                )
            until = max(until, result.retry_at or until)
            _write_cooldown(directory, company_id, until)
            return result.model_copy(update={"retry_at": until, "observed_at": datetime.now(UTC)})
    except FileExistsError:
        return base.model_copy(
            update={"status": BrowserStatus.PROFILE_BUSY, "reason": "PROFILE_ALREADY_IN_USE"}
        )
    except (OSError, ValueError, KeyError, TypeError):
        return base.model_copy(
            update={"status": BrowserStatus.SOURCE_ERROR, "reason": "PROFILE_STATE_UNAVAILABLE"}
        )
