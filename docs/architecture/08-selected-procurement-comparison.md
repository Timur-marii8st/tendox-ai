# Сравнение выбранного профиля и сохранённых кейсов

Дата: 2026-10-15. Локальный integration slice, production не изменён.
Владелец: profile_comparison. Контракт профиля:
[фактический API](09-company-profile-api.md).

## Нормальный путь

`/procurement-comparison` использует персональную сессию существующего
`/company-profile`. Общий PROCUREMENT_API_TOKEN не используется. После
проверки bearer existing PostgresAuthenticator сохраняется HttpOnly,
SameSite=Strict cookie на час, Secure в production; path `/` позволяет читать
его обоим экранам. Login/logout удаляют прежний cookie path `/company-profile`.
Root cookie называется procurement_personal_session; legacy cookie
company_profile_session истекает отдельно, чтобы Next не перезаписал удаление
при сериализации одноимённых cookies. Существующие узкие сессии нужно один раз
переподключить на странице профиля.

На странице профиля пользователь сохраняет выбор exact версии. Каталог
`GET /v1/procurement-comparison/catalog?cursor=...` загружает selection и exact
snapshot через существующие tenant-scoped read_selection/read_profile с
проверкой сохранённых команд/источников. CasePage берётся исключительно из
PostgresStorage.list_cases (200 за страницу, next_cursor и переход в UI).
Сохранённый кейс — существующий ProcurementCase; cached notices ЕИС не
превращаются в выдуманные полные кейсы. При отсутствии кейсов UI объясняет пробел.

`POST /v1/procurement-comparison` требует OPERATOR, selection_id UUID,
profile_ref(version, snapshot_sha256) и 2–5 разных case_refs(case_id, version,
input_sha256). Tenant/actor/time клиент не назначает. Сервис читает exact
selection и version; сверяет hash и загружает exact версии кейсов через
PostgresStorage.get_case. Missing/foreign selection/case →404; несовпавший
hash/ref →409; AUDITOR может читать каталог, POST →403. Время проверки серверное,
aware UTC, представление Europe/Moscow. Сохранение новой версии профиля не
переназначает старый selection; hidden selection_id формы сохраняет исходный
выбор, даже если latest selection изменён в другом окне.

## DTO и достоверность

Канонический CompanyProfileSnapshot читается существующей моделью, без новой
policy_confirmation и без изменения snapshot SHA. Facts — flat dotted paths;
источники сохраняют company_id/provenance/hash/actor/time. Проверены все три
реальных handoff fixtures из tests/fixtures/company_profile, включая UNKNOWN,
false и явно пустые списки. Заблокированные финансовые настройки остаются UNKNOWN.
География в этом DTO — заявленный интерес поиска, поэтому проверка территории
UNKNOWN: она не доказывает логистику и не создаёт hard exclusion.

Детерминированный движок сравнения сохраняет mandatory FAIL/UNKNOWN, exact
case_input_digest, Decimal и stale assessment controls. Старый assessment
нельзя переиспользовать при несовместимом профиле или изменённых входах.
НМЦК не считается выручкой; прибыль требует полного действующего КП, трёх
сценариев и подтверждённого exact-case ledger. В saved-case адаптере такого
отдельного ledger пока нет, поэтому экономика остаётся UNKNOWN. Выбор профиля
не переписывает кейсы, не вызывает evaluate_case и не разрешает PARTICIPATE.

## Явные ограничения

Отчёты **не сохраняются**: persistence=EPHEMERAL, audit_event_id=null. Это видно
в API, на странице и в отчёте. Immutable comparison storage/audit/receipt,
повторное чтение результата и production IAM остаются отдельным срезом.
Результат не называется production ready. Источники/ЕИС/loaders/scheduler не менялись.

Синтетическое демо оставлено отдельно: API factory
`procurement.api.comparison_demo:create_demo_app`, COMPARISON_DEMO_TOKEN,
COMPARISON_DEMO_API_URL (только loopback). Next использует этот путь только при
явном COMPARISON_MODE=demo; по умолчанию saved API. Примеры старого проектного
nested DTO доступны лишь в demo adapter; реальный endpoint читает canonical
снимки из PostgreSQL, не profile JSON клиента.

## Проверки

- tests/test_profile_comparison_integration.py: три фактических handoff fixtures,
  exact profile hash, geography UNKNOWN, tenant/ref/роль через HTTP.
- tests/integration/test_profile_comparison_pg.py: выделенная
  procurement_comparison_test, runtime procurement_app, настоящий bearer,
  saved v1 selection после сохранения v2, два saved кейса, foreign404,
  auditor403 и case hash409. Нужны COMPARISON_TEST_DATABASE_URL и
  COMPARISON_TEST_DATABASE_ADMIN_URL; только loopback/test DB.
- tests/test_procurement_comparison.py: 31 исходная регрессия demo/domain.
- web/tests/procurement-comparison.test.tsx: refs/tenant/hard FAIL/UNKNOWN,
  Decimal, источники, HTML escaping.

Миграций отчёта нет. Существующая миграция профиля не меняется этим срезом.

Локальное evidence 2026-10-15: targeted Python35PASS и отдельный real-PG1PASS;
ruff, mypy domain/comparison25files, doctests9PASS, docs checkerPASS;
Next build/TypeScriptPASS, Node162PASS. Независимая CUA проверка root: вход в
профиль, latest v2 и выбранная v1; переход в comparison без повторного входа;
сравнение двух saved PostgreSQL кейсов с точной v1PASS. После миграции cookie
повторное подключениеPASS; logout профиля закрывает comparison и убирает каталог.
Синтетические credentials не входят в Git или отчёт. Полный совместный gate
завершает отдельный integration audit; перечисленное не означает production release.

Полный pytest на исходном profile checkout запущен и завершён с четырьмя
не относящимися к этому diff отказами: три test_eis_search_capture (source pins,
включая pyproject.toml), test_golden_tz_002_scan_stays_unknown (Broken xref table
в унаследованном PDF). Эти закреплённые файлы не исправлялись. Общий audit
проверяет frozen byte-exact baseline и объединённую реализацию отдельно.
