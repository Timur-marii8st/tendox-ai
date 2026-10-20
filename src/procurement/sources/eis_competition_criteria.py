"""Read-only top-level EOK weights; no supplier score or legal admission."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_feed_archive import EisNoticeSnapshot

EP_NS = "http://zakupki.gov.ru/oos/EPtypes/1"
EXPORT_NS = "http://zakupki.gov.ru/oos/export/1"
SCHEMA_SHA = "4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7"
MAX_XML_BYTES = 32 * 1024 * 1024
_LABELS = {
    "CP": "Цена контракта, сумма цен единиц",
    "MC": "Расходы на эксплуатацию и ремонт",
    "TC": "Стоимость жизненного цикла",
    "EN": "Расходы заказчика по энергосервисному контракту",
    "QF": "Качественные, функциональные и экологические характеристики",
    "QO": "Квалификация участников закупки",
}
_VALID_CODES = {"COST": {"CP", "MC", "TC", "EN"}, "QUALITATIVE": {"QF", "QO"}}
WeightBand = Literal["STANDARD", "DISCOUNT_BELOW_25", "DISCOUNT_AT_LEAST_25", "UNKNOWN"]


class CriteriaModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisCriterionWeight(CriteriaModel):
    band: WeightBand
    value_percent: Decimal | None
    raw_value: str
    provenance: Provenance


class EisCompetitionCriterion(CriteriaModel):
    kind: Literal["COST", "QUALITATIVE", "UNKNOWN"]
    code: str | None
    code_provenance: Provenance | None
    label: str
    label_provenance: Provenance | None
    weights: tuple[EisCriterionWeight, ...]
    additional_info: str | None
    additional_info_provenance: Provenance | None
    indicators_status: Literal["PRESENT_UNREVIEWED", "NOT_OBSERVED", "UNKNOWN"]
    provenance: Provenance
    reasons: tuple[str, ...]


class EisCompetitionCriteria(CriteriaModel):
    source_xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_type: str
    source_status: Literal["EXTRACTED", "UNKNOWN", "NOT_APPLICABLE"]
    weight_integrity: Literal["CONSISTENT", "UNKNOWN", "NOT_APPLICABLE"]
    criteria: tuple[EisCompetitionCriterion, ...] = ()
    reasons: tuple[str, ...] = ()
    supplier_score_status: Literal["UNKNOWN"] = "UNKNOWN"
    qualification_status: Literal["UNKNOWN"] = "UNKNOWN"
    review_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def _claims_have_matching_evidence(self) -> EisCompetitionCriteria:
        for criterion in self.criteria:
            sources = [
                criterion.provenance,
                criterion.code_provenance,
                criterion.additional_info_provenance,
                *(w.provenance for w in criterion.weights),
            ]
            if any(p is not None and p.document_id != self.source_xml_sha256 for p in sources):
                raise ValueError("criterion evidence must match the exact XML")
        if self.weight_integrity == "CONSISTENT":
            patterns = {tuple(w.band for w in c.weights) for c in self.criteria}
            if (
                self.source_status != "EXTRACTED"
                or not self.criteria
                or len({c.code for c in self.criteria}) != len(self.criteria)
                or any(
                    c.code not in _VALID_CODES.get(c.kind, set())
                    or c.reasons
                    or c.code_provenance is None
                    or c.label_provenance is None
                    for c in self.criteria
                )
                or len(patterns) != 1
                or patterns.isdisjoint(
                    {("STANDARD",), ("DISCOUNT_BELOW_25", "DISCOUNT_AT_LEAST_25")}
                )
            ):
                raise ValueError("consistent weights require a complete unambiguous source shape")
            for position in range(len(self.criteria[0].weights)):
                values = [c.weights[position].value_percent for c in self.criteria]
                if any(
                    v is None or not v.is_finite() or not Decimal(0) <= v <= Decimal(100)
                    for v in values
                ) or sum((v for v in values if v is not None), Decimal(0)) != Decimal(100):
                    raise ValueError("consistent weights must sum to 100 in each band")
        if self.source_status == "NOT_APPLICABLE" and (
            self.document_type == "epNotificationEOK2020"
            or self.criteria
            or self.weight_integrity != "NOT_APPLICABLE"
        ):
            raise ValueError("not applicable cannot conceal competition criteria")
        return self


def unknown_competition_criteria(notice: EisNoticeSnapshot, reason: str) -> EisCompetitionCriteria:
    applicable = notice.document_type == "epNotificationEOK2020"
    return EisCompetitionCriteria(
        source_xml_sha256=notice.xml_sha256,
        document_type=notice.document_type,
        source_status="UNKNOWN" if applicable else "NOT_APPLICABLE",
        weight_integrity="UNKNOWN" if applicable else "NOT_APPLICABLE",
        reasons=(reason,) if applicable else (),
    )


def _one(parent: ET.Element, name: str) -> ET.Element | None:
    matches = [e for e in parent if e.tag.rsplit("}", 1)[-1] == name]
    return matches[0] if len(matches) == 1 else None


def extract_competition_criteria(raw: bytes, notice: EisNoticeSnapshot) -> EisCompetitionCriteria:
    """Parse only direct criteria weights: nested indicator weights have other denominators."""
    if notice.document_type != "epNotificationEOK2020":
        return unknown_competition_criteria(notice, "")
    if (
        not 0 < len(raw) <= MAX_XML_BYTES
        or b"\x00" in raw
        or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.IGNORECASE)
    ):
        return unknown_competition_criteria(notice, "CRITERIA_XML_UNSAFE")
    if hashlib.sha256(raw).hexdigest() != notice.xml_sha256:
        raise ValueError("EIS_CRITERIA_DIGEST_MISMATCH")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return unknown_competition_criteria(notice, "CRITERIA_XML_INVALID")
    if root.tag != f"{{{EXPORT_NS}}}export" or len(root) != 1:
        return unknown_competition_criteria(notice, "CRITERIA_ROOT_UNKNOWN")
    source = root[0]
    if source.tag != f"{{{EXPORT_NS}}}epNotificationEOK2020":
        raise ValueError("EIS_CRITERIA_NOTICE_MISMATCH")
    common = _one(source, "commonInfo")
    number = _one(common, "purchaseNumber") if common is not None else None
    version = _one(source, "versionNumber")
    if (
        number is None
        or version is None
        or (number.text or "").strip() != notice.purchase_number
        or (version.text or "").strip() != str(notice.version_number)
    ):
        raise ValueError("EIS_CRITERIA_NOTICE_MISMATCH")
    notification = _one(source, "notificationInfo")
    block = _one(notification, "criteriaInfo") if notification is not None else None
    if block is None or block.tag != f"{{{EP_NS}}}criteriaInfo" or not 0 < len(block) <= 20:
        return unknown_competition_criteria(notice, "CRITERIA_BLOCK_UNKNOWN")
    prefix = "epNotificationEOK2020/notificationInfo/criteriaInfo"

    def provenance(locator: str) -> Provenance:
        return Provenance(document_id=notice.xml_sha256, locator=locator, extractor=Extractor.API)

    entries = []
    overall_reasons = []
    for ordinal, item in enumerate(block, 1):
        locator = f"{prefix}/criterionInfo[{ordinal}]"
        if (
            item.tag != f"{{{EP_NS}}}criterionInfo"
            or len(item) != 1
            or item[0].tag
            not in {f"{{{EP_NS}}}costCriterionInfo", f"{{{EP_NS}}}qualitativeCriterionInfo"}
        ):
            return unknown_competition_criteria(notice, "CRITERIA_BRANCH_UNKNOWN")
        branch = item[0]
        kind: Literal["COST", "QUALITATIVE", "UNKNOWN"] = (
            "COST" if branch.tag.endswith("}costCriterionInfo") else "QUALITATIVE"
        )
        branch_name = branch.tag.rsplit("}", 1)[-1]
        locator += "/" + branch_name
        reasons = []
        code_nodes = branch.findall(f"{{{EP_NS}}}code")
        code = (
            (code_nodes[0].text or "").strip()
            if len(code_nodes) == 1 and not len(code_nodes[0])
            else None
        )
        known_code = code in _VALID_CODES[kind]
        if not known_code:
            reasons.append("CRITERION_CODE_UNKNOWN")
        values = branch.findall(f"{{{EP_NS}}}valueInfo")
        weights = []
        if len(values) == 1:
            names = tuple(e.tag for e in values[0])
            standard = names == (f"{{{EP_NS}}}value",)
            conditional = names == (
                f"{{{EP_NS}}}valueLess25MaxPrice",
                f"{{{EP_NS}}}valueMore25MaxPrice",
            )
            if not standard and not conditional:
                reasons.append("CRITERION_WEIGHT_SHAPE_UNKNOWN")
            if len(values[0]) > 4:
                return unknown_competition_criteria(notice, "CRITERION_WEIGHT_LIMIT")
            for position, element in enumerate(values[0], 1):
                raw_value = (element.text or "").strip()
                if len(raw_value) > 100:
                    return unknown_competition_criteria(notice, "CRITERION_WEIGHT_LIMIT")
                value = None
                if not len(element) and re.fullmatch(
                    r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", raw_value
                ):
                    parsed = Decimal(raw_value)
                    if Decimal(0) <= parsed <= Decimal(100):
                        value = parsed
                if value is None:
                    reasons.append("CRITERION_WEIGHT_UNKNOWN")
                band: WeightBand = "UNKNOWN"
                if standard:
                    band = "STANDARD"
                elif conditional:
                    band = "DISCOUNT_BELOW_25" if position == 1 else "DISCOUNT_AT_LEAST_25"
                weights.append(
                    EisCriterionWeight(
                        band=band,
                        value_percent=value,
                        raw_value=raw_value,
                        provenance=provenance(
                            f"{locator}/valueInfo/{element.tag.rsplit('}', 1)[-1]}[{position}]"
                        ),
                    )
                )
        else:
            reasons.append("CRITERION_WEIGHT_SHAPE_UNKNOWN")
        additional = branch.findall(f"{{{EP_NS}}}addInfo")
        additional_text = (
            (additional[0].text or "").strip()
            if len(additional) == 1 and not len(additional[0])
            else None
        )
        if (
            len(additional) > 1
            or (additional and len(additional[0]))
            or (additional_text and len(additional_text) > 4000)
        ):
            additional_text = None
            reasons.append("CRITERION_ADDITIONAL_INFO_UNKNOWN")
        indicators = branch.findall(f"{{{EP_NS}}}indicatorsInfo")
        label = _LABELS[code] if known_code and code is not None else "Неизвестный критерий"
        label_source = None
        if known_code:
            label_source = Provenance(
                document_id=SCHEMA_SHA,
                locator=f"IntegrationEPTypes.xsd/{branch_name.replace('Info', 'DocOKType')}/code"
                f" :: {code}; краткое название",
                extractor=Extractor.API,
            )
        entries.append(
            EisCompetitionCriterion(
                kind=kind,
                code=code,
                code_provenance=provenance(locator + "/code") if code is not None else None,
                label=label,
                label_provenance=label_source,
                weights=tuple(weights),
                additional_info=additional_text,
                additional_info_provenance=provenance(locator + "/addInfo")
                if additional_text
                else None,
                indicators_status="PRESENT_UNREVIEWED"
                if len(indicators) == 1
                else "UNKNOWN"
                if indicators
                else "NOT_OBSERVED",
                provenance=provenance(locator),
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
        overall_reasons.extend(reasons)
    if len({e.code for e in entries}) != len(entries):
        overall_reasons.append("CRITERION_CODE_DUPLICATE")
    patterns = {tuple(w.band for w in e.weights) for e in entries}
    if len(patterns) != 1 or patterns.isdisjoint(
        {("STANDARD",), ("DISCOUNT_BELOW_25", "DISCOUNT_AT_LEAST_25")}
    ):
        overall_reasons.append("CRITERIA_WEIGHT_REGIMES_UNKNOWN")
    elif not overall_reasons:
        for position in range(len(entries[0].weights)):
            values_at_position = [e.weights[position].value_percent for e in entries]
            if any(v is None for v in values_at_position) or sum(
                (v for v in values_at_position if v is not None), Decimal(0)
            ) != Decimal(100):
                overall_reasons.append("CRITERIA_WEIGHT_SUM_UNKNOWN")
    return EisCompetitionCriteria(
        source_xml_sha256=notice.xml_sha256,
        document_type=notice.document_type,
        source_status="UNKNOWN" if overall_reasons else "EXTRACTED",
        weight_integrity="UNKNOWN" if overall_reasons else "CONSISTENT",
        criteria=tuple(entries),
        reasons=tuple(dict.fromkeys(overall_reasons)),
    )
