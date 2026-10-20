import { randomUUID } from "node:crypto";
import Link from "next/link";
import { readManufacturerDirectory } from "@/lib/manufacturer-directory-api";
import { readManufacturerRfq } from "@/lib/manufacturer-rfq-api";
import { readManufacturerDecision, readManufacturerProposal } from "@/lib/procurement-api";
import { UUID_PATTERN } from "@/lib/manufacturer-review";
import { ManufacturerRfqForm } from "./form";

export default async function Page({ searchParams }: { searchParams: Promise<{ proposal?: string; draft?: string }> }) {
  const query = await searchParams;
  const draft = typeof query.draft === "string" && UUID_PATTERN.test(query.draft) ? await readManufacturerRfq(query.draft).catch(() => null) : null;
  const proposal = typeof query.proposal === "string" && UUID_PATTERN.test(query.proposal) ? await readManufacturerProposal(query.proposal).catch(() => null) : null;
  const decision = proposal ? await readManufacturerDecision(proposal.proposal_id, proposal).catch(() => null) : null;
  const directory = proposal && decision?.current_status === "PASS" ? await readManufacturerDirectory(proposal.dossier.run_id, proposal.dossier.response_sha256).catch(() => null) : null;
  const record = directory?.records.find(item => item.record_id === proposal?.dossier.record_id && item.status === "PASS");
  const evidence = record?.review_evidence.find(item => item.proposal_id === proposal?.proposal_id && item.decision_id === decision?.decision.decision_id && item.current_status === "PASS");
  const group = directory?.groups.find(item => item.status === "PASS" && !!record && item.record_ids.includes(record.record_id) && !!proposal && item.proposal_ids.includes(proposal.proposal_id) && !!evidence?.decision_sha256 && item.decision_sha256s.includes(evidence.decision_sha256));
  const eligible = !!proposal && !!decision && directory?.coverage === "COMPLETE" && !!record && !!evidence && !!group;
  return <main className="min-h-screen bg-slate-50 p-6"><div className="mx-auto max-w-4xl">
    <Link className="text-blue-700 underline" href="/manufacturer-review">К независимой проверке</Link>
    <h1 className="mt-4 text-3xl font-black">Черновик RFQ производителю</h1>
    <p>Создаётся внутренний неизменяемый текст. Контакт не определён, отправка не выполняется.</p>
    {query.draft && !draft && <p role="alert" className="text-red-700">Черновик не найден, недоступен или не прошёл проверку целостности.</p>}
    {draft && <section className="mt-6 rounded-xl border bg-white p-5"><h2 className="text-xl font-black">{draft.draft.manufacturer_identity.legal_name}</h2><p><b>Статус документа:</b> {draft.draft.status} · <b>текущая применимость производителя:</b> {draft.current_status}</p><p className="font-bold text-amber-800">НЕ ОТПРАВЛЕНО. Контакт: UNKNOWN. КП: UNKNOWN. Техническое соответствие: UNKNOWN. Участие: UNKNOWN.</p><p>{draft.draft.registry_snapshot.product_name} · реестровая запись {draft.draft.registry_snapshot.registry_number}</p><p>Количество: {draft.draft.quantity} {draft.draft.unit.value}</p><p>Основание: {draft.draft.quantity_basis.value}</p><h3 className="mt-4 font-bold">Требования оператора, не полное ТЗ</h3><ol className="list-decimal pl-6">{draft.draft.requirements.map((item, index) => <li key={index}>{item.value}</li>)}</ol><p>Поставка: {draft.draft.delivery_address.value}; {draft.draft.desired_delivery.value}</p><p>Ответить до: {draft.draft.reply_due_at}</p><p className="break-all text-sm">Draft SHA-256: {draft.draft.draft_sha256}<br />Text SHA-256: {draft.draft.text_sha256}<br />Decision SHA-256: {draft.draft.decision_sha256}</p><a className="font-bold text-blue-700 underline" href={`/manufacturer-rfq/${draft.draft.draft_id}/text`}>Скачать текст черновика</a><details className="mt-4"><summary>Точный сохранённый текст</summary><pre className="mt-2 whitespace-pre-wrap rounded bg-slate-100 p-3">{draft.draft.text}</pre></details></section>}
    {query.proposal && !proposal && <p role="alert" className="text-red-700">Предложение проверки не найдено или некорректно.</p>}
    {proposal && !eligible && <p role="alert" className="mt-5 text-red-700">RFQ заблокирован: выбранная запись, решение и объединённая identity-группа не имеют текущего PASS в полном directory snapshot.</p>}
    {eligible && decision && <section className="mt-5"><p><b>Проверенный производитель:</b> {group.legal_name} · {record.product_name}</p><p>Decision: {decision.decision.decision_id}; текущий статус PASS.</p><ManufacturerRfqForm commandId={randomUUID()} runId={proposal.dossier.run_id} recordId={proposal.dossier.record_id} proposalId={proposal.proposal_id} decisionId={decision.decision.decision_id} /></section>}
    {!query.proposal && !query.draft && <p className="mt-5">Откройте эту страницу из предложения производителя с текущим PASS.</p>}
  </div></main>;
}
