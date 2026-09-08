"""Синтетический вручную проверенный кейс для регрессий домена."""

from datetime import datetime
from pathlib import Path

from procurement.domain.cases import ProcurementCase, case_input_digest

AT = datetime.fromisoformat("2026-09-08T12:00:00+03:00")


def paper_case() -> ProcurementCase:
    path = Path(__file__).resolve().parents[1] / "examples" / "paper_case.json"
    return ProcurementCase.model_validate_json(path.read_text(encoding="utf-8"))


def reviewed(case: ProcurementCase) -> ProcurementCase:
    """Только тест: имитировать повторную ручную проверку изменённого снимка."""
    assert case.assessment is not None
    assessment = case.assessment.model_copy(update={"input_digest": case_input_digest(case)})
    return case.model_copy(update={"assessment": assessment})
