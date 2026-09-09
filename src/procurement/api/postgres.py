"""PostgreSQL adapters for the asynchronous HTTP contracts."""

from __future__ import annotations

from datetime import datetime
from functools import partial

from anyio import to_thread

from procurement.api.contracts import (
    CasePage,
    EvaluationRecord,
    InvalidCursor,
    Principal,
    VersionConflict,
)
from procurement.domain.cases import ProcurementCase
from procurement.domain.decisions import Recommendation
from procurement.storage import (
    CaseVersionConflict,
    IdempotencyConflict,
    PostgresStorage,
)


class PostgresAuthenticator:
    """Resolve a bearer secret without accepting a caller-selected tenant."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    async def authenticate(self, credential: str) -> Principal | None:
        stored = await to_thread.run_sync(self._storage.authenticate_api_key, credential)
        if stored is None:
            return None
        return Principal(company_id=stored.company_id, actor_id=stored.actor_id)


class PostgresCaseService:
    """Keep blocking SQLAlchemy work outside the FastAPI event loop."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    async def create_case(
        self,
        *,
        company_id: str,
        case: ProcurementCase,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        operation = partial(
            self._storage.save_case,
            company_id,
            case,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (CaseVersionConflict, IdempotencyConflict) as error:
            raise VersionConflict from error

    async def get_case(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> ProcurementCase | None:
        return await to_thread.run_sync(
            partial(self._storage.get_case, company_id, case_id, version)
        )

    async def list_cases(
        self,
        *,
        company_id: str,
        cursor: str | None,
        limit: int,
    ) -> CasePage:
        try:
            stored = await to_thread.run_sync(
                partial(self._storage.list_cases, company_id, cursor=cursor, limit=limit)
            )
        except ValueError as error:
            raise InvalidCursor from error
        return CasePage(items=stored.items, next_cursor=stored.next_cursor)

    async def get_latest_evaluation(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> EvaluationRecord | None:
        stored = await to_thread.run_sync(
            partial(
                self._storage.get_latest_evaluation,
                company_id,
                case_id,
                version,
            )
        )
        if stored is None:
            return None
        return EvaluationRecord(
            evaluation_id=stored.evaluation_id,
            audit_event_id=stored.evaluation_id,
            recommendation=stored.recommendation,
            engine_version=stored.engine_version,
            input_digest=stored.input_sha256,
            effective_at=stored.effective_at,
        )

    async def record_evaluation(
        self,
        *,
        company_id: str,
        actor_id: str,
        case_id: str,
        version: int,
        effective_at: datetime,
        recommendation: Recommendation,
        engine_version: str,
        input_digest: str,
        idempotency_key: str,
        request_digest: str,
    ) -> EvaluationRecord:
        operation = partial(
            self._storage.record_evaluation,
            company_id,
            actor_id,
            case_id,
            version,
            effective_at,
            input_digest,
            engine_version,
            recommendation,
            idempotency_key,
            request_digest,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except IdempotencyConflict as error:
            raise VersionConflict from error
        return EvaluationRecord(
            evaluation_id=stored.evaluation_id,
            audit_event_id=stored.evaluation_id,
            recommendation=stored.recommendation,
            engine_version=stored.engine_version,
            input_digest=stored.input_sha256,
            effective_at=stored.effective_at,
        )
