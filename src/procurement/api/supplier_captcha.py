"""Authenticated, exact-observation human browser assistance for the EIS pilot."""

import asyncio
import math
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, ValidationError

from procurement.access import AccessRole
from procurement.api.contracts import Authenticator, Principal
from procurement.sources.supplier_captcha_browser import CaptchaBrowserManager
from procurement.sources.supplier_captcha_recovery import issue_retry
from procurement.sources.supplier_serp import ENGINES, SearchEngine
from procurement.sources.supplier_serp_browser import profile_directory
from procurement.storage.eis_supplier_search import SupplierSearchRequest
from procurement.storage.eis_supplier_serp import read_supplier_serp
from procurement.storage.repository import PostgresStorage
from procurement.storage.supplier_captcha import admit_captcha, audit_captcha_end


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: SupplierSearchRequest
    run_id: UUID
    engine: SearchEngine


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID


class InputRequest(SessionRequest):
    event: dict


async def _body(request: Request, model):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 4096:
            raise HTTPException(413, "captcha_request_limit")
    try:
        return model.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise HTTPException(422, "captcha_request_invalid") from None


def install_captcha_routes(
    app: FastAPI,
    authenticator: Authenticator,
    storage: PostgresStorage | None,
) -> None:
    router = APIRouter(prefix="/v1/tender-discovery/supplier-captcha")
    manager = None
    contexts: dict[UUID, tuple[Principal, object, SearchEngine]] = {}
    finished: set[UUID] = set()
    ready: dict[UUID, float] = {}
    finalizers: dict[UUID, asyncio.Task] = {}
    monitors: set[asyncio.Task] = set()
    bearer = HTTPBearer(auto_error=False)
    mutation_lock = asyncio.Lock()

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/tender-discovery/supplier-captcha/"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def operator(
        credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        if credential is None or credential.scheme.lower() != "bearer":
            raise HTTPException(401, "invalid_credentials")
        principal = await authenticator.authenticate(credential.credentials)
        if principal is None:
            raise HTTPException(401, "invalid_credentials")
        if principal.access_role != AccessRole.OPERATOR:
            raise HTTPException(403, "operator_role_required")
        return principal

    def configured() -> CaptchaBrowserManager:
        nonlocal manager
        if storage is None:
            raise HTTPException(503, "captcha_unavailable")
        raw = os.environ.get("SUPPLIER_SERP_BROWSER_STATE_DIR", "")
        root = Path(raw)
        if not raw or not root.is_absolute():
            raise HTTPException(503, "captcha_unavailable")
        if manager is None:
            manager = CaptchaBrowserManager(root)
        return manager

    def retry_delay(session_id):
        return max(0, math.ceil(ready.get(session_id, 0) - asyncio.get_running_loop().time()))

    def reply(value, retry_after: int | None = None):
        result = value.model_dump(mode="json")
        session_id = getattr(value, "session_id", None)
        result["retry_after_seconds"] = (
            retry_delay(session_id) if retry_after is None else retry_after
        )
        result["retry_ready"] = session_id in ready
        pending = finalizers.get(session_id)
        result["finalizing"] = pending is not None and not pending.done()
        return JSONResponse(
            result,
            headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"},
        )

    async def finish(session_id: UUID, outcome: str, attempt=None):
        if session_id in finished:
            return
        principal, report, engine = contexts[session_id]
        await asyncio.to_thread(
            audit_captcha_end,
            storage,
            principal.company_id,
            principal.actor_id,
            report,
            engine,
            str(session_id),
            outcome,
            attempt,
        )
        finished.add(session_id)

    async def monitor(session_id: UUID):
        principal, _, _ = contexts[session_id]
        while True:
            await asyncio.sleep(1)
            view = await configured().status(principal.company_id, principal.actor_id, session_id)
            if view.status in {"CANCELLED", "EXPIRED", "FAILED"}:
                async with mutation_lock:
                    await finish(session_id, view.status)
                return
            if view.status == "VERIFIED":
                return

    async def verify_and_finalize(session_id: UUID):
        async with mutation_lock:
            browser = configured()
            principal, previous, engine = contexts[session_id]
            latest = await asyncio.to_thread(
                read_supplier_serp,
                storage,
                principal.company_id,
                previous.request,
            )
            if latest.report.run_id != previous.run_id:
                await browser.cancel(principal.company_id, principal.actor_id, session_id)
                await finish(session_id, "STALE")
                raise HTTPException(409, "captcha_observation_stale")
            view = await browser.status(principal.company_id, principal.actor_id, session_id)
            if view.status != "VERIFIED":
                view = await browser.verify(principal.company_id, principal.actor_id, session_id)
            if view.status != "VERIFIED":
                return view, 0
            if session_id in finished:
                return view, retry_delay(session_id)
            proof = await browser.proof(principal.company_id, principal.actor_id, session_id)
            root = Path(os.environ["SUPPLIER_SERP_BROWSER_STATE_DIR"])
            profile = profile_directory(root, principal.company_id, engine)
            from procurement.sources.supplier_captcha_recovery import retain_proof

            await asyncio.to_thread(retain_proof, profile, str(session_id), proof.content)
            try:
                delay = await asyncio.to_thread(
                    issue_retry,
                    root,
                    profile,
                    engine,
                    previous.query,
                    str(session_id),
                    proof.pacing_sha256,
                )
            except (ValueError, FileExistsError):
                await finish(session_id, "VERIFIED_NO_RETRY", proof.attempt)
                return view, 0
            retry_at = asyncio.get_running_loop().time() + delay
            try:
                await finish(session_id, "VERIFIED", proof.attempt)
            except Exception:
                (profile / "human-retry.json").unlink(missing_ok=True)
                raise
            ready[session_id] = retry_at
            return view, retry_delay(session_id)

    async def bounded_finalize(session_id: UUID):
        async with asyncio.timeout(45):
            return await verify_and_finalize(session_id)

    @router.post("/start")
    async def start(request: Request, principal: Annotated[Principal, Depends(operator)]):
        payload = await _body(request, StartRequest)
        browser = configured()
        if payload.engine not in ENGINES:
            raise HTTPException(422, "captcha_engine_disabled")
        async with mutation_lock:
            try:
                for existing_id, (owner, previous, selected_engine) in contexts.items():
                    if existing_id in finished:
                        continue
                    active = await browser.status(owner.company_id, owner.actor_id, existing_id)
                    if active.status not in {"STARTING", "WAITING"}:
                        continue
                    if (
                        owner.company_id == principal.company_id
                        and owner.actor_id == principal.actor_id
                        and previous.run_id == str(payload.run_id)
                        and selected_engine == payload.engine
                        and previous.request == payload.request
                    ):
                        latest = await asyncio.to_thread(
                            read_supplier_serp,
                            storage,
                            principal.company_id,
                            payload.request,
                        )
                        if latest.report.run_id != previous.run_id:
                            raise ValueError("CAPTCHA_OBSERVATION_STALE")
                        return reply(active)
                    raise ValueError("CAPTCHA_BUSY")
                report = await asyncio.to_thread(
                    admit_captcha,
                    storage,
                    principal.company_id,
                    principal.actor_id,
                    payload.request,
                    str(payload.run_id),
                    payload.engine,
                )
                view = await browser.start(
                    principal.company_id,
                    principal.actor_id,
                    payload.engine,
                    report.query,
                    payload.run_id,
                )
                contexts[view.session_id] = (principal, report, payload.engine)
                for old_id in tuple(contexts):
                    if len(contexts) <= 16:
                        break
                    if old_id in finished:
                        contexts.pop(old_id)
                        finished.discard(old_id)
                        ready.pop(old_id, None)
                        old_task = finalizers.get(old_id)
                        if old_task is None or old_task.done():
                            finalizers.pop(old_id, None)
                task = asyncio.create_task(monitor(view.session_id))
                monitors.add(task)
                task.add_done_callback(monitors.discard)
                return reply(view)
            except LookupError:
                raise HTTPException(404, "captcha_not_found") from None
            except (ValueError, FileExistsError):
                raise HTTPException(409, "captcha_busy_or_observation_stale") from None
            except RuntimeError:
                raise HTTPException(503, "captcha_unavailable") from None

    @router.post("/{operation}")
    async def operate(
        operation: str, request: Request, principal: Annotated[Principal, Depends(operator)]
    ):
        if operation not in {"status", "frame", "input", "verify", "cancel"}:
            raise HTTPException(404, "captcha_not_found")
        payload = await _body(request, InputRequest if operation == "input" else SessionRequest)
        browser = configured()
        own = contexts.get(payload.session_id)
        if (
            own is None
            or own[0].company_id != principal.company_id
            or own[0].actor_id != principal.actor_id
        ):
            raise HTTPException(404, "captcha_not_found")
        try:
            if operation == "input":
                from procurement.sources.supplier_captcha_browser import (
                    ClickInput,
                    KeyInput,
                    TypeInput,
                    WheelInput,
                )

                classes = {
                    "click": ClickInput,
                    "key": KeyInput,
                    "type": TypeInput,
                    "wheel": WheelInput,
                }
                cls = classes.get(payload.event.get("kind"))
                if cls is None:
                    raise ValueError("CAPTCHA_INPUT_INVALID")
                event = cls.model_validate(payload.event)
                return reply(
                    await browser.input(
                        principal.company_id, principal.actor_id, payload.session_id, event
                    )
                )
            if operation in {"status", "frame"}:
                value = await getattr(browser, operation)(
                    principal.company_id, principal.actor_id, payload.session_id
                )
                return reply(value)
            if operation == "verify":
                task = finalizers.get(payload.session_id)
                if task is None or task.done():
                    task = asyncio.create_task(bounded_finalize(payload.session_id))
                    finalizers[payload.session_id] = task
                    task.add_done_callback(
                        lambda done: None if done.cancelled() else done.exception()
                    )
                view, delay = await asyncio.shield(task)
                return reply(view, delay)
            async with mutation_lock:
                if operation == "cancel":
                    view = await browser.cancel(
                        principal.company_id, principal.actor_id, payload.session_id
                    )
                    await finish(payload.session_id, view.status)
                    return reply(view)
        except (KeyError, LookupError):
            raise HTTPException(404, "captcha_not_found") from None
        except (ValueError, FileExistsError):
            raise HTTPException(409, "captcha_not_ready_or_state_changed") from None
        except RuntimeError:
            raise HTTPException(503, "captcha_unavailable") from None

    async def shutdown():
        await asyncio.gather(*finalizers.values(), return_exceptions=True)
        if manager is not None:
            await manager.shutdown()
            for session_id in contexts:
                if session_id not in finished:
                    await finish(session_id, "CANCELLED")
        for task in tuple(monitors):
            task.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)

    app.router.on_shutdown.append(shutdown)
    app.include_router(router)
