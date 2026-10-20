import type { CharacteristicPairReport } from "../../lib/eis-characteristics";

type Evidence = { document_id: string; locator: string };
type Fact = { value: string | null; raw?: string | null; raw_truncated?: boolean; provenance: Evidence };
type Value = {
  description: Fact; minimum: Fact; minimum_operator: Fact; maximum: Fact;
  maximum_operator: Fact; unit: Fact; concrete_values: Fact[];
  concrete_values_total: number; concrete_values_truncated: boolean;
  range_source_complete?: boolean;
};
const observations = { SAME: "Записанные значения совпали", DIFFERENT: "Записанные значения различаются", UNKNOWN: "Недостаточно данных для сравнения" };
const reasons: Record<string, string> = {
  BLANK_CHARACTERISTIC_NAME: "Название характеристики отсутствует",
  DUPLICATE_OR_UNMATCHED_CHARACTERISTIC_NAME: "Нет однозначной пары по полному названию характеристики",
  INCOMPLETE_OR_TRUNCATED_SAVED_VALUES: "Сохранённые значения неполны, устарели или обрезаны",
  UNSUPPORTED_OR_INCOMPLETE_VALUE_SHAPE: "Неполные границы, смешанная структура или неподдерживаемые исходные значения требуют проверки",
  FILLING_INSTRUCTION_NOT_EXPLICITLY_EQUAL: "Инструкции заполнения не совпадают явно",
  UNITS_NOT_EXPLICITLY_EQUAL: "Единицы измерения не совпадают явно",
  MIXED_VALUE_SHAPES: "Текстовые и числовые значения нельзя сравнить этим правилом",
  EXACT_COMPLETE_STORED_VALUES_EQUAL: "Совпали явно сохранённые значения, единицы и инструкции",
  EXACT_COMPLETE_STORED_VALUES_DIFFER: "Явно сохранённые значения различаются; это не доказывает несовместимость товаров",
};
function Source({ evidence }: { evidence: Evidence }) {
  return <p className="break-all text-xs text-slate-500">XML SHA-256: {evidence.document_id} · {evidence.locator}</p>;
}
function Field({ label, fact }: { label: string; fact: Fact }) {
  return <div className="mt-1"><p>{label}: {fact.value ?? "UNKNOWN"}</p>
    {fact.raw !== null && fact.raw !== undefined && <p className="text-xs">Исходная запись: {fact.raw}{fact.raw_truncated ? " (обрезана)" : ""}</p>}
    <Source evidence={fact.provenance} />
  </div>;
}
function Values({ values }: { values: Value[] }) {
  return <div className="space-y-3">{values.length === 0 ? <p>Значения отсутствуют: UNKNOWN.</p> : values.map((value, i) =>
    <div key={i} className="rounded border border-slate-200 p-2">
      <Field label="Описание" fact={value.description} /><Field label="Единица" fact={value.unit} />
      {value.concrete_values.map((fact, j) => <Field key={j} label={`Числовое значение ${j + 1}`} fact={fact} />)}
      <p className="mt-1 text-xs">Сохранено числовых значений: {value.concrete_values.length} из {value.concrete_values_total}.
        {value.concrete_values_truncated && " Список обрезан."}</p>
      <details className="mt-2"><summary className="cursor-pointer">Исходные границы диапазона</summary>
        <p>Исходная структура границ: {value.range_source_complete === true ? "сохранена полностью" : "UNKNOWN"}.</p>
        <Field label="Минимум" fact={value.minimum} /><Field label="Оператор минимума" fact={value.minimum_operator} />
        <Field label="Максимум" fact={value.maximum} /><Field label="Оператор максимума" fact={value.maximum_operator} />
      </details>
    </div>)}</div>;
}
export function CharacteristicPairReportView({ report }: { report: CharacteristicPairReport }) {
  return <section className="mt-3 space-y-3 rounded border border-slate-200 bg-white p-3 text-sm" role="status">
    <h5 className="font-bold">Сравнение записанных характеристик</h5>
    <p>Выбранная карточка №{report.request.target.notice.purchase_number}, позиция {report.request.target.source_index};
      историческая №{report.request.candidate.notice.purchase_number}, позиция {report.request.candidate.source_index}.</p>
    <p>Характеристик в сравнении: {report.row_count}. Совпали записанные значения: {report.same_count};
      различаются: {report.different_count}; неизвестно: {report.unknown_count}.</p>
    <div className="rounded bg-amber-50 p-2">
      <p className="font-bold">Полная техническая сопоставимость: UNKNOWN · регион поставки: UNKNOWN.</p>
      <p>Прибыль: UNKNOWN · участие: UNKNOWN · охват ЕИС: UNKNOWN.</p>
      <p>Наблюдения относятся к сохранённым полям. Они не подтверждают полноту ТЗ или соответствие товара всем требованиям.</p>
      <p>Совпадение записанных диапазонов не подтверждает допуск товара. Пересечение диапазонов и пересчёт единиц здесь не выполняются.</p>
    </div>
    {[report.target, report.candidate].map((source, i) => <details key={i} className="rounded bg-slate-50 p-2">
      <summary className="cursor-pointer font-bold">{i === 0 ? "Выбранная" : "Историческая"} позиция: исходные характеристики</summary>
      <p>{source.storage_kind === "SAVED_PROJECTION" ? "Сохранённая проекция характеристик" : "Сохранённые поля извещения"}.</p>
      {source.legacy_values_unknown && <p className="font-bold text-amber-900">Устаревшая структура сохранённых значений: равенство не подтверждено.</p>}
      <p>Сохранено характеристик: {source.position.characteristics.length} из {source.position.characteristics_total}.
        {source.position.characteristics_truncated && " Список обрезан."}</p>
      {source.position.characteristics.map((c, j) => <details key={j} className="mt-2">
        <summary className="cursor-pointer">{j + 1}. {c.name.value ?? "Название UNKNOWN"}</summary>
        <Source evidence={c.name.provenance} /><Field label="Инструкция заполнения" fact={c.instruction_code} />
        <p>Сохранено вариантов значения: {c.values.length} из {c.values_total}.{c.truncated && " Список обрезан."}</p>
        <Values values={c.values} />
      </details>)}
    </details>)}
    {report.rows.length === 0 && <p>В сохранённых позициях нет характеристик для сравнения. Это не означает, что требования одинаковы.</p>}
    {report.rows.map((row, i) => <details key={i} className="rounded border border-slate-200 p-2">
      <summary className="cursor-pointer font-bold">{row.name || "Название UNKNOWN"}: {observations[row.observation]}</summary>
      <p>{Object.hasOwn(reasons, row.reason) ? reasons[row.reason] : row.reason}</p>
      <Source evidence={row.target_provenance} /><Source evidence={row.candidate_provenance} />
      <div className="mt-2 grid gap-3 md:grid-cols-2">
        <div><p className="font-bold">Выбранная позиция</p><Values values={row.target_values} /></div>
        <div><p className="font-bold">Историческая позиция</p><Values values={row.candidate_values} /></div>
      </div>
    </details>)}
    <p className="text-xs text-slate-500">Проверено: {report.checked_at}. Обращений к ЕИС: {report.source_requests}.</p>
  </section>;
}
