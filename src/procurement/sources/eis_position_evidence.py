"""Bounded source positions and native table leads; never approved specifications."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import DecimalFact, Eis223NoticeSnapshot, TextFact
from procurement.sources.eis_analysis import DocumentAnalysis
from procurement.sources.eis_feed_archive import EisNoticeSnapshot

MAX_POSITIONS = 25
MAX_CHARACTERISTICS = 24
MAX_VALUES = 8
MAX_TABLE_ROWS = 12
MAX_CELLS = 8
_ROW = re.compile(r"^(.*\btable \d+ row \d+) cell \d+$")


class EvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CharacteristicNumberFact(EvidenceModel):
    """Signed exact physical value; never reused as a money/quantity contract."""

    value: Decimal | None
    raw: str | None = Field(max_length=400)
    raw_truncated: bool = False
    provenance: Provenance

    @field_validator("value", mode="before")
    @classmethod
    def exact_number(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("characteristic cannot use float or bool")
        return value

    @field_validator("value")
    @classmethod
    def finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("characteristic must be finite")
        return value


class CharacteristicValueEvidence(EvidenceModel):
    description: TextFact
    minimum: CharacteristicNumberFact
    minimum_operator: TextFact
    maximum: CharacteristicNumberFact
    maximum_operator: TextFact
    unit: TextFact
    concrete_values: tuple[CharacteristicNumberFact, ...] = Field(default=(), max_length=MAX_VALUES)
    concrete_values_total: int = Field(default=0, ge=0)
    concrete_values_truncated: bool = False
    range_source_complete: bool = Field(default=False, strict=True)


class CharacteristicEvidence(EvidenceModel):
    name: TextFact
    instruction_code: TextFact
    values: tuple[CharacteristicValueEvidence, ...] = Field(max_length=MAX_VALUES)
    values_total: int = Field(ge=0)
    truncated: bool
    review_status: Literal["UNKNOWN"] = "UNKNOWN"


class PositionEvidence(EvidenceModel):
    source_index: int = Field(ge=1)
    lot_index: int | None = Field(default=None, ge=1)
    lot_ordinal: TextFact | None = None
    name: TextFact
    quantity: DecimalFact
    unit: TextFact
    classification_code: TextFact
    ktru_code: TextFact
    unit_price: DecimalFact
    line_sum: DecimalFact
    currency: TextFact
    characteristics: tuple[CharacteristicEvidence, ...] = Field(max_length=MAX_CHARACTERISTICS)
    characteristics_total: int = Field(ge=0)
    characteristics_truncated: bool
    characteristics_status: Literal["SOURCE_VALUES", "UNKNOWN"]
    provenance: Provenance
    review_status: Literal["UNKNOWN"] = "UNKNOWN"


class TableCellLead(EvidenceModel):
    text: str = Field(min_length=1, max_length=400)
    truncated: bool
    provenance: Provenance


class TableRowLead(EvidenceModel):
    cells: tuple[TableCellLead, ...] = Field(min_length=1, max_length=MAX_CELLS)
    cells_total: int = Field(ge=1)
    truncated: bool


class NativeTableLead(EvidenceModel):
    content_uid: str
    filename: str
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    extraction_status: Literal["PASS", "FAIL", "UNKNOWN"]
    extraction_reasons: tuple[str, ...]
    rows: tuple[TableRowLead, ...] = Field(max_length=MAX_TABLE_ROWS)
    rows_total: int = Field(ge=0)
    truncated: bool
    role_status: Literal["UNKNOWN"] = "UNKNOWN"
    position_association: Literal["UNKNOWN"] = "UNKNOWN"


class PositionEvidenceSet(EvidenceModel):
    law: Literal["44", "223"]
    purchase_number: str
    version_number: int = Field(ge=1)
    notice_xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    positions: tuple[PositionEvidence, ...] = Field(max_length=MAX_POSITIONS)
    positions_total: int = Field(ge=0)
    positions_truncated: bool
    native_tables: tuple[NativeTableLead, ...] = Field(max_length=32)
    specification_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    review_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def exact_sources(self) -> PositionEvidenceSet:
        def check(value: object) -> None:
            if isinstance(value, Provenance):
                if value.document_id != self.notice_xml_sha256:
                    raise ValueError("POSITION_XML_PROVENANCE_MISMATCH")
            elif isinstance(value, BaseModel):
                for key in type(value).model_fields:
                    check(getattr(value, key))
            elif isinstance(value, tuple):
                for item in value:
                    check(item)

        check(self.positions)
        for document in self.native_tables:
            for row in document.rows:
                if any(
                    cell.provenance.document_id != document.document_sha256 for cell in row.cells
                ):
                    raise ValueError("POSITION_NATIVE_PROVENANCE_MISMATCH")
        return self


def native_table_leads(
    documents: Iterable[tuple[str, DocumentAnalysis]],
) -> tuple[NativeTableLead, ...]:
    """Keep native cells in their actual rows; no semantic mapping or formula evaluation."""
    result = []
    for uid, analysis in documents:
        # Bundle-member hashes need a separate parent/member evidence chain.
        if not analysis.filename.casefold().endswith(".docx"):
            continue
        rows: dict[str, list[TableCellLead]] = {}
        for block in analysis.blocks:
            if block.provenance.extractor != Extractor.NATIVE_DOCX:
                continue
            match = _ROW.fullmatch(block.provenance.locator)
            if not match:
                continue
            if block.provenance.document_id != analysis.sha256:
                raise ValueError("POSITION_NATIVE_PROVENANCE_MISMATCH")
            rows.setdefault(match.group(1), []).append(
                TableCellLead(
                    text=block.text[:400],
                    truncated=len(block.text) > 400,
                    provenance=block.provenance,
                )
            )
        if not rows:
            continue
        selected = tuple(
            TableRowLead(
                cells=tuple(cells[:MAX_CELLS]),
                cells_total=len(cells),
                truncated=len(cells) > MAX_CELLS or any(c.truncated for c in cells[:MAX_CELLS]),
            )
            for cells in list(rows.values())[:MAX_TABLE_ROWS]
        )
        result.append(
            NativeTableLead(
                content_uid=uid,
                filename=analysis.filename,
                document_sha256=analysis.sha256,
                extraction_status=analysis.status,
                extraction_reasons=analysis.reasons,
                rows=selected,
                rows_total=len(rows),
                truncated=len(rows) > MAX_TABLE_ROWS or any(r.truncated for r in selected),
            )
        )
    return tuple(result)


def positions44(
    notice: EisNoticeSnapshot,
    documents: Iterable[tuple[str, DocumentAnalysis]] = (),
) -> PositionEvidenceSet:
    def provenance(locator: str) -> Provenance:
        return Provenance(
            document_id=notice.xml_sha256,
            locator=f"{notice.source_member} :: {locator}",
            extractor=Extractor.API,
        )

    def text(value: str | None, locator: str) -> TextFact:
        return TextFact(value=value, raw=None, provenance=provenance(locator))

    def decimal(value: Decimal | None, locator: str) -> DecimalFact:
        return DecimalFact(value=value, raw=None, provenance=provenance(locator))

    def number(
        value: Decimal | None, locator: str, raw: str | None = None
    ) -> CharacteristicNumberFact:
        return CharacteristicNumberFact(
            value=value,
            raw=raw[:400] if raw is not None else None,
            raw_truncated=raw is not None and len(raw) > 400,
            provenance=provenance(locator),
        )

    positions = []
    for index, item in enumerate(notice.lot_items[:MAX_POSITIONS], 1):
        characteristics = []
        for c in item.characteristics[:MAX_CHARACTERISTICS]:
            values = tuple(
                CharacteristicValueEvidence(
                    description=text(v.quality_description, v.locator + "/qualityDescription"),
                    minimum=number(
                        v.minimum, v.locator + "/rangeSet/valueRange/min", v.minimum_raw
                    ),
                    minimum_operator=text(
                        v.minimum_operator, v.locator + "/rangeSet/valueRange/minMathNotation"
                    ),
                    maximum=number(
                        v.maximum, v.locator + "/rangeSet/valueRange/max", v.maximum_raw
                    ),
                    maximum_operator=text(
                        v.maximum_operator, v.locator + "/rangeSet/valueRange/maxMathNotation"
                    ),
                    unit=text(v.unit, v.locator + "/OKEI/name"),
                    concrete_values=tuple(
                        number(x.value, x.locator, x.raw) for x in v.concrete_values[:MAX_VALUES]
                    ),
                    concrete_values_total=len(v.concrete_values),
                    concrete_values_truncated=len(v.concrete_values) > MAX_VALUES,
                    range_source_complete=v.range_source_complete,
                )
                for v in c.values[:MAX_VALUES]
            )
            characteristics.append(
                CharacteristicEvidence(
                    name=text(c.name, c.locator + "/name"),
                    instruction_code=text(
                        c.filling_instruction_code,
                        c.locator + "/characteristicsFillingInstruction/code",
                    ),
                    values=values,
                    values_total=len(c.values),
                    truncated=len(c.values) > MAX_VALUES,
                )
            )
        p = item.locator
        positions.append(
            PositionEvidence(
                source_index=index,
                name=text(item.name, p + "/name"),
                quantity=decimal(item.quantity, p + "/quantity/value"),
                unit=text(item.unit, p + "/OKEI/name"),
                classification_code=text(item.okpd2_code, p + "/KTRU/OKPD2/OKPDCode"),
                ktru_code=text(item.ktru_code, p + "/KTRU/code"),
                unit_price=decimal(item.unit_price_rub, p + "/price"),
                line_sum=decimal(item.line_sum_rub, p + "/sum"),
                currency=text(
                    "RUB" if notice.nmck_rub is not None else None,
                    notice.document_type
                    + "/notificationInfo/contractConditionsInfo/maxPriceInfo/currency/code",
                ),
                characteristics=tuple(characteristics),
                characteristics_total=len(item.characteristics),
                characteristics_truncated=len(item.characteristics) > MAX_CHARACTERISTICS,
                characteristics_status=(
                    "SOURCE_VALUES"
                    if item.characteristics
                    and not any(
                        value.range_structure_unknown
                        for characteristic in item.characteristics
                        for value in characteristic.values
                    )
                    else "UNKNOWN"
                ),
                provenance=provenance(p),
            )
        )
    return PositionEvidenceSet(
        law="44",
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
        positions=tuple(positions),
        positions_total=len(notice.lot_items),
        positions_truncated=len(notice.lot_items) > MAX_POSITIONS,
        native_tables=native_table_leads(documents),
    )


def positions223(
    notice: Eis223NoticeSnapshot,
    documents: Iterable[tuple[str, DocumentAnalysis]] = (),
) -> PositionEvidenceSet:
    positions: list[PositionEvidence] = []
    total = 0
    for lot_index, lot in enumerate(notice.lots, 1):
        for item in lot.items:
            total += 1
            if len(positions) >= MAX_POSITIONS:
                continue
            unknown_text = TextFact(value=None, raw=None, provenance=item.provenance)
            unknown_decimal = DecimalFact(value=None, raw=None, provenance=item.provenance)
            positions.append(
                PositionEvidence(
                    source_index=total,
                    lot_index=lot_index,
                    lot_ordinal=lot.ordinal,
                    name=item.description,
                    quantity=item.quantity,
                    unit=item.unit_name,
                    classification_code=item.classification_code,
                    ktru_code=unknown_text,
                    unit_price=unknown_decimal,
                    line_sum=unknown_decimal,
                    currency=lot.currency,
                    characteristics=(),
                    characteristics_total=0,
                    characteristics_truncated=False,
                    characteristics_status="UNKNOWN",
                    provenance=item.provenance,
                )
            )
    return PositionEvidenceSet(
        law="223",
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
        positions=tuple(positions),
        positions_total=total,
        positions_truncated=total > MAX_POSITIONS,
        native_tables=native_table_leads(documents),
    )


class PositionLinkLead(EvidenceModel):
    left_row: int = Field(ge=0, le=2)
    right_row: int = Field(ge=0, le=2)
    left_position: int = Field(ge=1)
    right_position: int = Field(ge=1)
    basis: Literal["NAME", "KTRU", "CLASSIFICATION"]
    differences: tuple[str, ...]
    evidence: tuple[Provenance, Provenance]
    equivalence: Literal["UNKNOWN"] = "UNKNOWN"
    price_comparability: Literal["UNKNOWN"] = "UNKNOWN"


def _normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().replace("ё", "е").split())


def position_links(
    sets: tuple[PositionEvidenceSet, ...],
) -> tuple[tuple[PositionLinkLead, ...], bool]:
    """Suggest source label/code overlaps, with no product or price equivalence verdict."""
    result: list[PositionLinkLead] = []
    for i, left in enumerate(sets):
        for j in range(i + 1, len(sets)):
            for a in left.positions:
                for b in sets[j].positions:
                    basis: Literal["NAME", "KTRU", "CLASSIFICATION"] | None = None
                    labels: tuple[tuple[str, Literal["NAME", "KTRU", "CLASSIFICATION"]], ...] = (
                        ("name", "NAME"),
                        ("ktru_code", "KTRU"),
                        ("classification_code", "CLASSIFICATION"),
                    )
                    for key, label in labels:
                        av = _normalize(getattr(a, key).value)
                        if av and av == _normalize(getattr(b, key).value):
                            basis = label
                            break
                    if basis is None:
                        continue
                    if len(result) >= 24:
                        return tuple(result), True
                    differences = []
                    for key, code in (
                        ("quantity", "SOURCE_QUANTITY_DIFFERS"),
                        ("unit", "SOURCE_UNIT_LABEL_DIFFERS"),
                    ):
                        av, bv = getattr(a, key).value, getattr(b, key).value
                        if av is None or bv is None:
                            differences.append(key.upper() + "_UNKNOWN")
                        elif av != bv:
                            differences.append(code)
                    if not a.characteristics or not b.characteristics:
                        differences.append("CHARACTERISTICS_UNKNOWN")
                    else:

                        def values(p: PositionEvidence) -> dict[str, tuple[object, ...]]:
                            result: dict[str, tuple[object, ...]] = {}
                            for c in p.characteristics:
                                key = _normalize(c.name.value)
                                result[key] = result.get(key, ()) + tuple(
                                    (
                                        v.description.value,
                                        v.minimum.value,
                                        v.minimum_operator.value,
                                        v.maximum.value,
                                        v.maximum_operator.value,
                                        tuple((x.value, x.raw) for x in v.concrete_values),
                                        v.unit.value,
                                    )
                                    for v in c.values
                                )
                            return result

                        va, vb = values(a), values(b)
                        if any(va[key] != vb[key] for key in va.keys() & vb.keys()):
                            differences.append("SOURCE_CHARACTERISTIC_VALUES_DIFFER")
                        if va.keys() != vb.keys():
                            differences.append("CHARACTERISTIC_SETS_DIFFER")
                    if basis == "CLASSIFICATION":
                        differences.append("CLASSIFICATION_DOES_NOT_ESTABLISH_EQUIVALENCE")
                    if (
                        left.positions_truncated
                        or sets[j].positions_truncated
                        or a.characteristics_truncated
                        or b.characteristics_truncated
                        or any(c.truncated for c in (*a.characteristics, *b.characteristics))
                        or any(
                            v.concrete_values_truncated
                            for c in (*a.characteristics, *b.characteristics)
                            for v in c.values
                        )
                    ):
                        differences.append("SOURCE_PREVIEW_TRUNCATED")
                    result.append(
                        PositionLinkLead(
                            left_row=i,
                            right_row=j,
                            left_position=a.source_index,
                            right_position=b.source_index,
                            basis=basis,
                            differences=tuple(differences),
                            evidence=(a.provenance, b.provenance),
                        )
                    )
    return tuple(result), False
