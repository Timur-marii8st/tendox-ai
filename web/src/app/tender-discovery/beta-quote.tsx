"use client";

import { useEffect, useState } from "react";
import { financialQuoteCurrent, betaCalculationLabel, betaReason, expenseFields, type BetaQuoteRef, type BetaQuoteInput, type BetaQuoteReport } from "@/lib/beta-procurement";
import { formatMoneyString, formatTenderDeadline } from "@/lib/tender-workspace";
import { readBetaQuote, saveBetaQuote } from "./beta-actions";
import styles from "./workspace.module.css";

export function BetaQuote({ notice, lotCount, onSaved, deadline, blocked }: { notice: BetaQuoteRef["notice"]; lotCount: number; onSaved: () => void; deadline: string | null; blocked: boolean }) {
  const [retry, setRetry] = useState(0);
  const [clock, setClock] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [lot, setLot] = useState(1);
  const ref: BetaQuoteRef = { notice, lot_index: notice.law === "223" ? lot : null };
  const [report, setReport] = useState<BetaQuoteReport>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [recordId, setRecordId] = useState("");
  useEffect(() => {
    let active = true;
    const requestNotice = { law: notice.law, purchase_number: notice.purchase_number, version_number: notice.version_number, notice_xml_sha256: notice.notice_xml_sha256 };
    void readBetaQuote({ notice: requestNotice, lot_index: notice.law === "223" ? lot : null }).then(result => {
      if (active) { setNow(Date.now()); setReport(result.report); setError(result.error); setLoaded(true); setRecordId(result.nextRecordId ?? ""); }
    }).catch(() => {
      if (active) { setError("Связь с сервисом прервалась. Повторите чтение КП."); setLoaded(true); }
    });
    return () => { active = false; };
  }, [notice.law, notice.purchase_number, notice.version_number, notice.notice_xml_sha256, lot, retry]); // stable source identity
  const input = report?.input;
  const sourceClosed = blocked || (!!deadline && Date.parse(deadline) <= now);
  const calculationBlocked = sourceClosed || report?.calculation?.status === "BLOCKED";
  const quoteExpired = !!input && Date.parse(input.valid_until) <= now;
  const current = !!report && financialQuoteCurrent(report, deadline, sourceClosed, now);
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
    quote.issued_at = text("issued_at"); quote.valid_until = text("valid_until");
    quote.covers_full_scope = data.get("covers_full_scope") === "yes";
    quote.expenses = Object.fromEntries(Object.keys(expenseFields).filter(key => text(key) !== "").map(key => [key, text(key)]));
    setPending(true); setError(undefined);
    try {
      const result = await saveBetaQuote(ref, recordId, quote);
      setError(result.error);
      if (result.report) { setNow(Date.now()); setReport(result.report); setRecordId(result.nextRecordId ?? ""); onSaved(); }
    } catch {
      setError("Связь прервалась. Ввод сохранён в форме. Повторите сохранение с теми же данными.");
    } finally { setPending(false); }
  }

  return <section className={styles.quoteSection} aria-label="КП и расходы"><h3>КП и расходы</h3>
    <p>Введите условия действующего КП на весь выбранный лот. Суммы — в рублях без НДС. Источник и условия сохранятся как ваше заявление; соответствие ТЗ проверяется отдельно.</p>
    {notice.law === "223" && <label>Лот <select value={lot} onChange={event => { setLot(Number(event.target.value)); setLoaded(false); setReport(undefined); setError(undefined); }} disabled={pending}>{Array.from({ length: lotCount }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select></label>}
    {error && <p role="alert" className={styles.error}>{error}</p>}{error && !recordId && <button type="button" disabled={pending} onClick={() => { setLoaded(false); setRetry(value => value + 1); }}>Повторить чтение КП</button>}{sourceClosed && <p role="alert">Расчёт заблокирован: срок подачи истёк или есть блокировка источника.</p>}{quoteExpired && <p role="alert">Срок КП истёк. Введите актуальное предложение; прежний расчёт больше не действует.</p>}
    {!loaded ? <p>Читаем сохранённое КП…</p> : <details><summary>{input ? "Изменить КП и расходы" : "Добавить КП и расходы"}</summary>
      <form key={`${lot}:${report?.record_id ?? "new"}`} onSubmit={event => { event.preventDefault(); void save(event.currentTarget); }}><fieldset disabled={pending || calculationBlocked || !recordId} style={{ border: 0 }}>
        {field("supplier", "Поставщик")}{field("document", "Документ КП: имя / номер")}{field("locator", "Страница или раздел документа")}
        {field("amount_ex_vat", "Стоимость всего лота по КП без НДС")}{field("quote_vat_rate", "НДС поставщика, доля (например 0.20 или 0)")}
        {field("issued_at", "Дата выдачи с часовым поясом, например 2026-10-21T10:00:00+03:00")}{field("valid_until", "Действует до, с часовым поясом")}
        <label><input type="checkbox" name="covers_full_scope" value="yes" defaultChecked={input?.covers_full_scope} /> КП покрывает все позиции и весь объём выбранного лота</label>
        {field("availability_terms", "Наличие и срок готовности")}{field("delivery_terms", "Условия доставки и все адреса")}{field("payment_terms", "Условия оплаты")}
        <h4>Прочие расходы без НДС</h4><p>Заполните каждую статью. Явный 0 означает: расход включён в КП либо не требуется. Пустое поле останется UNKNOWN.</p>
        {Object.entries(expenseFields).map(([key, label]) => <label key={key} style={{ display: "block", margin: "6px 0" }}>{label}<input name={key} inputMode="decimal" defaultValue={input?.expenses[key] ?? ""} maxLength={30} style={{ display: "block", width: "100%" }} /></label>)}
        {field("expense_basis", "Основание расходов и нулей: документ / расчёт")}{field("tax_model", "Налоговый режим и основание на дату расчёта")}{field("output_vat_rate", "Выходной НДС, доля")}
        <h4>Допущения сценариев</h4><p>Доли: 0.05 означает 5%. Проверьте допущения для этой сделки.</p>
        {field("realistic_discount", "Реалистичное снижение цены", "text", input?.realistic_discount ?? "0.05")}{field("conservative_discount", "Консервативное снижение цены", "text", input?.conservative_discount ?? "0.10")}{field("conservative_cost_growth", "Консервативный рост всех расходов", "text", input?.conservative_cost_growth ?? "0.10")}
        <button type="submit" className={styles.secondaryButton}>{pending ? "Сохраняем…" : "Сохранить КП и пересчитать"}</button>
      </fieldset></form>
    </details>}
    {report?.calculation && <div aria-live="polite"><p data-calculation-status={current ? "CALCULATED" : calculationBlocked ? "BLOCKED" : "UNKNOWN"}>Расчёт: {betaCalculationLabel(current ? "CALCULATED" : calculationBlocked ? "BLOCKED" : "UNKNOWN")} · {formatTenderDeadline(report.calculation.checked_at)}</p>
      {(current ? report.calculation.scenarios : []).map(s => <div key={s.kind}><h4>{({ base: "Базовый", realistic: "Реалистичный", conservative: "Консервативный" })[s.kind]}</h4><p>Выручка без НДС: {formatMoneyString(s.revenue_net)} · Расходы: {formatMoneyString(s.costs_net)} · Прибыль: {formatMoneyString(s.profit)}</p><p>Маржа (доля): {s.margin} · Цена безубыточности с НДС: {formatMoneyString(s.break_even_gross)}</p>{s.assumptions.map(a => <p key={a}>{a}</p>)}</div>)}
      {report.calculation.reasons.map(reason => <p key={reason}>{betaReason(reason)}</p>)}<p>Допуск к участию: UNKNOWN. Расчёт по введённому КП не подтверждает техническое и юридическое соответствие.</p>
    </div>}
  </section>;
}
