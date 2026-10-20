"use client";

import { useState, useTransition } from "react";
import { IndexedCompetitionCriteria } from "./indexed-competition-criteria";
import type { EisComparisonResult, EisIndexedLead } from "@/lib/procurement-api";
import { compareIndexed } from "./actions";

const blockerLabel = { NOTICE_VERSION_STALE: "Версия устарела",
  DEADLINE_EXPIRED: "Срок подачи истёк", PROCEDURE_BLOCKED: "Процедура заблокирована" };
const conditionKinds = ["Поставка", "Оплата", "Обеспечение", "Ограничения", "Ответственность", "Количество"];
const gapLabel: Record<string, string> = {
  SOURCE_MANIFEST_COVERAGE_UNVERIFIED: "Проверить полноту списка файлов в ЕИС",
  DOCUMENT_ROLES_NOT_REVIEWED: "Подтвердить роли документов",
  DOCUMENT_JOB_NOT_REQUESTED: "Запросить документы этой карточки",
  DOCUMENT_MANIFEST_EMPTY: "Найти список документов",
  DOCUMENTS_NOT_RECEIVED: "Дождаться получения всех перечисленных файлов",
  DOCUMENT_EXTRACTION_UNKNOWN: "Проверить неполностью разобранный текст",
  LOT_XML_NOT_PARSED: "Проверить состав лота",
  REQUIREMENTS_NOT_APPROVED: "Подтвердить полный набор требований",
};

function key(lead: EisIndexedLead) { return `${lead.purchase_number}:${lead.xml_sha256}`; }

export function IndexedComparison({ leads }: { leads: EisIndexedLead[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<EisComparisonResult>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const chosen = leads.filter((lead) => selected.includes(key(lead)));

  return <section aria-label="Сравнение закупок" className="rounded-xl border border-blue-300 bg-blue-50 p-4 text-sm">
    <h3 className="text-lg font-black">Сравнение выбранных закупок</h3>
    <p className="mt-1">Выберите 2–3 карточки. Сравнение использует сохранённые документы и условия;
      порядок доходности остаётся UNKNOWN до получения полного КП и расчёта затрат.</p>
    <details className="mt-2" open>
      <summary className="cursor-pointer font-bold">Выбрать карточки из результатов ({chosen.length} из 3)</summary>
      <div className="mt-2 grid max-h-52 gap-2 overflow-y-auto rounded bg-white p-3">
        {leads.map((lead) => <label key={key(lead)} className="flex items-start gap-2">
          <input type="checkbox" checked={selected.includes(key(lead))}
            disabled={pending || (chosen.length >= 3 && !selected.includes(key(lead)))}
            onChange={(event) => {
              setSelected(event.target.checked ? [...selected, key(lead)] : selected.filter((value) => value !== key(lead)));
              setResult(undefined); setError(undefined);
            }} />
          <span>№{lead.purchase_number} · {lead.title} · версия {lead.version_number}</span>
        </label>)}
      </div>
    </details>
    <button type="button" disabled={pending || chosen.length < 2} className="mt-3 rounded bg-blue-700 px-3 py-2 font-bold text-white disabled:opacity-50"
      onClick={() => start(async () => {
        const response = await compareIndexed(chosen.map((lead) => ({purchase_number:lead.purchase_number,
          version_number:lead.version_number, notice_xml_sha256:lead.xml_sha256})));
        setResult(response.result); setError(response.error);
      })}>{pending ? "Сравниваю карточки…" : "Сравнить выбранные карточки"}</button>
    {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
    {result && <div role="status" className="mt-3">
      <p>Сравнение предварительное · расчётное время {new Date(result.checked_at).toLocaleString("ru-RU")}.</p>
      <p>Охват всей ЕИС: {result.coverage}; порядок по прибыли: {result.profit_order_status}.
        Показан порядок выбора; НМЦК не является прибылью.</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[700px] border-collapse bg-white text-left align-top">
          <caption className="sr-only">Сроки, лоты, документы и условия выбранных закупок</caption>
          <thead><tr><th className="border p-3">Параметр</th>{result.rows.map(({evidence}) =>
            <th key={evidence.notice.purchase_number} className="min-w-64 border p-3">
              №{evidence.notice.purchase_number}<br />{evidence.title}<br />Версия {evidence.notice.version_number}
              <details className="mt-1 font-normal"><summary>Источник карточки</summary>
                <p className="break-all text-xs">{evidence.source_member} · XML {evidence.notice.notice_xml_sha256}</p>
              </details>
            </th>)}</tr></thead>
          <tbody>
            <tr><th className="border p-3">Готовность к дальнейшему анализу</th>{result.rows.map((row) =>
              <td key={row.evidence.notice.purchase_number} className="border p-3 align-top">
                <strong>{row.readiness_status === "BLOCKED" ? "Заблокировано" : "Нужна проверка"}</strong>
                {row.blocking_reasons.map((reason) => <p key={reason} className="text-red-800">{blockerLabel[reason]}</p>)}
                <ul className="mt-1 list-disc pl-4">{row.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                <details><summary>Срок и статус: основания</summary>{row.evidence.application_reasons.map((reason,index) =>
                  <p key={index} className="text-xs">{reason}</p>)}</details>
              </td>)}</tr>
            <tr><th className="border p-3">НМЦК</th>{result.rows.map(({evidence}) =>
              <td key={evidence.notice.purchase_number} className="border p-3 align-top">{evidence.nmck_rub ?? "UNKNOWN"} ₽
                {evidence.nmck_provenance && <p className="break-all text-xs">{evidence.nmck_provenance.locator}
                  {" "}· {evidence.nmck_provenance.document_id}</p>}
              </td>)}</tr>
            <tr><th className="border p-3">Подача заявки до</th>{result.rows.map(({evidence,deadline_provenance}) =>
              <td key={evidence.notice.purchase_number} className="border p-3 align-top">{evidence.deadline
                ? new Date(evidence.deadline).toLocaleString("ru-RU") : "UNKNOWN"}
                {deadline_provenance && <p className="break-all text-xs">{deadline_provenance.locator}
                  {" "}· {deadline_provenance.document_id}</p>}
              </td>)}</tr>
            <tr><th className="border p-3">Критерии конкурса</th>{result.rows.map(({evidence}) =>
              <td key={evidence.notice.purchase_number} className="border p-3 align-top">
                <IndexedCompetitionCriteria value={evidence.competition_criteria} />
              </td>)}</tr>
            <tr><th className="border p-3">Состав лота</th>{result.rows.map(({evidence}) =>
              <td key={evidence.notice.purchase_number} className="border p-3 align-top">
                {!evidence.lot_items.length ? "UNKNOWN" : <details><summary>Позиций: {evidence.lot_items.length}</summary>
                  {evidence.lot_items.map((item) => <div key={item.locator} className="mt-2">
                    <p>{item.name} · {item.quantity ?? "UNKNOWN"} {item.unit ?? "единица UNKNOWN"}</p>
                    <p className="break-all text-xs">{item.locator} · {evidence.notice.notice_xml_sha256}</p>
                  </div>)}
                </details>}
              </td>)}</tr>
            <tr><th className="border p-3">Документы и полнота</th>{result.rows.map(({evidence}) =>
              <td key={evidence.notice.purchase_number} className="border p-3 align-top">
                Получено {evidence.collection.received_count} из {evidence.collection.listed_count} перечисленных файлов.
                <p>Ожидает разбора: {evidence.collection.analysis_pending_count ?? 0}.</p>
                <p>Полнота и требования: UNKNOWN.</p>
                <details><summary>Что ещё проверить</summary>{evidence.review_gaps.map((gap) =>
                  <p key={gap} className="text-xs">{gapLabel[gap] ?? gap}</p>)}</details>
              </td>)}</tr>
            {conditionKinds.map((kind) => <tr key={kind}><th className="border p-3">{kind}</th>
              {result.rows.map(({evidence}) => {
                const conditions = evidence.documents.flatMap((document) => document.conditions.filter((item) => item.kind === kind));
                return <td key={evidence.notice.purchase_number} className="border p-3 align-top">
                  {!conditions.length ? "UNKNOWN: сохранённых фрагментов нет" : <details>
                    <summary>Фрагментов для проверки: {conditions.length}</summary>
                    {conditions.map((condition,index) => <blockquote key={index} className="mt-2 border-l-2 border-amber-300 pl-2">
                      <p>{condition.excerpt}{condition.truncated ? "…" : ""}</p>
                      <p className="break-all text-xs">{condition.provenance.locator} · {condition.provenance.document_id}</p>
                      {condition.context?.map((block,blockIndex) => <div key={blockIndex} className="mt-1 bg-amber-50 p-2">
                        <p className="text-xs font-bold">Следующий абзац; связь требует проверки</p>
                        <p>{block.excerpt}{block.truncated ? "…" : ""}</p>
                        <p className="break-all text-xs">{block.provenance.locator} · {block.provenance.document_id}</p>
                      </div>)}
                    </blockquote>)}
                    {evidence.documents.some((document) => document.conditions_truncated) &&
                      <p className="mt-2 text-xs text-amber-900">Это ограниченная сводка. Все сохранённые фрагменты доступны в разборе документов карточки.</p>}
                  </details>}
                </td>;
              })}</tr>)}
          </tbody>
        </table>
      </div>
    </div>}
  </section>;
}
