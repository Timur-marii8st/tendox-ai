"""Read-only, exact-identity grouping of a saved search's reviewed records."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Response

from procurement.api.contracts import Principal
from procurement.domain.manufacturer_directory import ManufacturerDirectory
from procurement.storage.manufacturer_directory import build_manufacturer_directory
from procurement.storage.manufacturer_review import ManufacturerReviewNotFound
from procurement.storage.manufacturer_search import ManufacturerSearchNotFound
from procurement.storage.repository import PostgresStorage


def manufacturer_directory_router(
    storage: PostgresStorage | None, reader: Callable[..., object]
) -> APIRouter:
    router = APIRouter(prefix="/v1/manufacturer-directory", tags=["manufacturer-directory"])

    @router.get("/{run_id}", response_model=ManufacturerDirectory)
    async def directory(
        run_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> ManufacturerDirectory:
        response.headers["Cache-Control"] = "no-store"
        headers = {"Cache-Control": "no-store"}
        if storage is None:
            raise HTTPException(503, "manufacturer_storage_unavailable", headers=headers)
        try:
            return await to_thread.run_sync(
                build_manufacturer_directory, storage, principal.company_id, str(run_id)
            )
        except (ManufacturerSearchNotFound, ManufacturerReviewNotFound) as error:
            raise HTTPException(404, "manufacturer_evidence_not_found", headers=headers) from error
        except ValueError as error:
            raise HTTPException(422, "manufacturer_directory_rejected", headers=headers) from error

    return router
