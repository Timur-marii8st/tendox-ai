"""Tenant-scoped EIS worklist and immutable attempt journal.

Only a fully ingested archive window closes a planned target. NO_DATA and
transport failures remain visible gaps even after the CLI process exits.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import and_, exists, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.selectable import CTE, ScalarSelect

from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_sync_attempts,
    eis_sync_targets,
)

if TYPE_CHECKING:
    from procurement.sources.eis_feed_sync import EisSelection
    from procurement.sources.eis_freshness_status import EisWindowObservation
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport
    from procurement.storage.repository import PostgresStorage

EisAttemptOutcome = Literal["SYNCED", "SKIPPED", "NO_DATA", "PREPARING", "SERVICE_ERROR", "FAILED"]
_OUTCOMES = frozenset({"SYNCED", "SKIPPED", "NO_DATA", "PREPARING", "SERVICE_ERROR", "FAILED"})
_DATE_WINDOW = re.compile(
    r"^getDocsIP/PRIZ/[0-9]{1,2}/[0-9]{4}-[0-9]{2}-[0-9]{2}(?:/[0-9]{2})?[+-][0-9]{2}:00(?:/(?:epNotificationEZK2020|epNotificationEOK2020|epNotificationCancel|epNotificationCancelFailure))?$"
)
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EisSyncGap:
    window_key: str
    planned_at: datetime
    last_outcome: str | None
    last_reason_code: str | None
    last_source_response_sha256: str | None
    last_attempted_at: datetime | None
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


def latest_eis_attempts(company_id: str) -> CTE:
    """One deterministic latest attempt per tenant/window, before eligibility filters."""
    return (
        select(
            eis_sync_attempts.c.company_id,
            eis_sync_attempts.c.window_key,
            eis_sync_attempts.c.outcome,
            eis_sync_attempts.c.reason_code,
            eis_sync_attempts.c.attempted_at,
            eis_sync_attempts.c.attempt_id,
            eis_sync_attempts.c.source_response_sha256,
        )
        .where(eis_sync_attempts.c.company_id == company_id)
        .distinct(eis_sync_attempts.c.window_key)
        .order_by(
            eis_sync_attempts.c.window_key,
            eis_sync_attempts.c.attempted_at.desc(),
            eis_sync_attempts.c.attempt_id.desc(),
        )
        .cte("latest_eis_attempts")
    )


class EisSyncJournal:
    """Record durable plans and attempts without retaining credentials or URLs."""

    def __init__(self, storage: PostgresStorage, company_id: str, actor_id: str) -> None:
        if not company_id.strip() or not actor_id.strip():
            raise ValueError("JOURNAL_ACTOR_INVALID")
        self.storage = storage
        self.company_id = company_id
        self.actor_id = actor_id

    def plan(self, selections: tuple[EisSelection, ...]) -> int:
        keys = tuple(selection.window_key for selection in selections)
        if not keys or len(keys) > 31 or len(set(keys)) != len(keys):
            raise ValueError("JOURNAL_PLAN_INVALID")
        if any(not _DATE_WINDOW.fullmatch(key) for key in keys):
            raise ValueError("JOURNAL_WINDOW_INVALID")
        now = datetime.now(UTC)
        with self.storage.transaction(self.company_id) as connection:
            created = (
                connection.execute(
                    pg_insert(eis_sync_targets)
                    .values(
                        [
                            {
                                "company_id": self.company_id,
                                "window_key": key,
                                "planned_by": self.actor_id,
                                "planned_at": now,
                                "coverage": "UNKNOWN",
                            }
                            for key in keys
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            eis_sync_targets.c.company_id,
                            eis_sync_targets.c.window_key,
                        ]
                    )
                    .returning(eis_sync_targets.c.window_key)
                )
                .scalars()
                .all()
            )
            if created:
                connection.execute(
                    insert(audit_events),
                    [
                        dict(
                            event_id=str(uuid.uuid4()),
                            company_id=self.company_id,
                            actor_id=self.actor_id,
                            event_type="EIS_SYNC_TARGET_PLANNED",
                            object_type="eis_sync_target",
                            object_id=key,
                            basis={"window_key": key, "coverage": "UNKNOWN"},
                            occurred_at=now,
                        )
                        for key in created
                    ],
                )
        return len(created)

    def record(
        self,
        window_key: str,
        outcome: EisAttemptOutcome,
        *,
        reason_code: str | None = None,
        source_response_sha256: str | None = None,
        observation: EisWindowObservation | None = None,
        variant_intake: EisVariantIntakeReport | None = None,
    ) -> str:
        if not _DATE_WINDOW.fullmatch(window_key) or outcome not in _OUTCOMES:
            raise ValueError("JOURNAL_ATTEMPT_INVALID")
        if observation is not None and (
            observation.company_id != self.company_id
            or observation.window_key != window_key
            or observation.outcome != outcome
            or observation.response_sha256 != source_response_sha256
        ):
            raise ValueError("JOURNAL_OBSERVATION_MISMATCH")
        if reason_code is not None and not _REASON.fullmatch(reason_code):
            raise ValueError("JOURNAL_REASON_INVALID")
        if source_response_sha256 is not None and not _SHA.fullmatch(source_response_sha256):
            raise ValueError("JOURNAL_RESPONSE_SHA_INVALID")
        if variant_intake is not None and (
            outcome != "FAILED"
            or source_response_sha256 is None
            or (observation is not None and observation.variant_intake != variant_intake)
        ):
            raise ValueError("JOURNAL_VARIANT_INTAKE_MISMATCH")
        if (outcome == "FAILED" and not reason_code) or (
            outcome == "NO_DATA" and not source_response_sha256
        ):
            raise ValueError("JOURNAL_EVIDENCE_MISSING")
        attempt_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self.storage.transaction(self.company_id) as connection:
            connection.execute(
                insert(eis_sync_attempts).values(
                    company_id=self.company_id,
                    attempt_id=attempt_id,
                    window_key=window_key,
                    actor_id=self.actor_id,
                    outcome=outcome,
                    reason_code=reason_code,
                    source_response_sha256=source_response_sha256,
                    attempted_at=now,
                )
            )
            connection.execute(
                insert(audit_events).values(
                    event_id=str(uuid.uuid4()),
                    company_id=self.company_id,
                    actor_id=self.actor_id,
                    event_type="EIS_SYNC_ATTEMPT_RECORDED",
                    object_type="eis_sync_target",
                    object_id=window_key,
                    basis={
                        "attempt_id": attempt_id,
                        "outcome": outcome,
                        "reason_code": reason_code,
                        "source_response_sha256": source_response_sha256,
                        **(
                            {"variant_intake": variant_intake.model_dump(mode="json")}
                            if variant_intake is not None
                            else {}
                        ),
                        **(
                            {"observation": observation.model_dump(mode="json")}
                            if observation is not None
                            else {}
                        ),
                    },
                    occurred_at=now,
                )
            )
        return attempt_id

    def gaps(self, *, region: str | None = None, limit: int = 500) -> tuple[EisSyncGap, ...]:
        if region is not None and not re.fullmatch(r"[0-9]{1,2}", region):
            raise ValueError("JOURNAL_REGION_INVALID")
        if not 1 <= limit <= 1000:
            raise ValueError("JOURNAL_LIMIT_INVALID")
        target = eis_sync_targets
        attempt = eis_sync_attempts

        def latest(column: str) -> ScalarSelect[Any]:
            return (
                select(attempt.c[column])
                .where(
                    and_(
                        attempt.c.company_id == target.c.company_id,
                        attempt.c.window_key == target.c.window_key,
                    )
                )
                .order_by(attempt.c.attempted_at.desc(), attempt.c.attempt_id.desc())
                .limit(1)
                .correlate(target)
                .scalar_subquery()
            )

        complete = exists(
            select(eis_feed_windows.c.window_key).where(
                and_(
                    eis_feed_windows.c.company_id == target.c.company_id,
                    eis_feed_windows.c.window_key == target.c.window_key,
                    eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
                )
            )
        )
        statement = (
            select(
                target.c.window_key,
                target.c.planned_at,
                latest("outcome").label("last_outcome"),
                latest("reason_code").label("last_reason_code"),
                latest("source_response_sha256").label("last_source_response_sha256"),
                latest("attempted_at").label("last_attempted_at"),
            )
            .where(and_(target.c.company_id == self.company_id, ~complete))
            .order_by(target.c.window_key)
            .limit(limit)
        )
        if region is not None:
            statement = statement.where(target.c.window_key.like(f"getDocsIP/PRIZ/{region}/%"))
        with self.storage.transaction(self.company_id) as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(
            EisSyncGap(
                window_key=row["window_key"],
                planned_at=row["planned_at"],
                last_outcome=row["last_outcome"],
                last_reason_code=row["last_reason_code"],
                last_source_response_sha256=row["last_source_response_sha256"],
                last_attempted_at=row["last_attempted_at"],
            )
            for row in rows
        )
