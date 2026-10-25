# Покрытие нового ТЗ партнёра

Ревизия 2026-10-23 по текущему ограниченному beta-срезу. В таблице различены
`LIVE SCOPED` (работает в ограниченном beta/production scope), `LOCALLY TESTED`
(механизм проверен изолированно) и `MISSING SCOPE` (нужна отдельная реализация,
интеграция или production evidence). Нумерация сохранена по исходнику; пункт 24
не предоставлен. Наблюдение на 23Oct: профиль 0 KNOWN/27 UNKNOWN и 0 реальных
КП; это датированный beta-факт, а не постоянный статус. Автоматический расчёт
доставки отложен пользователем 23Oct; ручные расходы сохраняются. B11 invitations
имеет отдельный статус `NOT_INSTALLED` и в эту таблицу не добавляет production
PASS. Детальный live-статус и evidence проверок находятся в
[плане реализации](../15-implementation-plan.md).

| Пункт | Требование / имеющийся код | Недостающая работа и критерий приёмки | Этап |
|---|---|---|---|
| 1 | `LIVE SCOPED`/`LOCALLY TESTED`: CompanyProfile, independent immutable versions, reload/edit diff и exact profile selection реализованы в API/UI; beta profile flow проверен | Полные evidence полей, лицензии/допуски, production owner authorization и последующее exact comparison остаются scope [контракта](../architecture/07-company-profile-contract.md); 23Oct наблюдались 27 UNKNOWN | MVP |
| 1.2 | `LOCALLY TESTED`: typed LEGAL/COMMERCIAL checks и UNKNOWN без контекста | Versioned predicate registry с источниками/effective dates и полная policy coverage | MVP |
| 2 | `LIVE SCOPED`: scheduled EIS ingestion, immutable tenant-scoped index/API и beta discovery по сохранённым версиям | Национальная полнота, устойчивая свежесть, production coverage/full-text и качество корпуса остаются UNKNOWN; checkpoints/dedup не означают полный охват | MVP/v1 |
| 3 | `LOCALLY TESTED`: core `decisions.py`/case evaluation snapshots, evidence и factors; financial shortlist использует отдельный financial order | Автоматический сбор всех входов и полный production workflow; financial shortlist eligibility остаётся `UNKNOWN` и не является core evaluator PASS | MVP/v1 |
| 4 | `LIVE SCOPED`: manual full quotes, 17 expenses и три сценария; Decimal/gates проверены | Реальные КП/расходы отсутствуют в наблюдении 23Oct; налоговая policy, cash-flow/forecast-fact и отложенный auto-delivery calculation остаются scope | MVP |
| 5 | `LOCALLY TESTED`/`LIVE SCOPED`: manufacturer search API и bounded S223–S226 (`suppliers111`) дают supplier candidates, pages, products и terms | Полное покрытие источников/стран, contract-backed access, cost comparison и резервный supplier остаются scope; supplier identity/linkage может быть UNKNOWN | MVP/v1 |
| 6 | `LOCALLY TESTED`: `quotes.py`/`cases.py`, tenant-scoped full quote и RFQ draft связаны exact evidence | RFQ dispatch после approval, Quote Analyzer и multi-quote comparison не выпущены; 0 реальных КП — датированное beta-наблюдение | MVP |
| 7 | `LOCALLY TESTED`/`LIVE SCOPED`: безопасные PDF/DOCX/XLSX/ZIP, native extraction, bounded OCR/visual review, human gate, derived persistence и immutable discovery index/API | Human-confirmed production calibration, approved vision provider/retention policy, executor exact-payload approval, расширение типов фактов и пользовательское резюме | MVP |
| 8 | `MISSING SCOPE`: обучение/предпочтения не заявлены | Tenant-scoped причины и сигналы, не меняющие hard policy | v2 |
| 9 | `LOCALLY TESTED`: versioned `ApplicationPackage` и application review существуют; execution status явно `ADMITTED_NO_DISPATCH` | Реальная подача/dispatch, внешний канал и подтверждённое исполнение не реализованы | v1 |
| 10 | `LIVE SCOPED`: `DeliveryPlan` и регион поставки участвуют в beta shortlist | Полные плечи, количество/даты, плательщик/услуги и доставка; неизвестная цена не ноль, auto-delivery calculation отложен | MVP |
| 11 | `LOCALLY TESTED`: `ProcedureMethod` и typed applicability checks | Полные правила заказчика и production applicability evidence; закрытые методы не получают допуск автоматически | MVP/v1 |
| 12 | `LIVE SCOPED`/`LOCALLY TESTED`: unit normalization, tenant hybrid search и immutable exact model→brand catalog с official PDF bytes/SHA-256 | Reviewer UI/IAM, legacy re-review, разрешённый official fetch, морфология/КТРУ/ОКПД2, аналоги и ranking coverage | MVP |
| 13 | `LIVE SCOPED`: `SubmissionWindow`, timezone-aware deadline и server-side evaluation | Полная ingestion/freshness visibility/timer; закрытая, истёкшая или только опубликованная процедура не зелёная | MVP |
| 14 | `LOCALLY TESTED`: typed mandatory checks и fail-closed compliance | Versioned Legal Rules Registry, №1875 и исключения с official sources/effective dates; category code сам не выдаёт FAIL/PASS | MVP |
| 16 | `LOCALLY TESTED`: `RiskFinding` и evidence-backed risk reasons | Полный evidence catalog и actions; отсутствие данных остаётся UNKNOWN | MVP/v1 |
| 17 | `LOCALLY TESTED`: `lifecycle.py` и typed lifecycle stages | Production DB/scheduler/notifications, 7-day warning и overdue-payment flow | v1 |
| 18 | `LIVE SCOPED`/`LOCALLY TESTED`: `ScenarioSet`, completeness checks, explicit zeros и три сценария | Нужны налоговая policy, cash-flow, forecast/fact и auto-delivery calculation; ручные расходы сохраняются | MVP/v1 |
| 19 | `LOCALLY TESTED`: `TenderRating`, versioned weights/sources и Recommendation gate | Production calibration/inputs; высокий балл не отменяет FAIL или UNKNOWN | MVP |
| 20 | `LOCALLY TESTED`: `eis_analogs.py` извлекает bounded historical analogs/protocol evidence | Coverage, sample completeness, freshness и competition prediction остаются `UNKNOWN`; нет калиброванной вероятности | v1/v2 |
| 21 | `LIVE SCOPED`: внутренний S3 показывает список/карточки, gates, provenance, экономику и evaluation | Полная воронка, согласования, контракты, дебиторка и production sessions; зелёные совпадения считаются после КП | MVP/v1 |
| 22 | `MISSING SCOPE`: автономный SearchPlan/orchestrator workflow не выпущен | Jobs, лимиты и policy-bounded orchestration; анализ не расширяет автономию | MVP/v1 |
| 23 | `LOCALLY TESTED`: tenant-scoped aggregates, audit events и PostgreSQL RLS | Production RBAC/IAM, read models и one-action all-time report с временем обновления | MVP/v1 |
| 25 | `LIVE SCOPED`/`LOCALLY TESTED`: immutable `ProcurementCase`, persistence/API, ручной импорт, UI, document pipeline, supplier search и ApplicationPackage | Нужны полный monitoring scope, state transitions, RFQ dispatch, application execution и путь до оплаты/прогноз-факт | MVP/v1 |
| 26 | `LOCALLY TESTED`: `actions.py`, exact transactional approval, price floor, receipts и role checks | Production execution remains approval-bound; повтор/изменение operation запрещены | MVP/v1 |
| 27 | `LOCALLY TESTED`/`LIVE SCOPED`: checks/reasons/factors, digest, audit, UI, document/OCR provenance, fail-closed gate, evidence manifest и exact review одного native-ТЗ | Связь terminal review с case/ruleset versions, production reviewer sessions, OCR calibration и полный пользовательский review остаются scope | MVP |
| Дополнение 04.09 | Платформы — частично, platforms.py | Sourcing и shelf sales; карточка/оферта/заказ, реестры и логистика оператора; неизвестный допуск не PASS | Этап 0/MVP, коннекторы по готовности |

## Зависимости конкретных интеграций

1. Список площадок, регистраций компании и разрешённых каналов доступа.
2. Документация/API/договорённости ЕИС, ЭТП, почты, банков, маркетплейсов и перевозчиков.
3. Официальные актуальные нормы, перечни операторов и процедура legal review.
4. Обезличенный набор ТЗ/КП/контрактов для проверки извлечения и расчётов.
5. Налоговая модель компании и финансовые ограничения.

Эти зависимости не мешают разработке моделей, БД, UI и тестов на синтетических
данных; они блокируют утверждение, что конкретная внешняя интеграция работает.
Исторические исходные пробелы — в [аудите](../history/legacy/13-partner-spec-audit.md), актуальные
приоритеты — в [плане реализации](../15-implementation-plan.md).
