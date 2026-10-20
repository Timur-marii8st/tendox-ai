# ADR-0015: Immutable reviewed model→brand catalog persistence

Дата: 2026-09-16  
Статус: частично заменено ADR-0017 и ADR-0019 (публикация только через review)

## Контекст

ADR-0014 определил доказательный exact model→brand manifest, но его локальная
загрузка через CLI не давала общей tenant-scoped версии для API и серверного
поиска. Нельзя принимать `company_id`, reviewer или время утверждения из тела
запроса: эти поля определяют границу доступа и audit identity.

## Решение

`model_brand_catalogs` хранит immutable версии `model-brand-catalog-v1`.
PostgreSQL применяет RLS/FORCE RLS, runtime-роль имеет только `SELECT/INSERT`, а
trigger запрещает `UPDATE/DELETE`. Каталог, событие `model_brand.catalog_stored`
и idempotency receipt записываются одной транзакцией.

`POST /v1/model-brand-catalogs` принимает catalog ID, approval reference и
reviewed entries. Tenant и reviewer берутся из bearer principal, `created_at` —
из серверных UTC-часов. Exact replay с тем же `Idempotency-Key` возвращает
исходную версию, а изменённый payload или повторный catalog ID конфликтуют.
`GET /v1/model-brand-catalogs/latest` выбирает последнюю доступную tenant-версию
на timezone-aware `effective_at`.

`GET /v1/document-search` фиксирует использованный `effective_at`, загружает
последний доступный каталог того же tenant и передаёт его детерминированному
поиску. Exact native model может породить `MODEL_BRAND_CATALOG` discovery hit со
статусом `PASS`; AI-suggested model остаётся `UNKNOWN`. Отсутствующий,
неактивный, конфликтующий или межтенантный evidence не выбирает бренд.

## Последствия

- сервер, а не клиент, задаёт tenant, reviewer и время утверждения;
- поиск воспроизводим относительно возвращённого `effective_at`;
- версии каталога и audit нельзя исправить на месте;
- исходные document/media bytes и bearer token не входят в ответы поиска;
- это управляемая запись reviewed manifest, но ещё не полноценный редактор или
  approval workflow;
- SHA-256 официального источника пока проверяется как поле manifest: ingestion и
  повторная сверка exact source artifact остаются отдельной границей.

## Альтернативы

- Хранить одну изменяемую строку на tenant — отклонено: теряются история и
  воспроизводимость.
- Принимать reviewer/company/time из JSON — отклонено: клиент мог бы подменить
  audit identity и effective time.
- Смешивать catalog rows с document search index — отклонено: у них разные
  жизненные циклы, provenance и правила версионирования.
