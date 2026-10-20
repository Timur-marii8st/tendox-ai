"""Ограниченная, fail-closed проверка состава серверной сборки.

Результат не является решением о соответствии всему ТЗ: даже семь PASS
оставляют общий статус UNKNOWN до полноты требований и независимого review.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.compliance import DEFAULT_MIN_CONFIDENCE, Verdict, check_requirement
from procurement.domain.offers import Attribute, Candidate
from procurement.domain.provenance import Provenance
from procurement.domain.requirements import Operator, Requirement


class PartKind(str, Enum):
    CHASSIS = "chassis"
    CPU = "cpu"
    SSD = "ssd"
    PSU = "psu"


class InventoryScope(str, Enum):
    PARTIAL = "partial"
    EXACT_CONFIG = "exact_config"


class BomPart(BaseModel):
    """Строка состава сборки; атрибуты могут ссылаться на отдельные datasheet."""

    model_config = ConfigDict(frozen=True)

    kind: PartKind
    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    provenance: Provenance
    attributes: tuple[Attribute, ...] = ()

    @model_validator(mode="after")
    def _unique_attributes(self) -> BomPart:
        names = [attr.property for attr in self.attributes]
        if len(names) != len(set(names)):
            raise ValueError("дублирующиеся свойства детали не допускаются")
        return self


class ServerBom(BaseModel):
    """Идентифицированный черновик сборки, НЕ подтверждённое КП."""

    model_config = ConfigDict(frozen=True)

    bom_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_provenance: Provenance
    inventory_scope: InventoryScope = InventoryScope.PARTIAL
    parts: tuple[BomPart, ...] = ()

    @model_validator(mode="after")
    def _source_and_shape(self) -> ServerBom:
        if any(
            part.provenance.document_id != self.source_provenance.document_id for part in self.parts
        ):
            raise ValueError("каждая строка BOM должна относиться к тому же документу")
        chassis = [part for part in self.parts if part.kind is PartKind.CHASSIS]
        if len(chassis) > 1 or (chassis and chassis[0].quantity != 1):
            raise ValueError("допускается не более одного шасси в количестве 1")
        keys = [(part.kind, part.sku) for part in self.parts]
        if len(keys) != len(set(keys)):
            raise ValueError("дублирующиеся SKU одной роли не допускаются")
        return self


class BomGateCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement: Requirement
    verdict: Verdict
    actual: str
    reason: str
    evidence: tuple[Provenance, ...]


class BomAssessment(BaseModel):
    """Частичная диагностика: общий PASS конструктивно невозможен."""

    model_config = ConfigDict(frozen=True)

    bom_id: str
    source_sha256: str
    verdict: Verdict
    checks: tuple[BomGateCheck, ...]
    missing_gate_properties: tuple[str, ...]
    out_of_scope_requirements: tuple[Requirement, ...]

    @model_validator(mode="after")
    def _never_pass(self) -> BomAssessment:
        if self.verdict is Verdict.PASS:
            raise ValueError("частичная проверка BOM не может дать общий PASS")
        return self


# Только установленные компоненты и ёмкость конкретного шасси. Свойства
# намеренно узкие: максимум семейства не равен характеристике сборки.
_EACH: dict[str, PartKind] = {
    "cpu_cores_each": PartKind.CPU,
    "ssd_capacity_each": PartKind.SSD,
    "psu_power_each": PartKind.PSU,
    "front_lff_bays": PartKind.CHASSIS,
    "ocp_slots": PartKind.CHASSIS,
}
_COUNT: dict[str, PartKind] = {
    "ssd_count": PartKind.SSD,
    "psu_count": PartKind.PSU,
}
SUPPORTED_GATE_PROPERTIES = tuple((*_EACH, *_COUNT))


def _eligible(provenance: Provenance, threshold: float) -> bool:
    return provenance.confidence >= threshold


def _check_each(bom: ServerBom, req: Requirement, kind: PartKind, threshold: float) -> BomGateCheck:
    parts = tuple(part for part in bom.parts if part.kind is kind)
    evidence = (bom.source_provenance, *(part.provenance for part in parts))
    if not _eligible(bom.source_provenance, threshold):
        return BomGateCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual="не подтверждено",
            reason="низкая уверенность источника состава",
            evidence=evidence,
        )
    if not parts:
        verdict = (
            Verdict.FAIL if bom.inventory_scope is InventoryScope.EXACT_CONFIG else Verdict.UNKNOWN
        )
        return BomGateCheck(
            requirement=req,
            verdict=verdict,
            actual="нет строки детали",
            reason="деталь отсутствует в полном составе"
            if verdict is Verdict.FAIL
            else "состав неполон",
            evidence=evidence,
        )

    checks = []
    for part in parts:
        if not _eligible(part.provenance, threshold):
            checks.append((part, Verdict.UNKNOWN, part.sku, "низкая уверенность строки BOM"))
            continue
        attr = next((a for a in part.attributes if a.property == req.property), None)
        if attr is not None:
            evidence = (*evidence, attr.provenance)
        if attr is not None and not _eligible(attr.provenance, threshold):
            checks.append(
                (part, Verdict.UNKNOWN, part.sku, "низкая уверенность источника характеристики")
            )
            continue
        candidate = Candidate(candidate_id=part.sku, name=part.sku, attributes=part.attributes)
        result = check_requirement(req, candidate, min_confidence=threshold)
        checks.append((part, result.verdict, result.actual, result.reason))

    if any(verdict is Verdict.FAIL for _, verdict, _, _ in checks):
        verdict = Verdict.FAIL
    elif any(verdict is Verdict.UNKNOWN for _, verdict, _, _ in checks):
        verdict = Verdict.UNKNOWN
    else:
        verdict = Verdict.PASS
    return BomGateCheck(
        requirement=req,
        verdict=verdict,
        actual="; ".join(
            f"{part.sku} × {part.quantity}: {actual}" for part, _, actual, _ in checks
        ),
        reason="; ".join(f"{part.sku}: {reason}" for part, _, _, reason in checks),
        evidence=evidence,
    )


def _check_count(
    bom: ServerBom, req: Requirement, kind: PartKind, threshold: float
) -> BomGateCheck:
    parts = tuple(part for part in bom.parts if part.kind is kind)
    count = sum(part.quantity for part in parts)
    evidence = (bom.source_provenance, *(part.provenance for part in parts))
    assert isinstance(req.value, Decimal)
    if not all(_eligible(source, threshold) for source in evidence):
        verdict, reason = Verdict.UNKNOWN, "низкая уверенность источника состава"
    elif bom.inventory_scope is InventoryScope.PARTIAL and count < req.value:
        verdict, reason = (
            Verdict.UNKNOWN,
            "список деталей неполон; недостающее количество не доказано",
        )
    else:
        attr = Attribute(
            property=req.property,
            value=Decimal(count),
            unit="шт" if req.unit is not None else None,
            provenance=bom.source_provenance,
        )
        candidate = Candidate(candidate_id=bom.bom_id, name=bom.bom_id, attributes=(attr,))
        checked = check_requirement(req, candidate, min_confidence=threshold)
        verdict, reason = checked.verdict, checked.reason
    return BomGateCheck(
        requirement=req,
        verdict=verdict,
        actual=f"{count} шт",
        reason=reason,
        evidence=evidence,
    )


def assess_server_bom(
    bom: ServerBom,
    requirements: tuple[Requirement, ...],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> BomAssessment:
    """Сверить семь критичных числовых gates, не подменяя полный review ТЗ."""
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence должен быть от 0 до 1")
    checks: list[BomGateCheck] = []
    out_of_scope: list[Requirement] = []
    for req in requirements:
        if req.property not in SUPPORTED_GATE_PROPERTIES:
            out_of_scope.append(req)
            continue
        if (
            req.operator is not Operator.GE
            or not isinstance(req.value, Decimal)
            or not req.mandatory
        ):
            out_of_scope.append(req)
            continue
        if not _eligible(req.provenance, min_confidence):
            checks.append(
                BomGateCheck(
                    requirement=req,
                    verdict=Verdict.UNKNOWN,
                    actual="не проверено",
                    reason="низкая уверенность источника требования",
                    evidence=(bom.source_provenance,),
                )
            )
            continue
        if req.property in _EACH:
            checks.append(_check_each(bom, req, _EACH[req.property], min_confidence))
        else:
            checks.append(_check_count(bom, req, _COUNT[req.property], min_confidence))

    checked_names = {check.requirement.property for check in checks}
    return BomAssessment(
        bom_id=bom.bom_id,
        source_sha256=bom.source_sha256,
        verdict=(
            Verdict.FAIL
            if any(check.verdict is Verdict.FAIL for check in checks)
            else Verdict.UNKNOWN
        ),
        checks=tuple(checks),
        missing_gate_properties=tuple(
            name for name in SUPPORTED_GATE_PROPERTIES if name not in checked_names
        ),
        out_of_scope_requirements=tuple(out_of_scope),
    )
