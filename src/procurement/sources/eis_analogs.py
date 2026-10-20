"""Evidence-backed retrieval filters; never technical equivalence or competition forecasts."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.provenance import Provenance
from procurement.storage.eis_document_store import NoticeDocumentRef

T = TypeVar("T")
MAX_CANDIDATES = 20
MAX_POSITIONS = 25
MAX_NOTICE_PAYLOAD_BYTES = 256 * 1024
MAX_TOTAL_PAYLOAD_BYTES = 2 * 1024**2
MAX_OMISSION_INTEGER = 2**31 - 1
POLICY_VERSION: Literal["eis-analog-retrieval-v2"] = "eis-analog-retrieval-v2"
Dimension = Literal["SUBJECT", "VOLUME", "PERIOD", "HISTORY", "TECHNICAL", "DELIVERY_REGION"]
Status = Literal["PASS", "FAIL", "UNKNOWN"]


class AnalogModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AnalogFact(AnalogModel, Generic[T]):
    value: T | None
    provenance: Provenance

    @field_validator("value", mode="before")
    @classmethod
    def exact_scalar(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("ANALOG_INEXACT_SCALAR")
        return value

    @field_validator("value", mode="after")
    @classmethod
    def bounded_decimal(cls, value: Any) -> Any:
        if isinstance(value, Decimal) and (
            not value.is_finite()
            or len(value.as_tuple().digits) > 30
            or abs(int(value.as_tuple().exponent)) > 12
        ):
            raise ValueError("ANALOG_QUANTITY_LIMIT")
        return value


class AnalogPosition(AnalogModel):
    source_index: int = Field(ge=1, le=MAX_POSITIONS)
    name: AnalogFact[str]
    ktru: AnalogFact[str]
    okpd2: AnalogFact[str]
    quantity: AnalogFact[Decimal]
    unit: AnalogFact[str]


class AnalogNotice(AnalogModel):
    notice: NoticeDocumentRef
    document_type: str
    source_member: str
    published_at: AnalogFact[AwareDatetime]
    deadline: AnalogFact[AwareDatetime]
    positions: tuple[AnalogPosition, ...] = Field(max_length=MAX_POSITIONS)
    positions_total: int = Field(ge=0)
    lot_parse_status: Literal["PARSED", "UNKNOWN"]

    @model_validator(mode="after")
    def exact_evidence(self) -> AnalogNotice:
        facts: list[AnalogFact[Any]] = [self.published_at, self.deadline]
        for p in self.positions:
            facts.extend([p.name, p.ktru, p.okpd2, p.quantity, p.unit])
        if any(f.provenance.document_id != self.notice.notice_xml_sha256 for f in facts):
            raise ValueError("ANALOG_PROVENANCE_MISMATCH")
        if len(self.positions) > self.positions_total:
            raise ValueError("ANALOG_POSITION_COUNT_INVALID")
        return self


class AnalogRequest(AnalogModel):
    target: NoticeDocumentRef
    source_index: int = Field(ge=1, le=MAX_POSITIONS, strict=True)
    query: str = Field(min_length=1, max_length=120)
    lookback_days: int = Field(default=365, ge=1, le=730, strict=True)


class AnalogCriterion(AnalogModel):
    dimension: Dimension
    status: Status
    reason: str
    target_value: str | None
    candidate_value: str | None
    evidence: tuple[Provenance, ...]


class AnalogRow(AnalogModel):
    notice: NoticeDocumentRef
    source_index: int | None
    disposition: Literal["EXCLUDED", "NEEDS_REVIEW"]
    comparability: Literal["FAIL", "UNKNOWN"]
    criteria: tuple[AnalogCriterion, ...]


class AnalogCandidateOmission(AnalogModel):
    notice: NoticeDocumentRef
    reason: Literal["CANDIDATE_NOTICE_PAYLOAD_LIMIT", "CANDIDATE_TOTAL_PAYLOAD_LIMIT"]
    payload_bytes: int = Field(ge=0, le=MAX_OMISSION_INTEGER, strict=True)
    limit_bytes: int = Field(ge=0, le=MAX_TOTAL_PAYLOAD_BYTES, strict=True)
    measurement_source: Literal["SAVED_NOTICE_LOT_ITEMS_JSONB_OCTET_LENGTH"] = (
        "SAVED_NOTICE_LOT_ITEMS_JSONB_OCTET_LENGTH"
    )


class AnalogReport(AnalogModel):
    request: AnalogRequest
    checked_at: AwareDatetime
    policy_version: Literal["eis-analog-retrieval-v2"] = POLICY_VERSION
    scope: Literal["BOUNDED_SAVED_HISTORICAL_TOKEN_PREFILTER"] = (
        "BOUNDED_SAVED_HISTORICAL_TOKEN_PREFILTER"
    )
    target: AnalogNotice
    period_start: AwareDatetime | None
    period_end: AwareDatetime | None
    candidates: tuple[AnalogNotice, ...] = Field(max_length=MAX_CANDIDATES)
    omitted_candidates: tuple[AnalogCandidateOmission, ...] = Field(
        default=(), max_length=MAX_CANDIDATES
    )
    rows: tuple[AnalogRow, ...] = Field(max_length=MAX_CANDIDATES * MAX_POSITIONS)
    selected_notices: int
    evaluated_positions: int
    excluded_rows: int
    review_rows: int
    selection_truncated: bool
    uninspected_positions: int
    reasons: tuple[str, ...]
    source_requests: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    sample_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    lexical_recall: Literal["UNKNOWN"] = "UNKNOWN"
    source_freshness: Literal["UNKNOWN"] = "UNKNOWN"
    supplier_identity: Literal["UNKNOWN"] = "UNKNOWN"
    lot_association: Literal["UNKNOWN"] = "UNKNOWN"
    competition_prediction: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    profit: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def exact_candidate_partition(self) -> AnalogReport:
        candidate_numbers = {candidate.notice.purchase_number for candidate in self.candidates}
        omitted_numbers = {
            omission.notice.purchase_number for omission in self.omitted_candidates
        }
        if (
            len(candidate_numbers) != len(self.candidates)
            or len(omitted_numbers) != len(self.omitted_candidates)
            or candidate_numbers & omitted_numbers
            or self.request.target.purchase_number in candidate_numbers | omitted_numbers
            or len(candidate_numbers) + len(omitted_numbers) > MAX_CANDIDATES
        ):
            raise ValueError("ANALOG_CANDIDATE_PARTITION_INVALID")
        for omission in self.omitted_candidates:
            if omission.reason == "CANDIDATE_NOTICE_PAYLOAD_LIMIT":
                valid = (
                    1 <= omission.limit_bytes <= MAX_NOTICE_PAYLOAD_BYTES
                    and omission.payload_bytes > omission.limit_bytes
                )
            else:
                valid = (
                    omission.payload_bytes <= MAX_NOTICE_PAYLOAD_BYTES
                    and omission.payload_bytes > omission.limit_bytes
                )
            if not valid:
                raise ValueError("ANALOG_OMISSION_BOUND_INVALID")
        if self.selected_notices != len(self.candidates):
            raise ValueError("ANALOG_SELECTED_COUNT_INVALID")
        return self


def normalized_label(value: str | None) -> str:
    """Whole-label normalization, without fuzzy or semantic equivalence."""
    return " ".join((value or "").casefold().split())


def analog_period(target: AnalogNotice, request: AnalogRequest) -> tuple[datetime, datetime] | None:
    if target.published_at.value is None:
        return None
    end = target.published_at.value
    return end - timedelta(days=request.lookback_days), end


def assess_position(
    target: AnalogNotice,
    tp: AnalogPosition,
    candidate: AnalogNotice,
    cp: AnalogPosition | None,
    request: AnalogRequest,
    *,
    now: datetime,
) -> AnalogRow:
    """A failed retrieval dimension excludes the row; UNKNOWN remains reviewable."""
    checks: list[AnalogCriterion] = []

    def check(
        dimension: Dimension,
        status: Status,
        reason: str,
        left: object,
        right: object,
        facts: tuple[AnalogFact[Any], ...],
    ) -> None:
        evidence = [f.provenance for f in facts]
        # A missing candidate position still needs its actual document root.
        for document in (target, candidate):
            if not any(p.document_id == document.notice.notice_xml_sha256 for p in evidence):
                evidence.append(
                    Provenance(
                        document_id=document.notice.notice_xml_sha256,
                        locator=f"{document.source_member} :: {document.document_type}",
                        extractor=target.published_at.provenance.extractor,
                    )
                )
        checks.append(
            AnalogCriterion(
                dimension=dimension,
                status=status,
                reason=reason,
                target_value=str(left) if left is not None else None,
                candidate_value=str(right) if right is not None else None,
                evidence=tuple(evidence),
            )
        )

    if cp is None or target.lot_parse_status != "PARSED" or candidate.lot_parse_status != "PARSED":
        check("SUBJECT", "UNKNOWN", "POSITION_NOT_PARSED", None, None, (tp.name,))
    elif tp.ktru.value and cp.ktru.value:
        same = tp.ktru.value == cp.ktru.value
        check(
            "SUBJECT",
            "PASS" if same else "FAIL",
            "KTRU_EXACT" if same else "KTRU_CONFLICT",
            tp.ktru.value,
            cp.ktru.value,
            (tp.ktru, cp.ktru),
        )
    elif (
        tp.okpd2.value
        and cp.okpd2.value
        and normalized_label(tp.name.value)
        and normalized_label(cp.name.value)
    ):
        same = tp.okpd2.value == cp.okpd2.value and normalized_label(
            tp.name.value
        ) == normalized_label(cp.name.value)
        check(
            "SUBJECT",
            "PASS" if same else "FAIL",
            "OKPD2_NAME_EXACT" if same else "OKPD2_NAME_CONFLICT",
            f"{tp.okpd2.value}: {tp.name.value}",
            f"{cp.okpd2.value}: {cp.name.value}",
            (tp.okpd2, tp.name, cp.okpd2, cp.name),
        )
    else:
        check(
            "SUBJECT",
            "UNKNOWN",
            "CLASSIFICATION_OR_NAME_MISSING",
            tp.name.value,
            cp.name.value,
            (tp.name, tp.okpd2, cp.name, cp.okpd2),
        )

    left, right = tp.quantity.value, cp.quantity.value if cp else None
    facts = (tp.quantity, tp.unit) + ((cp.quantity, cp.unit) if cp else ())
    valid_quantities = all(
        v is not None
        and v.is_finite()
        and v > 0
        and len(v.as_tuple().digits) <= 30
        and abs(int(v.as_tuple().exponent)) <= 12
        for v in (left, right)
    )
    if (
        not valid_quantities
        or cp is None
        or not normalized_label(tp.unit.value)
        or not normalized_label(cp.unit.value)
    ):
        check("VOLUME", "UNKNOWN", "QUANTITY_OR_UNIT_MISSING_INVALID", left, right, facts)
    elif normalized_label(tp.unit.value) != normalized_label(cp.unit.value):
        check("VOLUME", "FAIL", "UNIT_LABEL_CONFLICT", tp.unit.value, cp.unit.value, facts)
    else:
        assert left is not None and right is not None
        with localcontext() as context:
            context.prec = 64
            fits = left * Decimal("0.5") <= right <= left * Decimal("2")
        check(
            "VOLUME",
            "PASS" if fits else "FAIL",
            "VOLUME_HALF_TO_DOUBLE" if fits else "VOLUME_OUTSIDE_RANGE",
            f"{left} {tp.unit.value}",
            f"{right} {cp.unit.value}",
            facts,
        )

    period = analog_period(target, request)
    date = candidate.published_at.value
    inside = period is not None and date is not None and period[0] <= date <= period[1]
    check(
        "PERIOD",
        "UNKNOWN" if period is None or date is None else "PASS" if inside else "FAIL",
        "PUBLICATION_MISSING"
        if period is None or date is None
        else "WITHIN_PERIOD"
        if inside
        else "OUTSIDE_PERIOD",
        target.published_at.value,
        date,
        (target.published_at, candidate.published_at),
    )
    deadline = candidate.deadline.value
    check(
        "HISTORY",
        "UNKNOWN" if deadline is None else "PASS" if deadline <= now else "FAIL",
        "DEADLINE_MISSING"
        if deadline is None
        else "DEADLINE_ELAPSED_ONLY"
        if deadline <= now
        else "DEADLINE_NOT_ELAPSED",
        now,
        deadline,
        (candidate.deadline,),
    )
    # Root evidence identifies the documents examined, not a fabricated field.
    roots = (tp.name,) + ((cp.name,) if cp else ())
    check("TECHNICAL", "UNKNOWN", "SPECIFICATION_NOT_REVIEWED", None, None, roots)
    check("DELIVERY_REGION", "UNKNOWN", "DELIVERY_REGION_NOT_EXTRACTED", None, None, roots)
    failed = any(c.status == "FAIL" for c in checks)
    return AnalogRow(
        notice=candidate.notice,
        source_index=cp.source_index if cp else None,
        disposition="EXCLUDED" if failed else "NEEDS_REVIEW",
        comparability="FAIL" if failed else "UNKNOWN",
        criteria=tuple(checks),
    )


def build_analog_report(
    request: AnalogRequest,
    target: AnalogNotice,
    candidates: tuple[AnalogNotice, ...],
    *,
    now: datetime,
    selection_truncated: bool,
    omitted_candidates: tuple[AnalogCandidateOmission, ...] = (),
) -> AnalogReport:
    if (
        now.utcoffset() is None
        or target.notice != request.target
        or len(candidates) > MAX_CANDIDATES
    ):
        raise ValueError("ANALOG_INPUT_MISMATCH")
    if len({c.notice.purchase_number for c in candidates}) != len(candidates) or any(
        c.notice.purchase_number == target.notice.purchase_number for c in candidates
    ):
        raise ValueError("ANALOG_DUPLICATE_OR_SELF")
    tp = next((p for p in target.positions if p.source_index == request.source_index), None)
    if tp is None:
        raise ValueError("ANALOG_TARGET_POSITION_NOT_FOUND")
    if target.published_at.value is not None and target.published_at.value > now:
        raise ValueError("ANALOG_TARGET_PUBLICATION_FUTURE")
    period = analog_period(target, request)
    rows = tuple(
        assess_position(target, tp, c, p, request, now=now)
        for c in candidates
        for p in (c.positions or (None,))
    )
    return AnalogReport(
        request=request,
        checked_at=now,
        target=target,
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        candidates=candidates,
        omitted_candidates=omitted_candidates,
        rows=rows,
        selected_notices=len(candidates),
        evaluated_positions=sum(len(c.positions) for c in candidates),
        excluded_rows=sum(r.disposition == "EXCLUDED" for r in rows),
        review_rows=sum(r.disposition == "NEEDS_REVIEW" for r in rows),
        selection_truncated=selection_truncated,
        uninspected_positions=sum(c.positions_total - len(c.positions) for c in candidates),
        reasons=(
            "TOKEN_OVERLAP_IS_NOT_EXACT_QUERY_MATCH",
            "LEXICAL_RECALL_UNKNOWN",
            "SAME_NOTICE_FAMILY_ONLY",
            "EXPIRED_DEADLINE_IS_NOT_COMPLETED_CONTRACT",
            "VOLUME_FILTER_IS_NOT_UNIT_OR_TECHNICAL_EQUIVALENCE",
        )
        + (("TARGET_PUBLICATION_MISSING",) if period is None else ()),
    )
