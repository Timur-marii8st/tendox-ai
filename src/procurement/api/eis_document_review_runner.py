"""Private bounded subprocess protocol for native EIS document review preparation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, cast

from procurement.storage.eis_document_review import (
    ReviewDocumentRequest,
    SavedReviewDocumentPage,
)

RUNNER_TIMEOUT_SECONDS = 45
RUNNER_MAX_INPUT_BYTES = 4_096
RUNNER_MAX_OUTPUT_BYTES = 256 * 1024
_DATABASE_ENV = "PROCUREMENT_REVIEW_DATABASE_URL"
_SLOT = threading.BoundedSemaphore(1)
_SAFE_LOOKUP = {
    "NOTICE_NOT_FOUND",
    "DOCUMENT_ATTACHMENT_NOT_FOUND",
    "DOCUMENT_RECEIPT_NOT_FOUND",
}
_SAFE_VALUE = {
    "NOTICE_DIGEST_CONFLICT",
    "NOTICE_VERSION_STALE",
    "DOCUMENT_RECEIPT_DIGEST_CONFLICT",
    "REVIEW_ANALYSIS_EVIDENCE_CONFLICT",
    "NOTICE_VARIANT_REVIEW_REQUIRED",
    "ATTACHMENT_FILENAME_REQUIRES_REVIEW",
    "REVIEW_DOCUMENT_FORMAT_UNSUPPORTED",
    "REVIEW_DOCUMENT_BYTES_LIMIT",
    "DOCUMENT_BYTES_NOT_VERIFIABLE",
    "REVIEW_ATTACHMENT_MANIFEST_LIMIT",
    "REVIEW_ANALYSIS_PAYLOAD_LIMIT",
}


@dataclass(frozen=True)
class ReviewRunnerFailure(RuntimeError):
    kind: Literal["lookup", "value", "unavailable"]
    code: str

    def __str__(self) -> str:
        return self.code


def _child_environment(database_url: str) -> dict[str, str]:
    allowed = {
        "PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "TZ",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment[_DATABASE_ENV] = database_url
    return environment


def run_prepare_review_subprocess(
    storage: object,
    company: str,
    request: ReviewDocumentRequest,
    *,
    actor_id: str,
) -> SavedReviewDocumentPage:
    """Run the complete storage prepare under a process deadline and OS limits."""
    if os.name != "posix":
        raise ReviewRunnerFailure("unavailable", "document_review_unavailable")
    if not _SLOT.acquire(blocking=False):
        raise ReviewRunnerFailure("unavailable", "document_review_busy")
    try:
        engine = getattr(storage, "_engine", None)
        if engine is None:
            raise ReviewRunnerFailure("unavailable", "document_review_unavailable")
        database_url = engine.url.render_as_string(hide_password=False)
        payload = json.dumps(
            {
                "company": company,
                "actor": actor_id,
                "request": request.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(payload) > RUNNER_MAX_INPUT_BYTES:
            raise ReviewRunnerFailure("value", "invalid_review_request")
        process = subprocess.Popen(
            [sys.executable, "-m", "procurement.api.eis_document_review_runner"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_child_environment(database_url),
        )
        try:
            output, _ = process.communicate(payload, timeout=RUNNER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            raise ReviewRunnerFailure("unavailable", "document_review_unavailable") from error
        if process.returncode != 0 or len(output) > RUNNER_MAX_OUTPUT_BYTES:
            raise ReviewRunnerFailure("unavailable", "document_review_unavailable")
        try:
            message = json.loads(output)
            if not isinstance(message, dict) or set(message) - {"ok", "result", "kind", "code"}:
                raise ValueError
            if message.get("ok") is True and set(message) == {"ok", "result"}:
                result = SavedReviewDocumentPage.model_validate(message["result"])
                if (
                    result.request != request
                    or result.page.sha256 != request.expected_document_sha256
                    or result.page.offset != 0
                    or result.page.character_offset != 0
                    or result.page.limit != 25
                ):
                    raise ValueError
                return result
            if message.get("ok") is False and set(message) == {"ok", "kind", "code"}:
                kind, code = message["kind"], message["code"]
                if kind == "lookup" and code in _SAFE_LOOKUP:
                    raise ReviewRunnerFailure("lookup", code)
                if kind == "value" and code in _SAFE_VALUE:
                    raise ReviewRunnerFailure("value", code)
            raise ValueError
        except ReviewRunnerFailure:
            raise
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ReviewRunnerFailure("unavailable", "document_review_unavailable") from error
    except ReviewRunnerFailure:
        raise
    except Exception as error:
        raise ReviewRunnerFailure("unavailable", "document_review_unavailable") from error
    finally:
        _SLOT.release()


def _set_limits() -> None:
    resource = cast(Any, import_module("resource"))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _main() -> int:
    storage = None
    try:
        _set_limits()
        raw = sys.stdin.buffer.read(RUNNER_MAX_INPUT_BYTES + 1)
        if len(raw) > RUNNER_MAX_INPUT_BYTES:
            raise ValueError
        payload = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(payload, dict) or set(payload) != {"company", "actor", "request"}:
            raise ValueError
        company, actor = payload["company"], payload["actor"]
        if not isinstance(company, str) or not isinstance(actor, str):
            raise ValueError
        request = ReviewDocumentRequest.model_validate(payload["request"])
        database_url = os.environ.pop(_DATABASE_ENV, "")
        if not database_url:
            raise RuntimeError
        from procurement.storage.eis_document_review import prepare_review_document
        from procurement.storage.repository import PostgresStorage

        storage = PostgresStorage.from_url(database_url, pool_pre_ping=True)
        result = prepare_review_document(storage, company, request, actor_id=actor)
        message = {"ok": True, "result": result.model_dump(mode="json")}
    except LookupError as error:
        code = str(error)
        message = (
            {"ok": False, "kind": "lookup", "code": code}
            if code in _SAFE_LOOKUP
            else {"ok": False, "kind": "unavailable", "code": "document_review_unavailable"}
        )
    except ValueError as error:
        code = str(error)
        message = (
            {"ok": False, "kind": "value", "code": code}
            if code in _SAFE_VALUE
            else {"ok": False, "kind": "unavailable", "code": "document_review_unavailable"}
        )
    except Exception:
        message = {"ok": False, "kind": "unavailable", "code": "document_review_unavailable"}
    finally:
        if storage is not None:
            storage._engine.dispose()
    output = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
    if len(output) > RUNNER_MAX_OUTPUT_BYTES:
        output = b'{"ok":false,"kind":"unavailable","code":"document_review_unavailable"}'
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
