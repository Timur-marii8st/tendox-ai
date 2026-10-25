"""Read-only source-bound price basis, authenticated company from the server."""

from collections.abc import Callable
from functools import partial
from typing import Annotated, Any

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, ValidationError

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.sources.eis_supplier_product import SupplierProductRequest
from procurement.storage.public_unit_price import PublicUnitPriceReport, read_public_unit_price
from procurement.storage.repository import PostgresStorage


class PublicPriceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: SupplierProductRequest


def public_unit_price_router(
    storage: PostgresStorage | None, authenticate: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(prefix="/v1/tender-discovery")

    @router.post("/eis-public-unit-price/read", response_model=PublicUnitPriceReport)
    async def read(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(authenticate)],
    ) -> PublicUnitPriceReport:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role not in (AccessRole.OPERATOR, AccessRole.AUDITOR):
            raise HTTPException(
                403, "operator_or_auditor_required", headers={"Cache-Control": "no-store"}
            )
        if storage is None:
            raise HTTPException(
                503, "public_price_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "json_required", headers={"Cache-Control": "no-store"})
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 4096:
                raise HTTPException(
                    413, "public_price_request_limit", headers={"Cache-Control": "no-store"}
                )
            raw.extend(chunk)
        try:
            payload = PublicPriceRead.model_validate_json(bytes(raw))
        except ValidationError as error:
            raise HTTPException(
                422, "public_price_request_invalid", headers={"Cache-Control": "no-store"}
            ) from error
        try:
            return await to_thread.run_sync(
                partial(read_public_unit_price, storage, principal.company_id, payload.request)
            )
        except LookupError as error:
            raise HTTPException(
                404, "public_price_source_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            raise HTTPException(
                409,
                "public_price_source_changed_or_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    return router
