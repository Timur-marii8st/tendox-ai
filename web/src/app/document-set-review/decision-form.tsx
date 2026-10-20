"use client";

import { useActionState, useState } from "react";

import { submitDocumentSetReview, type DocumentSetReviewFormState } from "./actions";
import type { DocumentSetReviewEvidence } from "@/lib/procurement-api";

const initialState: DocumentSetReviewFormState = {};

export function DocumentSetReviewForm({ evidence }: { evidence: DocumentSetReviewEvidence }) {
  const [state, action, pending] = useActionState(submitDocumentSetReview, initialState);
  const [inventory, setInventory] = useState("");
  const [cross, setCross] = useState("");
  const [assessments, setAssessments] = useState<Record<number, string>>({});
  const [findingKind, setFindingKind] = useState("");
  const [findingSource, setFindingSource] = useState("");
  const [findingRationale, setFindingRationale] = useState("");
  const digestAvailable = /^[0-9a-f]{64}$/.test(evidence.manifest.evidence_sha256);
  const decisionsAvailable = evidence.constituents.every((item) => /^[0-9a-f]{64}$/.test(item.decision_sha256 ?? ""));
  const constituentFailure = evidence.constituents.some((item) => item.review.decision?.status === "FAIL");
  const allConstituentsPass = evidence.constituents.every((item) => item.review.decision?.status === "PASS");
  const findingComplete = (findingKind === "CONFIRMED_MATERIAL_OMISSION" || findingKind === "CONFIRMED_MISSING_DOCUMENT")
    && /^(10|[1-9]):(0|[1-9]\d{0,5})$/.test(findingSource)
    && Boolean(findingRationale.trim());
  const locallyFail = constituentFailure || findingComplete;
  const hasServerFindings = evidence.server_findings.length > 0;
  const visibleFindings = hasServerFindings || findingComplete;
  const passEligible = allConstituentsPass
    && !hasServerFindings
    && inventory === "CONFIRMED_FOR_DECLARED_SCOPE"
    && cross === "CHECKED_NO_OPEN_ISSUES"
    && evidence.constituents.every((item) => assessments[item.member.ordinal] === "REVIEWED_IN_SCOPE");

  return (
    <form action={action} className="mt-6 grid gap-4" noValidate>
      <input name="manifest-id" type="hidden" value={evidence.manifest.manifest_id} />
      <input name="manifest-evidence-sha256" type="hidden" value={evidence.manifest.evidence_sha256} />

      <fieldset className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <legend className="px-1 text-sm font-black text-slate-900">Участники exact manifest</legend>
        {evidence.constituents.map((constituent) => {
          const ordinal = constituent.member.ordinal;
          const review = constituent.member.completeness_review_id;
          return (
            <div className="grid gap-3 border-t border-slate-200 pt-4 first:border-0 first:pt-0" key={ordinal}>
              <input name={`member-${ordinal}-review-id`} type="hidden" value={review} />
              <input name={`member-${ordinal}-review-evidence`} type="hidden" value={constituent.member.completeness_review_evidence_sha256} />
              <input name={`member-${ordinal}-decision-sha`} type="hidden" value={constituent.decision_sha256 ?? ""} />
              <p className="m-0 text-sm font-bold">#{ordinal} · {constituent.member.source_document_id} · review {review}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm font-bold">
                  Assessment
                  <select
                    disabled={!digestAvailable || !decisionsAvailable || pending}
                    name={`member-${ordinal}-assessment`}
                    onChange={(event) => setAssessments((current) => ({ ...current, [ordinal]: event.target.value }))}
                    required
                    value={assessments[ordinal] ?? ""}
                  >
                    <option value="">Выберите assessment</option>
                    <option value="REVIEWED_IN_SCOPE">REVIEWED_IN_SCOPE</option>
                    <option value="UNRESOLVED">UNRESOLVED</option>
                  </select>
                </label>
                <label className="grid gap-1 text-sm font-bold">
                  Основание
                  <textarea disabled={!digestAvailable || !decisionsAvailable || pending} maxLength={2000} name={`member-${ordinal}-rationale`} required />
                </label>
              </div>
            </div>
          );
        })}
      </fieldset>

      <div className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-bold">
          Inventory assessment
          <select disabled={!digestAvailable || !decisionsAvailable || pending} name="inventory-assessment" onChange={(event) => setInventory(event.target.value)} required value={inventory}>
            <option value="">Выберите assessment</option>
            <option value="CONFIRMED_FOR_DECLARED_SCOPE">CONFIRMED_FOR_DECLARED_SCOPE</option>
            <option value="UNRESOLVED">UNRESOLVED</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm font-bold">
          Cross-document assessment
          <select disabled={!digestAvailable || !decisionsAvailable || pending} name="cross-assessment" onChange={(event) => setCross(event.target.value)} required value={cross}>
            <option value="">Выберите assessment</option>
            <option disabled={visibleFindings} value="CHECKED_NO_OPEN_ISSUES">CHECKED_NO_OPEN_ISSUES</option>
            <option value="OPEN_ISSUES">OPEN_ISSUES</option>
            <option value="UNRESOLVED">UNRESOLVED</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm font-bold sm:col-span-2">
          Основание inventory
          <textarea disabled={!digestAvailable || !decisionsAvailable || pending} maxLength={2000} name="inventory-rationale" required />
        </label>
        <label className="grid gap-1 text-sm font-bold sm:col-span-2">
          Основание cross-document check
          <textarea disabled={!digestAvailable || !decisionsAvailable || pending} maxLength={4000} name="cross-rationale" required />
        </label>
      </div>

      <fieldset className="grid gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
        <legend className="px-1 text-sm font-black text-red-950">Typed confirmed FAIL finding</legend>
        <p className="m-0 text-sm leading-6 text-red-950">Для нового aggregate FAIL выберите только confirmed kind и один source block из текущего exact evidence. ID finding и origin REVIEWER создаются серверной action; произвольные reference не принимаются.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm font-bold">
            Confirmed kind
            <select disabled={!digestAvailable || !decisionsAvailable || pending} name="finding-kind" onChange={(event) => setFindingKind(event.target.value)} value={findingKind}>
              <option value="">Не добавлять finding</option>
              <option value="CONFIRMED_MATERIAL_OMISSION">CONFIRMED_MATERIAL_OMISSION</option>
              <option value="CONFIRMED_MISSING_DOCUMENT">CONFIRMED_MISSING_DOCUMENT</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm font-bold">
            Exact source block
            <select disabled={!digestAvailable || !decisionsAvailable || pending} name="finding-source" onChange={(event) => setFindingSource(event.target.value)} value={findingSource}>
              <option value="">Выберите block из evidence</option>
              {evidence.constituents.flatMap((constituent) => constituent.review.snapshot.extraction.blocks.map((block, blockIndex) => (
                <option key={`${constituent.member.ordinal}:${blockIndex}`} value={`${constituent.member.ordinal}:${blockIndex}`}>
                  Member #{constituent.member.ordinal} · block #{blockIndex + 1} · {block.provenance.locator}
                </option>
              )))}
            </select>
          </label>
        </div>
        <label className="grid gap-1 text-sm font-bold">
          Finding rationale
          <textarea disabled={!digestAvailable || !decisionsAvailable || pending} maxLength={2000} name="finding-rationale" onChange={(event) => setFindingRationale(event.target.value)} value={findingRationale} />
        </label>
      </fieldset>

      <p className={`m-0 rounded-xl border p-4 text-sm font-black ${locallyFail ? "border-red-200 bg-red-50 text-red-950" : passEligible ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
        Локально вычисленный итог: {locallyFail ? "FAIL" : passEligible ? "PASS" : "UNKNOWN"}. {passEligible
          ? "Все видимые gates закрыты; API остаётся единственным authority."
          : locallyFail
            ? "FAIL основан на constituent FAIL либо typed confirmed reviewer finding; API повторно проверит exact evidence."
            : "PASS требует constituent PASS для каждого участника, REVIEWED_IN_SCOPE, confirmed inventory, completed cross-document check и отсутствия server findings."}
      </p>
      <label className="grid gap-1 text-sm font-bold">
        Основание terminal decision
        <textarea disabled={!digestAvailable || !decisionsAvailable || pending} maxLength={4000} name="reason" required />
      </label>

      {constituentFailure && <p className="m-0 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-900" role="alert">Найден constituent FAIL. Форма отправит exact attestations и assessments; дополнительный reviewer finding необязателен для этого FAIL path.</p>}
      {(!digestAvailable || !decisionsAvailable) && <p className="m-0 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-900" role="alert">Exact manifest digest или constituent terminal decision отсутствует; отправка заблокирована.</p>}
      {state.error && <p className="m-0 text-sm font-semibold text-red-800" role="alert">{state.error}</p>}
      {state.success && <p className="m-0 text-sm font-semibold text-emerald-800" role="status">{state.success}</p>}
      <button className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={!digestAvailable || !decisionsAvailable || pending} type="submit">
        {pending ? "Сохраняю…" : "Сохранить terminal decision"}
      </button>
    </form>
  );
}
