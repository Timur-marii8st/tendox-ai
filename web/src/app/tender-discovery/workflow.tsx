"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import type {
  DiscoveryCandidate, DiscoveryCostInput, DiscoveryRun, DiscoveryRunSummary,
} from "@/lib/eis-workflow-api";
import {
  advanceDiscovery, analyzeCandidate, cancelDiscovery, loadDiscoveryRun, loadDiscoveryRuns,
  requestCustomerHistory, saveDiscoveryCosts, startDiscoveryRun,
} from "./actions";

const STORAGE_KEY = "syurai:eis-discovery-run";
const rubles = (value: string | null) => {
  if (value === null) return "не подтверждена";
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (!match) return `${value} ₽`;
  const whole = match[2].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const fraction = (match[3] ?? "").padEnd(2, "0");
  return `${match[1]}${whole},${fraction} ₽`;
};
const percent = (value: string) => `${(Number(value) * 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%`;
const date = (value: string) => new Date(value).toLocaleString("ru-RU");
const dateOnly = (value: string) => value.split("-").reverse().join(".");
const scenarioName = { base: "Базовый", realistic: "Реалистичный", conservative: "Консервативный" };

function statusLabel(status: string) {
  return ({ RUNNING: "идёт", COMPLETED: "обработка остановлена", CANCELLED: "отменён", IN_PROGRESS: "в работе", FAILED: "источник не прочитан", UNKNOWN: "неизвестно", FAIL: "не пройдено", PASS: "прочитано", PARTIAL: "частично", COMPLETE: "обработка закончена, полнота не подтверждена", PENDING: "ожидает" } as Record<string, string>)[status] ?? status;
}

const searchStopLabel: Record<NonNullable<DiscoveryRun["search_stop_reason"]>, string> = {
  REPEATED_PAGE: "ЕИС повторила уже прочитанную страницу",
  NO_NEW_IDENTIFIERS: "Страница не добавила новых закупок",
  IDENTIFIERS_INCOMPLETE: "Не все номера карточек удалось проверить",
  LEGACY_STATE_UNVERIFIED: "У прежней сессии нет данных для проверки уникальности",
  PAGE_LIMIT: "Достигнут выбранный лимит страниц",
  SOURCE_END_HINT: "На прочитанной странице нет признака продолжения",
  SOURCE_ERROR: "Источник не удалось прочитать",
};

function completionNotice(run: DiscoveryRun) {
  if (run.completion_status === "FAILED") {
    return { className: "bg-red-50 text-red-900", title: "Источник не прочитан", text: "Рабочий процесс завершился без подтверждённого чтения источника. Не используйте пустой результат как доказательство отсутствия закупок." };
  }
  if (run.completion_status === "PARTIAL") {
    return { className: "bg-amber-50 text-amber-950", title: "Частичный результат", text: "Рабочий процесс закончен, но охват источника, документов или извлечённых требований неполон. Пропуски остаются UNKNOWN." };
  }
  if (run.completion_status === "CANCELLED") {
    return { className: "bg-slate-100 text-slate-800", title: "Сессия отменена", text: "Показаны только данные, полученные до отмены." };
  }
  return { className: "bg-blue-50 text-blue-900", title: "Сессия выполняется", text: "Следующий ограниченный шаг выполняется автоматически, пока страница открыта." };
}

function CostForm({ runId, candidate, onSaved }: {
  runId: string; candidate: DiscoveryCandidate; onSaved: (run: DiscoveryRun) => void;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string>();
  const submit = (form: FormData) => {
    const input: DiscoveryCostInput = {
      goods: String(form.get("goods") ?? ""), expenses: String(form.get("expenses") ?? ""),
      vat_rate: String(form.get("vat_rate") ?? ""),
      realistic_discount: String(form.get("realistic_discount") ?? ""),
      conservative_discount: String(form.get("conservative_discount") ?? ""),
      conservative_cost_growth: String(form.get("conservative_cost_growth") ?? ""),
      basis: String(form.get("basis") ?? ""), costs_complete_ack: form.get("costs_complete_ack") === "on",
    };
    startTransition(async () => {
      const response = await saveDiscoveryCosts(runId, candidate.lead.purchase_number, input);
      if (response.result) { setError(undefined); onSaved(response.result); }
      else setError(response.error);
    });
  };
  const inputClass = "rounded-lg border border-slate-300 px-3 py-2 font-normal";
  return <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
    <summary className="cursor-pointer font-bold">Рассчитать предварительную экономику</summary>
    <p className="mt-2 text-xs text-slate-600">Укажите известные расходы без НДС. Если их полнота не подтверждена, не отмечайте подтверждение: результат останется UNKNOWN. Расчёт не является решением об участии.</p>
    <form action={submit} className="mt-3 grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm font-bold">Товар на весь лот, без НДС
        <input className={inputClass} name="goods" inputMode="decimal" placeholder="850000.00" defaultValue={candidate.costs?.goods} required disabled={pending} />
      </label>
      <label className="grid gap-1 text-sm font-bold">Все прочие расходы, без выходного НДС
        <input className={inputClass} name="expenses" inputMode="decimal" placeholder="120000.00" defaultValue={candidate.costs?.expenses} required disabled={pending} />
        <span className="font-normal text-slate-600">Включите невозмещаемый входной НДС, если он применим к вашим затратам.</span>
      </label>
      <label className="grid gap-1 text-sm font-bold">Ставка НДС, доля
        <input className={inputClass} name="vat_rate" placeholder="например, 0 или 0.20; укажите свою ставку" defaultValue={candidate.costs?.vat_rate} required disabled={pending} />
      </label>
      <label className="grid gap-1 text-sm font-bold">Сценарное допущение: реалистичное снижение цены
        <input className={inputClass} name="realistic_discount" defaultValue={candidate.costs?.realistic_discount ?? "0.05"} required disabled={pending} />
      </label>
      <label className="grid gap-1 text-sm font-bold">Сценарное допущение: консервативное снижение цены
        <input className={inputClass} name="conservative_discount" defaultValue={candidate.costs?.conservative_discount ?? "0.10"} required disabled={pending} />
      </label>
      <label className="grid gap-1 text-sm font-bold">Сценарное допущение: рост затрат
        <input className={inputClass} name="conservative_cost_growth" defaultValue={candidate.costs?.conservative_cost_growth ?? "0.10"} required disabled={pending} />
      </label>
      <label className="grid gap-1 text-sm font-bold sm:col-span-2">Основание стоимости
        <textarea className={inputClass} name="basis" required placeholder="Поставщик, КП или прайс и дата" defaultValue={candidate.costs?.basis} disabled={pending} />
      </label>
      <label className="flex items-start gap-2 text-sm sm:col-span-2">
        <input type="checkbox" name="costs_complete_ack" className="mt-1" defaultChecked={candidate.costs?.costs_complete_ack} disabled={pending} />
        Подтверждаю, что в предварительный итог включены все известные расходы. Без подтверждения результат останется UNKNOWN.
      </label>
      <button disabled={pending} className="w-fit rounded-lg bg-slate-900 px-4 py-2 font-bold text-white disabled:opacity-50">{pending ? "Считаю…" : "Сохранить и рассчитать"}</button>
    </form>
    {error && <p role="alert" className="mt-2 text-sm font-bold text-red-800">{error}</p>}
  </details>;
}

function Evidence({ runId, candidate }: { runId: string; candidate: DiscoveryCandidate }) {
  return <details className="mt-4 rounded-xl border border-slate-200 p-4">
    <summary className="cursor-pointer font-bold">Документы и evidence ({candidate.documents.length})</summary>
    <p className="mt-2 text-sm text-amber-900">Извлечённые требования — кандидаты для проверки, а не утверждённые факты. Пропуски и неоднозначность остаются UNKNOWN.</p>
    {candidate.detail && <div className="mt-3 grid gap-2 text-sm">
      {candidate.detail.fields.map((field) => <details key={`${field.name}-${field.source_locator}`} className="rounded border border-slate-200 p-2">
        <summary>{field.label}: <strong>{field.value}</strong></summary>
        <p className="mt-1 text-slate-600">{field.evidence_snippet}</p><p className="text-xs text-slate-500">Локатор: {field.source_locator}</p>
      </details>)}
    </div>}
    <div className="mt-3 grid gap-3">
      {candidate.documents.map((document) => <article key={`${document.url}-${document.sha256}`} className="rounded-lg border border-slate-200 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2"><a href={`/tender-discovery/artifacts/${encodeURIComponent(runId)}/${document.sha256}`} className="font-bold text-blue-700 underline">Скачать оригинал: {document.filename}</a><span>{statusLabel(document.status)}</span></div>
        <p className="mt-1 text-xs font-bold text-amber-900">Роль документа: UNKNOWN — оператор ещё не проверил назначение файла.</p>
        <p className="mt-1 text-slate-600">Блоков: {document.blocks_total}; без сопоставления: {document.unmapped_count}; размер: {document.byte_count.toLocaleString("ru-RU")} байт.</p>
        {document.reasons.length > 0 && <p className="mt-1 text-amber-900">{document.reasons.join(" · ")}</p>}
        {document.members.length > 0 && <p className="mt-1 text-slate-600">Файлы архива: {document.members.join(", ")}</p>}
        {document.requirement_candidates.length > 0 && <details className="mt-2"><summary className="cursor-pointer font-bold">Кандидаты требований ({document.requirement_candidates.length})</summary>
          <ul className="mt-2 grid gap-2">{document.requirement_candidates.map((item, index) => <li key={`${item.provenance.locator}-${index}`} className="rounded bg-slate-50 p-2">
            <strong>{item.raw_text}</strong><br /><span className="text-xs text-slate-500">{item.property} {item.operator} {item.value} {item.unit} · {item.provenance.locator}</span>
          </li>)}</ul></details>}
        {document.snippets.length > 0 && <details className="mt-2"><summary className="cursor-pointer font-bold">Фрагменты ({document.snippets.length})</summary>
          {document.snippets.map((item, index) => <blockquote key={`${item.provenance.locator}-${index}`} className="mt-2 border-l-2 border-slate-300 pl-3 text-slate-700">{item.text}<footer className="text-xs text-slate-500">{item.kind} · {item.provenance.locator}</footer></blockquote>)}</details>}
      </article>)}
    </div>
  </details>;
}

function CustomerHistory({ candidate }: { candidate: DiscoveryCandidate }) {
  const customer = candidate.detail?.customer;
  const profile = candidate.customer_profile;
  const contracts = candidate.customer_contracts;
  if (!candidate.customer_history_requested && !customer) return null;
  const orderedContracts = contracts ? [
    ...contracts.contracts.filter((item) => item.relevance_status === "MATCHED_VISIBLE"),
    ...contracts.contracts.filter((item) => item.relevance_status === "UNKNOWN"),
  ] : [];
  const matchedCount = contracts?.contracts.filter((item) => item.relevance_status === "MATCHED_VISIBLE").length ?? 0;
  return <section className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
    <h4 className="font-bold">История заказчика по 44‑ФЗ</h4>
    <p className="mt-1 text-slate-600">Это ограниченная выборка для изучения заказчика. Она не подтверждает оплату, сроки приёмки, обычную скидку на торгах или выгодность текущей закупки.</p>
    {customer ? <p className="mt-2">Организация: <a href={customer.profile_url} target="_blank" rel="noreferrer" className="font-bold text-blue-700 underline">{customer.name}</a> · код {customer.organization_code} · источник: {customer.source_locator}, SHA‑256 {customer.source_sha256.slice(0, 12)}…</p> : <p className="mt-2 text-amber-900">Связь закупки с карточкой заказчика: UNKNOWN.</p>}
    {profile && <p className="mt-2">ИНН: {profile.inn ?? "UNKNOWN"} · источник: {profile.inn_locator ?? "UNKNOWN"}, SHA‑256 {profile.source_sha256?.slice(0, 12) ?? "UNKNOWN"}…</p>}
    {contracts && <>
      <p className="mt-2 font-bold">Завершённые контракты {contracts.product_query ? `по запросу «${contracts.product_query}»` : "без фильтра по товару"}: {contracts.contracts.length} из первой страницы выдачи ({contracts.scanned_count} карточек, пропущено {contracts.skipped_count}). <a href={contracts.search_url} target="_blank" rel="noreferrer" className="text-blue-700 underline">Открыть выдачу ЕИС</a></p>
      {contracts.status !== "COMPLETED" && <p className="mt-1 text-amber-900">Чтение выдачи не подтверждено: {contracts.reason ?? contracts.status}. Ноль карточек здесь не означает отсутствие контрактов.</p>}
      {contracts.reason === "NO_RESULTS_FIRST_PAGE" && <p className="mt-1">ЕИС не показала результатов по этому запросу. Проверена только первая страница с заданными фильтрами.</p>}
      {contracts.product_query && contracts.status === "COMPLETED" && contracts.contracts.length > 0 && <p className="mt-1">Видимый предмет совпал в {matchedCount} карточках. Остальные остаются UNKNOWN: слово могло находиться в другой позиции лота или поле выдачи.</p>}
      <p className="text-amber-900">Охват: только первая страница; другие контракты и история изменений не проверены.</p>
      <ul className="mt-2 grid gap-2">{orderedContracts.map((item) => <li key={item.registry_number} className="rounded-lg border border-slate-200 bg-white p-3">
        <a href={item.contract_url} target="_blank" rel="noreferrer" className="font-bold text-blue-700 underline">Контракт № {item.registry_number}</a>
        <p>{item.subject ?? "Предмет: UNKNOWN"}</p>
        {contracts.product_query && <p className={item.relevance_status === "MATCHED_VISIBLE" ? "text-emerald-800" : "text-amber-900"}>{item.relevance_status === "MATCHED_VISIBLE" ? `Совпали слова в видимом предмете: ${item.matched_terms.join(", ")}.` : "Совпадение видимого предмета: UNKNOWN."}</p>}
        <p>Цена контракта: {rubles(item.price_rub)} · заключён: {item.signed_on ? dateOnly(item.signed_on) : "UNKNOWN"}</p>
        {item.notice_url && <p><a href={item.notice_url} target="_blank" rel="noreferrer" className="text-blue-700 underline">Связанное извещение ЕИС № {item.notice_number}</a> <span className="text-xs text-slate-500">· {item.notice_locator}</span></p>}
        <p className="text-xs text-slate-500">Источник: {item.source_locator}, SHA‑256 {item.source_sha256.slice(0, 12)}…</p>
      </li>)}</ul>
    </>}
  </section>;
}

function Comparison({ run }: { run: DiscoveryRun }) {
  if (!run.candidates.some((candidate) => candidate.estimate)) return null;
  return <section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <h2 className="text-xl font-black">Сравнение предварительной экономики</h2>
    <table className="mt-3 w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b"><th className="p-2">Закупка</th><th className="p-2">Сценарий</th><th className="p-2">Выручка без НДС</th><th className="p-2">Затраты</th><th className="p-2">Прибыль</th><th className="p-2">Маржа</th><th className="p-2">Безубыточность с НДС</th></tr></thead>
      <tbody>{run.candidates.flatMap((candidate) => (candidate.estimate?.scenarios ?? []).map((scenario) => <tr className="border-b last:border-0" key={`${candidate.lead.purchase_number}-${scenario.kind}`}><td className="p-2 font-bold">№ {candidate.lead.purchase_number}</td><td className="p-2">{scenarioName[scenario.kind]}</td><td className="p-2">{rubles(scenario.revenue_net)}</td><td className="p-2">{rubles(scenario.costs_net)}</td><td className="p-2">{rubles(scenario.profit)}</td><td className="p-2">{percent(scenario.margin)}</td><td className="p-2">{rubles(scenario.break_even_gross)}<br /><span className="text-xs text-slate-500">макс. снижение {percent(scenario.maximum_discount)}</span></td></tr>))}</tbody>
    </table>
    <p className="mt-3 text-xs text-slate-600">Серверный предварительный порядок: незаблокированные оценки по убыванию консервативной прибыли, затем UNKNOWN, а FAIL и blocked — в конце. Это не прогноз поведения конкурентов или исхода торгов. Оценка не создаёт рекомендацию PARTICIPATE и не заменяет полное КП, hard gates и проверку комплекта документов.</p>
  </section>;
}

export function TenderDiscoveryWorkflow() {
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [history, setHistory] = useState<DiscoveryRunSummary[]>([]);
  const [error, setError] = useState<string>();
  const [busy, startTransition] = useTransition();
  const requestGeneration = useRef(0);
  const currentRunId = useRef<string | null>(null);

  const remember = useCallback((value: DiscoveryRun) => {
    currentRunId.current = value.id;
    setRun(value); localStorage.setItem(STORAGE_KEY, value.id);
  }, []);

  useEffect(() => {
    let active = true;
    const generation = requestGeneration.current;
    void loadDiscoveryRuns().then((response) => { if (active && response.result) setHistory(response.result); });
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) void loadDiscoveryRun(saved).then((response) => {
      if (!active || generation !== requestGeneration.current) return;
      if (response.result) { currentRunId.current = response.result.id; setRun(response.result); }
      else if (response.notFound) localStorage.removeItem(STORAGE_KEY);
      if (response.error && !response.notFound) setError(response.error);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!run || run.state !== "RUNNING") return;
    let active = true;
    const generation = requestGeneration.current;
    const retryAt = run.next_retry_at ? new Date(run.next_retry_at).getTime() : Date.now();
    const delay = Math.max(500, retryAt - Date.now());
    const timer = window.setTimeout(() => {
      void advanceDiscovery(run.id).then((response) => {
        if (!active || generation !== requestGeneration.current || currentRunId.current !== run.id) return;
        if (response.result) remember(response.result);
        else { setError(response.error); if (response.notFound) { localStorage.removeItem(STORAGE_KEY); setRun(null); } }
      });
    }, delay);
    return () => { active = false; window.clearTimeout(timer); };
  }, [remember, run]);

  const start = (form: FormData) => startTransition(async () => {
    const generation = ++requestGeneration.current;
    currentRunId.current = null;
    setError(undefined);
    const response = await startDiscoveryRun({
      query: String(form.get("query") ?? ""), max_pages: Number(form.get("max_pages")),
      max_candidates: Number(form.get("max_candidates")), max_documents: Number(form.get("max_documents")),
      search_page_size: Number(form.get("search_page_size")),
    });
    if (generation !== requestGeneration.current) return;
    if (response.result) remember(response.result); else setError(response.error);
  });
  const cancel = () => run && startTransition(async () => {
    const runId = run.id;
    const generation = ++requestGeneration.current;
    const response = await cancelDiscovery(runId);
    if (generation !== requestGeneration.current || currentRunId.current !== runId) return;
    if (response.result) remember(response.result);
    else { setError(response.error); setRun((current) => current ? { ...current } : current); }
  });
  const openHistory = (id: string) => startTransition(async () => {
    const generation = ++requestGeneration.current;
    currentRunId.current = id;
    const response = await loadDiscoveryRun(id);
    if (generation !== requestGeneration.current || currentRunId.current !== id) return;
    if (response.result) { setError(undefined); remember(response.result); }
    else setError(response.error);
  });
  const analyze = (purchaseNumber: string) => run && startTransition(async () => {
    const runId = run.id;
    const generation = ++requestGeneration.current;
    const response = await analyzeCandidate(runId, purchaseNumber);
    if (generation !== requestGeneration.current || currentRunId.current !== runId) return;
    if (response.result) { setError(undefined); remember(response.result); }
    else { setError(response.error); setRun((current) => current ? { ...current } : current); }
  });
  const customerHistory = (purchaseNumber: string) => run && startTransition(async () => {
    const runId = run.id;
    const generation = ++requestGeneration.current;
    const response = await requestCustomerHistory(runId, purchaseNumber);
    if (generation !== requestGeneration.current || currentRunId.current !== runId) return;
    if (response.result) { setError(undefined); remember(response.result); }
    else { setError(response.error); setRun((current) => current ? { ...current } : current); }
  });

  return <div className="mt-7 grid gap-5">
    <form action={start} className="grid gap-4 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
      <div><h2 className="text-xl font-black">Подключённый поиск и разбор ЕИС</h2><p className="mt-1 text-sm text-slate-600">Сессия читает ЕИС по одному ограниченному шагу. Автопродолжение работает, пока эта страница открыта; после закрытия возобновится при следующем открытии.</p></div>
      <label className="grid gap-1 text-sm font-bold">Что вы поставляете
        <input name="query" required maxLength={120} placeholder="Серверное оборудование" className="rounded-lg border border-slate-300 p-2 font-normal" disabled={busy} />
      </label>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="grid gap-1 text-sm font-bold">Страниц ЕИС<input name="max_pages" type="number" min="1" max="20" defaultValue="3" className="rounded-lg border p-2 font-normal" /></label>
        <label className="grid gap-1 text-sm font-bold">Кандидатов<input name="max_candidates" type="number" min="1" max="10" defaultValue="3" className="rounded-lg border p-2 font-normal" /></label>
        <label className="grid gap-1 text-sm font-bold">Документов на кандидата<input name="max_documents" type="number" min="1" max="12" defaultValue="6" className="rounded-lg border p-2 font-normal" /></label>
      </div>
      <label className="grid gap-1 text-sm font-bold">Карточек на странице
        <select name="search_page_size" defaultValue="100" className="w-fit rounded-lg border p-2 font-normal"><option value="100">100</option><option value="50">50 — резервный режим</option></select>
        <span className="text-xs font-normal text-slate-600">При повторе страниц обход остановится. Для повторной попытки можно начать новую сессию по 50 карточек.</span>
      </label>
      <button disabled={busy} className="w-fit rounded-lg bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50">{busy ? "Подключаю…" : "Начать новую сессию"}</button>
    </form>
    {history.length > 0 && <details className="rounded-xl border border-slate-200 bg-white p-4"><summary className="cursor-pointer font-bold">Предыдущие сессии ({history.length})</summary><div className="mt-3 flex flex-wrap gap-2">{history.map((item) => <button key={item.id} onClick={() => openHistory(item.id)} disabled={busy} className="rounded-lg border border-slate-300 px-3 py-2 text-left text-sm"><strong>{item.query}</strong><br />{statusLabel(item.state)} · {date(item.created_at)}</button>)}</div></details>}
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 font-bold text-red-800">{error}</p>}
    {run && <>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-live="polite">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-black">{run.request.query}</h2><p className="text-sm text-slate-600">Процесс: {statusLabel(run.state)} · результат: {statusLabel(run.completion_status)} · страниц {run.pages_read}/{run.request.max_pages} · ожидает шагов {run.pending_count}</p></div>{run.state === "RUNNING" && <button onClick={cancel} disabled={busy} className="rounded-lg border border-red-300 px-3 py-2 text-sm font-bold text-red-800">Отменить</button>}</div>
        <p className="mt-3 text-sm">Прочитано строк: {run.scanned_count} · уникальных закупок: {run.unique_scanned_count ?? "не подтверждено"} · известных номеров: {run.identified_count} · подтверждённых повторов: {run.duplicate_count} · не разобрано карточек: {run.unparsed_count}</p>
        {run.search_stop_reason && <p className="mt-2 text-sm font-bold text-amber-900">Обход остановлен: {searchStopLabel[run.search_stop_reason]}. Полнота ЕИС не подтверждена.</p>}
        {run.search_pages.length > 0 && <details className="mt-3 text-sm"><summary className="cursor-pointer font-bold">Прочитанные страницы и источники ({run.search_pages.length})</summary><ul className="mt-2 grid gap-2">{run.search_pages.map((page) => <li key={page.page_number} className="rounded-lg bg-slate-50 p-2"><a href={page.search_url} target="_blank" rel="noreferrer" className="font-bold text-blue-700 underline">Страница {page.page_number}</a> · {date(page.observed_at)} · строк {page.scanned_count ?? "неизвестно"} · номера {page.identifiers_complete ? "проверены" : "неполные"}<span className="mt-1 block break-all text-xs text-slate-500">SHA-256: {page.source_sha256 ?? "не получен"}</span></li>)}</ul></details>}
        {(() => { const notice = completionNotice(run); return <div className={`mt-3 rounded-lg p-3 text-sm ${notice.className}`}><strong>{notice.title}</strong><p>{notice.text}</p></div>; })()}
        {run.state === "RUNNING" && <p className="mt-3 rounded-lg bg-blue-50 p-3 text-sm">Автоматический шаг {run.next_retry_at ? `после ${date(run.next_retry_at)}` : "готовится"}. Можно закрыть страницу: сессия сохранена, но чтение приостановится до возвращения.</p>}
        {run.warnings.length > 0 && <ul className="mt-3 list-disc pl-5 text-sm text-amber-900">{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
      </section>
      <Comparison run={run} />
      <section className="grid gap-4" aria-label="Кандидаты закупок">{run.candidates.map((candidate, index) => <article key={candidate.lead.purchase_number} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Предварительный порядок #{index + 1}</p><h3 className="mt-1 text-xl font-black">{candidate.lead.subject}</h3><p className="mt-1 text-sm">№ {candidate.lead.purchase_number} · {candidate.lead.method}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-bold">анализ {statusLabel(candidate.analysis_status)}</span></div>
        <div className="mt-3 grid gap-1 text-sm sm:grid-cols-2"><p>Заказчик: {candidate.lead.customer ?? "UNKNOWN"}</p><p>НМЦК: {rubles(candidate.lead.nmck_rub)}</p><p>Точный срок: {candidate.detail?.exact_deadline ? date(candidate.detail.exact_deadline) : "UNKNOWN"}</p><p>Подача: <strong>{statusLabel(candidate.application_status)}</strong></p></div>
        <p className="mt-3 text-sm">Совпавшие слова: {candidate.lead.matched_terms.join(", ") || "нет подтверждённых"}. Порядок предварительный и не является рейтингом прибыли.</p>
        <div className="mt-3 flex flex-wrap gap-4 text-sm font-bold text-blue-700"><a href={candidate.lead.detail_url} target="_blank" rel="noreferrer" className="underline">Официальная карточка ЕИС</a>{candidate.lead.documents_url && <a href={candidate.lead.documents_url} target="_blank" rel="noreferrer" className="underline">Документы на ЕИС</a>}</div>
        {!candidate.detail && candidate.documents.length === 0 && <button type="button" onClick={() => analyze(candidate.lead.purchase_number)} disabled={busy} className="mt-3 rounded-lg bg-blue-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">{busy ? "Ставлю в очередь…" : "Прочитать карточку и документы"}</button>}
        {candidate.lead.law === "44-fz" && run.state !== "CANCELLED" && (!candidate.customer_contracts?.product_query || candidate.customer_contracts.status !== "COMPLETED") && <button type="button" onClick={() => customerHistory(candidate.lead.purchase_number)} disabled={busy || (run.state === "RUNNING" && candidate.customer_history_requested)} className="mt-3 ml-2 rounded-lg border border-blue-700 px-4 py-2 text-sm font-bold text-blue-800 disabled:opacity-50">{candidate.customer_history_requested && run.state === "RUNNING" ? "Ищу контракты по товару…" : candidate.customer_contracts?.status !== "COMPLETED" && candidate.customer_contracts?.product_query ? "Повторить поиск контрактов" : "Найти контракты заказчика по товару"}</button>}
        <CustomerHistory candidate={candidate} />
        {candidate.warnings.length > 0 && <p className="mt-3 text-sm text-amber-900">{candidate.warnings.join(" · ")}</p>}
        {candidate.estimate && <div className="mt-4 rounded-xl bg-emerald-50 p-4 text-sm"><strong>Статус расчёта: {candidate.estimate.status}</strong><p>Вывод: {candidate.estimate.recommendation === "do_not_participate" ? "не участвовать" : "нужен дальнейший анализ"}</p>{candidate.estimate.reasons.map((reason) => <p key={reason}>{reason}</p>)}</div>}
        <CostForm runId={run.id} candidate={candidate} onSaved={remember} />
        <Evidence runId={run.id} candidate={candidate} />
      </article>)}</section>
    </>}
  </div>;
}
