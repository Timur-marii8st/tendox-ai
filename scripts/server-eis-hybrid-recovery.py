"""Bounded 44-FZ public discovery -> durable missing queue -> stock number intake.

S201 needs an unrelated NO_DATA report; this entry point supplies independently
verified active-search observations without changing XML admission or source limits.
"""

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
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, model_validator
from sqlalchemy import create_engine, select, text

from procurement.eis_joint_budget import JointStartBudget
from procurement.sources.eis_public import (
    _browser_html,
    _deadline_date,
    _host_lease,
    _official_url,
    _parse_html,
    public_search_url,
)
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
ROOT = Path("/var/lib/eis-browser/hybrid") / COMPANY
MAX_QUEUE = 2000
MAX_STORE_BYTES = 256 * 1024**2
MAX_ATTEMPTS = 3


def recovery_module():
    name = "hybrid_stock_recovery"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("server-eis-public-candidate-recovery.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("STOCK_RECOVERY_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RecoveryOutcome = recovery_module().Outcome


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(Evidence):
    company_id: Literal["local-eis-supplier"] = COMPANY
    query: str = Field(min_length=0, max_length=120)
    max_pages: int = Field(default=3, ge=1, le=20)
    law: Literal["44"] = "44"
    all_active: Literal[True] | None = None
    publish_from: date | None = None
    publish_to: date | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.query != " ".join(self.query.split()):
            raise ValueError("QUERY_NOT_NORMALIZED")
        if self.all_active:
            if self.query or self.publish_to is None:
                raise ValueError("ACTIVE_SCOPE_INVALID")
            if self.publish_from is not None and self.publish_from > self.publish_to:
                raise ValueError("PUBLICATION_RANGE_INVALID")
        elif not self.query or self.publish_from is not None or self.publish_to is not None:
            raise ValueError("QUERY_SCOPE_INVALID")
        if self.query:
            public_search_url(self.query)
        return self

    def key(self) -> str:
        return hashlib.sha256(self.model_dump_json(exclude_none=True).encode()).hexdigest()


class Candidate(Evidence):
    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    detail_url: str
    deadline_day: date
    locator: str

    @model_validator(mode="after")
    def bound(self):
        if _official_url(self.detail_url, ("/epz/order/notice/",)) != self.detail_url or parse_qs(
            urlsplit(self.detail_url).query
        ).get("regNumber") != [self.purchase_number]:
            raise ValueError("CANDIDATE_URL_MISMATCH")
        return self


class Page(Evidence):
    company_id: Literal["local-eis-supplier"] = COMPANY
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: AwareDatetime
    day: date
    page_number: int = Field(ge=1, le=20)
    search_url: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scanned_cards: int = Field(ge=0, le=50)
    unparsed_cards: int = Field(ge=0, le=50)
    candidates: tuple[Candidate, ...] = Field(max_length=50)
    coverage: Literal["BOUNDED_QUERY_PAGE", "BOUNDED_ACTIVE_PARTITION_PAGE"] = "BOUNDED_QUERY_PAGE"

    @model_validator(mode="after")
    def unique(self):
        if len({c.purchase_number for c in self.candidates}) != len(self.candidates):
            raise ValueError("DUPLICATE_PUBLIC_NUMBER")
        if len(self.candidates) + self.unparsed_cards != self.scanned_cards:
            raise ValueError("PAGE_ACCOUNTING_MISMATCH")
        return self


def search_url(scope: Scope, day: date, page: int) -> str:
    if not 1 <= page <= scope.max_pages:
        raise ValueError("PAGE_SCOPE_INVALID")
    base = public_search_url(scope.query or "бумага", page, page_size=50)
    params = {k: v[0] for k, v in parse_qs(urlsplit(base).query).items()}
    params.pop("fz223")
    params["searchString"] = scope.query
    for name, value in (
        ("publishDateFrom", scope.publish_from),
        ("publishDateTo", scope.publish_to),
    ):
        if value is not None:
            params[name] = value.strftime("%d.%m.%Y")
    params.update(
        sortBy="PUBLISH_DATE" if scope.all_active else "PRICE",
        sortDirection="false",
        applSubmissionCloseDateFrom=day.strftime("%d.%m.%Y"),
    )
    return base.split("?", 1)[0] + "?" + urlencode(params)


def parse_page(raw: bytes, scope: Scope, day: date, page: int, now: datetime) -> Page:
    tree = _parse_html(raw)
    visible = tree.text().casefold()
    if any(
        s in visible
        for s in (
            "подтвердите, что вы не робот",
            "verify you are human",
            "доступ временно ограничен",
        )
    ):
        raise ValueError("BLOCKED_PAGE")
    expected = dict(
        searchString=scope.query,
        pageNumber=str(page),
        recordsPerPage="_50",
        sortBy="PUBLISH_DATE" if scope.all_active else "PRICE",
        sortDirection="false",
        applSubmissionCloseDateFrom=day.strftime("%d.%m.%Y"),
        publishDateFrom=scope.publish_from.strftime("%d.%m.%Y") if scope.publish_from else "",
        publishDateTo=scope.publish_to.strftime("%d.%m.%Y") if scope.publish_to else "",
    )
    for name, value in expected.items():
        nodes = [n for n in tree.walk() if n.tag == "input" and n.attrs.get("name") == name]
        if len(nodes) != 1 or nodes[0].attrs.get("value", "") != value:
            raise ValueError("FILTER_UNVERIFIED")
    for name in ("fz44", "fz223", "af", "ca", "pc", "pa"):
        nodes = [n for n in tree.walk() if n.tag == "input" and n.attrs.get("name") == name]
        if len(nodes) != 1 or ("checked" in nodes[0].attrs) != (name in {"fz44", "af"}):
            raise ValueError("FILTER_UNVERIFIED")
    cards = [n for n in tree.walk() if "search-registry-entry-block" in n.classes()]
    if len(cards) > 50 or (
        not cards
        and not any(s in visible for s in ("ничего не найдено", "поиск не дал результатов"))
    ):
        raise ValueError("MARKUP_CHANGED")
    candidates = []
    for i, card in enumerate(cards, 1):
        box = card.first("registry-entry__header-mid__number")
        link = next((n for n in box.walk() if n.tag == "a"), None) if box else None
        number = re.sub(r"\D", "", link.text()) if link else ""
        title = card.first("registry-entry__header-top__title")
        stage = card.first("registry-entry__header-mid__title")
        deadline = _deadline_date(card)
        if not title or "44-ФЗ" not in title.text() or not stage or stage.text() != "Подача заявок":
            raise ValueError("FILTER_UNVERIFIED")
        if deadline and deadline < day:
            raise ValueError("FILTER_UNVERIFIED")
        if scope.all_active:
            placed = re.findall(r"Размещено\s+(\d{2}\.\d{2}\.\d{4})(?!\d)", card.text())
            if len(placed) != 1:
                continue
            published = datetime.strptime(placed[0], "%d.%m.%Y").date()
            if published > scope.publish_to or (
                scope.publish_from and published < scope.publish_from
            ):
                raise ValueError("FILTER_UNVERIFIED")
        url = _official_url(link.attrs.get("href", ""), ("/epz/order/notice/",)) if link else None
        if not re.fullmatch(r"[0-9]{19,23}", number) or not url or deadline is None:
            continue
        candidates.append(
            Candidate(
                purchase_number=number,
                detail_url=url,
                deadline_day=deadline,
                locator=f"search-registry-entry-block[{i}]",
            )
        )
    return Page(
        scope_sha256=scope.key(),
        observed_at=now,
        day=day,
        page_number=page,
        search_url=search_url(scope, day, page),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        scanned_cards=len(cards),
        unparsed_cards=len(cards) - len(candidates),
        candidates=tuple(candidates),
        coverage="BOUNDED_ACTIVE_PARTITION_PAGE" if scope.all_active else "BOUNDED_QUERY_PAGE",
    )


class QueueItem(Evidence):
    candidate: Candidate
    first_seen: AwareDatetime
    last_seen: AwareDatetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pending_audit: RecoveryOutcome | None = None
    status: Literal["PENDING", "IN_FLIGHT", "RETRY", "INDEXED", "UNSUPPORTED", "EXPIRED"] = (
        "PENDING"
    )
    attempts: int = Field(default=0, ge=0)
    retry_at: AwareDatetime | None = None
    last_outcome: str | None = None


class State(Evidence):
    schema_version: Literal["eis-hybrid-state-v1"] = "eis-hybrid-state-v1"
    scope: Scope
    next_page: int = Field(default=1, ge=1, le=20)
    items: dict[str, QueueItem] = Field(default_factory=dict, max_length=MAX_QUEUE)

    @field_serializer("scope")
    def serialize_scope(self, scope):
        # V37 extra=forbid readers must still accept legacy state after rollback.
        return scope.model_dump(mode="json", exclude_none=True)

    @model_validator(mode="after")
    def bound(self):
        if self.next_page > self.scope.max_pages or any(
            k != v.candidate.purchase_number for k, v in self.items.items()
        ):
            raise ValueError("STATE_BINDING_INVALID")
        return self


def atomic_write(path: Path, raw: bytes) -> None:
    if path.is_symlink():
        raise ValueError("STATE_PATH_UNSAFE")
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        tmp.unlink(missing_ok=True)


def load_state(path: Path, scope: Scope) -> State:
    if path.is_symlink() or (path.exists() and path.stat().st_size > 4 * 1024**2):
        raise ValueError("STATE_PATH_UNSAFE")
    state = State.model_validate_json(path.read_bytes()) if path.exists() else State(scope=scope)
    if state.scope != scope:
        raise ValueError("STATE_SCOPE_MISMATCH")
    return state


def merge_page(state: State, page: Page, indexed: frozenset[str] = frozenset()) -> State:
    if page.scope_sha256 != state.scope.key() or page.page_number != state.next_page:
        raise ValueError("PAGE_STATE_MISMATCH")
    items = dict(state.items)
    for c in page.candidates:
        if c.purchase_number in items and items[c.purchase_number].pending_audit is not None:
            continue
        if c.purchase_number in indexed:
            if c.purchase_number in items:
                items[c.purchase_number] = items[c.purchase_number].model_copy(
                    update=dict(status="INDEXED", last_outcome="ALREADY_INDEXED")
                )
            continue
        old = items.get(c.purchase_number)
        if old:
            items[c.purchase_number] = old.model_copy(
                update=dict(
                    candidate=c,
                    last_seen=page.observed_at,
                    source_sha256=page.source_sha256,
                    observation_sha256=hashlib.sha256(page.model_dump_json().encode()).hexdigest(),
                )
            )
        else:
            items[c.purchase_number] = QueueItem(
                candidate=c,
                first_seen=page.observed_at,
                last_seen=page.observed_at,
                source_sha256=page.source_sha256,
                observation_sha256=hashlib.sha256(page.model_dump_json().encode()).hexdigest(),
            )
    if len(items) > MAX_QUEUE:
        raise ValueError("QUEUE_CAPACITY_REACHED")
    next_page = (
        1
        if page.scanned_cards < 50 or state.next_page == state.scope.max_pages
        else state.next_page + 1
    )
    return State(scope=state.scope, next_page=next_page, items=items)


def due_items(state: State, now: datetime) -> list[QueueItem]:
    day = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    return sorted(
        (
            i
            for i in state.items.values()
            if i.status not in {"INDEXED", "EXPIRED", "UNSUPPORTED"}
            and (
                i.pending_audit is not None
                or (
                    i.candidate.deadline_day >= day
                    and now - timedelta(days=2) <= i.last_seen <= now
                )
            )
            and (i.retry_at is None or i.retry_at <= now)
        ),
        key=lambda i: (i.attempts, i.first_seen, i.candidate.purchase_number),
    )


def outcome_item(item: QueueItem, out, now: datetime) -> QueueItem:
    indexed = out.after.latest is not None and out.after.lexical_rows > 0
    status = (
        "INDEXED"
        if indexed and out.status == "SYNCED" and out.audit_status == "RECORDED"
        else "RETRY"
    )
    return item.model_copy(
        update=dict(
            status=status,
            last_outcome=out.status,
            pending_audit=out if out.audit_status == "FAILED" else None,
            retry_at=None
            if status == "INDEXED"
            else now + timedelta(minutes=min(1440, 15 * 2 ** min(item.attempts, 7))),
        )
    )


class RunReport(Evidence):
    schema_version: Literal["eis-hybrid-run-v1"] = "eis-hybrid-run-v1"
    company_id: Literal["local-eis-supplier"] = COMPANY
    scope: Scope
    observed_at: AwareDatetime
    applied: bool
    page: Page
    missing_on_page: tuple[str, ...]
    next_page: int = Field(ge=1, le=20)
    queue_size: int = Field(ge=0, le=MAX_QUEUE)
    unresolved_queue: int = Field(ge=0, le=MAX_QUEUE)
    outcomes: tuple[RecoveryOutcome, ...] = Field(max_length=MAX_ATTEMPTS)
    seconds: float = Field(ge=0, allow_inf_nan=False)
    status: Literal["OBSERVED_ONLY", "PROCESSED_BATCH", "PARTIAL"]
    coverage: Literal["BOUNDED_QUERY_ONLY"] = "BOUNDED_QUERY_ONLY"
    national_coverage: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"


def verify_item(item: QueueItem, folder: Path, scope: Scope) -> None:
    raw_path = folder / (item.source_sha256 + ".html")
    page_path = folder / (item.observation_sha256 + ".json")
    if any(p.is_symlink() or not p.is_file() for p in (raw_path, page_path)):
        raise ValueError("QUEUE_SOURCE_UNAVAILABLE")
    if raw_path.stat().st_size > 8 * 1024**2 or page_path.stat().st_size > 128 * 1024:
        raise ValueError("QUEUE_SOURCE_SIZE_LIMIT")
    page = Page.model_validate_json(page_path.read_bytes())
    if hashlib.sha256(page.model_dump_json().encode()).hexdigest() != item.observation_sha256:
        raise ValueError("QUEUE_SOURCE_MISMATCH")
    actual = parse_page(raw_path.read_bytes(), scope, page.day, page.page_number, page.observed_at)
    if (
        actual != page
        or page.source_sha256 != item.source_sha256
        or item.candidate not in page.candidates
        or page.observed_at != item.last_seen
    ):
        raise ValueError("QUEUE_SOURCE_MISMATCH")


def guarded_store(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = list(root.rglob("*"))
    if (
        root.is_symlink()
        or any(p.is_symlink() for p in files)
        or len(files) > 5000
        or sum(p.stat().st_size for p in files if p.is_file()) > MAX_STORE_BYTES
    ):
        raise ValueError("EVIDENCE_CAPACITY_GUARD")


async def fetch_page(url: str, *, wait_seconds: int = 0) -> bytes:
    if not 0 <= wait_seconds <= 61:
        raise ValueError("PUBLIC_WAIT_LIMIT_INVALID")
    deadline = time.monotonic() + wait_seconds
    for attempt in range(2):
        with _host_lease() as retry_at:
            if retry_at is None:
                return await _browser_html(url)
        delay = max(0, (retry_at - datetime.now(UTC)).total_seconds()) + 0.1
        if attempt or time.monotonic() + delay > deadline:
            raise ValueError("ROBOTS_CRAWL_DELAY")
        await asyncio.sleep(delay)
    raise ValueError("ROBOTS_CRAWL_DELAY")


async def drain(
    storage,
    state: State,
    state_path: Path,
    *,
    recovery,
    joint,
    token: str,
    transport,
    max_attempts: int = MAX_ATTEMPTS,
    budget=None,
    persist=atomic_write,
) -> tuple[State, list]:
    if not 1 <= max_attempts <= 8:
        raise ValueError("ATTEMPT_LIMIT_INVALID")
    budget = budget if budget is not None else recovery.Budget()
    outcomes = []
    for item in due_items(state, datetime.now(UTC))[:50]:
        verify_item(item, state_path.parent, state.scope)
        number = item.candidate.purchase_number
        before = recovery.read_indexed(storage, number)
        if item.pending_audit is not None:
            out = recovery.record_outcome(storage, item.pending_audit, item.source_sha256)
            state.items[number] = outcome_item(item, out, datetime.now(UTC))
            persist(state_path, state.model_dump_json(indent=2).encode())
            continue
        if before.latest is not None and before.lexical_rows > 0:
            state.items[number] = item.model_copy(
                update=dict(status="INDEXED", last_outcome="ALREADY_INDEXED")
            )
        elif recovery.route_hint(item.candidate) not in {"ea20", "zk20", "ok20"}:
            state.items[number] = item.model_copy(
                update=dict(status="UNSUPPORTED", last_outcome="ROUTE_UNSUPPORTED")
            )
        else:
            if (
                len(outcomes) >= max_attempts
                or time.monotonic() >= budget.deadline
                or not joint.can_start(pending_reconciliation=("44", "223"))
            ):
                break
            # Durable before the network: a crash incurs a retry delay, never success.
            item = item.model_copy(
                update=dict(
                    status="IN_FLIGHT",
                    attempts=item.attempts + 1,
                    retry_at=datetime.now(UTC) + timedelta(minutes=15),
                )
            )
            state.items[number] = item
            persist(state_path, state.model_dump_json(indent=2).encode())
            out = await recovery.recover_one(
                storage, item.candidate, transport, budget, token, before, item.source_sha256
            )
            outcomes.append(out)
            state.items[number] = outcome_item(item, out, datetime.now(UTC))
        persist(state_path, state.model_dump_json(indent=2).encode())
    return state, outcomes


def read_present(storage: PostgresStorage, numbers: tuple[str, ...]) -> frozenset[str]:
    """Same versions+lexical presence criterion, one tenant-scoped SELECT per page."""
    if len(numbers) > 50 or any(not re.fullmatch(r"[0-9]{19,23}", n) for n in numbers):
        raise ValueError("PRESENCE_SCOPE_INVALID")
    recovery = recovery_module()
    keys = recovery.eis_notice_search_keys
    versions = recovery.eis_notice_versions
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        return frozenset(
            conn.scalars(
                select(keys.c.purchase_number)
                .distinct()
                .where(
                    keys.c.company_id == COMPANY,
                    keys.c.purchase_number.in_(numbers),
                    select(versions.c.purchase_number)
                    .where(
                        versions.c.company_id == COMPANY,
                        versions.c.purchase_number == keys.c.purchase_number,
                    )
                    .exists(),
                )
            )
        )


async def run(scope: Scope, *, apply: bool, root: Path = ROOT) -> RunReport:
    recovery = recovery_module()
    token = os.environ["EIS_GETDOCS_IP_TOKEN"]
    guarded_store(root)
    folder = root / scope.key()
    folder.mkdir(exist_ok=True, mode=0o700)
    state_path = folder / "state.json"
    state = load_state(state_path, scope)
    engine = create_engine(
        os.environ["DATABASE_URL"],
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
    )
    storage = PostgresStorage(engine)
    started = time.monotonic()
    try:
        recovery.source_guard(storage)
        with JointStartBudget(Path(os.environ["EIS_BROWSER_STATE_DIR"]), COMPANY) as joint:
            if not joint.can_start(pending_reconciliation=("44", "223")):
                raise ValueError("JOINT_BUDGET_EXHAUSTED")
            now = datetime.now(UTC)
            day = now.astimezone(ZoneInfo("Europe/Moscow")).date()
            raw = await fetch_page(search_url(scope, day, state.next_page))
            if token.encode() in raw:
                raise ValueError("SOURCE_CONTENT_REJECTED")
            page = parse_page(raw, scope, day, state.next_page, datetime.now(UTC))
            source_path = folder / (page.source_sha256 + ".html")
            atomic_write(source_path, raw)
            atomic_write(
                folder / (hashlib.sha256(page.model_dump_json().encode()).hexdigest() + ".json"),
                page.model_dump_json(indent=2).encode(),
            )
            indexed = read_present(storage, tuple(c.purchase_number for c in page.candidates))
            merged = merge_page(state, page, indexed)
            missing = [
                c.purchase_number for c in page.candidates if c.purchase_number not in indexed
            ]
            outcomes = []
            if apply:
                atomic_write(state_path, merged.model_dump_json(indent=2).encode())
                async with recovery.eis_browser_transport() as transport:
                    merged, outcomes = await drain(
                        storage,
                        merged,
                        state_path,
                        recovery=recovery,
                        joint=joint,
                        token=token,
                        transport=transport,
                    )
            unresolved = sum(i.status != "INDEXED" for i in merged.items.values())
            report = RunReport(
                schema_version="eis-hybrid-run-v1",
                company_id=COMPANY,
                scope=scope,
                observed_at=datetime.now(UTC).isoformat(),
                applied=apply,
                page=page,
                missing_on_page=missing,
                next_page=merged.next_page,
                queue_size=len(merged.items),
                outcomes=tuple(outcomes),
                unresolved_queue=unresolved,
                status="OBSERVED_ONLY"
                if not apply
                else "PARTIAL"
                if unresolved or page.unparsed_cards
                else "PROCESSED_BATCH",
                seconds=round(time.monotonic() - started, 3),
                coverage="BOUNDED_QUERY_ONLY",
                national_coverage="UNKNOWN",
                participation="UNKNOWN",
            )
            atomic_write(
                folder / ("run-" + uuid4().hex + ".json"),
                report.model_dump_json(indent=2).encode(),
            )
            return report
    finally:
        engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--query", required=True)
    p.add_argument("--max-pages", type=int, default=3)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    try:
        if os.environ.get("EIS_HYBRID_IMPORT_LEASE_HELD") != "1":
            raise ValueError("IMPORT_LEASE_REQUIRED")
        report = asyncio.run(
            run(Scope(query=args.query, max_pages=args.max_pages), apply=args.apply)
        )
        print(report.model_dump_json())
        return 0
    except Exception as error:
        # No arbitrary source text, SQL parameters, token or exception traceback.
        reason = str(error)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", reason):
            reason = "HYBRID_UNAVAILABLE"
        print(
            json.dumps(
                dict(company_id=COMPANY, status="UNKNOWN", reason=reason, coverage="UNKNOWN")
            )
        )
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
