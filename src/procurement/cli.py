"""CLI проекта; внешняя передача разрешена только явно названной AI-командой."""

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
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from procurement.documents.ai_requirement_review import AiRequirementTransferBatchRunSnapshot
from procurement.documents.ai_requirements import (
    DEFAULT_CHUNK_CHARACTERS,
    DEFAULT_OPENROUTER_MODEL,
)
from procurement.documents.ai_transfer_keys import local_pilot_tenant_kek_provider_from_env
from procurement.documents.ai_transfer_transport import ExactAiTransferHttpClient
from procurement.documents.ai_transfer_worker import AiTransferBatchCoordinator
from procurement.documents.bundle import (
    DocumentBundleRejected,
    extract_document_bundle_path,
    publish_document_bundle_result,
)
from procurement.documents.document_search import (
    build_document_search_entry,
    load_vision_search_tag_manifest,
    read_document_input,
    search_documents,
)
from procurement.documents.docx_media import (
    DocxMediaRejected,
    ocr_docx_media_path,
    publish_docx_media_ocr_report,
)
from procurement.documents.docx_media_calibration import (
    DocxMediaCalibrationError,
    DocxMediaCalibrationRunReport,
    publish_docx_media_calibration_report,
    run_docx_media_calibration_review,
)
from procurement.documents.extraction import (
    DocumentRejected,
    ExtractionStatus,
    extract_document,
)
from procurement.documents.model_brand import load_model_brand_catalog
from procurement.documents.ocr import (
    DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    OcrEngineError,
    OcrSourceRejected,
)
from procurement.documents.ocr_calibration_run import (
    CalibrationRunError,
    OcrCalibrationRunReport,
    publish_ocr_calibration_report,
    run_ocr_calibration_manifest,
)
from procurement.documents.ocr_labeling import (
    LabelingError,
    OcrLabelingDraft,
    finalize_ocr_labeling_draft,
    prepare_ocr_labeling_draft,
    publish_labeling_artifact,
)
from procurement.documents.ocr_routing import (
    LocalOcrDisposition,
    VisionEscalationConfig,
    load_docx_media_calibration_report,
    publish_docx_media_ocr_routing,
    route_docx_media_ocr,
)
from procurement.domain.cases import ProcurementCase, case_input_digest, evaluate_case
from procurement.domain.decisions import Recommendation
from procurement.storage import PostgresStorage, StorageError

AI_TRANSFER_LOCAL_PILOT_ENABLED_ENV = "AI_TRANSFER_LOCAL_PILOT_ENABLED"


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
    """Запустить типизированную операцию; юридически значимых действий здесь нет."""
    parser = argparse.ArgumentParser(description="Локальные инструменты Syurai Procurement")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="проверить кейс из JSON")
    evaluate.add_argument("case_file", type=Path)
    evaluate.add_argument("--at", type=_aware_time, help="момент расчёта; по умолчанию сейчас")
    evaluate.add_argument("--actor", required=True, help="идентификатор локального оператора")
    evaluate.add_argument("--audit-dir", type=Path, default=Path("data/evaluations"))
    calibrate = commands.add_parser(
        "calibrate-ocr",
        help="локально проверить размеченный manifest и записать OCR-отчёт",
    )
    calibrate.add_argument("manifest_file", type=Path)
    calibrate.add_argument("--output", type=Path, required=True)
    prepare_labeling = commands.add_parser(
        "prepare-ocr-labeling",
        help="создать неподтверждённый draft ручной OCR-разметки",
    )
    prepare_labeling.add_argument("dataset_directory", type=Path)
    prepare_labeling.add_argument("--dataset-id", required=True)
    prepare_labeling.add_argument("--authorization-reference", required=True)
    prepare_labeling.add_argument("--output", type=Path, required=True)
    finalize_labeling = commands.add_parser(
        "finalize-ocr-labeling",
        help="проверить ручное подтверждение и создать calibration manifest",
    )
    finalize_labeling.add_argument("draft_file", type=Path)
    finalize_labeling.add_argument("--output", type=Path, required=True)
    inspect_bundle = commands.add_parser(
        "inspect-document-bundle",
        help="безопасно раскрыть ZIP с PDF/DOCX/XLSX в локальный JSON-отчёт",
    )
    inspect_bundle.add_argument("bundle_file", type=Path)
    inspect_bundle.add_argument("--output", type=Path, required=True)
    docx_media = commands.add_parser(
        "ocr-docx-media",
        help="локально распознать связанные PNG/JPEG внутри DOCX",
    )
    docx_media.add_argument("document_file", type=Path)
    docx_media.add_argument("--output", type=Path, required=True)
    docx_media.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    )
    calibrate_docx_media = commands.add_parser(
        "calibrate-docx-media-review",
        help="проверить визуальную разметку DOCX-media без обхода human gate",
    )
    calibrate_docx_media.add_argument("review_file", type=Path)
    calibrate_docx_media.add_argument("--output", type=Path, required=True)
    route_docx_media = commands.add_parser(
        "route-docx-media-ocr",
        help="отклонить небезопасный local OCR или подготовить vision approval draft",
    )
    route_docx_media.add_argument("calibration_report", type=Path)
    route_docx_media.add_argument("--output", type=Path, required=True)
    route_docx_media.add_argument("--at", type=_aware_time)
    route_docx_media.add_argument("--vision-provider")
    route_docx_media.add_argument("--vision-model")
    route_docx_media.add_argument("--vision-endpoint")
    route_docx_media.add_argument("--retention-policy-reference")
    search_document = commands.add_parser(
        "search-document",
        help="найти запрос в имени, нативном тексте и отдельных vision-тегах",
    )
    search_document.add_argument("document_file", type=Path)
    search_document.add_argument("--company-id", required=True)
    search_document.add_argument("--query", required=True)
    search_document.add_argument("--title")
    search_document.add_argument("--document-id")
    search_document.add_argument("--vision-tags", type=Path)
    search_document.add_argument("--model-brand-catalog", type=Path)
    search_document.add_argument("--at", type=_aware_time)
    analyze_tz = commands.add_parser(
        "analyze-tz-ai",
        help="устаревшая небезопасная команда; внешний вызов отключён",
    )
    analyze_tz.add_argument("document_file", type=Path)
    analyze_tz.add_argument("--company-id", required=True)
    analyze_tz.add_argument("--output", type=Path, required=True)
    analyze_tz.add_argument("--model", default=DEFAULT_OPENROUTER_MODEL)
    analyze_tz.add_argument("--authorization-reference", required=True)
    analyze_tz.add_argument(
        "--allow-env-proxy",
        action="store_true",
        help="явно разрешить HTTPS_PROXY/ALL_PROXY для этого внешнего вызова",
    )
    analyze_tz.add_argument(
        "--max-chunk-characters",
        type=int,
        default=DEFAULT_CHUNK_CHARACTERS,
    )
    dispatch_ai = commands.add_parser(
        "dispatch-approved-ai-transfer",
        help="продвинуть approved AI transfer не более чем на один chunk в local pilot",
    )
    dispatch_ai.add_argument("--company-id", required=True)
    dispatch_ai.add_argument("--execution-id", required=True)
    dispatch_ai.add_argument("--worker-id", required=True)
    materialize_ai = commands.add_parser(
        "materialize-ai-transfer",
        help="recover a raw-free review result from a durable local-pilot transfer",
    )
    materialize_ai.add_argument("--company-id", required=True)
    materialize_ai.add_argument("--execution-id", required=True)
    materialize_ai.add_argument("--worker-id", required=True)
    args = parser.parse_args(argv)

    if args.command == "calibrate-ocr":
        return _run_ocr_calibration(args.manifest_file, args.output)
    if args.command == "prepare-ocr-labeling":
        return _prepare_ocr_labeling(
            args.dataset_directory,
            dataset_id=args.dataset_id,
            authorization_reference=args.authorization_reference,
            output=args.output,
        )
    if args.command == "finalize-ocr-labeling":
        return _finalize_ocr_labeling(args.draft_file, args.output)
    if args.command == "inspect-document-bundle":
        return _inspect_document_bundle(args.bundle_file, args.output)
    if args.command == "ocr-docx-media":
        return _ocr_docx_media(args.document_file, args.output, threshold=args.threshold)
    if args.command == "calibrate-docx-media-review":
        return _calibrate_docx_media_review(args.review_file, args.output)
    if args.command == "route-docx-media-ocr":
        return _route_docx_media_ocr(
            args.calibration_report,
            args.output,
            at=args.at or datetime.now(UTC),
            vision_provider=args.vision_provider,
            vision_model=args.vision_model,
            vision_endpoint=args.vision_endpoint,
            retention_policy_reference=args.retention_policy_reference,
        )
    if args.command == "search-document":
        return _search_document(
            args.document_file,
            company_id=args.company_id,
            query=args.query,
            title=args.title,
            document_id=args.document_id,
            vision_tags=args.vision_tags,
            model_brand_catalog=args.model_brand_catalog,
            at=args.at or datetime.now(UTC),
        )
    if args.command == "analyze-tz-ai":
        return _analyze_tz_ai(
            args.document_file,
            company_id=args.company_id,
            output=args.output,
            model=args.model,
            authorization_reference=args.authorization_reference,
            allow_env_proxy=args.allow_env_proxy,
            max_chunk_characters=args.max_chunk_characters,
        )
    if args.command == "dispatch-approved-ai-transfer":
        return _dispatch_approved_ai_transfer(
            company_id=args.company_id,
            execution_id=args.execution_id,
            worker_id=args.worker_id,
        )
    if args.command == "materialize-ai-transfer":
        return _materialize_ai_transfer(
            company_id=args.company_id,
            execution_id=args.execution_id,
            worker_id=args.worker_id,
        )
    return _run_evaluation(args)


def _dispatch_approved_ai_transfer(
    *,
    company_id: str,
    execution_id: str,
    worker_id: str,
) -> int:
    """Run the local-pilot exact approval boundary without exposing secrets or raw bytes."""
    if os.environ.get(AI_TRANSFER_LOCAL_PILOT_ENABLED_ENV) != "1":
        print(json.dumps({"error": "ai_transfer_local_pilot_disabled"}), file=sys.stderr)
        return 2
    database_url = os.environ.get("DATABASE_URL", "")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    try:
        key_provider = local_pilot_tenant_kek_provider_from_env()
    except RuntimeError:
        key_provider = None
    if not database_url or not api_key or api_key != api_key.strip() or key_provider is None:
        print(json.dumps({"error": "ai_transfer_local_pilot_not_ready"}), file=sys.stderr)
        return 2

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        storage = PostgresStorage(engine, raw_key_provider=key_provider)
        outcome = AiTransferBatchCoordinator(
            storage=storage,
            client=ExactAiTransferHttpClient(),
        ).run_once(
            company_id=company_id,
            worker_id=worker_id,
            execution_id=execution_id,
            api_key=api_key,
        )
    except (StorageError, SQLAlchemyError, TypeError, ValueError, RuntimeError):
        print(json.dumps({"error": "ai_transfer_dispatch_failed"}), file=sys.stderr)
        return 2
    finally:
        engine.dispose()

    print(
        json.dumps(
            {
                "company_id": outcome.company_id,
                "execution_id": outcome.execution_id,
                "action": outcome.action,
                "status": outcome.status,
                "reason": outcome.reason,
                "network_attempted": outcome.network_attempted,
                "claim_ordinal": outcome.claim_ordinal,
                "materialization_id": outcome.materialization_id,
                "run_id": outcome.run_id,
                "claim_id": (
                    None
                    if outcome.worker_outcome is None
                    else outcome.worker_outcome.claim.claim_id
                ),
                "receipt_id": (
                    None
                    if outcome.worker_outcome is None
                    else outcome.worker_outcome.receipt.receipt_id
                ),
                "raw_response_id": (
                    None
                    if outcome.worker_outcome is None
                    else outcome.worker_outcome.raw_response_id
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if outcome.status in {"PENDING", "MATERIALIZED"}:
        return 0
    if (
        outcome.worker_outcome is not None
        and outcome.worker_outcome.receipt.outcome == "DELIVERY_UNKNOWN"
    ):
        return 3
    return 4


def _materialize_ai_transfer(
    *,
    company_id: str,
    execution_id: str,
    worker_id: str,
) -> int:
    """Recover only a previously durable capture; this command never reaches a provider."""
    if os.environ.get(AI_TRANSFER_LOCAL_PILOT_ENABLED_ENV) != "1":
        print(json.dumps({"error": "ai_transfer_local_pilot_disabled"}), file=sys.stderr)
        return 2
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        key_provider = local_pilot_tenant_kek_provider_from_env()
    except RuntimeError:
        key_provider = None
    if not database_url or key_provider is None:
        print(json.dumps({"error": "ai_transfer_local_pilot_not_ready"}), file=sys.stderr)
        return 2
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        storage = PostgresStorage(engine, raw_key_provider=key_provider)
        execution = storage.get_ai_transfer_execution(company_id, execution_id)
        if execution is None:
            raise ValueError("AI transfer execution is unavailable")
        admission = execution[0]
        if (
            admission.company_id != company_id
            or admission.execution_id != execution_id
            or admission.chunk_count < 1
        ):
            raise ValueError("AI transfer execution identity differs")
        status: Literal["PENDING", "MATERIALIZED", "REJECTED"]
        reason: str
        if admission.chunk_count == 1:
            materialization, _ = storage.materialize_ai_transfer_requirement_run(
                company_id, worker_id, execution_id
            )
            status = materialization.status
            reason = materialization.reason
            materialization_id = materialization.materialization_id
            run_id = materialization.run_id
            run_evidence_sha256 = materialization.run_evidence_sha256
            materialized_ordinals = [1]
            recovery_mode = "SINGLE_CHUNK"
        else:
            results, record, rejection = storage.materialize_ai_transfer_requirement_batch(
                company_id, worker_id, execution_id
            )
            materialized_ordinals = [result.ordinal for result in results]
            recovery_mode = "MULTI_CHUNK"
            if rejection is not None:
                status = "REJECTED"
                reason = rejection.reason
                materialization_id = rejection.rejection_id
                run_id = None
                run_evidence_sha256 = None
            elif record is not None:
                if not isinstance(record.snapshot, AiRequirementTransferBatchRunSnapshot):
                    raise ValueError("AI transfer batch recovery returned another run type")
                status = "MATERIALIZED"
                reason = "MATERIALIZED"
                materialization_id = record.snapshot.result.batch_result_id
                run_id = record.snapshot.run_id
                run_evidence_sha256 = record.snapshot.evidence_sha256
            else:
                status = "PENDING"
                reason = "BATCH_PENDING"
                materialization_id = None
                run_id = None
                run_evidence_sha256 = None
    except (StorageError, SQLAlchemyError, TypeError, ValueError, RuntimeError):
        print(json.dumps({"error": "ai_transfer_materialization_failed"}), file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "company_id": company_id,
                "execution_id": execution_id,
                "recovery_mode": recovery_mode,
                "status": status,
                "reason": reason,
                "materialized_ordinals": materialized_ordinals,
                "materialization_id": materialization_id,
                "run_id": run_id,
                "run_evidence_sha256": run_evidence_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if status in {"PENDING", "MATERIALIZED"}:
        return 0
    return 4


def _analyze_tz_ai(
    document_file: Path,
    *,
    company_id: str,
    output: Path,
    model: str,
    authorization_reference: str,
    allow_env_proxy: bool,
    max_chunk_characters: int,
) -> int:
    """Refuse the legacy free-text authorization path before reading source bytes."""
    del (
        document_file,
        company_id,
        output,
        model,
        authorization_reference,
        allow_env_proxy,
        max_chunk_characters,
    )
    print(
        json.dumps(
            {
                "error": "legacy_ai_transfer_disabled",
                "required_workflow": "persisted_exact_request_approval_execution",
            }
        ),
        file=sys.stderr,
    )
    return 2


def _run_evaluation(args: argparse.Namespace) -> int:
    """Оценить JSON-кейс и сохранить новый файл аудита до вывода результата."""
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


def _run_ocr_calibration(manifest_file: Path, output: Path) -> int:
    """Записать отчёт при любом доменном статусе; exit code остаётся fail-closed."""
    try:
        report = run_ocr_calibration_manifest(manifest_file)
        report_path = publish_ocr_calibration_report(report, output)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        print(
            json.dumps({"error": "invalid_calibration_manifest", "details": errors}),
            file=sys.stderr,
        )
        return 2
    except CalibrationRunError as exc:
        print(
            json.dumps({"error": "calibration_failed", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(json.dumps({"error": "calibration_report_not_published"}), file=sys.stderr)
        return 2

    print(json.dumps(_calibration_summary(report, report_path), ensure_ascii=False, indent=2))
    if report.calibration.status is ExtractionStatus.PASS:
        return 0
    if report.calibration.status is ExtractionStatus.UNKNOWN:
        return 3
    return 4


def _calibration_summary(report: OcrCalibrationRunReport, path: Path) -> dict[str, object]:
    """Не печатать в терминал размеченный или распознанный текст документов."""
    calibration = report.calibration
    return {
        "dataset_id": report.dataset_id,
        "manifest_sha256": report.manifest_sha256,
        "engine": calibration.engine,
        "status": calibration.status,
        "reason": calibration.reason,
        "recommended_threshold": calibration.recommended_threshold,
        "samples_total": calibration.samples_total,
        "expected_lines_total": calibration.expected_lines_total,
        "report_path": str(path),
    }


def _prepare_ocr_labeling(
    dataset_directory: Path,
    *,
    dataset_id: str,
    authorization_reference: str,
    output: Path,
) -> int:
    """Создать draft с OCR-подсказками, но без автоматического эталона."""
    try:
        draft = prepare_ocr_labeling_draft(
            dataset_directory,
            dataset_id=dataset_id,
            authorization_reference=authorization_reference,
        )
        output_path = publish_labeling_artifact(draft, output, root=dataset_directory)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        print(json.dumps({"error": "invalid_labeling_draft", "details": errors}), file=sys.stderr)
        return 2
    except LabelingError as exc:
        print(
            json.dumps({"error": "labeling_preparation_failed", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(json.dumps({"error": "labeling_draft_not_published"}), file=sys.stderr)
        return 2
    print(json.dumps(_labeling_summary(draft, output_path), ensure_ascii=False, indent=2))
    return 0


def _finalize_ocr_labeling(draft_file: Path, output: Path) -> int:
    """Опубликовать manifest только после полного человеческого review."""
    try:
        manifest = finalize_ocr_labeling_draft(draft_file)
        output_path = publish_labeling_artifact(manifest, output, root=draft_file.parent)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        print(json.dumps({"error": "invalid_labeling_draft", "details": errors}), file=sys.stderr)
        return 2
    except LabelingError as exc:
        print(
            json.dumps({"error": "labeling_finalization_failed", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(json.dumps({"error": "calibration_manifest_not_published"}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "dataset_id": manifest.dataset_id,
                "status": ExtractionStatus.UNKNOWN,
                "reason": "CALIBRATION_NOT_RUN",
                "review_status": "CONFIRMED",
                "samples_total": len(manifest.samples),
                "expected_lines_total": sum(len(item.expected) for item in manifest.samples),
                "labeling_draft_sha256": manifest.labeling_draft_sha256,
                "manifest_path": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _labeling_summary(draft: OcrLabelingDraft, path: Path) -> dict[str, object]:
    """Не выводить подсказки OCR и ручной текст в терминал."""
    return {
        "dataset_id": draft.dataset_id,
        "engine": draft.engine,
        "status": ExtractionStatus.UNKNOWN,
        "reason": "HUMAN_REVIEW_REQUIRED",
        "samples_total": len(draft.samples),
        "suggestions_total": sum(len(item.suggestions) for item in draft.samples),
        "expected_lines_total": sum(len(item.expected) for item in draft.samples),
        "draft_path": str(path),
    }


def _inspect_document_bundle(bundle_file: Path, output: Path) -> int:
    """Сохранить полный отчёт локально, а в консоль вывести только агрегаты."""
    try:
        result = extract_document_bundle_path(bundle_file)
        output_path = publish_document_bundle_result(result, output)
    except DocumentBundleRejected as exc:
        print(
            json.dumps({"error": "document_bundle_rejected", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(json.dumps({"error": "document_bundle_report_not_published"}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "source_document_id": result.source_document_id,
                "source_sha256": result.source_sha256,
                "status": result.status,
                "reasons": result.reasons,
                "members_total": result.members_total,
                "supported_members": result.supported_members,
                "unsupported_members": result.unsupported_members,
                "report_path": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result.status is ExtractionStatus.PASS:
        return 0
    if result.status is ExtractionStatus.UNKNOWN:
        return 3
    return 4


def _ocr_docx_media(document_file: Path, output: Path, *, threshold: float) -> int:
    """Сохранить полный OCR-отчёт, не печатая распознанный текст в терминал."""
    try:
        report = ocr_docx_media_path(document_file, threshold=threshold)
        output_path = publish_docx_media_ocr_report(report, output)
    except DocxMediaRejected as exc:
        print(
            json.dumps({"error": "docx_media_rejected", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except DocumentRejected as exc:
        print(
            json.dumps({"error": "document_rejected", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except OcrSourceRejected:
        print(json.dumps({"error": "ocr_source_unsupported"}), file=sys.stderr)
        return 2
    except OcrEngineError:
        print(json.dumps({"error": "ocr_unavailable"}), file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print(json.dumps({"error": "docx_media_report_not_published"}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "source_document_id": report.extraction.source_document_id,
                "source_sha256": report.extraction.source_sha256,
                "status": report.status,
                "media_total": len(report.extraction.media),
                "issues": [item.code for item in report.extraction.issues],
                "ocr_pass": sum(
                    item.ocr.status is ExtractionStatus.PASS for item in report.results
                ),
                "ocr_unknown": sum(
                    item.ocr.status is ExtractionStatus.UNKNOWN for item in report.results
                ),
                "report_path": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.status is ExtractionStatus.PASS else 3


def _calibrate_docx_media_review(review_file: Path, output: Path) -> int:
    """Publish metrics while keeping AI review behind an explicit UNKNOWN gate."""
    try:
        report = run_docx_media_calibration_review(review_file)
        output_path = publish_docx_media_calibration_report(report, output)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        print(
            json.dumps({"error": "invalid_docx_media_review", "details": errors}),
            file=sys.stderr,
        )
        return 2
    except DocxMediaCalibrationError as exc:
        print(
            json.dumps({"error": "docx_media_calibration_failed", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(json.dumps({"error": "docx_media_calibration_not_published"}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            _docx_media_calibration_summary(report, output_path),
            ensure_ascii=False,
            indent=2,
        )
    )
    if report.status is ExtractionStatus.PASS:
        return 0
    if report.status is ExtractionStatus.UNKNOWN:
        return 3
    return 4


def _docx_media_calibration_summary(
    report: DocxMediaCalibrationRunReport,
    path: Path,
) -> dict[str, object]:
    """Keep visual labels and OCR text out of terminal output."""
    return {
        "review_sha256": report.review_sha256,
        "review_status": report.review_status,
        "status": report.status,
        "gate_reason": report.gate_reason,
        "engine": report.calibration.engine,
        "expected_lines_total": report.calibration.expected_lines_total,
        "observed_candidate_threshold": report.calibration.recommended_threshold,
        "production_recommended_threshold": report.production_recommended_threshold,
        "report_path": str(path),
    }


def _route_docx_media_ocr(
    calibration_report: Path,
    output: Path,
    *,
    at: datetime,
    vision_provider: str | None,
    vision_model: str | None,
    vision_endpoint: str | None,
    retention_policy_reference: str | None,
) -> int:
    """Publish method routing without transmitting document bytes."""
    vision_values = (
        vision_provider,
        vision_model,
        vision_endpoint,
        retention_policy_reference,
    )
    if any(value is not None for value in vision_values) and not all(
        value is not None for value in vision_values
    ):
        print(
            json.dumps({"error": "incomplete_vision_configuration"}),
            file=sys.stderr,
        )
        return 2
    try:
        report, report_sha256 = load_docx_media_calibration_report(calibration_report)
        vision = (
            VisionEscalationConfig(
                provider=vision_provider,
                model=vision_model,
                endpoint=vision_endpoint,
                retention_policy_reference=retention_policy_reference,
            )
            if all(value is not None for value in vision_values)
            else None
        )
        decision = route_docx_media_ocr(
            report,
            source_report_sha256=report_sha256,
            created_at=at,
            vision=vision,
        )
        output_path = publish_docx_media_ocr_routing(decision, output)
    except (OSError, ValueError, ValidationError):
        print(json.dumps({"error": "docx_media_routing_failed"}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "source_calibration_report_sha256": report_sha256,
                "document_status": decision.document_status,
                "disposition": decision.disposition,
                "reason": decision.reason,
                "next_actions": decision.next_actions,
                "vision_draft_status": (
                    decision.vision_escalation.status
                    if decision.vision_escalation is not None
                    else None
                ),
                "vision_payload_sha256": (
                    decision.vision_escalation.payload_sha256
                    if decision.vision_escalation is not None
                    else None
                ),
                "report_path": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if decision.disposition is LocalOcrDisposition.USE_LOCAL_OCR else 3


def _search_document(
    document_file: Path,
    *,
    company_id: str,
    query: str,
    title: str | None,
    document_id: str | None,
    vision_tags: Path | None,
    model_brand_catalog: Path | None,
    at: datetime,
) -> int:
    """Search one local document without uploading or persisting its contents."""
    try:
        document = read_document_input(document_file, document_id=document_id)
        extraction = extract_document(document)
        manifest = load_vision_search_tag_manifest(vision_tags) if vision_tags is not None else None
        catalog = (
            load_model_brand_catalog(model_brand_catalog)
            if model_brand_catalog is not None
            else None
        )
        entry = build_document_search_entry(
            document,
            extraction,
            company_id=company_id,
            title=title,
            vision_manifest=manifest,
        )
        results = search_documents(
            (entry,),
            company_id=company_id,
            query=query,
            model_brand_catalog=catalog,
            at=at if catalog is not None else None,
        )
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        print(
            json.dumps({"error": "invalid_search_evidence", "details": errors}),
            file=sys.stderr,
        )
        return 2
    except DocumentRejected as exc:
        print(
            json.dumps({"error": "document_rejected", "code": exc.code.value}),
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError):
        print(json.dumps({"error": "document_search_failed"}), file=sys.stderr)
        return 2

    result = results[0] if results else None
    print(
        json.dumps(
            {
                "company_id": entry.company_id,
                "document_id": entry.document_id,
                "source_sha256": entry.source_sha256,
                "extraction_status": entry.extraction_status,
                "extraction_reasons": entry.extraction_reasons,
                "query": query,
                "effective_at": at.isoformat(),
                "search_status": result.status if result is not None else ExtractionStatus.FAIL,
                "hits": (
                    [
                        {
                            "source_kind": hit.source_kind,
                            "matched_text": hit.matched_text,
                            "provenance": hit.provenance.model_dump(mode="json"),
                            "status": hit.status,
                            "vision_review_status": hit.vision_review_status,
                            "vision_evidence": (
                                hit.vision_evidence.model_dump(mode="json")
                                if hit.vision_evidence is not None
                                else None
                            ),
                            "model_brand_evidence": (
                                hit.model_brand_evidence.model_dump(mode="json")
                                if hit.model_brand_evidence is not None
                                else None
                            ),
                        }
                        for hit in result.hits
                    ]
                    if result is not None
                    else []
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result is not None else 4
