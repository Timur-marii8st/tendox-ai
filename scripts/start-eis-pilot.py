"""Start the localhost-only EIS pilot with an optional local search index."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

ROOT: Final = Path(__file__).resolve().parents[1]
PILOT_DIR: Final = ROOT / "data" / "eis-pilot"
BACKEND_PORT: Final = 8000
FRONTEND_PORT: Final = 3000
STARTUP_TIMEOUT_SECONDS: Final = 40


def _assert_port_free(port: int) -> None:
    """Fail before launch if another local program already owns the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"127.0.0.1:{port} is already in use") from error


def _pilot_token() -> str:
    """Read or create the persistent local token without writing it to stdout."""
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    token_path = PILOT_DIR / "token"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
        raise RuntimeError(f"pilot token file is invalid: {token_path}")
    token = secrets.token_urlsafe(48)
    token_path.write_text(token + "\n", encoding="utf-8")
    with suppress(OSError):
        os.chmod(token_path, 0o600)
    return token


def _child_environment(token: str) -> dict[str, str]:
    """Pass the local token and optional local index URL to pilot children."""
    environment = os.environ.copy()
    environment.pop("OPENROUTER_API_KEY", None)
    database_config = PILOT_DIR / "database.json"
    if database_config.is_file():
        try:
            runtime_url = json.loads(database_config.read_text(encoding="utf-8"))["runtime_url"]
            parsed = urlsplit(runtime_url)
            if (
                parsed.scheme != "postgresql+psycopg"
                or parsed.hostname != "127.0.0.1"
                or parsed.username != "procurement_app"
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("local EIS index database configuration is invalid") from error
        environment["DATABASE_URL"] = runtime_url
    environment["EIS_PILOT_TOKEN"] = token
    environment.setdefault("EIS_PILOT_COMPANY", "local-eis-supplier")
    environment["PROCUREMENT_API_URL"] = "http://127.0.0.1:8000"
    environment["PROCUREMENT_API_TOKEN"] = token
    return environment


def _popen_kwargs(log: object) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _wait_for_http(url: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 400:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError(f"service did not become ready within {STARTUP_TIMEOUT_SECONDS}s: {url}")


def _stop_own_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    """Launch backend and built frontend, then return their local URLs and PIDs."""
    next_cli = ROOT / "web" / "node_modules" / "next" / "dist" / "bin" / "next"
    build_marker = ROOT / "web" / ".next" / "BUILD_ID"
    if not next_cli.is_file():
        raise RuntimeError(
            "Next.js is not installed in web/node_modules; install dependencies first"
        )
    if not build_marker.is_file():
        raise RuntimeError("production frontend build is missing; run the web build first")
    _assert_port_free(FRONTEND_PORT)
    _assert_port_free(BACKEND_PORT)
    token = _pilot_token()
    environment = _child_environment(token)
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[bytes]] = []
    try:
        with (
            (PILOT_DIR / "backend.log").open("ab") as backend_log,
            (PILOT_DIR / "frontend.log").open("ab") as frontend_log,
        ):
            backend = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "--factory",
                    "procurement.api.discovery_runtime:create_discovery_app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(BACKEND_PORT),
                ],
                cwd=ROOT,
                env=environment,
                **_popen_kwargs(backend_log),
            )
            processes.append(backend)
            frontend = subprocess.Popen(
                [
                    "node",
                    str(next_cli),
                    "start",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(FRONTEND_PORT),
                ],
                cwd=ROOT / "web",
                env=environment,
                **_popen_kwargs(frontend_log),
            )
            processes.append(frontend)
            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            _wait_for_http("http://127.0.0.1:8000/health", deadline)
            _wait_for_http("http://127.0.0.1:3000/tender-discovery", deadline)
        (PILOT_DIR / "pids.json").write_text(
            json.dumps({"backend_pid": backend.pid, "frontend_pid": frontend.pid}) + "\n",
            encoding="utf-8",
        )
    except Exception:
        _stop_own_processes(processes)
        raise
    print("EIS pilot frontend: http://127.0.0.1:3000/tender-discovery")
    print("EIS pilot backend:  http://127.0.0.1:8000/health")
    print(f"PIDs: backend={backend.pid}, frontend={frontend.pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
