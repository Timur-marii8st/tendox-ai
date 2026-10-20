"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { supplierCatalogMatches, supplierCatalogRequestKey, type SupplierCatalogRequest, type CatalogLink, type SavedSupplierCatalog } from "@/lib/eis-supplier-catalog";
import { prepareSupplierCatalog, loadSupplierCatalog } from "./actions";
import { SupplierCatalogReportView } from "./supplier-catalog-report";
import { SupplierProduct } from "./supplier-product";
export function SupplierCatalog({ request, expectedLink }: { request: SupplierCatalogRequest; expectedLink?: CatalogLink }) {
  const [result, setResult] = useState<SavedSupplierCatalog>(); const [error, setError] = useState<string>();
  const [pending, start] = useTransition(); const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const product = request.search_run_id !== null;
  function load(kind: "prepare" | "read" | "refresh") {
    const id = ++sequence.current; setError(undefined); setResult(undefined);
    start(async () => {
      try {
        const response = await (kind === "read" ? loadSupplierCatalog(request) : prepareSupplierCatalog(request, kind === "refresh"));
        if (id !== sequence.current) return;
        if (!response.result || !supplierCatalogMatches(response.result, request, kind !== "read", expectedLink)) { setError(response.error ?? "Ответ не соответствует выбранной карточке."); return; }
        setResult(response.result);
      } catch { if (id === sequence.current) setError("Чтение не завершено. Откройте сохранённый результат позже."); }
    });
  }
  return <section className="mt-2" data-supplier-catalog={supplierCatalogRequestKey(request)}>
    <div className="flex flex-wrap gap-2">
      <button disabled={pending} type="button" onClick={() => load("prepare")} className="rounded border px-2 py-1">{product ? "Проверить товар и цену" : "Найти товары на этом сайте"}</button>
      <button disabled={pending} type="button" onClick={() => load("read")} className="rounded border px-2 py-1">Открыть сохранённый результат</button>
      <button disabled={pending} type="button" onClick={() => load("refresh")} className="rounded border px-2 py-1">Обновить</button>
    </div>
    {!product && <p className="text-xs">Поддержана проверенная форма поиска «Бумага-С». Отправляется публичное наименование позиции ЕИС.</p>}
    {pending && <p role="status">{product ? "Читаем выбранную товарную карточку…" : "Ищем товарные ссылки на сайте…"}</p>}
    {error && <p role="alert" className="text-red-800">{error}</p>}
    {result && <SupplierCatalogReportView result={result} renderProduct={link => <SupplierCatalog
      key={`${result.report.run_id}:${link.index}`} request={{ ...request, search_run_id: result.report.run_id, product_index: link.index }} expectedLink={link} />} />}
    {result?.report.stage === "PRODUCT" && result.report.observation?.status === "COMPLETED" && result.report.source_body_sha256 &&
      <SupplierProduct key={result.report.run_id} request={{ catalog: request, product_run_id: result.report.run_id }} expected={{ source_url: result.report.observation.final_url, html_sha256: result.report.source_body_sha256 }} />}
  </section>;
}
