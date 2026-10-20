"""Legacy mutators must refuse before touching an unaccepted deployment payload."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class ForbiddenStage:
    def __truediv__(self, name: str) -> Path:
        raise AssertionError(f"unaccepted stage accessed: {name}")


@pytest.mark.parametrize(
    ("filename", "entrypoint", "source_kind"),
    [
        ("server-supplier-browser-rollout.py", "install", "INSTALLED_BASE_OVERLAY"),
        ("server-supplier-browser-rollout.py", "install_locked", "INSTALLED_BASE_OVERLAY"),
        ("server-supplier-browser-rollout.py", "enable_init", "CONFIG_CHANGE"),
        ("server-supplier-captcha-rollout.py", "install", "INSTALLED_BASE_OVERLAY"),
    ],
)
def test_legacy_mutator_refuses_before_any_payload_or_runtime_access(
    filename: str, entrypoint: str, source_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = spec_from_file_location("legacy_rollout_under_test", ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("runtime, lease or source access before quality admission")

    for name in ("docker", "run", "atomic", "write", "deployment_lease", "spec_from_file_location"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, forbidden)
    with pytest.raises(RuntimeError, match=f"QUALITY_GATE_ADAPTER_UNAVAILABLE: {source_kind}"):
        getattr(module, entrypoint)(ForbiddenStage())
