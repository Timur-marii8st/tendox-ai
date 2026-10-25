import type { Metadata } from "next";
import Link from "next/link";

import { HardGateForm } from "./form";
import {
  ApiError,
  ConfigurationError,
  loadCaseHardGateAssessmentEvidence,
  type CaseHardGateAssessmentEvidence,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Hard gates — Tendox" };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Operator API не настроен.";
  if (error instanceof ApiError && error.status === 404) return "Case version не найдена.";
  if (error instanceof ApiError && error.status === 422) return "Case не является exact S89 materialization с одним technical PASS.";
  return "Hard-gate evidence недоступен.";
}

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const caseId = typeof params.case_id === "string" ? params.case_id : "";
  const version = Number(typeof params.version === "string" ? params.version : "");
  const valid = ID.test(caseId) && Number.isInteger(version) && version >= 1;
  let evidence: CaseHardGateAssessmentEvidence | null = null; let error: string | null = null;
  if (valid) try { evidence = await loadCaseHardGateAssessmentEvidence(caseId, version); } catch (caught) { error = failure(caught); }
  const technical = evidence?.case.assessment?.checks.find((item) => item.kind === "technical");
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1100px,calc(100%-1rem))] py-8">
    <header className="border-b border-slate-200 pb-6"><p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S90 · exact remaining hard gates</p><h1 className="mt-2 text-3xl font-black sm:text-5xl">Актуализация hard gates</h1><p className="max-w-3xl text-sm leading-6 text-slate-600">Technical PASS закреплён независимым offer review. DOCUMENT вычисляется из terminal document-set binding. Четыре остальные проверки требуют явного статуса, основания и exact persisted document для PASS/FAIL.</p><Link className="text-sm font-bold text-blue-700" href="/">Дела</Link></header>
    {!valid && <form action="/hard-gate-assessment" className="mt-6 grid gap-3 rounded-xl bg-white p-5 sm:grid-cols-3" method="get"><input name="case_id" placeholder="Case ID" required /><input name="version" placeholder="Version" required /><button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white">Открыть</button></form>}
    {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 font-bold text-red-900">{error}</p>}
    {evidence && <><section className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-emerald-950"><h2 className="m-0 text-xl font-black">Inherited technical PASS</h2><p>{technical?.reason}</p><p className="break-all font-mono text-xs">case input {evidence.source_case_input_sha256}</p>{technical?.evidence.map((item) => <p className="text-sm" key={`${item.document_id}:${item.locator}`}>{item.document_id} · {item.locator}</p>)}</section><HardGateForm evidence={evidence} /></>}
  </div></main>;
}
