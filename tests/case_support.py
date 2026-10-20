"""Синтетический вручную проверенный кейс для регрессий домена."""

from datetime import date, datetime, timedelta
from pathlib import Path

from procurement.domain.cases import ProcurementCase, case_input_digest

AT = datetime.fromisoformat("2026-09-08T12:00:00+03:00")


def paper_case() -> ProcurementCase:
    path = Path(__file__).resolve().parents[1] / "examples" / "paper_case.json"
    return ProcurementCase.model_validate_json(path.read_text(encoding="utf-8"))


def paper_case_at(at: datetime) -> ProcurementCase:
    """Shift synthetic dates for wall-clock API tests; do not reapprove inputs.

    Fixed-time domain tests keep using paper_case()/AT. A changed input digest
    still requires the caller's explicit reviewed() step before a PASS.
    """
    if at.utcoffset() is None:
        raise ValueError("Synthetic case clock must be timezone-aware")
    delta = at - AT

    def shift(value: object) -> object:
        if isinstance(value, datetime):
            return value + delta
        if isinstance(value, date):
            return value + timedelta(days=delta.days)
        if isinstance(value, dict):
            return {key: shift(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shift(item) for item in value]
        if isinstance(value, tuple):
            return tuple(shift(item) for item in value)
        return value

    return ProcurementCase.model_validate(shift(paper_case().model_dump(mode="python")))


def reviewed(case: ProcurementCase) -> ProcurementCase:
    """Только тест: имитировать повторную ручную проверку изменённого снимка."""
    assert case.assessment is not None
    assessment = case.assessment.model_copy(update={"input_digest": case_input_digest(case)})
    return case.model_copy(update={"assessment": assessment})
