# V47 — единственный заказчик в автоматическом подборе истории

Владелец root, 26 октября 2026. Установлен по точному human approval c25ffd76.
Evidence `tmp/eis-single-customer-20261026-v47/`.

После [V46](../ingestion/134-eis-ezk-final-companion.md) закупка
0836600003326000287 импортирована и находится в основном поиске.
Дополнительный forced-read-only probe истории выявил CUSTOMER_IDENTITY_REQUIRED:
XML содержит ровно одного заказчика01363000003, его НМЦК67082.1 совпадает
с общей, все159пачек распределены ему. Признак customerQuantities включал
совместную ветку parser, которая всегда требовала внешнего выбора заказчика.

## Контракт

Если явно выбранного заказчика нет, автоматический выбор возможен только при
единственном полном direct-child пути
EP notificationInfo/customerRequirementsInfo/customerRequirementInfo/customer/
BASE regNum. Все пять уровней должны быть единственными, namespace точным;
дубликаты и одноимённые foreign-namespace ветви не дают единственную identity.
Номер содержит11цифр. Source identity и locator сохраняются.
Новая auto-ветка также отклоняет mixed-namespace siblings в исходном дереве
и проверяет точные bounded пути всех позиций/customer allocations. Чужой
namespace не превращает усечённую parser-проекцию в полный объём.

После определения номера выполняется прежняя полная `_customer_partition`:
все позиции/SID, quantities и allocation, строки, цена каждого заказчика и
общая НМЦК сверяются. Отсутствующие/чужие/дублирующие allocation и конфликт
сумм сохраняют UNKNOWN. Глобальная цена не заменяет цену выбранного заказчика.
При двух и более requirements автоматический выбор запрещён; явный выбор
и существующий контракт совместной закупки не меняются.

Automatic history использует provenance фактически выбранной начальной суммы,
а не выдуманный общий locator. Tenant, exact XML SHA, version/current-card checks,
период/объём/спецификация и минимальные5независимых наблюдений сохраняются.
Собственная закупка исключается из статистики, КП не создаётся.

## Проверяемый результат

Регрессия до исправления: CUSTOMER_IDENTITY_REQUIRED; `red.txt`.
Focused232PASS; offline исходный XML198cb064 даёт Тверскую область,
159пачек/OKEI728, единственную identity и обе суммы67082.1 с provenance;
`real-source-scope-proof.json`. Это не приёмка PostgreSQL/production или прогноза.
Независимый code/executor review PASS. Sealed source37ae24e0; полный gate50/50:
4374PythonPASS+27allowedskip, PG751безskip, web221, doctest9; trusted verifierPASS.
Финальный образ9bfe3e37 без product-source mounts: canonical intake исходного
ZIPb34aa4e5, один реальный контракт/карточки, source0/production writes0.
Native historyHTTP200: Тверская область/159пачек/source buyer locator;
собственный результат исключён TARGET_IS_NOT_HISTORY, sample0UNKNOWN,
скидки null, quoteNO_QUOTE, AUDITOR save403, persisted counts не изменились.
Frozen self-exclusion оценена25Oct12:01:33UTC; это не продление актуальности карточек.

План `c25ffd761a41a69a7697df447273c8e5350c4cdefebd6fa2d9dec97fb3fa7478`:
ровно три API/default-worker/collector pin, recreate толькоAPI; schema26,
web/DB/cron/SQL limits/resource budgets сохранены. Миграций/replay/source calls0,
business writes0; только release audit. PreflightREADY/exact-plan reviewPASS.
Installed acceptance PASS: normal HTTPsearch200/SHA и forced-read-only
internal AUDITOR history/quote handlers200; Тверская область/159пачек,
sample0UNKNOWN/discountsnull, NO_QUOTE/save403. Три configSHA/schema26/health,
реально импортированные wheel moduleSHA, web/DB/cron/host scripts PASS. Это не личная production HTTP-сессия.
На сбое после barrier сохраняются принятые pins; старый exact-owned API
изолируется при смешанной конфигурации. Human approval получен до установки.

При сборе отчёта helper объединил stderr предупреждения Starlette с корректным
PASS JSON: сохранён READ_FAILED_RUNTIME_RETAINED. Под теми же leases и
неизменным payload строгая проверка rawSHA/точного prefix/полного JSON и
installed identities завершила первоначально одобренный READ_VERIFIED. Повторных
promote/migration/replay0; исходный raw сохранён рядом с clean JSON, independent
reconciliation reviewPASS. Последующий identity probe исправил неверное
предположение о /app/src: runtime импортирует non-editable wheel из /opt/venv,
все3 реальных moduleSHA совпадают с manifest. Это изменение проверки, не кода.
Независимый installed review PASS_INSTALLED_BOUNDED_V47; итог — acceptance.json.

После установки следующий результат — ≥5независимых сопоставимых source
наблюдений. Текущий inventory этого не подтверждает; регулярного сбора нет.
Изменение source schedule/бюджета/приоритета требует отдельного ограниченного
контракта и exact payload, прежний V45 one-shot не повторяется.
