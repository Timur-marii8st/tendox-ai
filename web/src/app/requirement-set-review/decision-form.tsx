"use client";

import { useActionState, useState } from "react";

import { submitRequirementSetReview, type RequirementSetReviewState } from "./actions";
import type { ReviewedRequirementSetRecord } from "@/lib/procurement-api";

const initialState: RequirementSetReviewState = {};

export function RequirementSetReviewForm({ record }: { record: ReviewedRequirementSetRecord }) {
  const [state, action, pending] = useActionState(submitRequirementSetReview, initialState);
  const [coverage, setCoverage] = useState("");
  const [normalization, setNormalization] = useState("");
  const [status, setStatus] = useState("");
  const passEligible = coverage === "CONFIRMED" && normalization === "REVIEWED";
  const manualCount = record.proposal.entries.filter(
    (entry) => entry.disposition === "MANUAL_REVIEW_REQUIRED",
  ).length;

  return (
    <form action={action} className="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" noValidate>
      <input name="set-id" type="hidden" value={record.proposal.set_id} />
      <input name="proposal-sha256" type="hidden" value={record.proposal.proposal_sha256} />
      <h2 className="m-0 text-xl font-black">Terminal decision</h2>
      <p className="m-0 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
        В proposal осталось manual-строк: <strong>{manualCount}</strong>. Даже <strong>PASS</strong>
        подтверждает только полное отображение исходных строк и проверку выбранной нормализации.
        Он не превращает manual-строки в машинные требования и не подтверждает товар.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-bold">
          Coverage assessment
          <select disabled={pending} name="coverage-assessment" onChange={(event) => setCoverage(event.target.value)} required value={coverage}>
            <option value="">Выберите явно</option>
            <option value="CONFIRMED">CONFIRMED</option>
            <option value="UNRESOLVED">UNRESOLVED</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm font-bold">
          Normalization assessment
          <select disabled={pending} name="normalization-assessment" onChange={(event) => setNormalization(event.target.value)} required value={normalization}>
            <option value="">Выберите явно</option>
            <option value="REVIEWED">REVIEWED</option>
            <option value="UNRESOLVED">UNRESOLVED</option>
          </select>
        </label>
      </div>
      <label className="grid gap-1 text-sm font-bold">
        Итог
        <select disabled={pending} name="status" onChange={(event) => setStatus(event.target.value)} required value={status}>
          <option value="">Выберите PASS, FAIL или UNKNOWN</option>
          <option disabled={!passEligible} value="PASS">PASS</option>
          <option value="FAIL">FAIL</option>
          <option value="UNKNOWN">UNKNOWN</option>
        </select>
      </label>
      {status === "PASS" && (
        <p className="m-0 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950">
          PASS доступен, потому что coverage подтверждено и нормализация проверена. Manual scope остаётся открытым.
        </p>
      )}
      <label className="grid gap-1 text-sm font-bold">
        Основание решения
        <textarea disabled={pending} maxLength={4000} name="reason" required rows={5} />
      </label>
      {state.error && <p className="m-0 text-sm font-bold text-red-800" role="alert">{state.error}</p>}
      {state.success && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" role="status">
          <p className="m-0 font-black">{state.success}</p>
          <p className="mb-0 mt-2 break-all font-mono text-xs">Decision SHA-256: {state.decisionSha256}</p>
        </div>
      )}
      <button className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={pending || !coverage || !normalization || !status} type="submit">
        {pending ? "Сохраняю…" : "Сохранить terminal decision"}
      </button>
    </form>
  );
}
