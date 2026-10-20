# S225 — поиск конкретного товара на сайте поставщика

Статус: COMPLETE в описанных границах, установлен на VPS 2026-10-06.

## Контракт

После чтения сайта из сохранённой выдачи оператор запускает поиск по полному
публичному наименованию позиции ЕИС. Первый адаптер — подтверждённая GET форма
«Бумага-С»: `/categories/search`, поле `q`. Адрес выводится из сохранённого HTML,
запрос — из текущей позиции ЕИС. URL и поисковую строку клиент не задаёт.

SEARCH сохраняет до десяти уникальных товарных ссылок с исходным DOM ordinal,
SHA HTML и locator. Число ссылок относится к снимку; truncated означает ограничение
списка, полный охват сайта остаётся UNKNOWN. Порядок каталога не является рейтингом
выгодности. PRODUCT читает одну выбранную ссылку из точного сохранённого SEARCH.
Изменившаяся страница поиска не подменяет выбранный товар.

`POST eis-supplier-catalog/prepare` принимает `{request, refresh}`; `read` —
`{request}`. Request: точный S224 `page`, `page_run_id`, совместная пара
`search_run_id/product_index` или два null. PRODUCT index 1–10. Не принимаются
URL, tenant, hostname или изменённая поисковая строка. Подготовка — OPERATOR,
чтение — аутентифицированный tenant, ответы no-store, request 4096 байт.

## Достоверность и ограничения

Продолжение разрешено только после source observation COMPLETED. HTTP 200 с
капчей остаётся BLOCKED; его форма и ссылки не инициируют следующий запрос.
STARTED и сохранённый исход попытки — разные immutable rows с audit. Последняя
ошибка не скрывается старым успехом. Read/cache не загружают raw HTML и не делают
внешних запросов. Сырой HTML сохраняется на VPS и не передаётся интерфейсу.

Транспорт S224 дополнительно проверяет точный hostname `bumaga-s.ru` до начального
DNS и каждого redirect. HTTPS/TLS/DNS pinning, 2 MiB HTML, не более 3 dispatch,
30 секунд транспорта; child 40 секунд/10 CPU секунд. Общий с S224 tenant slot,
30 стартов/час и 64 MiB сохранённых HTML/24 часа с резервом 2 MiB. Refresh 15 минут.
Нет обхода CAPTCHA, JavaScript, личного профиля или полного обхода каталога.

Товарная страница с одним активным microdata Product/Offer позволяет извлечь
заявление о названии и цене Decimal с валютой и SHA/locator. Скрытые, inert,
template/noscript или неоднозначные конкурирующие блоки не дают товарного факта.
Парсер не выполняет внешнее содержимое. НДС, единица/упаковка, партия, наличие,
доставка, соответствие ТЗ, сопоставимость цены, полное КП и участие UNKNOWN.

## Исследование на VPS

Сохранённая главная «Бумага-С» содержит подтверждённую форму. Реальный GET по
«Бумага для офисной техники» вернул HTTP 200, 109810 байт, первые десять товарных
ссылок, truncated=true. SHA HTML:
`058da0f28172e84468ed6de54c75aa2a3b70aa145e17021f0f9246cc26fe63be`.

Первая товарная карточка SvetoCopy ECO: HTTP 200, 132943 байта. Активная microdata
и видимый текст содержат 299,60 RUB. SHA HTML:
`82b4393608fa9402dbeef32676a875c116d40d182c59230566b73f93c75af411`.
Diagnostic затем подтверждён installed API workflow; закупочная цена партии
по-прежнему не подтверждена. [Страница поставщика](https://bumaga-s.ru/).

«Комус»: сохранённые HTTP HTML главной/категорий не содержат товарных ссылок;
обычный browser получил 503 robot block. Попытка остановлена. Targeted Bing
site-query не сохранил заявленное ограничение домена и не принят как adapter.

## Проверки и следующий этап

- Финальный isolated PostgreSQL: **403 Python/API/PG PASS**, 61.49 с, zero skips.
  Включены SEARCH→PRODUCT, RLS, UPDATE/DELETE запреты, FK/index, current/hold,
  BLOCKED200 форма/ссылки без дальнейшего dispatch, refresh/latest STARTED,
  общие бюджеты S224+S225, source0 и отсутствие body hydration при cache/read.
  PG log SHA256: `d9c22a9339dfb31053a4a21900f46d6613f8da9b03018d42eeab5814b850d2c1`.
  Code/tests/migrations manifest SHA256:
  `5a0157141701f952d89250c1a4a265c8a7b6d5efc33a1d7122919ad6dfd1cfa6`.
- **84 Node wire/render PASS**, включая 11 новых S225; TypeScript/ESLint/Next
  production build PASS, network none, 2 CPU/2 GiB build limit. Build SHA256:
  `5636b1c5fc9d08111d170a654f3c08c5690253950741316cb108c7cfa441fb92`.
- Source 90 tests, Ruff/mypy PASS. Astra проверил frozen TABLE_DDL/indexes против
  compiled PostgreSQL model: совпадают. PG поймал лишнюю закрывающую скобку в
  parent trigger; исправлена, повторный полный gate PASS. Source review поймал
  hidden/inert Product, storage review — continuation из BLOCKED200 и ancestry/
  pre-hydration checks. Исправления и повторные bounded reviews PASS.
- Live API 11:46:13 UTC: нормальный S224 root refresh 1991 мс/46595 байт;
  SEARCH **2759 мс**, HTTP200/109810 байт, 10 unique links, truncated=true;
  PRODUCT **2020 мс**, HTTP200/132943 байта, EXTRACTED, 299.6 RUB с meta locator.
  По одному dispatch на этап. API read **73–94 мс**/source0; повторная prepare
  **1588–1632 мс**/source0, child startup включён. Root +2 rows/audits,
  каталог +4 rows/audits. Caller URL, duplicate/oversize, auth, cooldown,
  unknown search и unsupported form source0 проверены. Quote/technical/price
  comparability/participation UNKNOWN. Live proof SHA256:
  `81c031f06d6cb637c583a416818bcb6bde87bb5758ced63e4d00f5d3c24f996b`.
- Installed Next Actions + compiled SSR 11:46:18 UTC: read **96–127 мс**,
  cache prepare1586–1636 мс; цены/provenance/coverage и negatives PASS;
  source0/writes0/jobs0. Browser visual check **NOT_PERFORMED**. Proof SHA256:
  `40d723cde03f744faa73dadec35a1455b7edd377d87a47b96a55e93ad6a55497`.
- Schema06, health200, disposable test DB0. DB5889899543 байта,
  free250584690688 байт. API119.6MiB/1GiB, web68.01MiB/768MiB, OOMfalse.
  Supplier source helpers0. Итог tenant: page8/audits8, catalog4/audits4.
  Обычный intake/cron не приостанавливался. Operations SHA256:
  `b8cf96c9bcf72a93b9a2c4b82240a2b51630830b5d78ea13e05eeec3db754451`;
  cleanup SHA256: `6f3985eef468c120084142815e856d67c042d3ae5230f66c6241a0e9112e0c06`.

### Installed image pins

- API: `sha256:fc1b436167f02669712a1bf042d89ba911c04cb3f071794a1828fcbbb0c13d28`.
- Worker: `sha256:11d855915adaab239f4be06bc2666fb0aa2c98a2fd052436c980e0adbd50231f`.
- Web: `sha256:01e8702e12530d8cb683bb0d807802399e4b93ae6e515c36680d5824f4c0653f`.

Полный manifest 240 файлов, API/worker48, web69. Raw HTML остаётся на VPS;
живой тест добавил около283KiB HTML (root + SEARCH + PRODUCT). Данные ноутбука
не используются как архив ЕИС.

### Как проверить в интерфейсе

Открыть сохранённый интернет-поиск позиции → «Бумага-С» → сохранённая проверка
сайта → «Найти товары на этом сайте» → «Проверить товар и цену» у выбранной
ссылки. «Открыть сохранённый результат» повторяет evidence без внешнего чтения.
Другие сайты требуют своего проверенного adapter. Полный охват каталога,
лучший закупочный прайс и соответствие SvetoCopy этой позиции не заявлены.

Следующий milestone — сопоставление товара, упаковки и полной партии с
характеристиками/документами ЕИС. Затем стоимость партии, draft RFQ и полное КП.
PARTICIPATE требует действительного полного КП и трёх завершённых сценариев.
