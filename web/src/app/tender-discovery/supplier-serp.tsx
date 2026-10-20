"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { supplierSearchRequestKey, type SupplierSearchRequest } from "@/lib/eis-supplier-search";
import { supplierSerpMatches, supplierSerpQuery, type SavedSupplierSerp } from "@/lib/eis-supplier-serp";
import { loadSupplierSerp, prepareSupplierSerp } from "./actions";
import { SupplierSerpReportView } from "./supplier-serp-report";
import { SupplierPage } from "./supplier-page";
import { CaptchaAssist } from "./captcha-assist";

export function SupplierSerp({ request, publicName }: { request: SupplierSearchRequest; publicName?: string | null }) {
  const [result, setResult] = useState<SavedSupplierSerp>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  function load(kind: "prepare" | "read" | "refresh") {
    const id = ++sequence.current; setResult(undefined); setError(undefined);
    start(async () => {
      try {
        const response = await (kind === "read" ? loadSupplierSerp(request) : prepareSupplierSerp(request, kind === "refresh"));
        if (id !== sequence.current) return;
        if (!response.result || !supplierSerpMatches(response.result, request, kind !== "read")) {
          setError(response.error ?? "Результат не соответствует выбранной позиции."); return;
        }
        setResult(response.result);
      } catch { if (id === sequence.current) setError("Поиск не завершён. Откройте сохранённую попытку позже."); }
    });
  }
  return <section className="mt-4 rounded border p-3" data-supplier-serp={supplierSearchRequestKey(request)}>
    <h4 className="font-semibold">Поиск производителей и поставщиков в интернете</h4>
    <p>Публичный запрос: {supplierSerpQuery(publicName) ?? "будет проверен по сохранённому наименованию позиции"}.</p>
    <p className="text-sm">Bing, Яндекс и Google. Отправляется публичное наименование позиции ЕИС и слова для поиска поставщиков. Найденные сайты требуют проверки цены, комплектации, партии и сроков.</p>
    <div className="mt-2 flex flex-wrap gap-2">
      <button type="button" disabled={pending} onClick={() => load("prepare")} className="rounded border px-3 py-2 disabled:opacity-50">Искать в интернете</button>
      <button type="button" disabled={pending} onClick={() => load("read")} className="rounded border px-3 py-2 disabled:opacity-50">Открыть сохранённую выдачу</button>
      <button type="button" disabled={pending} onClick={() => load("refresh")} className="rounded border px-3 py-2 disabled:opacity-50">Обновить выдачу</button>
    </div>
    <p className="text-xs">Обновление не чаще раза в 15 минут. При проверке робота источник останавливается и получает паузу. Поиск запускается нажатием кнопки.</p>
    {pending && <p role="status">Читаем поисковики… Это может занять до полутора минут. Не каждый источник обязательно выполнит переход до общего тайм-аута.</p>}
    {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
    {result && <CaptchaAssist key={result.report.run_id} request={request} result={result} onVerified={() => load("refresh")} />}
    {result && <SupplierSerpReportView result={result} renderPage={(engine, link) => <SupplierPage
      key={`${result.report.run_id}:${engine}:${link.rank}`} request={{ position: request,
        serp_run_id: result.report.run_id, engine, rank: link.rank }} link={link} />} />}
  </section>;
}
