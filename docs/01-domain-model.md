# Доменная модель

## Агрегат ProcurementCase

```text
Tenant / CompanyProfile (versioned)
└── ProcurementCase
    ├── TenderProcedure + SubmissionWindow + source snapshots
    ├── RequirementSet + participant/legal/document requirements
    ├── DeliveryPlan[]
    ├── EligibilityChecks[]
    ├── SupplierCandidates[] → QuoteThreads[] → Quotes[]
    ├── ComplianceResult[]
    ├── ScenarioSet(base, realistic, conservative)
    ├── RiskFinding[]
    ├── TenderRating + Recommendation
    ├── ApplicationPackage
    ├── ActionRequest[] → Approval[] → ExecutionReceipt[]
    └── ContractCase → Milestones[] → ActualEconomics
```

## Реализованные типы ядра

| Модуль | Типы |
|---|---|
| `company.py` | `CompanyIdentity`, `GeographyPolicy`, `FinancialPolicy`, `ProhibitionRule`, `CompanyProfile` |
| `tenders.py` | закон, способ, стадия, deadline, адреса и топология поставки |
| `requirements.py` | атомарное требование и позиция ТЗ |
| `offers.py` | кандидат, атрибут, сертификат |
| `compliance.py` | проверки и общий технический вердикт |
| `economics.py` | полный cost breakdown и три сценария |
| `decisions.py` | hard-gate statuses, risks, score factors, recommendation |
| `quotes.py` | версионированное КП в RUB на полный комплект поставки |
| `cases.py` | immutable `ProcurementCase`, ручная оценка gates и case evaluator |
| `actions.py` | точный payload, approval и audit event |
| `lifecycle.py` | контракт и контрольные этапы |
| `platforms.py` | `DigitalPlatformCase`, `PlatformUse`, проверки канала и `PlatformRuleSnapshot` |

## Инварианты

1. Все данные принадлежат одному `company_id`; cross-tenant join запрещён.
2. Факт из внешнего источника имеет `Provenance` и snapshot/version источника.
3. Критическая неизвестность остаётся `UNKNOWN`.
4. Юридические и коммерческие запреты хранятся раздельно.
5. `FAIL` обязательного правила останавливает кейс до рейтинга.
6. Рекомендация `PARTICIPATE` требует открытой подачи, всех hard-gate `PASS`,
   действующего КП и полного `ScenarioSet`.
7. Деньги — `Decimal`; deadline — timezone-aware datetime.
8. Рейтинг равен сумме объяснённых факторов, но не является compliance score.
9. Approval относится к конкретным action id, payload hash, человеку и сроку.
10. История — события append-only; исправление создаёт новую версию/событие.

## S1 — ручной снимок кейса

`ProcurementCase` — неизменяемый tenant-scoped снимок профиля компании,
процедуры, НМЦК, выбранного КП, сценариев и рейтинга. `Quote` ограничен валютой
`RUB`, относится к одной процедуре и компании и описывает весь комплект
поставки; действующее полное КП требует ставки НДС, подтверждённого покрытия
полного объёма, наличия и условий доставки и оплаты.

`CaseAssessment` хранит результаты шести именованных ручных hard gates:
`LEGAL`, `PARTICIPANT`, `TECHNICAL`, `COMPANY_POLICY`, `LOGISTICS` и `DOCUMENT`.
Оценка содержит timezone-aware время и SHA-256 digest точного входного снимка.
Промежуточная оценка может содержать меньше проверок; пропущенная проверка даёт
`NEEDS_ANALYSIS`. Для известного результата нужен источник; `UNKNOWN` может
объяснять отсутствие источника. Повторяющиеся виды проверок не допускаются.
`evaluate_case` повторно валидирует снимок, проверяет deadline, актуальность КП,
полноту затрат и все три сценария; только после этого считает финансовую
рекомендацию. Продажи «с полки» пока возвращают `NEEDS_ANALYSIS`.

Это локальная модель и чистый evaluator для ручного S1-кейса; CLI сохраняет
снимок каждого расчёта в отдельный JSON. Персистентных
tenant aggregates, БД, API, UI, RFQ-парсера и автоматического юридического
ruleset/парсинга пока нет.

## Не путать

- заказчик процедуры и поставщик товара — разные контрагенты;
- обеспечение заявки, исполнения и гарантийных обязательств — разные сущности;
- страна происхождения, страна поставщика и маршрут логистики — разные факты;
- прогноз цены торгов и минимальная допустимая цена — разные числа;
- юридический запрет и коммерческое нежелание — разные основания отказа.

## Дополнение 2026-09-07: платформы и фактические границы

`DigitalPlatformCase` содержит company_id, platform_id, назначение sourcing/sales,
дату публикации извещения с источником и snapshot правил. Для shelf sales
`shelf_eligibility()` проверяет полный набор условий; этот результат должен войти
в hard gates будущего ProcurementCase. PASS канала не заменяет КП, экономику,
технические требования и approval. Целевые PlatformOffer/PlatformOrder и их
жизненный цикл пока не реализованы.

Дерево ProcurementCase выше — целевая модель. `ProcurementCase` и `Quote`
реализованы как локальные immutable-типы для S1, но persisted tenant aggregates,
ApplicationPackage, ExecutionReceipt и ActualEconomics пока отсутствуют.
У Approval реализована привязка к tenant/tender/action type/id/hash, но
одноразовость обеспечит будущая транзакционная служба исполнения.
