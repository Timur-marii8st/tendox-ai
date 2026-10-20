# Первый экран внутреннего пилота — S3

Статус: **первый внутренний UI-срез завершён 2026-09-09**.

## Назначение и модель доступа

Первый экран проверяет ручной workflow одного настроенного tenant: увидеть кейсы,
импортировать новый immutable-снимок, открыть карточку и запросить серверный
пересчёт. Next.js работает как server-side BFF по
[ADR-0008](../adr/0008-server-side-pilot-ui.md).

Сервер `web/` получает один заранее созданный bearer token через
`PROCUREMENT_API_TOKEN` и обращается к FastAPI по `PROCUREMENT_API_URL`. Token не
передаётся в browser JavaScript, формы, URL, `localStorage` или публичные
`NEXT_PUBLIC_*` переменные. Это доступ для внутреннего пилота одного tenant, а не
production-аутентификация пользователей.

`PROCUREMENT_DEMO_MODE=true` включает заметную постоянную маркировку деморежима.
Она означает, что данные синтетические или учебные; маркировка не заменяет
tenant isolation и не ослабляет правила решения.

## Пользовательский поток

1. Список запрашивает последние доступные версии кейсов через `GET /v1/cases`.
   Пустой результат показывается как отдельное состояние с переходом к импорту.
2. Импорт принимает полный JSON `ProcurementCase`, валидирует его через
   `POST /v1/cases` и создаёт новую immutable-версию. В S3 нет отдельных форм
   изменения профиля, процедуры или КП.
3. Карточка загружает точную версию кейса и показывает заказчика, предмет, НМЦК
   без НДС, deadline с часовым поясом, источники, КП, расходы, обязательные
   проверки и рейтинг.
4. Последнее решение читается из
   `GET /v1/cases/{case_id}/versions/{version}/evaluations/latest`. Если записи
   нет, карточка показывает `UNKNOWN` / «требует анализа», а не вычисляет зелёный
   статус в браузере.
5. Команда «Пересчитать» передаёт timezone-aware `effective_at` в
   `POST /v1/cases/{case_id}/versions/{version}/evaluations`. BFF создаёт новый
   `Idempotency-Key`, API сохраняет recommendation и audit атомарно, после чего
   карточка перечитывает последнюю сохранённую оценку.

Цвет карточки определяется только `Recommendation.decision`. Рейтинг остаётся
отдельным объяснимым показателем и не перекрывает `FAIL`, `UNKNOWN`, истёкший
срок, неполное КП или неполную экономику. Основания решения и неизвестные gate
проверки показываются рядом с результатом.

## Ошибки и состояния

Интерфейс различает пустой список, отсутствие сохранённой оценки, неверный JSON,
ошибку доменной валидации, конфликт immutable-версии, недоступность API и ошибку
серверной конфигурации/авторизации. Пользователь получает краткое действие для
исправления; traceback, bearer token, database URL и внутренние ответы с
секретами не отображаются.

Чужой и отсутствующий кейс остаются неразличимыми `404`, как в S2. Ошибка
пересчёта не заменяет ранее сохранённую оценку и не создаёт вымышленный результат.

## Локальный запуск

Сначала запустите PostgreSQL и API по
[инструкции S2](17-storage-api.md). Bootstrap печатает bearer secret один раз:

```powershell
Copy-Item .env.example .env
# Заполнить DATABASE_ADMIN_URL и DATABASE_URL разными локальными паролями.
docker compose up -d postgres
uv run alembic upgrade head
uv run python -m procurement.api.bootstrap --company-id demo-company --actor-id demo-operator
uv run uvicorn --factory procurement.api.runtime:create_runtime_app
```

В отдельном терминале задайте server-only настройки и запустите Next.js:

```powershell
Set-Location web
$env:PROCUREMENT_API_URL = "http://127.0.0.1:8000"
$env:PROCUREMENT_API_TOKEN = "<bearer-secret-from-bootstrap>"
$env:PROCUREMENT_DEMO_MODE = "true"
npm install
npm run dev
```

Экран доступен на `http://localhost:3000`.
Секреты задаются только локально или через будущий secret manager и не
записываются в Git.

## Проверка

- `npm run lint` — ESLint проходит;
- `npm run build` — production build Next.js 16.3.4 и TypeScript проходят;
- полный+backend набор: 318 тестов, из них 13 работают с реальным PostgreSQL 16;
- 9 doctests, Ruff и mypy для domain/API/storage проходят;
- desktop-экран проверен headless Edge на реальном потоке
  PostgreSQL → FastAPI → server-side Next.js с синтетическим зелёным кейсом.

Кнопка пересчёта использует текущее серверное timezone-aware время. Даже
сохранённая рекомендация `PARTICIPATE` показывается зелёной только пока открыта
подача, deadline не наступил, КП действует, а evaluation не рассчитана в будущем.
При нарушении этих условий UI показывает жёлтое «требуется пересчёт».

## Явные ограничения

- S3 не загружает документы и не извлекает из них процедуру, КП или требования;
- нет мониторинга источников, продуктовой аналитики и вымышленных KPI;
- один server-side token не является multi-user session auth, RBAC или MFA;
- нет production TLS, rate limiting, ротации секретов и deployment-контура;
- интерфейс не отправляет RFQ, заявку или ставку, не публикует предложение, не
  принимает заказ, не подписывает документы и не переводит деньги;
- юридические и остальные обязательные проверки остаются ручными данными S1;
- продажи «с полки» не получают автоматическую положительную рекомендацию.

## Связанный экран поиска S4

Срез S4 от 2026-09-16 добавил `/document-search` поверх tenant-scoped immutable
search API. Он использует тот же server-side bearer boundary, показывает
status/provenance для совпадений в названии, имени файла, нативном тексте и
vision-тегах и не превращает discovery-hit в compliance или рекомендацию.
Подробный контракт и acceptance evidence находятся в
[документе S4](../documents/19-document-pipeline.md#пользовательский-поиск-двадцать-четвёртый-срез-s4-2026-09-16).

## Изолированный экран completeness review S4

Маршрут `/completeness-review` показывает persisted review snapshots одного
native-документа ТЗ: source SHA-256, extraction status/reasons, mapped
requirements, unmapped-блоки и точный provenance. Форма не выбирает disposition
по умолчанию. Reviewer явно задаёт `PASS`, `FAIL` или `UNKNOWN`, scope, reason и
решение по нужным блокам; API повторно проверяет exact evidence digest и все
доменные инварианты. Сохранённое решение отображается read-only.

Страница использует `cache: no-store` и server actions. Bearer token хранится
только в `PROCUREMENT_API_TOKEN` серверного процесса и не передаётся в browser,
форму или URL. Текущий BFF не имеет browser session identity, поэтому маршрут
допустим только в отдельном внутреннем reviewer deployment с token роли
`COMPLETENESS_REVIEWER`. Добавлять привилегированный reviewer token как второй
скрытый credential общей operator BFF запрещено. Production-доступ потребует
отдельной session auth/RBAC/MFA границы.

Для локального изолированного reviewer deployment создайте отдельный ключ и
передайте выведенный secret только серверному процессу Next.js:

```powershell
uv run python -m procurement.api.bootstrap `
  --company-id demo-company `
  --actor-id demo-completeness-reviewer `
  --access-role COMPLETENESS_REVIEWER

Set-Location web
$env:PROCUREMENT_API_URL = "http://127.0.0.1:8000"
$env:PROCUREMENT_API_TOKEN = "<completeness-reviewer-secret>"
npm run dev
```

Snapshot предварительно создаётся operator-запросом к
`POST /v1/documents/{document_id}/completeness-reviews`; reviewer credential не
может создавать snapshot, а operator credential не может принимать решение.

## Изолированный экран review комплекта документов S4

Маршрут `/document-set-review?manifest_id=<exact-manifest-id>` открывает только
явно указанный immutable manifest из 2–10 документов. Очереди, `latest`,
автоматического выбора `PASS` и fallback на operator token нет. Страница
показывает exact scope/digest, constituent snapshots и decisions, source
provenance, mapping facts и server findings; сохранённое terminal decision
остаётся read-only.

Для этого маршрута нужен отдельный server-only
`PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN` роли `COMPLETENESS_REVIEWER`. Браузер
не получает bearer или API URL. Server action перед отправкой повторно загружает
evidence и сверяет manifest digest и все ordered decision references. Локальный
`PASS` возможен только при `PASS` каждого constituent, полном подтверждении
members и inventory, закрытом cross-document check и отсутствии findings;
иначе форма отправляет `UNKNOWN`.

Следующий ограниченный срез добавил typed `FAIL`: форма принимает уже
существующий constituent `FAIL` либо один новый
`CONFIRMED_MATERIAL_OMISSION | CONFIRMED_MISSING_DOCUMENT` с выбором source block
из текущего exact evidence. Finding ID и `REVIEWER` origin создаёт server action;
произвольные ссылки и свободный текст вместо evidence не принимаются. Action
повторно проверяет block range, объединяет свежие server/reviewer findings для
cross-document gates и не превращает `UNRESOLVED_*` в `FAIL`. Маршрут остаётся
внутренним изолированным reviewer deployment до появления production session
auth/RBAC/MFA.
## Загрузка ТЗ и КП через отдельные слоты (S69, 2026-09-19)

Оператор открывает `/document-upload` с главного экрана и выбирает один из
двух слотов: «Документ заказчика» или «Коммерческое предложение поставщика».
Каждый принимает один PDF/DOCX/XLSX до 20 МиБ. Server action передаёт в
существующий `POST /v1/documents` фиксированный для слота `document_role`:
`TENDER_REQUIREMENTS` либо `SUPPLIER_QUOTE`. Роль не выбирается из содержимого
файла и не поступает из произвольного поля браузерной формы. API проверяет
MIME/сигнатуру и хранит immutable bytes; интерфейс показывает document ID,
SHA-256 и результат извлечения (`PASS | FAIL | UNKNOWN`) с причинами.

Это пока загрузка отдельных документов, а не поиск закупок или полный
пользовательский кейс. Смешанные ZIP через эту форму не принимаются, хотя для
них есть отдельный API. Загруженное КП не превращается автоматически в
подтверждённое предложение, цену или рекомендацию. Статус извлечения текста
не означает completeness review и не создаёт допуск.

## Поиск серверных карточек в кейсе (S80, 2026-09-20)

Каждая карточка сохранённого кейса принимает запрос модели из 1–5 слов. Server
action вызывает tenant-scoped API, после чего экран заново загружает уже
persisted результат. Видны источник, время наблюдения, exact digest, ссылки на
товары и статус `нужна техническая проверка` либо `отклонено`.

Пустой успешный результат показывается отдельно от `SOURCE_ERROR`. Интерфейс
всегда напоминает, что публичная карточка не является КП, а отсутствие
привязанного проверенного набора требований оставляет технический scope в
`UNKNOWN`.

После S81 результат поиска дополнительно показывает идентификатор exact reviewed
set и digest его case binding. Если binding есть, backend применяет только его
typed требования и сообщает количество строк, оставшихся на ручную проверку.
Экран не предлагает выбрать «последний PASS» и не скрывает manual scope. Создание
proposal, независимое решение и case binding теперь имеют отдельные экраны
S82/S85 в раздельных operator/reviewer deployments; browser credential смешивать
нельзя.

## Материализация таблицы требований (S82, 2026-09-20)

После загрузки документа заказчика интерфейс предлагает перейти на
`/requirement-set-materialization` с exact document ID и SHA-256. На первом шаге
server action запрашивает preview всех строк у API. Сервер сам читает persisted
DOCX extraction; browser не отправляет name/value или provenance.

На втором шаге оператор видит все строки и отдельные числовые подсказки.
Checkbox ни у одной подсказки не выбран заранее. Для выбранной строки нужно
явно заполнить canonical property, обязательность и основание нормализации;
число и оператор остаются server-derived. Commit сверяет exact preview digest и
создаёт immutable proposal, а все невыбранные строки сохраняет как
`MANUAL_REVIEW_REQUIRED`. Экран показывает set ID, proposal digest и количество
исполнимых строк. Это operator workflow: terminal review и binding к версии
кейса выполняются отдельными маршрутами S85.

## Официальный источник производителя (S83, 2026-09-20)

Форма поиска модели использует прежний case-bound sourcing endpoint. Для точных
запросов `DL360 Gen12` и `SR630 V3` backend сначала читает официальный каталог
HPE или Lenovo. Карточка показывает «официальный каталог · manufacturer»;
supplier fallback помечается отдельно. Пользователь видит фактически
использованный source name, время и digest.

Официальная страница подтверждает существование семейства и служит источником
для дальнейшей технической проверки. Она не подтверждает установленную
конфигурацию, цену, наличие, КП или соответствие всему ТЗ, поэтому UI сохраняет
статус «нужна техническая проверка» и общий `UNKNOWN`.

## Несколько источников и Dell R660 (S84, 2026-09-20)

Поиск `PowerEdge R660` открывает официальный Dell Technical Guide. Для
`DL360 Gen12` один sourcing run показывает отдельные HPE official и ServerMall
attempts. У каждого видны ссылка, тип, статус и SHA-256 успешного снимка. Ошибка
одного источника отображается рядом с успешным другим и не маскируется общей
пустой выдачей. Если не получен ни один проверяемый snapshot, run показывает
общий `SOURCE_ERROR`.

Список найденных моделей формируется только из successful sources. Несколько
страниц семейств не доказывают exact совместимую конфигурацию, поэтому карточки
сохраняют «нужна техническая проверка», а решение остаётся `UNKNOWN`.

## Независимое решение по requirement set и binding (S85, 2026-09-20)

После materialization оператор получает ссылки на две разные поверхности.
`/requirement-set-review?set_id=…` показывает независимому reviewer все строки,
typed-нормализацию, manual scope, provenance и exact proposal digest. Форма не
выбирает assessments или `PASS | FAIL | UNKNOWN` заранее. Сохранённое решение
показывается read-only. Маршрут требует отдельный server-only
`PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN` и разворачивается в reviewer
deployment без fallback на operator credential.

`/requirement-set-binding?set_id=…` работает с operator token. До terminal
`PASS` форма отсутствует; после него operator явно вводит `case_id + version` и
видит оба связываемых digest. Server action повторно читает exact set перед POST.
Manual ordinals остаются видимыми: reviewer `PASS` и case binding не означают
полную техническую проверку, exact BOM или действительное КП.

## Exact BOM и КП proposal (S86, 2026-09-20)

После case-bound sourcing run у карточки найденной модели появляется переход
`/server-offer-proposal` с exact case, binding, run и lead references. Оператор
добавляет immutable document ID/SHA-256 загруженного КП, все строки поставляемого
BOM с locators и коммерческие условия. Ни status, ни данные публичной карточки
браузер не назначает: API повторно извлекает lead snapshot из persisted run.

Форма требует явный тип каждой BOM-строки, SKU, описание, Decimal-количество и
source locator. Цены строк можно оставить неизвестными для lump-sum КП; если они
заполнены все, API сверяет сумму с общей стоимостью без НДС. Coverage, НДС,
наличие, поставка, оплата и timezone-aware срок не выводятся автоматически.
Успешный результат показывает offer ID и proposal digest со статусом
`UNKNOWN / PENDING_REVIEW`. Он ещё не влияет на рекомендацию кейса.
## Независимая проверка server offer (S87, 2026-09-20)

Маршрут `/server-offer-review?offer_id=…` открывает только явно заданный exact
proposal. Reviewer одновременно видит все строки approved requirement set,
полный BOM, коммерческие условия, locators и digests. Для каждой строки форма
требует явный verdict и основание; PASS/FAIL требуют одну или несколько ссылок
на показанные BOM lines либо terms. Global assessments также пусты по умолчанию.

Маршрут использует только server-only
`PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN` роли `COMPLETENESS_REVIEWER` без
operator fallback. Server action повторно читает evidence и сверяет digest и
число строк. Итоговый status вычисляет API, а сохранённое terminal decision
показывается read-only. `PASS` этого review не создаёт scenarios и не разрешает
участие автоматически.
## Три сценария из PASS server offer (S88, 2026-09-20)

`/server-offer-economics?case_id=…&version=…&offer_id=…` работает только с
operator token и открывает exact PASS offer той же версии кейса. Goods и НДС
показаны read-only и переносятся backend из КП. Для каждого из base, realistic и
conservative форма требует выручку, все остальные статьи и допущение; поля не
заполняются нулями автоматически.

После сохранения экран показывает immutable package digest и
`recommendation_status=UNKNOWN`. Этот экран не изменяет case snapshot, hard
gates или recommendation и не может выдать `PARTICIPATE`.

## Следующая версия кейса из economics (S89, 2026-09-20)

После сохранения package тот же operator screen показывает отдельную команду
создания `version + 1`. Server action повторно загружает exact package и
сравнивает `economics_id + package_sha256`; browser не отправляет quote,
scenarios, assessment или recommendation.

Успешная команда показывает ID и номер новой версии. Экран прямо сообщает, что
из independent offer review перенесён только technical PASS. Остальные hard
gates требуют отдельной актуальной оценки, поэтому эта операция не означает
готовность к участию.

## Exact hard gates для новой версии (S90, 2026-09-20)

Кейс с единственным technical PASS получает переход
`/hard-gate-assessment?case_id=…&version=…`. Экран показывает locked technical
evidence. Для DOCUMENT оператор указывает exact binding ID и два digest; status
вычисляет API из terminal document-set review. Для LEGAL, PARTICIPANT,
COMPANY_POLICY и LOGISTICS status не выбран заранее. PASS/FAIL требуют document
ID, SHA-256 и locator, UNKNOWN допускает отсутствие evidence.

Server action перечитывает exact source digest перед POST. После успеха экран
показывает новую version, но не запускает recommendation: пользователь отдельно
оценивает новый snapshot на главном экране.
