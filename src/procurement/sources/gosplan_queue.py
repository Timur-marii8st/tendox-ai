"""Tenant-scoped durable provider observations; never admits official facts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from procurement.sources.gosplan_discovery import (
    MAX_OFFSET,
    GosplanError,
    Law,
    Page,
    inspect_null_type_page,
    parse_page,
)


def release_guard_active(directory: Path = Path("/var/lib/eis-browser/gosplan")) -> bool:
    """Fail closed when a durable worker release is unfinished or state is inaccessible."""
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.stat("release.guard", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True
        finally:
            os.close(fd)
    except OSError:
        return True


class QueueError(ValueError):
    """Queue validation failure, with no source content in its message."""


class OffsetRecoveryReserved(QueueError):
    """A split reservation prevented a claim before any EIS request began."""


@dataclass(frozen=True)
class Scope:
    company: str
    law: Law
    start: datetime
    end: datetime
    offset: int
    limit: int

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.company)
            or self.law not in ("44", "223")
            or self.start.tzinfo is None
            or self.start.utcoffset() is None
            or self.end.tzinfo is None
            or self.end.utcoffset() is None
            or self.start >= self.end
            or not 0 <= self.offset <= 10000
            or not 1 <= self.limit <= 100
        ):
            raise QueueError("SCOPE_INVALID")

    def json(self) -> str:
        return json.dumps(
            {
                "company": self.company,
                "law": self.law,
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
                "offset": self.offset,
                "limit": self.limit,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
 company TEXT NOT NULL, id TEXT NOT NULL, scope TEXT NOT NULL, observed_at TEXT NOT NULL,
 response_sha TEXT NOT NULL, raw BLOB NOT NULL, PRIMARY KEY(company,id)
);
CREATE TABLE IF NOT EXISTS candidates (
 company TEXT NOT NULL, law TEXT NOT NULL, number TEXT NOT NULL, observation_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING')), PRIMARY KEY(company,law,number),
 FOREIGN KEY(company,observation_id) REFERENCES observations(company,id)
);
CREATE TABLE IF NOT EXISTS rejected_pages (
 company TEXT NOT NULL, id TEXT NOT NULL, scope TEXT NOT NULL, observed_at TEXT NOT NULL,
 response_sha TEXT NOT NULL, reason TEXT NOT NULL, raw BLOB NOT NULL,
 PRIMARY KEY(company,id)
);
CREATE TABLE IF NOT EXISTS rejected_page_audit (
 company TEXT NOT NULL, observation_id TEXT NOT NULL, event TEXT NOT NULL,
 PRIMARY KEY(company,observation_id,event),
 FOREIGN KEY(company,observation_id) REFERENCES rejected_pages(company,id)
);
CREATE TABLE IF NOT EXISTS partial_page_resolutions (
 company TEXT NOT NULL, observation_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 resolved_at TEXT NOT NULL, event TEXT NOT NULL CHECK(event='NULL_TYPE_GAPS_UNKNOWN'),
 PRIMARY KEY(company,observation_id),
 FOREIGN KEY(company,observation_id) REFERENCES rejected_pages(company,id)
);
CREATE TABLE IF NOT EXISTS partial_page_gaps (
 company TEXT NOT NULL, observation_id TEXT NOT NULL, row_index INTEGER NOT NULL,
 number TEXT NOT NULL, reason TEXT NOT NULL CHECK(reason='NULL_TYPE_UNKNOWN'),
 PRIMARY KEY(company,observation_id,row_index),
 FOREIGN KEY(company,observation_id) REFERENCES partial_page_resolutions(company,observation_id)
);
CREATE TABLE IF NOT EXISTS partial_scan_resumptions (
 company TEXT NOT NULL, law TEXT NOT NULL, observation_id TEXT NOT NULL,
 started_at TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, offset INTEGER NOT NULL,
 PRIMARY KEY(company,law),
 FOREIGN KEY(company,observation_id) REFERENCES partial_page_resolutions(company,observation_id)
);
CREATE TABLE IF NOT EXISTS inflight_scans (
 company TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, scope TEXT NOT NULL, observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_holds (
 company TEXT PRIMARY KEY, reason TEXT NOT NULL, until_at TEXT
);
CREATE TABLE IF NOT EXISTS provider_hold_evidence (
 company TEXT PRIMARY KEY, observation_id TEXT NOT NULL,
 FOREIGN KEY(company,observation_id) REFERENCES rejected_pages(company,id)
);
CREATE TABLE IF NOT EXISTS provider_hold_binding_audit (
 company TEXT NOT NULL, observation_id TEXT NOT NULL, resolution_id TEXT NOT NULL,
 actor_id TEXT NOT NULL, bound_at TEXT NOT NULL,
 PRIMARY KEY(company,observation_id),
 FOREIGN KEY(company,observation_id) REFERENCES rejected_pages(company,id),
 FOREIGN KEY(company,resolution_id) REFERENCES legacy_hold_resolutions(company,resolution_id)
);
CREATE TABLE IF NOT EXISTS legacy_hold_resolutions (
 company TEXT NOT NULL, resolution_id TEXT NOT NULL, resolved_at TEXT NOT NULL,
 actor_id TEXT NOT NULL,
 hold_reason TEXT NOT NULL CHECK(hold_reason='TYPE_INVALID'),
 original_reason_evidence TEXT NOT NULL CHECK(original_reason_evidence='UNKNOWN'),
 diagnostic_response_sha TEXT NOT NULL, diagnostic_scope TEXT NOT NULL,
 cursors_json TEXT NOT NULL, event TEXT NOT NULL CHECK(event='LEGACY_HOLD_RESOLVED_UNKNOWN'),
 PRIMARY KEY(company,resolution_id)
);
CREATE TABLE IF NOT EXISTS legacy_scan_resumptions (
 company TEXT NOT NULL, law TEXT NOT NULL, resolution_id TEXT NOT NULL,
 started_at TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, offset INTEGER NOT NULL,
 PRIMARY KEY(company,law),
 FOREIGN KEY(company,resolution_id) REFERENCES legacy_hold_resolutions(company,resolution_id)
);
CREATE TABLE IF NOT EXISTS scan_cursors (
 company TEXT NOT NULL, law TEXT NOT NULL, started_at TEXT NOT NULL, start_at TEXT NOT NULL,
 end_at TEXT NOT NULL, offset INTEGER NOT NULL, PRIMARY KEY(company,law)
);
CREATE TABLE IF NOT EXISTS offset_recovery_plans (
 company TEXT NOT NULL, plan_id TEXT NOT NULL, law TEXT NOT NULL,
 actor_id TEXT NOT NULL, prepared_at TEXT NOT NULL, source_observation_id TEXT NOT NULL,
 original_state TEXT NOT NULL, reason TEXT NOT NULL CHECK(reason='HTTP_422'),
 cause TEXT NOT NULL CHECK(cause='UNKNOWN'), coverage TEXT NOT NULL CHECK(coverage='UNKNOWN'),
 event TEXT NOT NULL CHECK(event='OFFSET_SPLIT_PREPARED_UNKNOWN'),
 PRIMARY KEY(company,plan_id), UNIQUE(company,law),
 FOREIGN KEY(company,source_observation_id) REFERENCES observations(company,id)
);
CREATE TABLE IF NOT EXISTS offset_recovery_children (
 company TEXT NOT NULL, plan_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
 start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PREPARED','ACTIVE','DONE','EXHAUSTED')),
 offset INTEGER NOT NULL CHECK(offset >= 0 AND offset <= 1000 AND offset % 100 = 0),
 PRIMARY KEY(company,plan_id,ordinal),
 FOREIGN KEY(company,plan_id) REFERENCES offset_recovery_plans(company,plan_id)
);
CREATE TABLE IF NOT EXISTS offset_recovery_events (
 company TEXT NOT NULL, plan_id TEXT NOT NULL, event TEXT NOT NULL,
 PRIMARY KEY(company,plan_id,event),
 FOREIGN KEY(company,plan_id) REFERENCES offset_recovery_plans(company,plan_id)
);
CREATE TABLE IF NOT EXISTS offset_recovery_reservations (
 company TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, scope TEXT NOT NULL, observed_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS offset_reserve_observation BEFORE INSERT ON observations
WHEN EXISTS (SELECT 1 FROM offset_recovery_reservations r WHERE r.company=NEW.company
 AND (r.scope!=NEW.scope OR r.observed_at!=NEW.observed_at))
BEGIN SELECT RAISE(ABORT,'OFFSET_RECOVERY_RESERVED'); END;
CREATE TRIGGER IF NOT EXISTS offset_reserve_rejected BEFORE INSERT ON rejected_pages
WHEN EXISTS (SELECT 1 FROM offset_recovery_reservations r WHERE r.company=NEW.company
 AND (r.scope!=NEW.scope OR r.observed_at!=NEW.observed_at))
BEGIN SELECT RAISE(ABORT,'OFFSET_RECOVERY_RESERVED'); END;
CREATE TRIGGER IF NOT EXISTS offset_reserve_one_observation BEFORE INSERT ON observations
WHEN EXISTS (SELECT 1 FROM offset_recovery_reservations r WHERE r.company=NEW.company
 AND (EXISTS (SELECT 1 FROM observations o WHERE o.company=r.company AND o.scope=r.scope
      AND o.observed_at=r.observed_at AND o.id!=NEW.id)
   OR EXISTS (SELECT 1 FROM rejected_pages p WHERE p.company=r.company AND p.scope=r.scope
      AND p.observed_at=r.observed_at)))
BEGIN SELECT RAISE(ABORT,'OFFSET_RECOVERY_RESERVED'); END;
CREATE TRIGGER IF NOT EXISTS offset_reserve_one_rejected BEFORE INSERT ON rejected_pages
WHEN EXISTS (SELECT 1 FROM offset_recovery_reservations r WHERE r.company=NEW.company
 AND (EXISTS (SELECT 1 FROM rejected_pages p WHERE p.company=r.company AND p.scope=r.scope
      AND p.observed_at=r.observed_at AND p.id!=NEW.id)
   OR EXISTS (SELECT 1 FROM observations o WHERE o.company=r.company AND o.scope=r.scope
      AND o.observed_at=r.observed_at)))
BEGIN SELECT RAISE(ABORT,'OFFSET_RECOVERY_RESERVED'); END;
CREATE TRIGGER IF NOT EXISTS offset_reserve_candidates_insert BEFORE INSERT ON candidates
WHEN EXISTS (SELECT 1 FROM offset_recovery_reservations r WHERE r.company=NEW.company
 AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.company=NEW.company
 AND o.id=NEW.observation_id AND o.scope=r.scope AND o.observed_at=r.observed_at))
BEGIN SELECT RAISE(ABORT,'OFFSET_RECOVERY_RESERVED'); END;
CREATE TRIGGER IF NOT EXISTS offset_reserve_candidates_update BEFORE UPDATE ON candidates
WHEN EXISTS (SELECT 1 FROM offset_recovery_reservations r WHERE r.company=NEW.company
 AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.company=NEW.company
 AND o.id=NEW.observation_id AND o.scope=r.scope AND o.observed_at=r.observed_at))
BEGIN SELECT RAISE(ABORT,'OFFSET_RECOVERY_RESERVED'); END;
CREATE TABLE IF NOT EXISTS attempts (
 company TEXT NOT NULL, id TEXT NOT NULL, law TEXT NOT NULL, number TEXT NOT NULL,
 observation_id TEXT NOT NULL, claimed_at TEXT NOT NULL, outcome TEXT, official_sha TEXT,
 PRIMARY KEY(company,id), FOREIGN KEY(company,observation_id) REFERENCES observations(company,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS active_attempt
 ON attempts(company,law,number) WHERE outcome IS NULL;
CREATE TABLE IF NOT EXISTS audit (
 company TEXT NOT NULL, observation_id TEXT NOT NULL, event TEXT NOT NULL,
 PRIMARY KEY(company,observation_id,event),
 FOREIGN KEY(company,observation_id) REFERENCES observations(company,id)
);
"""


class GosplanQueue:
    """Single trusted process store; all data and queries explicitly include tenant."""

    def __init__(self, path: Path):
        parent = path.parent
        if (
            not parent.is_dir()
            or parent.resolve() != parent.absolute()
            or parent.stat().st_uid != os.geteuid()
            or parent.stat().st_mode & 0o077
        ):
            raise QueueError("STORE_DIRECTORY_INVALID")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise QueueError("STORE_PATH_INVALID")
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077:
            raise QueueError("STORE_PERMISSIONS_INVALID")
        self.conn = sqlite3.connect(path, timeout=5)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def prepare_offset_recovery(
        self, *, company: str, law: Law, actor_id: str, prepared_at: datetime,
        expected_cursor: tuple[str, str, str, int], source_observation_id: str,
    ) -> str:
        """Prepare overlapping work without clearing a hold or claiming completeness.

        Caller holds the existing discovery cycle lease. This method performs no I/O
        to the provider; executing these children requires a separately reviewed consumer.
        """
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", company)
            or law not in ("44", "223")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", actor_id)
            or not re.fullmatch(r"[a-f0-9]{64}", source_observation_id)
            or prepared_at.tzinfo is None or prepared_at.utcoffset() is None
        ):
            raise QueueError("OFFSET_RECOVERY_INVALID")
        try:
            started, start, end = (datetime.fromisoformat(v) for v in expected_cursor[:3])
            if (len(expected_cursor) != 4 or expected_cursor[3] != MAX_OFFSET + 100
                    or any(t.tzinfo is None or t.utcoffset() is None
                           for t in (started, start, end))
                    or end != started or end - start != timedelta(hours=24)
                    or prepared_at < end):
                raise ValueError
        except (ValueError, TypeError, IndexError) as exc:
            raise QueueError("OFFSET_RECOVERY_CURSOR_INVALID") from exc
        scope = Scope(company, law, start, end, MAX_OFFSET, 100)
        midpoint = start + (end - start) / 2
        overlap = timedelta(minutes=1)
        children = ((start.isoformat(), (midpoint + overlap).isoformat()),
                    ((midpoint - overlap).isoformat(), end.isoformat()))
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.conn.execute(
                "SELECT started_at,start_at,end_at,offset FROM scan_cursors "
                "WHERE company=? AND law=?", (company, law),
            ).fetchone()
            if current != expected_cursor:
                raise QueueError("OFFSET_RECOVERY_CURSOR_CHANGED")
            resumes = []
            for table, binding in (("legacy_scan_resumptions", "resolution_id"),
                                   ("partial_scan_resumptions", "observation_id")):
                row = self.conn.execute(
                    f"SELECT {binding},started_at,start_at,end_at,offset FROM {table} "
                    "WHERE company=? AND law=?", (company, law),
                ).fetchone()
                if row is not None and row[1:] != current:
                    raise QueueError("OFFSET_RECOVERY_RESUME_CHANGED")
                resumes.append(row)
            if (self.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
            ).fetchone() != ("HTTP_422", None) or self.conn.execute(
                "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
            ).fetchone() or self.conn.execute(
                "SELECT 1 FROM attempts WHERE company=? AND outcome IS NULL", (company,)
            ).fetchone()):
                raise QueueError("OFFSET_RECOVERY_HOLD_CHANGED")
            observation = self.conn.execute(
                "SELECT scope,observed_at,response_sha,raw FROM observations "
                "WHERE company=? AND id=?", (company, source_observation_id),
            ).fetchone()
            if observation is None:
                raise QueueError("OFFSET_RECOVERY_SOURCE_MISSING")
            scope_json, observed, digest, raw = observation
            if (scope_json != scope.json() or hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256((scope_json + "\n" + observed + "\n" + digest).encode())
                    .hexdigest() != source_observation_id
                    or self.conn.execute(
                        "SELECT 1 FROM audit WHERE company=? AND observation_id=? "
                        "AND event='OBSERVED'", (company, source_observation_id),
                    ).fetchone() is None):
                raise QueueError("OFFSET_RECOVERY_SOURCE_INVALID")
            try:
                observed_at = datetime.fromisoformat(observed)
                if (observed_at.tzinfo is None or observed_at.utcoffset() is None
                        or observed_at > prepared_at):
                    raise ValueError
                page = parse_page(raw, law, observed_at, 100)
            except (ValueError, TypeError, GosplanError) as exc:
                raise QueueError("OFFSET_RECOVERY_SOURCE_INVALID") from exc
            if not page.may_have_more:
                raise QueueError("OFFSET_RECOVERY_SOURCE_NOT_FULL")
            state = json.dumps({"cursor": current, "resumes": resumes, "source_sha": digest},
                               sort_keys=True, separators=(",", ":"))
            payload = json.dumps([company, law, actor_id, prepared_at.isoformat(),
                                  source_observation_id, state, children], separators=(",", ":"))
            plan_id = hashlib.sha256(payload.encode()).hexdigest()
            expected = (law, actor_id, prepared_at.isoformat(), source_observation_id, state,
                        "HTTP_422", "UNKNOWN", "UNKNOWN", "OFFSET_SPLIT_PREPARED_UNKNOWN")
            existing = self.conn.execute(
                "SELECT law,actor_id,prepared_at,source_observation_id,original_state,reason,"
                "cause,coverage,event FROM offset_recovery_plans WHERE company=? AND plan_id=?",
                (company, plan_id),
            ).fetchone()
            if existing is not None:
                actual_children = self.conn.execute(
                    "SELECT ordinal,start_at,end_at FROM offset_recovery_children "
                    "WHERE company=? AND plan_id=? AND status='PREPARED' ORDER BY ordinal",
                    (company, plan_id),
                ).fetchall()
                if existing != expected or actual_children != [
                    (i, a, b) for i, (a, b) in enumerate(children)
                ]:
                    raise QueueError("OFFSET_RECOVERY_REPLAY_CONFLICT")
                return plan_id
            if self.conn.execute("SELECT 1 FROM offset_recovery_plans WHERE company=? AND law=?",
                                 (company, law)).fetchone():
                raise QueueError("OFFSET_RECOVERY_PLAN_EXISTS")
            self.conn.execute("INSERT INTO offset_recovery_plans VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              (company, plan_id, *expected))
            self.conn.executemany("INSERT INTO offset_recovery_children VALUES (?,?,?,?,?,?,?)",
                                  [(company, plan_id, i, a, b, "PREPARED", 0)
                                   for i, (a, b) in enumerate(children)])
            return plan_id

    def activate_offset_recovery(self, *, company: str, law: Law, plan_id: str) -> None:
        """Start a previously reviewed split under the discovery lease, without network I/O."""
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            parent = self.conn.execute(
                "SELECT original_state,source_observation_id,actor_id,prepared_at "
                "FROM offset_recovery_plans "
                "WHERE company=? AND law=? AND plan_id=?", (company, law, plan_id),
            ).fetchone()
            if parent is None:
                raise QueueError("OFFSET_RECOVERY_PLAN_MISSING")
            state = json.loads(parent[0])
            cursor = self.conn.execute(
                "SELECT started_at,start_at,end_at,offset FROM scan_cursors "
                "WHERE company=? AND law=?", (company, law),
            ).fetchone()
            resumes = []
            for table, binding in (("legacy_scan_resumptions", "resolution_id"),
                                   ("partial_scan_resumptions", "observation_id")):
                row = self.conn.execute(
                    f"SELECT {binding},started_at,start_at,end_at,offset FROM {table} "
                    "WHERE company=? AND law=?", (company, law),
                ).fetchone()
                resumes.append(list(row) if row else None)
            observation = self.conn.execute(
                "SELECT response_sha,raw,scope,observed_at FROM observations "
                "WHERE company=? AND id=?",
                (company, parent[1]),
            ).fetchone()
            children = self.conn.execute(
                "SELECT ordinal,start_at,end_at,status,offset FROM offset_recovery_children "
                "WHERE company=? AND plan_id=? ORDER BY ordinal", (company, plan_id),
            ).fetchall()
            start, end = (datetime.fromisoformat(state['cursor'][i]) for i in (1, 2))
            midpoint = start + (end - start) / 2
            expected = [(0, start.isoformat(), (midpoint + timedelta(minutes=1)).isoformat(),
                         'PREPARED', 0),
                        (1, (midpoint - timedelta(minutes=1)).isoformat(), end.isoformat(),
                         'PREPARED', 0)]
            payload = json.dumps([company, law, parent[2], parent[3], parent[1], parent[0],
                                  [(r[1], r[2]) for r in expected]], separators=(",", ":"))
            if hashlib.sha256(payload.encode()).hexdigest() != plan_id:
                raise QueueError("OFFSET_RECOVERY_PLAN_INVALID")
            if (observation is None or observation[0] != state['source_sha']
                    or hashlib.sha256(observation[1]).hexdigest() != observation[0]
                    or hashlib.sha256((observation[2] + '\n' + observation[3] + '\n'
                                       + observation[0]).encode()).hexdigest() != parent[1]
                    or self.conn.execute(
                        "SELECT 1 FROM audit WHERE company=? AND observation_id=? "
                        "AND event='OBSERVED'", (company, parent[1]),
                    ).fetchone() is None):
                raise QueueError("OFFSET_RECOVERY_SOURCE_INVALID")
            hold = self.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
            ).fetchone()
            activated = self.conn.execute(
                "SELECT 1 FROM offset_recovery_events WHERE company=? AND plan_id=? "
                "AND event='ACTIVATED_UNKNOWN'", (company, plan_id),
            ).fetchone()
            inflight = self.conn.execute(
                "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
            ).fetchone()
            if self.conn.execute(
                "SELECT 1 FROM attempts WHERE company=? AND outcome IS NULL", (company,)
            ).fetchone():
                raise QueueError("OFFSET_RECOVERY_ATTEMPT_OPEN")
            if (children == [(0, expected[0][1], expected[0][2], 'ACTIVE', 0), expected[1]]
                    and hold == ('OFFSET_RECOVERY', None) and activated and not inflight
                    and list(cursor or ()) == state['cursor'] and resumes == state['resumes']
                    and observation is not None and observation[0] == state['source_sha']
                    and hashlib.sha256(observation[1]).hexdigest() == observation[0]):
                return
            if (list(cursor or ()) != state['cursor'] or resumes != state['resumes']
                    or observation is None or observation[0] != state['source_sha']
                    or hashlib.sha256(observation[1]).hexdigest() != observation[0]
                    or children != expected
                    or hold != ('HTTP_422', None) or activated
                    or inflight):
                raise QueueError("OFFSET_RECOVERY_ACTIVATION_CHANGED")
            self.conn.execute("UPDATE offset_recovery_children SET status='ACTIVE' "
                              "WHERE company=? AND plan_id=? AND ordinal=0", (company, plan_id))
            self.conn.execute("UPDATE provider_holds SET reason='OFFSET_RECOVERY' WHERE company=?",
                              (company,))
            self.conn.execute("INSERT INTO offset_recovery_events VALUES (?,?,?)",
                              (company, plan_id, 'ACTIVATED_UNKNOWN'))

    def reconcile_offset_null_page(
        self, company: str, plan_id: str, observation_id: str, actor_id: str, now: datetime,
    ) -> int:
        """Reconcile only a quarantined active split child; null gaps remain UNKNOWN."""
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', company)
                or not re.fullmatch(r'[a-f0-9]{64}', plan_id)
                or not re.fullmatch(r'[a-f0-9]{64}', observation_id)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', actor_id)
                or now.tzinfo is None or now.utcoffset() is None):
            raise QueueError('OFFSET_NULL_INVALID')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            rejected = self.conn.execute(
                "SELECT scope,observed_at,response_sha,reason,raw FROM rejected_pages "
                "WHERE company=? AND id=?", (company, observation_id),
            ).fetchone()
            if rejected is None:
                raise QueueError('OFFSET_NULL_SOURCE_MISSING')
            raw_scope, observed, digest, reason, raw = rejected
            if (reason != 'TYPE_INVALID' or hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256((raw_scope + '\n' + observed + '\n' + digest).encode())
                    .hexdigest() != observation_id
                    or self.conn.execute(
                        "SELECT event FROM rejected_page_audit "
                        "WHERE company=? AND observation_id=?",
                        (company, observation_id),
                    ).fetchone() != ('QUARANTINED_UNKNOWN',)):
                raise QueueError('OFFSET_NULL_SOURCE_INVALID')
            try:
                data = json.loads(raw_scope)
                observed_at = datetime.fromisoformat(observed)
                scope = Scope(data['company'], data['law'], datetime.fromisoformat(data['start']),
                              datetime.fromisoformat(data['end']), data['offset'], data['limit'])
                if (scope.company != company or scope.json() != raw_scope or scope.limit != 100
                        or scope.offset > MAX_OFFSET or scope.offset % 100
                        or observed_at.tzinfo is None or observed_at.utcoffset() is None
                        or now < observed_at):
                    raise ValueError
                page, gaps = inspect_null_type_page(raw, scope.law, observed_at, 100)
            except (TypeError, ValueError, KeyError, GosplanError) as exc:
                raise QueueError('OFFSET_NULL_SOURCE_INVALID') from exc
            prior = self.conn.execute(
                "SELECT actor_id,resolved_at,event FROM partial_page_resolutions "
                "WHERE company=? AND observation_id=?", (company, observation_id),
            ).fetchone()
            if prior is not None:
                saved_gaps = self.conn.execute(
                    "SELECT row_index,number FROM partial_page_gaps WHERE company=? "
                    "AND observation_id=? ORDER BY row_index", (company, observation_id),
                ).fetchall()
                event = self.conn.execute(
                    "SELECT 1 FROM offset_recovery_events WHERE company=? AND plan_id=? "
                    "AND event LIKE ?", (company, plan_id, f'NULL_PAGE/%/{observation_id}'),
                ).fetchone()
                if (prior != (actor_id, now.isoformat(), 'NULL_TYPE_GAPS_UNKNOWN')
                        or tuple(saved_gaps) != gaps or event is None
                        or self.conn.execute(
                            "SELECT scope,observed_at,response_sha,raw FROM observations "
                            "WHERE company=? AND id=?", (company, observation_id),
                        ).fetchone() != (raw_scope, observed, digest, raw)
                        or self.conn.execute(
                            "SELECT 1 FROM audit WHERE company=? AND observation_id=? "
                            "AND event='PARTIAL_OBSERVED_UNKNOWN'", (company, observation_id),
                        ).fetchone() is None):
                    raise QueueError('OFFSET_NULL_REPLAY_CONFLICT')
                return len(gaps)
            active = self.conn.execute(
                "SELECT c.ordinal,c.start_at,c.end_at,c.offset FROM offset_recovery_children c "
                "JOIN offset_recovery_plans p ON p.company=c.company AND p.plan_id=c.plan_id "
                "WHERE c.company=? AND c.plan_id=? AND p.law=? AND c.status='ACTIVE'",
                (company, plan_id, scope.law),
            ).fetchall()
            if (len(active) != 1 or active[0][1:] != (scope.start.isoformat(),
                    scope.end.isoformat(), scope.offset)
                    or self.conn.execute(
                        "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
                    ).fetchone() != ('TYPE_INVALID', None)
                    or self.conn.execute(
                        "SELECT observation_id FROM provider_hold_evidence WHERE company=?",
                        (company,),
                    ).fetchone() != (observation_id,)
                    or self.conn.execute(
                        "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
                    ).fetchone()
                    or self.conn.execute(
                        "SELECT 1 FROM offset_recovery_reservations WHERE company=?", (company,)
                    ).fetchone()
                    or self.conn.execute(
                        "SELECT 1 FROM attempts WHERE company=? AND outcome IS NULL", (company,)
                    ).fetchone()):
                raise QueueError('OFFSET_NULL_SCOPE_CHANGED')
            count, size = self.conn.execute(
                "SELECT count(*),coalesce(sum(length(raw)),0) FROM observations WHERE company=?",
                (company,),
            ).fetchone()
            existing = {r[0] for r in self.conn.execute(
                "SELECT number FROM candidates WHERE company=? AND law=?", (company, scope.law),
            )}
            candidate_count = self.conn.execute(
                "SELECT count(*) FROM candidates WHERE company=?", (company,),
            ).fetchone()[0]
            if (count >= 2000 or size + len(raw) > 256 * 1024**2 or candidate_count
                    + sum(c.number not in existing for c in page.candidates) > 2000):
                raise QueueError('OFFSET_NULL_CAPACITY')
            self.conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',
                              (company, observation_id, raw_scope, observed, digest, raw))
            self.conn.execute('INSERT INTO partial_page_resolutions VALUES (?,?,?,?,?)',
                              (company, observation_id, actor_id, now.isoformat(),
                               'NULL_TYPE_GAPS_UNKNOWN'))
            self.conn.executemany('INSERT INTO partial_page_gaps VALUES (?,?,?,?,?)',
                                  [(company, observation_id, i, number, 'NULL_TYPE_UNKNOWN')
                                   for i, number in gaps])
            for candidate in page.candidates:
                self.conn.execute(
                    "INSERT INTO candidates VALUES (?,?,?,?,?) ON CONFLICT(company,law,number) "
                    "DO UPDATE SET observation_id=excluded.observation_id,status='PENDING'",
                    (company, scope.law, candidate.number, observation_id, 'PENDING'),
                )
            self.conn.execute('INSERT INTO audit VALUES (?,?,?)',
                              (company, observation_id, 'PARTIAL_OBSERVED_UNKNOWN'))
            ordinal = active[0][0]
            if page.may_have_more and scope.offset == MAX_OFFSET:
                self.conn.execute("UPDATE offset_recovery_children SET status='EXHAUSTED' "
                                  "WHERE company=? AND plan_id=? AND ordinal=?",
                                  (company, plan_id, ordinal))
                hold = 'OFFSET_RECOVERY_CHILD_LIMIT'
            elif page.may_have_more:
                self.conn.execute("UPDATE offset_recovery_children SET offset=? "
                                  "WHERE company=? AND plan_id=? AND ordinal=?",
                                  (scope.offset + 100, company, plan_id, ordinal))
                hold = 'OFFSET_RECOVERY'
            else:
                self.conn.execute("UPDATE offset_recovery_children SET status='DONE' "
                                  "WHERE company=? AND plan_id=? AND ordinal=?",
                                  (company, plan_id, ordinal))
                remaining = self.conn.execute(
                    "SELECT ordinal FROM offset_recovery_children WHERE company=? AND plan_id=? "
                    "AND status='PREPARED' ORDER BY ordinal", (company, plan_id),
                ).fetchall()
                if remaining:
                    self.conn.execute("UPDATE offset_recovery_children SET status='ACTIVE' "
                                      "WHERE company=? AND plan_id=? AND ordinal=?",
                                      (company, plan_id, remaining[0][0]))
                    hold = 'OFFSET_RECOVERY'
                else:
                    hold = 'OFFSET_RECOVERY_UNKNOWN'
            self.conn.execute("UPDATE provider_holds SET reason=? WHERE company=?", (hold, company))
            self.conn.execute('DELETE FROM provider_hold_evidence WHERE company=?', (company,))
            self.conn.execute('INSERT INTO offset_recovery_events VALUES (?,?,?)',
                              (company, plan_id,
                               f'NULL_PAGE/{ordinal}/{scope.offset}/{observation_id}'))
            return len(gaps)

    def resolve_legacy_type_hold(
        self, *, company: str, resolution_id: str, resolved_at: datetime, actor_id: str,
        diagnostic_response_sha: str, diagnostic_scope: Scope,
        expected_cursors: tuple[tuple[object, ...], ...],
    ) -> bool:
        """Record an unknown legacy failure and release only its exact durable hold.

        The separate diagnostic is not evidence of the missing old response. This
        operation cannot write observations, candidates or advance a cursor.
        """
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", company)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", actor_id)
            or not re.fullmatch(r"[a-f0-9]{64}", resolution_id)
            or not re.fullmatch(r"[a-f0-9]{64}", diagnostic_response_sha)
            or resolved_at.tzinfo is None or resolved_at.utcoffset() is None
            or diagnostic_scope.company != company
        ):
            raise QueueError("HOLD_RESOLUTION_INVALID")
        scope_json = diagnostic_scope.json()
        cursors_json = json.dumps(expected_cursors, separators=(",", ":"), ensure_ascii=False)
        expected = (
            resolved_at.isoformat(), actor_id, "TYPE_INVALID", "UNKNOWN", diagnostic_response_sha,
            scope_json, cursors_json, "LEGACY_HOLD_RESOLVED_UNKNOWN",
        )
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            prior = self.conn.execute(
                "SELECT resolved_at,actor_id,hold_reason,original_reason_evidence,"
                "diagnostic_response_sha,"
                "diagnostic_scope,cursors_json,event FROM legacy_hold_resolutions "
                "WHERE company=? AND resolution_id=?", (company, resolution_id)
            ).fetchone()
            hold = self.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
            ).fetchone()
            if prior is not None:
                if prior != expected or hold is not None:
                    raise QueueError("HOLD_RESOLUTION_CONFLICT")
                return False
            if hold != ("TYPE_INVALID", None):
                raise QueueError("PROVIDER_HOLD_CHANGED")
            if self.conn.execute(
                "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
            ).fetchone():
                raise QueueError("INFLIGHT_SCAN_UNRESOLVED")
            if self.conn.execute(
                "SELECT 1 FROM rejected_pages WHERE company=? AND reason='TYPE_INVALID' LIMIT 1",
                (company,),
            ).fetchone():
                raise QueueError("NOT_A_LEGACY_HOLD")
            cursors = tuple(self.conn.execute(
                "SELECT law,started_at,start_at,end_at,offset FROM scan_cursors "
                "WHERE company=? ORDER BY law", (company,)
            ).fetchall())
            if cursors != expected_cursors:
                raise QueueError("SCAN_CURSOR_CHANGED")
            self.conn.execute(
                "INSERT INTO legacy_hold_resolutions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (company, resolution_id, *expected),
            )
            for law, started, start, end, offset in cursors:
                self.conn.execute(
                    "INSERT INTO legacy_scan_resumptions VALUES (?,?,?,?,?,?,?)",
                    (company, law, resolution_id, started, start, end, offset),
                )
            self.conn.execute("DELETE FROM provider_holds WHERE company=?", (company,))
        return True

    def record(
        self, scope: Scope, page: Page, observed_at: datetime, *, inflight_id: str | None = None
    ) -> str:
        """Atomically retain source bytes, candidates and audit; repeat is idempotent."""
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise QueueError("OBSERVATION_TIME_INVALID")
        parsed = parse_page(page.raw, scope.law, observed_at, scope.limit)
        if parsed != page or page.response_sha256 != hashlib.sha256(page.raw).hexdigest():
            raise QueueError("SOURCE_BINDING_INVALID")
        scope_json = scope.json()
        identity = hashlib.sha256(
            (scope_json + "\n" + observed_at.isoformat() + "\n" + page.response_sha256).encode()
        ).hexdigest()
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            if inflight_id is not None:
                self.check_inflight(scope, observed_at, inflight_id)
            previous = self.conn.execute(
                "SELECT scope,observed_at,response_sha,raw FROM observations "
                "WHERE company=? AND id=?",
                (scope.company, identity),
            ).fetchone()
            expected = (scope_json, observed_at.isoformat(), page.response_sha256, page.raw)
            if previous is not None and previous != expected:
                raise QueueError("OBSERVATION_CONFLICT")
            if previous is not None:
                return identity
            count = self.conn.execute(
                "SELECT count(*) FROM observations WHERE company=?", (scope.company,)
            ).fetchone()[0]
            total_bytes = self.conn.execute(
                "SELECT coalesce(sum(length(raw)),0) FROM observations WHERE company=?",
                (scope.company,),
            ).fetchone()[0]
            candidate_count = self.conn.execute(
                "SELECT count(*) FROM candidates WHERE company=?", (scope.company,)
            ).fetchone()[0]
            existing = {
                row[0]
                for row in self.conn.execute(
                    "SELECT number FROM candidates WHERE company=? AND law=?",
                    (scope.company, scope.law),
                )
            }
            extra = sum(candidate.number not in existing for candidate in page.candidates)
            if count >= 2000 or total_bytes + len(page.raw) > 256 * 1024**2:
                raise QueueError("OBSERVATION_CAP_REACHED")
            if candidate_count + extra > 2000:
                raise QueueError("CANDIDATE_CAP_REACHED")
            self.conn.execute(
                "INSERT INTO observations VALUES (?,?,?,?,?,?)",
                (scope.company, identity, *expected),
            )
            for candidate in page.candidates:
                self.conn.execute(
                    "INSERT INTO candidates VALUES (?,?,?,?,?) "
                    "ON CONFLICT(company,law,number) DO UPDATE SET "
                    "observation_id=excluded.observation_id,status='PENDING'",
                    (scope.company, scope.law, candidate.number, identity, "PENDING"),
                )
            self.conn.execute(
                "INSERT INTO audit VALUES (?,?,?)", (scope.company, identity, "OBSERVED")
            )
        return identity

    def check_inflight(self, scope: Scope, observed_at: datetime, attempt_id: str) -> None:
        """Call only inside a write transaction to bind one exact network attempt."""
        hold = self.conn.execute(
            "SELECT reason,until_at FROM provider_holds WHERE company=?", (scope.company,)
        ).fetchone()
        inflight = self.conn.execute(
            "SELECT attempt_id,scope,observed_at FROM inflight_scans WHERE company=?",
            (scope.company,),
        ).fetchone()
        if hold != ("REQUEST_IN_FLIGHT", None) or inflight != (
            attempt_id, scope.json(), observed_at.isoformat()
        ):
            raise QueueError("INFLIGHT_BINDING_CHANGED")

    def quarantine_and_hold(
        self, scope: Scope, raw: bytes, observed_at: datetime, reason: str,
        expected_hold: tuple[str, str | None] | None, inflight_id: str | None = None,
    ) -> bool:
        """Atomically retain a rejected page and hold; never create candidates or move a cursor."""
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise QueueError("OBSERVATION_TIME_INVALID")
        try:
            parse_page(raw, scope.law, observed_at, scope.limit)
        except GosplanError as exc:
            if str(exc) != reason:
                raise QueueError("QUARANTINE_REASON_MISMATCH") from exc
        else:
            raise QueueError("QUARANTINE_PAGE_VALID")
        scope_json = scope.json()
        digest = hashlib.sha256(raw).hexdigest()
        identity = hashlib.sha256(
            (scope_json + "\n" + observed_at.isoformat() + "\n" + digest).encode()
        ).hexdigest()
        stored = False
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current_hold = self.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (scope.company,)
            ).fetchone()
            previous = self.conn.execute(
                "SELECT scope,observed_at,response_sha,reason,raw FROM rejected_pages "
                "WHERE company=? AND id=?", (scope.company, identity)
            ).fetchone()
            expected = (scope_json, observed_at.isoformat(), digest, reason, raw)
            if previous is not None and previous != expected:
                raise QueueError("QUARANTINE_BINDING_CONFLICT")
            if current_hold != expected_hold:
                audit = self.conn.execute(
                    "SELECT event FROM rejected_page_audit WHERE company=? AND observation_id=?",
                    (scope.company, identity),
                ).fetchone()
                if previous == expected and current_hold == (reason, None) and audit == (
                    "QUARANTINED_UNKNOWN",
                ):
                    return True
                raise QueueError("PROVIDER_HOLD_CHANGED")
            if expected_hold == ("REQUEST_IN_FLIGHT", None):
                if inflight_id is None:
                    raise QueueError("INFLIGHT_BINDING_MISSING")
                self.check_inflight(scope, observed_at, inflight_id)
            count, size = self.conn.execute(
                "SELECT count(*),coalesce(sum(length(raw)),0) FROM rejected_pages WHERE company=?",
                (scope.company,),
            ).fetchone()
            if previous is not None:
                stored = True
            elif count < 100 and size + len(raw) <= 32 * 1024**2:
                self.conn.execute(
                    "INSERT INTO rejected_pages VALUES (?,?,?,?,?,?,?)",
                    (scope.company, identity, *expected),
                )
                self.conn.execute(
                    "INSERT INTO rejected_page_audit VALUES (?,?,?)",
                    (scope.company, identity, "QUARANTINED_UNKNOWN"),
                )
                stored = True
            self.conn.execute(
                "INSERT INTO provider_holds VALUES (?,?,NULL) ON CONFLICT(company) "
                "DO UPDATE SET reason=excluded.reason,until_at=NULL",
                (scope.company, reason if stored else "QUARANTINE_CAP_REACHED"),
            )
            if stored:
                self.conn.execute(
                    "INSERT INTO provider_hold_evidence VALUES (?,?) "
                    "ON CONFLICT(company) DO UPDATE SET observation_id=excluded.observation_id",
                    (scope.company, identity),
                )
            else:
                self.conn.execute("DELETE FROM provider_hold_evidence WHERE company=?",
                                  (scope.company,))
            self.conn.execute("DELETE FROM inflight_scans WHERE company=?", (scope.company,))
            if inflight_id is not None:
                self.conn.execute(
                    "DELETE FROM offset_recovery_reservations WHERE company=? AND attempt_id=?",
                    (scope.company, inflight_id),
                )
        return stored

    def bind_post_legacy_hold(
        self, company: str, observation_id: str, resolution_id: str, actor_id: str, now: datetime
    ) -> bool:
        """Bind one unambiguous post-legacy rejection; caller holds the cycle lease."""
        if (not re.fullmatch(r"[a-f0-9]{64}", observation_id)
                or not re.fullmatch(r"[a-f0-9]{64}", resolution_id)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", actor_id)
                or now.tzinfo is None or now.utcoffset() is None):
            raise QueueError("HOLD_BINDING_INPUT_INVALID")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            binding = self.conn.execute(
                "SELECT observation_id FROM provider_hold_evidence WHERE company=?", (company,)
            ).fetchone()
            prior = self.conn.execute(
                "SELECT resolution_id,actor_id,bound_at FROM provider_hold_binding_audit "
                "WHERE company=? AND observation_id=?", (company, observation_id),
            ).fetchone()
            if prior is not None:
                if prior != (resolution_id, actor_id, now.isoformat()):
                    raise QueueError("HOLD_BINDING_REPLAY_MISMATCH")
                if binding != (observation_id,):
                    raise QueueError("HOLD_BINDING_NO_LONGER_ACTIVE")
                return False
            if binding is not None or self.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
            ).fetchone() != ("TYPE_INVALID", None) or self.conn.execute(
                "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
            ).fetchone():
                raise QueueError("HOLD_BINDING_STATE_CHANGED")
            rejected = self.conn.execute(
                "SELECT id,scope,observed_at,reason FROM rejected_pages WHERE company=?",
                (company,),
            ).fetchall()
            if len(rejected) != 1 or rejected[0][0] != observation_id or (
                rejected[0][3] != "TYPE_INVALID"
            ) or self.conn.execute(
                "SELECT event FROM rejected_page_audit WHERE company=? AND observation_id=?",
                (company, observation_id),
            ).fetchone() != ("QUARANTINED_UNKNOWN",):
                raise QueueError("HOLD_BINDING_AMBIGUOUS")
            scope = json.loads(rejected[0][1])
            prior_resolution = self.conn.execute(
                "SELECT resolved_at,event FROM legacy_hold_resolutions WHERE company=? "
                "AND resolution_id=?", (company, resolution_id),
            ).fetchone()
            resume = self.conn.execute(
                "SELECT resolution_id,started_at,start_at,end_at,offset "
                "FROM legacy_scan_resumptions "
                "WHERE company=? AND law=?", (company, scope["law"]),
            ).fetchone()
            cursor = self.conn.execute(
                "SELECT started_at,start_at,end_at,offset FROM scan_cursors "
                "WHERE company=? AND law=?",
                (company, scope["law"]),
            ).fetchone()
            if (prior_resolution is None or prior_resolution[1] != "LEGACY_HOLD_RESOLVED_UNKNOWN"
                or datetime.fromisoformat(prior_resolution[0])
                >= datetime.fromisoformat(rejected[0][2])
                or datetime.fromisoformat(rejected[0][2]) > now or scope["company"] != company
                or resume is None or resume[0] != resolution_id or resume[1:] != cursor
                or cursor is None or cursor[1:] != (scope["start"], scope["end"], scope["offset"])):
                raise QueueError("HOLD_BINDING_EVIDENCE_INVALID")
            self.conn.execute("INSERT INTO provider_hold_evidence VALUES (?,?)",
                              (company, observation_id))
            self.conn.execute("INSERT INTO provider_hold_binding_audit VALUES (?,?,?,?,?)",
                              (company, observation_id, resolution_id, actor_id, now.isoformat()))
        return True

    def reconcile_null_type_page(
        self, company: str, observation_id: str, actor_id: str, now: datetime
    ) -> int:
        """Reconcile one retained page atomically; null rows stay durable UNKNOWN gaps.

        Caller must hold the discovery cycle lease. No provider or EIS request occurs.
        """
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", actor_id)
            or not re.fullmatch(r"[a-f0-9]{64}", observation_id)
            or now.tzinfo is None or now.utcoffset() is None
        ):
            raise QueueError("PARTIAL_INPUT_INVALID")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            rejected = self.conn.execute(
                "SELECT scope,observed_at,response_sha,reason,raw FROM rejected_pages "
                "WHERE company=? AND id=?", (company, observation_id)
            ).fetchone()
            audit = self.conn.execute(
                "SELECT event FROM rejected_page_audit WHERE company=? AND observation_id=?",
                (company, observation_id),
            ).fetchone()
            if rejected is None or audit != ("QUARANTINED_UNKNOWN",):
                raise QueueError("PARTIAL_REJECTION_MISSING")
            scope_json, observed, digest, reason, raw = rejected
            if reason != "TYPE_INVALID" or hashlib.sha256(raw).hexdigest() != digest or (
                hashlib.sha256((scope_json + "\n" + observed + "\n" + digest).encode()).hexdigest()
                != observation_id
            ):
                raise QueueError("PARTIAL_SOURCE_BINDING_INVALID")
            s = json.loads(scope_json)
            scope = Scope(s["company"], s["law"], datetime.fromisoformat(s["start"]),
                          datetime.fromisoformat(s["end"]), s["offset"], s["limit"])
            if scope.company != company or scope.json() != scope_json or scope.limit != 100:
                raise QueueError("PARTIAL_SCOPE_INVALID")
            observation_time = datetime.fromisoformat(observed)
            if (observation_time.tzinfo is None or observation_time.utcoffset() is None
                    or now < observation_time or scope.end > observation_time
                    or scope.end - scope.start != timedelta(hours=24)
                    or scope.offset % 100):
                raise QueueError("PARTIAL_SCOPE_INVALID")
            page, gaps = inspect_null_type_page(raw, scope.law, observation_time, 100)
            prior = self.conn.execute(
                "SELECT actor_id,resolved_at,event FROM partial_page_resolutions "
                "WHERE company=? AND observation_id=?",
                (company, observation_id),
            ).fetchone()
            if prior is not None:
                stored = self.conn.execute(
                    "SELECT scope,observed_at,response_sha,raw FROM observations "
                    "WHERE company=? AND id=?", (company, observation_id),
                ).fetchone()
                stored_gaps = self.conn.execute(
                    "SELECT row_index,number FROM partial_page_gaps WHERE company=? "
                    "AND observation_id=? ORDER BY row_index", (company, observation_id),
                ).fetchall()
                partial_audit = self.conn.execute(
                    "SELECT event FROM audit WHERE company=? AND observation_id=? "
                    "AND event='PARTIAL_OBSERVED_UNKNOWN'", (company, observation_id),
                ).fetchone()
                if prior != (actor_id, now.isoformat(), "NULL_TYPE_GAPS_UNKNOWN") or stored != (
                    scope_json, observed, digest, raw
                ) or tuple(stored_gaps) != gaps or partial_audit != ("PARTIAL_OBSERVED_UNKNOWN",):
                    raise QueueError("PARTIAL_REPLAY_MISMATCH")
                return len(gaps)
            # Retain historical evidence without promoting a page beyond the
            # currently documented provider pagination limit.
            if scope.offset > MAX_OFFSET:
                raise QueueError("OFFSET_LIMIT")
            if self.conn.execute(
                "SELECT reason,until_at FROM provider_holds WHERE company=?", (company,)
            ).fetchone() != ("TYPE_INVALID", None) or self.conn.execute(
                "SELECT 1 FROM inflight_scans WHERE company=?", (company,)
            ).fetchone() or self.conn.execute(
                "SELECT observation_id FROM provider_hold_evidence WHERE company=?", (company,)
            ).fetchone() != (observation_id,):
                raise QueueError("PARTIAL_HOLD_CHANGED")
            cursor = self.conn.execute(
                "SELECT started_at,start_at,end_at,offset FROM scan_cursors "
                "WHERE company=? AND law=?", (company, scope.law)
            ).fetchone()
            resume = self.conn.execute(
                "SELECT started_at,start_at,end_at,offset FROM legacy_scan_resumptions "
                "WHERE company=? AND law=?", (company, scope.law)
            ).fetchone()
            partial_resume = self.conn.execute(
                "SELECT started_at,start_at,end_at,offset FROM partial_scan_resumptions "
                "WHERE company=? AND law=?", (company, scope.law),
            ).fetchone()
            valid_first_page = (cursor is None and scope.offset == 0 and resume is None
                                and partial_resume is None)
            valid_existing = cursor is not None and cursor[0] == s["end"] and cursor[1:] == (
                s["start"], s["end"], scope.offset
            ) and (resume is None or resume == cursor) and (
                partial_resume is None or partial_resume == cursor
            )
            if not valid_first_page and not valid_existing:
                raise QueueError("PARTIAL_CURSOR_CHANGED")
            count, size = self.conn.execute(
                "SELECT count(*),coalesce(sum(length(raw)),0) FROM observations WHERE company=?",
                (company,),
            ).fetchone()
            existing = {r[0] for r in self.conn.execute(
                "SELECT number FROM candidates WHERE company=? AND law=?", (company, scope.law)
            )}
            candidates = self.conn.execute(
                "SELECT count(*) FROM candidates WHERE company=?", (company,)
            ).fetchone()[0]
            if count >= 2000 or size + len(raw) > 256 * 1024**2 or (
                candidates + sum(c.number not in existing for c in page.candidates) > 2000
            ):
                raise QueueError("PARTIAL_CAP_REACHED")
            self.conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)",
                              (company, observation_id, scope_json, observed, digest, raw))
            self.conn.execute("INSERT INTO partial_page_resolutions VALUES (?,?,?,?,?)",
                              (company, observation_id, actor_id, now.isoformat(),
                               "NULL_TYPE_GAPS_UNKNOWN"))
            self.conn.executemany("INSERT INTO partial_page_gaps VALUES (?,?,?,?,?)", [
                (company, observation_id, position, number, "NULL_TYPE_UNKNOWN")
                for position, number in gaps
            ])
            for candidate in page.candidates:
                self.conn.execute(
                    "INSERT INTO candidates VALUES (?,?,?,?,?) "
                    "ON CONFLICT(company,law,number) DO UPDATE SET "
                    "observation_id=excluded.observation_id,status='PENDING'",
                    (company, scope.law, candidate.number, observation_id, "PENDING"),
                )
            self.conn.execute("INSERT INTO audit VALUES (?,?,?)",
                              (company, observation_id, "PARTIAL_OBSERVED_UNKNOWN"))
            if page.may_have_more and scope.offset == MAX_OFFSET:
                self.conn.execute("UPDATE provider_holds SET reason='OFFSET_LIMIT' WHERE company=?",
                                  (company,))
            else:
                self.conn.execute("DELETE FROM provider_hold_evidence WHERE company=?", (company,))
                self.conn.execute("DELETE FROM provider_holds WHERE company=?", (company,))
                if page.may_have_more:
                    self.conn.execute(
                        "INSERT INTO scan_cursors VALUES (?,?,?,?,?,?) ON CONFLICT(company,law) "
                        "DO UPDATE SET offset=excluded.offset",
                        (company, scope.law, s["end"], s["start"], s["end"], scope.offset + 100),
                    )
                    self.conn.execute(
                        "UPDATE legacy_scan_resumptions SET offset=? WHERE company=? AND law=?",
                        (scope.offset + 100, company, scope.law),
                    )
                    self.conn.execute(
                        "INSERT INTO partial_scan_resumptions VALUES (?,?,?,?,?,?,?) "
                        "ON CONFLICT(company,law) DO UPDATE SET "
                        "observation_id=excluded.observation_id,"
                        "started_at=excluded.started_at,start_at=excluded.start_at,"
                        "end_at=excluded.end_at,offset=excluded.offset",
                        (company, scope.law, observation_id, s["end"], s["start"], s["end"],
                         scope.offset + 100),
                    )
                else:
                    for table in (
                        "scan_cursors", "legacy_scan_resumptions", "partial_scan_resumptions"
                    ):
                        self.conn.execute("DELETE FROM " + table + " WHERE company=? AND law=?",
                                          (company, scope.law))
        return len(gaps)

    def pending_with_types(self, company: str) -> list[tuple[str, str, str, str]]:
        """Validate each observation once in a consistent, bounded-memory snapshot."""
        result = []
        verified = {}
        with self.conn:
            self.conn.execute("BEGIN")
            rows = self.conn.execute(
                "SELECT c.law,c.number,c.observation_id FROM candidates c "
                "JOIN observations o ON o.company=c.company AND o.id=c.observation_id "
                "WHERE c.company=? AND c.status='PENDING' "
                "AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.company=c.company "
                "AND a.law=c.law AND a.number=c.number AND a.observation_id=c.observation_id "
                "AND a.outcome='SYNCED') ORDER BY c.law,c.number", (company,)
            ).fetchall()
            for law, number, oid in rows:
                if oid not in verified:
                    observation = self.conn.execute(
                        "SELECT scope,observed_at,response_sha,raw FROM observations "
                        "WHERE company=? AND id=?", (company, oid)
                    ).fetchone()
                    if observation is None:
                        raise QueueError("OBSERVATION_MISSING")
                    scope_json, observed, digest, raw = observation
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise QueueError("SOURCE_HASH_MISMATCH")
                    scope = json.loads(scope_json)
                    if scope["company"] != company or scope["law"] != law:
                        raise QueueError("SCOPE_BINDING_INVALID")
                    expected_id = hashlib.sha256(
                        (scope_json + "\n" + observed + "\n" + digest).encode()
                    ).hexdigest()
                    if expected_id != oid:
                        raise QueueError("OBSERVATION_BINDING_INVALID")
                    partial = self.conn.execute(
                        "SELECT event FROM partial_page_resolutions "
                        "WHERE company=? AND observation_id=?", (company, oid)
                    ).fetchone()
                    if partial is None:
                        page = parse_page(
                            raw, law, datetime.fromisoformat(observed), scope["limit"]
                        )
                    else:
                        rejected = self.conn.execute(
                            "SELECT scope,observed_at,response_sha,raw,reason FROM rejected_pages "
                            "WHERE company=? AND id=?", (company, oid)
                        ).fetchone()
                        audit = self.conn.execute(
                            "SELECT event FROM rejected_page_audit WHERE company=? "
                            "AND observation_id=?", (company, oid)
                        ).fetchone()
                        partial_audit = self.conn.execute(
                            "SELECT event FROM audit WHERE company=? AND observation_id=? "
                            "AND event='PARTIAL_OBSERVED_UNKNOWN'", (company, oid)
                        ).fetchone()
                        if partial != ("NULL_TYPE_GAPS_UNKNOWN",) or rejected != (
                            scope_json, observed, digest, raw, "TYPE_INVALID"
                        ) or audit != ("QUARANTINED_UNKNOWN",) or partial_audit != (
                            "PARTIAL_OBSERVED_UNKNOWN",
                        ):
                            raise QueueError("PARTIAL_SOURCE_BINDING_INVALID")
                        page, gaps = inspect_null_type_page(
                            raw, law, datetime.fromisoformat(observed), scope["limit"]
                        )
                        stored_gaps = self.conn.execute(
                            "SELECT row_index,number FROM partial_page_gaps WHERE company=? "
                            "AND observation_id=? ORDER BY row_index", (company, oid)
                        ).fetchall()
                        if tuple(stored_gaps) != gaps:
                            raise QueueError("PARTIAL_GAPS_CHANGED")
                    verified[oid] = (
                        law, {item.number: item.document_type for item in page.candidates}
                    )
                bound_law, types = verified[oid]
                if bound_law != law or number not in types:
                    raise QueueError("CANDIDATE_BINDING_INVALID")
                result.append((law, number, oid, types[number]))
        return result

    def pending(self, company: str) -> list[tuple[str, str, str]]:
        """Return source-validated pending identities."""
        return [(law, number, oid) for law, number, oid, _ in self.pending_with_types(company)]

    def discard_present(self, company: str, law: Law, numbers: set[str]) -> int:
        """Drop queued IDs confirmed in the local DB; retain raw evidence and audit.

        This is identity-only cleanup, never proof of version completeness. The caller
        obtains numbers from a tenant-scoped read of immutable official versions.
        """
        verified = [row for row in self.pending(company) if row[0] == law and row[1] in numbers]
        removed = 0
        with self.conn:
            for _law, number, observation in verified:
                deleted = self.conn.execute(
                    "DELETE FROM candidates WHERE company=? AND law=? AND number=? "
                    "AND observation_id=? AND NOT EXISTS (SELECT 1 FROM attempts a "
                    "WHERE a.company=? AND a.law=? AND a.number=? AND a.outcome IS NULL)",
                    (company, law, number, observation, company, law, number),
                )
                if deleted.rowcount:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO audit VALUES (?,?,?)",
                        (company, observation, f"IDENTITY_PRESENT/{law}/{number}"),
                    )
                    removed += 1
        return removed

    def claim(
        self,
        company: str,
        law: Law,
        number: str,
        now: datetime,
        expected_observation: str | None = None,
    ) -> str:
        """Claim once before network; an interrupted claim is not silently retried."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise QueueError("CLAIM_TIME_INVALID")
        matches = [row for row in self.pending(company) if row[0] == law and row[1] == number]
        if len(matches) != 1:
            raise QueueError("CANDIDATE_NOT_FOUND")
        if expected_observation is not None and matches[0][2] != expected_observation:
            raise QueueError("CANDIDATE_CHANGED")
        identity = uuid4().hex
        try:
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                if self.conn.execute(
                    "SELECT 1 FROM offset_recovery_reservations WHERE company=?", (company,)
                ).fetchone():
                    raise OffsetRecoveryReserved("OFFSET_RECOVERY_RESERVED")
                current = self.conn.execute(
                    "SELECT observation_id FROM candidates WHERE company=? AND law=? AND number=?",
                    (company, law, number),
                ).fetchone()
                if current != (matches[0][2],):
                    raise QueueError("CANDIDATE_CHANGED")
                self.conn.execute(
                    "INSERT INTO attempts VALUES (?,?,?,?,?,?,NULL,NULL)",
                    (company, identity, law, number, current[0], now.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise QueueError("ATTEMPT_IN_PROGRESS") from exc
        return identity

    def finish(self, company: str, attempt: str, outcome: str, official_sha: str | None) -> None:
        """Close an attempt only with explicit source result; preserve the full history."""
        if outcome not in {"SYNCED", "NO_DATA", "PREPARING", "SERVICE_ERROR", "UNKNOWN"}:
            raise QueueError("OUTCOME_INVALID")
        if official_sha is not None and not re.fullmatch(r"[0-9a-f]{64}", official_sha):
            raise QueueError("OFFICIAL_SHA_INVALID")
        if outcome == "SYNCED" and official_sha is None:
            raise QueueError("OFFICIAL_SHA_REQUIRED")
        with self.conn:
            result = self.conn.execute(
                "UPDATE attempts SET outcome=?,official_sha=? WHERE company=? AND id=? "
                "AND outcome IS NULL",
                (outcome, official_sha, company, attempt),
            )
            if result.rowcount != 1:
                raise QueueError("ATTEMPT_NOT_ACTIVE")

    def candidate_type(self, company: str, law: Law, number: str) -> str:
        """Read provider type only after validating the bound observation."""
        matches = [
            row for row in self.pending_with_types(company) if row[0] == law and row[1] == number
        ]
        if len(matches) != 1:
            raise QueueError("CANDIDATE_NOT_FOUND")
        return matches[0][3]
