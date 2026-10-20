"""Run a local, fail-closed requirements-understanding pilot over tender files.

The generated report is evidence for execution coverage only. Semantic quality
metrics stay UNKNOWN until a human ground-truth file is supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from procurement.documents import (
    COMPLETENESS_MAPPER_VERSION,
    DEFAULT_FACT_MIN_CONFIDENCE,
    DocumentBundleRejected,
    DocumentRejected,
    DocumentRole,
    FactMappingResult,
    build_completeness_review_snapshot,
    extract_document,
    extract_document_bundle_path,
    map_blocks_to_requirements,
    read_document_input,
)

DIRECT_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx"})
SOURCE_EXTENSIONS = DIRECT_EXTENSIONS | {".zip", ".doc", ".rar"}
UNSUPPORTED_REASONS = {
    ".doc": "LEGACY_DOC_UNSUPPORTED",
    ".rar": "RAR_UNSUPPORTED",
}
IMPLEMENTATION_FILES = (
    "scripts/run-tz-understanding-pilot.py",
    "src/procurement/documents/extraction.py",
    "src/procurement/documents/bundle.py",
    "src/procurement/documents/facts.py",
    "src/procurement/documents/completeness_review.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_state(root: Path) -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": dirty}


def _implementation_evidence(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": relative_path,
            "sha256": _sha256(root / relative_path),
        }
        for relative_path in IMPLEMENTATION_FILES
    ]


def _mapping_payload(mapping: FactMappingResult) -> dict[str, object]:
    dumped = mapping.model_dump(mode="json")
    requirements = dumped["requirements"]
    unmapped = dumped["unmapped"]
    return {
        "document_role": dumped["document_role"],
        "blocks_total": dumped["blocks_total"],
        "blocks_mapped": dumped["blocks_mapped"],
        "technical_block_coverage": (
            dumped["blocks_mapped"] / dumped["blocks_total"]
            if dumped["blocks_total"]
            else None
        ),
        "requirements_count": len(requirements),
        "unmapped_count": len(unmapped),
        "requirements": requirements,
        "unmapped": unmapped,
        "equivalent_allowed": dumped["equivalent_allowed"],
        "delivery_deadline": dumped["delivery_deadline"],
        "automatic_completeness": dumped["completeness"],
        "provenance_structurally_valid": all(
            requirement["provenance"]["document_id"]
            and requirement["provenance"]["locator"]
            for requirement in requirements
        ),
    }


def _direct_result(path: Path, now: datetime) -> dict[str, object]:
    started = time.perf_counter()
    document = read_document_input(path)
    extraction = extract_document(document)
    mapping = map_blocks_to_requirements(
        extraction.blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )
    review_eligible = False
    review_ineligible_reason: str | None = None
    try:
        build_completeness_review_snapshot(
            company_id="local-pilot",
            review_id=f"pilot-{document.document_id}",
            source_document_id=document.document_id,
            source_document_sha256=hashlib.sha256(document.content).hexdigest(),
            document_role=DocumentRole.TENDER_REQUIREMENTS,
            extraction=extraction,
            created_by="local-pilot-operator",
            created_at=now,
        )
        review_eligible = True
    except ValueError as error:
        review_ineligible_reason = type(error).__name__
    return {
        "kind": "DIRECT_DOCUMENT",
        "filename": path.name,
        "extension": path.suffix.casefold(),
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(document.content).hexdigest(),
        "document_id": document.document_id,
        "extraction": extraction.model_dump(mode="json"),
        "mapping": _mapping_payload(mapping),
        "persisted_single_document_review_eligible": review_eligible,
        "review_ineligible_reason": review_ineligible_reason,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _bundle_result(path: Path) -> dict[str, object]:
    started = time.perf_counter()
    bundle = extract_document_bundle_path(path)
    members: list[dict[str, object]] = []
    for index, member in enumerate(bundle.members):
        mapping = None
        if member.media_type is not None:
            mapped = map_blocks_to_requirements(
                member.extraction.blocks,
                document_role=DocumentRole.TENDER_REQUIREMENTS,
            )
            mapping = _mapping_payload(mapped)
        members.append(
            {
                "member_index": index,
                "archive_path": member.archive_path,
                "media_type": member.media_type,
                "byte_size": member.byte_size,
                "sha256": member.sha256,
                "extraction": member.extraction.model_dump(mode="json"),
                "mapping": mapping,
                "persisted_single_document_review_eligible": False,
                "review_ineligible_reason": "ZIP_MEMBER_REVIEW_NOT_SUPPORTED",
            }
        )
    return {
        "kind": "ZIP_BUNDLE",
        "filename": path.name,
        "extension": path.suffix.casefold(),
        "byte_size": path.stat().st_size,
        "sha256": _sha256(path),
        "document_id": bundle.source_document_id,
        "bundle_status": bundle.status.value,
        "bundle_reasons": [reason.value for reason in bundle.reasons],
        "members_total": bundle.members_total,
        "supported_members": bundle.supported_members,
        "unsupported_members": bundle.unsupported_members,
        "members": members,
        "persisted_single_document_review_eligible": False,
        "review_ineligible_reason": "ZIP_REVIEW_NOT_SUPPORTED",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _source_result(path: Path, *, kind: str, status: str, reason: str) -> dict[str, object]:
    return {
        "kind": kind,
        "filename": path.name,
        "extension": path.suffix.casefold(),
        "byte_size": path.stat().st_size,
        "sha256": _sha256(path),
        "execution_status": status,
        "reason": reason,
        "persisted_single_document_review_eligible": False,
    }


def _unsupported_result(path: Path) -> dict[str, object]:
    return _source_result(
        path,
        kind="UNSUPPORTED_SOURCE",
        status="UNKNOWN",
        reason=UNSUPPORTED_REASONS.get(path.suffix.casefold(), "UNSUPPORTED_FORMAT"),
    )


def _process(path: Path, now: datetime) -> dict[str, object]:
    try:
        if path.suffix.casefold() in DIRECT_EXTENSIONS:
            return _direct_result(path, now)
        if path.suffix.casefold() == ".zip":
            return _bundle_result(path)
        return _unsupported_result(path)
    except DocumentRejected as error:
        return _source_result(
            path,
            kind="REJECTED_SOURCE",
            status="UNKNOWN",
            reason=error.code.value,
        )
    except DocumentBundleRejected as error:
        return _source_result(
            path,
            kind="REJECTED_BUNDLE",
            status="UNKNOWN",
            reason=error.code.value,
        )
    except (OSError, ValueError) as error:
        return _source_result(
            path,
            kind="PROCESSING_ERROR",
            status="FAIL",
            reason=type(error).__name__,
        )


def _mapping_rows(results: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for result in results:
        mapping = result.get("mapping")
        if isinstance(mapping, dict):
            rows.append(mapping)
        members = result.get("members")
        if isinstance(members, list):
            rows.extend(
                item["mapping"]
                for item in members
                if isinstance(item, dict) and isinstance(item.get("mapping"), dict)
            )
    return rows


def _summary(results: list[dict[str, object]]) -> dict[str, object]:
    mappings = _mapping_rows(results)
    direct = [item for item in results if item["kind"] == "DIRECT_DOCUMENT"]
    extraction_statuses = [
        extraction["status"]
        for item in direct
        if isinstance((extraction := item.get("extraction")), dict)
    ]
    extraction_pass = extraction_statuses.count("PASS")
    extraction_unknown = extraction_statuses.count("UNKNOWN")
    total_blocks = sum(int(item["blocks_total"]) for item in mappings)
    mapped_blocks = sum(int(item["blocks_mapped"]) for item in mappings)
    return {
        "source_files": len(results),
        "direct_supported_files": len(direct),
        "zip_bundles": sum(item["kind"] == "ZIP_BUNDLE" for item in results),
        "unsupported_or_rejected_files": sum(
            item["kind"] in {"UNSUPPORTED_SOURCE", "REJECTED_SOURCE", "REJECTED_BUNDLE"}
            for item in results
        ),
        "processing_errors": sum(item["kind"] == "PROCESSING_ERROR" for item in results),
        "direct_extraction_pass": extraction_pass,
        "direct_extraction_unknown": extraction_unknown,
        "mapping_units": len(mappings),
        "blocks_total": total_blocks,
        "blocks_mapped": mapped_blocks,
        "technical_block_coverage": mapped_blocks / total_blocks if total_blocks else None,
        "requirements_extracted": sum(int(item["requirements_count"]) for item in mappings),
        "unmapped_blocks": sum(int(item["unmapped_count"]) for item in mappings),
        "mapping_units_without_requirements": sum(
            int(item["requirements_count"]) == 0 for item in mappings
        ),
        "single_document_review_eligible": sum(
            item.get("persisted_single_document_review_eligible") is True
            for item in results
        ),
        "automatic_completeness_statuses": {
            "PASS": 0,
            "FAIL": 0,
            "UNKNOWN": len(mappings),
        },
    }


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle: int | None = None
    temporary: Path | None = None
    try:
        handle, raw_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        temporary = Path(raw_path)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            handle = None
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if handle is not None:
            os.close(handle)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rows = [
        "# Пилот понимания ТЗ — машинный прогон",
        "",
        f"Время: `{report['generated_at']}`  ",
        f"Scope: `{report['scope']}`  ",
        f"Execution status: **{report['execution_status']}**  ",
        "Quality acceptance: **UNKNOWN — human ground truth отсутствует**",
        "",
        "## Наблюдаемые результаты",
        "",
        f"- Исходных файлов: {summary['source_files']}",
        f"- Поддержанных direct-документов: {summary['direct_supported_files']}",
        f"- ZIP-пакетов: {summary['zip_bundles']}",
        f"- Неподдержанных/отклонённых: {summary['unsupported_or_rejected_files']}",
        "- Direct extraction PASS/UNKNOWN: "
        f"{summary['direct_extraction_pass']}/{summary['direct_extraction_unknown']}",
        "- Блоков всего/mapped/unmapped: "
        f"{summary['blocks_total']}/{summary['blocks_mapped']}/"
        f"{summary['unmapped_blocks']}",
        f"- Формализованных требований: {summary['requirements_extracted']}",
        f"- Mapping units без требований: {summary['mapping_units_without_requirements']}",
        "- Eligible для persisted single-document review: "
        f"{summary['single_document_review_eligible']}",
        "",
        "`technical_block_coverage` не является recall требований. Автоматическая",
        "полнота всех mapping units остаётся `UNKNOWN`.",
        "",
        "## По файлам",
        "",
        "| Файл | Вид | Extraction/bundle | Требования | Unmapped | Review eligible |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in report["results"]:
        mapping = item.get("mapping") or {}
        extraction = item.get("extraction") or {}
        state = extraction.get("status") or item.get("bundle_status") or item.get("reason")
        rows.append(
            "| {filename} | {kind} | {state} | {requirements} | {unmapped} | {eligible} |".format(
                filename=str(item["filename"]).replace("|", "\\|"),
                kind=item["kind"],
                state=state,
                requirements=mapping.get("requirements_count", "—"),
                unmapped=mapping.get("unmapped_count", "—"),
                eligible="yes" if item.get("persisted_single_document_review_eligible") else "no",
            )
        )
    rows.extend(
        [
            "",
            "## Метрики, ожидающие human review",
            "",
            "- material requirement recall: `UNKNOWN`;",
            "- requirement precision / hallucinations: `UNKNOWN`;",
            "- semantic provenance correctness: `UNKNOWN`;",
            "- false completeness PASS count: `UNKNOWN`;",
            "- manual review time: `UNKNOWN`.",
            "",
        ]
    )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    output = args.output.resolve()
    now = datetime.now(UTC)
    files = sorted(
        (
            path
            for path in source.iterdir()
            if path.is_file() and path.suffix.casefold() in SOURCE_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )
    supplemental = sorted(
        path.name
        for path in source.iterdir()
        if path.is_file() and path.suffix.casefold() == ".json"
    )
    results = [_process(path, now) for path in files]
    summary = _summary(results)
    report: dict[str, Any] = {
        "schema_version": "tz-understanding-pilot-v1",
        "scope": "requirements_understanding",
        "generated_at": now.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "source_directory": source.name,
        "authorization": {
            "status": "APPROVED_FOR_LOCAL_PILOT",
            "reference": "user instruction in active workspace session",
            "external_transfer": False,
        },
        "code": _git_state(root),
        "implementation_evidence": _implementation_evidence(root),
        "environment": {"python": platform.python_version()},
        "mapper_version": COMPLETENESS_MAPPER_VERSION,
        "mapping_min_confidence": DEFAULT_FACT_MIN_CONFIDENCE,
        "execution_status": (
            "FAIL" if summary["processing_errors"] else "COMPLETE_WITH_DOCUMENTED_GAPS"
        ),
        "quality_acceptance_status": "UNKNOWN",
        "quality_metrics": {
            "material_requirement_recall": None,
            "requirement_precision": None,
            "provenance_correctness": None,
            "false_completeness_pass_count": None,
            "manual_review_minutes": None,
            "reason": "human ground truth is not available",
        },
        "summary": summary,
        "results": results,
        "supplemental_json_artifacts_not_counted_as_tender_sources": supplemental,
        "limitations": [
            "No human ground truth; semantic quality metrics remain UNKNOWN.",
            "Persisted completeness review supports only one complete native document.",
            "ZIP members, RAR, legacy DOC, OCR and multi-document completeness "
            "cannot receive PASS.",
            "This pilot does not test supplier sourcing, quotes, economics or "
            "participation decisions.",
        ],
    }
    manifest = {
        "schema_version": "tz-pilot-manifest-v1",
        "generated_at": now.isoformat(),
        "source_directory": source.name,
        "files": [
            {
                "file_id": f"pilot-file-{index + 1:02d}",
                "filename": item["filename"],
                "role": "TENDER_REQUIREMENTS",
                "byte_size": item["byte_size"],
                "sha256": item["sha256"],
                "format": item["extension"],
                "execution_kind": item["kind"],
            }
            for index, item in enumerate(results)
        ],
    }
    _write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    _write_text(output / "machine-report.json", json.dumps(report, ensure_ascii=False, indent=2))
    _write_text(output / "summary.md", _markdown(report))
    print(json.dumps({"output": str(output), "summary": summary}, ensure_ascii=False, indent=2))
    return 1 if summary["processing_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
