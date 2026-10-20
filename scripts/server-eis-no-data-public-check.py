"""Bounded public-day cross-check for a retained NO_DATA; scope mismatch stays UNKNOWN."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_no_data_evidence import (
    KEY,
    NoDataRetention,
    no_data_evidence_root,
    verify_no_data_reply,
)
from procurement.sources.eis_public import (
    EIS_SEARCH_URL,
    EisPublicError,
    _browser_html,
    _host_lease,
    _Node,
    _official_url,
    _parse_html,
)
from procurement.storage.eis_sync_journal import latest_eis_attempts
from procurement.storage.models import audit_events, eis_notice_versions, eis_sync_attempts
from procurement.storage.repository import PostgresStorage

COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
ROOT = Path("/var/lib/eis-browser/research/rejected")
MAX_PAGE_BYTES = 8 * 1024**2
MAX_STORE_BYTES = 32 * 1024**2
MAX_CAPTURES = 8


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Target(Evidence):
    audit_event_id: UUID
    journal_attempt_id: UUID
    journal_attempted_at: AwareDatetime
    receipt: NoDataRetention
    day: date

    @model_validator(mode="after")
    def bound(self) -> Target:
        match = re.fullmatch(KEY, self.receipt.window_key)
        if (
            self.receipt.company_id != COMPANY
            or self.receipt.status != "RETAINED"
            or not match
            or match.group(2) is not None
            or date.fromisoformat(match.group(1)) != self.day
            or self.journal_attempted_at < self.receipt.observed_at
        ):
            raise ValueError("TARGET_INVALID")
        return self


class Candidate(Evidence):
    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    detail_url: str = Field(max_length=512)
    published_day: date
    locator: str = Field(max_length=160)


class Page(Evidence):
    day: date
    search_url: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filters_verified: Literal[True] = True
    scanned_cards: int = Field(ge=0, le=50)
    unparsed_cards: int = Field(ge=0, le=50)
    source_count_floor: int | None = Field(default=None, ge=0)
    source_count_exact: bool = False
    candidates: tuple[Candidate, ...] = Field(max_length=50)
    scope: Literal["NATIONAL_44_PUBLICATION_DAY_FIRST_PAGE"] = (
        "NATIONAL_44_PUBLICATION_DAY_FIRST_PAGE"
    )

    @model_validator(mode="after")
    def bound(self) -> Page:
        if (
            self.search_url != public_day_url(self.day)
            or len(self.candidates) + self.unparsed_cards != self.scanned_cards
        ):
            raise ValueError("PAGE_INVALID")
        if len({c.purchase_number for c in self.candidates}) != len(self.candidates) or any(
            c.published_day != self.day for c in self.candidates
        ):
            raise ValueError("PAGE_INVALID")
        if self.source_count_exact and self.source_count_floor is None:
            raise ValueError("PAGE_COUNT_INVALID")
        if (
            self.source_count_floor is not None
            and self.source_count_exact
            and self.source_count_floor < self.scanned_cards
        ):
            raise ValueError("PAGE_COUNT_INVALID")
        return self


class Artifact(Evidence):
    relative_path: str = Field(pattern=r"^body-[0-9a-f-]{36}\.html$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=MAX_PAGE_BYTES)


class Report(Evidence):
    schema_version: Literal["eis-no-data-public-cross-check-v1"] = (
        "eis-no-data-public-cross-check-v1"
    )
    company_id: Literal["local-eis-supplier"] = COMPANY
    observed_at: AwareDatetime
    since: AwareDatetime
    target: Target
    page: Page
    artifact: Artifact
    indexed_numbers: tuple[str, ...] = Field(max_length=50)
    not_indexed_candidates: tuple[str, ...] = Field(max_length=50)
    pg_snapshot: str
    scope_relation: Literal["DIFFERENT_REGION_TYPE_VERSION_SCOPE"] = (
        "DIFFERENT_REGION_TYPE_VERSION_SCOPE"
    )
    independent_corroboration: Literal["UNKNOWN"] = "UNKNOWN"
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    source_navigations: Literal[1] = 1
    database_writes: Literal[0] = 0

    @model_validator(mode="after")
    def bound(self) -> Report:
        numbers = {c.purchase_number for c in self.page.candidates}
        known, new = set(self.indexed_numbers), set(self.not_indexed_candidates)
        if (
            self.target.day != self.page.day
            or self.page.source_sha256 != self.artifact.sha256
            or known & new
            or known | new != numbers
            or len(known) != len(self.indexed_numbers)
            or len(new) != len(self.not_indexed_candidates)
        ):
            raise ValueError("REPORT_BINDING_INVALID")
        validate_since(self.since, self.observed_at)
        return self


class Unavailable(Evidence):
    company_id: Literal["local-eis-supplier"] = COMPANY
    observed_at: AwareDatetime
    status: Literal["UNKNOWN"] = "UNKNOWN"
    reason: str = Field(pattern=r"^[A-Z_]{1,64}$")
    target: Target | None = None
    artifact: Artifact | None = None
    source_navigations: Literal[0, 1, "UNKNOWN"] = "UNKNOWN"
    navigation_budget: Literal[1] = 1
    database_writes: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"
    independent_corroboration: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def bound(self) -> Unavailable:
        if self.artifact and (self.target is None or self.source_navigations != 1):
            raise ValueError("FAILURE_BINDING_INVALID")
        return self


def write_observation(value: Evidence) -> tuple[str, str]:
    blob = value.model_dump_json(indent=2).encode()
    if len(blob) > 1024**2:
        raise ValueError("PROOF_TOO_LARGE")
    path = ROOT / f"s200-public-check-{uuid4()}.json"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
    return str(path), hashlib.sha256(blob).hexdigest()


def public_day_url(day: date) -> str:
    return (
        EIS_SEARCH_URL
        + "?"
        + urlencode(
            dict(
                searchString="",
                pageNumber="1",
                recordsPerPage="_50",
                sortBy="PUBLISH_DATE",
                sortDirection="false",
                fz44="on",
                af="on",
                ca="on",
                pc="on",
                pa="on",
                publishDateFrom=day.strftime("%d.%m.%Y"),
                publishDateTo=day.strftime("%d.%m.%Y"),
            )
        )
    )


def page_tree(blob: bytes) -> _Node:
    if not 0 < len(blob) <= MAX_PAGE_BYTES:
        raise ValueError("PAGE_SIZE_INVALID")
    tree = _parse_html(blob)
    stack = [(tree, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > 64 or count > 100000:
            raise ValueError("MARKUP_CHANGED")
        stack.extend((c, depth + 1) for c in node.children if isinstance(c, _Node))
    return tree


def text_fragments(tree: _Node) -> str:
    stack: list[_Node | str] = [tree]
    parts = []
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            parts.append(node)
        else:
            stack.extend(reversed(node.children))
    return "".join(parts)


def parse_page(blob: bytes, day: date) -> Page:
    if not 0 < len(blob) <= MAX_PAGE_BYTES:
        raise ValueError("PAGE_SIZE_INVALID")
    tree = page_tree(blob)
    visible = tree.text().casefold()
    if any(
        t in visible
        for t in (
            "подтвердите, что вы не робот",
            "verify you are human",
            "доступ временно ограничен",
        )
    ):
        raise ValueError("BLOCKED_PAGE")

    def controls(name: str) -> list[_Node]:
        return [n for n in tree.walk() if n.tag == "input" and n.attrs.get("name") == name]

    expected = {
        "publishDateFrom": day.strftime("%d.%m.%Y"),
        "publishDateTo": day.strftime("%d.%m.%Y"),
        "pageNumber": "1",
        "recordsPerPage": "_50",
        "searchString": "",
    }
    for name, value in expected.items():
        nodes = controls(name)
        if len(nodes) != 1 or nodes[0].attrs.get("value", "") != value:
            raise ValueError("FILTER_UNVERIFIED")
    for name in ("fz44", "af", "ca", "pc", "pa", "fz223"):
        nodes = controls(name)
        if len(nodes) != 1 or ("checked" in nodes[0].attrs) != (name != "fz223"):
            raise ValueError("FILTER_UNVERIFIED")
    cards = [n for n in tree.walk() if "search-registry-entry-block" in n.classes()]
    if len(cards) > 50:
        raise ValueError("PAGE_SIZE_CHANGED")
    if (
        not cards
        and "ничего не найдено" not in visible
        and "поиск не дал результатов" not in visible
    ):
        raise ValueError("MARKUP_CHANGED")
    candidates = []
    unparsed = 0
    for i, card in enumerate(cards, 1):
        numberbox = card.first("registry-entry__header-mid__number")
        title = card.first("registry-entry__header-top__title")
        link = next((n for n in numberbox.walk() if n.tag == "a"), None) if numberbox else None
        number = re.sub(r"\D", "", link.text()) if link else ""
        url = _official_url(link.attrs.get("href", ""), ("/epz/order/notice/",)) if link else None
        placed = re.findall(r"Размещено\s+(\d{2}\.\d{2}\.\d{4})(?!\d)", card.text())
        if title and "223-ФЗ" in title.text():
            raise ValueError("FILTER_UNVERIFIED")
        if placed and placed != [day.strftime("%d.%m.%Y")]:
            raise ValueError("FILTER_UNVERIFIED")
        if (
            not re.fullmatch(r"[0-9]{19,23}", number)
            or not url
            or not title
            or "44-ФЗ" not in title.text()
            or parse_qs(urlsplit(url).query).get("regNumber") != [number]
            or len(placed) != 1
        ):
            unparsed += 1
            continue
        candidates.append(
            Candidate(
                purchase_number=number,
                detail_url=url,
                published_day=day,
                locator=f"search-registry-entry-block[{i}]",
            )
        )
    totals = [n.text() for n in tree.walk() if "search-results__total" in n.classes()]
    total = exact = None
    if len(totals) == 1:
        match = re.fullmatch(
            r"(?:(Более|более)\s+)?([0-9][0-9\s\u00a0\u202f]*)\s+запис(?:ей|и|ь)", totals[0].strip()
        )
        if match:
            total = int(re.sub(r"\s", "", match.group(2)))
            exact = match.group(1) is None
    return Page(
        day=day,
        search_url=public_day_url(day),
        source_sha256=hashlib.sha256(blob).hexdigest(),
        scanned_cards=len(cards),
        unparsed_cards=unparsed,
        source_count_floor=total,
        source_count_exact=bool(exact),
        candidates=tuple(candidates),
    )


def validate_since(since: datetime, now: datetime) -> None:
    if (
        since.tzinfo is None
        or since.utcoffset() is None
        or not now - timedelta(days=7) <= since <= now
    ):
        raise ValueError("PERIOD_INVALID")


def readonly(conn: Connection) -> None:
    if (
        conn.scalar(text("SHOW transaction_read_only")) != "on"
        or conn.scalar(text("SHOW transaction_isolation")) != "repeatable read"
    ):
        raise ValueError("SNAPSHOT_INVALID")
    conn.execute(text("SET LOCAL statement_timeout='30s'"))


def select_target(conn: Connection, since: datetime) -> Target:
    readonly(conn)
    now = conn.scalar(text("SELECT clock_timestamp()"))
    validate_since(since, now)
    audit = audit_events
    latest = latest_eis_attempts(COMPANY)
    rows = conn.execute(
        select(audit.c.event_id, audit.c.basis, latest.c.attempt_id, latest.c.attempted_at)
        .join(
            latest,
            (latest.c.window_key == audit.c.object_id)
            & (
                latest.c.source_response_sha256
                == audit.c.basis["evidence"]["source_response_sha256"].astext
            )
            & (latest.c.attempted_at >= audit.c.occurred_at),
        )
        .join(
            eis_sync_attempts,
            (eis_sync_attempts.c.company_id == COMPANY)
            & (eis_sync_attempts.c.attempt_id == latest.c.attempt_id),
        )
        .where(
            eis_sync_attempts.c.actor_id == audit.c.actor_id,
            latest.c.attempted_at <= now,
            audit.c.company_id == COMPANY,
            audit.c.event_type == "EIS_NO_DATA_RESPONSE_EVIDENCE",
            audit.c.occurred_at.between(since, now),
            audit.c.basis["evidence"]["status"].astext == "RETAINED",
            latest.c.outcome == "NO_DATA",
        )
        .order_by(audit.c.occurred_at.desc(), audit.c.event_id.desc())
        .limit(10)
    ).mappings()
    root = no_data_evidence_root()
    if root is None:
        raise ValueError("RETENTION_DISABLED")
    for row in rows:
        receipt = NoDataRetention.model_validate(row["basis"]["evidence"])
        match = re.fullmatch(KEY, receipt.window_key)
        if not match or match.group(2) is not None:
            continue
        day = date.fromisoformat(match.group(1))
        if day >= now.astimezone(ZoneInfo("Europe/Moscow")).date():
            continue
        verified = verify_no_data_reply(
            root, COMPANY, receipt.window_key, receipt.source_response_sha256
        )
        if (
            verified.status != "PASS"
            or receipt.manifest != verified.manifest
            or receipt.manifest_sha256 != verified.manifest_sha256
        ):
            continue
        return Target(
            audit_event_id=row["event_id"],
            journal_attempt_id=row["attempt_id"],
            journal_attempted_at=row["attempted_at"],
            receipt=receipt,
            day=day,
        )
    raise ValueError("NO_VERIFIED_DAILY_TARGET")


def retain_page(root: Path, blob: bytes, token: str) -> Artifact:
    if not 0 < len(blob) <= MAX_PAGE_BYTES:
        raise ValueError("PAGE_SIZE_INVALID")
    decoded = blob.decode("utf8")
    tree = page_tree(blob)
    if token and any(
        token in value
        for value in (
            decoded,
            html.unescape(decoded),
            text_fragments(tree),
            "".join(v for n in tree.walk() for v in n.attrs.values()),
        )
    ):
        raise ValueError("SECRET_REFLECTION")
    for p in (root, *root.parents):
        if p.is_symlink():
            raise ValueError("ARTIFACT_STORE_UNSAFE")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError("ARTIFACT_STORE_UNSAFE")
    lock = root / ".capture.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    path = None
    try:
        files = list(root.iterdir())
        if len(files) > MAX_CAPTURES + 1:
            raise ValueError("ARTIFACT_QUOTA_REACHED")
        captures = [f for f in files if f.name != ".capture.lock"]
        if any(
            f.is_symlink()
            or not f.is_file()
            or not re.fullmatch(r"body-[0-9a-f-]{36}\.html", f.name)
            for f in captures
        ):
            raise ValueError("ARTIFACT_STORE_UNSAFE")
        if (
            len(captures) >= MAX_CAPTURES
            or sum(f.stat().st_size for f in captures) + len(blob) > MAX_STORE_BYTES
        ):
            raise ValueError("ARTIFACT_QUOTA_REACHED")
        path = root / f"body-{uuid4()}.html"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        return Artifact(
            relative_path=path.name, sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob)
        )
    except BaseException:
        if path:
            path.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink()


def read_indexed(conn: Connection, page: Page) -> set[str]:
    readonly(conn)
    numbers = tuple(c.purchase_number for c in page.candidates)
    return (
        set(
            conn.execute(
                select(eis_notice_versions.c.purchase_number)
                .where(
                    eis_notice_versions.c.company_id == COMPANY,
                    eis_notice_versions.c.purchase_number.in_(numbers),
                )
                .distinct()
            ).scalars()
        )
        if numbers
        else set()
    )


async def fetch_page(day: date) -> bytes:
    with _host_lease() as retry:
        if retry:
            raise ValueError("PUBLIC_COOLDOWN")
        return await _browser_html(public_day_url(day))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    validate_since(args.since, datetime.now(UTC))
    engine = create_engine(os.environ["DATABASE_URL"])
    storage = PostgresStorage(engine)
    target = None
    artifact = None
    body_received = False
    try:
        with storage.transaction(COMPANY, consistent_read=True) as conn:
            target = select_target(conn, args.since)
        blob = asyncio.run(fetch_page(target.day))
        body_received = True
        artifact = retain_page(
            ROOT / "public-no-data" / COMPANY, blob, os.environ.get("EIS_GETDOCS_IP_TOKEN", "")
        )
        page = parse_page(blob, target.day)
        numbers = tuple(c.purchase_number for c in page.candidates)
        with storage.transaction(COMPANY, consistent_read=True) as conn:
            readonly(conn)
            snapshot = str(conn.scalar(text("SELECT pg_current_snapshot()::text")))
            known = read_indexed(conn, page)

        report = Report(
            observed_at=datetime.now(UTC),
            since=args.since,
            target=target,
            page=page,
            artifact=artifact,
            indexed_numbers=tuple(n for n in numbers if n in known),
            not_indexed_candidates=tuple(n for n in numbers if n not in known),
            pg_snapshot=snapshot,
        )
    except (ValueError, SQLAlchemyError, OSError, EisPublicError) as error:
        safe = {
            "BLOCKED_PAGE",
            "FILTER_UNVERIFIED",
            "MARKUP_CHANGED",
            "PAGE_SIZE_CHANGED",
            "PUBLIC_COOLDOWN",
            "SOURCE_BUSY",
            "ROBOTS_CRAWL_DELAY",
            "BLOCKED",
            "RATE_LIMITED",
            "NO_VERIFIED_DAILY_TARGET",
            "RETENTION_DISABLED",
            "ARTIFACT_QUOTA_REACHED",
            "ARTIFACT_STORE_UNSAFE",
            "SECRET_REFLECTION",
        }
        reason = str(error) if str(error) in safe else "PUBLIC_CROSS_CHECK_UNAVAILABLE"
        count = (
            1
            if body_received
            else (
                0
                if target is None
                or reason in {"PUBLIC_COOLDOWN", "SOURCE_BUSY", "ROBOTS_CRAWL_DELAY"}
                else "UNKNOWN"
            )
        )
        failure = Unavailable(
            observed_at=datetime.now(UTC),
            reason=reason,
            target=target,
            artifact=artifact,
            source_navigations=count,
        )
        path, sha = write_observation(failure)
        print(json.dumps(failure.model_dump(mode="json") | {"proof": path, "sha256": sha}))
        return 65
    finally:
        engine.dispose()
    path, proof_sha = write_observation(report)
    print(
        json.dumps(
            dict(
                status="PUBLIC_PAGE_OBSERVED",
                observed_at=report.observed_at.isoformat(),
                target_key=target.receipt.window_key,
                public_day=target.day.isoformat(),
                scanned_cards=page.scanned_cards,
                candidates=len(numbers),
                unparsed_cards=page.unparsed_cards,
                indexed=len(known),
                not_indexed_candidates=len(report.not_indexed_candidates),
                source_count_floor=page.source_count_floor,
                source_count_exact=page.source_count_exact,
                artifact=artifact.model_dump(),
                proof=str(path),
                sha256=proof_sha,
                source_navigations=1,
                database_writes=0,
                scope_relation=report.scope_relation,
                independent_corroboration="UNKNOWN",
                source_absence="UNKNOWN",
                coverage="UNKNOWN",
            )
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, SQLAlchemyError, OSError, EisPublicError):
        print('{"status":"UNKNOWN","reason":"PUBLIC_CROSS_CHECK_UNAVAILABLE","coverage":"UNKNOWN"}')
        raise SystemExit(65) from None
