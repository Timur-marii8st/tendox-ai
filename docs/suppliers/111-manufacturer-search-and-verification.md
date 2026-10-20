# Поиск и проверка производителя

Статус: `IN PROGRESS` локально; завершённые срезы проверены локально, выпуск не объявлен. Первый ограниченный срез —
поиск в официальной коллекции **EAEU PRODUCTS** с сохранением точного ответа и
материализацией сервером кандидатского досье. Это продолжение потока
S223–S226, но не изменение требований S229. Основания и границы источников:
[покрытие источников](23-supplier-source-coverage.md), [PRD 3.3](../product/11-product-requirements.md#33-поиск-поставщика-и-rfq),
[ADR-0030](../adr/0030-official-manufacturer-catalog-failover.md) и
[ADR-0031](../adr/0031-multi-source-sourcing-artifacts.md), [ADR-0099](../adr/0099-persisted-manufacturer-search.md) и целевой контракт независимого review [ADR-0100](../adr/0100-independent-manufacturer-review.md).

## Цель и границы первого среза

Оператор явно запускает поиск товара на первом маршруте `/manufacturer-search`
в официальной коллекции EAEU PRODUCTS.
UUID команды связывает запрос с одним сохранённым поиском; повтор той же команды
читает результат без сети, изменённый запрос вызывает конфликт 409. Фиксируются
STARTED до сети, точные параметры и bytes запроса, версия парсера, время с
часовым поясом, исход попытки, размер и SHA-256 полного полученного ответа.
Полный ответ до 512 KiB сохраняется и при ошибке парсера; timeout или превышение
лимита не представляются как полный снимок. Сервер извлекает записи в
типизированное досье: наименование товара, номер и ID реестровой записи,
названного изготовителя, срок документа, ссылку и provenance на поля.
Коды компании и страна не выводятся из названия и остаются незаполненными.

Raw ответ является доказательством ответа источника; server-derived dossier —
проекцией для review. Ни один из них сам по себе не устанавливает роль
производителя, происхождение, соответствие ТЗ, наличие, цену или действующее
КП. Ошибка источника, частичный ответ и отсутствие поля сохраняются явно и
дают `UNKNOWN`, а не догадку. Все объекты tenant-scoped и append-only;
повтор запроса не переписывает предыдущий snapshot.

## Последовательные этапы

| Этап | Содержание и результат | Статус | Владелец / зависимость |
|---|---|---|---|
| 1 | Persisted registry source и candidate dossier для EAEU PRODUCTS: exact raw response → server-derived typed candidates, provenance, tenant scope и replayable linkage. | `CHECKED LOCALLY` | Sol: source/storage/schema/migration/tests; root: API/web; Astra: read-only architecture review |
| 2 | Независимый review identity и роли: immutable evidence PDF до 2 МиБ, exact registry record и 1–3 citations; отдельный reviewer подтверждает источник, реквизиты и конкретный товар. Терминальное решение read-only; proposer и uploader не могут одобрить собственную работу. | `CHECKED LOCALLY` | Sol: domain/storage/migration10; root: API; Sol: web; Astra: review; реальная проверка документов не выполнена |
| 3 | Exact company ↔ registry-product linkage выполнен внутри этапа 2. Связь SKU/артикула продавца S226 с реестровой записью требует отдельного evidence и не подтверждена. | `CHECKED LOCALLY` для registry scope; SKU `NOT STARTED` | Sol + root; зависит от 2 |
| 4 | Сводка одного run: максимум 10 товаров и 20 reviews; точные country/scheme/registration ID, все proof links, конфликты → UNKNOWN, FAIL и expiry блокируют запись. Overflow → INCOMPLETE без подтверждённых групп. Глобального справочника нет. | `CHECKED LOCALLY` | Sol: domain/storage; root: API/web; Astra: review; [ADR-0101](../adr/0101-run-scoped-manufacturer-grouping.md) |
| 5 | GISP/B2B: доступ и контракт общего поиска не подтверждены. Автоматическое подключение остаётся отдельным незавершённым этапом; существующие узкие adapters S223–S226 не означают полное покрытие. | `ACCESS CONTRACT PENDING` | Нужны проверяемый официальный доступ, условия и реальные образцы ответа |
| 6 | Immutable draft RFQ по проверенному изготовителю и одной реестровой записи: ручные количество/единица/требования/доставка с provenance, future reply deadline, сохранение и скачивание TXT. Контакты и коммерческие условия остаются UNKNOWN; их review и отправка не выполнены. | draft `CHECKED LOCALLY`; contacts/commercial `NOT STARTED` | Sol: domain/storage/migration11/web; root: API; Astra: review; [ADR-0102](../adr/0102-manufacturer-rfq-draft.md) |
| 7 | Полная экономика КП (цена, MOQ, НДС, производство, доставка, гарантия и три сценария) остаётся последующим потоком; manufacturer search не выдаёт `PARTICIPATE`. | `NOT STARTED` | Отдельный economics/offer slice; зависит от действительного полного КП |

## Acceptance для первого среза

- Для успешного и ошибочного исхода доступны tenant-scoped persisted записи;
  незавершённая попытка остаётся STARTED/UNKNOWN. Частичный ответ не даёт кандидатов.
- До десяти исходных записей на поиск; явное количество совпадений не означает
  полноту рынка. Cooldown 15 минут и до двадцати запусков за UTC-день на tenant.
- Список последних двадцати поисков читает только metadata. Чтение конкретного
  поиска и досье проверяет bounded bytes, SHA и версию парсера, без сети.
- В досье нет поля без provenance; derived normalization не заменяет исходную
  строку и не меняет raw artifact.
- API/UI показывают source status, observed-at, идентификатор snapshot и
  `UNKNOWN` при недостатке evidence; карточка не получает технический `PASS`.
- Повторная обработка одного snapshot идемпотентна, а новый ответ создаёт новый
  snapshot; межтенантный доступ и подмена raw ответа покрыты тестами.
- Локальная проверка среза 1: 33 Python source/API/real-PostgreSQL теста PASS без
  skips, 4 Node wire теста PASS, mypy domain (18) PASS, 9 doctests PASS, ruff
  PASS, docs check PASS и Next production build PASS. Полный non-integration
  прогон: 3104 collected, passed с opt-in skips; это не новая общая метрика
  acceptance.
- Один live EAEU запрос завершился `SOURCE_ERROR` (run `95313c73…`, source 1,
  read 0), поэтому live-success не заявляется. Browser visual для
  незапущенной конфигурации PASS; connected Next synthetic-token запуск отклонён
  auto-review без доступной причины, connected visual остаётся `NOT_PERFORMED`.
  На VPS не развёртывалось.
- Проверка документации (`uv run python scripts/check_docs.py`) проходит.

Документ описывает целевой порядок и локальный статус работы. Он не является
evidence завершённого production acceptance; такой статус появится только после
связанных API, storage, migration, UI и независимых проверок.

## Локальные границы последующих срезов

Решения привязаны к exact proposal/dossier SHA и выбранным citations. Upload,
proposal и decision команды actor-bound и защищены от конкурентных повторов.
Список перепроверяет доказательства перед показом статуса, а reviewer видит
claimed URL, uploader, origin и исходный PDF с проверкой SHA. Ошибка чтения
терминального решения не открывает новую форму одобрения.

Сводка читает proposals, decisions и evidence в одном repeatable-read snapshot.
`evaluated_at` определяет актуальность expiry. При неполном охвате нельзя
объявлять отсутствие review по обрезанной выборке; наличие определяется по всем
связанным proposals только для известных десяти record IDs.

RFQ сохраняет точные ручные значения и детерминированный текст. Количество —
строка Decimal с ограниченной длиной обычной десятичной записи, без округления
через float или контекст `normalize()`. Повтор исходной команды после expiry
читает тот же исторический draft; его актуальность оценивается отдельно.
`DRAFT_NO_DISPATCH` не является КП или разрешением на отправку.

Проверка доступа 2026-10-06: официальная конфигурация ЕАЭС отвечает HTTP 200 и
по-прежнему перечисляет public коллекции PRODUCTS/MANUFACTURERS; два read-only
товарных запроса завершились SOURCE_ERROR без полного ответа. [Каталог ГИСП](https://gisp.gov.ru/goods/)
и [реестр ГИСП](https://gisp.gov.ru/pp719v2/pub/prod/) через web fetch дали HTTP 403;
чтение robots.txt настроенным HTTP transport завершилось TLS ConnectTimeout.
Это evidence недоступности на проверенном маршруте, а не отсутствия товаров,
производителей или API. Не менялись proxy/TLS и не обходились ограничения.

Итоговая bounded проверка этапов 1–4 и RFQ draft: **84 Python source/domain/API/
real-PostgreSQL tests PASS, zero skips**; **19 Node wire tests PASS**, включая
реальный synthetic PostgreSQL/API golden DTO с SHA и нормализацией UTC;
strict mypy domain — 21 модуль PASS, 9 doctests PASS, whole-repo Ruff PASS,
Next TypeScript/lint/production build PASS, docs check PASS. Миграции 09–11
применены только в изолированном локальном PostgreSQL 18. Данные тестов
синтетические, документы не доказывают реальных изготовителей.

Общий non-integration regression после реализации: **2975 PASS, 155 opt-in
SKIP**, 3130 collected, без failures. Эти skips не включены в 84 профильных
source/domain/API/real-PostgreSQL acceptance tests выше. Временные локальные
API/Next процессы и отдельный тестовый PostgreSQL остановлены; сохранённые
тестовые данные оставлены для воспроизводимости. Production deployment не
выполнялся.
