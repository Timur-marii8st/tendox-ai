import type { Metadata } from "next";
import Link from "next/link";

import { DocumentSetReviewForm } from "./decision-form";
import {
  ApiError,
  ConfigurationError,
  loadDocumentSetReviewDecision,
  loadDocumentSetReviewEvidence,
  type DocumentSetFinding,
  type DocumentSetReviewDecision,
  type DocumentSetReviewEvidence,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Проверка комплекта документов — Syurai Procurement",
  description: "Exact-evidence terminal review одного выбранного document-set manifest",
};

const MANIFEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

function Findings({ findings, title }: { findings: DocumentSetFinding[]; title: string }) {
  return (
    <section className="mt-6">
      <h3 className="m-0 text-base font-black">{title}</h3>
      {findings.length === 0 ? <p className="mt-2 text-sm text-slate-600">Нет findings.</p> : (
        <ul className="mt-3 grid gap-3 p-0">
          {findings.map((finding) => (
            <li className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm" key={finding.finding_id}>
              <p className="m-0 font-black">{finding.kind} · {finding.origin} · {finding.finding_id}</p>
              <p className="mb-0 mt-2 whitespace-pre-wrap break-words">{finding.rationale}</p>
              <ul className="mb-0 mt-2 grid gap-1 font-mono text-xs">
                {finding.evidence.map((reference, index) => (
                  <li key={`${finding.finding_id}:${index}`}>{reference.kind} · member #{reference.member_ordinal} · {reference.kind === "SOURCE_BLOCK" ? `block #${reference.extraction_block_index + 1}` : reference.field}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Evidence({ evidence }: { evidence: DocumentSetReviewEvidence }) {
  return (
    <article className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="m-0 text-xs font-black uppercase tracking-[.14em] text-blue-700">Exact persisted evidence</p>
      <h2 className="mt-1 break-all text-xl font-black">{evidence.manifest.manifest_id}</h2>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="font-bold">Scope</dt><dd className="whitespace-pre-wrap break-words">{evidence.manifest.scope}</dd></div>
        <div><dt className="font-bold">Manifest SHA-256</dt><dd className="break-all font-mono text-xs">{evidence.manifest.evidence_sha256}</dd></div>
      </dl>
      <div className="mt-6 grid gap-4">
        {evidence.constituents.map((constituent) => (
          <section className="rounded-xl border border-slate-200 bg-slate-50 p-4" key={constituent.member.ordinal}>
            <h3 className="m-0 text-base font-black">Member #{constituent.member.ordinal}</h3>
            <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
              <div><dt className="font-bold">Source document</dt><dd className="break-all">{constituent.member.source_document_id}</dd></div>
              <div><dt className="font-bold">Source SHA-256</dt><dd className="break-all font-mono text-xs">{constituent.member.source_document_sha256}</dd></div>
              <div><dt className="font-bold">Review</dt><dd className="break-all">{constituent.member.completeness_review_id}</dd></div>
              <div><dt className="font-bold">Review evidence</dt><dd className="break-all font-mono text-xs">{constituent.member.completeness_review_evidence_sha256}</dd></div>
              <div><dt className="font-bold">Constituent status</dt><dd>{constituent.review.decision?.status ?? "NO TERMINAL DECISION"}</dd></div>
              <div><dt className="font-bold">Decision SHA-256</dt><dd className="break-all font-mono text-xs">{constituent.decision_sha256 ?? "not available"}</dd></div>
            </dl>
            <p className="mb-0 mt-3 text-sm"><strong>Mapping:</strong> delivery deadline {constituent.review.snapshot.mapping.delivery_deadline ?? "UNKNOWN"}; equivalent allowed {constituent.review.snapshot.mapping.equivalent_allowed == null ? "UNKNOWN" : String(constituent.review.snapshot.mapping.equivalent_allowed)}.</p>
            <h4 className="mb-2 mt-4 text-sm font-black">Source blocks and provenance</h4>
            <ul className="grid gap-2 p-0">
              {constituent.review.snapshot.extraction.blocks.map((block, index) => (
                <li className="rounded-lg border border-slate-200 bg-white p-3" key={index}>
                  <p className="m-0 text-xs font-black text-slate-700">#{index + 1} · {block.provenance.document_id} · {block.provenance.locator} · {block.provenance.extractor ?? "extractor unknown"}</p>
                  <p className="mb-0 mt-1 whitespace-pre-wrap break-words text-sm leading-6">{block.text}</p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <Findings findings={evidence.server_findings} title="Server findings" />
    </article>
  );
}

function ReadOnlyDecision({ decision }: { decision: DocumentSetReviewDecision }) {
  return (
    <article className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
      <p className="m-0 text-xs font-black uppercase tracking-[.14em] text-emerald-800">Terminal decision · read-only</p>
      <h2 className="mt-1 text-xl font-black">{decision.status}</h2>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="font-bold">Reviewer</dt><dd>{decision.decided_by}</dd></div>
        <div><dt className="font-bold">Decided at</dt><dd>{decision.decided_at}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Decision SHA-256</dt><dd className="break-all font-mono text-xs">{decision.decision_sha256}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Reason</dt><dd className="whitespace-pre-wrap break-words">{decision.reason}</dd></div>
      </dl>
      <Findings findings={decision.findings} title="Persisted findings" />
    </article>
  );
}

function failureMessage(error: unknown): string {
  if (error instanceof ConfigurationError) return "Нужны PROCUREMENT_API_URL и dedicated reviewer token на сервере.";
  if (error instanceof ApiError && error.status === 404) return "Manifest недоступен в текущем tenant.";
  if (error instanceof ApiError && error.status === 403) return "Dedicated token не имеет роли COMPLETENESS_REVIEWER.";
  return "Exact review evidence временно недоступен.";
}

export default async function DocumentSetReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ manifest_id?: string | string[] }>;
}) {
  const requested = (await searchParams).manifest_id;
  const manifestId = typeof requested === "string" && MANIFEST_ID.test(requested) ? requested : null;
  let evidence: DocumentSetReviewEvidence | null = null;
  let decision: DocumentSetReviewDecision | null = null;
  let error: string | null = null;
  if (manifestId) {
    try {
      evidence = await loadDocumentSetReviewEvidence(manifestId);
      decision = await loadDocumentSetReviewDecision(manifestId);
    } catch (caught) {
      error = failureMessage(caught);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1120px,calc(100%-1rem))] py-6 sm:w-[min(1120px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S4 · exact evidence reviewer</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Проверка комплекта документов</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Экран открывает только manifest_id из query. Здесь нет list, latest selection, case ingestion или источника полномочий.</p>
          <nav aria-label="Разделы пилота" className="mt-4 flex flex-wrap gap-4 text-sm font-bold"><Link className="text-blue-700 hover:underline" href="/">Дела</Link><Link className="text-blue-700 hover:underline" href="/completeness-review">Проверка одного документа</Link></nav>
        </header>
        <aside className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">Используется только dedicated server-only <code>PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN</code> роли <code>COMPLETENESS_REVIEWER</code>. API URL и bearer token не попадают в HTML или browser JavaScript.</aside>
        {!manifestId && <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-950" role="alert">Передайте единственный корректный <code>?manifest_id=…</code>. Автоматического выбора manifest нет.</p>}
        {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-900" role="alert">{error}</p>}
        {evidence && !error && <>
          <Evidence evidence={evidence} />
          {decision ? <ReadOnlyDecision decision={decision} /> : <DocumentSetReviewForm evidence={evidence} />}
        </>}
      </div>
    </main>
  );
}
