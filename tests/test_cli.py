"""Регрессии локального CLI: ошибки не публикуют audit, replay воспроизводим."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from procurement.cli import EvaluationRecord, main
from procurement.domain.cases import ProcurementCase, case_input_digest

PAPER_CASE = Path(__file__).parent.parent / "examples" / "paper_case.json"
EFFECTIVE_AT = "2026-09-08T12:00:00+03:00"


def _evaluate_args(case_file: Path, audit_dir: Path, *, at: str = EFFECTIVE_AT) -> list[str]:
    return [
        "evaluate",
        str(case_file),
        "--actor",
        "test-operator",
        "--at",
        at,
        "--audit-dir",
        str(audit_dir),
    ]


@pytest.mark.parametrize(
    "contents",
    (
        "{",
        '{"company_id":"first","company_id":"second"}',
        '{"company_id": NaN}',
    ),
)
def test_invalid_json_does_not_publish_an_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], contents: str
) -> None:
    case_file = tmp_path / "invalid.json"
    audit_dir = tmp_path / "audit"
    case_file.write_text(contents, encoding="utf-8")

    assert main(_evaluate_args(case_file, audit_dir)) == 2

    assert json.loads(capsys.readouterr().err)["error"] == "evaluation_failed"
    assert not audit_dir.exists() or not tuple(audit_dir.iterdir())


def test_naive_effective_time_is_rejected_by_argparse(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(_evaluate_args(PAPER_CASE, tmp_path / "audit", at="2026-01-15T12:00:00"))

    assert exc_info.value.code == 2
    assert not (tmp_path / "audit").exists()


def test_failed_audit_publication_leaves_no_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    audit_dir = tmp_path / "audit"

    def fail_link(source: Path, target: Path) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr("procurement.cli.os.link", fail_link)

    assert main(_evaluate_args(PAPER_CASE, audit_dir)) == 2

    assert json.loads(capsys.readouterr().err)["error"] == "evaluation_failed"
    assert not tuple(audit_dir.glob("*.json"))
    assert not tuple(audit_dir.glob("*.tmp"))


def test_valid_evaluation_persists_full_case_and_replays_deterministically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    audit_dir = tmp_path / "audit"
    expected_case = ProcurementCase.model_validate_json(PAPER_CASE.read_text(encoding="utf-8"))
    expected_at = datetime.fromisoformat(EFFECTIVE_AT)

    assert main(_evaluate_args(PAPER_CASE, audit_dir)) == 0
    first_summary = json.loads(capsys.readouterr().out)
    first_record = EvaluationRecord.model_validate_json(
        Path(first_summary["audit_path"]).read_text(encoding="utf-8")
    )

    assert first_record.case == expected_case
    assert first_record.effective_at == expected_at
    assert first_record.input_sha256 == case_input_digest(expected_case)
    assert first_record.recommendation.model_dump(mode="json") == first_summary["recommendation"]
    assert first_summary["color"] == "green"
    assert first_summary["recommendation"]["decision"] == "participate"

    assert main(_evaluate_args(PAPER_CASE, audit_dir)) == 0
    second_summary = json.loads(capsys.readouterr().out)

    assert second_summary["evaluation_id"] != first_summary["evaluation_id"]
    assert second_summary["recommendation"] == first_summary["recommendation"]


def test_expired_case_is_a_successful_red_evaluation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_evaluate_args(PAPER_CASE, tmp_path / "audit", at="2100-01-01T00:00:00+00:00")) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["color"] == "red"
    assert summary["recommendation"]["decision"] == "do_not_participate"
