"use client";

import { useEffect, useState } from "react";
import { financialQuoteCurrent, betaCalculationLabel, betaReason, betaRefKey, type BetaQuoteRef, type BetaShortlist } from "@/lib/beta-procurement";
import { type TenderRow, formatMoneyString } from "@/lib/tender-workspace";
import { readBetaShortlist } from "./beta-actions";
import styles from "./workspace.module.css";

export function BetaFinancialComparison({ rows, region, onSelect }: { rows: TenderRow[]; region: string; onSelect: (id: string) => void }) {
  const [ranking, setRanking] = useState<"UNIT_PROFIT" | "TOTAL_PROFIT">("UNIT_PROFIT");
  const [clock, setClock] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [response, setResponse] = useState<{ key: string; report?: BetaShortlist }>();
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(rows.length > 0);
  const refs = rows.flatMap(row => Array.from({ length: row.law === "44" ? 1 : row.raw223?.notice.lots.length ?? 0 }, (_, i): BetaQuoteRef => ({ notice: { law: row.law, purchase_number: row.purchaseNumber, version_number: row.version, notice_xml_sha256: row.xmlSha256 }, lot_index: row.law === "223" ? i + 1 : null })));
  const selectedRefs = refs.slice(0, 20);
  const requestJson = JSON.stringify(selectedRefs);
  const queryKey = JSON.stringify({ requestJson, region, ranking });
  const result = response?.key === queryKey && response.report?.ranking === ranking ? response.report : undefined;
  useEffect(() => {
    if (requestJson === "[]") return;
    let active = true;
    void readBetaShortlist(JSON.parse(requestJson) as BetaQuoteRef[], region, ranking).then(next => {
      if (active) { setNow(Date.now()); setPending(false); setError(next.error); setResponse({ key: queryKey, report: next.report }); }
    }).catch(() => { if (active) { setPending(false); setError("Связь прервалась. Повторите обновление подбора."); } });
    return () => { active = false; };
  }, [requestJson, region, ranking, queryKey, refresh]);
  useEffect(() => {
    if (!result) return;
    const at = Date.now();
    const next = Math.min(...result.rows.flatMap(item => {
      const expiry = item.report.input?.valid_until;
      return expiry && Date.parse(expiry) > at ? [Date.parse(expiry)] : [];
    }));
    if (!Number.isFinite(next)) return;
    const timer = window.setTimeout(() => { setNow(Date.now()); setClock(value => value + 1); }, Math.min(next - at + 1, 60_000));
    return () => window.clearTimeout(timer);
  }, [result, clock]);
  const findRow = (ref: BetaQuoteRef) => rows.find(r => r.law === ref.notice.law && r.purchaseNumber === ref.notice.purchase_number && r.version === ref.notice.version_number && r.xmlSha256 === ref.notice.notice_xml_sha256);
  const isCurrent = (report: NonNullable<typeof result>["rows"][number]["report"]) => {
    const row = findRow(report.ref);
    return !!row && financialQuoteCurrent(report, row.deadline, row.blocked, now);
  };
  const currentOrder = (ranking === "UNIT_PROFIT" ? result?.unit_orders?.flatMap(group => group.record_ids) : result?.financial_order)?.filter(id => result?.rows.some(item => item.report.record_id === id && isCurrent(item.report))) ?? [];
  function compare() {
    setPending(true); setError(undefined); setResponse(undefined);
    setRefresh(value => value + 1);
  }
  return <section className={styles.betaPanel} aria-label="Лучшие закупки по расчёту КП"><h2>{ranking === "UNIT_PROFIT" ? "Лучшие по прибыли на единицу" : "Лучшие по общей расчётной прибыли"}</h2>
    <label>Порядок сравнения <select value={ranking} onChange={event => { setRanking(event.target.value as typeof ranking); setResponse(undefined); setPending(selectedRefs.length > 0); }}>
      <option value="UNIT_PROFIT">Прибыль на единицу товара</option>
      <option value="TOTAL_PROFIT">Общая прибыль лота</option>
    </select></label>
    <p>{ranking === "UNIT_PROFIT" ? "До пяти вариантов в каждой группе исходных единиц по консервативной прибыли на единицу, затем марже. Единицы и упаковки не пересчитываются; одинаковое название единицы не подтверждает эквивалентность товаров." : "До пяти вариантов по общей консервативной прибыли, затем марже."} Сравниваются {selectedRefs.length} из {refs.length} загруженных лотов с введёнными действующими КП. Это финансовое сравнение; допуск к участию требует проверки.</p>
    <button className={styles.secondaryButton} type="button" onClick={() => void compare()} disabled={pending || !selectedRefs.length}>{pending ? "Сравниваем…" : "Обновить подбор по КП и профилю"}</button>
    <p><a href="/company-profile">Открыть и выбрать профиль компании</a></p>
    {error && <p role="alert">{error}</p>}
    {result && <><p>Профиль: {result.profile ? `версия ${result.profile.version} · ${result.profile.snapshot_sha256}` : "Не выбран — персональный подбор недоступен"}</p>
      {currentOrder.length === 0 && <p>В этой части выдачи нет положительных полных расчётов без выявленных ограничений профиля. Введите КП и расходы или проверьте причины ниже.</p>}
      {[...result.rows].sort((a,b) => (ranking === "UNIT_PROFIT" ? (a.report.quantity_unit?.value?.toLowerCase().trim().replace(/\s+/g, " ") ?? "~").localeCompare(b.report.quantity_unit?.value?.toLowerCase().trim().replace(/\s+/g, " ") ?? "~", "ru") : 0) || (a.financial_position ?? 99) - (b.financial_position ?? 99)).map(item => {
        const row = findRow(item.report.ref);
        const current = isCurrent(item.report);
        const position = current && item.report.record_id && currentOrder.includes(item.report.record_id) ? item.financial_position : null;
        const scenario = current ? item.report.calculation?.scenarios.find(s => s.kind === "conservative") : undefined;
        return <article key={betaRefKey(item.report.ref)}><h3>{position ? `${position}. ` : ""}{row?.title ?? item.report.ref.notice.purchase_number}{item.report.ref.lot_index && ` · лот ${item.report.ref.lot_index}`}</h3>
          <p>{item.report.calculation ? betaCalculationLabel(row?.blocked ? "BLOCKED" : item.report.calculation.status === "CALCULATED" && !current ? "UNKNOWN" : item.report.calculation.status) : "КП не введено"} · Профиль: {item.profile_status === "FAIL" ? "нарушено ограничение" : "требует проверки"} · Допуск: UNKNOWN</p>
          {current && ranking === "UNIT_PROFIT" && item.unit_profit != null && <p>Прибыль на единицу: {item.unit_profit.replace(".", ",")} ₽ / {item.report.quantity_unit?.value} · Количество из XML: {item.report.unit_quantity?.value}. Позиция {position ?? "вне пятёрки"} в группе «{item.report.quantity_unit?.value}».</p>}
          {scenario && <p>Консервативная прибыль: {formatMoneyString(scenario.profit)} · Маржа (доля): {scenario.margin}</p>}
          {item.reasons.map(reason => <p key={reason}>{betaReason(reason)}</p>)}
          {row && <button type="button" onClick={() => onSelect(row.id)}>Открыть КП, ТЗ и ссылки закупки</button>}
        </article>;
      })}</>}
  </section>;
}
