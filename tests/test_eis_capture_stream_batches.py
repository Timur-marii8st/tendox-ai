from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from procurement.sources import eis_search_capture as codec
from procurement.storage import eis_search_capture as storage

ROOT = Path(__file__).resolve().parents[1]


def _spec() -> codec.RelationSpec:
    return codec.RelationSpec(
        name="eis_notice_versions",
        role="RUNTIME_44",
        columns=(
            codec.ColumnSpec(name="company_id", kind="TEXT", sql_type="TEXT", nullable=False),
            codec.ColumnSpec(name="payload", kind="JSON", sql_type="JSONB", nullable=False),
        ),
        primary_key=("company_id",),
        selection="FULL_TENANT",
        max_rows=1_000_000,
    )


@pytest.mark.parametrize(
    "payload",
    [
        [0] * 10_000,
        {"escaped": '\x00"\\\n' * 20_000, "unicode": "бумага😀e\u0301" * 10_000},
        [None, True, False, Decimal("1.200"), {"nested": [[], {}, -1]}] * 2_000,
        {"small": "бумага"},
    ],
)
def test_dense_typed_rows_have_bounded_chunks_and_exact_historical_bytes(payload: object) -> None:
    spec = _spec()
    row = {"company_id": "local-eis-supplier", "payload": payload}
    expected = codec.encode_row(spec, row)
    chunks = list(codec.iter_encoded_row(spec, row))
    assert chunks and all(0 < len(chunk) <= 65_536 for chunk in chunks)
    assert len(chunks) == (len(expected) + 65_535) // 65_536
    assert b"".join(chunks) == expected
    assert expected.endswith(b"\n")
    _, decoded = codec.decode_row(spec, expected)
    assert decoded == row


def test_first_chunk_does_not_consume_all_canonical_output(monkeypatch: pytest.MonkeyPatch) -> None:
    consumed = 0

    def canonical(_payload: object):
        nonlocal consumed
        for _ in range(100_000):
            consumed += 1
            yield b"x"

    monkeypatch.setattr(codec, "iter_canonical_bytes", canonical)
    chunks = codec.iter_encoded_row(_spec(), {"company_id": "tenant", "payload": []})
    assert next(chunks) == b"x" * 65_536
    assert consumed == 65_536
    chunks.close()


def _writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free):
    plan, _ = codec.load_capture_plan(ROOT / "scripts/benchmarks/eis-search-capture-plan.v3.json")
    assert isinstance(plan, codec.CapturePlanV3)

    def create(path: Path) -> tuple[Any, tuple[int, int]]:
        stream = path.open("x+b")
        facts = path.stat()
        return stream, (facts.st_dev, facts.st_ino)

    def remove(path: Path, identity: tuple[int, int]) -> None:
        facts = path.stat()
        assert (facts.st_dev, facts.st_ino) == identity
        path.unlink()

    monkeypatch.setattr(storage, "_create_exclusive_transient", create)
    monkeypatch.setattr(storage, "_remove_same_transient", remove)
    monkeypatch.setattr(storage.shutil, "disk_usage", free)
    return storage._RelationWriterV3(
        tmp_path, _spec(), storage._PackageBudget(plan, time.monotonic()), plan
    )


def test_pending_disk_checks_scale_with_physical_writes_and_keep_canonical_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def free(_path: Path) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(free=100 * 1024**3)

    writer = _writer(tmp_path, monkeypatch, free)
    row = {"company_id": "local-eis-supplier", "payload": [0] * 10_000}
    expected = codec.encode_row(_spec(), row)
    size, digest, stream = writer._spool_row(row)
    assert calls == (len(expected) + 65_535) // 65_536
    assert stream.read() == expected
    assert size == writer.pending_peak_bytes == len(expected)
    assert digest == hashlib.sha256(expected).hexdigest()
    assert writer._cleanup_pending() is None
    assert not (tmp_path / ".fragment-row.pending").exists()


def test_disk_full_stops_before_next_batch_and_cleans_pending_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def free(_path: Path) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(free=100 * 1024**3 if calls == 1 else 0)

    writer = _writer(tmp_path, monkeypatch, free)
    with pytest.raises(storage.CaptureCollectionError, match="FREE_DISK_LIMIT_DURING_ROW"):
        writer.write({"company_id": "local-eis-supplier", "payload": [0] * 10_000})
    assert calls == 2
    assert writer.pending_peak_bytes == 65_536
    assert writer.logical_rows == 0
    assert not writer.fragmented_rows
    assert not (tmp_path / ".fragment-row.pending").exists()
