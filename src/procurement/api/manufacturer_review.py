"""Evidence uploads and independent, scoped manufacturer identity review."""

import json
from collections.abc import Callable
from functools import partial
from typing import Annotated, TypeVar
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, Base64Bytes, BaseModel, ConfigDict, Field, StrictBool

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.api.manufacturer_search import unique_object
from procurement.domain.manufacturer_review import (
    LegalIdentity,
    ManufacturerCitation,
    ReviewStatus,
)
from procurement.storage.manufacturer_review import (
    ManufacturerEvidenceArtifact,
    ManufacturerProposalSummary,
    ManufacturerReviewConflict,
    ManufacturerReviewIndependenceViolation,
    ManufacturerReviewNotFound,
    ManufacturerReviewSourceMismatch,
    SavedManufacturerDecision,
    SavedManufacturerProposal,
    decide_manufacturer_review,
    list_manufacturer_proposals,
    prepare_manufacturer_review,
    read_manufacturer_decision,
    read_manufacturer_proposal,
    read_proposal_artifact,
    store_evidence_artifact,
)
from procurement.storage.repository import PostgresStorage

Body = TypeVar("Body", bound=BaseModel)


def request_schema(model: type[BaseModel]) -> dict[str, object]:
    """Document the same bounded command that the streaming parser validates."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


class ArtifactCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    source_title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=2048)
    original_filename: str = Field(min_length=1, max_length=255)
    content_base64: Base64Bytes


class ProposalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    run_id: UUID
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    claimed_identity: LegalIdentity
    citations: tuple[ManufacturerCitation, ...] = Field(min_length=1, max_length=3)


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    identity_status: ReviewStatus
    role_status: ReviewStatus
    official_origin_confirmed: StrictBool
    identity_fields_confirmed: StrictBool
    exact_product_link_confirmed: StrictBool
    effective_until: AwareDatetime | None
    rationale: str = Field(min_length=1, max_length=2000)
    citation_indexes: tuple[Annotated[int, Field(strict=True, ge=0, le=2)], ...] = Field(
        min_length=1, max_length=3
    )


async def body(request: Request, model: type[Body], limit: int = 16384) -> Body:
    headers = {"Cache-Control": "no-store"}
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "manufacturer_json_required", headers=headers)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            raise HTTPException(413, "manufacturer_body_too_large", headers=headers)
        content.extend(chunk)
    try:
        return model.model_validate(json.loads(bytes(content), object_pairs_hook=unique_object))
    except ValueError as error:
        raise HTTPException(422, "invalid_manufacturer_review", headers=headers) from error


def manufacturer_review_router(
    storage: PostgresStorage | None,
    reader: Callable[..., object],
    operator: Callable[..., object],
) -> APIRouter:
    router = APIRouter(prefix="/v1/manufacturer-review", tags=["manufacturer-review"])

    def configured(response: Response) -> PostgresStorage:
        response.headers["Cache-Control"] = "no-store"
        if storage is None:
            raise HTTPException(
                503, "manufacturer_storage_unavailable", headers={"Cache-Control": "no-store"}
            )
        return storage

    async def reviewer(principal: Annotated[Principal, Depends(reader)]) -> Principal:
        if principal.access_role is not AccessRole.MANUFACTURER_REVIEWER:
            raise HTTPException(
                403, "manufacturer_reviewer_role_required", headers={"Cache-Control": "no-store"}
            )
        return principal

    async def invoke(call: Callable[[], object]) -> object:
        try:
            return await to_thread.run_sync(call)
        except (
            ManufacturerReviewConflict,
            ManufacturerReviewIndependenceViolation,
            ManufacturerReviewNotFound,
            ManufacturerReviewSourceMismatch,
            ValueError,
        ) as error:
            status = (
                409
                if isinstance(error, ManufacturerReviewConflict)
                else 403
                if isinstance(error, ManufacturerReviewIndependenceViolation)
                else 404
                if isinstance(error, ManufacturerReviewNotFound)
                else 422
            )
            raise HTTPException(
                status, "manufacturer_review_rejected", headers={"Cache-Control": "no-store"}
            ) from error

    @router.post(
        "/artifacts",
        response_model=ManufacturerEvidenceArtifact,
        openapi_extra=request_schema(ArtifactCommand),
    )
    async def upload(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(operator)],
    ) -> object:
        payload = await body(request, ArtifactCommand, limit=3 * 1024 * 1024)
        store = configured(response)
        return await invoke(
            partial(
                store_evidence_artifact,
                store,
                principal.company_id,
                bytes(payload.content_base64),
                source_title=payload.source_title,
                source_url=payload.source_url,
                original_filename=payload.original_filename,
                actor_id=principal.actor_id,
                command_id=str(payload.command_id),
            )
        )

    @router.post(
        "/proposals",
        response_model=SavedManufacturerProposal,
        openapi_extra=request_schema(ProposalCommand),
    )
    async def propose(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(operator)],
    ) -> object:
        payload = await body(request, ProposalCommand)
        store = configured(response)
        return await invoke(
            partial(
                prepare_manufacturer_review,
                store,
                principal.company_id,
                str(payload.run_id),
                payload.record_id,
                claimed_identity=payload.claimed_identity,
                citations=payload.citations,
                actor_id=principal.actor_id,
                command_id=str(payload.command_id),
            )
        )

    @router.get("/proposals", response_model=list[ManufacturerProposalSummary])
    async def listing(
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> object:
        store = configured(response)
        return await invoke(partial(list_manufacturer_proposals, store, principal.company_id))

    @router.get("/proposals/{proposal_id}", response_model=SavedManufacturerProposal)
    async def read(
        proposal_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> object:
        store = configured(response)
        return await invoke(
            partial(
                read_manufacturer_proposal,
                store,
                principal.company_id,
                str(proposal_id),
            )
        )

    @router.post(
        "/proposals/{proposal_id}/decision",
        response_model=SavedManufacturerDecision,
        openapi_extra=request_schema(DecisionCommand),
    )
    async def decide(
        proposal_id: UUID,
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(reviewer)],
    ) -> object:
        payload = await body(request, DecisionCommand)
        store = configured(response)
        return await invoke(
            partial(
                decide_manufacturer_review,
                store,
                principal.company_id,
                str(proposal_id),
                **payload.model_dump(exclude={"command_id"}),
                reviewer_id=principal.actor_id,
                command_id=str(payload.command_id),
            )
        )

    @router.get("/proposals/{proposal_id}/decision", response_model=SavedManufacturerDecision)
    async def decision(
        proposal_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reader)],
    ) -> object:
        store = configured(response)
        return await invoke(
            partial(
                read_manufacturer_decision,
                store,
                principal.company_id,
                str(proposal_id),
            )
        )

    @router.get(
        "/proposals/{proposal_id}/artifacts/{artifact_id}/metadata",
        response_model=ManufacturerEvidenceArtifact,
    )
    async def artifact_metadata(
        proposal_id: UUID,
        artifact_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reviewer)],
    ) -> object:
        store = configured(response)
        result = await invoke(
            partial(
                read_proposal_artifact,
                store,
                principal.company_id,
                str(proposal_id),
                str(artifact_id),
            )
        )
        return result.metadata

    @router.get("/proposals/{proposal_id}/artifacts/{artifact_id}")
    async def artifact(
        proposal_id: UUID,
        artifact_id: UUID,
        response: Response,
        principal: Annotated[Principal, Depends(reviewer)],
    ) -> object:
        store = configured(response)
        result = await invoke(
            partial(
                read_proposal_artifact,
                store,
                principal.company_id,
                str(proposal_id),
                str(artifact_id),
            )
        )
        return Response(
            content=result.content,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'attachment; filename="manufacturer-evidence.pdf"',
                "X-Content-SHA256": result.metadata.sha256,
            },
        )

    return router
