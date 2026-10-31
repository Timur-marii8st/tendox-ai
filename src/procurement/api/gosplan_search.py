"""Authenticated, bounded access to Gosplan search with a shared host quota."""

import os
import sqlite3
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.sources.gosplan_search import Detail, GosplanSearchError, SearchPage
from procurement.sources.gosplan_search import read_detail as fetch_detail
from procurement.sources.gosplan_search import search_page as fetch_search


def _secret(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("SECRET_PERMISSIONS_INVALID")
        raw = stream.read(1025)
    key = raw.decode("ascii").strip()
    if not key or len(raw) > 1024 or any(c.isspace() for c in key):
        raise ValueError("SECRET_INVALID")
    return key


def _reserve(path: Path, company: str, now: datetime) -> None:
    """Serialize all process/tenant reservations; fail closed if state is unavailable."""
    if not company.strip() or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("QUOTA_SCOPE_INVALID")
    parent = path.parent
    info = parent.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("QUOTA_DIRECTORY_INVALID")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        file_info = os.fstat(fd)
        if (
            not stat.S_ISREG(file_info.st_mode)
            or file_info.st_uid != os.geteuid()
            or file_info.st_mode & 0o077
        ):
            raise ValueError("QUOTA_FILE_INVALID")
    finally:
        os.close(fd)
    with sqlite3.connect(path, timeout=2, isolation_level=None) as db:
        db.execute("PRAGMA busy_timeout=2000")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations (company TEXT NOT NULL, at REAL NOT NULL)"
            )
            stamp = now.timestamp()
            if db.execute(
                "SELECT 1 FROM reservations WHERE at > ? LIMIT 1", (stamp + 1,)
            ).fetchone():
                raise ValueError("QUOTA_CLOCK_INVALID")
            db.execute("DELETE FROM reservations WHERE at <= ?", (stamp - 3600,))
            all_count, tenant_count, burst = db.execute(
                "SELECT count(*), sum(company = ?), sum(at > ?) FROM reservations",
                (company, stamp - 1),
            ).fetchone()
            if all_count >= 600 or (tenant_count or 0) >= 120 or (burst or 0) >= 2:
                raise ValueError("RATE_LIMITED")
            db.execute("INSERT INTO reservations (company, at) VALUES (?, ?)", (company, stamp))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def _run(
    company: str, law: Literal["44", "223"], query: str | None, number: str | None, offset: int
) -> SearchPage | Detail:
    secret = os.environ.get("GOSPLAN_SEARCH_KEY_FILE")
    quota = os.environ.get("GOSPLAN_SEARCH_QUOTA_FILE")
    if not secret or not quota:
        raise ValueError("CONFIG_UNAVAILABLE")
    key = _secret(Path(secret))
    now = datetime.now(UTC)
    _reserve(Path(quota), company, now)
    with httpx.Client(timeout=25, trust_env=True) as client:
        if number is not None:
            return fetch_detail(client, key, law, number, now=now)
        assert query is not None
        return fetch_search(client, key, law, query=query, offset=offset, now=now)


def gosplan_search_router(authenticate: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/tender-discovery/gosplan")

    async def execute(
        principal: Principal,
        law: Literal["44", "223"],
        query: str | None,
        number: str | None,
        offset: int,
    ) -> SearchPage | Detail:
        if principal.access_role not in (AccessRole.OPERATOR, AccessRole.AUDITOR):
            raise HTTPException(
                403, "operator_or_auditor_required", headers={"Cache-Control": "no-store"}
            )
        try:
            return await to_thread.run_sync(
                partial(_run, principal.company_id, law, query, number, offset)
            )
        except GosplanSearchError as error:
            status = {"HTTP_429": 429, "HTTP_404": 404}.get(str(error), 503)
            reason = "gosplan_not_found" if status == 404 else "gosplan_source_unavailable"
            raise HTTPException(status, reason, headers={"Cache-Control": "no-store"}) from error
        except (OSError, UnicodeError, sqlite3.Error, ValueError) as error:
            status = 429 if str(error) == "RATE_LIMITED" else 503
            raise HTTPException(
                status, "gosplan_temporarily_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @router.get("/search", response_model=SearchPage)
    async def search(
        response: Response,
        principal: Annotated[Principal, Depends(authenticate)],
        law: Literal["44", "223"],
        query: Annotated[str, Query(min_length=1, max_length=120, pattern=r"\S")],
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> SearchPage:
        response.headers["Cache-Control"] = "no-store"
        return await execute(principal, law, query, None, offset)

    @router.get("/detail/{law}/{number}", response_model=Detail)
    async def detail(
        response: Response,
        principal: Annotated[Principal, Depends(authenticate)],
        law: Literal["44", "223"],
        number: str,
    ) -> Detail:
        response.headers["Cache-Control"] = "no-store"
        return await execute(principal, law, None, number, 0)

    return router
