import type { Metadata } from "next";
import Link from "next/link";

import {
  loadDocumentSearch,
  type DocumentSearchHit,
  type DocumentSearchResult,
  type SearchSourceKind,
} from "@/lib/procurement-api";

export const metadata: Metadata = {
  title: "Поиск по документам — Tendox",
  description: "Tenant-scoped поиск по доказательствам из документов закупки",
};

const sourceLabels: Record<SearchSourceKind, string> = {
  TITLE: "найдено в названии",
  FILENAME: "найдено в имени файла",
  NATIVE_TEXT: "найдено в тексте",
  VISION_TAG: "найдено на чертеже",
  MODEL_BRAND_CATALOG: "найдено по точной модели",
};

const extractorLabels: Record<string, string> = {
  native_pdf: "нативный PDF",
  native_docx: "нативный DOCX",
  native_xlsx: "нативный XLSX",
  llm: "vision-модель",
  manual: "ручное подтверждение",
};

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function excerpt(value: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > 320 ? `${compact.slice(0, 317)}…` : compact;
}

function displayName(result: DocumentSearchResult): string {
  const hit = result.hits.find(({ source_kind }) => source_kind === "TITLE")
    ?? result.hits.find(({ source_kind }) => source_kind === "FILENAME");
  return hit ? excerpt(hit.matched_text) : `Документ ${result.document_id}`;
}

function Hit({ hit }: { hit: DocumentSearchHit }) {
  const isUnknown = hit.status === "UNKNOWN";
  return (
    <li className="rounded-xl border border-slate-200 bg-slate-50/80 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-extrabold text-blue-800">
          {sourceLabels[hit.source_kind]}
        </span>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-black ${
            isUnknown ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-800"
          }`}
        >
          {hit.status}
        </span>
        {hit.vision_review_status === "AI_SUGGESTED" && (
          <span className="text-xs font-bold text-amber-800">AI-тег, не подтверждён человеком</span>
        )}
        {hit.vision_review_status === "HUMAN_CONFIRMED" && (
          <span className="text-xs font-bold text-emerald-800">подтверждено человеком</span>
        )}
      </div>
      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">
        {excerpt(hit.matched_text)}
      </p>
      <dl className="mt-3 grid gap-1 border-t border-slate-200 pt-3 text-xs text-slate-600 sm:grid-cols-2">
        <div><dt className="inline font-bold text-slate-800">Источник: </dt><dd className="inline">{hit.provenance.document_id}</dd></div>
        <div><dt className="inline font-bold text-slate-800">Место: </dt><dd className="inline">{hit.provenance.locator}</dd></div>
        <div><dt className="inline font-bold text-slate-800">Извлечение: </dt><dd className="inline">{extractorLabels[hit.provenance.extractor ?? ""] ?? hit.provenance.extractor ?? "не указано"}</dd></div>
        <div><dt className="inline font-bold text-slate-800">Уверенность: </dt><dd className="inline">{hit.provenance.confidence == null ? "не указана" : `${Math.round(hit.provenance.confidence * 100)}%`}</dd></div>
      </dl>
      {hit.vision_evidence && (
        <p className="mt-2 text-xs text-slate-600">
          Vision evidence: {hit.vision_evidence.producer} · {hit.vision_evidence.model}
          {hit.vision_evidence.reviewed_by ? ` · проверил ${hit.vision_evidence.reviewed_by}` : ""}
        </p>
      )}
      {hit.model_brand_evidence && (
        <div className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-950">
          <p className="m-0 font-extrabold">
            {hit.model_brand_evidence.model} → {hit.model_brand_evidence.brand}
          </p>
          <p className="mt-1 text-indigo-800">
            Reviewed catalog: {hit.model_brand_evidence.catalog_id} · источник модели: {sourceLabels[hit.model_brand_evidence.model_source_kind]}
          </p>
          {hit.model_brand_evidence.catalog_entries.map((entry, index) => (
            <p className="mt-1 break-words text-indigo-800" key={`${entry.evidence.source_url}:${index}`}>
              Официальный источник: {entry.evidence.source_title} · {entry.evidence.locator}
              {entry.evidence.source_artifact_id ? ` · артефакт ${entry.evidence.source_artifact_id}` : ""}
              {` · SHA-256 ${entry.evidence.source_document_sha256}`}
            </p>
          ))}
        </div>
      )}
    </li>
  );
}

export default async function DocumentSearchPage({ searchParams }: PageProps<"/document-search">) {
  const query = first((await searchParams).query).trim();
  const data = query ? await loadDocumentSearch(query) : { page: null };
  const results = data.page?.results ?? [];

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1100px,calc(100%-1rem))] py-6 sm:w-[min(1100px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S4 · поиск по evidence</p>
          <div className="mt-2 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="m-0 text-3xl font-black tracking-tight sm:text-5xl">Поиск по документам</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
                Ищет только в последних индексах документов текущей компании. Совпадение помогает найти источник, но не означает соответствие требованиям или решение об участии.
              </p>
            </div>
            <nav aria-label="Разделы пилота" className="flex flex-wrap gap-4 text-sm font-bold">
              <Link className="text-blue-700 hover:underline" href="/">Дела</Link>
              <Link className="text-blue-700 hover:underline" href="/ocr-review">Проверка OCR</Link>
              <Link className="text-blue-700 hover:underline" href="/completeness-review">Проверка полноты</Link>
            </nav>
          </div>
        </header>

        <form className="mt-7 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:flex-row" method="get">
          <label className="sr-only" htmlFor="document-query">Запрос по документам</label>
          <input
            autoComplete="off"
            className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-base outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
            defaultValue={query}
            id="document-query"
            maxLength={200}
            name="query"
            placeholder="Например: кондиционирование или GW-G140W/N1D3"
            required
          />
          <button className="rounded-xl bg-slate-900 px-6 py-3 font-extrabold text-white hover:bg-blue-800" type="submit">Найти</button>
        </form>

        {data.error && (
          <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-900" role="alert">
            {data.error === "configuration"
              ? "Не настроено серверное подключение к API. Проверьте PROCUREMENT_API_URL и PROCUREMENT_API_TOKEN."
              : data.error === "validation"
                ? "Введите от 1 до 200 символов с буквами или цифрами."
                : "Поиск временно недоступен. Проверьте, что FastAPI запущен, и повторите запрос."}
          </p>
        )}

        {!query && (
          <section className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center text-slate-600">
            Введите название, имя файла, фразу из текста или обозначение на чертеже.
          </section>
        )}

        {query && !data.error && (
          <section className="mt-7" aria-live="polite">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="m-0 text-xs font-black uppercase tracking-[.14em] text-blue-700">Результат</p>
                <h2 className="mt-1 text-2xl font-black">«{data.page?.query ?? query}»</h2>
              </div>
              <span className="text-sm font-bold text-slate-600">{results.length} документов</span>
            </div>
            {results.length ? (
              <div className="mt-4 grid gap-4">
                {results.map((result) => (
                  <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={result.document_id}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="m-0 break-all text-xs font-bold text-blue-700">{result.document_id}</p>
                        <h3 className="mt-1 text-lg font-black">{displayName(result)}</h3>
                      </div>
                      <span className={`rounded-full px-3 py-1 text-xs font-black ${result.status === "PASS" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-900"}`}>{result.status}</span>
                    </div>
                    <ul className="mt-4 grid gap-3 p-0" aria-label="Доказательства совпадения">
                      {result.hits.map((hit, index) => <Hit hit={hit} key={`${hit.source_kind}:${hit.provenance.locator}:${index}`} />)}
                    </ul>
                  </article>
                ))}
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center">
                <strong>Совпадений нет.</strong>
                <p className="mt-2 text-sm text-slate-600">Проверьте формулировку или убедитесь, что для документа сохранён поисковый индекс.</p>
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
