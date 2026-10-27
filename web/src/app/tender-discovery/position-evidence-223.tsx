import type { Eis223PositionProjection, Eis223TextFact } from "../../lib/procurement-api";

function shown(fact: Eis223TextFact): string {
  return fact.value ?? (fact.raw ? `Не подтверждено (исходное: ${fact.raw})` : "Не подтверждено");
}

export function PositionEvidence223View({ projection, ordinaryPositions = [] }: {
  projection: Eis223PositionProjection;
  ordinaryPositions?: ReadonlyArray<{ name: string; quantity: string; unit: string; locator: string }>;
}) {
  const total = projection.lots.reduce((n, lot) => n + lot.customers.reduce((m, c) => m + c.items.length, 0), 0);
  const groups = projection.lots.flatMap(lot => lot.customers);
  const visibleGroups = groups.slice(0, 100);
  const visibleLots = projection.lots.map(lot => ({
    ...lot,
    customers: lot.customers.filter(customer => visibleGroups.includes(customer)).map(customer => {
      const preceding = visibleGroups.slice(0, visibleGroups.indexOf(customer));
      const offset = preceding.reduce((n, group) => n + group.items.length, 0);
      return { ...customer, visibleItems: customer.items.slice(0, Math.max(0, 100 - offset)) };
    }),
  })).filter(lot => lot.customers.length > 0);
  return <div style={{ overflowWrap: "anywhere" }}>
    <p>Позиции совместной закупки по заказчикам. Полнота ТЗ и расчёт экономики не подтверждены.</p>
    {projection.source_item_coverage !== "PASS" && <p>Состав позиций подтверждён частично. Проверьте источник.</p>}
    {visibleLots.map(lot => <div key={lot.lot_index}>
      <h4>Лот {lot.ordinal.value ?? lot.lot_index}</h4>
      {lot.customers.map(customer => {
        const items = customer.visibleItems;
        return <div key={customer.customer_index}>
          <h5>Заказчик {customer.customer_index}: {shown(customer.name)}</h5>
          <p>ИНН: {shown(customer.inn)}</p>
          {items.map((item, i) => <p key={item.provenance.locator}>
            Позиция {i + 1}: {shown(item.description)} · {shown(item.quantity)} · {shown(item.unit_name)}
            <br />ОКПД2: {shown(item.classification_code)}
            <br />{item.provenance.locator}
          </p>)}
          {!customer.items.length && <p>Позиции заказчика не подтверждены.</p>}
          <details><summary>Источник группы заказчика</summary>
            <p>{customer.provenance.document_id} · {customer.provenance.locator}</p>
            {[customer.name, customer.inn, ...items.flatMap(item => [item.description, item.quantity, item.unit_name, item.classification_code])].map((fact, i) => <p key={i}>{shown(fact)}<br />{fact.provenance.document_id} · {fact.provenance.locator}</p>)}
          </details>
        </div>;
      })}
    </div>)}
    {(total > 100 || groups.length > 100) && <p>Показаны первые 100 позиций и до 100 групп из {total} исходных позиций. Полный состав — в XML.</p>}
    {ordinaryPositions.length > 0 && <div><h4>Позиции остальных лотов из извещения</h4>{ordinaryPositions.slice(0, 100).map((item, index) => <p key={`${item.locator}:${index}`}>{item.name} · {item.quantity} · {item.unit}<br />{item.locator}</p>)}{ordinaryPositions.length > 100 && <p>Показаны 100 из {ordinaryPositions.length} обычных позиций. Полный состав — в XML.</p>}</div>}
    <p>XML SHA-256: {projection.notice_xml_sha256}<br />Файл: {projection.source_member}</p>
  </div>;
}
