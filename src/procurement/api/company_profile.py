"""Профиль: строго server-derived tenant, роли и источники; сравнения здесь нет."""

from collections.abc import Callable
from functools import partial
from typing import Annotated, Any
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import ValidationError

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.domain.company_profile_snapshot import (
    CRITICAL_PATHS,
    FIELD_PATHS,
    CompanyProfileSnapshot,
    ProfileSaveCommand,
    ProfileSelection,
    ProfileSelectionCommand,
)
from procurement.storage.company_profile import (
    IdempotencyConflict,
    ProfileConflict,
    ProfileEvidenceInvalid,
    ProfileForbidden,
    ProfileNotFound,
    list_versions,
    read_profile,
    read_selection,
    save_profile,
    select_profile,
)
from procurement.storage.repository import PostgresStorage


def company_profile_router(
    storage: PostgresStorage | None, authenticate: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(prefix="/v1/company-profile", tags=["company-profile"])

    async def reader(
        response: Response, principal: Annotated[Principal, Depends(authenticate)]
    ) -> Principal:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role not in (
            AccessRole.OPERATOR,
            AccessRole.COMPANY_PROFILE_OWNER,
            AccessRole.AUDITOR,
        ):
            raise HTTPException(403, "profile_role_required")
        return principal

    def available() -> PostgresStorage:
        if storage is None:
            raise HTTPException(
                503, "profile_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        return storage

    async def execute(function: Callable[..., Any], *args: Any) -> Any:
        try:
            return await to_thread.run_sync(partial(function, available(), *args))
        except ProfileNotFound as error:
            raise HTTPException(404, str(error)) from error
        except (ProfileConflict, IdempotencyConflict) as error:
            raise HTTPException(409, "profile_version_or_request_conflict") from error
        except ProfileForbidden as error:
            raise HTTPException(403, str(error)) from error
        except ProfileEvidenceInvalid as error:
            raise HTTPException(409, "profile_evidence_invalid") from error
        except ValueError as error:
            fields = ["geography"] if "invalid_profile_group:geography" in str(error) else []
            raise HTTPException(
                422, {"code": "profile_values_invalid", "fields": fields}
            ) from error

    async def command_body(
        request: Request, model: type[ProfileSaveCommand] | type[ProfileSelectionCommand]
    ) -> Any:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, "profile_request_too_large")
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "json_required")
        try:
            return model.model_validate_json(bytes(body))
        except ValidationError as error:
            paths = []
            for item in error.errors():
                message = str(item["msg"])
                if "invalid_profile_field:" in message:
                    path = message.split("invalid_profile_field:", 1)[1]
                    if path in FIELD_PATHS:
                        paths.append(path)
                else:
                    paths.append(".".join(str(part) for part in item["loc"]))
            raise HTTPException(422, {"code": "profile_values_invalid", "fields": paths}) from error

    @router.get("/capabilities")
    async def capabilities(principal: Annotated[Principal, Depends(reader)]) -> dict[str, Any]:
        return {
            "company_id": principal.company_id,
            "actor_id": principal.actor_id,
            "access_role": principal.access_role.value,
            "can_edit": principal.access_role
            in (AccessRole.OPERATOR, AccessRole.COMPANY_PROFILE_OWNER),
            "critical_settings_editable": principal.access_role is AccessRole.COMPANY_PROFILE_OWNER,
            "blocked_fields": sorted(
                {"prohibitions"}
                | (
                    set()
                    if principal.access_role is AccessRole.COMPANY_PROFILE_OWNER
                    else CRITICAL_PATHS
                )
            ),
            "field_paths": FIELD_PATHS,
            "source_kind": "manual_declaration",
        }

    @router.get("", response_model=CompanyProfileSnapshot)
    async def latest(principal: Annotated[Principal, Depends(reader)]) -> CompanyProfileSnapshot:
        return await execute(read_profile, principal.company_id)

    @router.get("/versions")
    async def history(
        principal: Annotated[Principal, Depends(reader)],
        before: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        items = await execute(list_versions, principal.company_id, before)
        return {"items": items, "next_before": items[-1]["version"] if len(items) == 50 else None}

    @router.get("/versions/{version}", response_model=CompanyProfileSnapshot)
    async def exact(
        version: Annotated[int, Path(ge=1)], principal: Annotated[Principal, Depends(reader)]
    ) -> CompanyProfileSnapshot:
        return await execute(read_profile, principal.company_id, version)

    @router.post("/versions", response_model=CompanyProfileSnapshot, status_code=201)
    async def save(
        request: Request,
        principal: Annotated[Principal, Depends(reader)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ) -> CompanyProfileSnapshot:
        command = await command_body(request, ProfileSaveCommand)
        return await execute(
            save_profile,
            principal.company_id,
            principal.actor_id,
            principal.access_role,
            command,
            idempotency_key,
        )

    @router.get("/selection", response_model=ProfileSelection)
    async def selected(principal: Annotated[Principal, Depends(reader)]) -> ProfileSelection:
        return await execute(read_selection, principal.company_id)

    @router.get("/selections/{selection_id}", response_model=ProfileSelection)
    async def selected_exact(
        selection_id: UUID, principal: Annotated[Principal, Depends(reader)]
    ) -> ProfileSelection:
        return await execute(read_selection, principal.company_id, str(selection_id))

    @router.post("/selections", response_model=ProfileSelection, status_code=201)
    async def select(
        request: Request,
        principal: Annotated[Principal, Depends(reader)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ) -> ProfileSelection:
        command = await command_body(request, ProfileSelectionCommand)
        return await execute(
            select_profile,
            principal.company_id,
            principal.actor_id,
            principal.access_role,
            command,
            idempotency_key,
        )

    return router
