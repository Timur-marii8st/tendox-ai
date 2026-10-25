import type { Metadata } from "next";
import Link from "next/link";

import { RequirementSetBindingForm } from "./binding-form";
import {
  ApiError,
  ConfigurationError,
  loadReviewedRequirementSet,
  type ReviewedRequirementSetRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Привязка требований к кейсу — Tendox",
  description: "Operator binding exact reviewed requirement set к immutable версии кейса",
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроены PROCUREMENT_API_URL и PROCUREMENT_API_TOKEN.";
  if (error instanceof ApiError) {
    if (error.status === 404) return "Exact requirement set не найден в текущем tenant.";
    if (error.status === 403) return "Token не имеет доступа к requirement set.";
  }
  return "Requirement set временно недоступен.";
}

export default async function RequirementSetBindingPage({
  searchParams,
}: {
  searchParams: Promise<{ set_id?: string | string[]; case_id?: string | string[]; version?: string | string[] }>;
}) {
  const params = await searchParams;
  const setId = typeof params.set_id === "string" && ID.test(params.set_id) ? params.set_id : null;
  const caseId = typeof params.case_id === "string" && ID.test(params.case_id) ? params.case_id : "";
  const caseVersion = typeof params.version === "string" && /^\d{1,9}$/.test(params.version) ? params.version : "1";
  let record: ReviewedRequirementSetRecord | null = null;
  let error: string | null = null;
  if (setId) {
    try {
      record = await loadReviewedRequirementSet(setId);
    } catch (caught) {
      error = failure(caught);
    }
  }
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(960px,calc(100%-1rem))] py-6 sm:w-[min(960px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S85 · operator binding</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Привязка требований к кейсу</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Оператор выбирает точный set ID и immutable case version. Экран не ищет latest PASS и не принимает решение reviewer.</p>
          <nav aria-label="Разделы пилота" className="mt-4 flex flex-wrap gap-4 text-sm font-bold"><Link className="text-blue-700 hover:underline" href="/">Дела</Link><Link className="text-blue-700 hover:underline" href="/requirement-set-materialization">Материализация требований</Link></nav>
        </header>
        {!setId && (
          <form action="/requirement-set-binding" className="mt-6 grid gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-[1fr_auto] sm:items-end" method="get">
            <label className="grid gap-1 text-sm font-bold">Exact set ID<input className="rounded-lg border border-slate-300 p-2 font-mono" name="set_id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label>
            <button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white" type="submit">Открыть set</button>
          </form>
        )}
        {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-900" role="alert">{error}</p>}
        {record && !error && (
          <>
            <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="m-0 text-xl font-black">Exact reviewed set</h2>
              <p className="mt-3 break-all text-sm">Set ID: {record.proposal.set_id}</p>
              <p className="break-all font-mono text-xs">Proposal SHA-256: {record.proposal.proposal_sha256}</p>
              <p className="text-sm">Строк: {record.proposal.entries.length}; manual: {record.proposal.entries.filter((entry) => entry.disposition === "MANUAL_REVIEW_REQUIRED").length}</p>
              {record.decision ? (
                <div className={`mt-4 rounded-xl border p-4 text-sm ${record.decision.status === "PASS" ? "border-emerald-200 bg-emerald-50 text-emerald-950" : record.decision.status === "FAIL" ? "border-red-200 bg-red-50 text-red-950" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
                  <p className="m-0 font-black">Decision: {record.decision.status}</p>
                  <p>{record.decision.reason}</p>
                  <p className="mb-0 break-all font-mono text-xs">Decision SHA-256: {record.decision.decision_sha256}</p>
                </div>
              ) : <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-950">Terminal reviewer decision ещё не сохранено. Binding заблокирован.</p>}
            </section>
            {record.decision?.status === "PASS"
              ? <RequirementSetBindingForm caseId={caseId} caseVersion={caseVersion} record={record} />
              : record.decision && <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-950">Binding разрешён только для terminal PASS; текущее решение: {record.decision.status}.</p>}
          </>
        )}
      </div>
    </main>
  );
}
