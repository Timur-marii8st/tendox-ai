# Текущий статус и ближайший срез

Актуально: 2026-10-25.
Стадия: внутренняя бета; полный сквозной MVP не принят.
Требования — [PRD](product/11-product-requirements.md), релизы —
[roadmap](product/05-roadmap.md), порядок разработки — [AGENTS](../AGENTS.md).

## Установленная бета подбора закупок

Владелец root; [контракт](operations/123-beta-shortlist.md). КП/17расходов,
три сценария, финансовый top5 из20loaded lots, профиль/регион и ссылки44/223.
КП/расходы вводит пользователь; пропуск UNKNOWN, явный0 — декларация.
Public prices предварительные; PARTICIPATE UNKNOWN.

23Oct B10: закрытая бета на API/worker ab3b9686, WEB949064db/schema20261021_01.
Root; evidence:tmp/beta-readiness-20261023-v32/acceptance.json. Isolated beta smoke/production readonly PASS.
Поиск1709совпадений, регион13/55.505s близко к timeout60s; live browser blocked.
Профильv1:0KNOWN/27UNKNOWN; реальных КП0/прибыльUNKNOWN. Полнота ЕИС/ТЗ,
PARTICIPATE не приняты; top5 финансовый из20loaded lots. Инструкция —[123](operations/123-beta-shortlist.md).

## Исправления после сверки с ТЗ — локальный кандидат

Root; Luna — docs, Terra — owner workflow, Sol6.1 — source/margin/cache/review.
Исходники сверены с установленным R4; исправлены точный порог маржи,
owner confirmation и повторное чтение ZIP. [Отчёт125](operations/125-spec-remediation.md),
evidence `tmp/spec-remediation-20261023/`. Python3867PASS/27SKIP, PG31PASS.
Frontend201PASS/buildPASS; batchSQL проверен, latency53.826s ещё UNKNOWN. NOT_INSTALLED.
Далее — source-bound navigation projection: поиск читает1.7GB ZIP, контракт в125.
Локальному кандидату нужна интеграция с B11 и новый gate. Реальные данные не созданы.
Авторасчёт доставки отложен пользователем; ручные расходы и UNKNOWN сохранены.

## Текущий приоритет — полезность поиска ЕИС

Root; [V38](eis/search/129-eis-active-sweep.md) eb4581ba установлен24Oct07:50UTC:
active44 безquery, date partitions, до8attempts/проход в прежнем бюджете.
Sweep:13восстановлений; expiry25Oct03MSK, National UNKNOWN; evidence в129.
[V39](operations/127-eis-223-selector.md): SQLfix24Oct17:21MSK;13новых HTTPPASS19:48.
[V41](operations/131-eis-source-errors.md): b0a04204 установлен21:41MSK;gate50/50, DB/audit codesPASS.
[V42](operations/132-eis-timeout-recovery.md):25Oct08:11 WSDL200; +6/+6, HTTP6/6PASS.
Ротация[126](operations/126-backup-rotation.md) livePASS:2verified+original, free~192GiB.

B11 установлен24Oct, план3627e90e: [124](operations/124-beta-invitations.md).
API7e2b5207/WEBf4e6e60d/schema20261023_01; workerab3 сохранён.
Evidence:tmp/beta-invitations-20261023-v33/installed-acceptance.json.
Live вход/2профиля/2КП/RLS/отказ чужой компании/logout PASS; тестовый доступ отозван.
Реальных приглашений0; для выдачи нужны участники и company mapping.

NO_DATA recovery21Oct: bounded PASS51окон(12SYNCED/39NO_DATA),118редакций;
полное evidence — [122](operations/122-eis-no-data-overflow.md). Старые планы не применять.
Национальная свежесть M5 INCOMPLETE. Образы/тома не удалять; дампы — только по126.

## Завершённые адресные восстановления ЕИС

Root; R7:2SYNCED/157NO_DATA,260новых редакций,318audits/SHA PASS;
`tmp/eis-transient-recovery-20261023-v31/acceptance.json`. Census44:
297001planned/28447canonical,268554pending,63semantic failures. M5 UNKNOWN.
R5/R6:27range-отказов закрыты,2253new;543ranges UNKNOWN;9из10вложений SHA verified,
1XLSX >20MiB, роли UNKNOWN, receipts0. Evidence:
`tmp/eis-range-recovery-20261023-v30/acceptance.json`, [120](eis/ingestion/120-eis-national-coverage.md).
После R7 остаются8MEMBER_UNSUPPORTED,5DUPLICATE_ARCHIVE, source/version conflicts.
R4/R3 установлены22Oct; старые payloadb359e8d9/8764ff9d и R7 не повторять.
Images/config/schema/cron/SQL5s/disk40GiB/worker3GiB/locks сохранены;
recovery не является scheduler release. Исторические FAILED immutable.

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

S229 (единицы количества на требуемую упаковку) NOT STARTED, относится к M4.
Это будущий продуктовый срез после текущего приоритета ЕИС, а не активная задача.
Acceptance: исходная единица и provenance, независимый review, сохранение обеих
границ диапазона и UNKNOWN при неподтверждённой сортности. Зависимости — S226,
S227 и механизм S228; реальное независимое решение S228 остаётся незакрытым.

Полнота всего ТЗ, полное действующее КП, стоимость партии и три сценария
не подтверждены для выбранного сквозного кейса. PARTICIPATE не принят.
Полные supplier/logistics, external execution/post-award и SaaS незавершены.
Публичная цена не становится КП; mandatory FAIL блокирует допуск.

## Как продолжать

Читать тематический README и контракт; историю искать по вопросу.
Прежние SHA — [снимок20Oct](history/implementation/09-status-snapshot-2026-10-20.md).
Проверять tmp/hashes; исторический receipt не допускает новый код.

Обновлять границы/evidence/следующий шаг; журналы — в history.
[Git25Oct](history/implementation/10-git-checkpoint-2026-10-25.md).
