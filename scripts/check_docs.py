"""Check local documentation navigation without network or runtime dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LINK = re.compile(r"\]\(([^\n)]+)\)")
LIMITS = {
    "README.md": 120,
    "AGENTS.md": 100,
    "docs/README.md": 100,
    "docs/15-implementation-plan.md": 120,
}
# Character budgets bound context even when paragraphs are compressed into long lines.
CHAR_LIMITS = {
    "README.md": 6000,
    "AGENTS.md": 7000,
    "CLAUDE.md": 10000,
    "docs/README.md": 4000,
    "docs/15-implementation-plan.md": 6500,
}
# This retained user document is deliberately excluded from release snapshots.
# Its literal local-only index entry must work both with and without the file.
LOCAL_ONLY_DOCS = frozenset({"docs/history/legacy/ии.docx"})


def local_target(source: Path, raw: str) -> tuple[Path, str] | None:
    """Resolve a local Markdown destination; skip external URLs."""
    raw = raw.strip()
    if raw.startswith("<"):
        raw = raw[1 : raw.index(">")]
    else:
        # Optional quoted Markdown link title is not part of the destination.
        raw = re.split(r"\s+[\"']", raw, maxsplit=1)[0]
    url = urlsplit(raw)
    if url.scheme or url.netloc:
        return None
    target = (source.parent / unquote(url.path)).resolve() if url.path else source
    return target, unquote(url.fragment)


def heading_anchors(body: str) -> set[str]:
    """Collect GitHub-style heading slugs and explicit HTML ids/anchors."""
    anchors = set(re.findall(r"\b(?:id|name)=[\"']([^\"']+)[\"']", body))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)", body, re.MULTILINE):
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        heading = re.sub(r"<[^>]+>|[`*_]", "", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def numeric_key(path: Path) -> tuple[int, str]:
    match = re.match(r"(\d+)", path.name)
    return (int(match[1]) if match else 999999, path.name)


def main(layout: str = "modern") -> int:
    """Verify files, anchors, full sorted indices and bounded entry points."""
    sources = [
        *sorted(DOCS.rglob("*.md")),
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "web/README.md",
        ROOT / "web/AGENTS.md",
        ROOT / "web/CLAUDE.md",
        *([ROOT / "src/procurement/AGENTS.md"] if layout == "modern" else []),
    ]
    errors: list[str] = []
    links = 0
    anchors_cache: dict[Path, set[str]] = {}
    for source in sources:
        body = source.read_text(encoding="utf-8")
        for raw in LINK.findall(body):
            resolved = local_target(source, raw)
            if resolved is None:
                continue
            target, fragment = resolved
            links += 1
            if not target.exists():
                errors.append(f"{source.relative_to(ROOT)}: missing {raw}")
            elif fragment and target.is_file() and target.suffix == ".md":
                if target not in anchors_cache:
                    anchors_cache[target] = heading_anchors(target.read_text(encoding="utf-8"))
                if fragment not in anchors_cache[target]:
                    errors.append(f"{source.relative_to(ROOT)}: missing anchor {raw}")

    folders = [DOCS, *(p for p in DOCS.rglob("*") if p.is_dir())] if layout == "modern" else []
    for folder in sorted(folders):
        index = folder / "README.md"
        if not index.exists():
            errors.append(f"{folder.relative_to(ROOT)}: missing README.md")
            continue
        expected = {
            p.resolve()
            for p in folder.iterdir()
            if p.is_file() and p.name not in {"README.md", "AGENTS.md"}
        }
        expected.update(p.resolve() / "README.md" for p in folder.iterdir() if p.is_dir())
        actual: list[Path] = []
        index_body = index.read_text(encoding="utf-8")
        entries = "\n".join(
            line for line in index_body.splitlines() if line.startswith(("- [", "| "))
        )
        for raw in LINK.findall(entries):
            resolved = local_target(index, raw)
            if resolved is not None and resolved[0] in expected:
                actual.append(resolved[0])
        for target in expected:
            if (
                target.relative_to(ROOT).as_posix() in LOCAL_ONLY_DOCS
                and f"- `{target.name}` —" in index_body
            ):
                actual.append(target)
        for missing in sorted(expected - set(actual)):
            errors.append(f"{index.relative_to(ROOT)}: unindexed {missing.relative_to(ROOT)}")
        if len(actual) != len(set(actual)):
            errors.append(f"{index.relative_to(ROOT)}: duplicate file entries")
        # Direct numbered files should be in numeric order, not lexicographic 100 before 11.
        numbered = [p for p in actual if p.parent == folder and re.match(r"\d", p.name)]
        if numbered != sorted(numbered, key=numeric_key):
            errors.append(f"{index.relative_to(ROOT)}: numbered files are not sorted")

    for name, limit in (LIMITS.items() if layout == "modern" else []):
        count = len((ROOT / name).read_text(encoding="utf-8").splitlines())
        if count > limit:
            errors.append(f"{name}: {count} lines exceeds entry-point budget {limit}")

    for name, limit in (CHAR_LIMITS.items() if layout == "modern" else []):
        count = len((ROOT / name).read_text(encoding="utf-8"))
        if count > limit:
            errors.append(f"{name}: {count} characters exceeds entry-point budget {limit}")

    if errors:
        print("Documentation check FAIL:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(
        f"Documentation check PASS: {len(sources)} Markdown files, {links} local links, "
        + (
            f"{len(folders)} complete indices; entry-point budgets respected."
            if layout == "modern"
            else "legacy-flat local links and anchors verified."
        )
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", choices=("modern", "legacy-flat"), default="modern")
    sys.exit(main(parser.parse_args().layout))
