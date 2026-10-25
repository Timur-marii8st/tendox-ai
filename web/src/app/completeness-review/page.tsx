import type { Metadata } from "next";
import Link from "next/link";

import { CompletenessDecisionForm } from "./decision-form";
import {
  loadCompletenessReviews,
  type CompletenessReview,
  type Provenance,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Проверка полноты требований — Tendox",
  description: "Внутренняя проверка полноты извлечения требований по immutable snapshot",
};

function stamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "время не передано API"
    : new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function ProvenanceLine({ value }: { value: Provenance | null }) {
  if (!value) return <p className="m-0 text-xs text-slate-500">Provenance не передан API.</p>;
  return (
    <p className="m-0 break-words text-xs leading-5 text-slate-600">
      <strong className="text-slate-800">Источник:</strong> {value.document_id || "не указан"}
      {" · "}<strong className="text-slate-800">место:</strong> {value.locator || "не указано"}
      {value.extractor ? ` · извлечение: ${value.extractor}` : ""}
      {value.confidence == null ? "" : ` · confidence: ${Math.round(value.confidence * 100)}%`}
    </p>
  );
}

function StatusBadge({ value }: { value: string }) {
  const palette = value === "PASS"
    ? "bg-emerald-100 text-emerald-800"
    : value === "FAIL"
      ? "bg-red-100 text-red-800"
      : "bg-amber-100 text-amber-900";
  return <span className={`rounded-full px-2.5 py-1 text-xs font-black ${palette}`}>{value || "UNKNOWN"}</span>;
}

function TerminalDecision({ review }: { review: CompletenessReview }) {
  const decision = review.decision;
  if (!decision) return null;
  return (
    <section className="mt-5 rounded-xl border border-slate-300 bg-slate-100 p-4" aria-label="Терминальное решение">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="m-0 text-base font-black">Терминальное решение — только чтение</h3>
        <StatusBadge value={decision.status} />
      </div>
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="inline font-bold">Reviewer: </dt><dd className="inline break-words">{decision.reviewer_id || "не передан API"}</dd></div>
        <div><dt className="inline font-bold">Время: </dt><dd className="inline">{stamp(decision.reviewed_at)}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Evidence SHA-256</dt><dd className="mt-1 break-all font-mono text-xs">{decision.evidence_sha256 || "не передан API"}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Scope</dt><dd className="mt-1 whitespace-pre-wrap break-words">{decision.scope || "не передан API"}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Основание</dt><dd className="mt-1 whitespace-pre-wrap break-words">{decision.reason || "не передано API"}</dd></div>
      </dl>
    </section>
  );
}

function ReviewCard({ review }: { review: CompletenessReview }) {
  const { snapshot } = review;
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="m-0 text-xs font-black uppercase tracking-[.14em] text-blue-700">Immutable snapshot</p>
          <h2 className="mt-1 break-words text-xl font-black">{snapshot.source.filename || "Имя файла не передано API"}</h2>
          <p className="mb-0 mt-1 break-all text-xs text-slate-600">review {review.review_id || "не передан API"}</p>
        </div>
        <StatusBadge value={review.decision?.status ?? snapshot.extraction.status} />
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="font-bold text-slate-800">Document ID</dt><dd className="mt-1 break-all text-slate-600">{snapshot.source.document_id || "не передан API"}</dd></div>
        <div><dt className="font-bold text-slate-800">Роль</dt><dd className="mt-1 break-words text-slate-600">{snapshot.source.role || "не передана API"}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold text-slate-800">Source SHA-256</dt><dd className="mt-1 break-all font-mono text-xs text-slate-600">{snapshot.source.sha256 || "не передан API"}</dd></div>
        <div className="sm:col-span-2 lg:col-span-4"><dt className="font-bold text-slate-800">Evidence SHA-256</dt><dd className="mt-1 break-all font-mono text-xs text-slate-600">{snapshot.evidence_sha256 || "не передан API"}</dd></div>
      </dl>

      <section className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="m-0 text-base font-black">Извлечение</h3>
          <StatusBadge value={snapshot.extraction.status} />
        </div>
        {snapshot.extraction.reasons.length ? (
          <ul className="mb-0 mt-3 grid gap-1 pl-5 text-sm leading-6 text-slate-700">
            {snapshot.extraction.reasons.map((reason, index) => <li key={`${reason}:${index}`}>{reason}</li>)}
          </ul>
        ) : <p className="mb-0 mt-2 text-sm text-slate-600">Причины извлечения не переданы API.</p>}
      </section>

      <section className="mt-5">
        <h3 className="m-0 text-base font-black">Сопоставленные требования</h3>
        {snapshot.mapped_requirements.length ? (
          <ul className="mt-3 grid gap-3 p-0">
            {snapshot.mapped_requirements.map((requirement, index) => (
              <li className="rounded-xl border border-slate-200 bg-slate-50 p-3" key={`${requirement.requirement_id}:${index}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong className="break-words text-sm">{requirement.requirement_id}</strong>
                  <StatusBadge value={requirement.status} />
                </div>
                <p className="mb-2 mt-2 whitespace-pre-wrap break-words text-sm leading-6">{requirement.text || "Текст требования не передан API."}</p>
                <ProvenanceLine value={requirement.provenance} />
              </li>
            ))}
          </ul>
        ) : <p className="mb-0 mt-2 text-sm text-slate-600">Сопоставленные требования отсутствуют.</p>}
      </section>

      <section className="mt-5">
        <h3 className="m-0 text-base font-black">Непокрытые блоки</h3>
        {snapshot.unmapped_blocks.length ? (
          <ul className="mt-3 grid gap-3 p-0">
            {snapshot.unmapped_blocks.map((block) => (
              <li className="rounded-xl border border-amber-200 bg-amber-50/60 p-3" key={block.block_index}>
                <p className="m-0 text-xs font-black text-amber-900">Блок #{block.block_index + 1}{block.reason ? ` · ${block.reason}` : ""}</p>
                <p className="mb-2 mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{block.text || "Текст блока не передан API."}</p>
                <ProvenanceLine value={block.provenance} />
              </li>
            ))}
          </ul>
        ) : <p className="mb-0 mt-2 text-sm text-slate-600">Непокрытых блоков API не вернул.</p>}
      </section>

      {review.decision ? <TerminalDecision review={review} /> : (
        <CompletenessDecisionForm
          evidenceSha256={snapshot.evidence_sha256}
          reviewId={review.review_id}
          unmappedBlocks={snapshot.unmapped_blocks}
        />
      )}
    </article>
  );
}

export default async function CompletenessReviewPage() {
  const data = await loadCompletenessReviews();
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1180px,calc(100%-1rem))] py-6 sm:w-[min(1180px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S4 · reviewer workflow</p>
          <div className="mt-2 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="m-0 text-3xl font-black tracking-tight sm:text-5xl">Проверка полноты требований</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                Полнота не выводится из числа найденных требований. Решение привязывается к exact evidence SHA-256 и всем рассмотренным непокрытым блокам.
              </p>
            </div>
            <nav aria-label="Разделы пилота" className="flex flex-wrap gap-4 text-sm font-bold">
              <Link className="text-blue-700 hover:underline" href="/">Дела</Link>
              <Link className="text-blue-700 hover:underline" href="/document-search">Поиск документов</Link>
              <Link className="text-blue-700 hover:underline" href="/ocr-review">Проверка OCR</Link>
            </nav>
          </div>
        </header>

        <aside className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
          <strong>Deployment boundary.</strong> Этот экран разворачивается только во внутреннем reviewer deployment с одним server-only <code>PROCUREMENT_API_TOKEN</code> роли <code>COMPLETENESS_REVIEWER</code>. URL API и bearer не передаются браузеру; второй token и выбор credentials в интерфейсе отсутствуют.
        </aside>

        {data.error && (
          <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-900" role="alert">
            {data.error === "configuration"
              ? "Серверное подключение к API не настроено. Проверьте PROCUREMENT_API_URL и PROCUREMENT_API_TOKEN в reviewer deployment."
              : "Очередь completeness review временно недоступна. Проверьте API и повторите запрос."}
          </p>
        )}

        {!data.error && (data.reviews.length ? (
          <section className="mt-6 grid gap-5" aria-label="Очередь completeness review">
            {data.reviews.map((review) => <ReviewCard key={review.review_id} review={review} />)}
          </section>
        ) : (
          <section className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-10 text-center text-slate-600">
            В текущем tenant нет completeness review, доступных этой роли.
          </section>
        ))}
      </div>
    </main>
  );
}
