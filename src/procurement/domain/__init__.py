"""Ядро домена.

Чистая логика без I/O и сетевых вызовов: профиль компании, процедуры,
требования ТЗ, соответствие, экономика, решение и подтверждение действий.
"""

from procurement.domain.actions import ActionRequest, ActionType, Approval, is_authorized
from procurement.domain.company import CompanyProfile, FinancialPolicy, ProhibitionRule
from procurement.domain.compliance import (
    CandidateVerdict,
    ComplianceResult,
    RequirementCheck,
    Verdict,
    evaluate,
)
from procurement.domain.decisions import Recommendation, TenderRating, recommend
from procurement.domain.economics import (
    CostBreakdown,
    DealEconomics,
    EconomicsScenario,
    ScenarioKind,
    ScenarioSet,
    cost_of_money,
)
from procurement.domain.offers import Attribute, Candidate
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import LineItem, Operator, Requirement
from procurement.domain.tenders import TenderProcedure
from procurement.domain.units import Quantity, Unit, resolve_unit

__all__ = [
    "ActionRequest",
    "ActionType",
    "Approval",
    "Attribute",
    "Candidate",
    "CandidateVerdict",
    "CompanyProfile",
    "ComplianceResult",
    "CostBreakdown",
    "DealEconomics",
    "EconomicsScenario",
    "Extractor",
    "FinancialPolicy",
    "LineItem",
    "Operator",
    "ProhibitionRule",
    "Provenance",
    "Quantity",
    "Recommendation",
    "Requirement",
    "RequirementCheck",
    "ScenarioKind",
    "ScenarioSet",
    "TenderProcedure",
    "TenderRating",
    "Unit",
    "Verdict",
    "cost_of_money",
    "evaluate",
    "is_authorized",
    "recommend",
    "resolve_unit",
]
