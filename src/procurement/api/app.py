"""FastAPI factory with authentication and tenant isolation at the boundary."""

import hashlib
import re
from datetime import datetime
from typing import Annotated, Self

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.api.contracts import (
    Authenticator,
    CasePage,
    CaseService,
    EvaluationRecord,
    InvalidCursor,
    Principal,
    VersionConflict,
)
from procurement.domain.cases import ProcurementCase, case_input_digest, evaluate_case

ENGINE_VERSION = "s1"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str


class EvaluationRequest(BaseModel):
    """Only the server evaluates the already persisted immutable case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effective_at: datetime

    @model_validator(mode="after")
    def _effective_at_is_aware(self) -> Self:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must include a timezone")
        return self


async def _idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key")],
) -> str:
    if _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="validation_error",
        )
    return value


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _request_digest(*parts: str) -> str:
    """Stable digest used only to bind an Idempotency-Key to one request."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_app(service: CaseService, authenticator: Authenticator) -> FastAPI:
    """Create an app without database globals or caller-selected tenant identity."""

    app = FastAPI(title="Syurai Procurement API", version="0.1.0", debug=False)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def internal_error(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal_error"},
        )

    async def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Principal:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not credentials.credentials
        ):
            raise _invalid_credentials()
        try:
            principal = await authenticator.authenticate(credentials.credentials)
        except Exception:
            principal = None
        if principal is None:
            raise _invalid_credentials()
        return principal

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/v1/cases", status_code=status.HTTP_201_CREATED, response_model=ProcurementCase)
    async def create_case(
        case: ProcurementCase,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ProcurementCase:
        if case.company_id != principal.company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_mismatch")
        try:
            saved = await service.create_case(
                company_id=principal.company_id,
                case=case,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(case.model_dump_json()),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error
        if saved.company_id != principal.company_id:
            raise RuntimeError("storage returned a case for a different tenant")
        return saved

    @app.get("/v1/cases/{case_id}/versions/{version}", response_model=ProcurementCase)
    async def get_case(
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ProcurementCase:
        case = await service.get_case(
            company_id=principal.company_id,
            case_id=case_id,
            version=version,
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        return case

    @app.get("/v1/cases", response_model=CasePage)
    async def list_cases(
        principal: Annotated[Principal, Depends(current_principal)],
        cursor: Annotated[str | None, Query(max_length=200)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> CasePage:
        try:
            page = await service.list_cases(
                company_id=principal.company_id,
                cursor=cursor,
                limit=limit,
            )
        except InvalidCursor as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="validation_error",
            ) from error
        if any(case.company_id != principal.company_id for case in page.items):
            raise RuntimeError("storage returned a case for a different tenant")
        return page

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/evaluations",
        status_code=status.HTTP_201_CREATED,
        response_model=EvaluationRecord,
    )
    async def evaluate(
        request: EvaluationRequest,
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> EvaluationRecord:
        case = await service.get_case(
            company_id=principal.company_id,
            case_id=case_id,
            version=version,
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        recommendation = evaluate_case(case, at=request.effective_at)
        try:
            return await service.record_evaluation(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                case_id=case.case_id,
                version=case.version,
                effective_at=request.effective_at,
                recommendation=recommendation,
                engine_version=ENGINE_VERSION,
                input_digest=case_input_digest(case),
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    case.case_id,
                    str(case.version),
                    request.effective_at.isoformat(),
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    return app
