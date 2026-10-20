"""Supplier preparation subprocess has a narrow private protocol and environment."""

from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from procurement.api import eis_supplier_search_runner as runner
from procurement.api.eis_supplier_search_runner import SupplierRunnerFailure
from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_supplier_search import SupplierSearchRequest
from test_eis_supplier_search_api import saved

REQUEST = SupplierSearchRequest(
    selection=PositionSelection(
        notice=NoticeDocumentRef(
            purchase_number="0848300054826000154",
            version_number=1,
            notice_xml_sha256="a" * 64,
        ),
        source_index=1,
    )
)


def test_child_environment_is_an_explicit_allowlist(monkeypatch):
    monkeypatch.setattr(
        os,
        "environ",
        {
            "PATH": "/runtime",
            "PYTHONPATH": "/application",
            "DATABASE_URL": "owner",
            "DATABASE_ADMIN_URL": "admin",
            "connectionDSN": "foreign",
            "EIS_TOKEN": "secret",
            "http_proxy": "http://public-proxy",
        },
    )
    result = runner._environment("postgresql://app-private")
    assert result == {
        "PATH": "/runtime",
        "PYTHONPATH": "/application",
        "http_proxy": "http://public-proxy",
        "PROCUREMENT_SUPPLIER_DATABASE_URL": "postgresql://app-private",
    }


def test_unsupported_parent_platform_fails_before_storage_or_process(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    with pytest.raises(SupplierRunnerFailure, match="supplier_search_unavailable"):
        runner.run_prepare_supplier_subprocess(
            object(), "tenant-a", REQUEST, actor_id="actor-a", refresh=False
        )


def test_unique_private_protocol_rejects_duplicate_keys():
    with pytest.raises(ValueError):
        runner._unique_object([("ok", True), ("ok", False)])


class Url:
    def render_as_string(self, *, hide_password):
        assert not hide_password
        return "postgresql://private-user:private-password@db/supplier"


STORAGE = SimpleNamespace(_engine=SimpleNamespace(url=Url()))


def test_busy_slot_fails_before_process(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")
    assert runner._SLOT.acquire(blocking=False)
    try:
        with pytest.raises(SupplierRunnerFailure, match="supplier_search_busy"):
            runner.run_prepare_supplier_subprocess(
                STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
            )
    finally:
        runner._SLOT.release()


def test_parent_returns_bound_result_without_putting_dsn_in_payload(monkeypatch):
    expected = saved()
    captured = {}

    class Process:
        returncode = 0

        def communicate(self, payload, timeout):
            captured["payload"] = payload
            captured["timeout"] = timeout
            output = json.dumps(
                {"ok": True, "result": expected.model_dump(mode="json")}
            ).encode()
            return output, b""

    def popen(*args, **kwargs):
        captured["environment"] = kwargs["env"]
        return Process()

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    result = runner.run_prepare_supplier_subprocess(
        STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=True
    )
    assert result == expected and captured["timeout"] == 60
    assert b"private-password" not in captured["payload"]
    assert captured["environment"][runner._DATABASE_ENV].endswith("@db/supplier")


def test_parent_rejects_foreign_request_result(monkeypatch):
    child_payload = saved().model_dump(mode="json")
    child_payload["report"]["request"]["selection"]["source_index"] = 2

    class Process:
        returncode = 0

        def communicate(self, payload, timeout):
            return json.dumps({"ok": True, "result": child_payload}).encode(), b""

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure, match="supplier_search_unavailable"):
        runner.run_prepare_supplier_subprocess(
            STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
        )


def test_timeout_terminates_and_releases_slot(monkeypatch):
    actions = []

    class Process:
        returncode = None

        def communicate(self, payload, timeout):
            raise subprocess.TimeoutExpired("private-password", timeout)

        def terminate(self):
            actions.append("terminate")

        waits = 0

        def wait(self, timeout):
            actions.append(("wait", timeout))
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("private-password", timeout)
            return 1

        def kill(self):
            actions.append("kill")

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure) as caught:
        runner.run_prepare_supplier_subprocess(
            STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
        )
    assert str(caught.value) == "supplier_search_unavailable"
    assert actions == ["terminate", ("wait", 2), "kill", ("wait", 2)]
    assert runner._SLOT.acquire(blocking=False)
    runner._SLOT.release()


def test_child_resource_limits_are_cpu30_and_address512mib(monkeypatch):
    calls = []
    resource = SimpleNamespace(
        RLIMIT_CPU="cpu",
        RLIMIT_AS="as",
        setrlimit=lambda kind, value: calls.append((kind, value)),
    )
    monkeypatch.setattr(runner, "import_module", lambda name: resource)
    runner._limits()
    assert calls == [
        ("cpu", (30, 30)),
        ("as", (512 * 1024**2, 512 * 1024**2)),
    ]


def test_parent_input_and_output_caps_fail_closed(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")
    with pytest.raises(SupplierRunnerFailure, match="SUPPLIER_SEARCH_REQUEST_INVALID"):
        runner.run_prepare_supplier_subprocess(
            STORAGE, "x" * runner.MAX_INPUT_BYTES, REQUEST, actor_id="actor", refresh=False
        )

    class Process:
        returncode = 0

        def communicate(self, payload, timeout):
            return b"x" * (runner.MAX_OUTPUT_BYTES + 1), b""

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure, match="supplier_search_unavailable"):
        runner.run_prepare_supplier_subprocess(
            STORAGE, "tenant", REQUEST, actor_id="actor", refresh=False
        )
