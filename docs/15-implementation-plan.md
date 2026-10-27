# Текущий статус и ближайший срез

Актуально: 2026-10-27.
Стадия: внутренняя бета; полный MVP не принят.
[PRD](product/11-product-requirements.md), [roadmap](product/05-roadmap.md), [AGENTS](../AGENTS.md).

## Установленная бета подбора закупок

Владелец root; [контракт](operations/123-beta-shortlist.md). КП/17расходов,
три сценария, финансовый top5 из20loaded lots, профиль/регион и ссылки44/223.
КП/расходы пользователя; пропуск UNKNOWN.
PARTICIPATE UNKNOWN.

B10 evidence:tmp/beta-readiness-20261023-v32/acceptance.json. Полнота ЕИС/ТЗ/PARTICIPATE не приняты; инструкция —[123](operations/123-beta-shortlist.md).

## Принятые срезы V43–V45

Root; [контракт123](operations/123-beta-shortlist.md), evidence `tmp/tendox-feedback-20261025-v43/`.
Установлено: прибыль/единицу внутри групп
исходных единиц, single-position XML denominator; пропуски UNKNOWN. UI default,
TOTAL доступен отдельно; до20loaded lots с полными КП/расходами. V1ABI исправлен;
V2gate50PASS/PG737/web205. Планe373297e установлен25Oct10:52MSK; live readonlyPASS.
Прибыль UNKNOWN. [V45](eis/search/133-eis-regional-discount.md):
RGK/PRIZ/history/API/UI установлены; дальнейшая реальная приёмка — V48 ниже.
[125](operations/125-spec-remediation.md): owner/ZIP отдельно; доставка отложена пользователем.

## Текущий приоритет — полнота ЕИС

[V46](eis/ingestion/134-eis-ezk-final-companion.md) и
[V47](eis/search/135-eis-single-customer-history.md) приняты: импорт EZK,
основной поиск159пачек и solecustomer/history200; sample0UNKNOWN.
[V48](eis/search/136-eis-real-regional-five.md) принят bounded: EA500,5закупок/3заказчика,
median18.5%/p7530.79%; исходная159 sample0UNKNOWN, PARTICIPATEUNKNOWN.
[V49](eis/ingestion/137-eis-completeness-recovery.md) root: полнота/скорость44+223.
Census V58 ниже; nationalUNKNOWN.
59IDs:58source/UIverified;1transportUNKNOWN, consumedretry0; nationalUNKNOWN.
Root [V50](eis/ingestion/138-eis-drug-positions.md) принят:6карточек/26позиций/22UNKNOWN,
main/globalHTTP+actualUI PASS;2×gate50/PG771/web222. API024906c3/WEB71e83972,
schema26_02; source0/cron0; nationalUNKNOWN.
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
[V55](eis/ingestion/143-eis-223-joint-positions.md) root: исправление двух позиций
по заказчикам; принят:gate56/PG831/WEB228, schema27_02/APIad34/WEBca9d, HTTP/UI PASS.
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

R3–R7 bounded; M5 UNKNOWN.
[Coverage120](eis/ingestion/120-eis-national-coverage.md) содержит census,
variants/holds, неподдержанные members и незакрытые диапазоны.
R7 evidence: `tmp/eis-transient-recovery-20261023-v31/acceptance.json`.
FAILED immutable.

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

Root [V58](eis/ingestion/146-eis-completeness-census.md):44 414155/153527unattempted/67failed;22350899/1260terminal; 6/14/5UNKNOWN PASS.
[V59](eis/ingestion/147-eis-223-joint-families.md):106joint; gate56/native PASS, review/план/установка PENDING.
[История](history/implementation/09-status-snapshot-2026-10-20.md).
