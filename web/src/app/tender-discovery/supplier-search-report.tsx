import type { SavedSupplierSearch, PublishedSupplierPrice } from "@/lib/eis-supplier-search";

const priceLabel: Record<PublishedSupplierPrice["kind"], string> = {
  BASE_PRICE_FROM: "Цена базовой комплектации — от",
  PRICE_FROM: "Опубликованная стартовая цена — от",
  LEASE_MONTHLY: "Лизинговый / арендный платёж в месяц",
};
export function SupplierSearchReportView({ result }: { result: SavedSupplierSearch }) {
  const r = result.report, o = r.observation;
  return <section className="mt-3 rounded border bg-white p-3" aria-label="Источники снабжения выбранной позиции">
    <h5 className="font-bold">Поиск поставщиков: {r.position_name.value ?? "Название UNKNOWN"}</h5>
    <p>Запрос категории: {r.query ?? "Не поддерживается"}. Использовано наименование позиции; соответствие всему ТЗ не проверено.</p>
    <p>Сохранено: {r.created_at}. {result.created ? "Новая попытка." : "Сохранённый результат; цена могла измениться."}</p>
    <p className="break-all text-xs">Источник позиции: XML {r.position_name.provenance.document_id} · {r.position_name.provenance.locator}</p>
    {r.status === "STARTED" && <p role="status">Поиск начат, итог не сохранён. Он может ещё выполняться или быть прерван. Свежие предложения: UNKNOWN.</p>}
    {r.status === "SOURCE_ERROR" && <p role="alert">Источник недоступен или его структура изменилась. Эта попытка не подтвердила наличие или отсутствие поставщиков.</p>}
    {r.status === "QUERY_NOT_COVERED" && <p>Для этого наименования источник пока не подключён. Это не означает, что поставщиков нет.</p>}
    {o && <>
      <p>Проверена одна категория ServerMall: HPE ProLiant Gen12. Полнота рынка: UNKNOWN.</p>
      <p>Карточек в категории: {o.scanned_count}; совпали по названию: {o.matched_count}; показано: {o.returned_count}.{o.truncated && " Выдача сокращена."}</p>
      <p>Страница получена: {o.observed_at}. <a className="underline" href={o.source_url} target="_blank" rel="noreferrer">Источник</a></p>
      <p className="break-all text-xs">SHA-256 страницы: {o.source_sha256} · {o.byte_count} байт</p>
      {!o.leads.length && <p>В этой категории совпадений не найдено. Остальные источники не проверены.</p>}
      <ul className="mt-2 grid gap-2">{o.leads.map(lead => <li key={lead.product_url} className="rounded border p-2">
        <a href={lead.product_url} target="_blank" rel="noreferrer" className="font-bold underline">{lead.product_name}</a>
        <p>Поставщик по странице: {lead.supplier}; бренд по каталогу: {lead.manufacturer}. Юридическое лицо и происхождение не подтверждены.</p>
        <p className="break-all text-xs">Источник названия: {lead.name_provenance.locator}</p>
        {lead.price_status === "UNKNOWN" && <p>Опубликованная цена: UNKNOWN — однозначное значение не извлечено.</p>}
        {lead.published_prices.map(price => <div key={price.kind} className="mt-1">
          <p>{priceLabel[price.kind]}: {price.amount_rub} ₽.</p>
          <p>Текст источника: {price.raw_label}</p>
          <p className="break-all text-xs">Источник цены: {price.provenance.locator} · {price.provenance.document_id}</p>
        </div>)}
        <p>Полная комплектация, НДС, наличие, доставка и соответствие ТЗ: UNKNOWN.</p>
      </li>)}</ul>
    </>}
    <p className="mt-2 font-bold">Публичные цены не являются полным КП. Закупочная себестоимость, прибыль и решение об участии: UNKNOWN.</p>
  </section>;
}
