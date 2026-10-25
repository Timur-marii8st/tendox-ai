import type { PublicUnitPriceReport } from "../../lib/public-unit-price";
import { formatMoneyString } from "../../lib/tender-workspace";
const reasons: Record<string, string> = {
  EXPLICIT_PRICE_BASIS_UNAVAILABLE: "Источник не подтвердил единицу цены, НДС или однозначную цену товара.",
  PUBLIC_PRICE_STALE: "Наблюдение цены старше 24 часов или время источника некорректно.",
  PUBLIC_PRODUCT_UNAVAILABLE: "В источнике товар отмечен как недоступный.",
  REQUIRED_QUANTITY_UNKNOWN: "Количество заказчика не подтверждено.",
  UNIT_COMPARABILITY_UNKNOWN: "Единицы цены и количества заказчика пока несопоставимы.",
  POSITION_COST_LIMIT: "Стоимость позиции превышает предел расчёта.",
};
export function PublicPriceView({ report }: { report: PublicUnitPriceReport }) {
  return <section className="mt-3 rounded border border-blue-300 bg-blue-50 p-3" aria-label="Автоматическая оценка по публичной цене">
    <h5 className="font-semibold">Оценка по найденной публичной цене</h5>
    {report.status === "CALCULATED" ? <>
      <p>Товар на количество заказчика: <strong>{formatMoneyString(report.quantity_cost_rub)}</strong>
        {report.price?.amount_basis === "EX_VAT" ? " без НДС" : " с НДС по данным источника"}.</p>
      <p>Количество: {report.required_quantity?.value} {report.required_unit}.</p>
      <p>Это одна позиция, не полная стоимость закупки. Линейная цена на объём — допущение;
        минимальный заказ, шаг заказа, наличие и доставка требуют проверки.</p>
    </> : <p>Стоимость на объём пока не подтверждена. {report.missing.map(code => reasons[code] ?? "Данные источника требуют проверки.").join(" ")}</p>}
    <p>Прибыль и маржа: UNKNOWN — нужны все позиции, налоги и остальные расходы.
      Публичная цена не является действующим КП или допуском к участию.</p>
    <details><summary>Источники расчёта</summary><p>HTML SHA256: {report.source_sha256}</p>
      <p>Количество ЕИС: {report.required_quantity?.provenance.locator ?? "не подтверждено"}.</p>
      {report.price && <><p>Цена: {report.price.price.provenance.locator}.</p><p>Единица цены: {report.price.unit.provenance.locator}.</p></>}
    </details>
  </section>;
}
