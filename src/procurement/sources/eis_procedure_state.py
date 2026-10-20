"""Resolve official cancellation events without turning missing history into PASS."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from procurement.sources.eis_feed_archive import COMPANION_TYPES, EisProcedureEvent


@dataclass(frozen=True)
class EisProcedureState:
    application_status: Literal["FAIL", "UNKNOWN"]
    reasons: tuple[str, ...]


def resolve_procedure_state(
    events: Iterable[EisProcedureEvent], *, purchase_number: str, now: datetime
) -> EisProcedureState:
    """Only an unambiguous, aware official event can establish a blocking stage."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    selected = tuple(events)
    if not selected:
        return EisProcedureState("UNKNOWN", ())
    if any(event.purchase_number != purchase_number for event in selected):
        raise ValueError("EVENT_PURCHASE_MISMATCH")
    evidence = tuple(
        f"Событие {event.document_type}; XML {event.xml_sha256}; "
        f"файл {event.source_member}; локатор {event.locator}."
        for event in selected
    )
    companions = tuple(event for event in selected if event.document_type in COMPANION_TYPES)
    selected = tuple(event for event in selected if event.document_type not in COMPANION_TYPES)
    if companions:
        evidence = (
            *evidence,
            "Метаданные протоколов/разъяснений/результатов сохранены; "
            "их юридический результат и действующий этап требуют проверки.",
        )
    if not selected:
        return EisProcedureState("UNKNOWN", evidence)
    if any(
        event.published_at is None
        or event.published_at.tzinfo is None
        or event.published_at.utcoffset() is None
        or event.published_at > now
        for event in selected
    ):
        return EisProcedureState(
            "UNKNOWN",
            (*evidence, "Порядок событий не подтверждён: время отсутствует или неоднозначно."),
        )
    latest_time = max(event.published_at for event in selected if event.published_at is not None)
    latest = tuple(event for event in selected if event.published_at == latest_time)
    if len(latest) != 1:
        return EisProcedureState(
            "UNKNOWN", (*evidence, "Несколько событий имеют одно время; текущий этап неизвестен.")
        )
    event = latest[0]
    blocked = event.document_type == "epNotificationCancel" or event.recovery_stage in {
        "NP",
        "CW",
        "FO",
        "CO",
    }
    return EisProcedureState(
        "FAIL" if blocked else "UNKNOWN",
        (
            *evidence,
            "Подтверждённая отмена или этап без подачи заявок; кандидат заблокирован."
            if blocked
            else "Отмена отменена, но действующий этап, срок и полнота истории требуют проверки.",
        ),
    )
