"use client";

import { useEffect, useState, useTransition } from "react";
import type { DocumentCollectionStatus, EisEvidenceBridge, EisPreliminaryEstimate, NoticeDocumentRef } from "@/lib/procurement-api";
import type { DocumentAnalysis } from "@/lib/eis-workflow-api";
import { estimateIndexedEconomics, loadIndexedAnalysis, loadIndexedDocuments, loadIndexedEvidence, prepareIndexedDocuments } from "./actions";
import { IndexedCompetitionCriteria } from "./indexed-competition-criteria";
import { DocumentReview } from "./document-review";
import { reviewRequestKey } from "@/lib/eis-document-review";
import { PositionEvidenceView } from "./position-evidence";
import { sameProtocolRef } from "@/lib/eis-protocols";

const fetchLabel = { PENDING: "Ожидает загрузки", RECEIVED: "Получен",
  SIZE_MISMATCH: "Размер не совпал", FAILED: "Ошибка загрузки" };
const roleHint = { TECHNICAL_SPECIFICATION: "возможно, ТЗ",
  CONTRACT_DRAFT: "возможно, проект контракта", PRICE_JUSTIFICATION: "возможно, обоснование цены",
  APPLICATION_INSTRUCTIONS: "возможно, инструкция к заявке", UNKNOWN: "роль не определена" };
const gapLabel: Record<string, string> = {
  SOURCE_MANIFEST_COVERAGE_UNVERIFIED: "Полнота списка ЕИС не проверена",
  DOCUMENT_ROLES_NOT_REVIEWED: "Роли документов не подтверждены",
  DOCUMENT_JOB_NOT_REQUESTED: "Сбор документов не запрошен",
  DOCUMENT_MANIFEST_EMPTY: "Список файлов пуст",
  DOCUMENTS_NOT_RECEIVED: "Не все файлы получены",
  DOCUMENT_EXTRACTION_UNKNOWN: "Часть текста не разобрана полностью",
  LOT_XML_NOT_PARSED: "Состав лота в XML не разобран",
  REQUIREMENTS_NOT_APPROVED: "Требования не утверждены",
  COMPETITION_CRITERIA_NOT_REVIEWED: "Правила оценки конкурса не проверены",
  COMPETITION_QUALIFICATION_NOT_REVIEWED: "Квалификация участника не проверена",
  COMPETITION_SOURCE_WEIGHTS_UNKNOWN: "Исходные критерии или сумма весов требуют проверки",
};
const costGapLabel: Record<string, string> = {
  SUPPLIER_QUOTE_MISSING: "Нет действующего КП поставщика",
  ALL_IN_COSTS_MISSING: "Нет полной себестоимости и логистики",
  TAX_MODEL_MISSING: "Не задана налоговая модель",
  BASE_REALISTIC_CONSERVATIVE_MISSING: "Не рассчитаны три сценария",
};
const readGateLabel: Record<string, string> = {
  NOTICE_VERSION_STALE: "Версия карточки устарела",
  DEADLINE_EXPIRED: "Срок подачи заявки истёк",
  PROCEDURE_BLOCKED: "Подтверждена отмена или этап без подачи заявок",
};

export function IndexedDocuments({ notice }: { notice: NoticeDocumentRef }) {
  const [status, setStatus] = useState<DocumentCollectionStatus>();
  const [error, setError] = useState<string>();
  const [analyses, setAnalyses] = useState<Record<string, DocumentAnalysis>>({});
  const [evidence, setEvidence] = useState<EisEvidenceBridge>();
  const [estimate, setEstimate] = useState<EisPreliminaryEstimate>();
  const [pending, start] = useTransition();
  const { purchase_number, version_number, notice_xml_sha256 } = notice;
  const readBlocked = !!status?.read_gate?.blocked_reasons.length;

  useEffect(() => {
    if (!status?.requested || !(status.pending_count || status.analysis_pending_count) || status.version_status === "STALE" || readBlocked) return;
    let active = true;
    const timer = setInterval(async () => {
      const result = await loadIndexedDocuments({ purchase_number, version_number, notice_xml_sha256 });
      if (!active) return;
      if (result.result) setStatus(result.result);
      setError(result.error);
    }, 15_000);
    return () => { active = false; clearInterval(timer); };
  }, [purchase_number, version_number, notice_xml_sha256, status?.requested,
      status?.pending_count, status?.analysis_pending_count, status?.version_status, readBlocked]);

  function request(prepare: boolean) {
    start(async () => {
      const result = await (prepare ? prepareIndexedDocuments(notice) : loadIndexedDocuments(notice));
      setError(result.error);
      if (result.result) setStatus(result.result);
    });
  }

  return <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
    <h4 className="font-bold">Разбор комплекта документов</h4>
    <div className="mt-2 flex flex-wrap gap-2">
      <button type="button" disabled={pending || status?.version_status === "STALE" || readBlocked}
        onClick={() => request(true)} className="rounded bg-blue-700 px-3 py-2 font-bold text-white disabled:opacity-50">
        {pending ? "Подождите…" : "Скачать и разобрать документы"}
      </button>
      <button type="button" disabled={pending} onClick={() => request(false)}
        className="rounded border border-blue-300 px-3 py-2">Проверить сохранённый разбор</button>
      <button type="button" disabled={pending} onClick={() => start(async () => {
        const result = await loadIndexedEvidence(notice);
        setError(result.error);
        if (result.result) { setEvidence(result.result); setStatus(result.result.collection); }
      })} className="rounded border border-blue-300 px-3 py-2">Связать с карточкой и расчётом</button>
    </div>
    {error && <p role="alert" className="mt-2 font-bold text-red-800">{error}</p>}
    {evidence && <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
      <p className="font-bold">Связка с XML №{evidence.notice.purchase_number}, версия {evidence.notice.version_number}</p>
      {evidence.collection.version_status === "STALE" && <p className="text-red-800">Версия устарела. Повторите поиск.</p>}
      <p>НМЦК: {evidence.nmck_rub ? `${evidence.nmck_rub} ₽` : "UNKNOWN"} · крайний срок: {evidence.deadline
        ? new Date(evidence.deadline).toLocaleString("ru-RU") : "UNKNOWN"}.</p>
      {evidence.nmck_provenance && <p className="break-all text-xs text-slate-600">
        Источник НМЦК: {evidence.source_member} · XML {evidence.nmck_provenance.document_id} · {evidence.nmck_provenance.locator}</p>}
      <p>Подача: {evidence.application_status}; требования и полнота: UNKNOWN;
        экономика: {evidence.economic_status}. НМЦК не является прибылью.</p>
      {sameProtocolRef(evidence.notice, notice) && <PositionEvidenceView set={evidence.position_set} />}
      {!!evidence.lot_items.length && <p>Позиции XML: {evidence.lot_items.length};
        {" "}каждая связана с локатором в карточке.</p>}
      <ul className="mt-1 list-disc pl-5">{evidence.review_gaps.map((gap) => <li key={gap}>{gapLabel[gap] ?? gap}</li>)}</ul>
      {evidence.document_type === "epNotificationEOK2020" && <div className="my-3">
        <IndexedCompetitionCriteria value={evidence.competition_criteria} /></div>}
      <p className="mt-2 font-bold">Для расчёта не хватает:</p>
      <ul className="list-disc pl-5">{evidence.economic_missing.map((gap) => <li key={gap}>{costGapLabel[gap] ?? gap}</li>)}</ul>
      <p className="mt-2">Подсказки о ролях основаны на именах файлов и требуют проверки.</p>
      <ul className="mt-1 grid gap-2">{evidence.documents.map((document) => {
        const file = evidence.collection.documents.find((item) => item.content_uid === document.content_uid);
        return <li key={document.content_uid} className="rounded bg-white p-2">
          <p className="font-bold">{file?.filename ?? document.content_uid}: {roleHint[document.role_hint]} · статус роли UNKNOWN</p>
          {file && <p className="break-all text-xs text-slate-600">UID {document.content_uid} · SHA {file.sha256 ?? "UNKNOWN"} · {file.source_locator}</p>}
          {document.conditions_truncated && <p className="text-xs text-amber-900">Показано {document.conditions.length} из {document.conditions_total}
            {" "}сохранённых фрагментов условий. Остальные доступны через «Показать сохранённые условия».</p>}
          {document.conditions.map((condition, index) => <blockquote key={index} className="mt-1 border-l-2 border-slate-300 pl-2">
            {condition.kind}: {condition.excerpt}{condition.truncated ? "…" : ""}
            <p className="break-all text-xs text-slate-600">{condition.provenance.locator} · {condition.provenance.document_id}</p>
            {condition.context_status === "UNKNOWN" && <p className="text-xs text-amber-900">Продолжение заголовка не установлено: UNKNOWN.</p>}
            {!!condition.context?.length && <div className="mt-1 rounded bg-amber-50 p-2">
              <p className="text-xs font-bold">Следующий абзац; связь с условием требует проверки</p>
              {condition.context.map((block, blockIndex) => <div key={blockIndex}>
                <p>{block.excerpt}{block.truncated ? "…" : ""}</p>
                <p className="break-all text-xs text-slate-600">{block.provenance.locator} · {block.provenance.document_id}</p>
              </div>)}
            </div>}
          </blockquote>)}
        </li>;
      })}</ul>
      <form className="mt-3 rounded border border-blue-200 bg-white p-3" onSubmit={(event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        start(async () => {
          const result = await estimateIndexedEconomics(notice, values);
          setError(result.error);
          setEstimate(result.result);
        });
      }}>
        <p className="font-bold">Предварительная экономика по вашим затратам</p>
        <p className="mt-1 text-slate-600">Введите стоимость всего лота и все прочие расходы без НДС.
          НДС задайте долей, например 0.20. Расчёт не заменяет КП или проверку требований.</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <label>Товар, ₽ без НДС<input name="goods" required inputMode="decimal" className="mt-1 w-full rounded border p-2" /></label>
          <label>Прочие расходы, ₽ без НДС<input name="expenses" required inputMode="decimal" className="mt-1 w-full rounded border p-2" /></label>
          <label>Ставка НДС, доля<input name="vat_rate" required inputMode="decimal" placeholder="0.20" className="mt-1 w-full rounded border p-2" /></label>
        </div>
        <label className="mt-2 block">Источник оценки / допущения<input name="basis" required maxLength={2000}
          className="mt-1 w-full rounded border p-2" /></label>
        <label className="mt-2 flex items-start gap-2"><input name="costs_complete_ack" type="checkbox" className="mt-1" />
          Подтверждаю, что указал все известные расходы для предварительной оценки.</label>
        <p className="mt-1 text-xs text-slate-600">Сценарии: без снижения, снижение 5%,
          снижение 10% и рост затрат 10%. Данные не сохраняются.</p>
        <button type="submit" disabled={pending} className="mt-2 rounded bg-blue-700 px-3 py-2 font-bold text-white disabled:opacity-50">
          Посчитать три предварительных сценария</button>
      </form>
      {estimate && <div role="status" className="mt-2 rounded bg-white p-3">
        <p className="font-bold">Статус оценки: {estimate.estimate.status}; допуск и КП: UNKNOWN.</p>
        <p>{estimate.preliminary_guidance === "DO_NOT_PARTICIPATE"
          ? "Подача заблокирована сроком или подтверждённой отменой."
          : "Нужна дальнейшая проверка; участвовать пока не рекомендовано."}</p>
        {estimate.estimate.reasons.map((reason, index) => <p key={index}>{reason}</p>)}
        <ul className="mt-1 list-disc pl-5">{estimate.estimate.scenarios.map((scenario) => <li key={scenario.kind}>
          {scenario.kind}: выручка без НДС {scenario.revenue_net} ₽, затраты {scenario.costs_net} ₽,
          прибыль {scenario.profit} ₽; допущения: {scenario.assumptions.join(" ")}.
        </li>)}</ul>
      </div>}
    </div>}
    {status && <div className="mt-3">
      {readBlocked && <div role="status" className="mb-2 rounded border border-amber-300 bg-amber-50 p-2">
        <p className="font-bold">Загрузка новых файлов остановлена по известным данным карточки.</p>
        <ul className="list-disc pl-5">{status.read_gate!.blocked_reasons.map((reason) =>
          <li key={reason}>{readGateLabel[reason] ?? reason}</li>)}</ul>
        <p className="mt-1 text-xs">Проверено: {new Date(status.read_gate!.checked_at).toLocaleString("ru-RU")}.
          Сохранённые документы доступны; повторите поиск для актуальной версии.</p>
        <details className="mt-1"><summary>Источники решения</summary>
          {status.read_gate!.evidence.map((value, index) => <p key={index} className="break-all text-xs">{value}</p>)}
        </details>
      </div>}
      {status.version_status === "STALE" && <p className="font-bold text-red-800">
        Этот разбор устарел. Уже известна версия {status.current_version_number}; повторите поиск.</p>}
      <p>Получено {status.received_count} из {status.listed_count}; осталось {status.pending_count}.</p>
      {!!status.analysis_pending_count && <p className="mt-1 text-blue-900">Ещё ожидают обновлённого разбора:
        {" "}{status.analysis_pending_count}. Сохранённые файлы повторно не скачиваются.</p>}
      <p>Загрузка: {status.download_status === "COMPLETE_LISTED_SET" ? "Получены все перечисленные файлы"
        : status.download_status === "UNKNOWN_MANIFEST" ? "Список документов неизвестен"
        : status.download_status === "NOT_REQUESTED" ? "Не запрошена" : "Комплект ещё не получен"}.</p>
      <p>Извлечение: {status.extraction_status === "EXTRACTED" ? "Текст извлечён" : "Требует проверки"}.
        Полнота и review: UNKNOWN.</p>
      {status.pending_count > 0 && status.requested && !readBlocked && <p className="mt-1 text-slate-600">
        Задание сохранено. Фоновая загрузка зависит от доступности ЕИС; файлы читаются последовательно с паузой.</p>}
      <ul className="mt-2 grid gap-2">
        {status.documents.map((document) => <li key={document.content_uid} className="rounded bg-white p-3">
          <p className="font-bold">{document.filename} · {fetchLabel[document.fetch_status]}</p>
          <p>Извлечение: {document.extraction_status}; фрагментов условий: {document.condition_snippet_count};
            кандидатов требований: {document.requirement_candidate_count}.</p>
          {!!document.reasons.length && <p className="text-amber-900">{document.reasons.join(", ")}</p>}
          {document.fetch_status === "RECEIVED" && <button type="button" disabled={pending}
            className="mt-1 font-bold text-blue-700 underline" onClick={() => start(async () => {
              const result = await loadIndexedAnalysis(notice, document.content_uid);
              setError(result.error);
              if (result.result) setAnalyses((previous) => ({ ...previous, [document.content_uid]: result.result! }));
            })}>Показать сохранённые условия</button>}
          {analyses[document.content_uid] && <div className="mt-2">
            <p className="font-bold">Фрагменты для проверки; роль документа и требования ещё не утверждены.</p>
            {!analyses[document.content_uid].snippets.length && <p>Распознанных фрагментов условий нет.</p>}
            {analyses[document.content_uid].snippets.map((snippet, index) => <blockquote key={index}
              className="mt-2 border-l-2 border-slate-300 pl-2">
              <strong>{snippet.kind}</strong>: {snippet.text}
              <p className="break-all text-xs text-slate-500">{snippet.provenance.locator} · {snippet.provenance.document_id}</p>
            </blockquote>)}
          </div>}
          {document.sha256 && <p className="mt-1 break-all text-xs text-slate-500">SHA-256: {document.sha256}</p>}
          {document.fetch_status === "RECEIVED" && document.sha256 && /\.docx$/i.test(document.filename) &&
            status.version_status !== "STALE" && (() => {
              const request = { notice, content_uid: document.content_uid, expected_document_sha256: document.sha256 };
              return <DocumentReview key={reviewRequestKey(request)} request={request}
                positions={evidence && sameProtocolRef(evidence.notice, notice) ? evidence.position_set : undefined} />;
            })()}
        </li>)}
      </ul>
    </div>}
  </div>;
}
