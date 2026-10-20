> Исторический снимок плана до реорганизации 2026-10-06. Статусы и NEXT
> отражают момент записи; текущая задача — в [live-плане](../../15-implementation-plan.md).
> Содержимое и evidence сохранены; локальные ссылки перенесены механически.

### S218 — пакет исходного текста DOCX для проверки, серверный срез завершён 2026-10-06

Owner root: документация и последующий выбранный slice; Astra read-only audit
existing analysis/receipt/review contracts. Owned review files: sources/eis_analysis.py,
storage/eis_document_store.py, storage/eis_evidence_bridge.py, documents/extraction.py,
documents/bundle.py, models/migrations только для чтения. Зависимости: S216 release.
Acceptance: выбрать минимальный безопасный шаг к exact notice/content_uid/SHA
пакету полного ТЗ и raw delivery leads, честно отражая extraction/retention limits,
ZIP parent/member provenance и отсутствие утверждённого requirement set.
Не считать ограниченные snippets полным ТЗ, не менять case approvals и policy.

Выбранный S218 bounded foundation: отдельный source0 DOCX review revision
eis-native-review-v1, не менять analyze_document/v3/223 receipts. Sol owns только
новый sources/eis_document_review.py и tests/test_eis_document_review.py.
Root owns новый storage/eis_document_review.py, его PG tests, additive analyzer
check migration/models.py, bounded server wrapper и docs. Acceptance: exactnotice/
UID/expectedSHA/RECEIVED/current/tenant/hold gates; SQL byte-size до hydration;
immutable receipt+audit/replay0; native totals до retention, явные incomplete/
limits, bounded deterministic text pages и raw delivery/context leads с provenance.
DOCX only, остальные форматы явно unsupported, no source HTTP/jobs. Этот срез
предоставляет серверный пакет проверки; API/UI подключаются следующим срезом.
Role/positionassociation/approvedrequirements/fullTSpeccompleteness UNKNOWN.

Evidence:487isolatedPG PASS65.51s/zero skips; pure9/Ruff/mypy/Astra PASS. Deploy06:28:19UTC atomic13/host133/API28/worker28/head20261006_01. Real cached DOCX46657bytes:202blocks/35967chars,9losslesspages65–77ms,prepare238ms/replay76ms. One immutable analysis/audit; source0/jobs0/replay0,notice/v3digests unchanged,7negative gates PASS. Characteristic6API/direct identities/SSR6reads/5negative and3analogqueries1219–1556ms PASS. Native/fullTSpec UNKNOWN, body only; API/UInextS219. Proofs/pins/rollback: [docs100](../../documents/100-eis-document-review-capture.md).

### S219 — просмотр сохранённого текста DOCX в поиске ЕИС, завершён 2026-10-06

Владелец Sol: src/procurement/api/app.py и новый tests/test_eis_document_review_api.py.
Владелец root: новый web/src/lib/eis-document-review.ts, его wire/render tests и
отдельный test tsconfig; web/src/lib/procurement-api.ts, tender-discovery/actions.ts,
indexed-documents.tsx и новые document-review/report компоненты; документация и
ограниченные release/proof helpers. Astra — read-only contract review.
Зависимость выпуска: S218 foundation с migration20261006_01 и реальным cache proof.
Acceptance: отдельные POST prepare/page source0, body<=4096bytes с duplicate-key/
nonfinite/strict-field rejection; prepare только OPERATOR, read для авторизованного
читателя; exact notice/UID/SHA/current/tenant/hold gates, no-store/redacted errors.
UI предлагает анализ только полученного DOCX с известным SHA, показывает provenance,
body scope и native/fullTSpec UNKNOWN, counts/truncation и все страницы retained text
с парным block/character cursor. Никакого автоматического обхода всех страниц,
загрузок, RFQ или допуска. Wire validation связывает ответ с точным запросом и
cursor, проверяет размеры/счётчики/спаны/provenance; неизвестный или противоречивый
ответ блокируется. API negative tests, TS/Node/render/build и real installed API+
NextAction/SSR proof; визуальную браузерную проверку отмечать отдельно.
S219 уточнение high-risk review: prepare выполняется отдельным ограниченным
процессом, а не DOCX-разбором в API thread. Sol дополнительно owns новый
api/eis_document_review_runner.py и tests/test_eis_document_review_runner.py.
Один активный prepare на API process, busy503; child CPU30s/AS512MiB и parent
wall45s, никаких source credentials/HTTP. Read остаётся source0 cache read.

S219 evidence:509isolatedPG PASS73.54s/zero skips; final34Linux API/runner PASS11.17s,
Node8/13/11/8 +TS/ESLint/build/review PASS. Backend06:49:44/web06:50:39/authfix06:58:12,
host147/API29/worker29/web31/head06. Actual freshAPI1698ms/replay1541ms/2pages66–107ms,
source0/jobs0/1immutableanalysis+audit/notice+v3unchanged/10negativegates PASS.
InstalledNextActionSSR2pages76–77ms/6negative; largerDOCX7pages19–26ms lossless.
No browser visual claim. OpsDB5525920791/free251823386624/testDB0/health200/markersfalse.
Proofs/pins/rollback: [docs101](../../documents/101-eis-document-review-ui.md).

### S220 — поиск источников снабжения из позиции ЕИС, реализация начата

Owner root: точный контракт, storage/API/UI, docs и release; Sol получает отдельный
source adapter/types и синтетические tests после фиксации контракта. Astra read-only
high-risk review. До реализации owner files и acceptance фиксируются отдельно.
Зависимость: sealed S219, exact current/source-hold/tenant-gated position reader.
Одно выбранное наименование ЕИС + отдельные exact DOCX fragment refs, без скрытого
переноса body-only анализа в approved requirements или manual uploaded document.
Первая уже поддержанная категория, ограниченные источники/карточки; сохранять
URL/time/digest и публичную цену Decimal только при явном source evidence.
Цена «от», цена базовой сборки и лизинговый платёж имеют разные типы; ни одно не
является полным КП/стоимостью исполнения. НДС/наличие/срок/соответствие UNKNOWN
при отсутствии доказательства. Cache replay source0, RLS, immutable observations,
stale/hold/unsupported/ambiguous/no-price negatives. Никаких RFQ отправок,
подтверждения требований, прибыли или PARTICIPATE в этом срезе.
Обоснование: текущий Supplier Discovery принимает отдельный uploaded DocumentRecord,
а результаты поиска пока не привязаны и не сохраняются к exact позиции ЕИС.
Завершённый S219 даёт текст, но ещё не закупочную цену. Оптимизация cached prepare
(~1.5s против read20–100ms) ниже этого продуктового приоритета.

Последовательные milestones S220 (2026-10-06):
1. Source contract: Sol owns только новые `sources/eis_supplier_catalog.py` и
   `tests/test_eis_supplier_catalog.py`. Проверить фактическую разметку одной
   фиксированной публичной категории ServerMall, затем типизированно сохранить
   название/ссылку и только доказанную цену с её scope/raw label/locator/SHA/time.
   Неоднозначная или отсутствующая цена UNKNOWN; цена базы/«от»/лизинг не КП.
   Acceptance: <=1 GET, <=2MiB, <=10 результатов, unsupported query source0,
   строгие provenance/Decimal/URL/limits и синтетические negative tests.
2. Exact-position persistence: после freeze source contract назначить отдельные
   owned files для reader/storage/migration/API. Дважды проверить current/hold/
   tenant и exact source (до HTTP и перед записью), immutable snapshot+audit,
   сохранённый результат читается source0. Failed fetch не маскирует older result.
   Внешний запрос не держит DB transaction/tenant lock; конкурентный повтор
   ограничивается, refresh явный. Cache не означает актуальную цену поставщика.
3. UI/release: кнопка из exact позиции, понятное покрытие одной категории,
   карточки и ценовые ограничения. Один завершённый реальный server-side путь,
   cache replay/negative isolation и установленный API/UI proof до объявления
   среза завершённым. Installed gates S220 выполнены, результаты приведены ниже.

Каждый следующий milestone получает конкретные owned files до начала edits.
Root owns docs15/docs07/новые docs102 и ADR0090/release helpers; Astra read-only
review. Зависимости между milestones последовательные, старые admission gates,
ЕИС source budgets и процедуры отправки не меняются.

Milestone2 files зафиксированы: root owns extraction общего connection reader в
`storage/eis_characteristic_compare.py` (семантика исторических пар сохраняется),
новые `storage/eis_supplier_search.py`, `tests/integration/test_eis_supplier_search_pg.py`,
additive tables в `storage/models.py`, migration `20261006_02_eis_supplier_search.py`.
Acceptance reader: старые pair tests неизменны; новый current gate существует
только в supplier flow; name evidence exact, отсутствие/сокращённое наименование
не становится запросом. Query фиксированно выводится из наименования и проверенной
категории, совпадение по названию не является проверкой характеристик.

Milestone3 files: Sol owns только additive API additions в `api/app.py`, новый
`api/eis_supplier_search_runner.py`, `tests/test_eis_supplier_search_api.py` и
`tests/test_eis_supplier_search_runner.py`. Root owns новые web/lib/eis-supplier-search.ts,
supplier-search/report компоненты, wire/render tests/tsconfig, additive actions/API
client и position-evidence.tsx. API prepare только OPERATOR; read authenticated;
Root дополнительно owns additive indexed-documents.tsx: позиции доступны прямо
из сохранённой связки карточки, только при совпадении exact notice с parent.
strict <=4096byte request/no-store/typed safe errors. Prepare isolated child one
slot, bounded CPU/address-space/wall time, только app DSN и allowlisted public
HTTP configuration; ни admin/EIS credentials, ни произвольных env. Child result
связан с exact request. API/schema/wire/SSR/negative gates до выпуска.

S220 завершён: 150 final isolatedPG/API/runner/source tests PASS24.82s/zero skips;
Node6+8+13+11+8/TS/ESLint/build и независимый review PASS. Installed
0133200001726002460v2/position1: один GET2236ms/8leads/14prices;
read95ms/NextAction132ms/source0. STARTED+final/audit2/immutable; negativeHTTP8,
realrepairroomunsupported0, NextAction5negative, legacyDOCX/characteristics/analogs
PASS. Host166/API33/worker33/web39/schema20261006_02, cron/source budgets прежние.
Полный рынок/комплектация/ТЗ/КП/прибыль/участие UNKNOWN. Подробные proofs/pins/rollback
в [docs102](../../suppliers/102-eis-position-supplier-search.md).

## S221 — операторская связь позиции с сохранёнными фрагментами DOCX

Статус: завершён и установлен 2026-10-06. Зависимости: sealed S219/S220.
Цель: сформировать проверяемую исходную спецификацию для дальнейшего сравнения
товара и RFQ. Связь фрагментов не утверждает нормализованные требования,
полноту ТЗ, соответствие товара или допуск.

Последовательные milestones и ownership:

1. Sol owns новые `sources/eis_position_association.py`,
   `storage/eis_position_association.py`, `tests/test_eis_position_association.py`,
   `tests/integration/test_eis_position_association_pg.py`. Root owns additive
   `storage/models.py` и `migrations/versions/20261006_03_eis_position_association.py`.
   Exact current position + тот же notice в ReviewDocumentRequest + frozen
   `eis-native-review-v1` + до 10 непересекающихся диапазонов символов блоков.
   Клиент передаёт только селекторы; сервер извлекает полный выбранный текст,
   original provenance, source character count и digest анализа из cached review.
   До 16000 выбранных Unicode characters/256KiB report; одна consistent snapshot,
   RLS/immutability/audit/replay/current/hold/source0, без blob hydration/network.
2. После freeze контракта root owns additive `api/app.py`,
   `tests/test_eis_position_association_api.py`, новые
   `web/src/lib/eis-position-association.ts`, `.../position-association.tsx`,
   `.../position-association-report.tsx`, wire/render tests/fixture/tsconfig;
   additive API client/actions и `document-review.tsx`, `indexed-documents.tsx`.
   В DOCX review выбираются exact позиция и показанные фрагменты из разных
   страниц; действие явно сохраняет операторскую связь. Полнота/requirements/
   technical/quote/participation остаются UNKNOWN. Ошибка или смена exact
   документа/позиции не оставляет старый результат под новым выбором.
3. Root owns docs15/docs28/README, новый docs103/ADR0091 и release helpers;
   Astra read-only review. Acceptance: реальная позиция → селекторы с двух
   страниц → immutable связь → source0 повтор/API/NextAction/SSR. Tenant,
   stale version/SHA/revision, hold, client text/locator injection, overlapping
   or outside ranges, total limits/replay проверены. Gates до установки;
   source cron/budgets и admission прежние.

Root дополнительно owns `tests/fixtures/eis-position-association.json` для
dependency-complete API gate: fixture одинаков с web wire fixture и валидирован
Python contract. Все три milestones завершены: 189 final Python/isolatedPG/API
tests PASS43.27s/zero skips, Node51/TS/ESLint/build и независимый review PASS.
Backend08:19:13/web08:19:16UTC, host182/API36/worker36/web46/schema03.
Actual paperposition1/notice0107300009526000178v2: blocks1+32 из двух страниц
price-justification DOCX, 2fragments61chars, save198ms/replay160ms/read133ms,
1immutable association+1audit/source0/jobs0. NextAction read186/save148ms,
API10/NextAction6negativePASS, compiledSSR PASS; browser visual NOT_PERFORMED.
Legacy DOCX/supplier cache/characteristics/analogs PASS. OpsDB5574859799bytes/
free251540631552bytes/testDB0/health200/markersfalse. Полнота ТЗ/утверждённость
требований/соответствие/КП/участие UNKNOWN. Подробные evidence/pins/rollback:
[docs103](../../documents/103-eis-position-fragment-association.md).

Оптимизация установки: additive source0 release использует deployment mutex и
bounded DDL, не ждёт dispatch/import leases всего intake. Старые работающие
workers совместимы со schema03 и продолжают загрузку; cron/лимиты не изменены.
Tenant lease на самой записи связи остаётся обязательным и взят до RR snapshot.
Следующий ограниченный продуктовый срез: восстановление сохранённого контекста
позиции после перезагрузки; затем нормализация требований и сопоставление
конфигурации предложения перед RFQ/КП/экономикой.

## S222 — восстановление сохранённого контекста после перезагрузки

Статус: завершён и установлен 2026-10-06. Зависимость: sealed S221, schema20261006_03.
Вертикальный срез: точная карточка/позиция/документ → bounded список сохранённых
операторских связей → выбор association ID → полный проверенный source0 report
без повторного выделения строк. Автоматический выбор связи не выполняется.

Sol owns только additive `sources/eis_position_association.py`,
`storage/eis_position_association.py`, `api/app.py`, их три существующих
pure/PG/API test files и shared `tests/fixtures/eis-position-association.json`.
Acceptance: strict typed scope same notice/position/document/revision, canonical
UUID, ограниченные metadata pages (20 + stable typed cursor), точная связь ответа
с запросом, tenant/current/hold/receipt/source/digest guards на list/detail,
read-only repeatable-read, source0/jobs0/writes0, существующий save/replay не
изменяется. Полный report проверяется реконструкцией из immutable источника.
Нет blob hydration, новой таблицы/миграции, скрытого fallback на старую связь.
Root owns additive web wire/client/actions/association UI и существующие
wire/render tests/fixture, новый pure `position-association-list.tsx` и additive
`tsconfig.position-association-tests.json`; документацию docs15/28/README, новый docs104/ADR0092
и ограниченные release helpers. Astra — read-only high-risk review.
Milestones: (1) freeze backend contract/tests, (2) UI restore with bounded list
and explicit choice, (3) focused final gates/build/review, installed existing
двухстраничная связь и 2 distinct selections, negatives и source0 proofs.
Код/документация каждого milestone устанавливаются только после gates.
Никакого approved requirements, technical PASS, полного КП/прибыли/участия;
эти значения остаются UNKNOWN. Source budgets/cron не меняются.

Все milestones завершены: final197Python/API/isolatedPG PASS45.90s/zero skips,
Node55/TS/ESLint/build/independentreview PASS. Backend09:39:03/web09:39:12UTC,
host185/API36/worker36/web47/schema03. Realpaperposition1: восстановлены две
разные связи по ID без fragment selectors, list142–150ms/detail137–149ms,
NextActionlist147–188/detail145–217ms, API10/NextAction6negative PASS.
Чтения source0/jobs0/writes0. OpsDB5682658327/free251283402752/testDB0/health200/
markersfalse. Same-SHA re-receipt regression: текущий basis фильтруется до LIMIT,
старая связь не блокирует новые страницы и не выдаётся как текущая. Browser
visual NOT_PERFORMED; actual installed actions/compiled SSR проверены.
Proofs/pins/rollback в [docs104](../../documents/104-eis-position-association-restore.md).

Следующий milestone: классифицировать выбранные строки и формировать
неподтверждённый проект требований с exact fragment provenance. Не переносить
обоснование цены или публичную цену базы в техническое требование/КП. Затем
сопоставлять конфигурацию предложения, выявлять неизвестные характеристики и
готовить RFQ draft; внешняя отправка остаётся отдельным exact-payload approval.

## S223 — поисковики как источник новых поставщиков

Приоритет изменён пользователем 2026-10-06: сначала расширить поиск снабжения
за пределы фиксированных каталогов, используя несколько поисковых систем и
браузер без платного search API. S222 остаётся основанием exact контекста;
нормализация требований выполняется перед подтверждением соответствия товара.

Owner root: план/ADR/research, bounded VPS browser probe и интеграция после
freeze контракта. Astra: read-only architecture/high-risk review. Реализация
адаптера получает отдельные owned files и acceptance после измерения доступности.
Research-owned файлы: ignored `data/research/eis-documents-2026-10-02/s223-*`,
docs15/docs07/README, новый docs105/ADR0093. Зависимость: sealed S222.

Последовательность:
1. Проверить обычным Chromium на VPS один публичный товарный запрос в нескольких
   поисковиках: статус/время/DOM bytes/ссылки. Ограничить CPU/RAM/время/страницы;
   не трогать intake workers. CAPTCHA/403/429/consent не считать пустой выдачей.
2. Типизированный multi-engine adapter: запросы по публичной exact позиции,
   доказанные URL/title/snippet с engine/query/time/DOM digest и отдельным
   результатом каждой попытки. Dedupe domains/URLs, bounded fanout/cooldown/cache.
   Производитель/поставщик/дилер — кандидатные роли, подтверждаются на сайте.
3. Открытие ограниченного набора сайтов продавцов, evidence цены/единицы/НДС/
   партии/комплектации/наличия/срока. Search snippet не является прайсом или КП.
4. Сравнение сопоставимых предложений по полной стоимости партии и срокам;
   неполная комплектация и неизвестные расходы не получают выгодный рейтинг.
   RFQ сначала draft, внешняя отправка требует exact-payload approval.

Первый законченный slice и его owned source/storage/API/UI files будут закреплены
после live feasibility. Оплата search API не включается. Браузерные запросы имеют
стоимость VPS и обслуживания; скорость/устойчивость измеряется, не обещается.
Никакой CAPTCHA solving, stealth/fingerprint spoofing, смены IP после отказа
или открытия личного Chrome-профиля. Полный рынок/полное КП/участие UNKNOWN.

S223 implementation ownership зафиксирован перед edits: source adapter owner
Sol-role acquisition agent — только новые `sources/supplier_serp.py` и
`tests/test_supplier_serp.py`. Storage/API owner Sol — новые
`storage/eis_supplier_serp.py`, `api/eis_supplier_serp_runner.py`, additive
`api/app.py`, новые `tests/integration/test_eis_supplier_serp_pg.py`,
`tests/test_eis_supplier_serp_api.py`, `tests/test_eis_supplier_serp_runner.py`,
`tests/fixtures/eis-supplier-serp.json`. Root — additive `storage/models.py`,
новая migration `20261006_04_eis_supplier_serp.py`, новые web wire/components/
wire-render tests/fixture/test tsconfig, additive client/actions и подключение
рядом с S220; docs/release helpers. Review Astra read-only.
Root web owned files: новые `web/src/lib/eis-supplier-serp.ts`,
`.../supplier-serp.tsx`, `.../supplier-serp-report.tsx`, новые wire/render
tests/fixture и `tsconfig.supplier-serp-tests.json`; additive
`web/src/lib/procurement-api.ts`, `.../actions.ts`, `.../supplier-search.tsx`,
`.../position-evidence.tsx`, `.../position-association.tsx` (публичное название
для preview отправляемого запроса). Изменение фиксированного S220 wire не нужно.

Frozen slice: BING/YANDEX/GOOGLE по одному запросу/странице; обычный браузер,
слоты/cooldown/tenant budget, strict public position query, immutable STARTED
и final/audit, DOM capture/provenance, latest outcome replay source0, одно из
трёх результатов может быть полезным при BLOCKED остальных. Live probe Bing
действительно содержит 10 organic blocks; Yandex/Google blocked, новые engines
Brave429/Mojeek403/Ramblerchallenge/Yahoo500 не добавляются без подтверждения.
Это пилот multi-engine attempts, не доказательство доступности трёх выдач.
Acceptance: API/UI exact-position search+saved read, real3attempts/1source with
organic links, bounded source counts/statuses/dedupe/provenance/unsafe URLs,
tenant/current/hold/cooldown/concurrency/failedrefresh/processcleanup/no-secret
negative gates и installed proof. Candidate sites не открываются этим срезом,
ни manufacturer identity, ни цена, ни соответствие не подтверждаются сниппетом.


S223 итог 2026-10-06: установлен полный bounded API/UI slice. 263 Python/API/PG
PASS без пропусков; 63 Node wire/render PASS, TypeScript/ESLint/build PASS;
Astra/source и S203/runner-storage reviews закрыты. Live бумага: 3762 мс,
Bing10 ссылок, Яндекс BLOCKED, Google SOURCE_CHANGED; read92 мс/source0.
STARTED+final/audit2, installed Next Action+compiled SSR125 мс read; browser visual
NOT_PERFORMED. Остаточные browser processes0/OOMfalse; schema04; host203/API40/
worker40/web54, cron unchanged. Точные SHA, image pins и ограничения: [S223](../../suppliers/105-eis-position-supplier-serp.md).
Цена/поставщик/соответствие/КП/участие/полный рынок UNKNOWN.

## S224 — чтение сайта кандидата и опубликованные цены (COMPLETE в bounded scope)

Последовательный следующий срез: источник URL — только сохранённый SERP run,
engine и rank, с точной current позицией ЕИС. Сервер повторно проверяет основание
и выводит адрес из сохранённого evidence. Произвольный client URL не принимается.

1. Bounded public HTTP чтение сайта с DNS/IP/redirect защитой, без личного профиля,
   обхода антибота и обращения к внутренним адресам; raw snapshot, typed outcome,
   цена Decimal и provenance. Выделить товарные страницы из категорий и статей.
2. Наблюдения товара/продавца/бренда, цены/валюты/единицы/упаковки/минимальной партии,
   НДС, наличия и срока; каждое отсутствующее условие UNKNOWN. JSON-LD/видимый
   текст не повышают коммерческое предложение до действительного полного КП.
3. Привязать проверяемую комплектацию к публичным характеристикам и выбранным
   фрагментам документов ЕИС. Категория магазина и цена «от» не получают
   configured unit cost и выгодный рейтинг.
4. Сопоставить полную стоимость партии при известных условиях. При недостатке
   данных — объяснить пробелы и подготовить draft RFQ. Отправка только после
   exact-payload approval; PARTICIPATE требует полного КП и трёх сценариев.

Пункты 1–2 выполнены для одного HTTPS HTML/UTF-8 JSON-LD документа в ограничениях
контракта ниже. Пункты 3–4 остаются следующими последовательными milestones;
реальные цены на трёх выбранных страницах не извлечены. От пользователя не нужен ручной прайс.


S224 ownership/acceptance зафиксированы до implementation 2026-10-06.
Astra — read-only архитектура/SSRF review; design approved: отдельный HTTPS-only
DNS-pinned transport без proxy env, только один HTML документ, никаких JS/подресурсов.
Source owner Sol (acquisition agent): новые `sources/supplier_page.py`,
`tests/test_supplier_page.py`. Contract: Fetch/extraction outcomes отдельно;
2 MiB HTML, 30 с общий wall, max 2 redirects / 3 HTTP dispatch; каждый hop
валидируется, DNS mixed-public/private отклоняется; TCP в pinned IP + TLS hostname
verification/SNI, не обычный повторный DNS. JSON-LD Product/Offer/AggregateOffer
с Decimal и locator, category/article не становятся full quote/unit cost.
Storage/API owner Sol: новые `storage/eis_supplier_page.py`,
`api/eis_supplier_page_runner.py`, additive `api/app.py`, новые
`tests/test_eis_supplier_page_api.py`, `tests/test_eis_supplier_page_runner.py`,
`tests/integration/test_eis_supplier_page_pg.py`, `tests/fixtures/eis-supplier-page.json`.
Exact request: saved current position + parent SERP run UUID + engine + original
rank. URL выводится из tenant-owned immutable parent report; parent hash и link
сохраняются. STARTED+final/audit; последние ошибки видны; read/repeat source0;
refresh15m; tenant slot1/API slot1; 30 новых чтений/час, 64MiB body/24h с
резервом2MiB. Неизвестная ошибка после dispatch сохраняет STARTED/UNKNOWN.
Root owns additive `storage/models.py`, frozen migration05, new web wire,
page client/report components, wire/render tests/fixture/tsconfig; additive
SERP report/client, BFF/actions; docs15/docs28/docs07/README/docs106/ADR0094;
ignored s224 release/proof helpers. No overlapping edited files.
Acceptance: real selected link fetch through API/UI + immutable source0 replay;
source evidence/status/Decimal/range/category truthfulness, DNS/TLS/redirect/
body limits, tenant/current/hold/quotas/failed attempts/process cleanup negative
checks; isolated PG and production build; actual VPS measurements. No best-price
rank, no supplier-role verification, no full quote/compliance/PARTICIPATE claims.
S224 covers site reading/public price observations; specification matching and
comparable total cost are subsequent sequential milestones.

S224 итог 2026-10-06: 336 Python/API/PG PASS, zero skips; 73 Node wire/render,
TS/ESLint/production build PASS. API/UI установлены, schema05. Actual3 links:
Комус200/HTML261749/EMPTY, ВсеИнструменты403/BLOCKED, Бумага-С первоначальный
EOF bug; исправлен, bounded diagnostic200/HTML46595/EMPTY за314мс. Реальных
цен0. Source0 API read73–92мс, installed Action read82–152мс. Rows6/audits6,
helpers0/OOMfalse, intake непрерывный. Browser visual NOT_PERFORMED.
Полные измерения, SHA/pins и ограничения: [S224](../../suppliers/106-eis-position-supplier-page.md).

## S225 — конкретные товарные карточки из выбранного сайта (COMPLETE в bounded scope)

Порядок уточнён по S224 live evidence: SERP по бумаге ведёт преимущественно на
главные страницы и категории, поэтому чтение одной страницы не даёт предложения.

1. Source0 исследовать приватные сохранённые HTML «Комус»/«Бумага-С»: есть ли
   устойчивые товарные ссылки и evidence, позволяющие отделить товар от меню,
   рекламы, статьи и login. Никаких догаданных product URL.
2. Зафиксировать один bounded adapter и exact parent HTML/SERP/позиция contract.
   Вывести кандидатов с SHA/locator и неизвестным соответствием; перед чтением
   каждой карточки повторить hostname/DNS/TLS/current/tenant/budget guards.
3. Прочитать ограниченное число подходящих карточек, сохранять immutable outcomes
   и показать public product/price facts. JS-only и unsupported layout явно UNKNOWN.
4. Затем отдельный milestone: сопоставить комплектацию/единицу/упаковку/партию
   с требованиями ЕИС, hard FAIL блокирует. Полный расчёт и RFQ/КП — после этого.

Владелец, owned files и acceptance S225 фиксируются перед его реализацией.

S225 ownership/acceptance зафиксированы 2026-10-06 перед edits кода.
Research: Комус main/category/white category не содержат product href в retained
HTTP HTML; обычный browser503robot — остановлен. Targeted Bing query не соблюдает
site scope, не принимается как поиск товара. Бумага-С retained homepage содержит
GET form /categories/search, input#global_search name=q; exactpublicname ЕИС
«Бумага для офисной техники» даёт HTTP200/109810 и labeled /товар/ links.
Эффективный slice: один search GET на подтверждённом сайте, затем один выбранный
товар из exact immutable search snapshot. Никакого category crawl/guessedURL.

Source owner Sol/acquisition: new sources/supplier_catalog.py,
tests/test_supplier_catalog.py; additive supplier_page.py/test_supplier_page.py
только optional allowed_host для guard каждого redirect. Source DTO typed
search spec/links HTMLSHA+locator, parser revision, immutable ordinal≤10;
plainprice/productfacts source observations with UNKNOWN commercial flags.
Backend owner Sol/characteristic: new storage/eis_supplier_catalog.py,
api/eis_supplier_catalog_runner.py; additive api/app.py; new API/runner/PG tests
and syntheticfixture tests/fixtures/eis-supplier-catalog.json. Additive
storage/eis_supplier_page.py только общий budget/tenant slot с каталогом.
Root: additive models.py, frozen migration06; new web wire/client/report/tests/
fixture/tsconfig, additive supplier-page client/report, BFF/actions; docs15/28/
07/README/new107/ADR0095 и ignored release/proof helpers. Astra read-only review.
Owned files disjoint, source DTO freezes before storage implementation.

Request: page(S224 exact request), page_run_id, search_run_id|null,
product_index|null. Optional pair joint. URL/query only server-derived from
tenant-owned root HTML/publicposition or saved search link. SEARCH+PRODUCT
immutable STARTED/final/audit; read/cache source0; root/latest errors not hidden.
Shared S224+S225 30starts/hour/64MiBbody24h reserve2MiB, same tenant fetch slot;
child40s/CPU10/body2MiB/dispatch3. Only bumaga-s-v1 observed markup enabled,
unsupported form/layout explicit; exacthostname at every redirected hop.
Acceptance: actual search lists product links → selectedproduct read → API/UI
saved source0 replay; no clientURL/query, stale/hold/tenant/parent/body/ordinal/
digest/redirect/budget/type gates, realPG/build/installedproof. Publishedprice
does not become unitcost/fullquote/technicalmatch or beneficial ranking.

S225 итог:403 Python/API/PG PASS/zero skips;84 Node wire/render+TS/ESLint/production
build PASS. Installed schema06/API/UI. Live fullpublicname бумаги→10 links
(truncated=true) за2759мс→selectedSvetoCopy299.6RUB за2020мс. Read73–127мс/source0.
Цена остаётся заявлением сайта, упаковка/НДС/доставка/соответствие UNKNOWN.
Root+2rows/audits, catalog+4rows/audits;helpers0/OOMfalse/intakecontinuous.
Browser visual NOT_PERFORMED. [Контракт и proof SHA](../../suppliers/107-eis-position-supplier-catalog.md).

## S226 — условия сохранённого товара рядом с позицией ЕИС (COMPLETE)

S226 ownership/acceptance зафиксированы 2026-10-06 перед implementation.
Slice уточнён по retained evidence: source0 производная карточка одного S225
PRODUCT, raw характеристики и условия рядом с current публичной позицией ЕИС.
Price denominator не заявлен, packing5/100 неоднозначна, data-package5 только
control. Поэтому нет unitcost/стоимости партии/MOQ=1/technicalPASS. Legacy XML
range incomplete; mandatory состав/полнота ТЗ не подтверждены. Сравнение в этом
slice UNKNOWN с raw evidence обеих сторон; полный deterministic hardgate engine
используется после reviewed requirement contract, отдельным milestone.

Source owner Sol/acquisition: new sources/supplier_product_details.py,
tests/test_supplier_product_details.py. Typed bounded details from retained2MiB
active unique main Product: raw name/characteristics/packing/contents/control,
SHA/locator, failure/ambiguity/hidden nofalsefacts. No HTTP calls.
Backend owner Sol/characteristic: new sources/eis_supplier_product.py,
storage/eis_supplier_product.py; additive api/app.py; new API/unit/PGtests and
synthetic fixture. Exact request catalog(S225 PRODUCT request)+product_run_id;
full current position +parent report/body hash. Tenant immutable cached source0
prepare/read, metadata guards beforebody; cache/read noHTML; no jobs/HTTP.
Root: additive models.py/frozen migration07; web productwire/client/report/tests/
fixture/tsconfig, additivecatalogclient/BFF/actions and reuseexportpositionwire;
docs15/28/07/README/new108/ADR0096, ignored releaseproofhelpers. Astra readonly.
Acceptance: real savedproduct→rawterms+currentEISsidebyside→cache/read zeroHTTP;
400 пачек vs500листов/packing5/100 explicitUNKNOWNeconomicbasis; >=80<90 legacy
range vs80±3 no inventedPASS/FAIL; tenant/current/hold/body/report/digest/parent/
parserbound/immutability tests, realPG/Nextbuild/installedAction+SSR. Source0 work
does not require fetching supplier again. No overlapping ownededits.

Итог S226: installed schema07/API/UI;437 Python/API/PG PASS/zero skips,
94 Node wire/render+TS/ESLint/production build PASS. Read163мс/cachedprepare142мс,
Next Actions156–260мс/source0. Реальные6supplierfields/4publicrows, упаковка5/100,
содержимое500листов, все conclusionsUNKNOWN; profit/PARTICIPATE не вычисляются.
Tenantproduct1/audit1;page8/catalog4 unchanged, rawbody без дублирования.
DB5991701527/free250369658880,health200,testDB0/helpers0/OOMfalse;
API122.1MiB/1GiB/web64.88MiB/768MiB, intake/cron продолжаются.
Browser visual NOT_PERFORMED. [Контракт, pins и proof](../../suppliers/108-eis-position-supplier-product.md).

## S227 — таблица характеристик сохранённого DOCX рядом с товаром (COMPLETE)

Контракт уточнён по live evidence 2026-10-06: S221 associations у бумаги связаны
с обоснованием цены (название объекта и сумма), а не с описанием объекта.
Actual POD КУМС DOCX `727bf17ff7b085e150ace59cab5016512ff6ba16026e890393ee7fb85e5863c2`
уже получен; содержит отдельную таблицу2 с4характеристиками, sectionrow и
инструкциями. Native55blocks PASS не подтверждает роль/полнотуТЗ.

В этом milestone: readonly source0 preview exact S226 product + выбранный
existing review DOCX + table_index. Сначала явный существующий prepareReview,
затем preview из authoritative reviewv1, без новых downloads/parser/DBwrites.
Все retained table cells показаны со spans/locator/SHA; пустые и merged ячейки
в старом native extraction не сохранены, их структура UNKNOWN, отсутствующий
текст не называется пустой ячейкой. Исходные инструкции не теряются.
Числовые подсказки неисполняемы: >=500, >=80 AND <90; никакого inclusiveBETWEEN,
mandatory/approval/technical/fullTS/participation UNKNOWN. No fictional review.

Owner Sol/acquisition: new sources/eis_requirement_table.py и source tests.
Owner Sol/characteristic: new sources/eis_requirement_preview.py,
storage/eis_requirement_preview.py, additiveapi/app.py; newunit/API/PGtests и
syntheticfixture. Root: newwebwire/client/report/tests/fixture/tsconfig,
additiveS226client/BFF/actions, docs15/28/07/README/new109/ADR0097 и releasehelpers.
Astra: readonly contract/source/backend closure. Ownedfiles disjoint.
Acceptance: actualretainedPODtable2 all4characteristics+section+instructions,
exactproduct/doc/analysis/current/hold/tenant guards, duplicates/gaps/limits/
openbounds/mergedambiguity, repeatedstablepreviewSHA source0/write0, realPG/
productionbuild/installedAPI+NextActions+SSR. One bounded slice periteration.

Итог:474Python/API/PG PASS/zero skips;106Node+TS/ESLint/productionbuild PASS.
Installed actualtable2:4характеристики+sectionrow/24cells/4instructions.
Readonlypreview215–268мс/NextActions230–338мс, sameSHA/source0/write0.
Schema07 без новых таблиц/миграций; helpers0/OOMfalse/testDB0/health200.
DB6001007639/free250253279232;API123.4MiB/1GiB/web64.27MiB/768MiB.
Intake223 продолжился и добавил8собственныхaudits, отдельно от preview.
Нормативная роль/mandatory/technical/fullTS/participation UNKNOWN.
Browser visual NOT_PERFORMED. [Контракт/evidence/pins](../../documents/109-eis-requirement-table-preview.md).

## S228 — проверенные требования и технический допуск (NEXT)

1. Сверить existing reviewed/compliance контракты с exact S227 preview digest,
   current позицией, выбранным native документом и ролью источника. S221 связи
   обоснования цены не превращать в нормативные требования. Подтверждение
   интерпретации и роли относится к точным исходным ячейкам/инструкциям.
2. Реализовать один bounded путь: S227 server-derived cells → предложение
   нормализации или MANUAL_REVIEW_REQUIRED для каждой строки → настоящее
   независимое exact-digest решение и binding с provenance → saved PRODUCT →
   подтверждённая нормализация фактов → existing deterministic engine
   PASS/FAIL/UNKNOWN и объяснение по каждому проверенному требованию.
   Mandatory FAIL блокирует кандидата; неполнота остаётся UNKNOWN.
3. Подтвердить реальную цепочку на VPS, отсутствие повторного HTTP и подмены
   tenant/current/doc/product. Ownership, owned files, acceptance зафиксировать
   перед кодом; избегать параллельного изменения общих файлов.

Дальше последовательно: подтверждённая единица цены/упаковки/MOQ/НДС/доставки →
стоимость партии и сравнение предложений → draft RFQ → полное действующее КП →
base/realistic/conservative. PARTICIPATE только после всех существующих gates.
Внешняя отправка RFQ требует exact-payload approval.


## S228 — независимое решение по выбранной таблице и проверка формата

Статус: COMPLETE для выпуска механизма, установлен 2026-10-06.
Настоящее независимое решение по production предложению PENDING. Владелец интеграции — root. Зависимости: установленный
S227, exact сохранённый S226, существующая роль COMPLETENESS_REVIEWER.

Последовательные milestones: заморозить контракт → чистые DTO/правила →
PostgreSQL/API → экран → негативные проверки → bounded release.

Owned files:
- Sol / acquisition_research: sources/eis_requirement_review.py,
  tests/test_eis_requirement_review.py.
- Sol / s210_characteristic_model: storage/eis_requirement_review.py,
  storage/eis_requirement_preview.py (connection helper), additive api/app.py,
  models/migration новой immutable tenant-scoped таблицы, API/PG tests.
- root: web новый review модуль/компонент, additive preview/actions/BFF,
  web tests, docs/110, ADR/0098, план, README, release evidence.
- Astra / architecture_review: read-only high-risk review; пересечений edits нет.

Acceptance: сохраняются все исходные строки с exact preview/product/document
SHA и provenance; raw text/actor/time выводит сервер. OPERATOR создаёт immutable
предложение, отдельный COMPLETENESS_REVIEWER подтверждает exact proposal SHA,
нормативную роль, связь позиции и конкретную интерпретацию. Self-review и tenant
substitution запрещены. Только формат бумаги из закрытой грамматики A/B0–10
может стать исполняемым сравнением; кириллическая А/В требует explicit review.
Числовые единицы, допуски, сортность, контекст остаются UNKNOWN в этом срезе.
Каждая строка видна; обязательный FAIL блокирует выбранный товар, процентов нет.
Полное ТЗ, КП, экономика и PARTICIPATE остаются UNKNOWN. Source requests/jobs=0.
Реальный production review не подделывается: при отсутствии независимой учётной
записи выпуск механизма проверяется synthetic gates и pending proposal на VPS.

Результат S228: 505 Python/API/real PG PASS (82.51 s, zero skips),
116 Node wire/render PASS, TypeScript/ESLint/production build PASS.
Независимые source/backend/web review findings исправлены, включая canonical
actor IDs, единый RR write snapshot после tenant lease, metadata/S226 FK,
NULL-safe DB checks и exact wire evidence. Вторая учётная запись не создавалась.
Production предложение по 0107300009526000178 v2: пять строк, формат предлагается
к исполнению после review; три прочие характеристики и контекст manual UNKNOWN.
Создание 257 ms, replay 232 ms, read 222 ms; через Next Actions 288/246 ms.
Proposal ID 91ce8fd5-d8d6-46d4-9328-dee24ede9877; OPERATOR review 403,
pending comparison 404; один proposal + audit, решений ноль. Source0, jobs0;
повторные чтения/write0. DB 6017563671 bytes, free 250168291328 bytes,
health200, test DB0, source helpers0; cron прежний, intake продолжается.
Schema 20261006_08; детали и SHA evidence — [S228](../../documents/110-eis-independent-requirement-review.md).

### S229 NEXT

Нормализация количества листов должна сохранять смысл «на требуемую упаковку»,
исходную единицу и независимое подтверждение. Не заменять листы на штуки без
подтверждённого контекста. Два ограничения плотности >=80 и <90 сохранять
раздельно; 80±3 не становится scalar80. Сортность С/Сэ остаётся UNKNOWN до
подтверждённого порядка и производителя. Вслед за техническими требованиями —
полнота документации, полное КП, затраты и три сценария экономики.
