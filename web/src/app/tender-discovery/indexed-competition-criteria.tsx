import type { EisCompetitionCriteria, Provenance } from "@/lib/procurement-api";

const bands = {
  STANDARD: "Значимость",
  DISCOUNT_BELOW_25: "При снижении цены менее 25%",
  DISCOUNT_AT_LEAST_25: "При снижении цены на 25% и более",
  UNKNOWN: "Ветка значимости: UNKNOWN",
};

function Source({ value }: { value: Provenance | null }) {
  return value && <p className="break-all text-xs text-slate-600">
    {value.locator} · {value.document_id}</p>;
}

export function IndexedCompetitionCriteria({ value }: { value?: EisCompetitionCriteria | null }) {
  if (value?.source_status === "NOT_APPLICABLE") return <p>
    Эта сводка конкурсных критериев для данного метода не применяется.</p>;
  if (!value) return <p>Критерии конкурса: UNKNOWN — исходный XML не проверен.</p>;
  return <section aria-label="Критерии оценки конкурса" className="space-y-2">
    <p className="font-bold">Исходные критерии заказчика</p>
    <p>{value.weight_integrity === "CONSISTENT"
      ? "Веса суммируются в 100% в каждой показанной схеме."
      : "Полнота и согласованность весов: UNKNOWN."}</p>
    <p>Оценка поставщика, квалификация и проверка правил оценки: UNKNOWN.</p>
    {!value.criteria.length && <p>Исходные критерии не удалось извлечь.</p>}
    {value.criteria.map((criterion,index) => <div key={index} className="rounded border border-amber-200 p-2">
      <p className="font-bold">{criterion.label} · код {criterion.code ?? "UNKNOWN"}</p>
      {criterion.weights.map((weight,weightIndex) => <div key={weightIndex} className="mt-1">
        <p>{bands[weight.band]}: {weight.value_percent === null
          ? `UNKNOWN (исходное значение: ${weight.raw_value || "не указано"})`
          : `${weight.value_percent}%`}</p>
        <Source value={weight.provenance} />
      </div>)}
      {criterion.indicators_status === "PRESENT_UNREVIEWED" && <p className="mt-1 text-amber-900">
        Есть вложенные показатели. Их веса, шкалы и подтверждающие документы ещё не разобраны.</p>}
      {criterion.indicators_status === "UNKNOWN" && <p>Вложенные показатели: UNKNOWN.</p>}
      {criterion.additional_info && <details className="mt-1"><summary>Дополнительная информация заказчика</summary>
        <p className="whitespace-pre-wrap">{criterion.additional_info}</p>
        <Source value={criterion.additional_info_provenance} />
      </details>}
      <details className="mt-1"><summary>Источники кода и названия</summary>
        <Source value={criterion.code_provenance} />
        <Source value={criterion.label_provenance} />
      </details>
      {!!criterion.reasons.length && <p className="text-xs text-amber-900">
        Разбор критерия содержит неоднозначные или отсутствующие поля.</p>}
    </div>)}
  </section>;
}
