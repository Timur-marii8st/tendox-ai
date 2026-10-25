"""Private retained material must not force broken links into release docs."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_layout_still_rejects_missing_links_and_anchors(tmp_path: Path, monkeypatch):
    spec = spec_from_file_location("legacy_docs_check", ROOT / "scripts/check_docs.py")
    checker = module_from_spec(spec)
    spec.loader.exec_module(checker)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "DOCS", tmp_path / "docs")
    for name in ("README.md", "AGENTS.md", "CLAUDE.md", "web/README.md", "web/AGENTS.md",
                 "web/CLAUDE.md", "docs/README.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    index = tmp_path / "docs/README.md"
    index.write_text("[missing](absent.md)", encoding="utf-8")
    assert checker.main("legacy-flat") == 1
    index.write_text("[bad anchor](target.md#absent)", encoding="utf-8")
    (tmp_path / "docs/target.md").write_text("# Present\n", encoding="utf-8")
    assert checker.main("legacy-flat") == 1
    index.write_text("[valid](target.md#present)", encoding="utf-8")
    assert checker.main("legacy-flat") == 0


@pytest.mark.parametrize("private_present", [False, True])
def test_only_named_local_material_may_use_literal_index_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_present: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = spec_from_file_location("docs_check_under_test", ROOT / "scripts/check_docs.py")
    assert spec is not None and spec.loader is not None
    checker = module_from_spec(spec)
    spec.loader.exec_module(checker)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "DOCS", tmp_path / "docs")
    for name in (
        "README.md", "AGENTS.md", "CLAUDE.md", "web/README.md", "web/AGENTS.md",
        "web/CLAUDE.md", "src/procurement/AGENTS.md", "docs/15-implementation-plan.md",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "docs/README.md").write_text(
        "- [plan](15-implementation-plan.md)\n- [history](history/README.md)\n", encoding="utf-8"
    )
    legacy = tmp_path / "docs/history/legacy"
    legacy.mkdir(parents=True)
    (legacy.parent / "README.md").write_text("- [legacy](legacy/README.md)\n", encoding="utf-8")
    (legacy / "README.md").write_text("- `ии.docx` — retained local only.\n", encoding="utf-8")
    if private_present:
        (legacy / "ии.docx").write_bytes(b"synthetic private material")
    assert checker.main() == 0
    capsys.readouterr()

    (legacy / "another.docx").write_bytes(b"synthetic unindexed document")
    with (legacy / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("- `another.docx` — not an approved local-only exception.\n")
    assert checker.main() == 1
    assert "unindexed" in capsys.readouterr().out
