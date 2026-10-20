import type { Metadata } from "next";
import Link from "next/link";

import { ServerOfferReviewForm } from "./decision-form";
import {
  ApiError,
  ConfigurationError,
  loadServerOfferReview,
  type ServerOfferReviewDecision,
  type ServerOfferReviewRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Проверка серверного предложения — Syurai Procurement",
  description: "Независимое exact-digest review BOM, КП и каждой строки требований",
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const stamp = (value: string) => new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроен PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли COMPLETENESS_REVIEWER.";
    if (error.status === 404) return "Exact offer proposal не найден в текущем tenant.";
    if (error.status === 422) return "Stored evidence не прошло exact-integrity проверку.";
  }
  return "Предложение временно недоступно.";
}

function Decision({ decision }: { decision: ServerOfferReviewDecision }) {
  const tone = decision.status === "PASS" ? "border-emerald-200 bg-emerald-50 text-emerald-950"
    : decision.status === "FAIL" ? "border-red-200 bg-red-50 text-red-950"
      : "border-amber-200 bg-amber-50 text-amber-950";
  return <section className={`mt-6 rounded-2xl border p-5 ${tone}`}>
    <h2 className="m-0 text-xl font-black">Сохранённое решение: {decision.status}</h2>
    <p className="mt-3 text-sm">Quote gate: <strong>{decision.quote_gate_status}</strong> · {decision.quote_gate_reason}</p>
    <p className="text-sm">BOM: <strong>{decision.bom_scope_assessment}</strong> · terms: <strong>{decision.commercial_terms_assessment}</strong></p>
    <p className="text-sm">Reviewer: {decision.reviewed_by} · {stamp(decision.reviewed_at)}</p>
    <p className="whitespace-pre-wrap text-sm">{decision.reason}</p>
    <ol className="grid gap-2 p-0">{decision.requirement_decisions.map((row) =>
      <li className="list-none rounded-lg border border-current/20 bg-white/60 p-3 text-sm" key={row.requirement_ordinal}>
        <strong>Строка {row.requirement_ordinal}: {row.status}</strong> · {row.reason}<br />
        <span className="text-xs">Evidence: {row.evidence.length ? row.evidence.map((ref) => ref.kind === "BOM_LINE" ? `BOM ${ref.bom_line_ordinal}` : "commercial terms").join(", ") : "нет"}</span>
      </li>)}</ol>
    <p className="mb-0 break-all font-mono text-xs">Decision SHA-256: {decision.decision_sha256}</p>
  </section>;
}

function Evidence({ record }: { record: ServerOfferReviewRecord }) {
  const offer = record.evidence.proposal;
  const set = record.evidence.requirement_set.proposal;
  const terms = offer.commercial_terms;
  return <>
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="m-0 text-xl font-black">Exact offer и КП</h2>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="font-bold text-slate-500">Offer</dt><dd className="m-0 break-all">{offer.offer_id}</dd></div>
        <div><dt className="font-bold text-slate-500">Подготовил</dt><dd className="m-0">{offer.prepared_by} · {stamp(offer.prepared_at)}</dd></div>
        <div><dt className="font-bold text-slate-500">Lead</dt><dd className="m-0">{offer.lead_product_name}</dd></div>
        <div><dt className="font-bold text-slate-500">КП</dt><dd className="m-0">{terms.quote_number} · {terms.supplier_name}</dd></div>
        <div><dt className="font-bold text-slate-500">Цена без НДС</dt><dd className="m-0">{terms.amount_ex_vat} {terms.currency}</dd></div>
        <div><dt className="font-bold text-slate-500">Срок</dt><dd className="m-0">{stamp(terms.issued_at)} — {stamp(terms.valid_until)}</dd></div>
      </dl>
      <p className="text-sm">Scope: <strong>{String(terms.covers_full_scope)}</strong> · НДС: <strong>{terms.nds_rate ?? "UNKNOWN"}</strong></p>
      <p className="text-sm">Наличие: {terms.availability_terms ?? "UNKNOWN"}<br />Поставка: {terms.delivery_terms ?? "UNKNOWN"}<br />Оплата: {terms.payment_terms ?? "UNKNOWN"}</p>
      <p className="break-all font-mono text-xs text-slate-500">Terms evidence: {terms.provenance.document_id} · {terms.provenance.locator}</p>
      <p className="mb-0 break-all font-mono text-xs text-slate-500">Proposal SHA-256: {offer.proposal_sha256}</p>
    </section>
    <section className="mt-6"><h2 className="text-xl font-black">BOM — {offer.bom_lines.length} строк</h2>
      <ol className="grid gap-3 p-0">{offer.bom_lines.map((line) => <li className="list-none rounded-xl border border-slate-200 bg-white p-4" key={line.ordinal}>
        <p className="m-0 text-xs font-black text-slate-500">BOM {line.ordinal} · {line.kind}</p><h3 className="mb-1 mt-1 text-base font-black">{line.manufacturer ?? "—"} {line.sku}</h3>
        <p className="text-sm">{line.description} · {line.quantity} {line.unit} · сумма {line.line_total_ex_vat ?? "не выделена"}</p>
        <p className="mb-0 font-mono text-xs text-slate-500">{line.provenance.document_id} · {line.provenance.locator}</p>
      </li>)}</ol>
    </section>
    <section className="mt-6"><h2 className="text-xl font-black">Requirement set — {set.entries.length} строк</h2>
      <p className="break-all font-mono text-xs text-slate-500">Proposal {set.proposal_sha256} · decision {record.evidence.requirement_set.decision?.decision_sha256}</p>
      <ol className="grid gap-3 p-0">{set.entries.map((entry) => <li className="list-none rounded-xl border border-slate-200 bg-white p-4" key={entry.ordinal}>
        <p className="m-0 text-xs font-black text-slate-500">Требование {entry.ordinal} · {entry.disposition}</p><h3 className="mb-1 mt-1 text-base font-black">{entry.raw_name}</h3>
        <p className="text-sm">{entry.raw_value}</p><p className="mb-0 font-mono text-xs text-slate-500">{entry.provenance.document_id} · {entry.provenance.locator}</p>
      </li>)}</ol>
    </section>
  </>;
}

export default async function ServerOfferReviewPage({ searchParams }: { searchParams: Promise<{ offer_id?: string | string[] }> }) {
  const requested = (await searchParams).offer_id;
  const offerId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ServerOfferReviewRecord | null = null;
  let error: string | null = null;
  if (offerId) try { record = await loadServerOfferReview(offerId); } catch (caught) { error = failure(caught); }
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1120px,calc(100%-1rem))] py-6 sm:w-[min(1120px,calc(100%-2rem))] sm:py-10">
    <header className="border-b border-slate-200 pb-6"><p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S87 · independent exact review</p><h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Проверка серверного предложения</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Reviewer видит полный requirement set, BOM, КП и provenance. Каждый source row получает отдельный PASS, FAIL или UNKNOWN; итог вычисляет сервер.</p><nav className="mt-4 flex gap-4 text-sm font-bold"><Link className="text-blue-700 hover:underline" href="/">Дела</Link><Link className="text-blue-700 hover:underline" href="/server-offer-proposal">Создать proposal</Link></nav></header>
    <aside className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">Используется только server-only <code>PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN</code>. Latest selection и fallback на operator token отсутствуют.</aside>
    {!offerId && <form action="/server-offer-review" className="mt-6 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-end" method="get"><label className="grid flex-1 gap-1 text-sm font-bold">Exact offer ID<input className="rounded-lg border border-slate-300 p-2 font-mono" name="offer_id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label><button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white" type="submit">Открыть proposal</button></form>}
    {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-900" role="alert">{error}</p>}
    {record && !error && <><Evidence record={record} />{record.decision ? <><Decision decision={record.decision} />{record.decision.status === "PASS" && <p className="mt-4"><Link className="font-black text-blue-700 hover:underline" href={`/server-offer-economics?case_id=${encodeURIComponent(record.evidence.proposal.case_id)}&version=${record.evidence.proposal.case_version}&offer_id=${encodeURIComponent(record.evidence.proposal.offer_id)}`}>Открыть ввод трёх сценариев →</Link></p>}</> : <ServerOfferReviewForm record={record} />}</>}
  </div></main>;
}
