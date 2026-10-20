import type { HistoricalProtocolReport, ProtocolEvidence, ProtocolFact } from "../../lib/eis-protocols";

const kindLabel = {
  FINAL_PROTOCOL: "Итоговый протокол конкурса",
  PLACEMENT_RESULT: "Результат размещения",
  PROPOSALS_DISTRIBUTION: "Распределение предложений",
};
const reasonLabel: Record<string, string> = {
  DEADLINE_EXPIRED: "Срок подачи заявки истёк",
  NOT_RECORDED: "Поле отсутствует",
  APPLICATION_IDS_MISSING_OR_REPEATED: "Идентификаторы заявок отсутствуют или повторяются",
  APPLICATION_LIST_ABSENT_OR_EMPTY: "Список заявок отсутствует или пуст",
  NOT_APPLICABLE: "Поле не предусмотрено для этого типа документа",
  NOT_INTERPRETED: "Поле не интерпретировано",
  INVALID_SCALAR: "Значение неоднозначно",
  INVALID_AMOUNT: "Сумма не распознана",
  INVALID_RANK: "Ранг не распознан",
  INVALID_BOOLEAN: "Значение не распознано",
  UNMAPPED_RESULT_CODE: "Код результата не интерпретирован",
  INVALID_VALUE: "Значение не распознано",
};

function Source({ value }: { value: ProtocolEvidence }) {
  return <details className="mt-1 text-xs font-normal">
    <summary className="cursor-pointer">Источник XML</summary>
    <p className="break-all">Файл: {value.source_member}</p>
    <p className="break-all">SHA-256: {value.xml_sha256}</p>
    <p className="break-all">Поле: {value.locator}</p>
    <p className="break-all">Тип: {value.document_type} · namespace: {value.namespace}</p>
  </details>;
}

function Fact<T extends string | number | boolean>({ value, yes = "Да", no = "Нет" }: {
  value: ProtocolFact<T>; yes?: string; no?: string;
}) {
  const shown = value.status === "PASS" && value.value !== null
    ? typeof value.value === "boolean" ? value.value ? yes : no : String(value.value)
    : "UNKNOWN";
  return <div><span>{shown}</span>
    {value.status === "UNKNOWN" && value.reason && <p className="text-xs text-slate-600">
      {reasonLabel[value.reason] ?? value.reason}</p>}
    <Source value={value.evidence} />
  </div>;
}

export function HistoricalProtocolReportView({ report }: { report: HistoricalProtocolReport }) {
  return <div className="mt-3 space-y-3">
    <p>№{report.notice.purchase_number} · версия извещения {report.notice.version_number}.</p>
    <details className="text-xs"><summary>Выбранная версия</summary>
      <p className="break-all">XML SHA-256 извещения: {report.notice.notice_xml_sha256}</p>
    </details>
    <p className={report.application_status === "FAIL" ? "font-bold text-red-800" : "text-amber-900"}>
      Подача заявки: {report.application_status}. Участие: {report.participation}.
    </p>
    {report.reasons.length > 0 && <ul className="list-disc pl-5">
      {report.reasons.map((reason, index) => <li key={index}>{reasonLabel[reason] ?? reason}</li>)}
    </ul>}
    <p className="rounded border border-amber-300 bg-amber-50 p-2">
      Документы связаны по номеру закупки. Применимость к выбранной версии: {report.notice_version_link}.
      Текущий этап: UNKNOWN. Личности поставщиков: UNKNOWN.
      Строки и заявки в каждом документе не являются общим числом конкурентов.
      Ранг и код результата не подтверждают подписанный контракт.
    </p>
    <p className="text-xs">Охват ЕИС: {report.coverage} · свежесть источника: {report.source_freshness} ·
      прибыль: {report.profit}. Прочитано из базы {new Date(report.checked_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} (МСК).</p>
    {!report.documents.length && <p>Поддержанные протоколы не найдены среди сохранённых документов.
      Конкуренция: UNKNOWN; отсутствие протоколов не означает отсутствие конкурентов.</p>}
    <p className="text-xs">Сохранённых сопутствующих документов: {report.metadata_documents}.
      Разобрано протоколов: {report.documents.length}.</p>
    {report.uninterpreted_document_types.length > 0 && <details>
      <summary>Типы документов без анализа полей</summary>
      <ul className="list-disc pl-5">{report.uninterpreted_document_types.map(type => <li key={type}>{type}</li>)}</ul>
    </details>}
    {report.documents.map(doc => <details key={doc.source.xml_sha256} className="rounded border border-slate-300 bg-white p-3">
      <summary className="cursor-pointer font-bold">{kindLabel[doc.document_kind]} · {doc.source.document_type}</summary>
      <Source value={doc.source} />
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <div>Номер протокола: <Fact value={doc.protocol_number} /></div>
        <div>Протокол-основание: <Fact value={doc.foundation_protocol_number} /></div>
        <div>Номер лота: <Fact value={doc.lot_number} /></div>
        <div>Строк в документе: <Fact value={doc.observed_rows} /></div>
        <div>Заявок с однозначными идентификаторами в документе: <Fact value={doc.represented_applications} /></div>
      </div>
      {doc.document_kind === "PROPOSALS_DISTRIBUTION" && <p className="mt-2 text-amber-900">
        Распределение предложений может повторять идентификаторы заявок. Строки не складываются с другими протоколами.
      </p>}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[850px] border-collapse text-left">
          <caption className="mb-2 text-left">Строки этого документа · поставщики UNKNOWN · валюта и налоги UNKNOWN</caption>
          <thead><tr>{["Строка", "ID заявки", "Допуск в протоколе", "Ранг", "Исходная сумма", "Плата за право заключения", "Код результата"]
            .map(label => <th key={label} scope="col" className="border p-2">{label}</th>)}</tr></thead>
          <tbody>{doc.applications.map(row => <tr key={row.row_number}>
            <td className="border p-2 align-top">{row.row_number}</td>
            <td className="border p-2 align-top"><Fact value={row.application_id} /></td>
            <td className="border p-2 align-top"><Fact value={row.admission} yes="Допущена" no="Не допущена" /></td>
            <td className="border p-2 align-top"><Fact value={row.rank} /></td>
            <td className="border p-2 align-top"><Fact value={row.proposal.amount} />
              <p className="mt-1 text-xs">{row.proposal.source_kind === "FINAL_PROPOSAL" ? "Итоговое предложение" :
                row.proposal.source_kind === "PROPOSAL" ? "Предложение" : "Тип суммы UNKNOWN"}</p>
              <p className="text-xs">Валюта: {row.proposal.currency}; налоги: {row.proposal.tax_basis}.</p>
            </td>
            <td className="border p-2 align-top"><Fact value={row.proposal.right_to_conclude_contract} /></td>
            <td className="border p-2 align-top"><Fact value={row.result_code} /></td>
          </tr>)}</tbody>
        </table>
      </div>
      {!doc.applications.length && <p className="mt-2">Строк заявок нет в сохранённом документе; число конкурентов UNKNOWN.</p>}
    </details>)}
  </div>;
}
