"use client";

import { useEffect, useState } from "react";
import { financialQuoteCurrent, betaCalculationLabel, betaReason, betaRefKey, type BetaQuoteRef, type BetaShortlist } from "@/lib/beta-procurement";
import { type TenderRow, formatMoneyString } from "@/lib/tender-workspace";
import { readBetaShortlist } from "./beta-actions";
import styles from "./workspace.module.css";

export function BetaFinancialComparison({ rows, region, onSelect }: { rows: TenderRow[]; region: string; onSelect: (id: string) => void }) {
  const [clock, setClock] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [result, setResult] = useState<BetaShortlist>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(rows.length > 0);
  const refs = rows.flatMap(row => Array.from({ length: row.law === "44" ? 1 : row.raw223?.notice.lots.length ?? 0 }, (_, i): BetaQuoteRef => ({ notice: { law: row.law, purchase_number: row.purchaseNumber, version_number: row.version, notice_xml_sha256: row.xmlSha256 }, lot_index: row.law === "223" ? i + 1 : null })));
  const selectedRefs = refs.slice(0, 20);
  const requestJson = JSON.stringify(selectedRefs);
  useEffect(() => {
    if (requestJson === "[]") return;
    let active = true;
    void readBetaShortlist(JSON.parse(requestJson) as BetaQuoteRef[], region).then(next => {
      if (active) { setNow(Date.now()); setPending(false); setError(next.error); setResult(next.report); }
    }).catch(() => { if (active) { setPending(false); setError("Связь прервалась. Повторите обновление подбора."); } });
    return () => { active = false; };
  }, [requestJson, region]);
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
  const currentOrder = result?.financial_order.filter(id => result.rows.some(item => item.report.record_id === id && isCurrent(item.report))) ?? [];
  async function compare() {
    setPending(true); setError(undefined); setResult(undefined);
    try {
      const next = await readBetaShortlist(selectedRefs, region);
      setNow(Date.now()); setError(next.error); setResult(next.report);
    } catch { setError("Связь прервалась. Повторите обновление подбора."); }
    finally { setPending(false); }
  }
  return <section className={styles.betaPanel} aria-label="Лучшие закупки по расчёту КП"><h2>Лучшие по расчётной прибыли</h2>
    <p>До пяти вариантов по консервативной прибыли, затем марже. Сравниваются {selectedRefs.length} из {refs.length} загруженных лотов с введёнными действующими КП. Это финансовое сравнение; допуск к участию требует проверки.</p>
    <button className={styles.secondaryButton} type="button" onClick={() => void compare()} disabled={pending || !selectedRefs.length}>{pending ? "Сравниваем…" : "Обновить подбор по КП и профилю"}</button>
    <p><a href="/company-profile">Открыть и выбрать профиль компании</a></p>
    {error && <p role="alert">{error}</p>}
    {result && <><p>Профиль: {result.profile ? `версия ${result.profile.version} · ${result.profile.snapshot_sha256}` : "Не выбран — персональный подбор недоступен"}</p>
      {currentOrder.length === 0 && <p>В этой части выдачи нет положительных полных расчётов без выявленных ограничений профиля. Введите КП и расходы или проверьте причины ниже.</p>}
      {[...result.rows].sort((a,b) => (a.financial_position ?? 99) - (b.financial_position ?? 99)).map(item => {
        const row = findRow(item.report.ref);
        const current = isCurrent(item.report);
        const position = current && item.report.record_id && currentOrder.includes(item.report.record_id) ? currentOrder.indexOf(item.report.record_id) + 1 : null;
        const scenario = current ? item.report.calculation?.scenarios.find(s => s.kind === "conservative") : undefined;
        return <article key={betaRefKey(item.report.ref)}><h3>{position ? `${position}. ` : ""}{row?.title ?? item.report.ref.notice.purchase_number}{item.report.ref.lot_index && ` · лот ${item.report.ref.lot_index}`}</h3>
          <p>{item.report.calculation ? betaCalculationLabel(row?.blocked ? "BLOCKED" : item.report.calculation.status === "CALCULATED" && !current ? "UNKNOWN" : item.report.calculation.status) : "КП не введено"} · Профиль: {item.profile_status === "FAIL" ? "нарушено ограничение" : "требует проверки"} · Допуск: UNKNOWN</p>
          {scenario && <p>Консервативная прибыль: {formatMoneyString(scenario.profit)} · Маржа (доля): {scenario.margin}</p>}
          {item.reasons.map(reason => <p key={reason}>{betaReason(reason)}</p>)}
          {row && <button type="button" onClick={() => onSelect(row.id)}>Открыть КП, ТЗ и ссылки закупки</button>}
        </article>;
      })}</>}
  </section>;
}
