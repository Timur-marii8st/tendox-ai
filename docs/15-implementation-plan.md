# Текущий статус и ближайший срез

Актуально: 2026-10-31.
Стадия: внутренняя бета; полный MVP не принят.
[PRD](product/11-product-requirements.md), [roadmap](product/05-roadmap.md), [AGENTS](../AGENTS.md).

## ГосПлан — текущий срез

Root; [контракт и evidence](eis/ingestion/151-gosplan-discovery-slice.md).
Пагинация установлена, gate56/56 и браузерная проверка обоих законов PASS;
старый HTTP 422, полнота и приём данных в основную базу остаются UNKNOWN.
Split-recovery: child 0 ACTIVE offset 500; следующий штатный cron 14:17 UTC.
Общий admission BLOCKED четырьмя окнами 223; provider hold сохраняется.
Кандидат `89d2b186…` ограниченно поддерживает наборы отмен из до 8 ZIP;
review и isolated PG preflight 57/57 PASS после трёх FAIL release gate.
Полный gate `release-20261031-131541-96f8d9d2c172` работает; затем штатный выпуск.

## Установленная бета подбора закупок

Root; [контракт](operations/123-beta-shortlist.md), КП/расходы пользователя,
три сценария, профиль, регион и ссылки 44/223. Пропуски, полнота ЕИС/ТЗ и
PARTICIPATE UNKNOWN. Evidence: `tmp/beta-readiness-20261023-v32/acceptance.json`.

## Принятые срезы V43–V45

Root; [контракт123](operations/123-beta-shortlist.md), `tmp/tendox-feedback-20261025-v43/`.
Прибыль/единицу и single-position XML установлены; пропуски UNKNOWN, TOTAL отдельно.
Gate50/PG737/web205, live readonly PASS; прибыль UNKNOWN. [V45](eis/search/133-eis-regional-discount.md)
установлен, приёмка V48 ниже. [Доставка125](operations/125-spec-remediation.md) отложена.

## Текущий приоритет — полнота ЕИС

[V46](eis/ingestion/134-eis-ezk-final-companion.md) и
[V47](eis/search/135-eis-single-customer-history.md) приняты: импорт EZK,
основной поиск159пачек и solecustomer/history200; sample0UNKNOWN.
[V48](eis/search/136-eis-real-regional-five.md) принят bounded: EA500,5закупок/3заказчика,
median18.5%/p7530.79%; исходная159 sample0UNKNOWN, PARTICIPATEUNKNOWN.
[V49](eis/ingestion/137-eis-completeness-recovery.md) root: полнота/скорость44+223.
Census V58 ниже; nationalUNKNOWN.
59IDs:58source/UIverified;1transportUNKNOWN, consumedretry0; nationalUNKNOWN.
Root [V50](eis/ingestion/138-eis-drug-positions.md):6карточек/26позиций/22UNKNOWN,
HTTP/UI и2×gate50 PASS; schema26_02; nationalUNKNOWN.
[V51](eis/search/139-eis-freshness-handoff.md) root принят:singlefreshwaiter;
180окон/27версий/5UI.
Root [V52](eis/ingestion/140-eis-223-regular-kesmbo.md) принят: schema26_03,
APIe1ac47db/WEB005281eb; gate52/PG781/web223, native312/mainHTTP/actualUI PASS.
49KES/104версии;1080 PARTIAL;reviewPASS.
Root [V53](eis/ingestion/141-eis-kes-five-live.md) принят:5ZIP/регионов,
native/mainHTTP/actualUI5/reviewPASS.
[V54](eis/ingestion/142-eis-223-regular-zpesmbo.md) root установлен: schema27_01,
API022f/WEB6e2e;54gate/811PG/cached4/UI PASS. Joint2→0, PARTIAL.
Волна1260/1260terminal; новыеZP180:33SYNCED/147NO_DATA/0FAILED; nationalUNKNOWN.
[V55](eis/ingestion/143-eis-223-joint-positions.md):gate56/PG831/WEB228, schema27_02, HTTP/UI PASS.
[V56](eis/ingestion/144-eis-223-joint-backfill.md):135XML/34ZIP сверены;133обычных/2joint,
принят:source0 ещё1joint,5mainHTTP/UI/reviewPASS.
[V57](eis/ingestion/145-eis-zp-corpus-search.md) принят:135mainAPI/287nativeitems/8.23s/reviewPASS.
[V38](eis/search/129-eis-active-sweep.md) expired25Oct03MSK; renewal отложен
из-за freshdebt657unattempted. Evidence tmp/eis-freshness-handoff-20261026-v51/.
[V39](operations/127-eis-223-selector.md),[V41](operations/131-eis-source-errors.md),
[V42](operations/132-eis-timeout-recovery.md) установлены; evidence в контрактах.
[Ротация126](operations/126-backup-rotation.md) PASS.

B11[124](operations/124-beta-invitations.md) установлен24Oct:вход/2профиля/2КП/RLS/logoutPASS,
тестдоступ отозван, приглашений0. Evidence:tmp/beta-invitations-20261023-v33/installed-acceptance.json.

M5 INCOMPLETE; [NO_DATA recovery122](operations/122-eis-no-data-overflow.md).

## Завершённые адресные восстановления ЕИС

R3–R7 bounded; M5 UNKNOWN, FAILED immutable. [Coverage120](eis/ingestion/120-eis-national-coverage.md).
R7 evidence: `tmp/eis-transient-recovery-20261023-v31/acceptance.json`.

## Подтверждённые границы остальных направлений

| Область | Статус и контракт/evidence |
|---|---|
| Домен, хранение, интерфейс | S1, первый серверный S2 и внутренний S3 завершены в ограниченных границах; [история](history/implementation/01-foundation-and-document-review.md) |
| Документы/OCR | Внутренний пилот: extraction, review, выбранные документы и таблицы; [вход](documents/README.md) |
| Независимая проверка S228 | Механизм установлен; реальное production решение PENDING, технический допуск UNKNOWN; [контракт](documents/110-eis-independent-requirement-review.md) |
| ЕИС: охват и восстановление | M5 INCOMPLETE; адресный импорт Татарстана не принят, устойчивое ускорение UNKNOWN; [coverage](eis/ingestion/120-eis-national-coverage.md), [диагностика](operations/121-eis-production-readiness.md) |
| Поиск ЕИС | Обзор/continuation установлены; M2 не принят, precision/recall UNKNOWN без labels; [поиск](eis/search/113-eis-search-continuation.md), [benchmark](eis/search/118-eis-benchmark-instrument-evidence.md) |
| Поставщики | Поиск и выбранная карточка выпущены; manufacturer dossier/review/RFQ draft проверены локально, live source error; [контракт](suppliers/111-manufacturer-search-and-verification.md) |
| Браузерные источники | Транспорт установлен; Bing проверен, Google/Яндекс/Маркет блокируются CAPTCHA; [SERP](suppliers/105-eis-position-supplier-serp.md), [ручная CAPTCHA](suppliers/112-human-supplier-captcha.md) |
| Пилотный UI и профиль | Branding и personal OPERATOR access проверены 17 октября; critical settings OWNER_AUTHORIZATION_UNAVAILABLE; [снимок evidence](history/implementation/09-status-snapshot-2026-10-20.md) |

S229 (количество на упаковку), M4: NOT STARTED после приоритета ЕИС.
Нужны source/provenance, review, обе границы диапазона и UNKNOWN для сортности.
Зависимости S226/S227/S228; реальное независимое решение S228 PENDING.

Для сквозного кейса полнота ТЗ/КП, стоимость партии/3сценария не подтверждены.
PARTICIPATE не принят.
Supplier/logistics, post-award и SaaS незавершены.
Публичная цена не становится КП; mandatory FAIL блокирует допуск.

[V60](eis/ingestion/148-eis-national-census-v60.md): national UNKNOWN.
[V61](eis/ingestion/149-eis-corpus-initial-wait.md): initial busy evidence PENDING.
[V62](eis/ingestion/150-eis-historical-bounded-turn.md): production BLOCKED.
[История](history/implementation/09-status-snapshot-2026-10-20.md).
