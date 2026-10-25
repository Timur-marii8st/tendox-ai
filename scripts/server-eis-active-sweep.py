"""Resumable query-free active44 discovery; no claim of a complete national census."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import create_engine

NAME = "active_sweep_hybrid"
if NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        NAME, Path(__file__).with_name("server-eis-hybrid-recovery.py")
    )
    hybrid = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = hybrid
    spec.loader.exec_module(hybrid)
else:
    hybrid = sys.modules[NAME]

ROOT = hybrid.ROOT.parent / "active-sweep" / hybrid.COMPANY
MAX_PARTITIONS = 256
MAX_ATTEMPTS = 8


class Partition(hybrid.Evidence):
    queue: hybrid.State
    status: Literal[
        "PENDING",
        "SCANNING",
        "SPLIT",
        "OBSERVED_PAGES",
        "SATURATED_UNKNOWN",
        "UNPARSED_UNKNOWN",
        "LIMIT_UNKNOWN",
    ] = "PENDING"
    touched: int = Field(default=0, ge=0)
    pages_observed: int = Field(default=0, ge=0)
    count_floor: int | None = Field(default=None, ge=0)
    count_exact: bool = False
    count_changed: bool = False
    children: tuple[str, ...] = Field(default=(), max_length=2)


class DeferredObservation(hybrid.Evidence):
    partition_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    item: hybrid.QueueItem


class Sweep(hybrid.Evidence):
    schema_version: Literal["eis-active-sweep-v1"] = "eis-active-sweep-v1"
    company_id: Literal["local-eis-supplier"] = hybrid.COMPANY
    as_of: date
    partitions: dict[str, Partition] = Field(max_length=MAX_PARTITIONS)
    deferred: dict[str, DeferredObservation] = Field(
        default_factory=dict, max_length=hybrid.MAX_QUEUE
    )
    sequence: int = Field(default=0, ge=0)
    drain_cursor: int = Field(default=0, ge=0)
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def bound(self):
        numbers = []
        for key, part in self.partitions.items():
            scope = part.queue.scope
            if key != scope.key() or not scope.all_active or scope.publish_to > self.as_of:
                raise ValueError("PARTITION_SCOPE_MISMATCH")
            if (part.status == "SPLIT") != (len(part.children) == 2):
                raise ValueError("SPLIT_BINDING_INVALID")
            if part.children:
                expected = split_scope(scope)
                if expected is None or tuple(s.key() for s in expected) != part.children:
                    raise ValueError("SPLIT_BINDING_INVALID")
                if any(k not in self.partitions for k in part.children):
                    raise ValueError("SPLIT_CHILD_MISSING")
            numbers.extend(part.queue.items)
        if len(numbers) > hybrid.MAX_QUEUE or len(numbers) != len(set(numbers)):
            raise ValueError("GLOBAL_QUEUE_CAPACITY_OR_DUPLICATE")
        owners = {n: i for p in self.partitions.values() for n, i in p.queue.items.items()}
        for number, fresh in self.deferred.items():
            if (
                number not in owners
                or owners[number].pending_audit is None
                or fresh.partition_key not in self.partitions
                or number != fresh.item.candidate.purchase_number
                or fresh.item.pending_audit is not None
            ):
                raise ValueError("DEFERRED_OBSERVATION_INVALID")
        return self


def apply_deferred(state: Sweep) -> Sweep:
    parts = dict(state.partitions)
    deferred = dict(state.deferred)
    for number, fresh in state.deferred.items():
        owner = next(k for k, p in parts.items() if number in p.queue.items)
        old = parts[owner].queue.items[number]
        if old.pending_audit is not None:
            continue
        del deferred[number]
        if old.status == "INDEXED":
            continue
        items = dict(parts[owner].queue.items)
        del items[number]
        parts[owner] = parts[owner].model_copy(
            update={"queue": parts[owner].queue.model_copy(update={"items": items})}
        )
        target = parts[fresh.partition_key]
        items = dict(target.queue.items)
        items[number] = old.model_copy(
            update={
                "candidate": fresh.item.candidate,
                "last_seen": fresh.item.last_seen,
                "source_sha256": fresh.item.source_sha256,
                "observation_sha256": fresh.item.observation_sha256,
            }
        )
        parts[fresh.partition_key] = target.model_copy(
            update={"queue": target.queue.model_copy(update={"items": items})}
        )
    return state.model_copy(update={"partitions": parts, "deferred": deferred})


def initial(as_of: date) -> Sweep:
    scope = hybrid.Scope(query="", all_active=True, publish_to=as_of, max_pages=20)
    return Sweep(as_of=as_of, partitions={scope.key(): Partition(queue=hybrid.State(scope=scope))})


def split_scope(scope):
    lo, hi = scope.publish_from, scope.publish_to
    if lo == hi:
        return None
    # Preserve the unbounded historical tail; never invent a start date for EIS.
    pivot = hi - timedelta(days=30) if lo is None else lo + (hi - lo) // 2
    return (
        scope.model_copy(update={"publish_from": pivot + timedelta(days=1)}),
        scope.model_copy(update={"publish_to": pivot}),
    )


def source_count(raw: bytes) -> tuple[int | None, bool]:
    nodes = [
        n.text().strip()
        for n in hybrid._parse_html(raw).walk()
        if "search-results__total" in n.classes()
    ]
    if len(nodes) != 1:
        return None, False
    match = re.fullmatch(
        r"(?:(Более|более)\s+)?([0-9][0-9\s\u00a0\u202f]*)\s+запис(?:ей|и|ь)", nodes[0]
    )
    return (int(re.sub(r"\s", "", match[2])), match[1] is None) if match else (None, False)


def choose_partition(state: Sweep) -> str | None:
    pending = [
        (key, p) for key, p in state.partitions.items() if p.status in {"PENDING", "SCANNING"}
    ]
    return (
        min(
            pending,
            key=lambda item: (
                item[1].touched,
                -item[1].queue.scope.publish_to.toordinal(),
                item[0],
            ),
        )[0]
        if pending
        else None
    )


def observe(
    state: Sweep, key: str, page, indexed: frozenset[str], count: tuple[int | None, bool]
) -> Sweep:
    part = state.partitions[key]
    parts = dict(state.partitions)
    items = dict(part.queue.items)
    protected_audit = set()
    deferred = dict(state.deferred)
    owners = {
        number: owner for owner, value in state.partitions.items() for number in value.queue.items
    }
    for candidate in page.candidates:
        number = candidate.purchase_number
        owner = owners.get(number)
        if owner is None:
            continue
        old = parts[owner].queue.items[number]
        if old.pending_audit is not None:
            # Audit debt retains the exact original observation/source binding.
            protected_audit.add(number)
            deferred[number] = DeferredObservation(
                partition_key=key,
                item=old.model_copy(
                    update={
                        "candidate": candidate,
                        "last_seen": page.observed_at,
                        "source_sha256": page.source_sha256,
                        "observation_sha256": hashlib.sha256(
                            page.model_dump_json().encode()
                        ).hexdigest(),
                        "pending_audit": None,
                    }
                ),
            )
            continue
        if owner == key:
            continue
        previous = dict(parts[owner].queue.items)
        del previous[number]
        parts[owner] = parts[owner].model_copy(
            update={"queue": parts[owner].queue.model_copy(update={"items": previous})}
        )
        items[number] = old.model_copy(
            update={
                "candidate": candidate,
                "last_seen": page.observed_at,
                "source_sha256": page.source_sha256,
                "observation_sha256": hashlib.sha256(page.model_dump_json().encode()).hexdigest(),
            }
        )
    queue = hybrid.merge_page(
        part.queue.model_copy(update={"items": items}), page, indexed | frozenset(protected_audit)
    )
    total, exact = count
    if total is not None and exact and total < page.scanned_cards:
        raise ValueError("SOURCE_COUNT_INVALID")
    changed = part.count_changed or (
        part.pages_observed > 0 and (part.count_floor, part.count_exact) != count
    )
    updated = part.model_copy(
        update={
            "queue": queue,
            "touched": state.sequence + 1,
            "pages_observed": part.pages_observed + 1,
            "count_floor": total,
            "count_exact": exact,
            "count_changed": changed,
            "status": "SCANNING",
        }
    )
    overflow = (total is not None and (total > 1000 or (total >= 1000 and not exact))) or (
        page.page_number == 20 and page.scanned_cards == 50
    )
    if page.unparsed_cards:
        updated = updated.model_copy(update={"status": "UNPARSED_UNKNOWN"})
    elif overflow:
        scopes = split_scope(part.queue.scope)
        if scopes is None:
            updated = updated.model_copy(
                update={
                    "status": "SATURATED_UNKNOWN"
                    if page.page_number == 20 or page.scanned_cards < 50
                    else "SCANNING"
                }
            )
        elif len(parts) + 2 > MAX_PARTITIONS:
            updated = updated.model_copy(update={"status": "LIMIT_UNKNOWN"})
        else:
            children = tuple(s.key() for s in scopes)
            if any(k in parts for k in children):
                raise ValueError("PARTITION_COLLISION")
            for scope in scopes:
                parts[scope.key()] = Partition(queue=hybrid.State(scope=scope))
            updated = updated.model_copy(update={"status": "SPLIT", "children": children})
    elif page.scanned_cards < 50:
        updated = updated.model_copy(update={"status": "OBSERVED_PAGES"})
    parts[key] = updated
    # All queue additions, children and the parent checkpoint commit together.
    return Sweep.model_validate(
        state.model_copy(
            update={"partitions": parts, "deferred": deferred, "sequence": state.sequence + 1}
        ).model_dump()
    )


def load(path: Path, as_of: date) -> Sweep:
    if path.is_symlink() or (path.exists() and path.stat().st_size > 8 * 1024**2):
        raise ValueError("SWEEP_STATE_UNSAFE")
    state = Sweep.model_validate_json(path.read_bytes()) if path.exists() else initial(as_of)
    if state.as_of != as_of:
        raise ValueError("SWEEP_DATE_MISMATCH")
    return state


def save(path: Path, state: Sweep) -> None:
    validated = Sweep.model_validate(state.model_dump())
    hybrid.atomic_write(path, validated.model_dump_json(indent=2).encode())


def bind_cycle(root: Path, as_of: date) -> None:
    path = root / "cycle.json"
    expected = {"company_id": hybrid.COMPANY, "as_of": as_of.isoformat()}
    if path.is_symlink() or (path.exists() and path.stat().st_size > 512):
        raise ValueError("CYCLE_PATH_UNSAFE")
    if path.exists():
        if json.loads(path.read_bytes()) != expected:
            raise ValueError("SWEEP_CYCLE_MISMATCH")
    else:
        hybrid.atomic_write(path, json.dumps(expected, sort_keys=True).encode())


def safe_reason(error: Exception) -> str:
    reason = str(error)
    return reason if re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", reason) else "SWEEP_UNAVAILABLE"


class Report(hybrid.Evidence):
    schema_version: Literal["eis-active-sweep-run-v1"] = "eis-active-sweep-run-v1"
    company_id: Literal["local-eis-supplier"] = hybrid.COMPANY
    as_of: date
    observed_at: hybrid.AwareDatetime
    applied: bool
    discovery_status: Literal["OBSERVED", "DEFERRED", "UNAVAILABLE", "NO_PENDING_PARTITION"]
    discovery_reason: str | None = None
    page: hybrid.Page | None = None
    partition_key: str | None = None
    missing_on_page: tuple[str, ...] = ()
    outcomes: tuple[hybrid.RecoveryOutcome, ...] = Field(max_length=MAX_ATTEMPTS)
    partitions: dict[str, int]
    queue_size: int
    pending_queue: int
    seconds: float
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


async def drain_queues(
    state: Sweep,
    folder: Path,
    path: Path,
    storage,
    recovery,
    joint,
    token,
    transport,
    *,
    budget=None,
    max_attempts=MAX_ATTEMPTS,
):
    outcomes = []
    budget = budget if budget is not None else recovery.Budget()
    keys = sorted(state.partitions)
    # Bound housekeeping too; one source attempt per selected partition is fair.
    for _ in range(min(32, max(8, len(keys)))):
        if len(outcomes) >= max_attempts or time.monotonic() >= budget.deadline:
            break
        candidates = [
            k for k in keys if hybrid.due_items(state.partitions[k].queue, datetime.now(UTC))
        ]
        if not candidates:
            break
        key = candidates[state.drain_cursor % len(candidates)]
        state = state.model_copy(update={"drain_cursor": state.drain_cursor + 1})
        save(path, state)
        queue = state.partitions[key].queue

        def persist(_path, raw, state=state, key=key):
            # Bind the leaf update into a single global checkpoint, including attempts.
            leaf = hybrid.State.model_validate_json(raw)
            parts = dict(state.partitions)
            parts[key] = parts[key].model_copy(update={"queue": leaf})
            save(path, apply_deferred(state.model_copy(update={"partitions": parts})))

        queue, result = await hybrid.drain(
            storage,
            queue,
            folder / key / "state.json",
            recovery=recovery,
            joint=joint,
            token=token,
            transport=transport,
            max_attempts=1,
            budget=budget,
            persist=persist,
        )
        parts = dict(state.partitions)
        parts[key] = parts[key].model_copy(update={"queue": queue})
        state = apply_deferred(state.model_copy(update={"partitions": parts}))
        save(path, state)
        outcomes.extend(result)
        if not result and not joint.can_start(pending_reconciliation=("44", "223")):
            break
    return state, outcomes


async def run(as_of: date, *, apply: bool, root: Path = ROOT) -> Report:
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    if as_of > today or (today - as_of).days > 7:
        raise ValueError("SWEEP_DATE_EXPIRED")
    hybrid.guarded_store(root)
    bind_cycle(root, as_of)
    folder = root / as_of.isoformat()
    folder.mkdir(exist_ok=True, mode=0o700)
    path = folder / "sweep.json"
    state = load(path, as_of)
    recovery = hybrid.recovery_module()
    engine = create_engine(
        os.environ["DATABASE_URL"],
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
    )
    storage = hybrid.PostgresStorage(engine)
    started = time.monotonic()
    outcomes = []
    page = None
    missing = ()
    status, reason = "NO_PENDING_PARTITION", None
    try:
        recovery.source_guard(storage)
        with hybrid.JointStartBudget(
            Path(os.environ["EIS_BROWSER_STATE_DIR"]), hybrid.COMPANY
        ) as joint:
            budget = recovery.Budget()
            # Recovery is independent of availability of a new public page.
            if apply:
                async with recovery.eis_browser_transport() as transport:
                    state, outcomes = await drain_queues(
                        state,
                        folder,
                        path,
                        storage,
                        recovery,
                        joint,
                        os.environ["EIS_GETDOCS_IP_TOKEN"],
                        transport,
                        budget=budget,
                    )
            key = choose_partition(state)
            if key is not None:
                try:
                    if not joint.can_start(pending_reconciliation=("44", "223")):
                        raise ValueError("JOINT_BUDGET_EXHAUSTED")
                    part = state.partitions[key]
                    raw = await hybrid.fetch_page(
                        hybrid.search_url(part.queue.scope, today, part.queue.next_page),
                        wait_seconds=61,
                    )
                    if os.environ["EIS_GETDOCS_IP_TOKEN"].encode() in raw:
                        raise ValueError("SOURCE_CONTENT_REJECTED")
                    page = hybrid.parse_page(
                        raw, part.queue.scope, today, part.queue.next_page, datetime.now(UTC)
                    )
                    indexed = hybrid.read_present(
                        storage, tuple(c.purchase_number for c in page.candidates)
                    )
                    missing = tuple(
                        c.purchase_number
                        for c in page.candidates
                        if c.purchase_number not in indexed
                    )
                    next_state = observe(state, key, page, indexed, source_count(raw))
                    evidence = folder / key
                    evidence.mkdir(exist_ok=True, mode=0o700)
                    hybrid.atomic_write(evidence / (page.source_sha256 + ".html"), raw)
                    hybrid.atomic_write(
                        evidence
                        / (hashlib.sha256(page.model_dump_json().encode()).hexdigest() + ".json"),
                        page.model_dump_json(indent=2).encode(),
                    )
                    if apply:
                        save(path, next_state)
                    state = next_state
                    status = "OBSERVED"
                except Exception as error:
                    reason = safe_reason(error)
                    status = (
                        "DEFERRED"
                        if reason
                        in {
                            "ROBOTS_CRAWL_DELAY",
                            "SOURCE_BUSY",
                            "JOINT_BUDGET_EXHAUSTED",
                            "GLOBAL_QUEUE_CAPACITY_OR_DUPLICATE",
                            "QUEUE_CAPACITY_REACHED",
                        }
                        else "UNAVAILABLE"
                    )
                    page = None
                    missing = ()
            if apply and status == "OBSERVED" and len(outcomes) < MAX_ATTEMPTS:
                async with recovery.eis_browser_transport() as transport:
                    state, additional = await drain_queues(
                        state,
                        folder,
                        path,
                        storage,
                        recovery,
                        joint,
                        os.environ["EIS_GETDOCS_IP_TOKEN"],
                        transport,
                        budget=budget,
                        max_attempts=MAX_ATTEMPTS - len(outcomes),
                    )
                    outcomes.extend(additional)
            counts = {}
            for part in state.partitions.values():
                counts[part.status] = counts.get(part.status, 0) + 1
            items = [i for p in state.partitions.values() for i in p.queue.items.values()]
            report = Report(
                as_of=as_of,
                observed_at=datetime.now(UTC),
                applied=apply,
                discovery_status=status,
                discovery_reason=reason,
                page=page,
                partition_key=key,
                missing_on_page=missing,
                outcomes=tuple(outcomes),
                partitions=counts,
                queue_size=len(items),
                pending_queue=sum(i.status != "INDEXED" for i in items),
                seconds=round(time.monotonic() - started, 3),
            )
            hybrid.atomic_write(
                folder / ("run-" + uuid4().hex + ".json"), report.model_dump_json(indent=2).encode()
            )
            return report
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if os.environ.get("EIS_HYBRID_IMPORT_LEASE_HELD") != "1":
            raise ValueError("IMPORT_LEASE_REQUIRED")
        print(asyncio.run(run(args.as_of, apply=args.apply)).model_dump_json())
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "company_id": hybrid.COMPANY,
                    "status": "UNKNOWN",
                    "reason": safe_reason(error),
                    "coverage": "UNKNOWN",
                }
            )
        )
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
