# S190 — измерения общего доступа загрузчиков к ЕИС

Статус: **DEPLOYED / VERIFIED BOUNDED OBSERVABILITY**, 2026-10-05.

**Correction S191:** прежний recent-gap393 отозван. Census вручную добавлял
suffix `/epNotificationEF2020` к DEFAULT EF, тогда как domain window_key для EF
использует legacy key без suffix. Это создало297 ложных gaps. Domain-key live
snapshot S191:1389planned/96missing до repair;1485planned/0missing после.
Retrospective planned_at reconstruction подтверждает EF297 уже существовали
на обоих S190 cutoff. Старые immutable proofs сохранены как MISKEYED_SCOPE;
их recent planned/canonical/NO_DATA/unattempted нельзя использовать для coverage.
Global queue counts и lease metrics этим дефектом не затронуты. Evidence — docs74.

Контракт — [ADR0071](../adr/0071-eis-shared-lease-observability.md).
Цель: измерить ожидание и работу четырёх загрузчиков на общем import lease,
затем выбирать расписание национального обновления по наблюдаемым данным.
Это operational evidence, не подтверждение полноты ЕИС или выгодности закупки.

## Исходная очередь

Read-only tenant snapshot 2026-10-05 04:49:59 UTC:

| Показатель | Окон |
| --- | ---: |
| Запланировано | 149050 |
| Canonical | 5428 |
| Pending | 143622 |
| Pending без попытки | 135611 |
| Pending с последним NO_DATA | 7987 |

Для завершённых дат 2–4 октября по МСК, 99 candidate codes и пяти семейств:
1485 ожидаемых domain keys; corrected reconstruction:1389planned/96missingEOK.
Это изменившийся после полуночи scope; S189 proof для прежних дат не доказывает
его полноту. Candidate codes не являются проверенным реестром регионов.
В текущем priority scope 50/77/78 — 90 часовых targets, 90 planned, due0.
Это не национальный scope и не доказательство свежести всех карточек.

Baseline proof на VPS:
`/var/lib/eis-browser/research/rejected/s190-baseline.json`,
SHA256 `ebdd5a0ae3ee7f26fd24b40bc614bf0cc57d5ab18a18bb4e2924b598465eb9b6`.
Source requests0, DBwrites0. До S190 сопоставимые timestamps имел только223
wrapper; joint capacity UNKNOWN.

## Проверки и rollout

Linux stubs: **54 PASS**, 2026-10-05 05:38:31 UTC, network disabled,
source requests0. Observer synthetic checks **15 PASS**: clipping/union/lane filtering,
censoring, drift/boot/phase rejection, terminal result counted once, bounded
regular-file reading. Ruff/compile/bash syntax PASS.
Astra review runtime/logger/deployment PASS; observer corrections applied.
First gate exposed priority TERM-before-trap race; trap now precedes marker
creation and is restored after acquisition. Priority/documents reap only their
waiting flock process. Corpus signal policy and active Docker cancellation
remain as before. Logging failure preserves stdout/exit and owned marker cleanup.

Script-only rollout 05:39:57 UTC: 14 atomic replacements (scripts6/tests2/docs6),
host20 hashes PASS. Helpers installed before wrappers, scripts mode700.
Backup `/home/syurai/vibe-seller-state/backups/s190-before-20261005T053956Z-code.tar.gz`,
SHA256 `d0019725e9646bff357ff9f6b75e20cf36d64074ddd86cfb96744de205352b21`.
API/web/worker image, schema, source budgets и cron не меняются.
Cron SHA256 `d20580264560d4bb8e733172a907d39c6b92aeb6fd4c418182e2390c2c88ef88`.

## Наблюдение и ограничения

Horizon start 2026-10-05 05:40:32 UTC; >=15 минут ordinary cron без
дополнительных source dispatch. End05:55:47UTC, horizon915s.

| Lane | Runs | Terminal observations | Work intervals |
| --- | ---: | --- | --- |
| corpus | 1 | ERROR1 (nonzero process exit) | 366.401s |
| priority | 3 | IDLE3 | Work phases отсутствуют |
| documents | 15 | IDLE15 | Work phases отсутствуют |
| 223_refresh | 2 | SUCCESS2 (process exits) | 90.217s и99.969s |

21 observed complete dispatch runs, censored0/inconsistent0. Captured56 valid
lines, rejected0;54 events относятся к21 runs, пересекающим horizon.
18 IDLE не имеют import/work phases, поэтому18 интервальных значений UNKNOWN/
not applicable. Три закрытых wait intervals: sum5.797s, max5.731s.
Observed shared held lower bound union557.018s (60.876% horizon); это минимум
наблюдаемого удержания, не фактическая utilization и не свободная capacity.
Observer source requests0/DBwrites0; ordinary cron продолжал source/DB работу.

Последние три typed corpus reports: BLOCKED/REGIONAL_REFRESH_REQUESTED,
attempted44/8/47, synced27/1/26. Это cooperative yield по существующему коду,
а не доказательство parser failure. Exact timestamp binding этих старых stdout
records к S190 run UNKNOWN. Metric ERROR означает ненулевой process exit,
SUCCESS не доказывает canonical/source completeness.

Final read-only census05:55:55.749UTC: planned149065/canonical5487/pending143578,
unattempted135507/NO_DATA8046. Recent subcounts отозваны из-за MISKEYED_SCOPE;
corrected reconstruction planned1389/missing96. Priority50/77/78:105expected/planned,
due0/unattempted0; oldest latest attempt age20625s, не freshness SLA.
Изменения между baseline04:49:59 и final census нельзя приписывать одному915s
sample. Оба census helpers source0/DBwrites0 и один tenant RR/read-only snapshot.
Пропущенные events, незавершённые runs и несопоставимые clocks остаются UNKNOWN.
Удержание lock оценивается только как OBSERVED_HELD_LOWER_BOUND: union интервалов
внутри горизонта, без сложения перекрытий и без суточной экстраполяции.
Полный охват ЕИС, national current-day SLA, source-call rate и прибыль UNKNOWN.

## Evidence

Private captured JSONL: `/var/lib/eis-browser/research/rejected/s190-observation-inputs/`,
current21423bytes SHA256 `b57904a6a79729db24ba116b4327fadbf9dc9f92595bb7cbed1332ec591748ec`;
previous missing (rotation ещё не происходила). Production retention8+8MiB.

| Proof | SHA256 |
| --- | --- |
| `s190-observation.json` | `8d7f0c482aaf7f55073ea00295289e6214884443406639f85d651d371a8bea58` |
| `s190-corpus-observation.json` | `bb3789838175ec2fb13cc14b46ea58150ba5fc70a65a4ebc62d5e86b0e6b4f09` |
| `s190-priority-observation.json` | `2a8a22e178f28b61482cdaa821433289eed9bbfdfe2551a5465e7d37c2eb6153` |
| `s190-documents-observation.json` | `aec2fbf25bcef293aaf1321432bd983b7ed15af99675682b5ced58896593d31e` |
| `s190-223_refresh-observation.json` | `5caadad939ab4b8b9f6f94071624f03b8334038cf7689239007bbe64e0262c2b` |
| `s190-final-census.json` | `9e75632aca251a90e23cff11f84729107b4b305fe15ac9b1845a5ecca4df8c40` |

Proof root `/var/lib/eis-browser/research/rejected/` on VPS. Host diagnostic
`/home/syurai/vibe-seller-state/s190-corpus-diagnostic.json` SHA256
`a422bc59cc367b01272a8ba62d9de38c7ff8e05beab70ca25ca97b1cd8356fbb`.
Final gate06:02:18UTC: host20/API2 hashes PASS; API/web full image IDs and worker
image prefix совпадают с pre-rollout snapshot. HEAD20261004_03, health200,
OOMfalse, API1GiB/web768MiB. DB3942718487bytes/free258988384256bytes,
test DB отсутствуют. Priority markerfalse/regional markertrue при работающем
ordinary cron — observation, маркеры не сбрасывались. Source budgets/cron unchanged.
Operations proof `s190-operations-proof.json` SHA256
`f58b35d18a1f7e0c7643af0eced87e4606330b4a709761a4edb7cf1250ee1a59`.
Docs backup `/home/syurai/vibe-seller-state/backups/s190-before-20261005T060217Z-docs.tar.gz`,
SHA256 `07625aa6201bc82320b2314faf00c96b7c0b0366713d01a64e35b1cdd35630ca`.
Receipt additions включены в final docs-only hash synchronization;
актуальные document hashes находятся в release manifest.

## Следующий срез: надёжное планирование новых дат

Corrected diagnostic: missing96EOK на4Oct. DEFAULT EF297 имели legacy keys
и были ошибочно исключены старым census. Три имеющихся EOK4Oct совпадают с50/77/78.
Исторические PLANNED records в corpus log: expected1188 (99×3×4), new0.
Deployed daily script содержит пять families; его хеш соответствует S189.
Последний corpus log record был SERVER_IMPORT_BUSY, но timestamps отсутствуют.
Причина пропуска04:10 daily cron — inference/UNKNOWN, не доказанный факт.

S191 acceptance: повторяемое планирование завершённых дней после lease busy,
exact1485 expected keys в текущем трёхдневном scope, повтор new_targets0,
остановка/перезапуск между31-target batches не теряет окно. Только добавление
недостающих targets и tenant audit; не менять предыдущие attempts/source bytes,
не сбрасывать NO_DATA, не повышать source/CPU/memory/disk budgets.
Планирование в CLI не вызывает browser transport; существующий journal.plan
использует ON CONFLICT DO NOTHING и atomic target+audit insert. Выбор режима
повтора должен учитывать измеренное ожидание общего lease. Planning completeness
отделяется от canonical/source completeness и freshness, которые остаются UNKNOWN.
