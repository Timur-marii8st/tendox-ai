"""Personal operator beta declarations and cached financial comparison."""

from collections.abc import Callable
from functools import partial
from typing import Annotated, Any

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ValidationError

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.storage.beta_quote import (
    BetaQuoteCommand,
    BetaQuoteRef,
    BetaQuoteReport,
    quote_report,
)
from procurement.storage.beta_shortlist import BetaShortlist, BetaShortlistRequest, shortlist
from procurement.storage.repository import PostgresStorage


def beta_procurement_router(
    storage: PostgresStorage | None, authenticate: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(prefix="/v1/beta-procurement", tags=["beta-procurement"])

    async def reader(
        response: Response, principal: Annotated[Principal, Depends(authenticate)]
    ) -> Principal:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role not in (AccessRole.OPERATOR, AccessRole.AUDITOR):
            raise HTTPException(403, "operator_required", headers={"Cache-Control": "no-store"})
        return principal

    async def execute(
        request: Request,
        model: type[BaseModel],
        function: Callable[..., Any],
        principal: Principal,
        *,
        save: bool = False,
    ) -> Any:
        headers = {"Cache-Control": "no-store"}
        if storage is None:
            raise HTTPException(503, "beta_storage_unavailable", headers=headers)
        if save and principal.access_role != AccessRole.OPERATOR:
            raise HTTPException(403, "auditor_read_only", headers=headers)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "json_required", headers=headers)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 32768:
                raise HTTPException(413, "beta_payload_limit", headers=headers)
            body.extend(chunk)
        try:
            payload = model.model_validate_json(bytes(body))
        except ValidationError as error:
            raise HTTPException(422, "beta_input_invalid", headers=headers) from error
        try:
            kwargs = {"actor": principal.actor_id}
            ref = payload
            if save:
                ref = BetaQuoteRef.model_validate(
                    payload.model_dump(include={"notice", "lot_index"})
                )
                kwargs["command"] = payload
            return await to_thread.run_sync(
                partial(function, storage, principal.company_id, ref, **kwargs)
            )
        except LookupError as error:
            raise HTTPException(404, "beta_source_not_found", headers=headers) from error
        except ValueError as error:
            raise HTTPException(409, "beta_source_or_input_conflict", headers=headers) from error

    @router.post("/quote/read", response_model=BetaQuoteReport)
    async def read(request: Request, principal: Annotated[Principal, Depends(reader)]) -> Any:
        return await execute(request, BetaQuoteRef, quote_report, principal)

    @router.post("/quote/save", response_model=BetaQuoteReport)
    async def save(request: Request, principal: Annotated[Principal, Depends(reader)]) -> Any:
        return await execute(request, BetaQuoteCommand, quote_report, principal, save=True)

    @router.post("/shortlist", response_model=BetaShortlist)
    async def compare(request: Request, principal: Annotated[Principal, Depends(reader)]) -> Any:
        return await execute(request, BetaShortlistRequest, shortlist, principal)

    return router
