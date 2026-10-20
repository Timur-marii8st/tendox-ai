"""Prepare and download internal RFQ drafts; this router never dispatches anything."""

from collections.abc import Callable
from functools import partial
from typing import Annotated
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from procurement.api.contracts import Principal
from procurement.api.manufacturer_review import body, request_schema
from procurement.domain.manufacturer_rfq import ManufacturerRfqCommand
from procurement.storage.manufacturer_rfq import (
    ManufacturerRfqConflict,
    ManufacturerRfqIneligible,
    ManufacturerRfqNotFound,
    ManufacturerRfqSourceMismatch,
    SavedManufacturerRfqDraft,
    create_manufacturer_rfq_draft,
    read_manufacturer_rfq_draft,
)
from procurement.storage.repository import PostgresStorage


def manufacturer_rfq_router(
    storage: PostgresStorage | None,
    reader: Callable[..., object],
    operator: Callable[..., object],
) -> APIRouter:
    router = APIRouter(prefix="/v1/manufacturer-rfq", tags=["manufacturer-rfq"])

    def configured(response: Response) -> PostgresStorage:
        response.headers["Cache-Control"] = "no-store"
        if storage is None:
            raise HTTPException(
                503, "manufacturer_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        return storage

    async def invoke(call):
        try:
            return await to_thread.run_sync(call)
        except (
            ManufacturerRfqConflict,
            ManufacturerRfqNotFound,
            ManufacturerRfqSourceMismatch,
            ManufacturerRfqIneligible,
            ValueError,
        ) as error:
            status = (
                409
                if isinstance(error, ManufacturerRfqConflict)
                else 404
                if isinstance(error, ManufacturerRfqNotFound)
                else 422
            )
            raise HTTPException(
                status, "manufacturer_rfq_rejected", headers={"Cache-Control": "no-store"}
            ) from error

    @router.post(
        "",
        response_model=SavedManufacturerRfqDraft,
        openapi_extra=request_schema(ManufacturerRfqCommand),
    )
    async def create(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(operator)],
    ) -> object:
        command = await body(request, ManufacturerRfqCommand, limit=64 * 1024)
        store = configured(response)
        return await invoke(
            partial(
                create_manufacturer_rfq_draft,
                store,
                principal.company_id,
                command,
                principal.actor_id,
            )
        )

    @router.get("/{draft_id}", response_model=SavedManufacturerRfqDraft)
    async def read(
        draft_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> object:
        return await invoke(
            partial(
                read_manufacturer_rfq_draft,
                configured(response),
                principal.company_id,
                str(draft_id),
            )
        )

    @router.get("/{draft_id}/text")
    async def download(
        draft_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> Response:
        saved = await invoke(
            partial(
                read_manufacturer_rfq_draft,
                configured(response),
                principal.company_id,
                str(draft_id),
            )
        )
        return Response(
            content=saved.draft.text.encode("utf-8"),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'attachment; filename="manufacturer-rfq-draft.txt"',
                "X-Content-SHA256": saved.draft.text_sha256,
                "X-Manufacturer-Applicability": str(saved.current_status),
            },
        )

    return router
