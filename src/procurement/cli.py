"""Локальная проверка вручную подготовленного кейса без внешних действий."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from procurement.domain.cases import ProcurementCase, case_input_digest, evaluate_case
from procurement.domain.decisions import Recommendation


class EvaluationRecord(BaseModel):
    """Снимок локального расчёта; идентичность actor не аутентифицируется CLI."""

    model_config = ConfigDict(frozen=True)

    engine_version: Literal["s1-v1"] = "s1-v1"
    evaluation_id: str
    company_id: str
    actor: str
    recorded_at: datetime
    effective_at: datetime
    input_sha256: str
    case: ProcurementCase
    recommendation: Recommendation


def _aware_time(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ожидается ISO datetime с часовым поясом") from exc
    if moment.utcoffset() is None:
        raise argparse.ArgumentTypeError("время должно содержать часовой пояс")
    return moment


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON содержит недопустимую константу {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON содержит повторяющийся ключ")
        result[key] = value
    return result


def _save_record(record: EvaluationRecord, directory: Path) -> Path:
    """Опубликовать полностью записанный файл, не перезаписывая существующий."""
    serialized = record.model_dump_json(indent=2)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{record.evaluation_id}.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        # link атомарно публикует полный файл и отказывает при существующей цели.
        os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    """Оценить JSON-кейс и сохранить новый файл аудита до вывода результата."""
    parser = argparse.ArgumentParser(description="Локальный расчёт закупочного кейса")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="проверить кейс из JSON")
    evaluate.add_argument("case_file", type=Path)
    evaluate.add_argument("--at", type=_aware_time, help="момент расчёта; по умолчанию сейчас")
    evaluate.add_argument("--actor", required=True, help="идентификатор локального оператора")
    evaluate.add_argument("--audit-dir", type=Path, default=Path("data/evaluations"))
    args = parser.parse_args(argv)

    try:
        if not args.actor.strip():
            raise ValueError("actor не может быть пустым")
        payload = json.loads(
            args.case_file.read_text(encoding="utf-8-sig"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
        case = ProcurementCase.model_validate(payload)
        at = args.at or datetime.now(UTC)
        result = evaluate_case(case, at=at)
        record = EvaluationRecord(
            evaluation_id=uuid4().hex,
            company_id=case.company_id,
            actor=args.actor,
            recorded_at=datetime.now(UTC),
            effective_at=at,
            input_sha256=case_input_digest(case),
            case=case,
            recommendation=result,
        )
        # Имя файла генерируется нами, а не из идентификаторов входного JSON.
        audit_path = _save_record(record, args.audit_dir)
        summary = {
            "evaluation_id": record.evaluation_id,
            "company_id": record.company_id,
            "input_sha256": record.input_sha256,
            "color": result.color,
            "recommendation": result.model_dump(mode="json"),
            "audit_path": str(audit_path.resolve()),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except ValidationError as exc:
        # Не выводить исходные клиентские значения и полный payload в сообщение ошибки.
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        print(json.dumps({"error": "invalid_case", "details": errors}), file=sys.stderr)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": "evaluation_failed", "message": str(exc)}), file=sys.stderr)
    return 2
