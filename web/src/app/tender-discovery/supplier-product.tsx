"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { supplierProductMatches, supplierProductRequestKey, type SupplierProductRequest, type SavedSupplierProduct } from "@/lib/eis-supplier-product";
import { prepareSupplierProduct, loadSupplierProduct } from "./actions";
import { SupplierProductReportView } from "./supplier-product-report";
import { RequirementPreviewView } from "./requirement-preview";
export function SupplierProduct({ request, expected }: { request: SupplierProductRequest; expected: { source_url: string; html_sha256: string } }) {
  const [result, setResult] = useState<SavedSupplierProduct>(), [error, setError] = useState<string>();
  const [pending, start] = useTransition(), sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  function load(prepare: boolean) {
    const id = ++sequence.current; setResult(undefined); setError(undefined);
    start(async () => { try {
      const state = await (prepare ? prepareSupplierProduct(request) : loadSupplierProduct(request));
      if (sequence.current !== id) return;
      if (!state.result || !supplierProductMatches(state.result, request, prepare, expected)) { setError(state.error ?? "Данные не соответствуют выбранному товару."); return; }
      setResult(state.result);
    } catch { if (sequence.current === id) setError("Не удалось открыть условия товара."); } });
  }
  return <section className="mt-2" data-supplier-product={supplierProductRequestKey(request)}>
    <div className="flex gap-2"><button disabled={pending} type="button" className="rounded border px-2 py-1" onClick={() => load(true)}>Сопоставить условия и характеристики</button><button disabled={pending} type="button" className="rounded border px-2 py-1" onClick={() => load(false)}>Открыть сохранённое сопоставление</button></div>
    <p className="text-xs">Используется сохранённая карточка. Новых обращений к сайту нет.</p>
    {pending && <p role="status">Разбираем сохранённые условия товара…</p>}{error && <p role="alert">{error}</p>}
    {result && <><SupplierProductReportView result={result} /><RequirementPreviewView key={result.report.run_id} product={result} /></>}
  </section>;
}
