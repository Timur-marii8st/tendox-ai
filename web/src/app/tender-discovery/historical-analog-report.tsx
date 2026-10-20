import type { AnalogDimension, AnalogEvidence, AnalogFact, AnalogNotice, AnalogReport, AnalogRow } from "../../lib/eis-analogs";
import { characteristicRequestKey } from "../../lib/eis-characteristics";
import { CharacteristicPairPanel, type CharacteristicLoader } from "./characteristic-pair";

const dimensions: Record<AnalogDimension, string> = {
  SUBJECT: "Предмет закупки", VOLUME: "Объём", PERIOD: "Период публикации", HISTORY: "Срок подачи",
  TECHNICAL: "Технические требования", DELIVERY_REGION: "Регион поставки",
};
const noticePages = new Map([["epNotificationEF2020", "ea20"], ["epNotificationEZK2020", "zk20"], ["epNotificationEOK2020", "ok20"]]);
const reasons: Record<string, string> = {
  POSITION_NOT_PARSED: "Позиция не разобрана",
  KTRU_EXACT: "Полное совпадение КТРУ", KTRU_CONFLICT: "КТРУ различается",
  OKPD2_NAME_EXACT: "Совпадают ОКПД2 и полное нормализованное название",
  OKPD2_NAME_CONFLICT: "ОКПД2 или полное название различаются",
  CLASSIFICATION_OR_NAME_MISSING: "Не хватает классификации или названия",
  QUANTITY_OR_UNIT_MISSING_INVALID: "Количество или единица отсутствуют либо некорректны",
  UNIT_LABEL_CONFLICT: "Названия единиц различаются",
  VOLUME_HALF_TO_DOUBLE: "Количество в пределах 0,5–2 от выбранной позиции",
  VOLUME_OUTSIDE_RANGE: "Количество за пределами 0,5–2 от выбранной позиции",
  PUBLICATION_MISSING: "Дата публикации неизвестна", WITHIN_PERIOD: "Публикация в выбранном периоде",
  OUTSIDE_PERIOD: "Публикация вне выбранного периода", DEADLINE_MISSING: "Срок подачи неизвестен",
  DEADLINE_ELAPSED_ONLY: "Срок подачи истёк; это не подтверждает завершённый контракт",
  DEADLINE_NOT_ELAPSED: "Срок подачи ещё не истёк", SPECIFICATION_NOT_REVIEWED: "Технические требования не проверены",
  DELIVERY_REGION_NOT_EXTRACTED: "Регион поставки не извлечён",
  TOKEN_OVERLAP_IS_NOT_EXACT_QUERY_MATCH: "Совпадение поисковых слов не подтверждает точное соответствие запросу",
  LEXICAL_RECALL_UNKNOWN: "Полнота поиска по словам неизвестна",
  SAME_NOTICE_FAMILY_ONLY: "Выбраны карточки того же типа процедуры",
  EXPIRED_DEADLINE_IS_NOT_COMPLETED_CONTRACT: "Истёкший срок подачи не подтверждает завершение контракта",
  VOLUME_FILTER_IS_NOT_UNIT_OR_TECHNICAL_EQUIVALENCE: "Совпадение названий единиц и диапазона объёма — фильтр отбора; физическая и техническая эквивалентность неизвестна",
  TARGET_PUBLICATION_MISSING: "Нет даты публикации выбранной карточки: период и историческая выборка UNKNOWN",
};
function Source({ value }: { value: AnalogEvidence }) {
  return <p className="break-all text-xs text-slate-500">XML SHA-256: {value.document_id} · {value.locator}</p>;
}
function Fact({ label, value }: { label: string; value: AnalogFact }) {
  return <div className="mt-2"><p>{label}: {value.value ?? "UNKNOWN"}</p><Source value={value.provenance} /></div>;
}
function CardFacts({ notice, sourceIndex }: { notice: AnalogNotice; sourceIndex: number | null }) {
  const position = notice.positions.find(p => p.source_index === sourceIndex);
  return <details className="mt-2"><summary className="cursor-pointer font-bold">Исходные поля и XML-источники</summary>
    <p className="mt-2 break-all text-xs">Версия {notice.notice.version_number} · {notice.document_type} · {notice.source_member}</p>
    <Fact label="Публикация (с часовым поясом)" value={notice.published_at} />
    <Fact label="Срок подачи (с часовым поясом)" value={notice.deadline} />
    {position ? <>{(["name", "ktru", "okpd2", "quantity", "unit"] as const).map((key, i) =>
      <Fact key={key} label={["Название", "КТРУ", "ОКПД2", "Количество", "Единица"][i]} value={position[key]} />)}</> :
      <p>Позиция не разобрана: UNKNOWN.</p>}
  </details>;
}
function Row({ row, report, compareCharacteristics }: { row: AnalogRow; report: AnalogReport; compareCharacteristics?: CharacteristicLoader }) {
  const candidate = report.candidates.find(c => c.notice.purchase_number === row.notice.purchase_number)!;
  const position = candidate.positions.find(p => p.source_index === row.source_index);
  const page = noticePages.get(candidate.document_type);
  const pair = row.source_index === null ? null : {
    target: { notice: report.request.target, source_index: report.request.source_index },
    candidate: { notice: row.notice, source_index: row.source_index },
  };
  return <details className="mt-2 rounded-lg border border-slate-200 bg-white p-3">
    <summary className="cursor-pointer font-bold">{row.comparability} · №{row.notice.purchase_number} ·
      {row.source_index === null ? " позиция UNKNOWN" : ` позиция ${row.source_index}`} · {position?.name.value ?? "Название UNKNOWN"}</summary>
    {page && <a className="mt-2 inline-block text-blue-700 underline" target="_blank" rel="noreferrer"
      href={`https://zakupki.gov.ru/epz/order/notice/${page}/view/common-info.html?regNumber=${row.notice.purchase_number}`}>Карточка ЕИС по номеру (может показывать другую версию)</a>}
    <CardFacts notice={candidate} sourceIndex={row.source_index} />
    <div className="mt-3 space-y-3">{row.criteria.map(c => <div key={c.dimension} className="rounded bg-slate-50 p-2">
      <p className={c.status === "FAIL" ? "font-bold text-red-800" : "font-bold"}>{dimensions[c.dimension]}: {c.status}</p>
      <p>{Object.hasOwn(reasons, c.reason) ? reasons[c.reason] : c.reason}</p>
      <p className="mt-1 break-words">Выбранная позиция: {c.target_value ?? "UNKNOWN"} · Историческая позиция: {c.candidate_value ?? "UNKNOWN"}</p>
      <details className="mt-1"><summary className="cursor-pointer text-xs font-bold">Источники сравнения ({c.evidence.length})</summary>
        {c.evidence.map((e, i) => <Source key={i} value={e} />)}
      </details>
    </div>)}</div>
    {pair && compareCharacteristics && <CharacteristicPairPanel key={characteristicRequestKey(pair)} request={pair} load={compareCharacteristics} />}
  </details>;
}
export function HistoricalAnalogReportView({ report, compareCharacteristics }: { report: AnalogReport; compareCharacteristics?: CharacteristicLoader }) {
  const review = report.rows.filter(r => r.disposition === "NEEDS_REVIEW");
  const excluded = report.rows.filter(r => r.disposition === "EXCLUDED");
  const omitted = report.omitted_candidates ?? [];
  return <div className="mt-3 space-y-3 text-sm" role="status">
    <p className="font-bold">Историческая выборка по позиции {report.request.source_index} · запрос «{report.request.query}»</p>
    <p>Период: {report.period_start ?? "UNKNOWN"} — {report.period_end ?? "UNKNOWN"} ({report.request.lookback_days} дней до публикации выбранной карточки).
      Проверено: {report.checked_at}.</p>
    <CardFacts notice={report.target} sourceIndex={report.request.source_index} />
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
      <p>Выбрано карточек: {report.selected_notices} из лимита 20. Разобрано позиций: {report.evaluated_positions}.
        Исключено строк: {report.excluded_rows}. Требуют проверки: {report.review_rows}.</p>
      <p className="mt-1 font-bold">{report.selection_truncated ? "Выборка обрезана: есть дополнительные карточки за пределами лимита." :
        "Дополнительные карточки за пределами лимита не обнаружены; полнота всей ЕИС остаётся UNKNOWN."}</p>
      <p>Не проверено позиций за лимитом 25 на карточку: {report.uninspected_positions}.</p>
      {omitted.length > 0 && <div className="mt-2 rounded border border-amber-300 bg-white p-2">
        <p className="font-bold">Не разобрано карточек из-за размера: {omitted.length}.</p>
        <p>Эти карточки не исключены по требованиям. Их позиции и сопоставимость: UNKNOWN.</p>
        <ul className="mt-1 list-disc pl-5">{omitted.map(item => <li key={item.notice.purchase_number}>
          №{item.notice.purchase_number}, версия {item.notice.version_number}: {item.reason === "CANDIDATE_NOTICE_PAYLOAD_LIMIT" ?
            "карточка превышает лимит разбора" : "карточка не помещается в оставшийся бюджет разбора"}.
          <p>Сохранённые данные: {item.payload_bytes.toLocaleString("ru-RU")} байт;
            {item.reason === "CANDIDATE_TOTAL_PAYLOAD_LIMIT" ? " доступный остаток" : " лимит"}: {item.limit_bytes.toLocaleString("ru-RU")} байт.</p>
          <p className="break-all text-xs text-slate-500">XML SHA-256 этой версии: {item.notice.notice_xml_sha256}</p>
        </li>)}</ul>
      </div>}
      <p className="mt-1">Охват ЕИС: UNKNOWN · полнота выборки: UNKNOWN · свежесть источника: UNKNOWN.</p>
      <p>Техническая эквивалентность: UNKNOWN · регион поставки: UNKNOWN · связь с лотом: UNKNOWN.</p>
      <p>Личности поставщиков: UNKNOWN · прогноз конкуренции: UNKNOWN · прибыль: UNKNOWN · участие: UNKNOWN.</p>
      <p className="mt-1">Только сохранённые карточки того же типа процедуры; кандидаты упорядочены по публикации.
        Строки требуют проверки и не являются подтверждёнными аналогами.</p>
      <ul className="mt-2 list-disc pl-5">{report.reasons.map((reason, i) => <li key={i}>{Object.hasOwn(reasons, reason) ? reasons[reason] : reason}</li>)}</ul>
    </div>
    {report.rows.length === 0 && <p>{omitted.length > 0 ?
      "Карточки найдены, но не рассмотрены из-за ограничения размера." : "В сохранённой выборке кандидатов нет."}
      {" "}Это не подтверждает отсутствие аналогов или конкурентов в ЕИС.</p>}
    <details open={review.length > 0} className="rounded-lg bg-slate-50 p-3">
      <summary className="cursor-pointer font-bold">Требуют проверки: {review.length} · сопоставимость UNKNOWN</summary>
      {review.map(row => <Row key={`${row.notice.purchase_number}:${row.source_index}`} row={row} report={report} compareCharacteristics={compareCharacteristics} />)}
    </details>
    <details className="rounded-lg bg-slate-50 p-3">
      <summary className="cursor-pointer font-bold">Исключённые строки: {excluded.length} · сопоставимость FAIL</summary>
      {excluded.map(row => <Row key={`${row.notice.purchase_number}:${row.source_index}`} row={row} report={report} compareCharacteristics={compareCharacteristics} />)}
    </details>
    <p className="text-xs text-slate-500">Правило {report.policy_version} · обращений к ЕИС: {report.source_requests}.
      Новый подбор выполняется только кнопкой; загрузка документов не запускается.</p>
  </div>;
}
