"use client";

import { useState, type ReactNode } from "react";

export type ResultEntry = {
  id: string;
  quality: "STRONG" | "PARTIAL";
  application: "FAIL" | "UNKNOWN";
  method: string;
};
export type ResultFilter = "ALL" | "STRONG" | "PARTIAL" | "FAIL" | "UNKNOWN";

export function filterResults(entries: ResultEntry[], filter: ResultFilter, method: string | null) {
  return entries.filter(entry => (!method || entry.method === method) &&
    (filter === "ALL" || (filter === "STRONG" || filter === "PARTIAL"
      ? entry.quality === filter : entry.application === filter)));
}

export function ResultExplorer({ entries, total, canLoad = false, children }: {
  entries: ResultEntry[]; total: number; canLoad?: boolean; children: (visible: Set<string>) => ReactNode;
}) {
  const [filter, setFilter] = useState<ResultFilter>("ALL");
  const [method, setMethod] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const filtered = filterResults(entries, filter, method);
  const pageSize = 10;
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages - 1);
  const visible = new Set(filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map(entry => entry.id));
  const methods = [...new Set(entries.map(entry => entry.method))].map(name => ({
    name, count: entries.filter(entry => entry.method === name).length,
  })).sort((a, b) => b.count - a.count);
  const filters: [ResultFilter, string][] = [["ALL", "Все"], ["STRONG", "Все слова запроса"],
    ["PARTIAL", "Часть слов"], ["FAIL", "Подача заблокирована"], ["UNKNOWN", "Подача не подтверждена"]];

  return <section aria-label="Обзор результатов поиска" className="space-y-4">
    <div className="rounded-xl bg-slate-900 p-5 text-white">
      <h3 className="text-lg font-bold">Сначала обзор, затем отдельная закупка</h3>
      <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div><dt className="text-sm text-slate-300">Найдено в сохранённой базе</dt><dd className="text-3xl font-black">{total}</dd></div>
        <div><dt className="text-sm text-slate-300">Получено для просмотра</dt><dd className="text-3xl font-black">{entries.length}</dd></div>
        <div><dt className="text-sm text-slate-300">Полнота всей ЕИС</dt><dd className="text-lg font-bold">Не подтверждена</dd></div>
      </dl>
      {total > entries.length && <p className="mt-4 text-sm text-amber-200">Сервер вернул только {entries.length} из {total} совпадений.
        Ещё {total - entries.length} не показаны. {canLoad ? "Загрузите следующие совпадения кнопкой под результатами;" : "Уточните запрос;"}
        {" "}страницы ниже переключают только полученные записи.</p>}
    </div>
    <div className="rounded-xl border border-slate-200 p-4">
      <h4 className="font-bold">По способу закупки</h4>
      <p className="mt-1 text-xs text-slate-600">Схема только по {entries.length} полученным записям. Нажмите на строку, чтобы сузить просмотр.</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {methods.map(item => <button type="button" key={item.name} aria-pressed={method === item.name}
          onClick={() => { setMethod(method === item.name ? null : item.name); setPage(0); }}
          className="rounded-lg p-3 text-left text-sm"
          style={{ background: method === item.name ? "#eff6ff" : "white", color: "#0f172a",
            border: `1px solid ${method === item.name ? "#1d4ed8" : "#cbd5e1"}` }}>
          <span className="flex justify-between gap-3"><span>{item.name}</span><strong>{item.count}</strong></span>
          <span aria-hidden="true" className="mt-2 block h-2 overflow-hidden rounded bg-slate-100">
            <span className="block h-full rounded bg-blue-600" style={{ width: `${item.count / Math.max(1, entries.length) * 100}%` }} />
          </span>
        </button>)}
      </div>
    </div>
    <div className="flex flex-wrap gap-2" aria-label="Фильтры полученных результатов">
      {filters.map(([value, label]) => <button type="button" key={value} aria-pressed={filter === value}
        onClick={() => { setFilter(value); setPage(0); }}
        className="rounded-full px-3 py-2 text-sm"
        style={{ background: filter === value ? "#eff6ff" : "white", color: filter === value ? "#1d4ed8" : "#0f172a",
          border: `1px solid ${filter === value ? "#1d4ed8" : "#cbd5e1"}` }}>
        {label} · {filterResults(entries, value, method).length}
      </button>)}
      {method && <button type="button" className="px-3 text-sm text-blue-700 underline"
        onClick={() => { setMethod(null); setPage(0); }}>Сбросить способ закупки</button>}
    </div>
    <p className="text-xs text-slate-600">Совпадение слов не подтверждает соответствие ТЗ. Подача, полное КП и прибыль требуют отдельной проверки.</p>
    {filtered.length === 0 && <p role="status" className="rounded-lg bg-slate-50 p-4 text-sm">
      В полученных записях по выбранным фильтрам ничего нет. Это не означает отсутствие закупок в ЕИС.</p>}
    {children(visible)}
    {filtered.length > 0 && <nav aria-label="Страницы полученных результатов" className="flex flex-wrap items-center justify-between gap-3 text-sm">
      <p role="status">Строки {currentPage * pageSize + 1}–{Math.min((currentPage + 1) * pageSize, filtered.length)} из {filtered.length} · страница {currentPage + 1} из {pages}</p>
      <div className="flex gap-2">
        <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Назад</button>
        <button type="button" disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Дальше</button>
      </div>
    </nav>}
  </section>;
}

export function ResultRow({ title, number, quality, application, price, deadline, children }: {
  title: string; number: string; quality: ResultEntry["quality"]; application: ResultEntry["application"];
  price: string; deadline: string | null; children: ReactNode;
}) {
  return <details className="rounded-xl border border-slate-200 bg-white">
    <summary className="cursor-pointer p-4 marker:text-blue-700">
      <span className="inline-grid w-[calc(100%-1.5rem)] gap-3 align-top sm:grid-cols-[1fr_11rem]">
        <span><span className="block font-bold">{title}</span><span className="mt-1 block text-xs text-slate-500">№ {number} · открыть условия и документы</span></span>
        <span className="text-sm"><span className="block font-bold">{price}</span><span className="block text-slate-600">Срок: {deadline ?? "не подтверждён"}</span></span>
        <span className="flex flex-wrap gap-2 text-xs sm:col-span-2">
          <span className="rounded bg-slate-100 px-2 py-1">{quality === "STRONG" ? "Все слова запроса" : "Часть слов запроса"}</span>
          <span className={`rounded px-2 py-1 ${application === "FAIL" ? "bg-red-50 font-bold text-red-800" : "bg-amber-50 text-amber-900"}`}>
            {application === "FAIL" ? "Подача заблокирована · FAIL" : "Подача не подтверждена · UNKNOWN"}</span>
        </span>
      </span>
    </summary>
    <div className="border-t border-slate-100 p-4 text-sm">{children}</div>
  </details>;
}
