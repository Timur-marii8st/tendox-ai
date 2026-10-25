"""Read-only source-bound price basis, authenticated company from the server."""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any, Literal

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.sources.tender_navigation import TenderNavigation
from procurement.storage.eis_global_price import (
    GlobalPriceOptions,
    GlobalPriceResult,
    search_global_price,
)
from procurement.storage.eis_mixed_comparison import MixedNoticeRef
from procurement.storage.eis_search_pagination import SearchPageError
from procurement.storage.repository import PostgresStorage
from procurement.storage.tender_navigation import read_navigation


class NavigationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: MixedNoticeRef


def tender_navigation_router(
    storage: PostgresStorage | None, authenticate: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(prefix="/v1/tender-discovery")

    @router.get("/global-price", response_model=GlobalPriceResult)
    async def global_price(
        response: Response,
        principal: Annotated[Principal, Depends(authenticate)],
        query: Annotated[str, Query(min_length=1, max_length=120, pattern=r"\S")],
        law: Literal["all", "44", "223"] = "all",
        delivery_region: Annotated[str, Query(max_length=200)] = "",
        include_unknown_region: bool = False,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> GlobalPriceResult:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role not in (AccessRole.OPERATOR, AccessRole.AUDITOR):
            raise HTTPException(
                403, "operator_or_auditor_required", headers={"Cache-Control": "no-store"}
            )
        if storage is None:
            raise HTTPException(
                503, "navigation_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        options = GlobalPriceOptions(
            query=query.strip(),
            law=law,
            delivery_region=delivery_region.strip(),
            include_unknown_region=include_unknown_region,
        )
        try:
            return await to_thread.run_sync(
                partial(
                    search_global_price,
                    storage,
                    principal.company_id,
                    options,
                    now=datetime.now(UTC),
                    cursor=cursor,
                    limit=page_size,
                )
            )
        except SearchPageError as error:
            code = str(error)
            raise HTTPException(
                {"SEARCH_PAGE_CHANGED": 409, "SEARCH_PAGE_EXPIRED": 410}.get(code, 422),
                code,
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            raise HTTPException(
                422, "global_price_request_invalid", headers={"Cache-Control": "no-store"}
            ) from error

    @router.post("/eis-navigation/read", response_model=TenderNavigation)
    async def read(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(authenticate)],
    ) -> TenderNavigation:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role not in (AccessRole.OPERATOR, AccessRole.AUDITOR):
            raise HTTPException(
                403, "operator_or_auditor_required", headers={"Cache-Control": "no-store"}
            )
        if storage is None:
            raise HTTPException(
                503, "navigation_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "json_required", headers={"Cache-Control": "no-store"})
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 4096:
                raise HTTPException(
                    413, "navigation_request_limit", headers={"Cache-Control": "no-store"}
                )
            raw.extend(chunk)
        try:
            payload = NavigationRead.model_validate_json(bytes(raw))
        except ValidationError as error:
            raise HTTPException(
                422, "navigation_request_invalid", headers={"Cache-Control": "no-store"}
            ) from error
        try:
            return await to_thread.run_sync(
                partial(read_navigation, storage, principal.company_id, payload.request)
            )
        except LookupError as error:
            raise HTTPException(
                404, "navigation_source_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            raise HTTPException(
                409,
                "navigation_source_changed_or_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    return router
