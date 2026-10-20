# S179: общий hold evidence-only вариантов44

Статус: завершён, deployed 04.10.2026 09:32 UTC.
Контракт — [ADR0062](../../adr/0062-eis-44-consumer-variant-hold.md).

## Поведение

Любой tenant-scoped ledger variant/origin с номером выбранной карточки и
version>=выбранной версии означает `NOTICE_VARIANT_REVIEW_REQUIRED`. Даже
одиночный XML остаётся evidence-only/UNKNOWN и не разрешает канонический допуск.
Старый ledger не заменяет отдельные stale/deadline gates. Неполный receipt,
для которого нельзя установить affected numbers, удерживает весь tenant
до проверки целостности. Это не supplier mandatory FAIL.

Search исключает held current rows перед ранжированием и eligible/matched
counts, отдельно показывает held_current_notices. Held count вычисляется из
UNION ledger metadata keys с current canonical join и count DISTINCT;
CASE глобальной receipt integrity ошибки удерживает все current rows.
Exact current consumers
отказываются с явной причиной до возврата кешированного анализа/проекции/
сравнения/экономики. API возвращает422 с явной причиной и no-store, включая
mixed/source-estimate/live-number. HTTPException headers заданы отдельно:
FastAPI не переносит headers обычного Response в exception response.
Проверка не читает raw XML и полные ledger/audit JSON; SQL использует metadata.

Документ worker пропускает held jobs до HTTP и cached reanalysis, сохраняет
идемпотентный decision audit; readonly probe не пишет audit. Late hold после
download также проверяется перед receipt/replay/blob/analysis writes. Ledger
writer и final document receipt используют общий tenant advisory lock, затем
writer берёт свой отдельный ledger lock. Порядок предотвращает race commit.
Projection повторно проверяет hold после parsing перед сохранением.

## Граница

Intake hook/канонический индекс/schema20261004_02/история не переключаются.
Статус NO_HOLD означает только отсутствие причины этого guard; не PASS,
не полноту ЕИС или пригодность к участию. Old jobs/receipts не обходят новый
guard. SOURCE unknown не превращается в юридический допуск.

By-number sync проверяет возвращаемую latest reference после прежнего intake;
его source contract не меняется. Pure cached DTO сохраняет blocker в comparison
и не даёт estimate scenarios. Общий44comparison читает refs в одном tenant snapshot.

## Gates

PASS:172Linux/52isolatedPG (224tests), scoped Ruff10runtime/10test, mypy9storage/
source, независимый review. Negative gates:11 cached consumer операций,
same/newer/older cutoff, singleton/cross-tenant, receipt-only integrity anomaly,
search counts/exclusion, cached projection/receipt/reanalysis, late hold до final
receipt. Worker status-read/failure-record races покрыты unit gates. Семь HTTP
document/comparison/economics classes и live-number hold возвращают422/no-store.
БД `procurement_eis_test_20261004_s179` удалена после gates, HEAD20261004_02 прежний.

## Deployment и evidence

Final backup `/home/syurai/vibe-seller-state/backups/s179-before-20261004T093217Z-code.tar.gz`,
SHA256 `64c98885bf5f5a5a34a34b45d61000a13d2377fb1dc8be6b827e68648c40a314`.
Первый backup до S179:
`/home/syurai/vibe-seller-state/backups/s179-before-20261004T092154Z-code.tar.gz`,
SHA256 `29dd62b71d54a753f44020a7cc507a8322214d2902492ad1d5f0b6a75f2f1660`.
Host26/runtime10 hashes PASS; API/worker rebuilt. Priority/import lease удержан
при rollout/proof, markers сняты. Schema/intake/cron/resource caps прежние.

Read-only proof: pair2variants/2origins HOLD, singletonHOLD, othertenant и
selectedversion2/olderledger1 NO_HOLD. Receipt UUID совпал с S178. Source0,
все12 persisted table deltas0, gap не закрыт. Metadata EXPLAIN500rowselector
2.884ms execution/0.245ms planning без JSON/XML. Стоимость растёт с ledger
history; constant-time и whole-EIS SLA не обещаются.
`/var/lib/eis-browser/research/rejected/s179-retained-proof.json`, SHA256
`b76c18be42a06a633825631edec6b5df714c9cfcefd752830bb8302c97bfe115`.
Optimized staged proof `/var/lib/eis-browser/research/rejected/s179-staged-proof.json`,
SHA256 `410d997cacfe5d34b3beed01896dba056504ca9088b59c77f1b5a0e8f3c51032`.

До оптимизации held count добавлял лишний проход по всему индексу. Baseline
до S179:бумага3.415s/сервер9.451s при127009current numbers. Final deployed API:
3.444s/2436matches и9.399s/5138matches при127150current numbers,46heldcurrent.
Одноразовые замеры, изменившийся cron corpus и разный budget stage worker/API
не изолируют overhead. Это saved-index comparison, не поиск по всей ЕИС.
`/var/lib/eis-browser/research/rejected/s179-after-api-proof.json`, SHA256
`b59fe434a4e3511b5d8412fb8a28e27b84095a94c4578a8431f56df9818c75c5`.

Реальный HTTP hold:422/NOTICE_VARIANT_REVIEW_REQUIRED/no-store;
`/var/lib/eis-browser/research/rejected/s179-http-hold-proof.json`, SHA256
`2f7514b6f82a1c35ad0c3293459a1f1f8d05ee8a39b8cd8318ffc20854915e85`.
API health200/anonymous401/no-store/markersfalse; индекс2232882numbers,
бумага243.89ms/59matches, сервер610.14ms/184matches, coverage/freshness UNKNOWN.
`/var/lib/eis-browser/research/regions/s179-final-api-20261004T093329Z.json`, SHA256
`8059e4f187d026d37bcbd8a860fad646cf62e8aa90a145bd157c7fabdd6ba759`.

## Следующий S180

Отдельный ADR full-window variant intake/canonical projection: immutable receipt
всего набора и отдельное доказуемое решение о допустимости конкретной проекции.
Singleton не становится допуском автоматически; divergenceUNKNOWN. Переключить
intake после consumer gates; старые FAILED не переписывать. Далее — устойчивая
cadence/freshness, активные более ранние даты, bounded backfill/parity семейств
и ускорение comparison большого индекса. Полный охват и сравнение прибыли всей
ЕИС остаются незавершённой продуктовой задачей.
