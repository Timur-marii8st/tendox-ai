import type { SavedSupplierPage } from "@/lib/eis-supplier-page";

const statuses: Record<string, string> = { COMPLETED: "Страница прочитана", BLOCKED: "Сайт ограничил доступ или показал проверку робота",
  RATE_LIMITED: "Сайт ограничил частоту запросов", TIMEOUT: "Время ожидания истекло", SOURCE_ERROR: "Ошибка сайта или соединения",
  UNSAFE_URL: "Адрес не подходит для безопасного чтения", RESOURCE_LIMIT: "Превышен лимит чтения", UNSUPPORTED_CONTENT: "Формат ответа не поддерживается" };
const kinds: Record<string, string> = { PRODUCT: "Товарная разметка", CATEGORY: "Категория или несколько товаров", ARTICLE: "Статья", UNKNOWN: "Тип страницы не установлен" };
export function SupplierPageReportView({ result }: { result: Pick<SavedSupplierPage, "source_requests"> & {
  report: Pick<SavedSupplierPage["report"], "run_id" | "created_at" | "status" | "observation"> } }) {
  const r = result.report, o = r.observation;
  return <section className="mt-2 rounded border bg-white p-3" data-supplier-page-report={r.run_id}>
    <h5 className="font-semibold">Проверка сайта</h5>
    <p>Сохранено: {r.created_at}. Новых попыток HTTP-чтения: {result.source_requests}.</p>
    {r.status === "STARTED" && <p role="status">Чтение начато; итог ещё не сохранён. Откройте сохранённую проверку позже.</p>}
    {o && <>
      <p>{statuses[o.status]} · {kinds[o.page_kind]}.</p>
      {o.status === "COMPLETED" && <p>Разобрано товарных наблюдений: {o.products.length}. {o.extraction_status === "EMPTY" && "Структурированные товарные данные не найдены."}
        {o.extraction_status === "AMBIGUOUS" && "Страница содержит неоднозначные данные или несколько товаров."}
        {o.extraction_status === "LIMIT_EXCEEDED" && "Разбор ограничен; полнота неизвестна."}</p>}
      <p className="text-sm">Цена и названия взяты из разметки сайта. Единица продажи, партия, НДС, наличие, доставка, соответствие закупке и действующее КП пока не подтверждены.</p>
      {o.products.map((p, i) => <article key={`${p.locator}:${i}`} className="mt-2 border-t pt-2">
        <h6 className="font-semibold">{p.name?.value ?? "Товар без указанного названия"}</h6>
        {p.sku && <p>Артикул, заявленный сайтом: {p.sku.value}</p>}
        {p.brand && <p>Бренд, заявленный сайтом: {p.brand.value}</p>}
        {p.manufacturer && <p>Производитель, заявленный сайтом: {p.manufacturer.value}</p>}
        {p.seller && <p>Продавец, заявленный сайтом: {p.seller.value}</p>}
        {p.prices.length ? p.prices.map((price, j) => <div key={`${price.locator}:${j}`}>
          <p>{price.price_kind === "LOW" ? "Нижняя граница цены" : price.price_kind === "HIGH" ? "Верхняя граница цены" : "Опубликованная цена"}: {price.amount} {price.currency ?? "валюта неизвестна"}.</p>
          <details className="text-xs"><summary>Источник цены</summary><p>Исходное значение: {price.raw_amount}</p><p>{price.locator}</p><p className="break-all">HTML SHA256: {price.html_sha256}</p></details>
        </div>) : <p>Структурированная цена не установлена.</p>}
        <details className="text-xs"><summary>Источник товарных данных</summary><p>{p.locator}</p><p className="break-all">{o.html_sha256}</p></details>
      </article>)}
      <details className="mt-2 text-xs"><summary>Сведения о чтении страницы</summary>
        <p className="break-all">Исходный URL: {o.source_url}</p><p className="break-all">Последний прочитанный URL: {o.final_url}</p>
        <p>{o.observed_at} · HTTP {o.http_status ?? "не получен"} · переходов: {o.redirect_count} · причина: {o.reason_code}</p>
        {o.hops.map((hop, i) => <p key={i} className="break-all">{i + 1}. {hop.url} · HTTP {hop.http_status ?? "не получен"}{hop.location && ` · Location: ${hop.location}`}</p>)}
        <p className="break-all">HTML SHA256: {o.html_sha256 ?? "снимок не сохранён"}</p>
      </details>
    </>}
    <p className="mt-2 text-sm font-semibold">Сопоставимость цены и полная стоимость закупки неизвестны. Это ещё не рекомендация выгодного поставщика.</p>
  </section>;
}
