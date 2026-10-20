"use client";

import { useActionState, useState } from "react";

import { submitCompletenessDecision, type CompletenessDecisionFormState } from "./actions";
import type { CompletenessUnmappedBlock } from "@/lib/procurement-api";

const initialState: CompletenessDecisionFormState = {};

const dispositions = [
  ["MATERIAL_REQUIREMENT", "Существенное требование"],
  ["NON_REQUIREMENT", "Не является требованием"],
  ["EXCLUDED_FROM_SCOPE", "Исключено из scope"],
] as const;

export function CompletenessDecisionForm({
  reviewId,
  evidenceSha256,
  unmappedBlocks,
}: {
  reviewId: string;
  evidenceSha256: string;
  unmappedBlocks: CompletenessUnmappedBlock[];
}) {
  const [state, action, pending] = useActionState(submitCompletenessDecision, initialState);
  const [status, setStatus] = useState("");
  const digestAvailable = /^[0-9a-f]{64}$/.test(evidenceSha256);
  const requireBlockDecisions = status === "PASS";
  const disableBlockDecisions = status === "UNKNOWN";

  return (
    <form action={action} className="mt-5 grid gap-4" noValidate={false}>
      <input name="review-id" type="hidden" value={reviewId} />
      <input name="evidence-sha256" type="hidden" value={evidenceSha256} />

      <div className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-bold text-slate-800" htmlFor={`status-${reviewId}`}>
          Статус полноты
          <select
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 font-semibold"
            disabled={!digestAvailable || pending}
            id={`status-${reviewId}`}
            name="status"
            onChange={(event) => setStatus(event.target.value)}
            required
            value={status}
          >
            <option value="">Выберите итог</option>
            <option value="PASS">PASS — полнота подтверждена</option>
            <option value="FAIL">FAIL — есть существенный непокрытый блок</option>
            <option value="UNKNOWN">UNKNOWN — данных недостаточно</option>
          </select>
        </label>
        <p className="m-0 self-end text-xs leading-5 text-slate-600">
          PASS не разрешён, пока по каждому непокрытому блоку нет явного решения.
          UNKNOWN можно сохранить без решений по блокам.
        </p>
      </div>

      <label className="grid gap-1 text-sm font-bold text-slate-800" htmlFor={`scope-${reviewId}`}>
        Проверенный scope
        <textarea
          className="min-h-20 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal"
          disabled={!digestAvailable || pending}
          id={`scope-${reviewId}`}
          maxLength={4000}
          name="scope"
          placeholder="Например: весь документ и все существенные технические требования"
          required
        />
      </label>
      <label className="grid gap-1 text-sm font-bold text-slate-800" htmlFor={`reason-${reviewId}`}>
        Основание итоговой оценки
        <textarea
          className="min-h-24 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal"
          disabled={!digestAvailable || pending}
          id={`reason-${reviewId}`}
          maxLength={4000}
          name="reason"
          placeholder="Опишите проверку и основания итогового статуса"
          required
        />
      </label>

      {unmappedBlocks.length > 0 && (
        <fieldset className="grid gap-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
          <legend className="px-1 text-sm font-black text-amber-950">Решения по непокрытым блокам</legend>
          {unmappedBlocks.map((block) => (
            <div className="grid gap-2 border-t border-amber-200 pt-3 first:border-0 first:pt-0" key={block.block_index}>
              <p className="m-0 text-xs font-bold text-amber-900">
                Блок #{block.block_index + 1}
                {block.reason ? ` · ${block.reason}` : ""}
              </p>
              <p className="m-0 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{block.text || "Текст блока не передан API."}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-xs font-bold text-slate-800">
                  Решение
                  <select
                    className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                    disabled={!digestAvailable || pending || disableBlockDecisions}
                    name={`unmapped-${block.block_index}-disposition`}
                    required={requireBlockDecisions}
                    defaultValue=""
                  >
                    <option value="">Не выбрано</option>
                    {dispositions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-bold text-slate-800">
                  Основание по блоку
                  <textarea
                    className="min-h-16 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal"
                    disabled={!digestAvailable || pending || disableBlockDecisions}
                    maxLength={2000}
                    name={`unmapped-${block.block_index}-rationale`}
                    placeholder="Явное основание решения"
                    required={requireBlockDecisions}
                  />
                </label>
              </div>
            </div>
          ))}
        </fieldset>
      )}

      {!digestAvailable && (
        <p className="m-0 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-900" role="alert">
          Снимок API не содержит корректный SHA-256 evidence; терминальное решение не отправляется.
        </p>
      )}
      {state.error && <p className="m-0 text-sm font-semibold text-red-800" role="alert">{state.error}</p>}
      {state.success && <p className="m-0 text-sm font-semibold text-emerald-800" role="status">{state.success}</p>}
      <button
        className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!digestAvailable || pending}
        type="submit"
      >
        {pending ? "Сохраняю решение…" : "Сохранить терминальное решение"}
      </button>
    </form>
  );
}
