"""Explainable comparison over an already downloaded EIS notice corpus.

This is a bounded first pass. It matches notice titles and individual lot item
names; full lot composition, quote validity and gates require later review.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from snowballstemmer.russian_stemmer import RussianStemmer  # type: ignore[import-untyped]

from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    DiscoveryEstimate,
    calculate_discovery_economics,
)
from procurement.sources.eis_feed_archive import EisLotItem, EisNoticeSnapshot
from procurement.sources.eis_procedure_state import EisProcedureState

_WORD = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_INTENT_WORDS = frozenset(
    {"хочу", "хотим", "купить", "продать", "перепродавать", "ищи", "найди", "закупки", "тендеры"}
)
# Query-only exclusion: persisted title/item v1 keys must not change without reindex.
_QUERY_FUNCTION_WORDS = frozenset({"для", "при", "или", "как", "это", "что"})
_SECURITIES_ADJECTIVES = frozenset(
    {
        "ценный",
        "ценная",
        "ценное",
        "ценные",
        "ценного",
        "ценной",
        "ценным",
        "ценному",
        "ценную",
        "ценными",
        "ценных",
        "ценном",
    }
)
EisSearchValueKind = Literal[
    "TITLE",
    "ITEM_NAME",
    "CHARACTERISTIC_NAME",
    "TEXT",
    "MINIMUM",
    "MAXIMUM",
    "UNIT",
    "PURCHASE_NUMBER",
]


@dataclass(frozen=True)
class EisSearchTermEvidence:
    term: str
    locator: str
    source_value: str
    value_kind: EisSearchValueKind


@dataclass(frozen=True)
class EisComparedNotice:
    snapshot: EisNoticeSnapshot
    matched_terms: tuple[str, ...]
    match_locator: str
    match_quality: str
    application_status: str
    economics_status: str
    estimate: DiscoveryEstimate | None
    conservative_profit_rub: Decimal | None
    reasons: tuple[str, ...]
    term_evidence: tuple[EisSearchTermEvidence, ...] = ()


@dataclass(frozen=True)
class EisIndexComparison:
    query: str
    inspected_current_notices: int
    matched_notices: tuple[EisComparedNotice, ...]
    corpus_coverage: str = "UNKNOWN"
    comparison_kind: str = "PRELIMINARY"


def _tokens(text: str) -> tuple[str, ...]:
    words = (word.casefold().replace("ё", "е") for word in _WORD.findall(text))
    return tuple(
        dict.fromkeys(word for word in words if len(word) >= 3 and word not in _INTENT_WORDS)
    )


def _key(word: str) -> str:
    if word in {"маска", "маски", "масок", "маску", "маской", "масками", "масках", "маскам"}:
        return "маск"
    return word[:5] if len(word) >= 6 and re.fullmatch(r"[а-я]+", word) else word


def search_keys_v1(text: str) -> tuple[str, ...]:
    """Stable v1 prefilter keys, shared by intake and the exact comparison.

    Changing these semantics requires rebuilding the derived search index.
    """
    return tuple(sorted({_key(word) for word in _tokens(text)}))


def _query_tokens(text: str) -> tuple[str, ...]:
    return tuple(word for word in _detail_tokens(text) if word not in _QUERY_FUNCTION_WORDS)


def _detail_tokens(text: str) -> tuple[str, ...]:
    words = (word.casefold().replace("ё", "е") for word in _WORD.findall(text))
    return tuple(
        dict.fromkeys(
            word
            for word in words
            if word not in _INTENT_WORDS
            and (len(word) >= 3 or (len(word) == 2 and any(char.isdigit() for char in word)))
        )
    )


@lru_cache(maxsize=16384)
def _comparison_key(word: str) -> str:
    # Explicit visual spelling variants of the common paper format labels.
    if re.fullmatch(r"а[3456]", word):
        return "a" + word[1:]
    if _key(word) == "маск":
        return "маск"  # Explicit irregular forms retained from v1.
    if re.fullmatch(r"[а-я]+", word):
        # Instances carry mutable state: each cache miss owns its stemmer.
        # Coarse persisted v1 keys are deliberately separate from this verifier.
        stem = str(RussianStemmer().stemWord(word))
        return "латекс" if stem == "латексн" else stem
    return word


def search_query_keys_v1(text: str) -> tuple[str, ...]:
    """Meaningful query keys; existing document keys are a safe superset."""
    return tuple(
        sorted({_key(word) for word in _tokens(text) if word not in _QUERY_FUNCTION_WORDS})
    )


def exact_purchase_number(query: str) -> str | None:
    """Полный номер 223/44-ФЗ остаётся строкой, включая ведущие нули."""
    query = query.strip()
    return query if re.fullmatch(r"(?:[0-9]{11}|[0-9]{19,23})", query) else None


def _evidence(
    parts: Iterable[tuple[str, str, EisSearchValueKind]],
    query_terms: tuple[str, ...],
) -> tuple[EisSearchTermEvidence, ...]:
    found: dict[str, EisSearchTermEvidence] = {}
    query_keys = {_comparison_key(term) for term in query_terms}
    exclude_securities = "бумаг" in query_keys and not any(
        term in _SECURITIES_ADJECTIVES for term in query_terms
    )
    for value, locator, kind in parts:
        keys = {_comparison_key(word) for word in _detail_tokens(value)}
        if exclude_securities and "бумаг" in keys:
            # Preserve occurrences: a field can mention securities and office paper.
            # Persisted v1 keys remain an unchanged, deliberately broad prefilter.
            words = _WORD.findall(value.casefold().replace("ё", "е"))
            if not any(
                _comparison_key(word) == "бумаг"
                and (index == 0 or words[index - 1] not in _SECURITIES_ADJECTIVES)
                for index, word in enumerate(words)
            ):
                keys.remove("бумаг")
        for term in query_terms:
            if term not in found and _comparison_key(term) in keys:
                found[term] = EisSearchTermEvidence(term, locator, value, kind)
        if len(found) == len(query_terms):
            break
    return tuple(found[term] for term in query_terms if term in found)


def match_search_terms(
    parts: Iterable[tuple[str, str, EisSearchValueKind]], query: str
) -> tuple[EisSearchTermEvidence, ...]:
    """Read-only lexical evidence shared by law-specific notice adapters."""
    terms = _query_tokens(query)
    if not terms or not search_query_keys_v1(query) or len(query) > 120:
        raise ValueError("QUERY_INVALID")
    return _evidence(parts, terms)


def search_query_terms(query: str) -> tuple[str, ...]:
    """Meaningful modifiers without pretending they establish compliance."""
    match_search_terms((), query)
    return _query_tokens(query)


def _item_parts(item: EisLotItem) -> Iterable[tuple[str, str, EisSearchValueKind]]:
    yield item.name, f"{item.locator}/name", "ITEM_NAME"
    for characteristic in item.characteristics:
        yield characteristic.name, characteristic.locator, "CHARACTERISTIC_NAME"
        for value in characteristic.values:
            fields: tuple[tuple[str | Decimal | None, EisSearchValueKind], ...] = (
                (value.quality_description, "TEXT"),
                (value.minimum, "MINIMUM"),
                (value.maximum, "MAXIMUM"),
                (value.unit, "UNIT"),
            )
            for field, kind in fields:
                if field is not None:
                    yield str(field), value.locator, kind


def compare_indexed_notices(
    notices: Iterable[EisNoticeSnapshot],
    query: str,
    *,
    now: datetime,
    costs_by_exact_notice: Mapping[tuple[str, str], DiscoveryCostInput] | None = None,
    procedure_states: Mapping[str, EisProcedureState] | None = None,
) -> EisIndexComparison:
    """Keep the latest version, then compare exact evidence and optional costs."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    query = query.strip()
    number = exact_purchase_number(query)
    query_terms = _query_tokens(query)
    if not query_terms or not search_query_keys_v1(query) or len(query) > 120:
        raise ValueError("QUERY_INVALID")
    current: dict[str, EisNoticeSnapshot] = {}
    for notice in notices:
        previous = current.get(notice.purchase_number)
        if previous is None or notice.version_number > previous.version_number:
            current[notice.purchase_number] = notice
        elif (
            notice.version_number == previous.version_number
            and notice.xml_sha256 != previous.xml_sha256
        ):
            raise ValueError("NOTICE_VERSION_CONFLICT")
    matched: list[EisComparedNotice] = []
    anchor_keys = set(search_query_keys_v1(query))
    for notice in current.values():
        notice_keys = set(search_keys_v1(notice.title))
        for item in notice.lot_items:
            notice_keys.update(search_keys_v1(item.name))
        if number is not None and notice.purchase_number != number:
            continue
        if number is None and not anchor_keys & notice_keys:
            continue
        match_locator = f"{notice.document_type}/commonInfo/" + (
            "purchaseNumber" if number is not None else "purchaseObjectInfo"
        )
        evidence = (
            (
                EisSearchTermEvidence(
                    number, match_locator, notice.purchase_number, "PURCHASE_NUMBER"
                ),
            )
            if number is not None
            else _evidence(((notice.title, match_locator, "TITLE"),), query_terms)
        )
        hits = tuple(item.term for item in evidence)
        for item in notice.lot_items:
            if len(evidence) == len(query_terms):
                break
            item_evidence = _evidence(_item_parts(item), query_terms)
            item_hits = tuple(part.term for part in item_evidence)
            if len(item_hits) > len(hits):
                hits = item_hits
                evidence = item_evidence
                match_locator = (
                    item.locator
                    if any(part.value_kind != "ITEM_NAME" for part in evidence)
                    else f"{item.locator}/name"
                )
        if not hits:
            continue
        strong_match = len(hits) == len(query_terms)
        expired = notice.deadline is not None and notice.deadline <= now
        status = "FAIL" if expired else "UNKNOWN"
        procedure = (procedure_states or {}).get(notice.purchase_number)
        if procedure is not None and procedure.application_status == "FAIL":
            status = "FAIL"
        reasons = [
            (
                f"Точный регистрационный номер: {number}; XML: {match_locator}."
                if number is not None
                else f"Совпадение слов: {', '.join(hits)}; XML: {match_locator}."
            ),
            (
                f"Источник: XML {notice.xml_sha256}, файл {notice.source_member}, "
                f"версия {notice.version_number}."
            ),
        ]
        if notice.document_type == "epNotificationEOK2020":
            reasons.append(
                "Электронный открытый конкурс: критерии оценки и квалификация UNKNOWN; "
                "НМЦК и релевантность не подтверждают вероятность победы. "
                "XML: epNotificationEOK2020/notificationInfo/criteriaInfo."
            )
        if procedure is not None:
            reasons.extend(procedure.reasons)
        for part in evidence:
            if part.value_kind not in {"TITLE", "ITEM_NAME", "PURCHASE_NUMBER"}:
                reasons.append(f"Уточнение {part.term}: {part.source_value}; XML: {part.locator}.")
        if any(part.value_kind in {"MINIMUM", "MAXIMUM"} for part in evidence):
            reasons.append(
                "Число найдено в границе характеристики; точное соответствие требует "
                "проверки диапазона и единиц."
            )
        if not strong_match:
            reasons.append("Совпала только часть запроса; предмет лота требует проверки.")
            reasons.append(
                "Не найдены в выбранной позиции/заголовке: "
                + ", ".join(term for term in query_terms if term not in hits)
                + "."
            )
        if expired:
            reasons.append("Срок подачи истёк; кандидат заблокирован.")
        elif notice.deadline is None:
            reasons.append("Срок с часовым поясом неизвестен; статус подачи не подтверждён.")
        else:
            reasons.append("Срок ещё не истёк; текущий этап подачи требует проверки.")
        estimate = None
        profit = None
        exact_costs = (costs_by_exact_notice or {}).get((notice.purchase_number, notice.xml_sha256))
        if strong_match and exact_costs is not None and notice.deadline is not None:
            estimate = calculate_discovery_economics(
                notice.nmck_rub, exact_costs, blocked=status == "FAIL"
            )
            if estimate.status == "ESTIMATE":
                profit = next(
                    item.profit for item in estimate.scenarios if item.kind == "conservative"
                )
                reasons.append(
                    "Предварительный порядок по консервативной прибыли из указанных расходов."
                )
        if profit is None:
            reasons.append("Выгода неизвестна: нет сопоставимого полного расчёта по этому XML.")
        matched.append(
            EisComparedNotice(
                snapshot=notice,
                matched_terms=hits,
                match_locator=match_locator,
                match_quality="STRONG" if strong_match else "PARTIAL",
                application_status=status,
                economics_status=estimate.status if estimate else "UNKNOWN",
                estimate=estimate,
                conservative_profit_rub=profit,
                reasons=tuple(reasons),
                term_evidence=evidence,
            )
        )
    matched.sort(
        key=lambda item: (
            item.application_status == "FAIL",
            item.match_quality != "STRONG",
            item.conservative_profit_rub is None,
            -(item.conservative_profit_rub or Decimal(0)),
            -len(item.matched_terms),
            item.snapshot.purchase_number,
        )
    )
    return EisIndexComparison(
        query=query,
        inspected_current_notices=len(current),
        matched_notices=tuple(matched),
    )
