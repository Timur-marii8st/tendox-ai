import type { Metadata } from "next";
import { randomUUID } from "node:crypto";
import Link from "next/link";

import {
  listManufacturerSearches,
  readManufacturerDossier,
  readManufacturerSearch,
} from "@/lib/procurement-api";
import type { ManufacturerCandidate, ManufacturerDossier, ManufacturerSearchReport, ManufacturerSearchSummary } from "@/lib/manufacturer-search";

import { ManufacturerSearchForm } from "./form";
import { ReviewedManufacturers } from "./directory";

export const metadata: Metadata = { title: "Поиск производителей ЕАЭС — Tendox" };

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function stamp(value: string | null): string { return value ? new Date(value).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) : "не завершён"; }
function reason(report: ManufacturerSearchReport): string {
  if (report.status === "COMPLETED") return "Ответ реестра сохранён и прочитан сервером.";
  if (report.status === "SOURCE_ERROR") return "Реестр не ответил или изменил формат. Результат неизвестен.";
  return "Исход реестра пока неизвестен.";
}
function CandidateCard({ candidate, dossier, selected }: { candidate: ManufacturerCandidate; dossier: ManufacturerDossier | null; selected: boolean }) {
  return <article className="rounded-xl border border-slate-200 bg-slate-50 p-4">
    <h3 className="m-0 text-base font-black"><a className="text-blue-700 underline" href={candidate.record_url} rel="noopener noreferrer" target="_blank">{candidate.product_name}</a></h3>
    <p className="mb-0 mt-2 text-sm"><strong>Изготовитель, заявленный источником:</strong> {candidate.manufacturer_name}</p>
    <dl className="mt-3 grid gap-2 text-xs text-slate-700 sm:grid-cols-2">
      <div><dt className="font-bold">Реестровый номер</dt><dd className="break-all">{candidate.registry_number}</dd></div>
      <div><dt className="font-bold">Запись источника</dt><dd>{candidate.source_record_index}</dd></div>
      <div><dt className="font-bold">Срок документа</dt><dd>{candidate.document_expires_on ?? "не указан"}</dd></div>
      <div><dt className="font-bold">Статус документа</dt><dd>{candidate.document_validity} · {candidate.document_validity_reason}</dd></div>
    </dl>
    <p className="mb-0 mt-3 text-xs text-amber-900">Роль — заявление источника о производителе; юридическое лицо, сайт, продавец, бренд, техническое соответствие и КП: UNKNOWN.</p>
    {dossier && <details className="mt-3 text-xs text-slate-600"><summary>Сохранённые данные источника</summary>
      <p className="break-all">Ответ SHA-256: {dossier.provenance.response_sha256} · запись {dossier.provenance.source_record_index} · проверено из сохранённого ответа: да.</p>
      <ul className="break-all pl-5">{Object.entries(dossier.provenance.field_locators).map(([field, locator]) => <li key={field}>{field}: {locator}</li>)}</ul>
    </details>}
    {dossier && <Link className="mt-3 inline-block text-xs font-bold text-blue-700 underline" href={`/manufacturer-review?run=${encodeURIComponent(dossier.run_id)}&record=${encodeURIComponent(dossier.candidate.record_id)}`}>Проверить изготовителя по документам</Link>}
    {selected && !dossier && <p className="mb-0 mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-900" role="alert">Сохранённые данные выбранной записи сейчас недоступны.</p>}
  </article>;
}
function Report({ report, dossier, selectedRecordId }: { report: ManufacturerSearchReport; dossier: ManufacturerDossier | null; selectedRecordId: string | null }) {
  return <section className="mt-6 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap justify-between gap-3 border-b border-slate-200 pb-4"><div><p className="m-0 text-xs font-black uppercase tracking-[.14em] text-blue-700">Persisted EAEU PRODUCTS</p><h2 className="mt-1 text-xl font-black">{report.query}</h2></div><span className="h-fit rounded-full bg-amber-100 px-3 py-1 text-xs font-black text-amber-900">{report.status}</span></div>
    <p className="mt-4 text-sm">{reason(report)} Найдено: {report.matched_count ?? "UNKNOWN"}; показано: {report.candidates.length}.</p>
    <dl className="grid gap-3 text-xs text-slate-600 sm:grid-cols-2"><div><dt className="font-bold">Создан</dt><dd>{stamp(report.created_at)}</dd></div><div><dt className="font-bold">Завершён</dt><dd>{stamp(report.finished_at)}</dd></div><div className="sm:col-span-2"><dt className="font-bold">Источник</dt><dd>Официальная коллекция ЕАЭС; адрес запроса сохранён в snapshot.</dd></div><div><dt className="font-bold">SHA-256 запроса</dt><dd className="break-all font-mono">{report.request_sha256}</dd></div><div><dt className="font-bold">SHA-256 ответа</dt><dd className="break-all font-mono">{report.response_sha256 ?? "не получен"}</dd></div><div><dt className="font-bold">Размер ответа</dt><dd>{report.response_byte_size ?? "не получен"}</dd></div><div><dt className="font-bold">Причина</dt><dd>{report.reason_code}</dd></div></dl>
    <div className="mt-5 grid gap-3">{report.candidates.length ? report.candidates.map((candidate) => <div key={candidate.record_id}><CandidateCard candidate={candidate} dossier={candidate.record_id === selectedRecordId ? dossier : null} selected={candidate.record_id === selectedRecordId} /><Link className="mt-2 inline-block text-xs font-bold text-blue-700 underline" href={`/manufacturer-search?run=${encodeURIComponent(report.run_id)}&record=${encodeURIComponent(candidate.record_id)}`}>Показать сохранённые данные этой записи</Link></div>) : <p className="m-0 text-sm text-slate-600">Кандидаты не сохранены. Отсутствие записей не доказывает отсутствие производителей.</p>}</div>
    <ReviewedManufacturers runId={report.run_id} responseSha={report.response_sha256} />
  </section>;
}

export default async function ManufacturerSearchPage({ searchParams }: { searchParams: Promise<{ run?: string | string[]; record?: string | string[] }> }) {
  let summaries: ManufacturerSearchSummary[] = [];
  let unavailable = false;
  try { summaries = await listManufacturerSearches(); } catch { unavailable = true; }
  const params = await searchParams;
  const requested = params.run;
  const malformedRun = requested !== undefined && (typeof requested !== "string" || !RUN_ID.test(requested));
  const selectedId = malformedRun ? null : typeof requested === "string" ? requested : summaries[0]?.run_id;
  const requestedRecord = params.record;
  const selectedRecordId = typeof requestedRecord === "string" && /^[0-9a-f]{24}$/.test(requestedRecord) ? requestedRecord : null;
  const detail = selectedId ? await (async () => {
    try {
      const report = await readManufacturerSearch(selectedId);
      const dossier = selectedRecordId && report.response_sha256
        ? await readManufacturerDossier(report.run_id, selectedRecordId)
        : null;
      if (dossier && dossier.provenance.response_sha256 !== report.response_sha256) throw new Error("dossier digest mismatch");
      return { report, dossier, unavailable: false };
    } catch { return { report: null, dossier: null, unavailable: true }; }
  })() : { report: null, dossier: null, unavailable: false };
  return <main className="min-h-screen bg-slate-50 p-5 text-slate-950 sm:p-10"><div className="mx-auto max-w-6xl"><header className="border-b border-slate-200 pb-6"><p className="text-xs font-black uppercase tracking-widest text-blue-700">Поиск производителей</p><h1 className="text-3xl font-black">Реестр промышленной продукции ЕАЭС</h1><p className="max-w-3xl text-sm leading-6 text-slate-600">Сохраняется точный ответ официального источника. Указанный изготовитель — заявление реестра, а не проверенное юридическое лицо, технический допуск или коммерческое предложение.</p><nav className="flex flex-wrap gap-4 text-sm font-bold"><Link className="text-blue-700 hover:underline" href="/">Дела</Link><Link className="text-blue-700 hover:underline" href="/supplier-discovery">Источники снабжения</Link></nav></header><aside className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">Источник: <a className="underline" href="https://goszakupki.eaeunion.org/erpt/ru/registers/products/list" rel="noopener noreferrer" target="_blank">официальный реестр ЕАЭС</a>. Сам ответ реестра не подтверждает действительность записи, связь юридического лица с товаром, наличие, цену или КП. Независимые проверки показаны отдельно ниже. `UNKNOWN` остаётся `UNKNOWN`; просроченный документ показан как `FAIL`.</aside><ManufacturerSearchForm commandId={randomUUID()} />{unavailable && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">Сохранённые поиски временно недоступны.</p>}{malformedRun && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">Идентификатор выбранного поиска некорректен.</p>}{!unavailable && !malformedRun && summaries.length === 0 && <p className="mt-6 rounded-xl border border-dashed border-slate-300 bg-white p-8 text-sm text-slate-600">В текущем tenant ещё нет сохранённых поисков.</p>}{!unavailable && !malformedRun && summaries.length > 0 && <div className="mt-6 grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]"><aside className="grid content-start gap-3" aria-label="Сохранённые поиски">{summaries.map((summary) => <Link className={`rounded-xl border p-3 text-sm ${summary.run_id === selectedId ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white"}`} href={`/manufacturer-search?run=${encodeURIComponent(summary.run_id)}`} key={summary.run_id}><strong className="block break-all">{summary.query}</strong><span className="mt-1 block text-xs text-slate-600">{summary.status} · {stamp(summary.created_at)}</span><span className="mt-1 block text-xs text-slate-600">Кандидатов: {summary.candidate_count}; найдено: {summary.matched_count ?? "UNKNOWN"}</span></Link>)}</aside>{detail.unavailable || !detail.report ? <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">Сохранённые данные выбранного поиска временно недоступны.</p> : <Report dossier={detail.dossier} report={detail.report} selectedRecordId={selectedRecordId} />}</div>}</div></main>;
}
