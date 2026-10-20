import { randomUUID } from "node:crypto";
import Link from "next/link";
import { ApiError, listManufacturerProposals, readManufacturerArtifactMetadata, readManufacturerDecision, readManufacturerProposal } from "@/lib/procurement-api";
import { UUID_PATTERN, type ManufacturerArtifact } from "@/lib/manufacturer-review";
import { DecisionForm, ReviewForm } from "./form";

const recordPattern = /^[0-9a-f]{24}$/;
const statusStyle = { PASS: "bg-emerald-100 text-emerald-900", FAIL: "bg-red-100 text-red-900", UNKNOWN: "bg-amber-100 text-amber-900" } as const;

export default async function Page({ searchParams }: { searchParams: Promise<{ run?: string; record?: string; proposal?: string }> }) {
  const query = await searchParams;
  const listed = await listManufacturerProposals().then(list => ({ list, error: null as string | null })).catch(() => ({ list: [], error: "Список предложений сейчас недоступен." }));
  const { list, error: listError } = listed;
  const proposalRequested = typeof query.proposal === "string";
  const proposal = proposalRequested && UUID_PATTERN.test(query.proposal!) ? await readManufacturerProposal(query.proposal!).catch(() => null) : null;
  let decision = null;
  let decisionError: string | null = null;
  if (proposal) {
    const result = await readManufacturerDecision(proposal.proposal_id, proposal).then(value => ({ value, error: null as string | null })).catch((error) => error instanceof ApiError && error.status === 404 ? ({ value: null, error: null }) : ({ value: null, error: "Сохранённое решение не удалось прочитать. Повторная запись заблокирована." }));
    decision = result.value; decisionError = result.error;
  }
  let artifacts: ManufacturerArtifact[] = [];
  let artifactError: string | null = null;
  if (proposal) {
    const ids = [...new Set(proposal.citations.map(citation => citation.artifact_id))];
    const results = await Promise.allSettled(ids.map(id => readManufacturerArtifactMetadata(proposal.proposal_id, id, proposal.citations.find(citation => citation.artifact_id === id)?.artifact_sha256)));
    artifacts = results.flatMap(result => result.status === "fulfilled" ? [result.value] : []);
    if (artifacts.length !== ids.length) artifactError = "Метаданные одного или нескольких документов недоступны reviewer. Решение следует оставить UNKNOWN.";
  }
  const ready = typeof query.run === "string" && UUID_PATTERN.test(query.run) && typeof query.record === "string" && recordPattern.test(query.record);
  return <main className="min-h-screen bg-slate-50 p-6"><div className="mx-auto max-w-4xl">
    <Link className="text-blue-700 underline" href="/manufacturer-search">К поиску производителей</Link>
    <h1 className="mt-4 text-3xl font-black">Независимая проверка производителя</h1>
    <p>Заявление реестра не подтверждает юридическое лицо или роль производителя. Без независимых документов статус остаётся UNKNOWN.</p>
    {ready && <ReviewForm runId={query.run!} recordId={query.record!} uploadCommandId={randomUUID()} proposalCommandId={randomUUID()} />}
    {(query.run || query.record) && !ready && <p role="alert" className="mt-4 text-red-700">Ссылка на поисковый результат некорректна.</p>}
    {proposalRequested && !proposal && <p role="alert" className="mt-4 text-red-700">Предложение не найдено или недоступно.</p>}
    {proposal && <section className="mt-6 rounded-xl border bg-white p-4">
      <h2 className="text-xl font-black">{proposal.claimed_identity.legal_name}</h2>
      <dl className="grid gap-1 text-sm"><div><dt className="inline font-bold">Идентификатор:</dt> <dd className="inline">{proposal.claimed_identity.identifier_scheme} {proposal.claimed_identity.registration_id}, {proposal.claimed_identity.country_code}</dd></div><div><dt className="inline font-bold">Предложил:</dt> <dd className="inline">{proposal.proposed_by}</dd></div><div><dt className="inline font-bold">Proposal SHA-256:</dt> <dd className="inline break-all">{proposal.proposal_sha256}</dd></div><div><dt className="inline font-bold">Источник:</dt> <dd className="inline">{proposal.dossier.product_name} · {proposal.dossier.source_manufacturer_name} · запись {proposal.dossier.registry_number}</dd></div></dl>
      <h3 className="mt-5 font-black">Документы и цитаты</h3>
      {artifactError && <p role="alert" className="text-red-700">{artifactError}</p>}
      {proposal.citations.map((citation, index) => { const artifact = artifacts.find(item => item.artifact_id === citation.artifact_id); return <article className="mt-3 rounded border p-3" key={`${citation.artifact_id}-${index}`}><p><b>Цитата {index + 1}:</b> стр. {citation.page}, {citation.locator}</p><blockquote className="border-l-4 pl-3">{citation.quote}</blockquote><p>Факты: {citation.claims.map(claim => claimLabels[claim]).join(", ")}</p><p className="break-all">Citation SHA-256: {citation.artifact_sha256}</p>{artifact && <><p><b>Заявленный источник:</b> <a className="text-blue-700 underline" href={artifact.source_url} rel="noreferrer" target="_blank">{artifact.source_title}</a></p><p>Загрузил: {artifact.uploaded_by} · origin: {artifact.origin_status}</p><p className="break-all">Artifact SHA-256: {artifact.sha256} {artifact.sha256 === citation.artifact_sha256 ? "(совпадает)" : "(НЕ СОВПАДАЕТ)"}</p><a className="font-bold text-blue-700 underline" href={`/manufacturer-review/artifacts/${proposal.proposal_id}/${artifact.artifact_id}`}>Скачать исходный PDF</a></>}</article>; })}
      {decision ? <section className="mt-5 rounded-xl border-2 p-4"><h3 className="font-black">Сохранённое решение</h3><p><span className={`rounded px-2 py-1 font-bold ${statusStyle[decision.current_status]}`}>Текущий статус: {decision.current_status}</span></p><p>Identity: {decision.decision.identity_status} · роль: {decision.decision.role_status}</p><p>Reviewer: {decision.decision.reviewed_by} · сохранено {decision.decision.reviewed_at}</p><p>Действует до: {decision.decision.effective_until ?? "не задано"}</p><p>{decision.decision.rationale}</p><p className="break-all">Decision SHA-256: {decision.decision.decision_sha256}</p><p className="font-bold">Решение окончательное и доступно только для чтения.</p></section> : decisionError ? <p role="alert" className="mt-5 text-red-700">{decisionError}</p> : artifactError ? <p className="mt-5 font-bold text-red-700">Решение заблокировано до доступности и совпадения metadata всех PDF.</p> : <DecisionForm proposal={proposal} decisionCommandId={randomUUID()} />}
    </section>}
    <h2 className="mt-8 font-black">Последние предложения</h2>
    {listError && <p role="alert" className="text-red-700">{listError}</p>}
    {!listError && list.length === 0 && <p>Сохранённых предложений пока нет.</p>}
    {list.map(item => <Link className="mt-2 block border bg-white p-3" href={`/manufacturer-review?proposal=${item.proposal_id}`} key={item.proposal_id}>{item.legal_name} · {item.decision_status ?? "ожидает проверки"}</Link>)}
  </div></main>;
}

const claimLabels = { LEGAL_NAME: "юридическое наименование", COUNTRY: "страна", IDENTIFIER_SCHEME: "схема идентификатора", REGISTRATION_ID: "регистрационный номер", MANUFACTURER_ROLE: "роль производителя" } as const;
