"""Частичный BOM-check: известный FAIL блокирует, пробелы не дают PASS."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.compliance import Verdict
from procurement.domain.offers import Attribute
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement
from procurement.domain.server_bom import (
    BomPart,
    InventoryScope,
    PartKind,
    ServerBom,
    assess_server_bom,
)


def source(document_id: str, locator: str, confidence: float = 1.0) -> Provenance:
    return Provenance(
        document_id=document_id,
        locator=locator,
        extractor=Extractor.MANUAL,
        confidence=confidence,
    )


def requirement(prop: str, value: int, unit: str | None = None) -> Requirement:
    return Requirement(
        property=prop,
        operator=Operator.GE,
        value=Decimal(value),
        unit=unit,
        mandatory=True,
        raw_text=f"{prop} не менее {value}",
        provenance=source("ТЗ", f"строка {prop}"),
    )


def part(
    kind: PartKind,
    sku: str,
    quantity: int,
    attrs: tuple[Attribute, ...] = (),
    confidence: float = 1.0,
) -> BomPart:
    return BomPart(
        kind=kind,
        sku=sku,
        quantity=quantity,
        provenance=source("BOM-1", f"строка {sku}", confidence),
        attributes=attrs,
    )


def attribute(prop: str, value: int, unit: str | None = None, confidence: float = 1.0) -> Attribute:
    return Attribute(
        property=prop,
        value=Decimal(value),
        unit=unit,
        confidence=confidence,
        provenance=source("datasheet-1", f"поле {prop}"),
    )


def bom(*parts: BomPart, scope: InventoryScope = InventoryScope.PARTIAL) -> ServerBom:
    return ServerBom(
        bom_id="draft-1",
        source_sha256="a" * 64,
        source_provenance=source("BOM-1", "весь документ"),
        inventory_scope=scope,
        parts=parts,
    )


def test_known_cpu_failure_blocks_even_when_other_cpu_is_unknown() -> None:
    result = assess_server_bom(
        bom(
            part(PartKind.CPU, "cpu-12", 1, (attribute("cpu_cores_each", 12),)),
            part(PartKind.CPU, "cpu-unknown", 1),
        ),
        (requirement("cpu_cores_each", 16, "шт"),),
    )
    # Без единицы у характеристики сравнение не может выдать ложный FAIL.
    assert result.checks[0].verdict is Verdict.UNKNOWN
    assert result.verdict is Verdict.UNKNOWN


def test_known_cpu_failure_with_matching_units_blocks() -> None:
    result = assess_server_bom(
        bom(
            part(PartKind.CPU, "cpu-12", 1, (attribute("cpu_cores_each", 12, "шт"),)),
            part(PartKind.CPU, "cpu-unknown", 1),
        ),
        (requirement("cpu_cores_each", 16, "шт"),),
    )
    assert result.checks[0].verdict is Verdict.FAIL
    assert result.verdict is Verdict.FAIL
    assert result.checks[0].evidence[0].document_id == "BOM-1"
    assert result.checks[0].evidence[-1].document_id == "datasheet-1"


def test_partial_inventory_low_count_is_unknown_but_exact_is_fail() -> None:
    req = requirement("ssd_count", 4, "шт")
    ssd = part(PartKind.SSD, "ssd-1", 2)
    partial = assess_server_bom(bom(ssd), (req,))
    exact = assess_server_bom(bom(ssd, scope=InventoryScope.EXACT_CONFIG), (req,))
    assert partial.checks[0].verdict is Verdict.UNKNOWN
    assert exact.checks[0].verdict is Verdict.FAIL


def test_passed_subset_never_becomes_overall_pass() -> None:
    result = assess_server_bom(
        bom(part(PartKind.SSD, "ssd-1", 4)),
        (requirement("ssd_count", 4),),
    )
    assert result.checks[0].verdict is Verdict.PASS
    assert result.verdict is Verdict.UNKNOWN
    assert "cpu_cores_each" in result.missing_gate_properties


def test_gbytes_and_watts_checked_for_installed_parts() -> None:
    result = assess_server_bom(
        bom(
            part(PartKind.SSD, "ssd-1", 4, (attribute("ssd_capacity_each", 960, "ГБ"),)),
            part(PartKind.PSU, "psu-1", 2, (attribute("psu_power_each", 800, "Вт"),)),
        ),
        (
            requirement("ssd_capacity_each", 960, "Гбайт"),
            requirement("psu_power_each", 1300, "Вт"),
        ),
    )
    assert [check.verdict for check in result.checks] == [Verdict.PASS, Verdict.FAIL]
    assert result.verdict is Verdict.FAIL


def test_low_confidence_or_missing_attribute_is_unknown() -> None:
    result = assess_server_bom(
        bom(
            part(PartKind.CPU, "cpu-1", 1, (attribute("cpu_cores_each", 12, confidence=0.5),)),
            part(PartKind.PSU, "psu-1", 2),
        ),
        (requirement("cpu_cores_each", 16), requirement("psu_power_each", 1300, "Вт")),
    )
    assert all(check.verdict is Verdict.UNKNOWN for check in result.checks)
    assert result.verdict is Verdict.UNKNOWN


def test_unsupported_requirement_is_exposed_not_silently_passed() -> None:
    outside = requirement("nic_ports", 2)
    result = assess_server_bom(bom(), (outside,))
    assert result.checks == ()
    assert result.out_of_scope_requirements == (outside,)
    assert result.verdict is Verdict.UNKNOWN


def test_mixed_bom_source_and_duplicate_attributes_rejected() -> None:
    with pytest.raises(ValidationError, match="тому же документу"):
        ServerBom(
            bom_id="mixed",
            source_sha256="a" * 64,
            source_provenance=source("BOM-1", "all"),
            parts=(
                BomPart(
                    kind=PartKind.CPU, sku="cpu", quantity=1, provenance=source("BOM-2", "row")
                ),
            ),
        )
    with pytest.raises(ValidationError, match="дублирующиеся свойства"):
        part(
            PartKind.CPU,
            "cpu",
            1,
            (attribute("cpu_cores_each", 12), attribute("cpu_cores_each", 16)),
        )
