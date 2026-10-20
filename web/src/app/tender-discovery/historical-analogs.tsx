"use client";

import { useEffect, useState, useTransition } from "react";
import { createAnalogReadSession, validAnalogRequest, type AnalogReadState } from "../../lib/eis-analogs";
import type { ProtocolNoticeRef } from "../../lib/eis-protocols";
import { loadCharacteristicPair, loadHistoricalAnalogs } from "./actions";
import { HistoricalAnalogReportView } from "./historical-analog-report";

type Props = { notice: ProtocolNoticeRef; query: string; positions: Array<{ name: string }> };
export function HistoricalAnalogs(props: Props) {
  return <AnalogReader key={`${props.notice.purchase_number}:${props.notice.version_number}:${props.notice.notice_xml_sha256}:${props.query}`} {...props} />;
}
function AnalogReader({ notice, query: initialQuery, positions }: Props) {
  const [sourceIndex, setSourceIndex] = useState("1");
  const [query, setQuery] = useState(initialQuery);
  const [lookback, setLookback] = useState("365");
  const [state, setState] = useState<AnalogReadState>({});
  const [session] = useState(createAnalogReadSession);
  const [pending, startReading] = useTransition();
  useEffect(() => () => session.invalidate(), [session]);
  const clear = () => { session.invalidate(); setState({}); };
  const request = { target: notice, source_index: Number(sourceIndex), query: query.trim(), lookback_days: Number(lookback) };
  return <section className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3">
    <h4 className="font-bold">Подобрать исторические кандидаты в аналоги</h4>
    <p className="mt-1 text-xs text-slate-600">До 20 сохранённых карточек и 25 позиций на карточку. Технические требования и регион поставки ещё не проверены.</p>
    {positions.length ? <div className="mt-3 flex flex-wrap gap-3">
      <label className="min-w-48 flex-1 text-sm font-bold">Позиция выбранной карточки
        <select value={sourceIndex} disabled={pending} onChange={e => { clear(); setSourceIndex(e.target.value); }}
          className="mt-1 block w-full rounded border border-slate-300 bg-white p-2 font-normal">
          {positions.slice(0, 25).map((p, i) => <option key={i} value={i + 1}>{i + 1}. {p.name}</option>)}
        </select>
      </label>
      <label className="min-w-48 flex-1 text-sm font-bold">Поисковые слова для истории
        <input value={query} maxLength={120} disabled={pending} onChange={e => { clear(); setQuery(e.target.value); }}
          className="mt-1 block w-full rounded border border-slate-300 bg-white p-2 font-normal" />
      </label>
      <label className="text-sm font-bold">Период, дней
        <input type="number" min={1} max={730} step={1} value={lookback} disabled={pending}
          onChange={e => { clear(); setLookback(e.target.value); }} className="mt-1 block w-28 rounded border border-slate-300 bg-white p-2 font-normal" />
      </label>
      <button type="button" disabled={pending || !validAnalogRequest(request)}
        className="self-end rounded bg-indigo-700 px-3 py-2 font-bold text-white disabled:opacity-50"
        onClick={() => { setState({}); startReading(async () => {
          const result = await session.read(request, loadHistoricalAnalogs);
          if (result) setState(result);
        }); }}>{pending ? "Подбираю историю…" : "Подобрать из сохранённой истории"}</button>
    </div> : <p className="mt-2 text-sm">Позиции карточки не разобраны: UNKNOWN. Подбор по позиции недоступен.</p>}
    {positions.length > 25 && <p className="mt-2 text-xs">Доступны первые 25 из {positions.length} позиций. Остальные этим подбором не проверяются.</p>}
    {state.error && <p role="alert" className="mt-3 text-sm font-bold text-red-800">{state.error}</p>}
    {state.result && <HistoricalAnalogReportView report={state.result} compareCharacteristics={loadCharacteristicPair} />}
  </section>;
}
