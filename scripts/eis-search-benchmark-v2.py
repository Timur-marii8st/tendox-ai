"""Replay an EIS saved-search v2 evidence package without network or database access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from procurement.sources.eis_search_benchmark_v2 import (
    calculate_report,
    labels_template,
    load_package,
    report_markdown,
)


def _write(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ValueError("OUTPUT_SYMLINK_REJECTED")
    path.write_bytes(content)


def replay(evidence_root: Path, package_path: Path, output: Path) -> None:
    """Validate exact evidence and write deterministic JSON, Markdown and label template."""
    root = evidence_root.resolve(strict=True)
    package = package_path.resolve(strict=True)
    if not package.is_relative_to(root):
        raise ValueError("PACKAGE_PATH_ESCAPE")
    if output.resolve().is_relative_to(root):
        raise ValueError("OUTPUT_INSIDE_EVIDENCE_ROOT")
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise ValueError("OUTPUT_PATH_INVALID")
    loaded = load_package(root, package)
    report = calculate_report(loaded)
    report_json = (
        json.dumps(
            report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2
        ).encode("utf-8")
        + b"\n"
    )
    template_json = (
        json.dumps(labels_template(loaded), sort_keys=True, ensure_ascii=False, indent=2).encode(
            "utf-8"
        )
        + b"\n"
    )
    output.mkdir(parents=True, exist_ok=True)
    targets = tuple(output / name for name in ("report.json", "report.md", "labels-template.json"))
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in targets):
        raise ValueError("OUTPUT_FILE_INVALID")
    _write(output / "report.json", report_json)
    _write(output / "report.md", report_markdown(report).encode("utf-8"))
    _write(output / "labels-template.json", template_json)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        replay(args.evidence_root, args.package, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"benchmark v2 rejected: {type(error).__name__}\n")


if __name__ == "__main__":
    main()
