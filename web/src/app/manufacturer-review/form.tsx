"use client";

import { useActionState } from "react";
import type { ManufacturerProposal } from "@/lib/manufacturer-review";
import { decide, propose, upload, type State } from "./actions";

const empty: State = {};
const claimLabels = [
  ["LEGAL_NAME", "Юридическое наименование"], ["COUNTRY", "Страна регистрации"],
  ["IDENTIFIER_SCHEME", "Схема идентификатора"], ["REGISTRATION_ID", "Регистрационный номер"],
  ["MANUFACTURER_ROLE", "Роль производителя для этого товара"],
] as const;

export function ReviewForm({ runId, recordId, uploadCommandId, proposalCommandId }: { runId: string; recordId: string; uploadCommandId: string; proposalCommandId: string }) {
  const [uploadState, uploadAction, uploadPending] = useActionState(upload, empty);
  const [proposalState, proposalAction, proposalPending] = useActionState(propose, empty);
  return <section className="mt-6 grid gap-5">
    <form action={uploadAction} className="rounded-xl border bg-white p-4">
      <input type="hidden" name="upload_command_id" value={uploadCommandId} />
      <h2 className="m-0 font-black">Документ для проверки</h2>
      <p className="text-sm text-slate-600">Источник и его адрес заявлены загрузившим и сами по себе не подтверждены.</p>
      <label className="mt-3 block">PDF до 2 МиБ<input className="mt-1 block" name="file" accept="application/pdf,.pdf" type="file" required /></label>
      <label className="mt-2 block">Название источника<input className="mt-1 w-full border p-2" name="source_title" maxLength={500} required /></label>
      <label className="mt-2 block">HTTPS-адрес источника<input className="mt-1 w-full border p-2" name="source_url" type="url" pattern="https://.*" maxLength={2048} required /></label>
      <button className="mt-3 rounded bg-slate-950 px-4 py-2 text-white disabled:opacity-50" disabled={uploadPending}>{uploadPending ? "Сохраняю…" : "Сохранить PDF"}</button>
      {uploadState.artifact && <p className="break-all text-sm">Документ сохранён: {uploadState.artifact.artifact_id}<br />SHA-256: {uploadState.artifact.sha256}</p>}
      {uploadState.error && <p role="alert" className="text-red-700">{uploadState.error}</p>}
    </form>
    {uploadState.artifact && <form action={proposalAction} className="rounded-xl border bg-white p-4">
      <input type="hidden" name="proposal_command_id" value={proposalCommandId} /><input type="hidden" name="run_id" value={runId} /><input type="hidden" name="record_id" value={recordId} /><input type="hidden" name="artifact_id" value={uploadState.artifact.artifact_id} /><input type="hidden" name="artifact_sha256" value={uploadState.artifact.sha256} />
      <h2 className="m-0 font-black">Предложить юридическое лицо</h2>
      <div className="mt-3 grid gap-3">
        <label>Юридическое наименование<input className="mt-1 w-full border p-2" name="legal_name" maxLength={500} required /></label>
        <label>Код страны (две заглавные буквы)<input className="mt-1 w-full border p-2" name="country_code" pattern="[A-Z]{2}" maxLength={2} required /></label>
        <label>Схема идентификатора<input className="mt-1 w-full border p-2" name="identifier_scheme" pattern="[A-Z0-9._-]+" maxLength={80} required /></label>
        <label>Регистрационный номер<input className="mt-1 w-full border p-2" name="registration_id" maxLength={120} required /></label>
        <label>Страница PDF<input className="mt-1 w-full border p-2" name="page" type="number" min={1} max={100000} required /></label>
        <label>Точное место на странице<input className="mt-1 w-full border p-2" name="locator" maxLength={500} required /></label>
        <label>Цитата<input className="mt-1 w-full border p-2" name="quote" maxLength={1000} required /></label>
        <fieldset className="border p-3"><legend className="font-bold">Какие факты подтверждает цитата</legend>{claimLabels.map(([value, label]) => <label className="mt-2 block" key={value}><input name="claims" type="checkbox" value={value} /> {label}</label>)}</fieldset>
      </div>
      <button className="mt-3 rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50" disabled={proposalPending}>{proposalPending ? "Сохраняю…" : "Передать на независимую проверку"}</button>
      {proposalState.error && <p role="alert" className="text-red-700">{proposalState.error}</p>}
    </form>}
  </section>;
}

export function DecisionForm({ proposal, decisionCommandId }: { proposal: ManufacturerProposal; decisionCommandId: string }) {
  const [state, action, pending] = useActionState(decide, empty);
  return <form action={action} className="mt-5 rounded-xl border p-4">
    <input type="hidden" name="proposal_id" value={proposal.proposal_id} /><input type="hidden" name="decision_command_id" value={decisionCommandId} />
    <h2 className="m-0 font-black">Независимое решение</h2>
    <div className="mt-3 grid gap-3">
      <label>Статус юридической идентичности<select className="mt-1 block w-full border p-2" name="identity_status" defaultValue="UNKNOWN"><option>UNKNOWN</option><option>PASS</option><option>FAIL</option></select></label>
      <label>Статус роли производителя<select className="mt-1 block w-full border p-2" name="role_status" defaultValue="UNKNOWN"><option>UNKNOWN</option><option>PASS</option><option>FAIL</option></select></label>
      <label><input name="official_origin_confirmed" type="checkbox" value="true" /> Официальное происхождение документов подтверждено</label>
      <label><input name="identity_fields_confirmed" type="checkbox" value="true" /> Все поля юридического лица подтверждены</label>
      <label><input name="exact_product_link_confirmed" type="checkbox" value="true" /> Точная связь производителя с указанным товаром подтверждена</label>
      <fieldset className="border p-3"><legend className="font-bold">Цитаты, на которых основано решение</legend>{proposal.citations.map((citation, index) => <label className="mt-2 block" key={`${citation.artifact_id}-${index}`}><input name="citation_indexes" type="checkbox" value={index} /> Цитата {index + 1}: стр. {citation.page}, {citation.locator}</label>)}</fieldset>
      <label>Действует до (МСК, UTC+03:00)<input className="mt-1 block w-full border p-2" name="effective_until" type="datetime-local" /></label>
      <label>Основание решения<textarea className="mt-1 block w-full border p-2" name="rationale" maxLength={2000} required /></label>
    </div>
    <button className="mt-3 rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50" disabled={pending}>{pending ? "Сохраняю…" : "Сохранить решение"}</button>
    {state.error && <p role="alert" className="text-red-700">{state.error}</p>}
  </form>;
}
