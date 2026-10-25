import type { Metadata } from "next";
import Link from "next/link";

import { ParticipationDecisionForm } from "./decision-form";
import {
  ApiError,
  ConfigurationError,
  loadParticipationDecision,
  type ParticipationDecisionRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Согласование участия — Tendox",
  description: "Независимое human approval одной exact PARTICIPATE evaluation",
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const stamp = (value: string) => new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) {
    return "Не настроен PROCUREMENT_PARTICIPATION_APPROVER_TOKEN.";
  }
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли PARTICIPATION_APPROVER.";
    if (error.status === 404) return "Exact evaluation не найдена в текущем tenant.";
    if (error.status === 422) return "Stored evaluation evidence не прошло проверку.";
  }
  return "Evaluation временно недоступна.";
}

function Evidence({ record }: { record: ParticipationDecisionRecord }) {
  const evidence = record.evidence;
  const recommendation = evidence.recommendation;
  const recommendationTone = recommendation.decision === "participate"
    ? "bg-emerald-100 text-emerald-900"
    : "bg-amber-100 text-amber-950";
  return <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="m-0 text-xl font-black">Exact evaluation</h2>
      <strong className={`rounded-full px-3 py-1 ${recommendationTone}`}>{recommendation.decision}</strong>
    </div>
    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
      <div><dt className="font-bold text-slate-500">Evaluation</dt><dd className="m-0 break-all">{evidence.evaluation_id}</dd></div>
      <div><dt className="font-bold text-slate-500">Case</dt><dd className="m-0">{evidence.case_id} · v{evidence.case_version}</dd></div>
      <div><dt className="font-bold text-slate-500">Оценил</dt><dd className="m-0">{evidence.evaluated_by} · {stamp(evidence.evaluated_at)}</dd></div>
      <div><dt className="font-bold text-slate-500">Effective at</dt><dd className="m-0">{stamp(evidence.effective_at)}</dd></div>
      <div><dt className="font-bold text-slate-500">Прибыль</dt><dd className="m-0">{recommendation.realistic_profit ?? "UNKNOWN"}</dd></div>
      <div><dt className="font-bold text-slate-500">Маржа / floor</dt><dd className="m-0">{recommendation.realistic_margin ?? "UNKNOWN"} · {recommendation.minimum_bid_price ?? "UNKNOWN"}</dd></div>
    </dl>
    <h3 className="mt-5 text-base font-black">Основания движка</h3>
    <ul className="text-sm">{recommendation.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
    <p className="break-all font-mono text-xs text-slate-500">Case input SHA-256: {evidence.case_input_sha256}</p>
    <p className="mb-0 break-all font-mono text-xs text-slate-500">Evidence SHA-256: {evidence.evidence_sha256}</p>
  </section>;
}

export default async function ParticipationApprovalPage({
  searchParams,
}: {
  searchParams: Promise<{ evaluation_id?: string | string[] }>;
}) {
  const requested = (await searchParams).evaluation_id;
  const evaluationId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ParticipationDecisionRecord | null = null;
  let error: string | null = null;
  if (evaluationId) {
    try { record = await loadParticipationDecision(evaluationId); }
    catch (caught) { error = failure(caught); }
  }
  const decision = record?.decision;
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(900px,calc(100%-1rem))] py-6 sm:w-[min(900px,calc(100%-2rem))] sm:py-10">
    <header className="border-b border-slate-200 pb-6">
      <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S92 · independent human decision</p>
      <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Согласование участия</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Согласующий открывает одну immutable оценку PARTICIPATE. APPROVED допустим только после серверного пересчёта того же case на текущее время.</p>
      <nav className="mt-4"><Link className="font-bold text-blue-700 hover:underline" href="/">Дела</Link></nav>
    </header>
    <aside className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">Используется только server-only <code>PROCUREMENT_PARTICIPATION_APPROVER_TOKEN</code>. Это внутреннее решение; <strong>external_action_authorized=false</strong>.</aside>
    {!evaluationId && <form action="/participation-approval" className="mt-6 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-end" method="get"><label className="grid flex-1 gap-1 text-sm font-bold">Exact evaluation ID<input className="rounded-lg border border-slate-300 p-2 font-mono" name="evaluation_id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label><button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white" type="submit">Открыть evaluation</button></form>}
    {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 font-bold text-red-900" role="alert">{error}</p>}
    {record && !error && <><Evidence record={record} />{decision ? <section className="mt-6 rounded-2xl border border-slate-300 bg-white p-5"><h2 className="m-0 text-xl font-black">Terminal decision: {decision.status}</h2><p>{decision.reason}</p><p className="text-sm">{decision.decided_by} · {stamp(decision.decided_at)}</p><p className="text-sm">Текущий пересчёт: <strong>{decision.current_recommendation.decision}</strong></p><p className="break-all font-mono text-xs">{decision.decision_sha256}</p><p className="font-bold text-amber-900">Внешнее действие не разрешено.</p>{decision.status === "APPROVED" && <Link className="font-bold text-blue-700 hover:underline" href={`/application-package?decision_id=${encodeURIComponent(decision.decision_id)}`}>Собрать пакет заявки</Link>}</section> : record.evidence.recommendation.decision === "participate" ? <ParticipationDecisionForm evaluationId={record.evidence.evaluation_id} evidenceSha256={record.evidence.evidence_sha256} /> : <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 font-bold text-amber-950">Эта evaluation не содержит PARTICIPATE и не может получить participation decision.</p>}</>}
  </div></main>;
}
