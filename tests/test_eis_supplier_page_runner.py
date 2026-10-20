"""Supplier preparation subprocess has a narrow private protocol and environment."""

from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from procurement.api import eis_supplier_page_runner as runner
from procurement.api.eis_supplier_page_runner import SupplierRunnerFailure
from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.sources.supplier_serp import SearchEngine
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_supplier_page import SupplierPageRequest
from procurement.storage.eis_supplier_search import SupplierSearchRequest
from test_eis_supplier_page_api import saved

REQUEST = SupplierPageRequest(
    position=SupplierSearchRequest(
        selection=PositionSelection(
            notice=NoticeDocumentRef(
                purchase_number="0848300054826000154",
                version_number=1,
                notice_xml_sha256="a" * 64,
            ),
            source_index=1,
        ),
    ),
    serp_run_id="11111111-1111-4111-8111-111111111111",
    engine=SearchEngine.BING,
    rank=1,
)


@pytest.fixture(autouse=True)
def posix_process_group_api(monkeypatch):
    monkeypatch.setitem(runner.os.__dict__, "killpg", lambda pid, sig: None)
    monkeypatch.setitem(runner.signal.__dict__, "SIGKILL", 9)


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
        "PROCUREMENT_SUPPLIER_PAGE_DATABASE_URL": "postgresql://app-private",
    }


def test_unsupported_parent_platform_fails_before_storage_or_process(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    with pytest.raises(SupplierRunnerFailure, match="supplier_page_unavailable"):
        runner.run_prepare_supplier_page_subprocess(
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
        with pytest.raises(SupplierRunnerFailure, match="supplier_page_busy"):
            runner.run_prepare_supplier_page_subprocess(
                STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
            )
    finally:
        runner._SLOT.release()


def test_parent_returns_bound_result_without_putting_dsn_in_payload(monkeypatch):
    expected = saved()
    captured = {}

    class Process:
        returncode = 0
        pid = 320

        def communicate(self, payload, timeout):
            captured["payload"] = payload
            captured["timeout"] = timeout
            output = json.dumps({"ok": True, "result": expected.model_dump(mode="json")}).encode()
            return output, b""

        def wait(self, timeout):
            return 0

    def popen(*args, **kwargs):
        captured["environment"] = kwargs["env"]
        return Process()

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    result = runner.run_prepare_supplier_page_subprocess(
        STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=True
    )
    assert result == expected and captured["timeout"] == 40
    assert b"private-password" not in captured["payload"]
    assert captured["environment"][runner._DATABASE_ENV].endswith("@db/supplier")


def test_successful_leader_exit_still_kills_remaining_process_group(monkeypatch):
    expected = saved()
    signals = []

    class Process:
        returncode = 0
        pid = 324

        def communicate(self, payload, timeout):
            return json.dumps(
                {"ok": True, "result": expected.model_dump(mode="json")}
            ).encode(), b""

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setitem(runner.os.__dict__, "killpg", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    runner.run_prepare_supplier_page_subprocess(
        STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
    )
    assert signals == [(324, runner.signal.SIGKILL)]


def test_communicate_oserror_kills_group_and_releases_slot(monkeypatch):
    actions = []

    class Process:
        pid = 325

        def communicate(self, payload, timeout):
            raise OSError("pipe failed with private detail")

        def wait(self, timeout):
            actions.append(("wait", timeout))
            return 1

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setitem(runner.os.__dict__, "killpg", lambda pid, sig: actions.append((pid, sig)))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure, match="supplier_page_unavailable"):
        runner.run_prepare_supplier_page_subprocess(
            STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
        )
    assert actions == [(325, runner.signal.SIGKILL), ("wait", 2)]
    assert runner._SLOT.acquire(blocking=False)
    runner._SLOT.release()


def test_parent_rejects_foreign_request_result(monkeypatch):
    child_payload = saved().model_dump(mode="json")
    child_payload["report"]["request"]["position"]["selection"]["source_index"] = 2

    class Process:
        returncode = 0
        pid = 322

        def communicate(self, payload, timeout):
            return json.dumps({"ok": True, "result": child_payload}).encode(), b""

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure, match="supplier_page_unavailable"):
        runner.run_prepare_supplier_page_subprocess(
            STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
        )


def test_timeout_terminates_and_releases_slot(monkeypatch):
    actions = []
    monkeypatch.setattr(runner.signal, "SIGKILL", 9, raising=False)

    class Process:
        returncode = None
        pid = 321

        def communicate(self, payload, timeout):
            raise subprocess.TimeoutExpired("private-password", timeout)

        waits = 0

        def wait(self, timeout):
            actions.append(("wait", timeout))
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("private-password", timeout)
            return 1

    monkeypatch.setattr(runner.os, "name", "posix")
    monkeypatch.setattr(
        runner.os, "killpg", lambda pid, sig: actions.append((pid, sig)), raising=False
    )
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure) as caught:
        runner.run_prepare_supplier_page_subprocess(
            STORAGE, "tenant-a", REQUEST, actor_id="actor-a", refresh=False
        )
    assert str(caught.value) == "supplier_page_unavailable"
    assert actions == [
        (321, runner.signal.SIGTERM),
        ("wait", 2),
        (321, runner.signal.SIGKILL),
        ("wait", 2),
    ]
    assert runner._SLOT.acquire(blocking=False)
    runner._SLOT.release()


def test_child_resource_limit_is_cpu45_without_address_space_cap(monkeypatch):
    calls = []
    resource = SimpleNamespace(
        RLIMIT_CPU="cpu",
        setrlimit=lambda kind, value: calls.append((kind, value)),
    )
    monkeypatch.setattr(runner, "import_module", lambda name: resource)
    runner._limits()
    assert calls == [("cpu", (10, 10))]


def test_parent_input_and_output_caps_fail_closed(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")
    with pytest.raises(SupplierRunnerFailure, match="SUPPLIER_PAGE_REQUEST_INVALID"):
        runner.run_prepare_supplier_page_subprocess(
            STORAGE, "x" * runner.MAX_INPUT_BYTES, REQUEST, actor_id="actor", refresh=False
        )

    class Process:
        returncode = 0
        pid = 323

        def communicate(self, payload, timeout):
            return b"x" * (runner.MAX_OUTPUT_BYTES + 1), b""

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(SupplierRunnerFailure, match="supplier_page_unavailable"):
        runner.run_prepare_supplier_page_subprocess(
            STORAGE, "tenant", REQUEST, actor_id="actor", refresh=False
        )
