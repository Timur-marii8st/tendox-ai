"""Worker изолирует исключения и поддерживает subprocess loop на Windows."""

import asyncio
import sys
import threading
from datetime import UTC, datetime

from procurement.sources import browser_worker as module
from procurement.sources.browser_catalog import BrowserAttempt, BrowserSite, BrowserStatus


def test_browser_worker_uses_tenant_and_private_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_PROFILE_ROOT", str(tmp_path))

    async def preview(*, company_id, site, query, options):
        assert company_id == "tenant-a"
        assert options.profile_root == tmp_path.resolve()
        if sys.platform == "win32":
            assert "Proactor" in type(asyncio.get_running_loop()).__name__
        return BrowserAttempt(
            company_id=company_id,
            site=site,
            query=query,
            source_url="https://servermall.ru/",
            status=BrowserStatus.COMPLETED,
            observed_at=datetime.now(UTC),
            query_mode="TITLE_TERMS",
        )

    monkeypatch.setattr(module, "preview_browser_catalog", preview)
    result = asyncio.run(
        module.run_browser_source(company_id="tenant-a", site=BrowserSite.SERVERMALL, query="DL360")
    )
    assert result.status == BrowserStatus.COMPLETED


def test_worker_exception_is_sanitized_and_typed(monkeypatch) -> None:
    def broken(*args):
        raise RuntimeError("sensitive-cookie-secret")

    monkeypatch.setattr(module, "_run", broken)
    result = asyncio.run(
        module.run_browser_source(company_id="tenant-a", site=BrowserSite.SERVERMALL, query="DL360")
    )
    assert result.status == BrowserStatus.SOURCE_ERROR
    assert result.reason == "BROWSER_WORKER_FAILED"
    assert "sensitive-cookie-secret" not in result.model_dump_json()


def test_worker_capacity_returns_status_without_starting_browser(monkeypatch) -> None:
    monkeypatch.setattr(module, "_BROWSER_SLOTS", threading.BoundedSemaphore(0))
    result = asyncio.run(
        module.run_browser_source(company_id="tenant-a", site=BrowserSite.SERVERMALL, query="DL360")
    )
    assert result.status == BrowserStatus.WORKER_BUSY
