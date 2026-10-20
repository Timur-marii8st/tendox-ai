"""Authenticated saved registry searches; callers never supply source facts."""

import json
from collections.abc import Callable
from functools import partial
from typing import Annotated
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from procurement.api.contracts import Principal
from procurement.storage.manufacturer_search import (
    ManufacturerCandidateDossier,
    ManufacturerSearchConflict,
    ManufacturerSearchNotFound,
    ManufacturerSearchRateLimited,
    ManufacturerSearchSummary,
    SavedManufacturerSearch,
    list_saved_searches,
    read_candidate,
    read_search,
    start_search,
)
from procurement.storage.repository import PostgresStorage


class SearchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID
    query: str = Field(min_length=1, max_length=80)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


async def read_command(request: Request) -> SearchCommand:
    """Reject oversized or ambiguous commands before loading source or storage."""
    headers = {"Cache-Control": "no-store"}
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "manufacturer_json_required", headers=headers)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 4096:
            raise HTTPException(413, "manufacturer_command_too_large", headers=headers)
        body.extend(chunk)
    try:
        payload = json.loads(bytes(body), object_pairs_hook=unique_object)
        return SearchCommand.model_validate(payload)
    except (ValueError, ValidationError) as error:
        raise HTTPException(422, "invalid_manufacturer_search", headers=headers) from error


def manufacturer_search_router(
    storage: PostgresStorage | None,
    reader: Callable[..., object],
    operator: Callable[..., object],
) -> APIRouter:
    """Bind the existing tenant authentication and role checks to this workflow."""
    router = APIRouter(prefix="/v1/manufacturer-search", tags=["manufacturer-search"])

    def configured(response: Response) -> PostgresStorage:
        response.headers["Cache-Control"] = "no-store"
        if storage is None:
            raise HTTPException(
                503, "manufacturer_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        return storage

    def translate(error: Exception) -> HTTPException:
        headers = {"Cache-Control": "no-store"}
        if isinstance(error, ManufacturerSearchConflict):
            return HTTPException(409, "manufacturer_command_conflict", headers=headers)
        if isinstance(error, ManufacturerSearchRateLimited):
            return HTTPException(429, "manufacturer_search_rate_limited", headers=headers)
        if isinstance(error, ManufacturerSearchNotFound):
            return HTTPException(404, "manufacturer_evidence_not_found", headers=headers)
        return HTTPException(422, "invalid_manufacturer_search", headers=headers)

    @router.post(
        "",
        response_model=SavedManufacturerSearch,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": SearchCommand.model_json_schema()}},
            }
        },
    )
    async def create(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(operator)],
    ) -> SavedManufacturerSearch:
        payload = await read_command(request)
        store = configured(response)
        try:
            return await to_thread.run_sync(
                partial(
                    start_search,
                    store,
                    principal.company_id,
                    payload.query,
                    actor_id=principal.actor_id,
                    command_id=str(payload.command_id),
                )
            )
        except (
            ManufacturerSearchConflict,
            ManufacturerSearchRateLimited,
            ManufacturerSearchNotFound,
            ValueError,
        ) as error:
            raise translate(error) from error

    @router.get("", response_model=list[ManufacturerSearchSummary])
    async def listing(
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> list[ManufacturerSearchSummary]:
        store = configured(response)
        return list(await to_thread.run_sync(list_saved_searches, store, principal.company_id))

    @router.get("/{run_id}", response_model=SavedManufacturerSearch)
    async def read(
        run_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> SavedManufacturerSearch:
        store = configured(response)
        try:
            return await to_thread.run_sync(read_search, store, principal.company_id, str(run_id))
        except (ManufacturerSearchNotFound, ValueError) as error:
            raise translate(error) from error

    @router.get("/{run_id}/candidates/{record_id}", response_model=ManufacturerCandidateDossier)
    async def candidate(
        run_id: UUID,
        record_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")],
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> ManufacturerCandidateDossier:
        store = configured(response)
        try:
            return await to_thread.run_sync(
                read_candidate,
                store,
                principal.company_id,
                str(run_id),
                record_id,
            )
        except (ManufacturerSearchNotFound, ValueError) as error:
            raise translate(error) from error

    return router
