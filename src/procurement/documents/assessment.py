"""Fail-closed проверка кандидата по результату document requirement mapping."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.facts import (
    CompletenessAssessment,
    CompletenessStatus,
    FactMappingResult,
)
from procurement.domain.compliance import (
    CandidateVerdict,
    ComplianceResult,
    evaluate,
)
from procurement.domain.offers import Candidate
from procurement.domain.requirements import LineItem


class DocumentComplianceAssessment(BaseModel):
    """Итог по известным требованиям с отдельным gate полноты документа."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: CandidateVerdict
    reasons: tuple[str, ...] = Field(min_length=1)
    completeness: CompletenessAssessment
    compliance: ComplianceResult

    @model_validator(mode="after")
    def _result_is_fail_closed(self) -> DocumentComplianceAssessment:
        if self.compliance.verdict is CandidateVerdict.FAIL:
            if self.verdict is not CandidateVerdict.FAIL:
                raise ValueError("известный mandatory FAIL должен оставаться итоговым FAIL")
            return self
        if self.completeness.status is not CompletenessStatus.PASS:
            if self.verdict is not CandidateVerdict.NEEDS_CLARIFICATION:
                raise ValueError("неподтверждённая полнота требует NEEDS_CLARIFICATION")
            return self
        if self.verdict is not self.compliance.verdict:
            raise ValueError("при подтверждённой полноте итог должен совпадать с compliance")
        return self


def evaluate_document_mapping(
    mapping: FactMappingResult,
    item: LineItem,
    candidate: Candidate,
    *,
    min_confidence: float = 0.75,
) -> DocumentComplianceAssessment:
    """Проверить только точные требования mapping и применить gate полноты.

    Положительный результат движка по известным требованиям не повышается до
    ``COMPLIANT``, пока человек не подтвердил полноту exact mapping. Доказанный
    mandatory ``FAIL`` сохраняется даже при неполном документе.
    """
    checked_mapping = FactMappingResult.model_validate(mapping.model_dump(mode="python"))
    checked_item = LineItem.model_validate(item.model_dump(mode="python"))
    checked_candidate = Candidate.model_validate(candidate.model_dump(mode="python"))
    if checked_item.requirements != checked_mapping.requirements:
        raise ValueError("LineItem должен содержать точные requirements проверяемого mapping")
    if (
        checked_mapping.delivery_deadline is not None
        and checked_item.delivery_deadline != checked_mapping.delivery_deadline
    ):
        raise ValueError("дата поставки LineItem не совпадает с document mapping")
    if (
        checked_mapping.equivalent_allowed is not None
        and checked_item.equivalent_allowed != checked_mapping.equivalent_allowed
    ):
        raise ValueError("режим эквивалента LineItem не совпадает с document mapping")

    compliance = evaluate(checked_item, checked_candidate, min_confidence=min_confidence)
    if compliance.verdict is CandidateVerdict.FAIL:
        return DocumentComplianceAssessment(
            verdict=CandidateVerdict.FAIL,
            reasons=tuple(check.reason for check in compliance.blocking),
            completeness=checked_mapping.completeness,
            compliance=compliance,
        )
    if checked_mapping.completeness.status is not CompletenessStatus.PASS:
        reason = (
            "полнота извлечения требований не подтверждена"
            if checked_mapping.completeness.status is CompletenessStatus.UNKNOWN
            else "review выявил неразобранное существенное требование"
        )
        return DocumentComplianceAssessment(
            verdict=CandidateVerdict.NEEDS_CLARIFICATION,
            reasons=(reason,),
            completeness=checked_mapping.completeness,
            compliance=compliance,
        )
    reasons = (
        tuple(check.reason for check in compliance.open_questions)
        if compliance.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        else ("полнота документа подтверждена, известные требования пройдены",)
    )
    return DocumentComplianceAssessment(
        verdict=compliance.verdict,
        reasons=reasons,
        completeness=checked_mapping.completeness,
        compliance=compliance,
    )
