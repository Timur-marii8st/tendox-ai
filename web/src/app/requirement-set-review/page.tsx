import type { Metadata } from "next";
import Link from "next/link";

import { RequirementSetReviewForm } from "./decision-form";
import {
  ApiError,
  ConfigurationError,
  loadReviewedRequirementSetForReview,
  type ReviewedRequirementSetDecision,
  type ReviewedRequirementSetRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Проверка набора требований — Tendox",
  description: "Независимое exact-digest review полного набора строк ТЗ",
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

function stamp(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроен PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет доступа к exact requirement set.";
    if (error.status === 404) return "Exact requirement set не найден в текущем tenant.";
  }
  return "Requirement set временно недоступен.";
}

function Decision({ decision }: { decision: ReviewedRequirementSetDecision }) {
  const tone = decision.status === "PASS"
    ? "border-emerald-200 bg-emerald-50 text-emerald-950"
    : decision.status === "FAIL"
      ? "border-red-200 bg-red-50 text-red-950"
      : "border-amber-200 bg-amber-50 text-amber-950";
  return (
    <section className={`mt-6 rounded-2xl border p-5 ${tone}`}>
      <h2 className="m-0 text-xl font-black">Сохранённое решение: {decision.status}</h2>
      <p className="mt-3 text-sm">Coverage: <strong>{decision.coverage_assessment}</strong> · normalization: <strong>{decision.normalization_assessment}</strong></p>
      <p className="text-sm">Reviewer: {decision.reviewed_by} · {stamp(decision.reviewed_at)}</p>
      <p className="whitespace-pre-wrap text-sm">{decision.reason}</p>
      <p className="mb-0 break-all font-mono text-xs">Decision SHA-256: {decision.decision_sha256}</p>
      <p className="mb-0 mt-3 text-sm">Manual ordinals: {decision.manual_review_entry_ordinals.length ? decision.manual_review_entry_ordinals.join(", ") : "нет"}</p>
    </section>
  );
}

function Proposal({ record }: { record: ReviewedRequirementSetRecord }) {
  const proposal = record.proposal;
  return (
    <>
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="m-0 text-xl font-black">Exact proposal</h2>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="font-bold text-slate-500">Set ID</dt><dd className="m-0 break-all">{proposal.set_id}</dd></div>
          <div><dt className="font-bold text-slate-500">Подготовил</dt><dd className="m-0">{proposal.prepared_by} · {stamp(proposal.prepared_at)}</dd></div>
          <div><dt className="font-bold text-slate-500">Source document</dt><dd className="m-0 break-all">{proposal.source_document_id}</dd></div>
          <div><dt className="font-bold text-slate-500">Строки</dt><dd className="m-0">{proposal.entries.length} / {proposal.expected_entry_count}</dd></div>
        </dl>
        <p className="mt-4 whitespace-pre-wrap text-sm"><strong>Declared scope:</strong> {proposal.declared_scope}</p>
        <p className="break-all font-mono text-xs text-slate-600">Source SHA-256: {proposal.source_document_sha256}</p>
        <p className="mb-0 break-all font-mono text-xs text-slate-600">Proposal SHA-256: {proposal.proposal_sha256}</p>
      </section>
      <section className="mt-6">
        <h2 className="text-xl font-black">Все строки proposal</h2>
        <ol className="grid gap-3 p-0">
          {proposal.entries.map((entry) => (
            <li className="list-none rounded-xl border border-slate-200 bg-white p-4" key={entry.ordinal}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="m-0 text-xs font-black uppercase tracking-wide text-slate-500">Строка {entry.ordinal}</p>
                  <h3 className="mb-0 mt-1 text-base font-black">{entry.raw_name}</h3>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-black ${entry.disposition === "EXECUTABLE" ? "bg-blue-100 text-blue-900" : "bg-amber-100 text-amber-950"}`}>{entry.disposition}</span>
              </div>
              <p className="whitespace-pre-wrap text-sm"><strong>Исходное значение:</strong> {entry.raw_value}</p>
              {entry.requirement && (
                <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
                  <strong>{entry.requirement.property}</strong> {entry.requirement.operator} {entry.requirement.value === null ? "" : Array.isArray(entry.requirement.value) ? entry.requirement.value.join("…") : String(entry.requirement.value)} {entry.requirement.unit ?? ""} · {entry.requirement.mandatory ? "mandatory" : "desirable"}
                </p>
              )}
              <p className="text-sm text-slate-700"><strong>Основание:</strong> {entry.review_note}</p>
              <p className="mb-0 break-all font-mono text-xs text-slate-500">{entry.provenance.document_id} · {entry.provenance.locator}</p>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

export default async function RequirementSetReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ set_id?: string | string[] }>;
}) {
  const requested = (await searchParams).set_id;
  const setId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ReviewedRequirementSetRecord | null = null;
  let error: string | null = null;
  if (setId) {
    try {
      record = await loadReviewedRequirementSetForReview(setId);
    } catch (caught) {
      error = failure(caught);
    }
  }
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1120px,calc(100%-1rem))] py-6 sm:w-[min(1120px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S85 · independent reviewer</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Проверка набора требований</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Открывается только явно указанный set_id. Reviewer видит все source rows, typed-нормализацию, manual scope и exact proposal digest; очереди и latest selection нет.</p>
          <nav aria-label="Разделы пилота" className="mt-4 flex flex-wrap gap-4 text-sm font-bold"><Link className="text-blue-700 hover:underline" href="/">Дела</Link><Link className="text-blue-700 hover:underline" href="/document-set-review">Проверка комплекта</Link></nav>
        </header>
        <aside className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">Маршрут использует только server-only <code>PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN</code> роли <code>COMPLETENESS_REVIEWER</code>. Fallback на operator token отсутствует.</aside>
        {!setId && (
          <form action="/requirement-set-review" className="mt-6 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-end" method="get">
            <label className="grid flex-1 gap-1 text-sm font-bold">Exact set ID<input className="rounded-lg border border-slate-300 p-2 font-mono" name="set_id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label>
            <button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white" type="submit">Открыть proposal</button>
          </form>
        )}
        {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-900" role="alert">{error}</p>}
        {record && !error && <><Proposal record={record} />{record.decision ? <Decision decision={record.decision} /> : <RequirementSetReviewForm record={record} />}</>}
      </div>
    </main>
  );
}
