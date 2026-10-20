"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { supplierSearchMatches, supplierSearchRequestKey, type SupplierSearchRequest, type SavedSupplierSearch } from "@/lib/eis-supplier-search";
import { loadSupplierSearch, prepareSupplierSearch } from "./actions";
import { SupplierSerp } from "./supplier-serp";
import { SupplierSearchReportView } from "./supplier-search-report";

export function SupplierSearch({ request, publicName }: { request: SupplierSearchRequest; publicName?: string | null }) {
  const [result, setResult] = useState<SavedSupplierSearch>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  function load(kind: "prepare" | "read" | "refresh") {
    const id = ++sequence.current;
    setResult(undefined); setError(undefined);
    start(async () => {
      try {
        const response = await (kind === "read" ? loadSupplierSearch(request) : prepareSupplierSearch(request, kind === "refresh"));
        if (id !== sequence.current) return;
        if (!response.result || !supplierSearchMatches(response.result, request, kind !== "read")) {
          setError(response.error ?? "Результат не соответствует выбранной позиции."); return;
        }
        setResult(response.result);
      } catch { if (id === sequence.current) setError("Поиск не завершён. Откройте сохранённую попытку или повторите позже."); }
    });
  }
  return <section className="mt-3" data-supplier-search={supplierSearchRequestKey(request)}>
    <SupplierSerp key={supplierSearchRequestKey(request)} request={request} publicName={publicName} />
    <p>Предварительный поиск снабжения по наименованию. Сейчас подключена категория серверов HPE Gen12; остальные категории добавляются отдельно.</p>
    <div className="mt-2 flex flex-wrap gap-2">
      <button type="button" disabled={pending} onClick={() => load("prepare")} className="rounded border px-3 py-2 disabled:opacity-50">Найти поставщиков</button>
      <button type="button" disabled={pending} onClick={() => load("read")} className="rounded border px-3 py-2 disabled:opacity-50">Открыть сохранённый поиск</button>
      <button type="button" disabled={pending} onClick={() => load("refresh")} className="rounded border px-3 py-2 disabled:opacity-50">Обновить источник</button>
    </div>
    <p className="text-xs">Обновление доступно не чаще одного раза в 15 минут. Самостоятельно новые запросы не отправляются.</p>
    {pending && <p role="status">Проверяем выбранную позицию и источник…</p>}
    {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
    {result && <SupplierSearchReportView result={result} />}
  </section>;
}
