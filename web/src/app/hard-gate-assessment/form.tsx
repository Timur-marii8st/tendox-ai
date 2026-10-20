"use client";

import Link from "next/link";
import { useActionState } from "react";

import { submitHardGates, type HardGateState } from "./actions";
import type { CaseHardGateAssessmentEvidence, HardGateKind } from "@/lib/procurement-api";

const initial: HardGateState = {};
const gates: Array<{ kind: HardGateKind; label: string }> = [
  { kind: "legal", label: "LEGAL · правовые запреты и применимые нормы" },
  { kind: "participant", label: "PARTICIPANT · требования к участнику" },
  { kind: "company_policy", label: "COMPANY POLICY · лимиты и запреты компании" },
  { kind: "logistics", label: "LOGISTICS · адреса, сроки и выполнимость поставки" },
];

export function HardGateForm({ evidence }: { evidence: CaseHardGateAssessmentEvidence }) {
  const [state, action, pending] = useActionState(submitHardGates, initial);
  const item = evidence.case;
  return <form action={action} className="mt-6 space-y-5">
    <input name="case-id" type="hidden" value={item.case_id} />
    <input name="case-version" type="hidden" value={item.version} />
    <input name="source-case-sha256" type="hidden" value={evidence.source_case_input_sha256} />
    <fieldset className="rounded-xl border border-violet-200 bg-violet-50 p-5" disabled={pending || Boolean(state.success)}>
      <legend className="px-2 font-black">DOCUMENT · terminal document-set review</legend>
      <p className="text-sm">DOCUMENT status вычисляет сервер из exact binding. Ручной verdict не принимается.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="grid gap-1 text-sm font-bold">Binding ID<input name="document-binding-id" required /></label>
        <label className="grid gap-1 text-sm font-bold">Manifest evidence SHA-256<input name="manifest-evidence-sha256" pattern="[0-9a-f]{64}" required /></label>
        <label className="grid gap-1 text-sm font-bold">Decision SHA-256<input name="document-decision-sha256" pattern="[0-9a-f]{64}" required /></label>
      </div>
    </fieldset>
    {gates.map(({ kind, label }) => <fieldset className="rounded-xl border border-slate-200 bg-white p-5" disabled={pending || Boolean(state.success)} key={kind}>
      <legend className="px-2 font-black">{label}</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-bold">Status<select name={`${kind}-status`} required defaultValue=""><option value="" disabled>Выберите</option><option>PASS</option><option>FAIL</option><option>UNKNOWN</option></select></label>
        <label className="grid gap-1 text-sm font-bold">Основание<input name={`${kind}-reason`} maxLength={4000} required /></label>
        <label className="grid gap-1 text-sm font-bold">Evidence document ID<input name={`${kind}-document-id`} /></label>
        <label className="grid gap-1 text-sm font-bold">Evidence SHA-256<input name={`${kind}-document-sha256`} pattern="[0-9a-f]{64}" /></label>
        <label className="grid gap-1 text-sm font-bold sm:col-span-2">Locator<input name={`${kind}-locator`} maxLength={1000} /></label>
      </div>
      <p className="mb-0 text-xs text-slate-500">Для PASS/FAIL exact документ обязателен. Для UNKNOWN поля evidence можно оставить пустыми.</p>
    </fieldset>)}
    <button className="rounded-lg bg-blue-800 px-5 py-3 font-black text-white disabled:opacity-50" disabled={pending || Boolean(state.success)}>{pending ? "Проверяем…" : `Создать v${item.version + 1}`}</button>
    {state.error && <p className="rounded-lg bg-red-50 p-3 font-bold text-red-900">{state.error}</p>}
    {state.success && <p className="rounded-lg bg-emerald-50 p-3 font-bold text-emerald-900">{state.success} <Link className="underline" href="/">Открыть список дел</Link></p>}
  </form>;
}
