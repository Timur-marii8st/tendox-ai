# S191 — повторяемое планирование завершённых дат

Статус: DEPLOYED / VERIFIED BOUNDED PLANNING. Owner root, 2026-10-05.
Контракт — [ADR0072](../../adr/0072-eis-durable-planning-retry.md).

Начальный диапазон2–4Oct:99candidatecodes×5families×3dates=1485keys;
S190 recent-gap393 оказался ошибочным:297 DEFAULT EF были посчитаны с
неверным suffix. Source key factory хранит DEFAULT EF без suffix (legacy).
Перед repair domain-key snapshot подтвердил1389planned/96missingEOK.
Cursor начинается2Oct; после полного receipt
продвигается по <=3days chunks. При простое старые непроверенные даты сохраняются.
Busy/failure/invalid result не меняют cursor. Планирование использует существующие
31-target atomic target+audit batches, ON CONFLICT DO NOTHING, source0.

Планировщик проверяется каждые5минут, минуты4,9,...59; после успеха IDLE.
Import lease/worker2CPU2GiB/source cron и DB100GiB/minfree40GiB сохраняются.
Host receipt private/tenant-scoped/atomic/fsync; expected scopeSHA проверяется
по полному контракту EisCorpusScope. Нет source data/URL/token в cursor.

Linux74PASS06:16:03UTC (planner20+existinglease/metrics54), source0/networknone.
Ruff/Linux-platformmypy/bashsyntax PASS. TypedDict receipt/due outputs;
strict runtime validation rejects wrong scope/digest/count/status/unknown fields.
Rollout06:20:28UTC:2scripts/1test/6docs, atomic9, host20hashPASS06:21:06UTC.
API/web/worker не пересобирались; HEAD03. Backup code SHA256
`e6d2cb8b4bc944ef94608d958e792c791e042f4e2fbfa1e28243122e3d5d4220`,
path `/home/syurai/vibe-seller-state/backups/s191-before-20261005T062028Z-code.tar.gz`.
Postinstall shell-check helper первоначально ссылался на неверное имя sh;
исправлен, actual daily bash syntax и host hashes проверены до live pass.

Controlled source0 pass06:22:36–06:22:46UTC:

- Before:1389planned/96missing, scopeSHA
  `67f76af00ac93aa5eaa6c3656d7c1b2ab20476c324a9ea9a7c8d69ca8f8bd6d8`.
- Один31-target batch создал6targets/6audits; cursor ещё отсутствовал.
- Real daily wrapper повторил весь scope:90remaining targets, exact receipt.
- After/repeat:1485exactkeys/missing0;15982oldattempts и1389oldtargets имеют
  прежние полные rowSHA256;96newtargets/96exact target audits, no duplicates.
- Direct duplicate CLI plan new_targets0; cached wrapper IDLE/source0.

Cron changed06:23:57UTC exactly1plannerentry; остальные source entries unchanged.
BeforeSHA `d20580264560d4bb8e733172a907d39c6b92aeb6fd4c418182e2390c2c88ef88`,
afterSHA `012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f`.
Two ordinary cron IDLE records observed in corpus log by06:30; no extra source
dispatch. Ресурсы2CPU/2GiB и100GiB/minfree40GiB unchanged.

Corrected tenant RR/read-only census06:26:48UTC: recent1485planned/missing0,
canonical374/NO_DATA1015/unattempted96; globalplanned149176/canonical5499/
pending143677/unattempted135583/NO_DATA8069. Current priority50/77/78:120planned,
due0. All diagnostic helpers source0/DBwrites0; partial and full planning wrote
only new targets+audits. Background cron продолжал обычную source/DB работу.

## Исправление доказательств S190

Original proofs immutable, recent subcounts отозваны как MISKEYED_SCOPE.
Corrected census использует EisCorpusScope.batches()/selection.window_key.
Retrospective planned_at reconstruction (не replay historical RR snapshot)
на04:49:59.627 и05:55:55.749:1389planned/96missing/297legacyDEFAULT EFpresent.
Этот дефект не менял source ingestion, globalqueue counts или S190 lease timings.

## Private evidence на VPS

Root `/var/lib/eis-browser/research/rejected/`:

| File | SHA256 |
| --- | --- |
| `s191-before.json` | `98a75a4f01249486130844d851aa6f99e89f11417eb389b5817ccc887c35829c` |
| `s191-partial.json` | `c7c9f52818573b79ee7bc6ab5b97642e73a1809670f87f900f75e19979dad0aa` |
| `s191-after.json` | `c179ba32e0cd575f2a72d833ebf19303eeca7390a89e4908a4775d9f4b15ae61` |
| `s191-repeat.json` | `015af907e18a99378b6651e4c32c426bb402de78a5cafda23931732b5ad4db4a` |
| `s191-s190-correction.json` | `c2344544ea91148d4515230e27af37d4b5666468ba7aff5121f6bf53da384fb5` |
| `s191-corrected-census.json` | `91819b41f1ba90e5f8e573b17340006d0fd76bc6d6a3d979a39b2c146dd3789f` |

Cron backup `/home/syurai/vibe-seller-state/s191-cron.before`; proof
`s191-cron-proof.json` SHA256 `b548ba5e854d8e0abf5be40b8b284e108b53723f866e74853fd5ddf12283db8b`.
Planning completeness не доказывает canonical/fullEIS/nationalfreshness/profit.

## Итоговая проверка VPS

2026-10-05 06:37:20 UTC: проверены хеши 21 файла на хосте и двух файлов
в API; расхождений нет. Два runtime scripts и тест побайтово совпадают
с Linux stage, прошедшим 74 теста. API/web image IDs и 12-символьный
worker image prefix сохранены; HEAD `20261004_03`, API health 200, OOM false.
Лимиты API 1 GiB / web 768 MiB сохранены. Read-only receipt: БД
3 945 159 703 байта, свободно 258 990 403 584 байта, test DB отсутствуют,
priority/223 markers false в момент проверки. Source requests 0, DB writes 0
относятся к этой диагностике; обычный cron продолжает свою работу.

- Private receipt `s191-operations-proof.json`: SHA256
  `f5feef4ce59a58ccfc5d06323fa1154b88c2f6dba3f2d9624fc1a1cb0a519f89`.
- Docs backup `/home/syurai/vibe-seller-state/backups/s191-before-20261005T063719Z-docs.tar.gz`:
  SHA256 `5de2164a013b952ace0abf77a9160a40496483e784b1c2fca0f194ab49aab240`.
- Итоговый docs-only пакет включает семь документов, в том числе исправление S190;
  эти receipt additions включаются в заключительную сверку хешей.

Следующий срез: измерить фактическое прохождение свежих запланированных окон
через source ingestion и canonical index, возраст очереди и причины задержек.
Завершённое планирование не является основанием повышать source concurrency
или объявлять национальную свежесть подтверждённой.
