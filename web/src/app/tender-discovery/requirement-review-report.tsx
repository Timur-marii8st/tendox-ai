import type { RequirementProposal, RequirementComparison } from "../../lib/eis-requirement-review";
export function RequirementReviewReport({ proposal, comparison }: { proposal: RequirementProposal; comparison?: RequirementComparison }) {
  return <section className="mt-3 rounded border p-3">
    <h6 className="font-semibold">Сохранённое предложение проверки</h6>
    <p className="break-all">ID: {proposal.proposal_id}; автор: {proposal.prepared_by}; {proposal.prepared_at}</p>
    <p className="break-all">Proposal SHA256: {proposal.proposal_sha256}</p>
    <p className="break-all">Preview SHA256: {proposal.preview.preview_sha256}; товар: {proposal.preview.product_report_sha256}; документ: {proposal.preview.table.document_sha256}</p>
    {!comparison && <p>Независимое решение ожидается. Результаты требований UNKNOWN.</p>}
    {comparison && <><p>Проверяющий: {comparison.decision.reviewed_by}; {comparison.decision.reviewed_at}</p><p className="break-all">Decision SHA256: {comparison.decision_sha256}</p><p>Пояснение проверяющего: {comparison.decision.request.note}</p><p>{comparison.candidate_blocked ? "Обязательное требование провалено: выбранный товар заблокирован." : "Блокирующего FAIL в проверенных строках нет; полного технического допуска нет."}</p></>}
    <div className="overflow-x-auto"><table className="mt-2 w-full text-left text-sm"><thead><tr><th>Строка и требование</th><th>Интерпретация / обязательность</th><th>Товар и результат</th></tr></thead><tbody>{proposal.preview.table.rows.map((row,i) => {
      const choice = proposal.request.rows[i], result = comparison?.rows[i];
      const supplier = choice.supplier_index === null ? undefined : proposal.preview.product.details.characteristics[choice.supplier_index-1];
      return <tr key={row.source_row} className="border-t align-top"><td className="p-2"><p>Строка {row.source_row}: {row.cells.find(c => c.column === 1)?.text}</p>{row.cells.map(c => <p key={c.column}>{c.column}: {c.text}<span className="block break-all text-xs">{c.provenance.document_id} / {c.provenance.locator}</span></p>)}</td><td className="p-2">{choice.mode === "PAPER_FORMAT" ? "Формат бумаги A/B0–10; кириллическая А/В требует подтверждения" : "Ручная проверка; не исполняется"}<p>Обязательность: {choice.mandatory === null ? "UNKNOWN" : choice.mandatory ? "Да" : "Нет"}</p></td><td className="p-2">{supplier && <><p>{supplier.label_raw}: {supplier.value_raw}</p><p className="break-all text-xs">{supplier.html_sha256} / {supplier.value_locator}</p></>}<p className="font-semibold">{result?.status ?? "UNKNOWN"}</p><p>{result?.check?.reason ?? (choice.mode === "MANUAL" ? "Нужны подтверждённые смысл, единицы и интерпретация." : "Нужно независимое подтверждение документа, позиции и нормализации.")}</p></td></tr>;
    })}</tbody></table></div>
    <p>Полнота всего ТЗ, полный технический допуск, КП, прибыль и участие UNKNOWN. Процент соответствия не вычисляется.</p>
  </section>;
}
