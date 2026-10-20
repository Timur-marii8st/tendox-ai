import type { PositionEvidenceSet, PositionFact, Provenance } from "@/lib/procurement-api";
import { SupplierSearch } from "./supplier-search";
import { supplierSearchRequestKey } from "@/lib/eis-supplier-search";

function Source({ provenance }: { provenance: Provenance }) {
  return <details className="text-xs"><summary>Источник значения</summary>
    <p className="break-all">{provenance.document_id} · {provenance.locator}</p></details>;
}
function Fact({ label, fact }: { label: string; fact: PositionFact }) {
  return <div><p>{label}: {fact.value ?? "UNKNOWN"}</p><Source provenance={fact.provenance} /></div>;
}

export function PositionEvidenceView({ set }: { set?: PositionEvidenceSet | null }) {
  if (!set) return <p className="text-sm">Структурированные характеристики: UNKNOWN.</p>;
  return <section aria-label={`Позиции и характеристики ${set.law}-ФЗ ${set.purchase_number}`}
    className="mt-3 min-w-0 rounded border bg-white p-3 text-sm">
    <h5 className="font-bold">Позиции и характеристики из источника</h5>
    <p>Показано {set.positions.length} из {set.positions_total} позиций.
      {set.positions_truncated && " Список сокращён."}</p>
    <p>Полнота спецификации и проверка требований: UNKNOWN.</p>
    {set.positions.map(p => <details key={p.source_index} className="mt-2 rounded border p-2">
      <summary>Позиция {p.source_index}{p.lot_index !== null && ` · лот ${p.lot_ordinal?.value ?? p.lot_index}`}:
        {" "}{p.name.value ?? "Название UNKNOWN"} · {p.quantity.value ?? "Количество UNKNOWN"} {p.unit.value ?? "Единица UNKNOWN"}</summary>
      <Fact label="Название" fact={p.name} /><Fact label="Количество" fact={p.quantity} />
      <Fact label="Единица в источнике" fact={p.unit} /><Fact label="Код классификации" fact={p.classification_code} />
      <Fact label="КТРУ" fact={p.ktru_code} />
      <Fact label="Цена единицы" fact={p.unit_price} /><Fact label="Сумма позиции" fact={p.line_sum} />
      <Fact label="Валюта" fact={p.currency} />
      {set.law === "44" && <SupplierSearch key={supplierSearchRequestKey({ selection: {
        notice: { purchase_number: set.purchase_number, version_number: set.version_number,
          notice_xml_sha256: set.notice_xml_sha256 }, source_index: p.source_index } })}
        publicName={p.name.value} request={{ selection: { notice: { purchase_number: set.purchase_number,
          version_number: set.version_number, notice_xml_sha256: set.notice_xml_sha256 },
          source_index: p.source_index } }} />}
      {set.law === "223" && <p>Цена всего лота не распределяется по его позициям.</p>}
      <p className="mt-2 font-bold">Характеристики: {p.characteristics_status === "SOURCE_VALUES" ? `${p.characteristics.length} из ${p.characteristics_total}` : "UNKNOWN"}.
        {p.characteristics_truncated && " Список сокращён."}</p>
      {p.characteristics.map((c,i) => <div key={i} className="mt-2 border-t pt-2">
        <Fact label="Характеристика" fact={c.name} />
        <Fact label="Код инструкции заполнения" fact={c.instruction_code} />
        <p>Варианты значений: {c.values.length} из {c.values_total}.{c.truncated && " Превью сокращено."}</p>
        {c.values.map((v,j) => <div key={j} className="my-1 border-l-2 pl-2">
          <Fact label="Описание" fact={v.description} />
          <p>Конкретные числовые значения: {v.concrete_values.length} из {v.concrete_values_total}.
            {v.concrete_values_truncated && " Превью сокращено."}</p>
          {v.concrete_values.map((n,k) => <div key={k}>
            <Fact label="Значение" fact={n} />
            {n.value === null && n.raw !== null && <p>Исходный текст: {n.raw}{n.raw_truncated && "… (сокращено)"}. Число не подтверждено.</p>}
          </div>)}
          <Fact label="Минимум" fact={v.minimum} /><Fact label="Оператор минимума" fact={v.minimum_operator} />
          <Fact label="Максимум" fact={v.maximum} /><Fact label="Оператор максимума" fact={v.maximum_operator} />
          <Fact label="Единица характеристики" fact={v.unit} />
        </div>)}
      </div>)}
    </details>)}
    <h5 className="mt-3 font-bold">Таблицы полученных DOCX</h5>
    <p>Связь строк с позицией и роль документа требуют проверки. Таблицы могут содержать условия договора и другие сведения.</p>
    {!set.native_tables.length && <p>Табличное превью отсутствует. Это не подтверждает отсутствие требований в документах.</p>}
    {set.native_tables.map((d,i) => <details key={`${d.content_uid}:${i}`} className="mt-2 rounded border p-2">
      <summary>{d.filename} · {d.rows.length} из {d.rows_total} строк</summary>
      <p>Извлечение: {d.extraction_status}. Полнота и привязка к позиции: UNKNOWN.</p>
      <p>{d.extraction_reasons.join("; ")}</p>
      <p className="break-all text-xs">SHA-256: {d.document_sha256} · UID: {d.content_uid}</p>
      {d.truncated && <p>Превью сокращено. Полный извлечённый текст сохранён на сервере.</p>}
      <div className="overflow-x-auto"><table className="mt-2 w-full border-collapse text-xs"><tbody>
        {d.rows.map((r,j) => <tr key={j}>{r.cells.map((c,k) => <td key={k} className="min-w-32 border p-2 align-top">
          <p className="whitespace-pre-line">{c.text}{c.truncated && "… (сокращено)"}</p><Source provenance={c.provenance} />
          {k === r.cells.length - 1 && r.cells_total > r.cells.length && <p>Показано {r.cells.length} из {r.cells_total} ячеек строки.</p>}
        </td>)}</tr>)}
      </tbody></table></div>
    </details>)}
  </section>;
}
