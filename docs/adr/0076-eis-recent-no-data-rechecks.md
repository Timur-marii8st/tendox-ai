# ADR0076 — резерв для повторной проверки недавних NO_DATA

Effective date: 2026-10-05. Owner root. Status: accepted, deployed / bounded verification.

## Основание

Tenant RR/read-only census08:40:31UTC:1807 последних NO_DATA за семь завершённых
MSK дат;1148 ответов старше24h, а selector60 не выбрал ни одного из них.
Oldest due attempt2026-09-29T16:33:36UTC. Непроверенные исторические окна имеют
NULL-first порядок и могут оттеснять повторную проверку пустых ответов.
Источник факта — private `s195-baseline-census.json`, SHA256
`6bf1ac0dc9934b25090ced9b553f298c7f5ebf937c3f5d52c56d488faf5f3a6b`.
Это внутренняя scheduling policy, не изменение юридических правил или допусков.

## Решение

В существующем recent repair reserve R=min(ceil(L/5),12,L-1) выделить для
empty recheck E=min(ceil(L/20),3,max(0,R-1)). Сначала выбрать не болееE старейших
due NO_DATA, затем FAILED на оставшиеся R-actualE slots. При отсутствии пустых
ответов прежняя квота FAILED сохраняется. Для L<=5 нет нового reserve; limit1
и обычное small-budget поведение сохраняются. При L60/both lanes sufficient:
3NO_DATA+9FAILED внутри прежних12repair slots. Historical transient<=3 и daily
new quota36/old anchor/within-lane order/unique limit60 сохраняются.

Только latest attempt (timestamp DESC,UUID DESC) до eligibility filters, тот же
tenant, exact planned date key, valid64hex sourceSHA, last7 completed MSK dates,
age>=24h, отсутствие любого LEGACY_CANONICAL receipt. VARIANT_TRANSPORT не даёт
canonical completeness. Future timestamps и незавершённые даты исключены.
Date cast защищён pg_input_is_valid; malformed dates не роняют recent query.

Квота — **reserve на один selector/worker segment**, не запрет обычного fill.
После исчерпания остальных очередей general backlog по-прежнему может включать
due NO_DATA. S194 parent может состоять из нескольких segments; его общий60-window
budget остаётся строгим, каждый повтор расходует его. Нельзя обещать максимум3
повтора на весь parent или3HTTP requests; window attempt не равен HTTP request.

Повторный NO_DATA записывается существующим append-only journal с sourceSHA и
начинает новый24h cooldown. Он остаётся UNKNOWN; несколько одинаковых пустых
ответов не превращаются в canonical receipt. Новый SYNCED считается intake только
при фактическом canonical receipt и проверенной проекции в search keys.
Не добавляется source pass, cron, concurrency, миграция, permission или resource budget.

## Проверка

PG tenant/latest/tie/proof/24h boundary/MSK dates/canonical vs transport/read-only
gates, квоты с обоими lanes и fallback без new dates; исходные fairness tests.
Один old/candidate shadow snapshot должен показать due rechecks без нарушения
old anchor и new share. Pinned one-module rollout и actual ordinary cron journal
transitions с прежними attempt IDs/sourceSHA и новыми receipt IDs/sourceSHA.
Источник, registry/fullEIS/hourlyfreshness остаются UNKNOWN. Tests/live evidence
не заменяют независимую проверку отсутствия закупок в source.

## Evidence

53unit/PG tests PASS08:54:16UTC/Ruff/mypy; production schemaunchanged/testDBremoved.
SingleRRshadow old0/candidate3due rechecks/60selected unchanged; source0/DBwrites0.
Pinnedone-module rollout08:56:53UTC/host28/API2/worker2hashPASS.
Ordinarycron cumulative09:04:16UTC:6oldNO_DATA rechecked across two segments,
6newattemptIDs/SHA/cooldownresets,0canonical/versions/index/events. Parent active
at observation; no terminalpass/SLA claim. Source emptiness staysUNKNOWN.
Detailed receipts — [S195](../eis/ingestion/78-eis-recent-no-data-rechecks.md).
