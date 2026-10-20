"""Playwright в отдельном thread/loop, включая Windows Uvicorn Selector loop."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from anyio import to_thread

from procurement.sources.browser_catalog import (
    BrowserAttempt,
    BrowserOptions,
    BrowserSite,
    BrowserStatus,
    preview_browser_catalog,
)
from procurement.sources.catalog_routes import category_page_url, yandex_route
from procurement.sources.servermall import SERVERMALL_HPE_GEN12_URL
from procurement.sources.supl_browser import SUPL_PUMPS_URL
from procurement.sources.yandex_business import YANDEX_BUSINESS_PUMPS_URL

_BROWSER_SLOTS = threading.BoundedSemaphore(2)


def _failure(
    company_id: str, site: BrowserSite, query: str, status: BrowserStatus, reason: str
) -> BrowserAttempt:
    return BrowserAttempt(
        company_id=company_id,
        site=site,
        query=query,
        source_url=SERVERMALL_HPE_GEN12_URL
        if site == BrowserSite.SERVERMALL
        else (
            SUPL_PUMPS_URL if site == BrowserSite.SUPL_BIZ else (
                category_page_url(route, 1)
                if (route := yandex_route(query))
                else YANDEX_BUSINESS_PUMPS_URL
            )
        ),
        status=status,
        observed_at=datetime.now(UTC),
        query_mode="TITLE_TERMS",
        reason=reason,
    )


def _run(company_id: str, site: BrowserSite, query: str) -> BrowserAttempt:
    if not _BROWSER_SLOTS.acquire(blocking=False):
        return _failure(
            company_id, site, query, BrowserStatus.WORKER_BUSY, "BROWSER_CAPACITY_LIMIT"
        )
    try:
        return _run_in_loop(company_id, site, query)
    finally:
        _BROWSER_SLOTS.release()


def _run_in_loop(company_id: str, site: BrowserSite, query: str) -> BrowserAttempt:
    root = Path(os.environ.get("BROWSER_PROFILE_ROOT", "data/server-browser-profiles"))
    options = BrowserOptions(profile_root=root.resolve())
    # Windows subprocess необходим браузерному драйверу. Не меняем loop сервера.
    loop_factory = asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(
            preview_browser_catalog(company_id=company_id, site=site, query=query, options=options)
        )


async def run_browser_source(*, company_id: str, site: BrowserSite, query: str) -> BrowserAttempt:
    """Ошибка одного браузера не отменяет результаты других источников."""
    try:
        return await to_thread.run_sync(partial(_run, company_id, site, query))
    except Exception:
        # Полные сообщения ошибок могут содержать данные профиля/URL и не выдаются.
        return _failure(
            company_id, site, query, BrowserStatus.SOURCE_ERROR, "BROWSER_WORKER_FAILED"
        )
