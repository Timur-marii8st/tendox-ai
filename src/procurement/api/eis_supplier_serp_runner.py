"""Private bounded subprocess protocol for explicit supplier-serp preparation."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, cast

from procurement.storage.eis_supplier_search import SupplierSearchRequest
from procurement.storage.eis_supplier_serp import SavedSupplierSerp

TIMEOUT_SECONDS = 90
MAX_INPUT_BYTES = 4_096
MAX_OUTPUT_BYTES = 256 * 1024
_DATABASE_ENV = "PROCUREMENT_SUPPLIER_SERP_DATABASE_URL"
_SLOT = threading.BoundedSemaphore(1)
_SAFE_LOOKUP = {"SUPPLIER_SERP_NOT_FOUND"}
_SAFE_VALUE = {
    "NOTICE_VERSION_STALE",
    "NOTICE_VARIANT_REVIEW_REQUIRED",
    "SUPPLIER_SERP_BUSY",
    "SUPPLIER_SERP_TENANT_BUSY",
    "SUPPLIER_SERP_REFRESH_COOLDOWN",
    "SUPPLIER_SERP_POSITION_CHANGED",
    "SUPPLIER_SERP_REQUEST_INVALID",
    "SUPPLIER_SERP_REPORT_LIMIT",
    "SUPPLIER_SERP_BUNDLE_LIMIT",
    "SUPPLIER_SERP_DAILY_BUNDLE_LIMIT",
    "SUPPLIER_SERP_HOURLY_LIMIT",
    "SUPPLIER_SERP_DIGEST_CONFLICT",
    "SUPPLIER_SERP_EVIDENCE_CONFLICT",
    "CHARACTERISTIC_POSITION_NOT_FOUND",
    "CHARACTERISTIC_POSITION_INVALID",
}


def _signal_group(pid: int, signal_name: str) -> None:
    kill_group = os.__dict__.get("killpg")
    group_signal = signal.__dict__.get(signal_name)
    if not callable(kill_group) or not isinstance(group_signal, int):
        raise RuntimeError("process group control unavailable")
    with suppress(ProcessLookupError):
        kill_group(pid, group_signal)


@dataclass(frozen=True)
class SupplierRunnerFailure(RuntimeError):
    kind: Literal["lookup", "value", "unavailable"]
    code: str

    def __str__(self) -> str:
        return self.code


def _environment(database_url: str) -> dict[str, str]:
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
        "SOURCE_HTTP_TRUST_ENV",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "PLAYWRIGHT_BROWSERS_PATH",
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "CHROME_PATH",
        "CHROMIUM_PATH",
        "SUPPLIER_SERP_BROWSER_STATE_DIR",
        "SUPPLIER_SERP_CHROME_PATH",
        "SUPPLIER_SERP_XVFB_PATH",
    }
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result[_DATABASE_ENV] = database_url
    return result


def _exchange(process: Any, raw: bytes, request: SupplierSearchRequest) -> SavedSupplierSerp:
    try:
        try:
            output, _ = process.communicate(raw, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            _signal_group(process.pid, "SIGTERM")
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
            raise SupplierRunnerFailure("unavailable", "supplier_serp_unavailable") from error
        if process.returncode != 0 or len(output) > MAX_OUTPUT_BYTES:
            raise SupplierRunnerFailure("unavailable", "supplier_serp_unavailable")
        message = json.loads(
            output,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if (
            isinstance(message, dict)
            and message.get("ok") is True
            and set(message) == {"ok", "result"}
        ):
            result = SavedSupplierSerp.model_validate(message["result"])
            if result.report.request != request or (
                result.created and result.report.status == "STARTED"
            ):
                raise ValueError
            return result
        if (
            isinstance(message, dict)
            and message.get("ok") is False
            and set(message) == {"ok", "kind", "code"}
        ):
            kind, code = message["kind"], message["code"]
            if kind == "lookup" and code in _SAFE_LOOKUP:
                raise SupplierRunnerFailure("lookup", code)
            if kind == "value" and code in _SAFE_VALUE:
                raise SupplierRunnerFailure("value", code)
        raise ValueError
    finally:
        _signal_group(process.pid, "SIGKILL")
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)


def run_prepare_supplier_serp_subprocess(
    storage: object,
    company: str,
    request: SupplierSearchRequest,
    *,
    actor_id: str,
    refresh: bool,
) -> SavedSupplierSerp:
    if os.name != "posix":
        raise SupplierRunnerFailure("unavailable", "supplier_serp_unavailable")
    if not _SLOT.acquire(blocking=False):
        raise SupplierRunnerFailure("unavailable", "supplier_serp_busy")
    try:
        engine = getattr(storage, "_engine", None)
        if engine is None:
            raise SupplierRunnerFailure("unavailable", "supplier_serp_unavailable")
        database_url = engine.url.render_as_string(hide_password=False)
        raw = json.dumps(
            {
                "company": company,
                "actor": actor_id,
                "request": request.model_dump(mode="json"),
                "refresh": refresh,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(raw) > MAX_INPUT_BYTES:
            raise SupplierRunnerFailure("value", "SUPPLIER_SERP_REQUEST_INVALID")
        process = subprocess.Popen(
            [sys.executable, "-m", "procurement.api.eis_supplier_serp_runner"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_environment(database_url),
            start_new_session=True,
        )
        return _exchange(process, raw, request)
    except SupplierRunnerFailure:
        raise
    except Exception as error:
        raise SupplierRunnerFailure("unavailable", "supplier_serp_unavailable") from error
    finally:
        _SLOT.release()


def _limits() -> None:
    resource = cast(Any, import_module("resource"))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _main() -> int:
    storage = None
    try:
        _limits()
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        payload = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if (
            len(raw) > MAX_INPUT_BYTES
            or not isinstance(payload, dict)
            or set(payload) != {"company", "actor", "request", "refresh"}
        ):
            raise ValueError
        if (
            not isinstance(payload["company"], str)
            or not payload["company"].strip()
            or not isinstance(payload["actor"], str)
            or not payload["actor"].strip()
            or type(payload["refresh"]) is not bool
        ):
            raise ValueError
        request = SupplierSearchRequest.model_validate(payload["request"])
        url = os.environ.pop(_DATABASE_ENV, "")
        if not url:
            raise RuntimeError
        from procurement.storage.eis_supplier_serp import prepare_supplier_serp
        from procurement.storage.repository import PostgresStorage

        storage = PostgresStorage.from_url(url, pool_pre_ping=True)
        result = prepare_supplier_serp(
            storage,
            payload["company"],
            request,
            actor_id=payload["actor"],
            refresh=payload["refresh"],
        )
        message = {"ok": True, "result": result.model_dump(mode="json")}
    except LookupError as error:
        code = str(error)
        message = (
            {"ok": False, "kind": "lookup", "code": code}
            if code in _SAFE_LOOKUP
            else {"ok": False, "kind": "unavailable", "code": "supplier_serp_unavailable"}
        )
    except ValueError as error:
        code = str(error)
        message = (
            {"ok": False, "kind": "value", "code": code}
            if code in _SAFE_VALUE
            else {"ok": False, "kind": "unavailable", "code": "supplier_serp_unavailable"}
        )
    except Exception:
        message = {"ok": False, "kind": "unavailable", "code": "supplier_serp_unavailable"}
    finally:
        if storage is not None:
            storage._engine.dispose()
    output = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
    if len(output) > MAX_OUTPUT_BYTES:
        output = b'{"ok":false,"kind":"unavailable","code":"supplier_serp_unavailable"}'
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
