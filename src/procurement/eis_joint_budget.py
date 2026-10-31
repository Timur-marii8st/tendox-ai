"""Durable shared start accounting, used only under the server import lease."""

from __future__ import annotations

import math
import os
import re
import stat
import tempfile
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Law = Literal["44", "223"]
# Accepted national outage baseline; do not promote older history to recovery.
NATIONAL_RECOVERY_START = date(2026, 10, 9)


class BudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    company_id: str
    hour: AwareDatetime
    used_seconds: float = Field(ge=0, le=7200, allow_inf_nan=False)
    recovery44_seconds: float = Field(ge=0, le=7200, allow_inf_nan=False)
    recovery223_seconds: float = Field(ge=0, le=7200, allow_inf_nan=False)
    active_reservation: float = Field(ge=0, le=540, allow_inf_nan=False)
    active_started_at: AwareDatetime | None = None


class HistoryTurnState(BaseModel):
    """Separate opt-in accounting; never changes the existing budget JSON schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    company_id: str
    hour: AwareDatetime
    status: Literal["UNUSED", "PENDING", "FINISHED", "UNCERTAIN"]
    window_key: str | None = None
    demand_sha256: str | None = None
    claim_id: str | None = None


class JointStartBudget:
    """54min shared admission; atomic180s tail;60s recovery starts per law/hour.

    The existing import lease serializes source work. An additional file lock
    protects this tenant's accounting from accidental concurrent callers.
    Crash reservations are conservative; they never acknowledge source windows.
    """

    START_SECONDS = 3240
    WINDOW_SECONDS = 180
    RECOVERY_SECONDS = 60
    PROTECTED_RECOVERY_SECONDS = 360

    def __init__(self, root: Path, company: str, *, reservation: int = 360):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", company) or reservation not in {360, 540}:
            raise ValueError("JOINT_BUDGET_SCOPE_INVALID")
        self.company = company
        self.history_path = root / f"eis-history-turn-{company}.json"
        self._history_owned_claim: str | None = None
        self.protected_reconciliation = os.environ.get("EIS_RECONCILIATION_SHARE_ENABLED") == "1"
        self.path = root / f"eis-joint-budget-{company}.json"
        self.lock = (root / f"eis-joint-budget-{company}.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.lock.seek(0)
                self.lock.write(b"0")
                self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            now = datetime.now(UTC)
            hour = now.replace(minute=0, second=0, microsecond=0)
            state = BudgetState(
                company_id=company,
                hour=hour,
                used_seconds=0,
                recovery44_seconds=0,
                recovery223_seconds=0,
                active_reservation=0,
            )
            self.started_at = now
            if self.path.exists():
                old = BudgetState.model_validate_json(self.path.read_bytes())
                if (
                    old.company_id != company
                    or old.hour > hour
                    or old.hour
                    != old.hour.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
                    or (bool(old.active_reservation) != (old.active_started_at is not None))
                    or (old.active_started_at is not None and old.active_started_at > now)
                ):
                    raise ValueError("JOINT_BUDGET_BINDING_INVALID")
                crash_charge = (
                    max(old.active_reservation, (now - old.active_started_at).total_seconds())
                    if old.active_started_at is not None
                    else 0
                )
                if old.hour == hour:
                    state = old.model_copy(
                        update={
                            "used_seconds": min(7200, old.used_seconds + crash_charge),
                            "recovery44_seconds": min(7200, old.recovery44_seconds + crash_charge),
                            "recovery223_seconds": min(
                                7200, old.recovery223_seconds + crash_charge
                            ),
                            "active_reservation": 0,
                            "active_started_at": None,
                        }
                    )
                elif old.active_reservation:
                    # Unknown synchronous work has no assumed180s wall ceiling.
                    # Charge the whole current-hour interval through restart;
                    # overcharging a crashed idle process is intentionally safe.
                    carry = max(180, (now - hour).total_seconds())
                    state = state.model_copy(
                        update={
                            "used_seconds": carry,
                            "recovery44_seconds": carry,
                            "recovery223_seconds": carry,
                        }
                    )
            self.state = BudgetState.model_validate(state.model_dump())
            self.started = time.monotonic()
            self.recovery = {"44": 0.0, "223": 0.0}
            self.window: tuple[Law | None, float] | None = None
            self._write(
                self.state.model_copy(
                    update={"active_reservation": reservation, "active_started_at": now}
                )
            )
        except BaseException:
            self.lock.close()
            raise

    def _write(self, state: BudgetState) -> None:
        raw = state.model_dump_json().encode()
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        if os.name != "nt":
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def recovery_reserved(self, law: Law) -> bool:
        """A share admits attempts only; it never acknowledges a source window."""
        return self.protected_reconciliation and (
            getattr(self.state, f"recovery{law}_seconds") + self.recovery[law]
            < self.PROTECTED_RECOVERY_SECONDS
        )

    @staticmethod
    def _history_hour() -> datetime:
        now = datetime.now(UTC)
        return now.replace(minute=0, second=0, microsecond=0)

    def _read_history_turn(self) -> HistoryTurnState:
        if self.lock.closed:
            raise ValueError("HISTORY_BUDGET_LOCK_REQUIRED")
        try:
            fd = os.open(self.history_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError as error:
            raise ValueError("HISTORY_STATE_MISSING") from error
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("HISTORY_STATE_INVALID")
            raw = handle.read(16385)
        if len(raw) > 16384:
            raise ValueError("HISTORY_STATE_INVALID")
        state = HistoryTurnState.model_validate_json(raw)
        hour = self._history_hour()
        if (
            state.company_id != self.company
            or state.hour.utcoffset() != timedelta(0)
            or state.hour != state.hour.replace(minute=0, second=0, microsecond=0)
            or state.hour > hour
            or (state.status == "UNUSED")
            != (state.window_key is None and state.demand_sha256 is None and state.claim_id is None)
            or (
                state.status != "UNUSED"
                and (not state.window_key or not state.demand_sha256 or not state.claim_id)
            )
            or (
                state.window_key is not None
                and not re.fullmatch(r"[^\x00-\x1f\x7f]{1,512}", state.window_key)
            )
            or (
                state.demand_sha256 is not None
                and not re.fullmatch(r"[0-9a-f]{64}", state.demand_sha256)
            )
            or (state.claim_id is not None and not re.fullmatch(r"[0-9a-f]{32}", state.claim_id))
        ):
            raise ValueError("HISTORY_STATE_INVALID")
        return state

    def _write_history_turn(self, state: HistoryTurnState) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".eis-history-turn-", dir=self.history_path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(state.model_dump_json().encode())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.history_path)
            directory = os.open(self.history_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def claim_history_turn(self, window_key: str, demand_sha256: str) -> bool:
        """Reserve one READY turn; caller must validate demand and audit before source."""
        if not self.protected_reconciliation:
            raise ValueError("HISTORY_RECONCILIATION_GUARD_REQUIRED")
        if not re.fullmatch(r"[^\x00-\x1f\x7f]{1,512}", window_key) or not re.fullmatch(
            r"[0-9a-f]{64}", demand_sha256
        ):
            raise ValueError("HISTORY_CLAIM_INVALID")
        state = self._read_history_turn()
        hour = self._history_hour()
        if state.status == "UNCERTAIN" or (state.hour == hour and state.status != "UNUSED"):
            return False
        if state.hour < hour and state.status == "PENDING":
            self._write_history_turn(state.model_copy(update={"hour": hour, "status": "UNCERTAIN"}))
            return False
        if not self.can_start(pending_reconciliation=("44", "223")):
            return False
        claim_id = uuid.uuid4().hex
        self._write_history_turn(
            HistoryTurnState(
                company_id=self.company, hour=hour, status="PENDING",
                window_key=window_key, demand_sha256=demand_sha256, claim_id=claim_id,
            )
        )
        self._history_owned_claim = claim_id
        return True

    def finish_history_turn(self) -> None:
        """Record completion without returning the hourly slot, including on rollover."""
        state = self._read_history_turn()
        if state.status != "PENDING":
            raise ValueError("HISTORY_TURN_NOT_PENDING")
        if self._history_owned_claim is None or state.claim_id != self._history_owned_claim:
            raise ValueError("HISTORY_TURN_NOT_OWNED")
        self._write_history_turn(
            state.model_copy(update={"hour": self._history_hour(), "status": "FINISHED"})
        )
        self._history_owned_claim = None

    def can_start(
        self,
        recovery_law: Law | None = None,
        *,
        borrow: bool = False,
        pending_reconciliation: tuple[Law, ...] = (),
    ) -> bool:
        elapsed = time.monotonic() - self.started
        now = datetime.now(UTC)
        remaining_wall = (self.state.hour + timedelta(hours=1) - now).total_seconds()
        if elapsed < 0 or not math.isfinite(elapsed) or remaining_wall < self.WINDOW_SECONDS:
            return False
        used = self.state.used_seconds + elapsed
        if used >= self.START_SECONDS or used + self.WINDOW_SECONDS > 3600:
            return False
        if self.protected_reconciliation:
            reserve = sum(
                max(
                    0,
                    self.PROTECTED_RECOVERY_SECONDS
                    - getattr(self.state, f"recovery{law}_seconds")
                    - self.recovery[law],
                )
                for law in set(pending_reconciliation)
                if law != recovery_law
            )
            if reserve and used + self.WINDOW_SECONDS + reserve > self.START_SECONDS:
                return False
        recovery_limit = (
            self.PROTECTED_RECOVERY_SECONDS
            if self.protected_reconciliation
            else self.RECOVERY_SECONDS
        )
        if recovery_law:
            previous = getattr(self.state, f"recovery{recovery_law}_seconds")
            if previous + self.recovery[recovery_law] >= recovery_limit:
                if not borrow:
                    return False
                other = "223" if recovery_law == "44" else "44"
                reserve = max(
                    0,
                    recovery_limit
                    - getattr(self.state, f"recovery{other}_seconds")
                    - self.recovery[other],
                )
                if used + self.WINDOW_SECONDS + reserve > self.START_SECONDS:
                    return False
        return True

    def begin_window(self, recovery_law: Law | None) -> None:
        if self.window is not None:
            raise ValueError("JOINT_WINDOW_ALREADY_ACTIVE")
        self.window = (recovery_law, time.monotonic())

    def end_window(self) -> None:
        if self.window is not None:
            law, started = self.window
            if law:
                self.recovery[law] += max(0, time.monotonic() - started)
            self.window = None

    def close(self) -> None:
        try:
            self.end_window()
            elapsed = max(0, time.monotonic() - self.started)
            now = datetime.now(UTC)
            hour = now.replace(minute=0, second=0, microsecond=0)
            state = self.state
            if hour > state.hour:
                current_spent = min(elapsed, (now - hour).total_seconds())
                state = BudgetState(
                    company_id=state.company_id,
                    hour=hour,
                    used_seconds=current_spent,
                    recovery44_seconds=min(current_spent, self.recovery["44"]),
                    recovery223_seconds=min(current_spent, self.recovery["223"]),
                    active_reservation=0,
                )
                self._write(state)
                return
            self._write(
                BudgetState.model_validate(
                    state.model_copy(
                        update={
                            "used_seconds": self.state.used_seconds + elapsed,
                            "recovery44_seconds": self.state.recovery44_seconds
                            + self.recovery["44"],
                            "recovery223_seconds": self.state.recovery223_seconds
                            + self.recovery["223"],
                            "active_reservation": 0,
                            "active_started_at": None,
                        }
                    ).model_dump()
                )
            )
        finally:
            self.lock.close()

    def __enter__(self) -> JointStartBudget:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
