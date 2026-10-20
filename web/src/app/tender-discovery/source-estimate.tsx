"use client";

import { useRef, useState, useTransition } from "react";
import type { MixedNoticeRef, SourceEstimateResult } from "@/lib/procurement-api";
import { estimateSource } from "./actions";
import { price223Labels } from "./comparison-223";
import { Rejection223State } from "./rejection223-state";
import { LotCancellation223State } from "./lot-cancellation223-state";

type LotChoice = { index: number; title: string };
export function SourceEstimateForm({ notice, lots = [] }: { notice: MixedNoticeRef; lots?: LotChoice[] }) {
  const [state, setState] = useState<{ result?: SourceEstimateResult; error?: string }>({});
  const [pending, start] = useTransition();
  const generation = useRef(0);
  const label = `Предварительная экономика ${notice.law}-ФЗ ${notice.purchase_number}`;
  const fields = [
    ["goods", "Товар целиком, без НДС, ₽", ""],
    ["expenses", "Остальные затраты и налоги, кроме выходного НДС, ₽", ""],
    ["vat_rate", "Выходной НДС, доля от 0 до 1", ""],
    ["realistic_discount", "Реалистичное снижение цены, доля", "0.05"],
    ["conservative_discount", "Консервативное снижение цены, доля", "0.10"],
    ["conservative_cost_growth", "Консервативный рост затрат, доля", "0.10"],
  ];
  return <section aria-label={label} className="mt-3 rounded border bg-white p-3 text-sm">
    <details><summary className="font-bold">Предварительная экономика — три сценария</summary>
      <p className="mt-2">Опубликованная цена берётся из выбранной версии ЕИС. Введите затраты на весь объём
        {notice.law === "223" ? " выбранного лота" : " закупки"}, включая логистику, финансирование, гарантии и прочие известные расходы.</p>
      <p>Доли: 0.05 = 5%. Налоговая модель задаётся вами. Это предварительный расчёт; полное КП, допуск и рейтинг прибыли: UNKNOWN.</p>
      <form className="mt-3" onChange={() => { generation.current++; setState({}); }} onSubmit={event => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const value = (key: string) => String(data.get(key) ?? "").trim().replace(",", ".");
        const costs = { goods: value("goods"), expenses: value("expenses"), vat_rate: value("vat_rate"),
          realistic_discount: value("realistic_discount"), conservative_discount: value("conservative_discount"),
          conservative_cost_growth: value("conservative_cost_growth"), basis: String(data.get("basis") ?? "").trim(),
          costs_complete_ack: data.get("costs_complete_ack") === "on" };
        const epoch = ++generation.current;
        setState({});
        start(async () => {
          const next = await estimateSource({ notice, lot_index: notice.law === "223" ? Number(value("lot_index")) : null, costs });
          if (epoch === generation.current) setState(next);
        });
      }}>
        <fieldset disabled={pending} className="space-y-2 disabled:opacity-60">
          {notice.law === "223" && <label className="block">Лот для расчёта
            <select name="lot_index" required defaultValue="" className="mt-1 block w-full rounded border p-2">
              <option value="" disabled>Выберите конкретный лот</option>
              {lots.map(l => <option key={l.index} value={l.index}>{l.title}</option>)}
            </select>
          </label>}
          {fields.map(([name, title, initial]) => <label key={name} className="block">{title}
            <input name={name} required inputMode="decimal" pattern="[0-9]+([.,][0-9]+)?" maxLength={40}
              defaultValue={initial} className="mt-1 block w-full rounded border p-2" />
          </label>)}
          <label className="block">Основание затрат и налогов
            <textarea name="basis" required maxLength={2000} className="mt-1 block w-full rounded border p-2" />
          </label>
          <label className="flex gap-2"><input name="costs_complete_ack" type="checkbox" />
            Подтверждаю, что предварительные затраты включают все известные расходы. Это не подтверждённое КП.</label>
          <button type="submit" className="rounded bg-blue-700 px-3 py-2 font-bold text-white">
            {pending ? "Расчёт…" : "Рассчитать три сценария"}</button>
        </fieldset>
      </form>
      {state.error && <p role="alert" className="mt-2 text-red-800">{state.error}</p>}
      {state.result && <EstimateView result={state.result} />}
    </details>
  </section>;
}

function EstimateView({ result }: { result: SourceEstimateResult }) {
  const e = result.estimate;
  const names: Record<string, string> = { base: "Базовый", realistic: "Реалистичный", conservative: "Консервативный" };
  return <div className="mt-3" role="status">
    <p className="font-bold">Предварительный расчёт: {e.status}</p>
    <Rejection223State state={result.cancellation_state} />
    <LotCancellation223State state={result.lot_cancellation_state} selected={result.selected_lot_cancellation_state} />
    <p className={result.source_schema_status === "PASS" ? "" : "font-bold text-amber-900"}>
      Качество исходного XML: {result.source_schema_status ?? "UNKNOWN"}.
      {result.source_schema_status !== "PASS" && " Полнота и достоверность исходных условий требуют проверки; расчёт не является допуском."}</p>
    {result.request.notice.law === "223" && <p>Вид исходной цены: {price223Labels[result.source_price_kind ?? "UNKNOWN"]}.</p>}
    {result.source_price_kind && result.source_price_kind !== "INITIAL_SUM" && <p className="font-bold text-amber-900">
      Максимальная или текстовая цена не заменяет начальную сумму для этого расчёта.</p>}
    <p>Опубликованный предел: {result.ceiling_rub ?? "UNKNOWN"} RUB.
      {result.request.lot_index !== null && ` Выбран лот ${result.request.lot_index}, номер в XML: ${result.lot_ordinal?.value ?? "UNKNOWN"}.`}</p>
    {result.currency && <p>Валюта источника: {result.currency.value ?? "UNKNOWN"}. Пересчёт валют не выполняется.</p>}
    {result.blocking_reasons.length > 0 && <ul className="list-disc pl-4 font-bold text-red-800">{result.blocking_reasons.map((r,i) => <li key={i}>{r}</li>)}</ul>}
    {result.source_reasons.length > 0 && <ul className="list-disc pl-4 text-amber-900">{result.source_reasons.map((r,i) => <li key={i}>{r}</li>)}</ul>}
    <ul className="list-disc pl-4">{e.reasons.map((r,i) => <li key={i}>{r}</li>)}</ul>
    {!!e.scenarios.length && <div className="overflow-x-auto"><table className="mt-2 w-full text-left text-xs">
      <caption className="text-left">Суммы в рублях без НДС; маржа и допустимое снижение — доли.</caption>
      <thead><tr>{["Сценарий", "Выручка", "Затраты", "Прибыль", "Маржа", "Безубыточная цена с НДС", "Макс. снижение"].map(h => <th key={h} className="p-1">{h}</th>)}</tr></thead>
      <tbody>{e.scenarios.map(s => <tr key={s.kind} className="border-t">
        {[names[s.kind], s.revenue_net, s.costs_net, s.profit, s.margin, s.break_even_gross, s.maximum_discount].map((v,i) => <td key={i} className="p-1">{v}</td>)}
      </tr>)}</tbody>
    </table></div>}
    {e.scenarios.map(s => <p key={s.kind} className="mt-2">{names[s.kind]}: {s.assumptions.join(" ")}</p>)}
    <p className="mt-2">Основание: {e.basis}</p>
    <p>Проверка требований, действительного КП, полноты затрат и допуска: UNKNOWN. Рекомендация: {e.recommendation}.</p>
    <details className="mt-2 text-xs"><summary>Источники и время расчёта</summary>
      <p className="break-all">XML: {result.ceiling.provenance.document_id} · {result.ceiling.provenance.locator}</p>
      <p className="break-all">Ввод оператора: {result.manual_provenance.document_id} · {result.manual_provenance.locator}</p>
      <p>{result.checked_at} · {result.actor_id}</p>
    </details>
  </div>;
}
