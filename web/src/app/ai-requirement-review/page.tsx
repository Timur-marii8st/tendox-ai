import type { Metadata } from "next";
import Link from "next/link";

import { AiRequirementDecisionForm, type ReviewCandidate } from "./decision-form";
import {
  loadAiRequirementReview,
  loadAiRequirementReviews,
  type AiCandidateDecision,
  type AiEvidenceClaim,
  type AiItemCandidate,
  type AiRequirementCandidate,
  type AiRequirementReviewDetail,
  type AiRequirementReviewSummary,
  type AiSourceBlock,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Проверка AI-разбора ТЗ — Syurai Procurement",
  description: "Изолированная проверка evidence-bound кандидатов AI-разбора технического задания",
};

function stamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "время не передано API"
    : new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function Evidence({ blocks }: { blocks: AiSourceBlock[] }) {
  return (
    <ul className="mt-2 grid gap-2 p-0">
      {blocks.map((block) => (
        <li className="rounded-lg border border-slate-200 bg-white p-3" key={block.block_id}>
          <p className="m-0 text-xs font-black text-slate-700">
            {block.block_id} · {block.provenance.document_id} · {block.provenance.locator}
          </p>
          <p className="mb-0 mt-1 whitespace-pre-wrap break-words text-sm leading-6">{block.text}</p>
        </li>
      ))}
    </ul>
  );
}

function Claim({ label, claim }: { label: string; claim: AiEvidenceClaim | null }) {
  if (!claim) return <p className="m-0 text-sm text-slate-500">{label}: не найдено</p>;
  return (
    <div>
      <p className="m-0 text-sm"><strong>{label}:</strong> {claim.raw_value ?? claim.value ?? "не найдено"}</p>
      <Evidence blocks={claim.evidence} />
    </div>
  );
}

function RequirementCandidate({ candidate }: { candidate: AiRequirementCandidate }) {
  const value = Array.isArray(candidate.value) ? candidate.value.join("; ") : candidate.value;
  return (
    <article className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <p className="m-0 break-all text-xs font-black text-blue-800">{candidate.candidate_id}</p>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="font-bold">Позиция</dt><dd>{candidate.item_name ?? "не определена"}</dd></div>
        <div><dt className="font-bold">Свойство</dt><dd>{candidate.property}</dd></div>
        <div><dt className="font-bold">Условие</dt><dd>{candidate.operator} {value ?? ""} {candidate.unit ?? ""}</dd></div>
        <div><dt className="font-bold">Обязательность</dt><dd>{candidate.mandatory == null ? "UNKNOWN" : candidate.mandatory ? "да" : "нет"}</dd></div>
      </dl>
      {candidate.uncertainties.length > 0 && (
        <p className="mb-0 mt-3 text-sm text-amber-900"><strong>Неопределённости:</strong> {candidate.uncertainties.join("; ")}</p>
      )}
      <Evidence blocks={candidate.evidence} />
    </article>
  );
}

function ItemCandidate({ candidate }: { candidate: AiItemCandidate }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <p className="m-0 break-all text-xs font-black text-blue-800">{candidate.candidate_id}</p>
      <div className="mt-3 grid gap-4">
        <Claim label="Наименование" claim={candidate.item_name} />
        {candidate.okpd2_codes.map((claim, index) => <Claim key={`okpd2:${index}`} label="ОКПД2" claim={claim} />)}
        {candidate.ktru_codes.map((claim, index) => <Claim key={`ktru:${index}`} label="КТРУ" claim={claim} />)}
        <Claim label="Единица" claim={candidate.unit} />
        <Claim label="Количество" claim={candidate.quantity} />
      </div>
      {candidate.uncertainties.length > 0 && (
        <p className="mb-0 mt-3 text-sm text-amber-900"><strong>Неопределённости:</strong> {candidate.uncertainties.join("; ")}</p>
      )}
    </article>
  );
}

function ReadOnlyDecision({ decisions }: { decisions: AiCandidateDecision[] }) {
  return (
    <section className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <h3 className="m-0 text-base font-black">Терминальная проверка — только чтение</h3>
      {decisions.length === 0 ? (
        <p className="mb-0 mt-2 text-sm">Зафиксирована пустая проверка COMPLETE-run без кандидатов.</p>
      ) : (
        <ul className="mb-0 mt-3 grid gap-2 p-0">
          {decisions.map((decision) => (
            <li className="rounded-lg border border-emerald-200 bg-white p-3 text-sm" key={`${decision.candidate_kind}:${decision.candidate_id}`}>
              <strong>{decision.candidate_id} · {decision.disposition}</strong>
              <p className="mb-0 mt-1 whitespace-pre-wrap break-words">{decision.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RunLink({ run, selected }: { run: AiRequirementReviewSummary; selected: boolean }) {
  return (
    <Link
      className={`block rounded-xl border p-3 text-sm ${selected ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-300"}`}
      href={`/ai-requirement-review?run=${encodeURIComponent(run.run_id)}`}
    >
      <span className="block break-all font-black">{run.run_id}</span>
      <span className="mt-1 block text-xs text-slate-600">{run.model} · {stamp(run.submitted_at)}</span>
      <span className={`mt-2 inline-block rounded-full px-2 py-1 text-xs font-black ${run.reviewed ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-900"}`}>
        {run.reviewed ? "REVIEWED" : "PENDING"}
      </span>
    </Link>
  );
}

function Detail({ detail }: { detail: AiRequirementReviewDetail }) {
  const candidates: ReviewCandidate[] = [
    ...detail.requirement_candidates.map((candidate) => ({
      kind: "REQUIREMENT" as const,
      id: candidate.candidate_id,
      label: candidate.item_name ? `${candidate.item_name}: ${candidate.property}` : candidate.property,
    })),
    ...detail.procurement_item_candidates.map((candidate) => ({
      kind: "PROCUREMENT_ITEM" as const,
      id: candidate.candidate_id,
      label: candidate.item_name.value ?? "Позиция закупки",
    })),
  ];

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <p className="m-0 text-xs font-black uppercase tracking-[.14em] text-blue-700">Exact persisted evidence</p>
          <h2 className="mt-1 break-all text-xl font-black">{detail.run_id}</h2>
        </div>
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-black text-amber-900">COMPLETENESS UNKNOWN</span>
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="font-bold">Source document</dt><dd className="break-all">{detail.source_document_id}</dd></div>
        <div><dt className="font-bold">Model</dt><dd className="break-words">{detail.model}</dd></div>
        <div><dt className="font-bold">Execution</dt><dd>{detail.execution_status}</dd></div>
        <div><dt className="font-bold">Submitted</dt><dd>{stamp(detail.submitted_at)} · {detail.submitted_by}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Source SHA-256</dt><dd className="break-all font-mono text-xs">{detail.source_sha256}</dd></div>
        <div className="sm:col-span-2"><dt className="font-bold">Evidence SHA-256</dt><dd className="break-all font-mono text-xs">{detail.evidence_sha256}</dd></div>
      </dl>

      <aside className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
        Принятые кандидаты остаются review evidence. Они не становятся исполняемыми требованиями,
        позициями закупки или разрешением на участие. Полнота документа остаётся UNKNOWN.
      </aside>

      <section className="mt-6">
        <h3 className="m-0 text-base font-black">Кандидаты требований ({detail.requirement_candidates.length})</h3>
        <div className="mt-3 grid gap-3">
          {detail.requirement_candidates.length
            ? detail.requirement_candidates.map((candidate) => <RequirementCandidate candidate={candidate} key={candidate.candidate_id} />)
            : <p className="m-0 text-sm text-slate-500">Кандидаты требований отсутствуют.</p>}
        </div>
      </section>

      <section className="mt-6">
        <h3 className="m-0 text-base font-black">Кандидаты позиций ({detail.procurement_item_candidates.length})</h3>
        <div className="mt-3 grid gap-3">
          {detail.procurement_item_candidates.length
            ? detail.procurement_item_candidates.map((candidate) => <ItemCandidate candidate={candidate} key={candidate.candidate_id} />)
            : <p className="m-0 text-sm text-slate-500">Кандидаты позиций отсутствуют.</p>}
        </div>
      </section>

      {detail.reviewed && detail.candidate_decisions
        ? <ReadOnlyDecision decisions={detail.candidate_decisions} />
        : detail.reviewed
          ? <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-900" role="alert">API вернул reviewed-run без терминальных решений; повторная отправка заблокирована.</p>
          : detail.execution_status !== "COMPLETE"
            ? <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-950">Запуск не завершён: terminal review запрещён до статуса COMPLETE.</p>
            : <AiRequirementDecisionForm
                candidates={candidates}
                evidenceSha256={detail.evidence_sha256}
                key={detail.run_id}
                runId={detail.run_id}
              />}
    </article>
  );
}

export default async function AiRequirementReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ run?: string | string[] }>;
}) {
  const data = await loadAiRequirementReviews();
  const requested = (await searchParams).run;
  const requestedId = typeof requested === "string" ? requested : null;
  const selectedSummary =
    data.reviews.find((run) => run.run_id === requestedId) ??
    data.reviews.find((run) => !run.reviewed) ??
    data.reviews[0] ??
    null;

  let detail: AiRequirementReviewDetail | null = null;
  let detailFailed = false;
  if (selectedSummary) {
    try {
      detail = await loadAiRequirementReview(selectedSummary.run_id);
    } catch {
      detailFailed = true;
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1280px,calc(100%-1rem))] py-6 sm:w-[min(1280px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S4 · independent reviewer</p>
          <div className="mt-2 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="m-0 text-3xl font-black tracking-tight sm:text-5xl">Проверка AI-разбора ТЗ</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                Reviewer видит только типизированных кандидатов и точное source evidence. Provider transcript,
                импорт и запуск модели в этом интерфейсе недоступны.
              </p>
            </div>
            <nav aria-label="Разделы пилота" className="flex flex-wrap gap-4 text-sm font-bold">
              <Link className="text-blue-700 hover:underline" href="/">Дела</Link>
              <Link className="text-blue-700 hover:underline" href="/completeness-review">Проверка полноты</Link>
              <Link className="text-blue-700 hover:underline" href="/document-search">Поиск документов</Link>
            </nav>
          </div>
        </header>

        <aside className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
          Экран использует отдельный server-only <code>PROCUREMENT_AI_REQUIREMENTS_REVIEWER_TOKEN</code> роли
          <code> AI_REQUIREMENTS_REVIEWER</code>. Токен, API URL и выбор credentials не попадают в браузер.
        </aside>

        {data.error && (
          <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-900" role="alert">
            {data.error === "configuration"
              ? "Reviewer API не настроен: нужны PROCUREMENT_API_URL и отдельный PROCUREMENT_AI_REQUIREMENTS_REVIEWER_TOKEN."
              : "Очередь AI requirement review временно недоступна."}
          </p>
        )}

        {!data.error && data.reviews.length === 0 && (
          <section className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-600">
            В текущем tenant нет доступных AI requirement runs.
          </section>
        )}

        {!data.error && data.reviews.length > 0 && (
          <div className="mt-6 grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
            <aside className="grid content-start gap-3" aria-label="Очередь AI requirement review">
              {data.reviews.map((run) => <RunLink key={run.run_id} run={run} selected={run.run_id === selectedSummary?.run_id} />)}
            </aside>
            {detailFailed || !detail
              ? <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-900" role="alert">Exact evidence выбранного запуска временно недоступен.</p>
              : <Detail detail={detail} />}
          </div>
        )}
      </div>
    </main>
  );
}
