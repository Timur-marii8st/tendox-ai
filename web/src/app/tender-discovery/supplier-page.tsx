"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { supplierPageMatches, supplierPageRequestKey, type SupplierPageRequest, type SavedSupplierPage } from "@/lib/eis-supplier-page";
import type { SerpLink } from "@/lib/eis-supplier-serp";
import { loadSupplierPage, prepareSupplierPage } from "./actions";
import { SupplierPageReportView } from "./supplier-page-report";
import { SupplierCatalog } from "./supplier-catalog";
export function SupplierPage({ request, link }: { request: SupplierPageRequest; link: SerpLink }) {
  const [result, setResult] = useState<SavedSupplierPage>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  function load(kind: "prepare" | "read" | "refresh") {
    const id = ++sequence.current; setResult(undefined); setError(undefined);
    start(async () => {
      try {
        const response = await (kind === "read" ? loadSupplierPage(request) : prepareSupplierPage(request, kind === "refresh"));
        if (id !== sequence.current) return;
        if (!response.result || !supplierPageMatches(response.result, request, kind !== "read", link)) {
          setError(response.error ?? "Результат не соответствует выбранному сайту."); return;
        }
        setResult(response.result);
      } catch { if (id === sequence.current) setError("Чтение сайта не завершено. Откройте сохранённую попытку позже."); }
    });
  }
  return <section className="mt-2" data-supplier-page={supplierPageRequestKey(request)}>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={pending} onClick={() => load("prepare")} className="rounded border px-2 py-1 disabled:opacity-50">Проверить сайт и цены</button>
      <button type="button" disabled={pending} onClick={() => load("read")} className="rounded border px-2 py-1 disabled:opacity-50">Открыть сохранённую проверку</button>
      <button type="button" disabled={pending} onClick={() => load("refresh")} className="rounded border px-2 py-1 disabled:opacity-50">Обновить проверку</button>
    </div>
    <p className="text-xs">Читается выбранная HTTPS-страница. Обновление не чаще раза в 15 минут.</p>
    {pending && <p role="status">Читаем страницу и её товарную разметку…</p>}
    {error && <p role="alert" className="text-red-800">{error}</p>}
    {result && <SupplierPageReportView result={result} />}
    {result?.report.observation?.status === "COMPLETED" && result.report.observation.final_url.startsWith("https://bumaga-s.ru/") &&
      <SupplierCatalog key={result.report.run_id} request={{ page: request, page_run_id: result.report.run_id, search_run_id: null, product_index: null }} />}
  </section>;
}
