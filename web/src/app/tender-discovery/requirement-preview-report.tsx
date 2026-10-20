import { supplierFieldsForTableRow, type RequirementPreview, type RequirementTableCell } from "../../lib/eis-requirement-preview";
function Cell({ cell }: { cell: RequirementTableCell | undefined }) {
  return cell ? <div><p className="whitespace-pre-line">{cell.text}</p><details className="text-xs"><summary>Источник ячейки</summary><p>{cell.provenance.locator} · фрагмент {cell.block_index}, символы [0:{cell.source_char_count}]</p><p className="break-all">SHA256: {cell.provenance.document_id}</p></details></div> : <p>Текст не сохранён. Пустая или объединённая ячейка не подтверждена.</p>;
}
export function RequirementPreviewReport({ result }: { result: RequirementPreview }) {
  const t = result.table;
  return <section className="mt-3 rounded border p-3" data-requirement-preview={result.preview_sha256}>
    <h5 className="font-semibold">Таблица документа и выбранный товар</h5>
    <p>{result.filename} · таблица {t.table_index}. Показаны все {t.cell_count} сохранённые текстовые ячейки, {t.row_count} строк после заголовка.</p>
    <p>Документ выбран для просмотра. Его роль, связь с позицией и полнота ТЗ не подтверждены. Одобрение требований и соответствие товара: UNKNOWN.</p>
    <div className="overflow-x-auto"><table className="mt-2 w-full text-left text-sm"><thead><tr>{t.header.map(c => <th className="min-w-36" key={c.column}><Cell cell={c} /></th>)}<th className="min-w-48">Опубликовано у товара</th><th className="min-w-40">Проверка</th></tr></thead><tbody>
      {t.rows.map(row => <tr key={row.source_row} className="border-t align-top">{[1,2,3,4,5].map(column => <td className="p-1" key={column}><Cell cell={row.cells.find(c => c.column === column)} /></td>)}
        <td className="p-1">{supplierFieldsForTableRow(row,result.product).map(index => { const c = result.product.details.characteristics[index]; return <div key={index}><p>{c.label_raw}: {c.value_raw}</p><details className="text-xs"><summary>Источник товара</summary><p>{c.value_locator}</p><p className="break-all">HTML SHA256: {c.html_sha256}</p></details></div>; })}{row.kind === "CONTEXT_ONLY" ? "Контекст таблицы" : !supplierFieldsForTableRow(row,result.product).length && "Связанное поле товара не найдено"}</td>
        <td className="p-1"><p>UNKNOWN</p><p>Обязательность и интерпретация требования требуют проверки.</p>{row.numeric_hints.length > 0 && <p>Числовая подсказка: {row.numeric_hints.map(h => `${h.operator} ${h.value}`).join(" и ")} {row.unit_raw ?? "(единица не подтверждена)"}. Это не исполняемое требование.</p>}</td>
      </tr>)}
    </tbody></table></div>
    <p className="mt-2">Совпадение названий не подтверждает соответствие. «Сэ» не приравнивается к «С», «80 ± 3» не заменяется на «80». Цена партии, прибыль и участие UNKNOWN.</p>
    <details className="text-xs"><summary>Основание просмотра</summary><p className="break-all">Preview SHA256: {result.preview_sha256}</p><p className="break-all">Product report SHA256: {result.product_report_sha256}</p><p className="break-all">Analysis SHA256: {result.analysis_sha256}</p><p>Receipt: {result.document_observation_id}. {result.observed_at}. Разбор: {result.analyzed_at}.</p><p>Новых обращений: 0. Новых записей: 0. Структура исходной таблицы: UNKNOWN.</p></details>
  </section>;
}
