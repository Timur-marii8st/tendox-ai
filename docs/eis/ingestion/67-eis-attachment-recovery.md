# S182 — восстановление старых отказов по количеству вложений

Дата: 04.10.2026. Статус: deployed; controlled recovery и финальные проверки PASS.
Контракт: [ADR-0066](../../adr/0066-eis-obsolete-attachment-limit-recovery.md).

## Исходные данные

Read-only baseline16:35МСК:9незавершённых окон с exact latest
`FAILED / ATTACHMENT_COUNT_LIMIT`,7суточных25/78 и2часовых77/EOK.
Текущий parser уже принимает до4096 attachment metadata entries; превышение
имеет новый код `ATTACHMENT_METADATA_COUNT_LIMIT`. Source URL/UID, unsafe XML,
размеры, uniqueness, atomic ingestion и consumer holds остаются прежними.
Обоснование старого лимита и реальные примеры136/278entries — [docs43](43-eis-attachment-limit-review.md).

Baseline proof `/var/lib/eis-browser/research/rejected/s182-baseline.json`, SHA-256
`834656c4e3a883881f7db43b29badf3b40dfab41ffa7327d4f958150854cd298`.

## Операторский запуск

На VPS из каталога `/home/syurai/vibe-seller`:

```bash
bash scripts/server-eis-attachment-recovery.sh status
bash scripts/server-eis-attachment-recovery.sh run 3
```

Status читает всю eligibility группу, выводит точный count и до3candidate
immutable IDs; source token не нужен. Run обрабатывает максимум1–3окна через
прежний sync/browser/journal, с priority/import leases, CPU2/memory2GiB,
DB100GiB/free40GiB и600s gate перед следующим окном. Текущее atomic окно не
отменяется таймером. Source/service/DB/failedpartial ошибки останавливают pass.
Новый cron или автоматическая очередь повторов не добавляются.

Eligibility: planned tenant scope, exact latest FAILED старого кода,24h cooldown,
valid +03date/hour interval полностью завершён; canonical checkpoint отсутствует.
Перед каждой source operation заново проверяются latest ID, eligibility и
completion с operation clock. Изменившийся candidate даёт NOT_ATTEMPTED,
source0/journal0 и остановку. Все известные parser ошибки/NO_DATA/currentcap
исключены из этого recovery selector.

Результаты имеют typed plan/outcomes: original/new IDs, response SHA, actual
canonical checkpoint, новые versions/events и optional partial intake. PARTIAL
остаётся FAILED без checkpoint; NO_DATA остаётся gap. Metadata admission не
означает скачивание всех вложений или допуск поставщика. Coverage UNKNOWN.

## Проверки до выкладки

219 Linux tests и32 isolated PostgreSQL tests PASS; Ruff5files/mypy2runtime PASS.
Реальный стандартный sync на синтетическом архиве101metadata entry дал full
canonical import, сохранив прежнюю FAILED запись. Проверены latest tie/RLS,
date/hour/past/invalid/currentcap exclusion, superseded candidates, budget/DB
stops, partial/failedprojection и typed evidence. Linux process gates проверяют
сигнал сразу после marker publication/во время import wait, cleanup после worker
ошибки и сохранение marker чужого priority owner. Waiter process kill/reap,
ownership flag и traps установлены до публикации собственного marker.

Production staged plan16:48МСК:9eligible/3selected,1.957s, EXPLAIN895.854ms,
source0/writes0. Proof `s182-staged-status-proof.json`, SHA-256
`deb5bda65a87224ae3fb552de5934c322e4900f690bc831b028e8a387ba0e8e7`,
в `/var/lib/eis-browser/research/rejected/`.

## Production

Deployment 13:52:11 UTC: API и worker пересобраны, host 12/runtime 2 hashes PASS,
HEAD `20261004_03`. Backup:
`/home/syurai/vibe-seller-state/backups/s182-before-20261004T135211Z-code.tar.gz`,
SHA-256 `d2928434beeca140aafe898b3f06c1f918c851c94bf238f2f0450ffa958eea1a`.
Deployed read-only plan: 9 eligible/3 selected, 1.969 s, EXPLAIN 910.364 ms,
source 0/writes 0. Это один замер, не SLA.

Один реальный `run 3`, начатый 13:55:56 UTC, завершился за 39 s, exit 0:

| Source window | Outcome | ZIP | Новые versions | Max attachment metadata |
| --- | --- | ---: | ---: | ---: |
| 25 / 2026-09-25 | SYNCED | 1 | 59 | 193 |
| 78 / 2026-09-23 | SYNCED | 3 | 271 | 240 |
| 25 / 2026-09-21 | SYNCED | 1 | 68 | 278 |

Итого 398 новых версий, 5 архивов, 0 новых lifecycle events. Для каждого окна
проверены canonical checkpoint, точный source response SHA, новая journal запись
и audit. Все девять исходных FAILED записей сохранены побайтно по значениям
полей. Max metadata измерен среди новых persisted versions с тем же window/SHA;
это количество ссылок, а не скачанных файлов вложений. Осталось 6 eligible окон.

Cached API smoke: 44-ФЗ current 132982, бумага 8.390 s/2558 matches, серверное
оборудование 14.733 s/5373; 223-ФЗ current 2887, бумага 302 ms/59, серверы
615 ms/185. Health 200, anonymous 401, no-store; coverage/freshness UNKNOWN.
Индекс продолжает пополняться штатным cron, эти counts — моментальный снимок.
Test DB `procurement_eis_test_20261004_s182` удалена. Operations 13:57:37 UTC:
оба markers отсутствуют. Source requests при проверках 0; чужие markers не удалялись.

Proofs в `/var/lib/eis-browser/research/rejected/`:

| Файл | SHA-256 |
| --- | --- |
| `s182-deployed-status-proof.json` | `4f0450c7bc40ce6882fff01f24831ff02b7abf8d6fa05d60b09b577dd1428697` |
| `s182-live-proof.json` | `9f95e5181494fea24b2acbd0ec573a88e88716b15788430eeaafd8f0fe8352c1` |
| `s182-api-proof.json` | `90edca84d9b9338939f585ce17fb27379e0fd729c8a14db88841d0f00db64f8c` |
| `s182-operations-proof.json` | `63825cc567996e32e1d05c95d3982b0f99c638b107b09778872785724c922e04` |

## Следующий срез

Оставшиеся 6 старых отказов восстановлены в S183 ниже. Следующий срез:
классифицировать `ATTACHMENT_REFERENCE_INVALID` и `MEMBER_UNSUPPORTED`
по точным source bytes и member/XML provenance перед изменением parser.
Затем проверить свежий backlog/parity и оптимизировать latency большого
поискового индекса. Полный ЕИС и срок полного сравнения пока не подтверждены.

## S183 — завершение восстановления старых отказов

04.10.2026, operational slice по deployed ADR0066, owner root. Runtime, cron,
schema, parser safeguards и resource budgets не менялись. Baseline 14:06:46 UTC:
6 eligible, status 1.978 s, EXPLAIN 915.500 ms, source 0/writes 0.

Два прохода `run 3`, каждый с отдельным recheck и последующей сверкой receipts:

| Source window | Outcome | ZIP | Notice records | Новые versions | Max metadata новых rows |
| --- | --- | ---: | ---: | ---: | ---: |
| 78 / 2026-09-18 | SYNCED | 3 | 212 | 212 | 240 |
| 78 / 2026-09-17 | SYNCED | 3 | 252 | 252 | 236 |
| 25 / 2026-09-16 | SYNCED | 1 | 55 | 55 | 273 |
| 25 / 2026-09-15 | SYNCED | 1 | 54 | 54 | 271 |
| 77 / 2026-10-02 15:00 / EOK | SYNCED | 1 | 4 | 0 | — |
| 77 / 2026-10-02 14:00 / EOK | SYNCED | 1 | 5 | 0 | — |

Первый проход: 14:06:58 UTC, 46 s, 519 новых versions. Второй: 14:08:10 UTC,
31 s, 54 новых versions. Итого 10 ZIP/582 notice records, 573 новых versions,
0 lifecycle events. В двух часовых окнах извещения уже сохранены; новые rows
не создаются повторно, max metadata для новых rows не применим. Все6 actual
canonical checkpoints и source SHA/journal/audit проверены, все9 исходных FAILED
records неизменны. Следующий typed plan: eligible 0. В S182/S183 восстановлены
все9 исходных окон, добавлена 971 версия. Это не весь ЕИС и не скачивание всех
файлов вложений.

### Полная очередь и операционные проверки

Census 14:09:05 UTC за 8.620 s: 148168 planned, 5088 canonical completed,
143080 pending, из них 136544 unattempted и 6472 NO_DATA. Старая attachment-count
группа отсутствует; 45 `ATTACHMENT_REFERENCE_INVALID` и 5 `MEMBER_UNSUPPORTED`
по-прежнему требуют диагностики. Остальные gaps относятся к variant/resource/
source contract/service errors. Это totals tenant planned queue; количество
source windows не является количеством карточек, 99 candidate region codes
не означают подтверждённое покрытие всех регионов. Coverage/freshness UNKNOWN.

Cached API: 44 current 133474, бумага 8.376 s/2574 matches, серверы 14.647 s/5406;
223 current 2894, бумага 282 ms/59, серверы 645 ms/185. Health 200, anonymous 401,
no-store. Измерения единичные, индекс и cron продолжают работать; SLA не заявляется.
Operations 14:09:55 UTC: DB 3698105367 bytes, свободно 265857155072 bytes,
тестовых баз и обоих markers нет. Чужие markers не удалялись. Все проверки
после source runs: source 0/database writes 0; proof files — на VPS.

Новые runtime tests не запускались: runtime неизменен, 251 S182 gates остаются
предыдущим evidence. Этот slice проверен реальными typed outcomes, SQL receipts,
полным census, API/operations и hash/head gates; code rebuild не требуется.

Proofs в `/var/lib/eis-browser/research/rejected/`:

| Файл | SHA-256 |
| --- | --- |
| `s183-baseline-proof.json` | `ea91b3a0c52415043dc5397df11883e9c76ade6d18e60b550c81de2eea8009d2` |
| `s183-live-proof-1.json` | `5c185e21271df6a9f35b4bc1eb8be3874439165bd63859497d4c10f809f98124` |
| `s183-live-proof-2.json` | `8bb7627d9b873a523ddef370a108966e72bae78216374172eec939694295b6eb` |
| `s183-final-census.json` | `f896e839cfa83bcdb8e769db4a0e267678243dc87a1dafd23802bff0ed5f2a18` |
| `s183-api-proof.json` | `313606665b934a9f69ecfbdc4522d7b0ec157dd171dccadcd86b8905d64d2bfb` |
| `s183-operations-proof.json` | `5ff47fcd9f2dc38b95ae32981ba4fd2865bb49bf81f7da764106e85c66e9d8d1` |
