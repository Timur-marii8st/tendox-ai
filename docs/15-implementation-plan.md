# Текущий статус и ближайший срез

Обновлено: 2026-10-19. Root: NO_DATA overflowv2 READY_PENDING_EXACT_APPROVAL; source68c64fd0/image935dae45, full50PASS(unit3665+27allowed skips/PG688zero skips/Node178), actual-copy57976/hash/replay/foreign PASS. Owned runtime/report/два test modules; [evidence и payload](operations/122-eis-no-data-overflow.md). Payloadaca2b9b8/preflightPASS; NOT INSTALLED. Следующее: exact approval→install→ordinary-cron raw/journal proof; API NOT READY. SQLfix/worker pacing installed17Oct. Единственный live-план; [история](history/implementation/README.md). Требования — в [PRD](product/11-product-requirements.md), порядок разработки — в
[AGENTS.md](../AGENTS.md). Читать историю целиком перед задачей не требуется. Tendox INSTALLED/VERIFIED: approved web-only `8bf356fd…`, source `6a184459…`, web `cec6383b…`;4production-origin routes200,50/50gate/render/rollback PASS. Evidence: `tmp/tendox-branding-20261016-v1/handoff.json`; backend/DB/worker unchanged.
Профиль: installed UI/API and personal OPERATOR access for elkgo verified17Oct; critical settings remain OWNER_AUTHORIZATION_UNAVAILABLE. Installed contract is documented in accepted source `tmp/eis-223-probe-fix-20261017-v1/candidate/docs/architecture/09-company-profile-api.md`; no profile behavior changes in EIS speed slice.
ЕИС/Татарстан — root, handoff v177; INCOMPLETE. M0v7: full50PASS (3712unit/689PG/181web), три реальных формата отображаются корректно; прежний actual63PG PASS (274редакции/254закупки/replay/search/RLS). На18Oct04:24UTC:52отсутствующих редакции/36закупок, проект56адресныхTatкомплектов+23метадокумента; региональное окно исключено. Дополнительно29новых закупок/36редакций прошли парсер, все29 подтверждены какTat и отсутствуют в production на05:16UTC; изолированный импорт ещё не проверен. Source53 продолжен после завершения сборки: две ресурсные ошибки были до обращения кЕИС. Остаток30 без повтора23успехов. HTMLdirect остановлен; используется штатная пауза60s. Следующее: закончить новый набор, проверить импорт и точную операцию с миграциями01→03. Production не менялся; exact-approval не запрошено. Evidence: tmp/improvement-program/handoff-current.json.
EIS speed INSTALLED_VERIFIED17Oct19:29UTC: approved548773f3/sourcee57cf271/worker96a570c1,gap1.25s;SQLfix/API721727d4 сохраняются. Один обычный44проход60окон/113.187s против155.254s,0fail; устойчивое ускорение UNKNOWN. Evidence tmp/eis-ingest-speed-20261017-v1/completion-summary-v1.json. Tendox/профиль/БД не изменены; hourlymonitorDISABLED.
## Подтверждённые границы

| Область | Состояние и источник |
|---|---|
| Домен, хранение, первый экран | S1, первый серверный S2 и внутренний S3 завершены в ограниченных границах; [история](history/implementation/01-foundation-and-document-review.md) |
| Документы и ЕИС | Внутренний пилот: native extraction/OCR/review, индекс и очереди ЕИС, выбранные документы и поиск; [документы](documents/README.md), [ЕИС](eis/README.md) |
| Поиск снабжения | S223–S226 выпущены: поисковики → сайт → выбранная карточка → сохранённые условия/характеристики; [поставщики](suppliers/README.md) |
| Выбранная таблица ТЗ | S227 выпущен: точные сохранённые ячейки рядом с товаром; [контракт](documents/109-eis-requirement-table-preview.md) |
| Независимая проверка | S228 COMPLETE для механизма и проверки формата; установлен 2026-10-06; [контракт и evidence](documents/110-eis-independent-requirement-review.md) |
| Реальное решение S228 | PENDING: production proposal создан, независимых решений ноль; полный технический допуск UNKNOWN |

Полный охват ЕИС, полнота всего ТЗ, действительное полное КП, стоимость партии
и PARTICIPATE в текущем выбранном сценарии не подтверждены. Публичная цена
не становится КП. Выпуск механизма не означает завершение product acceptance.
Полные этапы поставщиков/логистики, внешнего исполнения/post-award и SaaS
остаются незавершёнными; отдельные механизмы уже есть. Целевые релизы — в
[roadmap](product/05-roadmap.md), а не в перечне исторических NEXT.

## Последние проверки продукта

В [отчёте S228](documents/110-eis-independent-requirement-review.md) зафиксированы:
505 Python/API/real PostgreSQL PASS без skips, 116 Node wire/render PASS,
TypeScript/ESLint/production build PASS, installed API/Next Actions/SSR proof.
Это результаты выпуска S228, не новые проверки текущего рабочего дерева.
Browser visual NOT_PERFORMED; production independent review PENDING.

## S229 — будущий срез требований внутри M4, NOT STARTED

Цель: подтверждённые единицы количества листов на требуемую упаковку.
Зависимости: exact S226 product, S227 preview и механизм S228.
Реальное независимое решение S228 остаётся отдельным незакрытым acceptance.

До реализации назначить одного владельца, owned files и ограниченную проверку.
Этот план не назначает разработчиков и не разрешает менять общие файлы параллельно.

Критерии контракта:

- Количество сохраняет смысл «на требуемую упаковку», исходную единицу и provenance.
- Листы не заменяются на штуки без подтверждённого контекста и независимого review.
- Плотность >=80 и <90 сохраняет обе границы; 80±3 не становится scalar 80.
- Сортность С/Сэ UNKNOWN до подтверждённого порядка и производителя.
- UNKNOWN не становится допуском; mandatory FAIL блокирует кандидата, процентов нет.

Дальше последовательно: полнота требований → единица цены/упаковка/MOQ/НДС/
доставка → стоимость партии → draft RFQ → полное действующее КП →
base/realistic/conservative. Внешняя отправка требует exact-payload approval.

## Поиск и проверка производителя — `IN PROGRESS` локально

План и границы: [111-manufacturer-search-and-verification](suppliers/111-manufacturer-search-and-verification.md).
Первый срез сохраняет raw response официального EAEU PRODUCTS и создаёт
server-derived candidate dossier; он CHECKED LOCALLY, но live query
`SOURCE_ERROR`, поэтому live-success и production acceptance не заявляются.
Identity/role review с immutable PDF, exact registry linkage и separation of
duties проверен локально по [ADR-0100](adr/0100-independent-manufacturer-review.md).
Сводка изготовителей одного run с exact-key grouping проверена локально по
[ADR-0101](adr/0101-run-scoped-manufacturer-grouping.md). RFQ draft проверен локально;
отправки нет. GISP/B2B access contract pending; supplier SKU linkage,
contacts/commercial review и действительное полное КП остаются незавершёнными.
Владельцы: root — API/интеграция, Sol — backend/web, Astra — review.

## Отмена дополнительных поисковиков

По запросу пользователя Brave/DDG/Mojeek удалены из активного поиска;
policy v1 снова запускает Bing/Яндекс/Google. Исторический v2 читается source0.
Владелец root: storage/integration/docs; Sol: source и web. Owned files:
supplier_serp source/storage, SERP UI/wire и тематические тесты.
Acceptance: нет новых обращений к удалённым engines; старый evidence сохранён;
три активных источника, исходные лимиты, проверка backend/UI/real PG.
Проверено: 90 Python с real PG + 20 Node PASS, TS/ESLint/Ruff/docs PASS.
История — [отозванный ADR0103](adr/0103-supplier-serp-fallback-engines.md).

## Программа улучшения — M1 COMPLETE; национальный охват IN PROGRESS

Приоритет09.10: первый результат — актуальные44/223 по всей России с измеренной свежестью; fresh flow обрабатывается быстрее поступления, история отдельно на остаточной мощности. После выкладки измерить новые окна/сутки по официальным регионам/families, terminal throughput, source→search lag и необслуживаемые координаты; планы/общий ETA истории не доказывают охват. M1 и принятые production6/restore сохраняются.
Контракт и рабочие цели — [программа](product/16-improvement-program.md).
Root; exact v4 c4f6…/activation092d…/applicationbee8… APPROVED и INSTALLED777.067s; minimal223 c641…/receipt11dd… переиспользованы, схема20261008_01, worker3GiB/3CPU. Окна77/05–06.10:481новая версия,423ранее отсутствовавшие закупки, три production HTTP query нашли заданные версии; integrity PASS. Штатный223 также закрыл77/08.10 (+57версий). Ошибки postcheck OOM137 и leasewait180s сохранены; вместо третьей выгрузки использованы committed audit и bounded read-only/API proof. Национальная свежесть INCOMPLETE: за08.10 evidence448/450 координат44 и450/450 координат223 в scope90регионов×5поддержанныхfamilies;44остались48/EZK duplicate и77/EOK attachment. Existing national fresh pilot:43окна/241.358s,37версий,2события,0ошибок; terminal RUN_TIME_BUDGET_REACHED, постоянный cron не изменён. Измерены lag и поисковая проекция; sustained arrival/repoll capacity UNKNOWN. Следующий срез — latest-hour-first и ограниченная reconciliation через существующий scheduler с измерением совместной ёмкости; история на остаточной мощности. Pagination/paper не установлены; wholecoverage/quality UNKNOWN. [Release/evidence](operations/115-candidate-quality-workflow.md), [scope](eis/ingestion/120-eis-national-coverage.md), [search](eis/search/113-eis-search-continuation.md).
Baseline v2 sealed Linux: 3233 PASS/27 explicit skips; real PG 608/608 PASS, 60 modules/15 groups; Ruff/mypy/9 doctests, 153 Node, API/web clean build/startup PASS. Provider v5 and independent audit PASS: Python 3892/27 known skips, Node153, clean builds/startup/cleanup.
Gate по [ADR-0107](adr/0107-candidate-triggered-quality-gate.md): provider/два guards INSTALLED; four refusals/identity audit PASS. Два fresh full installed runs и независимые audits PASS; root принял ограниченный local-provider M1.
M1 принят для bounded local-provider. M2 INCOMPLETE: PG5 terminal FAIL `CONTAINER_ENV_UNEXPECTED` с принятым failed-evidence/cleanup review; PG6 и PG7 bounded synthetic diagnostics приняты в описанных пределах, не как full release gate или production-fit результат.
Production6 повторно не выгружался. В isolated PG16.15 восстановлены25relations/800444rows; schema/25FK/counts/ordered hashes до и после поиска PASS;209 deployed Python files exact before/copy/after,95 loaded modules verified; RLS/read-only/foreign tenant0/write refusal PASS. Fixed9cases×3:327calls=324success+3wall timeout;12complete/12page-budget/3error traversals. Restore COMPLETE, bounded SQL_STORAGE observation executed; all-success/full-walk INCOMPLETE. Total6287.272s; worker peak1.340GiB, PG peak1GiB+8192B/max-events304947/OOM0; cleanup PASS, stopped PGdata retained. Root owns corpus worker/evidence/live; one preflight0600 failure diagnosed/fixed, no third cycle. Precision/recall UNKNOWN без labels; fullM2/release NOT ACCEPTED, M3/M4 не начаты; M5 теперь приоритет. q05 SQL/fetch/comparison localization сохранена как проблема поиска; текущий приоритет — ingestion; [evidence](eis/search/118-eis-benchmark-instrument-evidence.md).

## Серверная браузерная методология — транспорт INSTALLED

Root: source/storage/runner, compose, deployment и docs; Sol: новый browser helper
и его тесты; Astra: независимый review. Зависимость: серверный controlled probe.
Acceptance: отдельные tenant/origin профили, lock, durable pacing/cooldown,
bounded cleanup, source0 и сохранение UNKNOWN; проверка на VPS после restart.
Bing: 10 ссылок после смены контейнера; полный runner→PostgreSQL→source0 PASS.
105 Python/real PG PASS; API health и отсутствие zombie/живых браузеров PASS.
Google, Яндекс и Маркет: CAPTCHA; доступ ко всем источникам не подтверждён.
Полнота/качество выбора производителя остаются UNKNOWN; [evidence](suppliers/105-eis-position-supplier-serp.md).

## Обзор и продолжение поиска ЕИС — INSTALLED

Root; owned: saved-index storage/API, discovery UI/tests/docs. Зависимости: existing query contracts.
Acceptance: схема, до 10 строк, все совпадения через continuation; tenant/evidence guards, FAIL/UNKNOWN.
100 Python, 24 real PG, 7 Node, build/types/lint и saved-production read PASS; [evidence](eis/search/113-eis-search-continuation.md).
Census 1485 recent 44 windows без known gaps; полнота UNKNOWN, 223 PARTIAL. Installed 07.10: HTTPS/browser/continuation PASS.

## Как обновлять

Ручная CAPTCHA — INSTALLED; root API/storage/UI/deploy/docs, Sol browser/парсеры, Astra review; [owned files/evidence](suppliers/112-human-supplier-captcha.md). Frame/input/verify/retry PASS; retry source_error, human CAPTCHA pending.

Доступ к пилоту (2026-10-06): по запросу пользователя домен заменён на
`www.syurai.su`, HTTPS/Basic Auth работают; 401 без пароля, 200 с паролем,
302 с корня на поиск, Forgejo 200. Прежний `.ru` снят;
границы и evidence — [эксплуатация](operations/28-eis-server-operations.md#syurairu--конфигурация-активирована-2026-10-06-dnstls-pending).

После среза обновить только текущие границы, ограничения и следующий шаг здесь.
Контракт/evidence хранить в тематическом документе, ADR — в [реестре решений](adr/README.md).
Прошедший подробный журнал перенести в history и добавить ссылку в индекс.
Не дописывать сюда журналы тестов, SHA-таблицы и историю развёртываний.
