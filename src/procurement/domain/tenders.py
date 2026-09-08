"""Факты о процедуре, сроке подачи и географии исполнения."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Provenance


class ProcurementLaw(str, Enum):
    FZ_44 = "44-fz"
    FZ_223 = "223-fz"
    COMMERCIAL = "commercial"


class ProcedureMethod(str, Enum):
    ELECTRONIC_AUCTION = "electronic_auction"
    ELECTRONIC_COMPETITION = "electronic_competition"
    QUOTATION_REQUEST = "quotation_request"
    PROPOSAL_REQUEST = "proposal_request"
    SINGLE_SUPPLIER = "single_supplier"
    ELECTRONIC_STORE = "electronic_store"
    OTHER_COMPETITIVE_223 = "other_competitive_223"
    NON_COMPETITIVE_223 = "non_competitive_223"
    CLOSED = "closed"


class ProcedureStage(str, Enum):
    PUBLISHED = "published"
    SUBMISSION_OPEN = "submission_open"
    SUBMISSION_CLOSING = "submission_closing"
    SUBMISSION_CLOSED = "submission_closed"
    REVIEW = "review"
    BIDDING = "bidding"
    WINNER_SELECTION = "winner_selection"
    CONTRACT = "contract"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SubmissionWindow(BaseModel):
    """Окончание подачи всегда хранится с часовым поясом и источником."""

    model_config = ConfigDict(frozen=True)

    closes_at: datetime
    timezone: str = Field(min_length=1)
    provenance: Provenance

    @model_validator(mode="after")
    def _timezone_is_explicit_and_consistent(self) -> SubmissionWindow:
        if self.closes_at.tzinfo is None or self.closes_at.utcoffset() is None:
            raise ValueError("срок подачи должен содержать UTC offset")
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("неизвестный часовой пояс") from exc
        expected = self.closes_at.astimezone(zone).utcoffset()
        if expected != self.closes_at.utcoffset():
            raise ValueError("timezone не соответствует offset срока подачи")
        return self

    def is_open_at(self, moment: datetime) -> bool:
        """Истёкшая процедура никогда не попадает в рекомендации."""
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("момент проверки должен содержать часовой пояс")
        return moment < self.closes_at

    def seconds_left(self, moment: datetime) -> int:
        if not self.is_open_at(moment):
            return 0
        return int((self.closes_at - moment).total_seconds())


class DeliveryAddress(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: str = Field(min_length=1)
    city: str = Field(min_length=1)
    address: str = Field(min_length=1)
    unloading_required: bool = False
    lifting_required: bool = False
    installation_required: bool = False
    packaging_removal_required: bool = False
    provenance: Provenance


class DeliveryTopology(str, Enum):
    SINGLE_CITY = "single_city"
    MULTI_CITY_ONE_REGION = "multi_city_one_region"
    MULTI_REGION = "multi_region"


class DeliveryPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    addresses: tuple[DeliveryAddress, ...] = Field(min_length=1)

    @property
    def topology(self) -> DeliveryTopology:
        regions = {item.region.casefold() for item in self.addresses}
        cities = {(item.region.casefold(), item.city.casefold()) for item in self.addresses}
        if len(regions) > 1:
            return DeliveryTopology.MULTI_REGION
        if len(cities) > 1:
            return DeliveryTopology.MULTI_CITY_ONE_REGION
        return DeliveryTopology.SINGLE_CITY


class TenderProcedure(BaseModel):
    """Минимальный проверяемый паспорт процедуры."""

    model_config = ConfigDict(frozen=True)

    tender_id: str = Field(min_length=1)
    customer_name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    law: ProcurementLaw
    method: ProcedureMethod
    stage: ProcedureStage
    submission: SubmissionWindow
    delivery: DeliveryPlan
    notice_provenance: Provenance

    def accepts_applications_at(self, moment: datetime) -> bool:
        return self.stage in {
            ProcedureStage.SUBMISSION_OPEN,
            ProcedureStage.SUBMISSION_CLOSING,
        } and self.submission.is_open_at(moment)
