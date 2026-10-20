"""Регрессии локального CLI: ошибки не публикуют audit, replay воспроизводим."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import procurement.cli as cli_module
from procurement.cli import EvaluationRecord, main
from procurement.documents.ai_transfer_worker import AiTransferBatchCoordinatorOutcome
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


def test_legacy_ai_transfer_command_is_disabled_before_reading_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_source = tmp_path / "must-not-be-read.docx"

    result = main(
        [
            "analyze-tz-ai",
            str(missing_source),
            "--company-id",
            "tenant-a",
            "--output",
            str(tmp_path / "report.json"),
            "--authorization-reference",
            "free-text-is-not-approval",
        ]
    )

    assert result == 2
    assert json.loads(capsys.readouterr().err) == {
        "error": "legacy_ai_transfer_disabled",
        "required_workflow": "persisted_exact_request_approval_execution",
    }


def test_approved_ai_transfer_dispatch_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AI_TRANSFER_LOCAL_PILOT_ENABLED", raising=False)

    result = main(
        [
            "dispatch-approved-ai-transfer",
            "--company-id",
            "tenant-a",
            "--execution-id",
            "execution-1",
            "--worker-id",
            "worker-1",
        ]
    )

    assert result == 2
    assert json.loads(capsys.readouterr().err) == {"error": "ai_transfer_local_pilot_disabled"}


@pytest.mark.parametrize(
    ("status", "reason", "materialization_id", "run_id", "expected_code"),
    [
        ("MATERIALIZED", "BATCH_MATERIALIZED", "batch-1", "run-1", 0),
        ("REJECTED", "SEMANTIC_REJECTION", "rejection-1", None, 4),
    ],
)
def test_local_pilot_dispatch_uses_one_bounded_coordinator_step(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    reason: str,
    materialization_id: str,
    run_id: str | None,
    expected_code: int,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class FakeCoordinator:
        def __init__(self, **_: object) -> None: ...

        def run_once(self, **_: object) -> AiTransferBatchCoordinatorOutcome:
            return AiTransferBatchCoordinatorOutcome(
                company_id="tenant-a",
                execution_id="execution-1",
                action="RECOVERY",
                status=status,
                network_attempted=False,
                claim_ordinal=2,
                materialization_id=materialization_id,
                run_id=run_id,
                reason=reason,
            )

    engine = FakeEngine()
    monkeypatch.setenv("AI_TRANSFER_LOCAL_PILOT_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://local-pilot")
    monkeypatch.setenv("OPENROUTER_API_KEY", "pilot-key")
    monkeypatch.setattr(cli_module, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(cli_module, "local_pilot_tenant_kek_provider_from_env", lambda: object())
    monkeypatch.setattr(cli_module, "PostgresStorage", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli_module, "ExactAiTransferHttpClient", lambda: object())
    monkeypatch.setattr(cli_module, "AiTransferBatchCoordinator", FakeCoordinator)

    result = main(
        [
            "dispatch-approved-ai-transfer",
            "--company-id",
            "tenant-a",
            "--execution-id",
            "execution-1",
            "--worker-id",
            "worker-1",
        ]
    )

    assert result == expected_code
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == status
    assert output["action"] == "RECOVERY"
    assert output["network_attempted"] is False
    assert "raw_response_body" not in output
    assert engine.disposed is True


def test_ai_transfer_materialization_recovery_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AI_TRANSFER_LOCAL_PILOT_ENABLED", raising=False)

    result = main(
        [
            "materialize-ai-transfer",
            "--company-id",
            "tenant-a",
            "--execution-id",
            "execution-1",
            "--worker-id",
            "worker-1",
        ]
    )

    assert result == 2
    assert json.loads(capsys.readouterr().err) == {"error": "ai_transfer_local_pilot_disabled"}


@pytest.mark.parametrize(
    ("chunk_count", "batch_outcome", "expected"),
    [
        (
            1,
            None,
            {
                "recovery_mode": "SINGLE_CHUNK",
                "status": "MATERIALIZED",
                "reason": "MATERIALIZED",
                "materialized_ordinals": [1],
                "materialization_id": "single-materialization",
                "run_id": "single-run",
                "run_evidence_sha256": "a" * 64,
            },
        ),
        (
            3,
            "PENDING",
            {
                "recovery_mode": "MULTI_CHUNK",
                "status": "PENDING",
                "reason": "BATCH_PENDING",
                "materialized_ordinals": [1, 2],
                "materialization_id": None,
                "run_id": None,
                "run_evidence_sha256": None,
            },
        ),
        (
            3,
            "MATERIALIZED",
            {
                "recovery_mode": "MULTI_CHUNK",
                "status": "MATERIALIZED",
                "reason": "MATERIALIZED",
                "materialized_ordinals": [1, 2, 3],
                "materialization_id": "batch-result",
                "run_id": "batch-run",
                "run_evidence_sha256": "b" * 64,
            },
        ),
        (
            3,
            "REJECTED",
            {
                "recovery_mode": "MULTI_CHUNK",
                "status": "REJECTED",
                "reason": "INVALID_CANDIDATE_EVIDENCE",
                "materialized_ordinals": [1],
                "materialization_id": "chunk-rejection",
                "run_id": None,
                "run_evidence_sha256": None,
            },
        ),
    ],
)
def test_materialization_cli_routes_single_and_multi_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    chunk_count: int,
    batch_outcome: str | None,
    expected: dict[str, object],
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class FakeBatchSnapshot:
        def __init__(self) -> None:
            self.result = SimpleNamespace(batch_result_id="batch-result")
            self.run_id = "batch-run"
            self.evidence_sha256 = "b" * 64

    class FakeStorage:
        single_calls = 0
        batch_calls = 0

        def __init__(self, *_: object, **__: object) -> None: ...

        def get_ai_transfer_execution(self, company_id: str, execution_id: str):
            return (
                SimpleNamespace(
                    company_id=company_id,
                    execution_id=execution_id,
                    chunk_count=chunk_count,
                ),
                None,
                None,
            )

        def materialize_ai_transfer_requirement_run(self, *_: object):
            self.single_calls += 1
            return (
                SimpleNamespace(
                    status="MATERIALIZED",
                    reason="MATERIALIZED",
                    materialization_id="single-materialization",
                    run_id="single-run",
                    run_evidence_sha256="a" * 64,
                ),
                object(),
            )

        def materialize_ai_transfer_requirement_batch(self, *_: object):
            self.batch_calls += 1
            count = 2 if batch_outcome in {"PENDING", "REJECTED"} else 3
            results = tuple(SimpleNamespace(ordinal=index) for index in range(1, count + 1))
            if batch_outcome == "REJECTED":
                return (
                    results[:1],
                    None,
                    SimpleNamespace(
                        reason="INVALID_CANDIDATE_EVIDENCE",
                        rejection_id="chunk-rejection",
                    ),
                )
            if batch_outcome == "MATERIALIZED":
                snapshot = FakeBatchSnapshot()
                return results, SimpleNamespace(snapshot=snapshot), None
            return results, None, None

    engine = FakeEngine()
    storage = FakeStorage()
    monkeypatch.setenv("AI_TRANSFER_LOCAL_PILOT_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://local-pilot")
    monkeypatch.setattr(cli_module, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(cli_module, "local_pilot_tenant_kek_provider_from_env", lambda: object())
    monkeypatch.setattr(cli_module, "PostgresStorage", lambda *args, **kwargs: storage)
    monkeypatch.setattr(cli_module, "AiRequirementTransferBatchRunSnapshot", FakeBatchSnapshot)

    result = main(
        [
            "materialize-ai-transfer",
            "--company-id",
            "tenant-a",
            "--execution-id",
            "execution-1",
            "--worker-id",
            "recovery-worker",
        ]
    )

    assert result == (4 if batch_outcome == "REJECTED" else 0)
    output = json.loads(capsys.readouterr().out)
    assert {key: output[key] for key in expected} == expected
    assert storage.single_calls == (1 if chunk_count == 1 else 0)
    assert storage.batch_calls == (0 if chunk_count == 1 else 1)
    assert engine.disposed is True
