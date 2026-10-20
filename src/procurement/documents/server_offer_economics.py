"""Complete three-scenario economics bound to one independently reviewed offer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.server_offer_review import ServerOfferReviewRecord
from procurement.domain.cases import ProcurementCase, case_input_digest
from procurement.domain.compliance import Verdict
from procurement.domain.economics import (
    CostBreakdown,
    DealEconomics,
    EconomicsScenario,
    ScenarioKind,
    ScenarioSet,
    _finite_decimal,
)


class ServerOfferOperatingCostsInput(BaseModel):
    """Every non-goods cost must be explicit, including confirmed zeroes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    packaging: Decimal = Field(ge=0)
    logistics: Decimal = Field(ge=0)
    loading_unloading: Decimal = Field(ge=0)
    storage: Decimal = Field(ge=0)
    installation: Decimal = Field(ge=0)
    payroll_travel: Decimal = Field(ge=0)
    subcontracting: Decimal = Field(ge=0)
    insurance: Decimal = Field(ge=0)
    finance: Decimal = Field(ge=0)
    bank_guarantee: Decimal = Field(ge=0)
    platform_fees: Decimal = Field(ge=0)
    taxes: Decimal = Field(ge=0)
    certification: Decimal = Field(ge=0)
    warranty: Decimal = Field(ge=0)
    risk_reserve: Decimal = Field(ge=0)
    penalty_reserve: Decimal = Field(ge=0)
    other: Decimal = Field(ge=0)

    @field_validator("*", mode="before")
    @classmethod
    def _exact_decimal(cls, value: object) -> Decimal:
        return _finite_decimal(value)  # type: ignore[arg-type]


class ServerOfferScenarioInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ScenarioKind
    contract_revenue: Decimal = Field(gt=0)
    costs: ServerOfferOperatingCostsInput
    assumptions: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("contract_revenue", mode="before")
    @classmethod
    def _exact_revenue(cls, value: object) -> Decimal:
        return _finite_decimal(value)  # type: ignore[arg-type]

    @field_validator("assumptions")
    @classmethod
    def _assumptions_are_explicit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item or len(item) > 2_000 for item in normalized):
            raise ValueError("scenario assumptions must be non-empty and bounded")
        return normalized


class ServerOfferEconomicsEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case: ProcurementCase
    offer_review: ServerOfferReviewRecord

    @model_validator(mode="after")
    def _exact_pass_review_for_case(self) -> Self:
        proposal = self.offer_review.evidence.proposal
        decision = self.offer_review.decision
        if decision is None or decision.status is not Verdict.PASS:
            raise ValueError("economics requires terminal PASS server-offer review")
        if (
            proposal.company_id != self.case.company_id
            or proposal.case_id != self.case.case_id
            or proposal.case_version != self.case.version
        ):
            raise ValueError("reviewed offer does not belong to the exact case version")
        return self


class ServerOfferEconomicsPackage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["server-offer-economics-package-v1"] = (
        "server-offer-economics-package-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    economics_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    case_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offer_id: str = Field(min_length=1, max_length=200)
    offer_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offer_review_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_set: ScenarioSet
    scenario_status: Literal["COMPLETE"] = "COMPLETE"
    recommendation_status: Literal[Verdict.UNKNOWN] = Verdict.UNKNOWN
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: datetime
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("economics package time must include timezone")
        return value

    @model_validator(mode="after")
    def _complete_and_digest_bound(self) -> Self:
        if not self.scenario_set.is_complete:
            raise ValueError("all three economics scenarios must be complete")
        payload = self.model_dump(mode="json", exclude={"package_sha256"})
        if canonical_json_sha256(payload) != self.package_sha256:
            raise ValueError("server-offer economics package digest does not match payload")
        return self


class ServerOfferEconomicsRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: ServerOfferEconomicsEvidence
    package: ServerOfferEconomicsPackage | None = None

    @model_validator(mode="after")
    def _package_matches_evidence(self) -> Self:
        if self.package is None:
            return self
        rebuilt = build_server_offer_economics_package(
            self.evidence,
            economics_id=self.package.economics_id,
            scenarios=tuple(
                ServerOfferScenarioInput(
                    kind=scenario.kind,
                    contract_revenue=scenario.economics.contract_revenue,
                    costs=ServerOfferOperatingCostsInput(
                        **scenario.economics.costs.model_dump(
                            mode="python", exclude={"goods", "specified_cost_fields"}
                        )
                    ),
                    assumptions=scenario.assumptions,
                )
                for scenario in self.package.scenario_set.scenarios
            ),
            prepared_by=self.package.prepared_by,
            prepared_at=self.package.prepared_at,
        )
        if rebuilt != self.package:
            raise ValueError("economics package does not match exact evidence")
        return self


def build_server_offer_economics_package(
    evidence: ServerOfferEconomicsEvidence,
    *,
    economics_id: str,
    scenarios: tuple[ServerOfferScenarioInput, ...],
    prepared_by: str,
    prepared_at: datetime,
) -> ServerOfferEconomicsPackage:
    review = evidence.offer_review
    decision = review.decision
    assert decision is not None
    proposal = review.evidence.proposal
    quote = proposal.commercial_terms
    if prepared_by == decision.reviewed_by:
        raise ValueError("economics preparer must differ from offer reviewer")
    if not quote.is_complete or not quote.issued_at <= prepared_at < quote.valid_until:
        raise ValueError("economics requires a complete quote valid at preparation time")
    expected_kinds = tuple(ScenarioKind)
    if tuple(item.kind for item in scenarios) != expected_kinds:
        raise ValueError("scenarios must be ordered base, realistic, conservative")
    built: list[EconomicsScenario] = []
    for item in scenarios:
        if item.contract_revenue > evidence.case.nmck_ex_vat:
            raise ValueError("scenario revenue cannot exceed exact case NMCK")
        costs = CostBreakdown(
            goods=quote.amount_ex_vat,
            **item.costs.model_dump(mode="python"),
        )
        economics = DealEconomics(
            contract_revenue=item.contract_revenue,
            costs=costs,
            nds_rate=quote.nds_rate,
        )
        if not economics.is_complete:
            raise ValueError("scenario economics is incomplete")
        built.append(
            EconomicsScenario(
                kind=item.kind, economics=economics, assumptions=item.assumptions
            )
        )
    scenario_set = ScenarioSet(scenarios=tuple(built))
    draft = ServerOfferEconomicsPackage.model_construct(
        schema_version="server-offer-economics-package-v1",
        company_id=proposal.company_id,
        economics_id=economics_id,
        case_id=proposal.case_id,
        case_version=proposal.case_version,
        case_input_sha256=case_input_digest(evidence.case),
        offer_id=proposal.offer_id,
        offer_proposal_sha256=proposal.proposal_sha256,
        offer_review_decision_sha256=decision.decision_sha256,
        source_document_id=proposal.source_document_id,
        source_document_sha256=proposal.source_document_sha256,
        scenario_set=scenario_set,
        scenario_status="COMPLETE",
        recommendation_status=Verdict.UNKNOWN,
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        package_sha256="0" * 64,
    )
    digest = canonical_json_sha256(draft.model_dump(mode="json", exclude={"package_sha256"}))
    return ServerOfferEconomicsPackage.model_validate(
        draft.model_dump(mode="python") | {"package_sha256": digest}
    )
