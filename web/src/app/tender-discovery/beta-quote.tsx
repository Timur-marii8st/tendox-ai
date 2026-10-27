"use client";

import { startTransition, useEffect, useRef, useState } from "react";
import { financialQuoteCurrent, betaCalculationLabel, betaReason, betaRefKey, betaReportMatches, quoteDiscountMode, betaHistoryMatches, historyDecimal, historyFraction, historyScopeLabel, expenseFields, type BetaHistoryReport, type RegionalObservation, type HistorySource, type DiscountMode, type BetaQuoteRef, type BetaQuoteInput, type BetaQuoteReport } from "@/lib/beta-procurement";
import { formatMoneyString, formatTenderDeadline } from "@/lib/tender-workspace";
import { readBetaHistory, readBetaQuote, saveBetaQuote } from "./beta-actions";
import styles from "./workspace.module.css";

type QuoteProps = { notice: BetaQuoteRef["notice"]; lotCount: number; onSaved: () => void; deadline: string | null; blocked: boolean };

export function BetaQuote(props: QuoteProps) {
  return <QuoteSelection key={betaRefKey({ notice: props.notice, lot_index: null })} {...props} />;
}

function QuoteSelection(props: QuoteProps) {
  const [lot, setLot] = useState(1);
  const quoteRef: BetaQuoteRef = { notice: props.notice, lot_index: props.notice.law === "223" ? lot : null };
  return <section className={styles.quoteSection} aria-label="КП и расходы"><h3>КП и расходы</h3>
    {props.notice.law === "223" && <label>Лот <select value={lot} onChange={event => setLot(Number(event.target.value))}>{Array.from({ length: props.lotCount }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select></label>}
    <QuoteForm key={betaRefKey(quoteRef)} quoteRef={quoteRef} onSaved={props.onSaved} deadline={props.deadline} blocked={props.blocked} />
  </section>;
}

function QuoteForm({ quoteRef, onSaved, deadline, blocked }: { quoteRef: BetaQuoteRef; onSaved: () => void; deadline: string | null; blocked: boolean }) {
  // Identity changes remount this component, including unsaved form values and requests.
  const [ref] = useState(quoteRef);
  const alive = useRef(false);
  const [retry, setRetry] = useState(0);
  const [historyRetry, setHistoryRetry] = useState(0);
  const [history, setHistory] = useState<BetaHistoryReport>();
  const [historyError, setHistoryError] = useState<string>();
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [modeOverride, setModeOverride] = useState<DiscountMode>();
  const [clock, setClock] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [report, setReport] = useState<BetaQuoteReport>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [recordId, setRecordId] = useState("");
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    let active = true;
    startTransition(() => {
      void readBetaQuote(ref).then(result => {
        if (!active) return;
        const matched = result.report && betaReportMatches(result.report, ref);
        setNow(Date.now()); setReport(matched ? result.report : undefined);
        setError(result.error ?? (result.report && !matched ? "Ответ не соответствует выбранной закупке." : undefined));
        setLoaded(true); setRecordId(matched ? result.nextRecordId ?? "" : "");
      }).catch(() => {
        if (active) { setError("Связь с сервисом прервалась. Повторите чтение КП."); setLoaded(true); }
      });
    });
    return () => { active = false; };
  }, [ref, retry]);
  useEffect(() => {
    let active = true;
    startTransition(() => {
      void readBetaHistory(ref).then(result => {
        if (!active) return;
        const matched = result.report && betaHistoryMatches(result.report, ref);
        setHistory(matched ? result.report : undefined);
        setHistoryError(result.error ?? (result.report && !matched ? "История не соответствует выбранному лоту." : undefined));
        setHistoryLoaded(true);
      }).catch(() => {
        if (active) { setHistoryError("Связь прервалась. Повторите чтение истории контрактов."); setHistoryLoaded(true); }
      });
    });
    return () => { active = false; };
  }, [ref, historyRetry]);
  const input = report?.input;
  const mode = modeOverride ?? quoteDiscountMode(input);
  const sourceClosed = blocked || (!!deadline && Date.parse(deadline) <= now);
  const calculationBlocked = sourceClosed || report?.calculation?.status === "BLOCKED";
  const quoteExpired = !!input && Date.parse(input.valid_until) <= now;
  const current = !!report && financialQuoteCurrent(report, deadline, sourceClosed, now) &&
    (quoteDiscountMode(input) !== "REGIONAL" || (historyLoaded && history?.history.status === "PASS"));
  useEffect(() => {
    const at = Date.now();
    const next = Math.min(...[report?.input?.valid_until, deadline].flatMap(value => value && Date.parse(value) > at ? [Date.parse(value)] : []));
    if (!Number.isFinite(next)) return;
    const timer = window.setTimeout(() => { setNow(Date.now()); setClock(value => value + 1); }, Math.min(next - at + 1, 60_000));
    return () => window.clearTimeout(timer);
  }, [report, deadline, clock]);
  const field = (name: keyof BetaQuoteInput, label: string, type = "text", defaultValue?: string) => <label style={{ display: "block", margin: "8px 0" }}>{label}<input name={name} type={type} required maxLength={1000} defaultValue={defaultValue ?? (typeof input?.[name] === "string" ? input[name] as string : "")} style={{ display: "block", width: "100%" }} /></label>;
  async function save(form: HTMLFormElement) {
    const data = new FormData(form);
    const text = (name: string) => String(data.get(name) ?? "").trim();
    const quote = Object.fromEntries(["supplier", "document", "locator", "amount_ex_vat", "quote_vat_rate", "availability_terms", "delivery_terms", "payment_terms", "expense_basis", "tax_model", "output_vat_rate", "realistic_discount", "conservative_discount", "conservative_cost_growth"].map(name => [name, text(name)])) as unknown as BetaQuoteInput;
    quote.discount_mode = mode;
    quote.issued_at = text("issued_at"); quote.valid_until = text("valid_until");
    quote.covers_full_scope = data.get("covers_full_scope") === "yes";
    quote.expenses = Object.fromEntries(Object.keys(expenseFields).filter(key => text(key) !== "").map(key => [key, text(key)]));
    setPending(true); setError(undefined);
    try {
      const result = await saveBetaQuote(ref, recordId, quote);
      if (!alive.current) return;
      if (result.report && !betaReportMatches(result.report, ref)) { setError("Ответ не соответствует выбранному лоту."); return; }
      setError(result.error);
      if (result.report) { setNow(Date.now()); setReport(result.report); setRecordId(result.nextRecordId ?? ""); onSaved(); }
    } catch {
      if (alive.current) setError("Связь прервалась. Ввод сохранён в форме. Повторите сохранение с теми же данными.");
    } finally { if (alive.current) setPending(false); }
  }

  return <>
    <HistoryPanel report={history} loaded={historyLoaded} error={historyError} />
    <button type="button" disabled={!historyLoaded || pending} onClick={() => { setHistoryLoaded(false); setHistory(undefined); setHistoryError(undefined); setHistoryRetry(value => value + 1); }}>Обновить историю</button>
    <p>Введите условия действующего КП на весь выбранный лот. Суммы — в рублях без НДС. Источник и условия сохранятся как ваше заявление; соответствие ТЗ проверяется отдельно.</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}{error && !recordId && <button type="button" disabled={pending} onClick={() => { setLoaded(false); setRetry(value => value + 1); }}>Повторить чтение КП</button>}{sourceClosed && <p role="alert">Расчёт заблокирован: срок подачи истёк или есть блокировка источника.</p>}{quoteExpired && <p role="alert">Срок КП истёк. Введите актуальное предложение; прежний расчёт больше не действует.</p>}
    {!loaded ? <p>Читаем сохранённое КП…</p> : <details><summary>{input ? "Изменить КП и расходы" : "Добавить КП и расходы"}</summary>
      <form key={report?.record_id ?? "new"} onSubmit={event => { event.preventDefault(); void save(event.currentTarget); }}><fieldset disabled={pending || calculationBlocked || !recordId} style={{ border: 0 }}>
        {field("supplier", "Поставщик")}{field("document", "Документ КП: имя / номер")}{field("locator", "Страница или раздел документа")}
        {field("amount_ex_vat", "Стоимость всего лота по КП без НДС")}{field("quote_vat_rate", "НДС поставщика, доля (например 0.20 или 0)")}
        {field("issued_at", "Дата выдачи с часовым поясом, например 2026-10-21T10:00:00+03:00")}{field("valid_until", "Действует до, с часовым поясом")}
        <label><input type="checkbox" name="covers_full_scope" value="yes" defaultChecked={input?.covers_full_scope} /> КП покрывает все позиции и весь объём выбранного лота</label>
        {field("availability_terms", "Наличие и срок готовности")}{field("delivery_terms", "Условия доставки и все адреса")}{field("payment_terms", "Условия оплаты")}
        <h4>Прочие расходы без НДС</h4><p>Заполните каждую статью. Явный 0 означает: расход включён в КП либо не требуется. Пустое поле останется UNKNOWN.</p>
        {Object.entries(expenseFields).map(([key, label]) => <label key={key} style={{ display: "block", margin: "6px 0" }}>{label}<input name={key} inputMode="decimal" defaultValue={input?.expenses[key] ?? ""} maxLength={30} style={{ display: "block", width: "100%" }} /></label>)}
        {field("expense_basis", "Основание расходов и нулей: документ / расчёт")}{field("tax_model", "Налоговый режим и основание на дату расчёта")}{field("output_vat_rate", "Выходной НДС, доля")}
        <h4>Допущения сценариев</h4>
        <label style={{ display: "block" }}>Основание снижения цены <select name="discount_mode" value={mode} onChange={event => setModeOverride(event.target.value === "MANUAL" ? "MANUAL" : "REGIONAL")}>
          <option value="REGIONAL">История сопоставимых контрактов региона</option><option value="MANUAL">Ручные допущения</option>
        </select></label>
        <p>{mode === "REGIONAL" ? "Сервер выбирает историю по выбранному лоту. Для сценариев берётся большее из ручного минимума и медианы / p75; консервативное снижение не меньше реалистичного." : "Снижение задаётся вами вручную. История контрактов не применяется к этому расчёту."}</p>
        {mode === "REGIONAL" && history?.history.status !== "PASS" && <p role="status">Региональное снижение: UNKNOWN. КП можно сохранить, но расчёт по истории требует минимум 5 проверенных сопоставимых контрактов. Для своих допущений явно выберите ручной режим.</p>}
        <p>Доли: 0.05 означает 5%. Проверьте допущения для этой сделки.</p>
        {field("realistic_discount", mode === "REGIONAL" ? "Ручной минимум реалистичного снижения" : "Реалистичное снижение цены", "text", input?.realistic_discount ?? "0.05")}{field("conservative_discount", mode === "REGIONAL" ? "Ручной минимум консервативного снижения" : "Консервативное снижение цены", "text", input?.conservative_discount ?? "0.10")}{field("conservative_cost_growth", "Консервативный рост всех расходов", "text", input?.conservative_cost_growth ?? "0.10")}
        <button type="submit" className={styles.secondaryButton}>{pending ? "Сохраняем…" : "Сохранить КП и пересчитать"}</button>
      </fieldset></form>
    </details>}
    {report?.calculation && <div aria-live="polite"><p data-calculation-status={current ? "CALCULATED" : calculationBlocked ? "BLOCKED" : "UNKNOWN"}>Расчёт: {betaCalculationLabel(current ? "CALCULATED" : calculationBlocked ? "BLOCKED" : "UNKNOWN")} · {formatTenderDeadline(report.calculation.checked_at)}</p>
      <p>Основание сохранённого расчёта: {report.calculation.discount_basis === "REGIONAL_HISTORY" ? "региональная история" : quoteDiscountMode(input) === "MANUAL" ? "ручные допущения" : "UNKNOWN"}.
        {report.calculation.regional_discount && <> История проверена: {formatTenderDeadline(report.calculation.regional_discount.checked_at)}.</>}</p>
      {(current ? report.calculation.scenarios : []).map(s => <div key={s.kind}><h4>{({ base: "Базовый", realistic: "Реалистичный", conservative: "Консервативный" })[s.kind]}</h4><p>Выручка без НДС: {formatMoneyString(s.revenue_net)} · Расходы: {formatMoneyString(s.costs_net)} · Прибыль: {formatMoneyString(s.profit)}</p><p>Маржа (доля): {s.margin} · Цена безубыточности с НДС: {formatMoneyString(s.break_even_gross)}</p>{s.assumptions.map(a => <p key={a}>{a}</p>)}</div>)}
      {report.calculation.reasons.map(reason => <p key={reason}>{betaReason(reason)}</p>)}<p>Допуск к участию: UNKNOWN. Расчёт по введённому КП не подтверждает техническое и юридическое соответствие.</p>
    </div>}
  </>;
}

const historyFields: { key: Exclude<keyof RegionalObservation, "purchase_number" | "law" | "concluded_date" | "qualification_reasons" | "price_basis" | "price_scope" | "customer">; label: string }[] = [
  { key: "initial", label: "Объявленная начальная сумма" }, { key: "final", label: "Подписанная сумма" },
  { key: "region", label: "Регион поставки" }, { key: "product_key", label: "Товарная группа" },
  { key: "procedure", label: "Способ закупки" }, { key: "unit", label: "Единица" },
  { key: "quantity", label: "Объём" }, { key: "concluded_at", label: "Дата и время заключения, если указаны" },
  { key: "notice_lot_volume_link", label: "Связь с извещением, лотом и объёмом" },
  { key: "rub_nominal_totals", label: "Сопоставимость полных номинальных рублёвых сумм" },
  { key: "concluded_contract", label: "Подписанный контракт" }, { key: "current_result", label: "Актуальный результат" },
];

function Source({ value }: { value: HistorySource }) {
  return <p style={{ overflowWrap: "anywhere" }}>Источник / XML SHA: <code>{value.document_id}</code> · Локатор: <code>{value.locator}</code></p>;
}

function HistoryPanel({ report, loaded, error }: { report?: BetaHistoryReport; loaded: boolean; error?: string }) {
  const h = report?.history;
  return <section aria-label="Региональная история снижения цены">
    <h4>История контрактов региона</h4>
    <p>Показатель: номинальное снижение объявленной цены до подписанной суммы. Это допущение для сценариев, не вероятность победы и не результат исполнения контракта.</p>
    {!loaded ? <p role="status">Читаем официальные контрактные результаты…</p> : !h ? <p role="status">Региональное снижение: UNKNOWN. {error ?? "Подтверждённая история недоступна."}</p> : <>
      <p>Пригодных независимых закупок: {h.sample_size} · Минимум: {h.required_sample} · {h.status === "PASS" ? "Достаточно для сценарного допущения" : "UNKNOWN — данных недостаточно"}.</p>
      <p>Регион поставки: {h.cohort.region ?? "UNKNOWN"} · Предмет: {h.cohort.product_key ?? "UNKNOWN"} · Способ: {h.cohort.procedure ?? "UNKNOWN"}.</p>
      <p>Объём выбранного лота: {h.cohort.quantity ?? "UNKNOWN"} {h.cohort.unit ?? "единица UNKNOWN"}. Сопоставимый объём — от половины до двойного.</p>
      <p>Период: с {formatTenderDeadline(h.cohort.period_start)} до {formatTenderDeadline(h.cohort.period_end)} (конец не включён). Проверено: {formatTenderDeadline(h.checked_at)}.</p>
      <p>Медиана, доля: {h.status === "PASS" ? historyFraction(h.realistic_discount) : "UNKNOWN"} · p75, доля: {h.status === "PASS" ? historyFraction(h.conservative_discount) : "UNKNOWN"}. Доля 0.05 означает 5%.</p>
      <p>Минимум 5 — продуктовый порог, не статистическая гарантия. p75 не гарантирует консервативность результата.</p>
      {[...h.reasons, ...report.source_reasons].map((reason, index) => <p key={`${index}:${reason}`}>{betaReason(reason)}</p>)}
      <details><summary>Наблюдения, исключения и источники ({h.evaluated.length})</summary>
        <Source value={h.cohort.source} />
        {h.evaluated.map((entry, index) => <details key={`${entry.observation.law}:${entry.observation.purchase_number}:${index}`}>
          <summary>{entry.observation.law}-ФЗ · {entry.observation.purchase_number} · {entry.status === "PASS" ? "В выборке" : "Исключено — UNKNOWN"}</summary>
          <p>Снижение, доля: {entry.status === "PASS" ? historyFraction(entry.discount) : "UNKNOWN"}</p>
          <p>База сравнения: {historyScopeLabel(entry.observation)}.</p>
          {entry.observation.price_scope === "WHOLE_CUSTOMER_CONTRACT" && <p>Начальная и подписанная суммы относятся ко всему контракту одного заказчика. Общая НМЦК совместной закупки в это сравнение не входит.</p>}
          {entry.observation.customer ? <div><p>Заказчик — регистрационный номер в ЕИС: {entry.observation.customer.value ?? "не подтверждён"}.</p>
            <Source value={entry.observation.customer.source} />{entry.observation.customer.supporting_sources.map((source, n) => <Source key={n} value={source} />)}</div>
            : entry.observation.price_scope === "WHOLE_CUSTOMER_CONTRACT" && <p>Заказчик в ЕИС не подтверждён.</p>}
          {[...new Set([...entry.reasons, ...entry.observation.qualification_reasons])].map(reason => <p key={reason}>{betaReason(reason)}</p>)}
          {entry.observation.concluded_date && <div><p>Календарная дата подписания: {entry.observation.concluded_date.value ?? "UNKNOWN"}. Время и часовой пояс не указаны.</p>
            <Source value={entry.observation.concluded_date.source} />{entry.observation.concluded_date.supporting_sources.map((source, n) => <Source key={n} value={source} />)}</div>}
          {historyFields.map(({ key, label }) => {
            const fact = entry.observation[key];
            const value = fact.value === null ? "UNKNOWN" : typeof fact.value === "boolean" ? (fact.value ? "Подтверждено" : "Не подтверждено")
              : key === "initial" || key === "final" ? formatMoneyString(historyDecimal(fact.value) ? fact.value : null)
              : key === "concluded_at" ? formatTenderDeadline(fact.value) : fact.value;
            const scopeLabel = entry.observation.price_scope === "WHOLE_CUSTOMER_CONTRACT"
              ? key === "initial" ? "Начальная сумма полного контракта заказчика" : key === "final" ? "Подписанная сумма полного контракта заказчика" : label
              : label;
            return <div key={key}><p>{scopeLabel}: {value}</p><Source value={fact.source} />{fact.supporting_sources.map((source, n) => <Source key={n} value={source} />)}</div>;
          })}
        </details>)}
      </details>
    </>}
    <p>Полнота охвата источника: UNKNOWN. Отсутствие записи не доказывает отсутствие контракта.</p>
  </section>;
}
