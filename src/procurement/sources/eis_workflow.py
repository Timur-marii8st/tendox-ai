"""Возобновляемый tenant-scoped поиск, разбор и сравнение закупок ЕИС.

Один advance выполняет один сетевой шаг. Клиент продолжает с retry_at;
закрытие вкладки приостанавливает продвижение, но не удаляет результаты.
SQLite — локальный durable store пилота, не замена основной базе кейсов.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    DiscoveryEstimate,
    calculate_discovery_economics,
)
from procurement.sources import eis_public
from procurement.sources.eis_analysis import DocumentAnalysis, analyze_document
from procurement.sources.eis_public import EisPublicDetailResult, EisPublicLead

MAX_RUN_BYTES = 100 * 1024 * 1024


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=120)
    max_pages: int = Field(default=3, ge=1, le=20)
    max_candidates: int = Field(default=3, ge=1, le=10)
    max_documents: int = Field(default=6, ge=1, le=12)
    search_page_size: Literal[50, 100] = 100

    @field_validator("query")
    @classmethod
    def _query_valid(cls, value: str) -> str:
        normalized = " ".join(value.split())
        eis_public.public_search_url(normalized)
        return normalized


class Candidate(BaseModel):
    lead: EisPublicLead
    detail: EisPublicDetailResult | None = None
    customer_profile: eis_public.EisCustomerProfileResult | None = None
    customer_contracts: eis_public.EisCustomerContractsResult | None = None
    customer_history_requested: bool = False
    documents: list[DocumentAnalysis] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analysis_status: Literal["PENDING", "COMPLETE", "PARTIAL"] = "PENDING"
    application_status: Literal["UNKNOWN", "FAIL"] = "UNKNOWN"
    estimate: DiscoveryEstimate | None = None
    costs: DiscoveryCostInput | None = None
    document_list_read: bool = False


class Task(BaseModel):
    kind: Literal[
        "SEARCH", "DETAIL", "DOCUMENTS", "ATTACHMENT", "CUSTOMER_PROFILE", "CUSTOMER_CONTRACTS"
    ]
    page: int = 1
    number: str | None = None
    url: str | None = None
    filename: str | None = None
    attempts: int = 0


class SearchPageEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    page_number: int
    page_size: Literal[50, 100]
    search_url: str
    observed_at: AwareDatetime
    source_sha256: str | None
    scanned_count: int | None
    unparsed_count: int
    unidentified_count: int | None
    purchase_numbers: tuple[str, ...]
    fingerprint: str | None
    identifiers_complete: bool


SearchStopReason = Literal[
    "REPEATED_PAGE",
    "NO_NEW_IDENTIFIERS",
    "IDENTIFIERS_INCOMPLETE",
    "LEGACY_STATE_UNVERIFIED",
    "PAGE_LIMIT",
    "SOURCE_END_HINT",
    "SOURCE_ERROR",
]


class DiscoveryRun(BaseModel):
    id: str
    company_id: str
    request: DiscoveryRequest
    state: Literal["RUNNING", "COMPLETED", "CANCELLED"] = "RUNNING"
    completion_status: Literal["IN_PROGRESS", "PARTIAL", "FAILED", "CANCELLED"] = "IN_PROGRESS"
    created_at: AwareDatetime
    updated_at: AwareDatetime
    next_retry_at: AwareDatetime | None = None
    pages_read: int = 0
    scanned_count: int = 0
    unique_scanned_count: int | None = None
    identified_count: int = 0
    duplicate_count: int = 0
    unparsed_count: int = 0
    search_pages: list[SearchPageEvidence] = Field(default_factory=list)
    search_stop_reason: SearchStopReason | None = None
    warnings: list[str] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    pending_count: int = 0


class RunNotFound(ValueError):
    """Одинаковый ответ для отсутствующей и чужой сессии."""


class RunBusy(ValueError):
    """Следующий выбор можно добавить после текущего атомарного шага."""


def _db_path() -> Path:
    default = Path(__file__).resolve().parents[3] / "data" / "eis-discovery.sqlite3"
    return Path(os.environ.get("EIS_DISCOVERY_DB", str(default))).resolve()


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS eis_runs (
              company_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
              lease TEXT, lease_until TEXT, PRIMARY KEY(company_id,id));
            CREATE TABLE IF NOT EXISTS eis_artifacts (
              company_id TEXT NOT NULL, run_id TEXT NOT NULL, sha256 TEXT NOT NULL,
              filename TEXT NOT NULL, url TEXT NOT NULL, content BLOB NOT NULL,
              PRIMARY KEY(company_id,run_id,sha256));
            CREATE TABLE IF NOT EXISTS eis_audit (
              company_id TEXT NOT NULL, run_id TEXT NOT NULL, at TEXT NOT NULL,
              actor_id TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _audit(db: sqlite3.Connection, run: DiscoveryRun, actor: str, event: str, detail: str) -> None:
    db.execute(
        "INSERT INTO eis_audit VALUES (?,?,?,?,?,?)",
        (
            run.company_id,
            run.id,
            datetime.now(UTC).isoformat(),
            actor,
            event,
            detail,
        ),
    )


def _load(db: sqlite3.Connection, company: str, run_id: str) -> DiscoveryRun:
    row = db.execute(
        "SELECT payload FROM eis_runs WHERE company_id=? AND id=?", (company, run_id)
    ).fetchone()
    if row is None:
        raise RunNotFound("discovery_run_not_found")
    return DiscoveryRun.model_validate_json(row[0])


def _save(db: sqlite3.Connection, run: DiscoveryRun) -> None:
    run.updated_at = datetime.now(UTC)
    run.pending_count = len(run.tasks)
    db.execute(
        "UPDATE eis_runs SET payload=? WHERE company_id=? AND id=?",
        (run.model_dump_json(), run.company_id, run.id),
    )


def _refresh(run: DiscoveryRun) -> DiscoveryRun:
    """Пересчитать истечение срока даже у сохранённого завершённого поиска."""
    now = datetime.now(UTC)
    for candidate in run.candidates:
        lead = candidate.lead
        deadline = candidate.detail.exact_deadline if candidate.detail else None
        # A date without timezone cannot prove current validity. With no timezone,
        # wait until even UTC-12 has passed the date before declaring it expired.
        expired_date = (
            lead.deadline_date and lead.deadline_date < (now - timedelta(hours=12)).date()
        )
        blocked = lead.application_status == "FAIL" or bool(expired_date)
        if candidate.detail:
            stages = [
                f.value.casefold().strip() for f in candidate.detail.fields if f.name == "stage"
            ]
            if any(stage != "подача заявок" for stage in stages):
                blocked = True
        if deadline is not None and deadline <= now:
            blocked = True
        candidate.application_status = "FAIL" if blocked else "UNKNOWN"
        if candidate.costs:
            candidate.estimate = calculate_discovery_economics(
                lead.nmck_rub,
                candidate.costs,
                blocked=blocked,
            )

    # This is only the order of preliminary economic hypotheses, never admission.
    def order(candidate: Candidate) -> tuple[int, Decimal, int, date, str]:
        if candidate.application_status == "FAIL":
            return (2, Decimal(0), 0, date.max, candidate.lead.purchase_number)
        if candidate.estimate and candidate.estimate.status == "ESTIMATE":
            conservative = next(s for s in candidate.estimate.scenarios if s.kind == "conservative")
            return (0, -conservative.profit, 0, date.max, candidate.lead.purchase_number)
        return (
            1,
            Decimal(0),
            -len(candidate.lead.matched_terms),
            candidate.lead.deadline_date or date.max,
            candidate.lead.purchase_number,
        )

    run.candidates.sort(key=order)
    run.pending_count = len(run.tasks)
    return run


def create_run(company: str, actor: str, request: DiscoveryRequest) -> DiscoveryRun:
    now = datetime.now(UTC)
    run = DiscoveryRun(
        id=str(uuid.uuid4()),
        company_id=company,
        request=request,
        created_at=now,
        updated_at=now,
        tasks=[Task(kind="SEARCH")],
        pending_count=1,
    )
    with _db() as db:
        db.execute(
            "INSERT INTO eis_runs(company_id,id,payload) VALUES (?,?,?)",
            (company, run.id, run.model_dump_json()),
        )
        _audit(db, run, actor, "discovery.created", request.model_dump_json())
    return run


def get_run(company: str, run_id: str) -> DiscoveryRun:
    with _db() as db:
        return _refresh(_load(db, company, run_id))


def list_runs(company: str) -> list[dict[str, str]]:
    with _db() as db:
        rows = db.execute(
            "SELECT payload FROM eis_runs WHERE company_id=? ORDER BY rowid DESC LIMIT 30",
            (company,),
        ).fetchall()
    return [
        dict(id=r.id, query=r.request.query, state=r.state, created_at=r.created_at.isoformat())
        for row in rows
        for r in [DiscoveryRun.model_validate_json(row[0])]
    ]


def _artifact(run: DiscoveryRun, content: bytes, filename: str, url: str) -> str:
    digest = hashlib.sha256(content).hexdigest()
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        if _load(db, run.company_id, run.id).state != "RUNNING":
            raise ValueError("RUN_STOPPED")
        existing = db.execute(
            "SELECT 1 FROM eis_artifacts WHERE company_id=? AND run_id=? AND sha256=?",
            (run.company_id, run.id, digest),
        ).fetchone()
        total = db.execute(
            "SELECT COALESCE(SUM(length(content)),0) FROM eis_artifacts "
            "WHERE company_id=? AND run_id=?",
            (run.company_id, run.id),
        ).fetchone()[0]
        if not existing and total + len(content) > MAX_RUN_BYTES:
            raise ValueError("RUN_ARTIFACT_LIMIT")
        db.execute(
            "INSERT OR IGNORE INTO eis_artifacts VALUES (?,?,?,?,?,?)",
            (run.company_id, run.id, digest, filename, url, content),
        )
    return digest


def read_artifact(company: str, run_id: str, digest: str) -> tuple[str, bytes]:
    with _db() as db:
        _load(db, company, run_id)
        row = db.execute(
            "SELECT filename,content FROM eis_artifacts "
            "WHERE company_id=? AND run_id=? AND sha256=?",
            (company, run_id, digest),
        ).fetchone()
        if row is None:
            raise RunNotFound("discovery_artifact_not_found")
        return row[0], row[1]


def _warn(run: DiscoveryRun, task: Task, message: str) -> None:
    target = next(
        (c.warnings for c in run.candidates if c.lead.purchase_number == task.number), run.warnings
    )
    if message not in target:
        target.append(message)


def _source_result(
    run: DiscoveryRun,
    task: Task,
    result: eis_public.EisPublicSearchResult
    | eis_public.EisPublicDocumentsResult
    | eis_public.EisPublicDetailResult
    | eis_public.EisCustomerProfileResult
    | eis_public.EisCustomerContractsResult,
) -> bool:
    status = result.status
    if status == "COMPLETED":
        return True
    if status == "COOLDOWN":
        run.next_retry_at = result.retry_at or datetime.now(UTC) + timedelta(seconds=60)
        return False
    reason = getattr(result, "reason", None) or status
    if reason == "SOURCE_BUSY":
        run.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)
        return False
    task.attempts += 1
    if status in {"SOURCE_CHANGED", "BLOCKED"} or task.attempts >= 3:
        _warn(run, task, f"{task.kind}: {reason}; данные не получены.")
        run.tasks.pop(0)
        if task.kind == "SEARCH":
            run.search_stop_reason = "SOURCE_ERROR"
    else:
        run.next_retry_at = datetime.now(UTC) + timedelta(seconds=60 * task.attempts)
    return False


def _observer(run: DiscoveryRun, filename: str, url: str) -> Callable[[bytes], None]:
    def save(content: bytes) -> None:
        _artifact(run, content, filename, url)

    return save


def _record_search_page(run: DiscoveryRun, result: eis_public.EisPublicSearchResult) -> None:
    """Count raw rows and stop repeated/incomplete pagination before following links."""
    prior_ids = {number for page in run.search_pages for number in page.purchase_numbers}
    numbers = result.purchase_numbers or ()
    ids = set(numbers)
    complete = (
        result.purchase_numbers is not None
        and result.unidentified_count == 0
        and result.scanned_count == len(numbers)
        and result.source_sha256 is not None
    )
    fingerprint = hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest() if complete else None
    if not complete:
        run.search_stop_reason = "IDENTIFIERS_INCOMPLETE"
        run.warnings.append(
            "Не все карточки имеют проверяемые номера и evidence; уникальный охват UNKNOWN. "
            "Обход остановлен. Можно начать новую сессию по 50 карточек."
        )
    elif ids and any(page.fingerprint == fingerprint for page in run.search_pages):
        run.search_stop_reason = "REPEATED_PAGE"
        run.warnings.append(
            f"Страница {result.page_number} повторяет ранее прочитанный набор номеров. "
            "Обход остановлен; повторные карточки не увеличивают уникальный охват. "
            "Можно начать новую сессию по 50 карточек."
        )
    elif ids and run.search_pages and not ids - prior_ids:
        run.search_stop_reason = "NO_NEW_IDENTIFIERS"
        run.warnings.append(
            f"Страница {result.page_number} не добавила новых номеров закупок; обход остановлен."
        )
    run.search_pages.append(
        SearchPageEvidence(
            page_number=result.page_number,
            page_size=result.page_size,
            search_url=result.search_url,
            observed_at=result.observed_at,
            source_sha256=result.source_sha256,
            scanned_count=result.scanned_count,
            unparsed_count=result.unparsed_count,
            unidentified_count=result.unidentified_count,
            purchase_numbers=numbers,
            fingerprint=fingerprint,
            identifiers_complete=complete,
        )
    )
    run.pages_read += 1
    run.scanned_count += result.scanned_count or 0
    run.unparsed_count += result.unparsed_count
    run.identified_count = len(prior_ids | ids)
    run.duplicate_count = (
        sum(len(page.purchase_numbers) for page in run.search_pages) - run.identified_count
    )
    run.unique_scanned_count = (
        run.identified_count
        if len(run.search_pages) == run.pages_read
        and all(page.identifiers_complete for page in run.search_pages)
        else None
    )


def _step(run: DiscoveryRun) -> None:
    task = run.tasks[0]
    if task.kind == "SEARCH":
        if run.pages_read != len(run.search_pages):
            run.search_stop_reason = "LEGACY_STATE_UNVERIFIED"
            run.unique_scanned_count = None
            run.warnings.append(
                "У прежней сессии нет evidence номеров всех страниц; уникальный охват UNKNOWN. "
                "Начните новую сессию для проверяемого обхода."
            )
            run.tasks = [item for item in run.tasks if item.kind != "SEARCH"]
            return
        url = eis_public.public_search_url(
            run.request.query, task.page, page_size=run.request.search_page_size
        )
        result = eis_public.search_public_eis(
            run.request.query,
            page_number=task.page,
            page_size=run.request.search_page_size,
            raw_observer=_observer(run, f"search-{task.page}.html", url),
        )
        if not _source_result(run, task, result):
            return
        _record_search_page(run, result)
        if result.unparsed_count:
            run.warnings.append(
                f"Страница {task.page}: пропущено карточек без проверяемого "
                f"номера/названия/типа — {result.unparsed_count}."
            )
        if result.query_exceeds_page_limit and task.page == 1:
            run.warnings.append(
                "Счётчик ЕИС превышает текущий лимит программы "
                f"20×{run.request.search_page_size} карточек; "
                "доступность всех результатов и корректность пагинации не подтверждены."
            )
        known = {c.lead.purchase_number for c in run.candidates}
        for lead in result.leads:
            if lead.purchase_number not in known:
                run.candidates.append(Candidate(lead=lead))
                known.add(lead.purchase_number)
        run.tasks.pop(0)
        if run.search_stop_reason is not None:
            run.warnings.append(
                "Полнота охвата ЕИС не подтверждена; анализ найденных кандидатов продолжается."
            )
        elif result.has_more_pages and task.page < run.request.max_pages:
            run.tasks.insert(0, Task(kind="SEARCH", page=task.page + 1))
        else:
            run.search_stop_reason = "PAGE_LIMIT" if result.has_more_pages else "SOURCE_END_HINT"
            if result.has_more_pages:
                run.warnings.append(
                    "Достигнут лимит страниц; источник указывает возможное продолжение, "
                    "но новые результаты не проверены."
                )
            run.warnings.append(
                "Выдача ЕИС меняется во время обхода; полнота охвата не гарантирована."
            )
    elif task.kind == "DETAIL":
        candidate = next(c for c in run.candidates if c.lead.purchase_number == task.number)
        url = candidate.lead.detail_url
        detail = eis_public.read_public_detail(
            url,
            raw_observer=_observer(run, f"{task.number}.html", url),
        )
        if not _source_result(run, task, detail):
            return
        candidate.detail = detail
        run.tasks.pop(0)
    elif task.kind == "DOCUMENTS":
        candidate = next(c for c in run.candidates if c.lead.purchase_number == task.number)
        assert task.url is not None
        documents = eis_public.read_public_documents(
            task.url,
            raw_observer=_observer(run, f"{task.number}-documents.html", task.url),
        )
        if not _source_result(run, task, documents):
            return
        candidate.document_list_read = True
        run.tasks.pop(0)
        supported = [item for item in documents.documents if item.supported]
        for item in documents.documents:
            if not item.supported:
                _warn(run, task, f"Формат не поддержан: {item.filename}")
        selected = supported[: run.request.max_documents]
        for item in reversed(selected):
            run.tasks.insert(
                0, Task(kind="ATTACHMENT", number=task.number, url=item.url, filename=item.filename)
            )
        if len(supported) > len(selected):
            _warn(run, task, "Достигнут лимит документов; комплект загружен не полностью.")
        if not documents.documents:
            _warn(run, task, "На странице не обнаружены документы; полнота неизвестна.")
    elif task.kind == "CUSTOMER_PROFILE":
        candidate = next(c for c in run.candidates if c.lead.purchase_number == task.number)
        customer = candidate.detail.customer if candidate.detail else None
        if customer is None:
            _warn(run, task, "Заказчик не подтверждён ссылкой в карточке ЕИС.")
            run.tasks.pop(0)
            return
        profile = eis_public.read_customer_profile(
            customer.profile_url,
            raw_observer=_observer(run, f"{task.number}-customer.html", customer.profile_url),
        )
        if not _source_result(run, task, profile):
            return
        candidate.customer_profile = profile
        run.tasks.pop(0)
        if profile.inn and profile.contracts_url:
            run.tasks.insert(0, Task(kind="CUSTOMER_CONTRACTS", number=task.number))
        else:
            _warn(run, task, "Ссылка на контракты этого заказчика не подтверждена.")
    elif task.kind == "CUSTOMER_CONTRACTS":
        candidate = next(c for c in run.candidates if c.lead.purchase_number == task.number)
        stored_profile = candidate.customer_profile
        customer = candidate.detail.customer if candidate.detail else None
        if (
            stored_profile is None
            or stored_profile.inn is None
            or stored_profile.contracts_url is None
            or customer is None
        ):
            _warn(run, task, "Связь заказчика с реестром контрактов не подтверждена.")
            run.tasks.pop(0)
            return
        search_url = eis_public.completed_contracts_url(
            stored_profile.contracts_url, stored_profile.inn, run.request.query
        )
        contracts = eis_public.read_completed_contracts(
            stored_profile.contracts_url,
            stored_profile.inn,
            customer.name,
            raw_observer=_observer(run, f"{task.number}-contracts.html", search_url),
            product_query=run.request.query,
        )
        if not _source_result(run, task, contracts):
            return
        candidate.customer_contracts = contracts
        run.tasks.pop(0)
    else:
        assert task.url is not None and task.filename is not None
        candidate = next(c for c in run.candidates if c.lead.purchase_number == task.number)
        try:
            content = eis_public.download_public_attachment(task.url)
        except eis_public.EisPublicError as error:
            if str(error) in {"ROBOTS_CRAWL_DELAY", "SOURCE_BUSY"}:
                run.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)
                return
            raise
        _artifact(run, content, task.filename, task.url)
        used_characters = sum(
            len(block.text)
            for row in run.candidates
            for doc in row.documents
            for block in doc.blocks
        )
        analysis = analyze_document(
            content,
            task.filename,
            task.url,
            max_characters=min(100_000, max(0, 2_000_000 - used_characters)),
        )
        candidate.documents.append(analysis)
        run.tasks.pop(0)
    run.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)


def _schedule_analysis(run: DiscoveryRun) -> None:
    if run.tasks or not any(c.analysis_status == "PENDING" for c in run.candidates):
        return
    # Analyse the first bounded shortlist, then retain all other discovered options
    # visibly. No expensive unseen selection is called a profitability ranking.
    for index, candidate in enumerate(run.candidates):
        if candidate.analysis_status != "PENDING":
            continue
        candidate.analysis_status = "PARTIAL"
        if index >= run.request.max_candidates:
            candidate.warnings.append("Вне лимита автоматического анализа; документы не прочитаны.")
            continue
        number = candidate.lead.purchase_number
        if candidate.detail is None:
            run.tasks.append(Task(kind="DETAIL", number=number))
        if (
            not candidate.document_list_read
            and candidate.lead.documents_url
            and candidate.lead.law == "44-fz"
        ):
            run.tasks.append(
                Task(kind="DOCUMENTS", number=number, url=candidate.lead.documents_url)
            )
        else:
            candidate.warnings.append("Автоматическое чтение страницы документов недоступно.")


def _renew_lease(company: str, run_id: str, lease: str, stop: threading.Event) -> None:
    while not stop.wait(30):
        try:
            with _db() as db:
                changed = db.execute(
                    "UPDATE eis_runs SET lease_until=? WHERE company_id=? AND id=? AND lease=?",
                    (
                        (datetime.now(UTC) + timedelta(minutes=3)).isoformat(),
                        company,
                        run_id,
                        lease,
                    ),
                ).rowcount
                if not changed:
                    return
        except sqlite3.Error:
            # A transient busy store gets another renewal attempt before expiry.
            continue


def advance_run(company: str, actor: str, run_id: str) -> DiscoveryRun:
    """Выполнить максимум один шаг с lease между процессами и аудитом."""
    now = datetime.now(UTC)
    lease = str(uuid.uuid4())
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        run = _load(db, company, run_id)
        if run.state != "RUNNING" or (run.next_retry_at and run.next_retry_at > now):
            return _refresh(run)
        acquired = db.execute(
            "UPDATE eis_runs SET lease=?,lease_until=? WHERE company_id=? AND id=? "
            "AND (lease IS NULL OR lease_until < ?)",
            (lease, (now + timedelta(minutes=3)).isoformat(), company, run_id, now.isoformat()),
        ).rowcount
        if not acquired:
            run.next_retry_at = now + timedelta(seconds=5)
            return _refresh(run)
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_renew_lease, args=(company, run_id, lease, stop), daemon=True
    )
    heartbeat.start()
    try:
        run.next_retry_at = None
        task = run.tasks[0] if run.tasks else None
        if task:
            try:
                _step(run)
            except (ValueError, OSError) as error:
                task.attempts += 1
                # Never leak external response bodies or local paths in errors.
                code = (
                    str(error)
                    if isinstance(error, eis_public.EisPublicError)
                    else type(error).__name__
                )
                if task.attempts >= 3:
                    _warn(run, task, f"{task.kind}: {code}; шаг не завершён.")
                    run.tasks.pop(0)
                run.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)
        _schedule_analysis(run)
        if not run.tasks:
            run.state = "COMPLETED"
            run.completion_status = "PARTIAL" if run.pages_read else "FAILED"
            run.next_retry_at = None
            for candidate in run.candidates:
                candidate.analysis_status = "PARTIAL"
        with _db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = _load(db, company, run_id)
            held = db.execute(
                "SELECT lease FROM eis_runs WHERE company_id=? AND id=?", (company, run_id)
            ).fetchone()[0]
            if held != lease or current.state == "CANCELLED":
                return _refresh(current)
            # Cost edits may happen while a browser step is running.
            costs = {c.lead.purchase_number: c.costs for c in current.candidates}
            for candidate in run.candidates:
                candidate.costs = costs.get(candidate.lead.purchase_number, candidate.costs)
            _save(db, _refresh(run))
            _audit(db, run, actor, "discovery.step", task.model_dump_json() if task else "{}")
            if run.search_stop_reason != current.search_stop_reason:
                _audit(
                    db,
                    run,
                    actor,
                    "discovery.search_stopped",
                    json.dumps(
                        {
                            "reason": run.search_stop_reason,
                            "page": run.search_pages[-1].model_dump(mode="json")
                            if run.search_pages
                            else None,
                            "unique_scanned_count": run.unique_scanned_count,
                        }
                    ),
                )
        return run
    finally:
        stop.set()
        heartbeat.join(timeout=12)
        with _db() as db:
            db.execute(
                "UPDATE eis_runs SET lease=NULL,lease_until=NULL "
                "WHERE company_id=? AND id=? AND lease=?",
                (company, run_id, lease),
            )


def cancel_run(company: str, actor: str, run_id: str) -> DiscoveryRun:
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        run = _load(db, company, run_id)
        run.state = "CANCELLED"
        run.completion_status = "CANCELLED"
        run.next_retry_at = None
        _save(db, run)
        _audit(db, run, actor, "discovery.cancelled", "{}")
    return _refresh(run)


def analyze_candidate(company: str, actor: str, run_id: str, number: str) -> DiscoveryRun:
    """Оператор выбирает для чтения любой найденный вариант, включая вне лимита."""
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        run = _load(db, company, run_id)
        if run.state == "CANCELLED":
            raise RunBusy("discovery_run_cancelled")
        lease = db.execute(
            "SELECT lease_until FROM eis_runs WHERE company_id=? AND id=?", (company, run_id)
        ).fetchone()[0]
        if lease and datetime.fromisoformat(lease) > datetime.now(UTC):
            raise RunBusy("discovery_step_in_progress")
        candidate = next((c for c in run.candidates if c.lead.purchase_number == number), None)
        if candidate is None:
            raise RunNotFound("discovery_candidate_not_found")
        if any(t.number == number for t in run.tasks):
            return _refresh(run)
        if not candidate.detail:
            run.tasks.append(Task(kind="DETAIL", number=number))
        if (
            not candidate.documents
            and candidate.lead.documents_url
            and candidate.lead.law == "44-fz"
        ):
            run.tasks.append(
                Task(kind="DOCUMENTS", number=number, url=candidate.lead.documents_url)
            )
        candidate.warnings = [w for w in candidate.warnings if not w.startswith("Вне лимита")]
        if run.tasks:
            run.state = "RUNNING"
            run.completion_status = "IN_PROGRESS"
        _save(db, run)
        _audit(db, run, actor, "discovery.analyze_candidate", number)
    return _refresh(run)


def request_customer_history(company: str, actor: str, run_id: str, number: str) -> DiscoveryRun:
    """Queue on-demand 44-FZ customer evidence; never infer identity from a name."""
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        run = _load(db, company, run_id)
        if run.state == "CANCELLED":
            raise RunBusy("discovery_run_cancelled")
        lease = db.execute(
            "SELECT lease_until FROM eis_runs WHERE company_id=? AND id=?", (company, run_id)
        ).fetchone()[0]
        if lease and datetime.fromisoformat(lease) > datetime.now(UTC):
            raise RunBusy("discovery_step_in_progress")
        candidate = next((c for c in run.candidates if c.lead.purchase_number == number), None)
        if candidate is None:
            raise RunNotFound("discovery_candidate_not_found")
        if candidate.lead.law != "44-fz":
            raise RunBusy("customer_history_44_only")
        try:
            product_query = eis_public.contract_product_query(run.request.query)
        except eis_public.EisPublicError as error:
            raise RunBusy("customer_history_query_invalid") from error
        if any(
            t.number == number and t.kind in {"CUSTOMER_PROFILE", "CUSTOMER_CONTRACTS"}
            for t in run.tasks
        ):
            return _refresh(run)
        if (
            candidate.detail
            and candidate.detail.customer is None
            and candidate.detail.source_sha256
        ):
            row = db.execute(
                "SELECT content FROM eis_artifacts WHERE company_id=? AND run_id=? AND sha256=?",
                (company, run_id, candidate.detail.source_sha256),
            ).fetchone()
            if row:
                with suppress(eis_public.EisPublicError):
                    candidate.detail = eis_public.parse_public_detail(
                        row[0], candidate.lead.detail_url, datetime.now(UTC)
                    )
        if (candidate.detail is None or candidate.detail.customer is None) and not any(
            t.number == number and t.kind == "DETAIL" for t in run.tasks
        ):
            run.tasks.append(Task(kind="DETAIL", number=number))
        if candidate.customer_profile is None or candidate.customer_profile.contracts_url is None:
            run.tasks.append(Task(kind="CUSTOMER_PROFILE", number=number))
        elif candidate.customer_profile.contracts_url and (
            candidate.customer_contracts is None
            or candidate.customer_contracts.product_query != product_query
            or candidate.customer_contracts.status != "COMPLETED"
        ):
            run.tasks.append(Task(kind="CUSTOMER_CONTRACTS", number=number))
        candidate.customer_history_requested = True
        if run.tasks:
            run.state = "RUNNING"
            run.completion_status = "IN_PROGRESS"
        _save(db, run)
        _audit(db, run, actor, "discovery.customer_history_requested", number)
    return _refresh(run)


def set_costs(
    company: str, actor: str, run_id: str, number: str, costs: DiscoveryCostInput
) -> DiscoveryRun:
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        run = _load(db, company, run_id)
        candidate = next((c for c in run.candidates if c.lead.purchase_number == number), None)
        if candidate is None:
            raise RunNotFound("discovery_candidate_not_found")
        candidate.costs = costs
        _save(db, _refresh(run))
        _audit(
            db,
            run,
            actor,
            "discovery.costs",
            json.dumps(
                {
                    "purchase_number": number,
                    "costs": costs.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
        )
    return run


def public_run(run: DiscoveryRun) -> dict[str, object]:
    """Маленький публичный ответ; полные блоки остаются в scoped store."""
    return run.model_dump(
        mode="json",
        exclude={
            "company_id": True,
            "tasks": True,
            "candidates": {"__all__": {"documents": {"__all__": {"blocks"}}}},
        },
    )
