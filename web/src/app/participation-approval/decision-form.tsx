"use client";

import { useActionState } from "react";

import {
  submitParticipationDecision,
  type ParticipationApprovalState,
} from "./actions";

const initial: ParticipationApprovalState = {};

export function ParticipationDecisionForm({
  evaluationId,
  evidenceSha256,
}: {
  evaluationId: string;
  evidenceSha256: string;
}) {
  const [state, action, pending] = useActionState(submitParticipationDecision, initial);
  return <form action={action} className="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5">
    <input name="evaluation-id" type="hidden" value={evaluationId} />
    <input name="evidence-sha256" type="hidden" value={evidenceSha256} />
    <fieldset className="grid gap-2">
      <legend className="font-black">Решение человека</legend>
      <label className="flex gap-2"><input name="status" required type="radio" value="APPROVED" /> APPROVED — участвовать</label>
      <label className="flex gap-2"><input name="status" required type="radio" value="REJECTED" /> REJECTED — отказаться</label>
    </fieldset>
    <label className="grid gap-2 font-bold">Основание
      <textarea className="min-h-28 rounded-lg border border-slate-300 p-3 font-normal" maxLength={4000} name="reason" required />
    </label>
    <p className="text-sm text-amber-900">Перед APPROVED сервер заново рассчитает этот же case на текущее время. Решение не разрешает отправку заявки или иное внешнее действие.</p>
    <button className="rounded-lg bg-slate-950 px-4 py-3 font-black text-white disabled:opacity-50" disabled={pending} type="submit">
      {pending ? "Проверяем и сохраняем…" : "Сохранить terminal decision"}
    </button>
    {state.error && <p className="text-red-700" role="alert">{state.error}</p>}
    {state.success && <p className="text-emerald-700" role="status">{state.success}</p>}
    {state.decisionSha256 && <code className="break-all text-xs">{state.decisionSha256}</code>}
  </form>;
}
