"""Границы API и будущего tenant-scoped хранилища.

Протоколы намеренно асинхронны: PostgreSQL-адаптер может выполнять каждую
операцию без блокировки event loop. ``record_evaluation`` — одна транзакционная
граница для результата, audit event и идемпотентности.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from procurement.domain.cases import ProcurementCase
from procurement.domain.decisions import Recommendation


class Principal(BaseModel):
    """Идентичность, полученная только из проверенного bearer credential."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)


class Authenticator(Protocol):
    """Проверяет credential; ``None`` единообразно означает отказ аутентификации."""

    async def authenticate(self, credential: str) -> Principal | None: ...


class CasePage(BaseModel):
    """Одна страница кейсов только одного арендатора."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[ProcurementCase, ...]
    next_cursor: str | None = None


class EvaluationRecord(BaseModel):
    """Долговечный результат вычисления и связанного append-only audit event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str = Field(min_length=1)
    audit_event_id: str = Field(min_length=1)
    recommendation: Recommendation
    engine_version: str = Field(min_length=1)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_at: datetime


class VersionConflict(Exception):
    """Снимок уже существует либо Idempotency-Key использован с другим запросом."""


class InvalidCursor(Exception):
    """Cursor списка не был создан этим сервисом или повреждён."""


class CaseService(Protocol):
    """Tenant-scoped persistence boundary used by the HTTP layer."""

    async def create_case(
        self,
        *,
        company_id: str,
        case: ProcurementCase,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        """Создать immutable snapshot или повторить результат того же запроса.

        ``None`` ниже означает отсутствие в пределах ``company_id``; поэтому
        API одинаково отвечает на несуществующий и чужой идентификатор.
        """

    async def get_case(
        self, *, company_id: str, case_id: str, version: int
    ) -> ProcurementCase | None: ...

    async def list_cases(self, *, company_id: str, cursor: str | None, limit: int) -> CasePage: ...

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
        """Atomically persist evaluation, audit fact, and idempotency state.

        Reusing a key with a distinct ``request_digest`` raises
        :class:`VersionConflict`.
        """
