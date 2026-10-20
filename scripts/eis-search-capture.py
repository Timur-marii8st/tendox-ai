"""Capture or verify one bounded M2b1 EIS search package."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from pydantic import TypeAdapter

from procurement.sources.eis_search_capture import canonical_bytes, verify_capture_package
from procurement.storage.eis_search_capture import build_storage, capture_search_projection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture")
    capture.add_argument("--plan", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--capture-id", required=True)
    capture.add_argument("--runtime-identity", type=Path, required=True)
    capture.add_argument("--database-url-env", default="DATABASE_URL")
    verify = subcommands.add_parser("verify")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--expected-manifest-sha256")
    return parser


def _read_runtime(path: Path) -> dict[str, str]:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("runtime identity must be a regular file")
    if metadata.st_size > 16_777_216:
        raise ValueError("runtime identity exceeds metadata cap")
    with path.open("rb") as stream:
        content = stream.read(16_777_217)
    if len(content) > 16_777_216:
        raise ValueError("runtime identity exceeds metadata cap")
    value = TypeAdapter(dict[str, str]).validate_json(content)
    if not value:
        raise ValueError("runtime identity must not be empty")
    return value


def _write_report(path: Path, value: object) -> None:
    if path.exists():
        raise ValueError("report path already exists")
    content = canonical_bytes(value) + b"\n"
    if len(content) > 16_777_216:
        raise ValueError("report exceeds metadata cap")
    path.write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    status: str
    if args.command == "capture":
        database_url = os.environ.get(args.database_url_env)
        if not database_url:
            raise ValueError(f"{args.database_url_env} is required")
        capture_result = capture_search_projection(
            build_storage(database_url),
            args.plan,
            args.output,
            capture_id=args.capture_id,
            external_runtime=_read_runtime(args.runtime_identity),
        )
        status = capture_result.status
        output = args.output
    else:
        verification_result = verify_capture_package(
            args.package,
            args.plan,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
        _write_report(args.report, verification_result)
        status = verification_result.status
        output = args.report
    message = json.dumps(
        {"status": status, "output": str(output)}, ensure_ascii=True, sort_keys=True
    )
    sys.stdout.buffer.write(message.encode("ascii") + b"\n")
    return 0 if status in {"COMPLETE", "CAPTURE_CONTENT_VERIFIED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
