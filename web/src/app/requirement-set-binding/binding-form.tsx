"use client";

import { useActionState } from "react";

import { submitRequirementSetBinding, type RequirementSetBindingState } from "./actions";
import type { ReviewedRequirementSetRecord } from "@/lib/procurement-api";

const initialState: RequirementSetBindingState = {};

export function RequirementSetBindingForm({
  record,
  caseId,
  caseVersion,
}: {
  record: ReviewedRequirementSetRecord;
  caseId: string;
  caseVersion: string;
}) {
  const [state, action, pending] = useActionState(submitRequirementSetBinding, initialState);
  const decision = record.decision;
  if (!decision || decision.status !== "PASS") return null;
  return (
    <form action={action} className="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" noValidate>
      <input name="set-id" type="hidden" value={record.proposal.set_id} />
      <input name="proposal-sha256" type="hidden" value={record.proposal.proposal_sha256} />
      <input name="decision-sha256" type="hidden" value={decision.decision_sha256} />
      <h2 className="m-0 text-xl font-black">Привязать к immutable версии кейса</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-bold">Case ID<input className="rounded-lg border border-slate-300 p-2 font-mono" defaultValue={caseId} name="case-id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label>
        <label className="grid gap-1 text-sm font-bold">Версия<input className="rounded-lg border border-slate-300 p-2" defaultValue={caseVersion} min="1" name="case-version" required type="number" /></label>
      </div>
      <p className="m-0 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">API повторно проверит существование exact case version, terminal PASS, оба digest и разделение reviewer/binder. Для одной версии кейса допускается один append-only binding.</p>
      {state.error && <p className="m-0 text-sm font-bold text-red-800" role="alert">{state.error}</p>}
      {state.success && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" role="status">
          <p className="m-0 font-black">{state.success}</p>
          <p className="mt-2 break-all">Binding ID: {state.bindingId}</p>
          <p className="mb-0 break-all font-mono text-xs">Binding SHA-256: {state.bindingSha256}</p>
          <a
            className="mt-3 inline-block font-bold text-blue-700 hover:underline"
            href={`/server-offer-proposal?case_id=${encodeURIComponent(state.caseId ?? "")}&version=${state.caseVersion ?? 1}&binding_id=${encodeURIComponent(state.bindingId ?? "")}&binding_sha256=${state.bindingSha256 ?? ""}`}
          >
            Перейти к exact BOM/КП →
          </a>
        </div>
      )}
      <button className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={pending} type="submit">{pending ? "Привязываю…" : "Создать exact binding"}</button>
    </form>
  );
}
