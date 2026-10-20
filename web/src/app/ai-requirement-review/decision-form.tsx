"use client";

import { useActionState } from "react";

import { submitAiRequirementReview, type AiReviewFormState } from "./actions";

const initialState: AiReviewFormState = {};
const dispositions = [
  ["ACCEPTED", "Принять как проверенное evidence"],
  ["REJECTED", "Отклонить"],
  ["NEEDS_CLARIFICATION", "Нужно уточнение"],
] as const;

export type ReviewCandidate = {
  kind: "REQUIREMENT" | "PROCUREMENT_ITEM";
  id: string;
  label: string;
};

export function AiRequirementDecisionForm({
  runId,
  evidenceSha256,
  candidates,
}: {
  runId: string;
  evidenceSha256: string;
  candidates: ReviewCandidate[];
}) {
  const [state, action, pending] = useActionState(submitAiRequirementReview, initialState);
  const available = /^[0-9a-f]{64}$/.test(evidenceSha256) && candidates.length <= 10_000;

  return (
    <form action={action} className="mt-6 grid gap-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <input name="run-id" type="hidden" value={runId} />
      <input name="evidence-sha256" type="hidden" value={evidenceSha256} />
      <input name="candidate-count" type="hidden" value={candidates.length} />
      <div>
        <h3 className="m-0 text-base font-black">Терминальная проверка кандидатов</h3>
        <p className="mb-0 mt-1 text-xs leading-5 text-slate-700">
          Каждый кандидат требует явного disposition и основания. Проверка не создаёт Requirement,
          LineItem и не подтверждает полноту документа.
        </p>
      </div>

      {candidates.length === 0 && (
        <p className="m-0 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          COMPLETE-run не содержит кандидатов. Пустую проверку можно зафиксировать, но она не
          доказывает отсутствие требований: completeness остаётся UNKNOWN.
        </p>
      )}

      {candidates.map((candidate) => (
        <div className="grid gap-2 border-t border-blue-200 pt-3" key={`${candidate.kind}:${candidate.id}`}>
          <p className="m-0 text-sm font-bold">
            {candidate.label} <code className="text-xs">{candidate.id}</code>
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-xs font-bold">
              Disposition
              <select
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                defaultValue=""
                disabled={!available || pending}
                name={`candidate-${candidate.kind}-${candidate.id}-disposition`}
                required
              >
                <option value="">Не выбрано</option>
                {dispositions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-bold">
              Основание
              <textarea
                className="min-h-16 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal"
                disabled={!available || pending}
                maxLength={4000}
                name={`candidate-${candidate.kind}-${candidate.id}-reason`}
                required
              />
            </label>
          </div>
        </div>
      ))}

      {!available && (
        <p className="m-0 text-sm font-semibold text-red-800" role="alert">
          Нет корректного digest или число кандидатов превышает безопасный предел.
        </p>
      )}
      {state.error && <p className="m-0 text-sm font-semibold text-red-800" role="alert">{state.error}</p>}
      {state.success && <p className="m-0 text-sm font-semibold text-emerald-800" role="status">{state.success}</p>}
      <button
        className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:opacity-50"
        disabled={!available || pending}
        type="submit"
      >
        {pending ? "Сохраняю…" : "Сохранить проверку"}
      </button>
    </form>
  );
}
