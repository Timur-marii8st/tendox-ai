"""Контроль договора и исполнения после победы."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Provenance


class MilestoneKind(str, Enum):
    CONTRACT_SIGNING = "contract_signing"
    SECURITY = "security"
    PRODUCTION = "production"
    DELIVERY = "delivery"
    ACCEPTANCE_DOCUMENTS = "acceptance_documents"
    PAYMENT = "payment"
    WARRANTY_END = "warranty_end"


class MilestoneStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    UNKNOWN = "unknown"


class ContractMilestone(BaseModel):
    """Контрольная дата с доказательством и ответственным."""

    model_config = ConfigDict(frozen=True)

    milestone_id: str = Field(min_length=1)
    kind: MilestoneKind
    due_date: date
    status: MilestoneStatus
    owner: str = Field(min_length=1)
    provenance: Provenance
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def _completion_is_consistent(self) -> ContractMilestone:
        if self.status is MilestoneStatus.COMPLETED and self.completed_at is None:
            raise ValueError("выполненный этап требует времени завершения")
        if self.status is not MilestoneStatus.COMPLETED and self.completed_at is not None:
            raise ValueError("время завершения допустимо только для выполненного этапа")
        return self


class ContractCase(BaseModel):
    """Один выигранный контракт и полный план исполнения."""

    model_config = ConfigDict(frozen=True)

    contract_id: str = Field(min_length=1)
    tender_id: str = Field(min_length=1)
    supplier_contract_ids: tuple[str, ...] = ()
    milestones: tuple[ContractMilestone, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _milestone_ids_are_unique(self) -> ContractCase:
        ids = [item.milestone_id for item in self.milestones]
        if len(ids) != len(set(ids)):
            raise ValueError("идентификаторы этапов должны быть уникальны")
        return self

    def due_within(self, today: date, days: int) -> tuple[ContractMilestone, ...]:
        """Этапы для предупреждений, включая уже просроченные незавершённые."""
        if days < 0:
            raise ValueError("горизонт предупреждения не может быть отрицательным")
        return tuple(
            item
            for item in self.milestones
            if item.status is not MilestoneStatus.COMPLETED and (item.due_date - today).days <= days
        )
