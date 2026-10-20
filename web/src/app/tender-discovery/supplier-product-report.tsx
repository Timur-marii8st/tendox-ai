import type { SavedSupplierProduct } from "@/lib/eis-supplier-product";
import type { DeclaredFact } from "@/lib/eis-supplier-page";
function Fact({ label, fact }: { label: string; fact: DeclaredFact | null }) {
  return <div><p>{label}: {fact?.value ?? "не указано"}.</p>{fact && <details className="text-xs"><summary>Источник</summary><p>{fact.locator}</p><p className="break-all">HTML SHA256: {fact.html_sha256}</p></details>}</div>;
}
const reasons: Record<string, string> = { POSITION_CHARACTERISTIC_NAME_MISSING: "Название характеристики отсутствует.", POSITION_CHARACTERISTIC_VALUES_INCOMPLETE: "Значения ЕИС неполны или требуют проверки.", SUPPLIER_DETAILS_NOT_EXTRACTED: "Данные товарной карточки не разобраны однозначно.", SUPPLIER_CHARACTERISTIC_MISSING: "Связанное поле товара не найдено.", SUPPLIER_CHARACTERISTIC_AMBIGUOUS: "На сайте несколько значений этого поля.", PUBLIC_LABEL_MATCH_RECORDED: "Поля связаны по названию; соответствие требованию ещё не проверено." };
export function SupplierProductReportView({ result }: { result: SavedSupplierProduct }) {
  const r = result.report, p = r.position.position, d = r.details;
  return <section className="mt-2 rounded border p-3" data-supplier-product-report={r.run_id}>
    <h5 className="font-semibold">Товар и условия рядом с требованиями ЕИС</h5>
    <p>Позиция: {p.name.value ?? "не указана"}. Количество заказчика: {p.quantity.value ?? "неизвестно"} {p.unit.value ?? "единица неизвестна"}.</p>
    <p>Сохранено {r.created_at}. Новых обращений к сайту: 0.</p>
    <Fact label="Название товара" fact={d.product_name} />
    <Fact label="Содержимое товара по карточке" fact={d.contents_raw} />
    <Fact label="Упаковка, исходное обозначение" fact={d.packaging_raw} />
    <Fact label="За какую единицу указана цена" fact={d.price_basis_raw} />
    <p>Минимальный заказ и шаг заказа не подтверждены. Число листов и обозначение упаковки не определяют единицу цены.</p>
    {d.order_controls.length > 0 && <details><summary>Параметры формы заказа</summary>{d.order_controls.map((c,i) => <p key={i}>{c.attribute}: {c.raw_value}. {c.locator}. Это технический параметр формы, смысл для заказа не подтверждён.</p>)}</details>}
    <div className="overflow-x-auto"><table className="mt-2 w-full text-left text-sm"><thead><tr><th>Характеристика ЕИС</th><th>Записано заказчиком</th><th>Опубликовано у товара</th><th>Проверка</th></tr></thead><tbody>
      {r.rows.map(row => { const c = p.characteristics[row.characteristic_index - 1]; return <tr key={row.characteristic_index} className="border-t align-top">
        <td>{row.name}</td><td>{c.values.map((v,i) => <div key={i}>
          {v.description.value && <p>{v.description.value}</p>}
          {v.minimum.value !== null && <p>Минимум: {v.minimum.value}; знак: {v.minimum_operator.value ?? "неизвестен"}.</p>}
          {v.maximum.value !== null && <p>Максимум: {v.maximum.value}; знак: {v.maximum_operator.value ?? "неизвестен"}.</p>}
          {v.concrete_values.map((n,j) => <p key={j}>{n.value ?? n.raw ?? "неизвестно"}</p>)}
          {v.unit.value && <p>Единица: {v.unit.value}.</p>}
        </div>)}<details className="text-xs"><summary>Источник ЕИС</summary><p>{c.name.provenance.locator}</p><p className="break-all">XML SHA256: {c.name.provenance.document_id}</p>{c.values.map((v,i) => <p key={i}>{v.description.value !== null ? v.description.provenance.locator : v.minimum.provenance.locator}</p>)}</details></td>
        <td>{row.supplier_indices.length ? row.supplier_indices.map(index => { const f = d.characteristics[index - 1]; return <div key={index}><p>{f.label_raw}: {f.value_raw}</p><details className="text-xs"><summary>Источник товара</summary><p>{f.label_locator}</p><p>{f.value_locator}</p><p className="break-all">HTML SHA256: {f.html_sha256}</p></details></div>; }) : "Поле не найдено"}</td>
        <td>UNKNOWN. {reasons[row.reason]}</td>
      </tr>; })}
    </tbody></table></div>
    <p className="mt-2">Это данные публичной позиции и карточки товара. Полнота ТЗ, обязательность требований и соответствие пока не подтверждены. Единичная цена, стоимость партии, НДС, доставка и прибыль неизвестны; полного КП нет.</p>
  </section>;
}
