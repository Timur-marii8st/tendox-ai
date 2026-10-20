"""One exact-query retry after human verification; never delete origin holds."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from procurement.sources.supplier_serp import SearchEngine, source_url

VERSION = "supplier-captcha-retry-v1"


def retain_proof(profile: Path, session_id: str, content: bytes) -> None:
    from uuid import UUID

    from procurement.sources.supplier_serp import MAX_DOM_BYTES
    from procurement.sources.supplier_serp_browser import _private_dir, _private_file

    if str(UUID(session_id)) != session_id or not 0 < len(content) <= MAX_DOM_BYTES:
        raise ValueError("CAPTCHA_EVIDENCE_INVALID")
    directory = profile / "manual-dom"
    _private_dir(directory)
    target = directory / (session_id + ".html")
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("CAPTCHA_EVIDENCE_CONFLICT")
        return
    with target.open("xb") as handle:
        _private_file(target)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def pacing_paths(root: Path, profile: Path, engine: SearchEngine) -> tuple[Path, Path]:
    origin = urlsplit(source_url(engine, "x производитель поставщик купить оптом")).netloc
    digest = hashlib.sha256(origin.encode()).hexdigest()
    return root.resolve() / "state/global" / f"{digest}.json", profile / "pacing.json"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def issue_retry(
    root: Path,
    profile: Path,
    engine: SearchEngine,
    query: str,
    session_id: str,
    snapshots: tuple[str, str],
) -> int:
    from procurement.sources.supplier_serp_browser import _lease, _private_file

    global_path, tenant_path = pacing_paths(root, profile, engine)
    now = datetime.now(UTC)
    with (
        _lease(profile / "profile.lock"),
        _lease(global_path.with_suffix(".lock")),
        _lease(profile / "pacing.lock"),
    ):
        if tuple(file_sha(p) for p in (global_path, tenant_path)) != snapshots:
            raise ValueError("CAPTCHA_PACING_CHANGED")
        next_times = []
        for path in (global_path, tenant_path):
            raw = json.loads(path.read_text())["next_allowed_at"]
            if raw is not None:
                next_times.append(datetime.fromisoformat(raw))
        retry_at = max([now, *next_times])
        payload = {
            "version": VERSION,
            "engine": engine.value,
            "session_id": session_id,
            "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "pacing_sha256": list(snapshots),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
        }
        target = profile / "human-retry.json"
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            _private_file(temporary)
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return max(0, math.ceil((retry_at - now).total_seconds()))


def take_retry(
    profile: Path, engine: SearchEngine, query: str | None, paths: tuple[Path, Path], now: datetime
) -> bool:
    """Caller holds profile and pacing leases. Consume before any source navigation."""
    target = profile / "human-retry.json"
    if query is None or not target.exists():
        return False
    try:
        payload = json.loads(target.read_text())
        expires = datetime.fromisoformat(payload["expires_at"])
        valid = (
            payload["version"] == VERSION
            and payload["engine"] == engine.value
            and payload["query_sha256"] == hashlib.sha256(query.encode()).hexdigest()
            and expires.tzinfo is not None
            and now < expires <= now + timedelta(minutes=5)
            and payload["pacing_sha256"] == [file_sha(p) for p in paths]
        )
    except (ValueError, KeyError, TypeError, OSError):
        valid = False
    target.unlink(missing_ok=True)
    return valid
