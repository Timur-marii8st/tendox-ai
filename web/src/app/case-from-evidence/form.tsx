"use client";

import Link from "next/link";
import { useActionState } from "react";

import { submitCaseFromEvidence, type CaseFromEvidenceFormState } from "./actions";

const initialState: CaseFromEvidenceFormState = {};

export function CaseFromEvidenceForm() {
  const [state, action, pending] = useActionState(submitCaseFromEvidence, initialState);

  return (
    <div>
      <form action={action} className="mt-6 grid gap-4" noValidate>
        <fieldset className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-3">
          <legend className="px-1 text-sm font-black text-slate-900">Exact привязка</legend>
          <label className="grid gap-1 text-sm font-bold">
            Binding ID
            <input
              autoComplete="off"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm outline-none focus:border-blue-500"
              disabled={pending}
              maxLength={200}
              name="binding-id"
              placeholder="binding-…"
              required
            />
          </label>
          <label className="grid gap-1 text-sm font-bold">
            Manifest evidence SHA-256
            <input
              autoComplete="off"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm outline-none focus:border-blue-500"
              disabled={pending}
              maxLength={64}
              minLength={64}
              name="manifest-evidence-sha256"
              pattern="[0-9a-f]{64}"
              placeholder="64 hex"
              required
            />
          </label>
          <label className="grid gap-1 text-sm font-bold">
            Decision SHA-256
            <input
              autoComplete="off"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm outline-none focus:border-blue-500"
              disabled={pending}
              maxLength={64}
              minLength={64}
              name="decision-sha256"
              pattern="[0-9a-f]{64}"
              placeholder="64 hex"
              required
            />
          </label>
        </fieldset>

        <label className="grid gap-1 text-sm font-bold">
          Драфт кейса JSON без assessment
          <textarea
            className="min-h-56 rounded-xl border border-slate-300 bg-white p-3 font-mono text-xs leading-5 outline-none focus:border-blue-500"
            disabled={pending}
            maxLength={200000}
            name="case-json"
            placeholder='{"case_id": "…", "version": 1, "company_id": "…", …}'
            required
            spellCheck={false}
          />
        </label>

        <label className="grid gap-1 text-sm font-bold">
          Дополнительные проверки JSON (необязательно, массив до 5 без kind document)
          <textarea
            className="min-h-24 rounded-xl border border-slate-300 bg-white p-3 font-mono text-xs leading-5 outline-none focus:border-blue-500"
            disabled={pending}
            maxLength={20000}
            name="other-checks"
            placeholder="[]"
            spellCheck={false}
          />
        </label>

        <div>
          <button
            className="rounded-xl bg-slate-900 px-6 py-3 font-extrabold text-white hover:bg-blue-800 disabled:opacity-50"
            disabled={pending}
            type="submit"
          >
            {pending ? "Создание…" : "Создать кейс из привязки"}
          </button>
        </div>
      </form>

      {state.error && (
        <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-900" role="alert">
          {state.error}
        </p>
      )}
      {state.success && (
        <section className="mt-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-5" aria-live="polite">
          <p className="m-0 text-sm font-black text-emerald-900">{state.success}</p>
          <dl className="mt-3 grid gap-2 text-sm text-emerald-950 sm:grid-cols-3">
            <div><dt className="font-bold">Кейс</dt><dd className="break-all font-mono text-xs">{state.caseId}</dd></div>
            <div><dt className="font-bold">Версия</dt><dd>{state.version}</dd></div>
            <div><dt className="font-bold">DOCUMENT-проверка</dt><dd>{state.documentStatus}</dd></div>
          </dl>
          <p className="mb-0 mt-3 text-sm">
            <Link className="font-bold text-blue-700 hover:underline" href="/">Открыть дела</Link>
          </p>
        </section>
      )}
    </div>
  );
}
