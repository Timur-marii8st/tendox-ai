import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID

import httpx
from fastapi import FastAPI

from procurement.access import AccessRole
from procurement.api import supplier_captcha as api
from procurement.api.contracts import Principal
from procurement.sources.supplier_captcha_browser import CaptchaSessionStatus, CaptchaSessionView
from procurement.sources.supplier_serp import SearchEngine

ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST = {
    "selection": {
        "notice": {
            "purchase_number": "0848300054826000154",
            "version_number": 1,
            "notice_xml_sha256": "a" * 64,
        },
        "source_index": 1,
    }
}


class Auth:
    async def authenticate(self, token):
        if token == "bad":
            return None
        return Principal(
            company_id="a" if token != "other" else "b",
            actor_id=token,
            access_role=AccessRole.OPERATOR,
        )


class Browser:
    calls: ClassVar[list] = []

    def __init__(self, root):
        pass

    async def start(self, company, actor, engine, query, run):
        self.calls.append((company, actor, engine, query, run))
        return self.view()

    def view(self):
        return CaptchaSessionView(
            session_id=ID,
            run_id=ID,
            engine=SearchEngine.GOOGLE,
            status="WAITING",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    async def status(self, *args):
        return self.view()

    async def shutdown(self):
        pass


def test_auth_owner_isolation_and_exact_server_query(monkeypatch, tmp_path):
    async def check():
        monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(api, "CaptchaBrowserManager", Browser)
        report = SimpleNamespace(query="server-derived exact query", run_id=str(ID))
        monkeypatch.setattr(api, "admit_captcha", lambda *args: report)
        app = FastAPI()
        api.install_captcha_routes(app, Auth(), object())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            body = {"request": REQUEST, "run_id": str(ID), "engine": "GOOGLE"}
            prefix = "/v1/tender-discovery/supplier-captcha/"
            for token in (None, "bad"):
                r = await c.post(
                    prefix + "start",
                    json=body,
                    headers={} if token is None else {"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 401
                assert "no-store" in r.headers["Cache-Control"]
            r = await c.post(
                prefix + "start",
                json={**body, "query": "attacker"},
                headers={"Authorization": "Bearer owner"},
            )
            assert r.status_code == 422
            r = await c.post(prefix + "start", json=body, headers={"Authorization": "Bearer owner"})
            assert r.status_code == 200 and Browser.calls[-1][3] == "server-derived exact query"
            r = await c.post(
                prefix + "status",
                json={"session_id": str(ID)},
                headers={"Authorization": "Bearer other"},
            )
            assert r.status_code == 404
            r = await c.post(
                prefix + "status",
                json={"session_id": str(ID)},
                headers={"Authorization": "Bearer different-actor"},
            )
            assert r.status_code == 404
            r = await c.post(
                prefix + "status",
                json={"session_id": str(ID)},
                headers={"Authorization": "Bearer owner"},
            )
            assert r.status_code == 200
            assert not any(key in r.json() for key in ("query", "cookies", "profile", "cdp"))
        for callback in app.router.on_shutdown:
            monkeypatch.setattr(api, "audit_captcha_end", lambda *args: None)
            await callback()

    asyncio.run(check())


def test_unavailable_or_disabled_engine_does_not_open_browser(monkeypatch, tmp_path):
    async def check():
        monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", str(tmp_path))
        app = FastAPI()
        api.install_captcha_routes(app, Auth(), None)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/v1/tender-discovery/supplier-captcha/start",
                json={"request": REQUEST, "run_id": str(ID), "engine": "GOOGLE"},
                headers={"Authorization": "Bearer owner"},
            )
            assert r.status_code == 503

    asyncio.run(check())


def test_discovery_factory_retains_assistance_router_after_route_filter(monkeypatch):
    from procurement.api.discovery_runtime import create_discovery_app

    async def check():
        monkeypatch.setenv("EIS_PILOT_TOKEN", "x" * 32)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = create_discovery_app()
        assert "/v1/tender-discovery/supplier-captcha/start" in app.openapi()["paths"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/tender-discovery/supplier-captcha/start",
                json={"request": REQUEST, "run_id": str(ID), "engine": "GOOGLE"},
                headers={"Authorization": "Bearer " + "x" * 32},
            )
            assert response.status_code == 503

    asyncio.run(check())


def test_verified_source_without_pacing_grant_does_not_authorize_retry(monkeypatch, tmp_path):
    from procurement.sources import supplier_captcha_recovery as recovery

    class VerifiedBrowser(Browser):
        verified = False

        def view(self):
            value = super().view()
            return value.model_copy(
                update={
                    "status": (
                        CaptchaSessionStatus.VERIFIED
                        if self.verified
                        else CaptchaSessionStatus.WAITING
                    )
                }
            )

        async def verify(self, *args):
            self.verified = True
            return self.view()

        async def proof(self, *args):
            return SimpleNamespace(content=b"fixture", attempt=None, pacing_sha256=("a", "b"))

    async def check():
        monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(api, "CaptchaBrowserManager", VerifiedBrowser)
        report = SimpleNamespace(
            query="server-derived exact query", run_id=str(ID), request=REQUEST
        )
        monkeypatch.setattr(api, "admit_captcha", lambda *args: report)
        monkeypatch.setattr(api, "read_supplier_serp", lambda *args: SimpleNamespace(report=report))
        monkeypatch.setattr(recovery, "retain_proof", lambda *args: None)
        monkeypatch.setattr(
            api, "issue_retry", lambda *args: (_ for _ in ()).throw(ValueError("changed"))
        )
        outcomes = []
        monkeypatch.setattr(api, "audit_captcha_end", lambda *args: outcomes.append(args[6]))
        app = FastAPI()
        api.install_captcha_routes(app, Auth(), object())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            headers = {"Authorization": "Bearer owner"}
            prefix = "/v1/tender-discovery/supplier-captcha/"
            await c.post(
                prefix + "start",
                json={"request": REQUEST, "run_id": str(ID), "engine": "GOOGLE"},
                headers=headers,
            )
            response = await c.post(
                prefix + "verify", json={"session_id": str(ID)}, headers=headers
            )
            assert response.status_code == 200
            assert response.json()["status"] == "VERIFIED"
            assert response.json()["retry_ready"] is False
            assert outcomes == ["VERIFIED_NO_RETRY"]
            repeated = await c.post(
                prefix + "verify", json={"session_id": str(ID)}, headers=headers
            )
            assert repeated.json()["retry_ready"] is False
            assert outcomes == ["VERIFIED_NO_RETRY"]
        for callback in app.router.on_shutdown:
            await callback()

    asyncio.run(check())


def test_disconnected_verify_finishes_and_status_retains_retry_pacing(monkeypatch, tmp_path):
    import threading
    from contextlib import suppress

    from procurement.sources import supplier_captcha_recovery as recovery

    class VerifiedBrowser(Browser):
        verified = False

        def view(self):
            value = super().view()
            return value.model_copy(update={"status": (
                CaptchaSessionStatus.VERIFIED if self.verified else CaptchaSessionStatus.WAITING
            )})

        async def verify(self, *args):
            self.verified = True
            return self.view()

        async def proof(self, *args):
            return SimpleNamespace(content=b"fixture", attempt=None, pacing_sha256=("a", "b"))

    async def check():
        entered, release = threading.Event(), threading.Event()
        monkeypatch.setenv("SUPPLIER_SERP_BROWSER_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(api, "CaptchaBrowserManager", VerifiedBrowser)
        report = SimpleNamespace(query="exact query", run_id=str(ID), request=REQUEST)
        monkeypatch.setattr(api, "admit_captcha", lambda *args: report)
        monkeypatch.setattr(api, "read_supplier_serp", lambda *args: SimpleNamespace(report=report))
        monkeypatch.setattr(recovery, "retain_proof", lambda *args: None)
        monkeypatch.setattr(api, "issue_retry", lambda *args: 35)
        outcomes = []

        def audit(*args):
            entered.set()
            assert release.wait(3)
            outcomes.append(args[6])

        monkeypatch.setattr(api, "audit_captcha_end", audit)
        app = FastAPI()
        api.install_captcha_routes(app, Auth(), object())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer owner"}
            prefix = "/v1/tender-discovery/supplier-captcha/"
            await client.post(prefix + "start", json={
                "request": REQUEST, "run_id": str(ID), "engine": "GOOGLE"
            }, headers=headers)
            task = asyncio.create_task(client.post(
                prefix + "verify", json={"session_id": str(ID)}, headers=headers
            ))
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            pending = await client.post(
                prefix + "status", json={"session_id": str(ID)}, headers=headers
            )
            assert pending.json()["finalizing"] is True
            assert pending.json()["retry_ready"] is False
            release.set()
            for _ in range(100):
                status = await client.post(
                    prefix + "status", json={"session_id": str(ID)}, headers=headers
                )
                if status.json()["retry_ready"]:
                    break
                await asyncio.sleep(0.01)
            assert status.json()["finalizing"] is False
            assert status.json()["retry_ready"] is True
            assert 1 <= status.json()["retry_after_seconds"] <= 35
            assert outcomes == ["VERIFIED"]
        for callback in app.router.on_shutdown:
            await callback()

    asyncio.run(check())
