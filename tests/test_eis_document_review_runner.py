"""The private review runner bounds concurrency, time, protocol, and inherited secrets."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from procurement.api import eis_document_review_runner as runner
from test_eis_document_review_api import REQUEST, result


class Url:
    def render_as_string(self, *, hide_password):
        assert not hide_password
        return "postgresql://private-user:private-password@db/review"


STORAGE = SimpleNamespace(_engine=SimpleNamespace(url=Url()))


def test_unsupported_platform_and_busy_slot_fail_without_process(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    with pytest.raises(runner.ReviewRunnerFailure, match="document_review_unavailable"):
        runner.run_prepare_review_subprocess(STORAGE, "tenant", REQUEST, actor_id="actor")

    monkeypatch.setattr(runner.os, "name", "posix")
    assert runner._SLOT.acquire(blocking=False)
    try:
        with pytest.raises(runner.ReviewRunnerFailure, match="document_review_busy"):
            runner.run_prepare_review_subprocess(STORAGE, "tenant", REQUEST, actor_id="actor")
    finally:
        runner._SLOT.release()


def test_parent_protocol_returns_typed_result_and_does_not_log_database_url(monkeypatch):
    expected = result()
    captured = {}

    class Process:
        returncode = 0

        def communicate(self, payload, timeout):
            captured["payload"] = payload
            captured["timeout"] = timeout
            return (
                json.dumps(
                    {"ok": True, "result": expected.model_dump(mode="json")},
                    separators=(",", ":"),
                ).encode(),
                b"",
            )

    def popen(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        assert kwargs["stderr"] is subprocess.DEVNULL
        return Process()

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setenv("EIS_PRIVATE_TOKEN", "must-not-pass")
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner")
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://admin")
    monkeypatch.setenv("CONNECTION_DSN", "postgresql://other")
    monkeypatch.setenv("UNKNOWN_SECRET_ENV", "secret")
    monkeypatch.setenv("PYTHONPATH", "runtime-path")
    actual = runner.run_prepare_review_subprocess(STORAGE, "tenant", REQUEST, actor_id="actor")
    assert actual == expected
    assert captured["timeout"] == 45
    assert "EIS_PRIVATE_TOKEN" not in captured["environment"]
    assert "DATABASE_URL" not in captured["environment"]
    assert "DATABASE_ADMIN_URL" not in captured["environment"]
    assert "CONNECTION_DSN" not in captured["environment"]
    assert "UNKNOWN_SECRET_ENV" not in captured["environment"]
    assert captured["environment"]["PYTHONPATH"] == "runtime-path"
    assert captured["environment"][runner._DATABASE_ENV].endswith("@db/review")
    assert b"private-password" not in captured["payload"]


@pytest.mark.parametrize("mutation", ["request", "cursor"])
def test_parent_rejects_valid_but_wrong_child_result(monkeypatch, mutation):
    payload = result().model_dump(mode="json")
    if mutation == "request":
        payload["request"]["content_uid"] = "B" * 32
    else:
        payload["page"]["character_offset"] = 1
        payload["page"]["blocks"][0].update(
            character_start=1,
            text="ext",
            text_truncated=True,
        )
        payload["page"]["page_text_characters"] = 3
        payload["page"]["page_text_truncated"] = True
        payload["page"]["page_reasons"] = ["PAGE_TEXT_LIMIT"]
        payload["page"]["delivery_lead_indices"] = []

    class Process:
        returncode = 0

        def communicate(self, _payload, timeout):
            return json.dumps({"ok": True, "result": payload}).encode(), b""

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(runner.ReviewRunnerFailure, match="document_review_unavailable"):
        runner.run_prepare_review_subprocess(STORAGE, "tenant", REQUEST, actor_id="actor")


def test_timeout_terminates_then_redacts(monkeypatch):
    actions = []

    class Process:
        returncode = None

        def communicate(self, payload, timeout):
            raise subprocess.TimeoutExpired("private-password", timeout)

        def terminate(self):
            actions.append("terminate")

        def wait(self, timeout):
            actions.append(("wait", timeout))
            return 1

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(runner.ReviewRunnerFailure) as caught:
        runner.run_prepare_review_subprocess(STORAGE, "tenant", REQUEST, actor_id="actor")
    assert str(caught.value) == "document_review_unavailable"
    assert actions == ["terminate", ("wait", 2)]


def test_child_resource_limits_are_cpu30_and_address512mib(monkeypatch):
    calls = []
    resource = SimpleNamespace(
        RLIMIT_CPU="cpu",
        RLIMIT_AS="as",
        setrlimit=lambda kind, value: calls.append((kind, value)),
    )
    monkeypatch.setattr(runner, "import_module", lambda name: resource)
    runner._set_limits()
    assert calls == [
        ("cpu", (30, 30)),
        ("as", (512 * 1024**2, 512 * 1024**2)),
    ]


@pytest.mark.skipif(os.name != "posix", reason="resource limits are a POSIX child contract")
def test_actual_child_rejects_invalid_private_protocol_without_echoing_input():
    secret = "secret-value-that-must-not-return"
    completed = subprocess.run(
        [sys.executable, "-m", "procurement.api.eis_document_review_runner"],
        input=("{" + secret).encode(),
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert secret.encode() not in completed.stdout + completed.stderr
    assert json.loads(completed.stdout) == {
        "ok": False,
        "kind": "unavailable",
        "code": "document_review_unavailable",
    }
