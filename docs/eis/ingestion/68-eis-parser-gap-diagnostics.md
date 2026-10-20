# S184 — диагностика отказов parser и исходные названия документов

Дата: 04.10.2026. Статус: deployed; release/live/API/operations PASS.
Контракт: [ADR0067](../../adr/0067-eis-parser-failure-diagnostics.md).

## Исходное состояние

Read-only census 14:16:51 UTC: 45 exact latest FAILED
`ATTACHMENT_REFERENCE_INVALID`, 5 `MEMBER_UNSUPPORTED`, canonical checkpoints
отсутствуют. Retained evidence для этих окон не найдено. Старые attempts не имеют
source response SHA; новый capture не устанавливает SHA старому ответу задним числом.
Baseline `/var/lib/eis-browser/research/rejected/s184-baseline.json`, SHA-256
`62a68ab4ad317ea5259994c8a1c3a3fa71f9877473f5687eb8911b70c3842de6`.

Три diagnostic-only окна получены через прежний source transport и полный
`bind_ready_window`: 42/2026-09-07/EZK, 30/2026-09-09/EF, 23/2026-09-30/EF.
33.044 s, 6 SOAP POST/5 archive GET, 5 ZIP; source leases/CPU2/memory2GiB,
DB100GiB/free40GiB и 600s gate перед следующим окном прежние. Ingest перехвачен
отдельным sentinel, rejection/partial write hook запрещён в research worker.
Карточки, checkpoint, journal и domain audit не записывались; все50 исходных
attempt records проверены на неизменность. Production cron продолжал работать.

Capture — полный новый bound source set для каждого из трёх окон, не полнота ЕИС.
Байты остаются на VPS в private research storage:
`/var/lib/eis-browser/research/rejected/local-eis-supplier/s184-20261004T142046Z/`.
`capture.json` SHA-256
`07d56f7bb32ea35a68a43e9f1d468bc527b73364763373d6080c45a3dafc7fa9`.

## Подтверждённые формы

| Sample | Причина | Evidence |
| --- | --- | --- |
| 42 / 2026-09-07 / EZK | 8 исходных имён содержат один `/`; остальные reference predicates проходят | Member ordinal + XML SHA + attachment ordinal |
| 30 / 2026-09-09 / EF | Повторный publishedContentId | XML SHA + attachment ordinal 20 |
| 23 / 2026-09-30 / EF | Один XML 34586604 bytes, выше 32 MiB | Archive SHA + member ordinal 65; oversized XML не распаковывается |

Shape probe SHA-256
`576184002e1524df62343fd0cb6a03a40b1230ef594f762afbc0cd3e21f5b65c`.
Samples не классифицируют автоматически все50 окон. Duplicate UID и oversized XML
остаются ошибками, лимиты не повышаются.

## Поведение

`fileName` — неизменный source display label. Только `/` разрешён как metadata;
backslash/NUL/1024 chars, UID/URL binding, uniqueness и ZIP member path guards
сохраняются. Label не превращается в basename и не используется как путь.

Document worker перед download выдаёт `ATTACHMENT_FILENAME_REQUIRES_REVIEW`,
attempted0. Probe не пишет outcome или audit. Для уже имеющихся bytes native
analysis/reanalysis возвращает typed UNKNOWN до DocumentInput, сохраняет raw label,
URL и SHA. Полный metadata import не означает полный download/extraction или допуск.

Новый pure diagnostic module возвращает tenant/window/response/archive/member/XML
provenance, exact failure flags, totals и bounded samples с truncation. Raw names,
URL, UID, тексты и credentials не выводятся. Все ZIP headers/global expanded bounds
проверяются перед XML read; oversized/encrypted/path-unsafe members не открываются.
Streaming guard 50000 nodes/depth128 не строит дерево перед full parsing.
Превышение остаётся UNKNOWN/NOT_RUN, не новым выдуманным canonical parser reason.
Canonical admission NOT_ENABLED, coverage/freshness UNKNOWN.

## Проверки и production

Cron/regions/families/source budgets/schema не расширялись.

141 Linux tests PASS (9.24 s), 40 PostgreSQL tests PASS (17.35 s), Ruff9/mypy4
PASS, независимый code review PASS. PG проверяет persisted filename-review job
до downloader, probe без writes, UNKNOWN cached reanalysis; прежние RLS/source
holds/expired/stale/receipt/evidence/index gates сохранены. Test fixture analyzer
использует существующую разрешённую версию, schema whitelist не менялся.

Staged retained diagnostics 14:34:32 UTC, 2.896 s, source0/writes0: 42 sample
37 XML/166 attachments, findings0; 30 sample16 XML/96 attachments, duplicateUID1;
23 sample269 member headers,266 XML inspected, size-limit1 и2 streaming node-limit
UNKNOWN. Для этих2 XML полного tree parsing не было, общая inspection incomplete.
Это не три закрытых gaps. Report SHA-256
`9d597d0f1eb62872c55f0434d63e84771de142ca972ad74c5c746012123eda9a`.
Independent SQL no-intake proof14:36:58UTC: captured response windows0/versions0,
diagnostic actor journal0/audit0. SHA-256
`32c5b291c17a4220e55868fd96a4e98f7bf6280c6da8b40ea428eeb9e2d4fe57`.

Deployment14:38:05UTC: host15/runtime4 hashes PASS, API+worker rebuilt,
schema HEAD `20261004_03`. Backup:
`/home/syurai/vibe-seller-state/backups/s184-before-20261004T143805Z-code.tar.gz`,
SHA-256 `cd5c2b9e8353b7ef3ba31817ad1757621e14a61ee4f825b81b80855b98136339`.
Deployed retained reports повторно сверили SOAP/URL/archive bindings и hashes,
дали те же findings за2.931s, source0/writes0. Source bytes на ноутбук не копировались.

Единственный controlled live retry42/2026-09-07/EZK14:39:28UTC:
SYNCED за8.372s,1ZIP/37newversions/0events,420430 archive bytes.
Canonical checkpoint/source SHA/new journal/audit проверены; все50 старых records
неизменны. Все8 slash labels сохранены точно. Metadata import не скачивает
166 файлов и не даёт document extraction/supplier PASS.

Полный tenant planned census14:41:21UTC:148183planned,5105completed,
143078pending,136524unattempted,6491NO_DATA; references44/members5 остаются.
Снимок содержит concurrent cron progress, весь прирост не приписывается S184.
Counts source windows не равны количеству закупок; coverage/freshness UNKNOWN.

Cached API44current134030:paper8.493s/2581matches,server15.589s/5427;
223current2898:paper227ms/59,server643ms/185;health200/anon401/no-store.
Test DB `procurement_eis_test_20261004_s184` удалена. Final operations14:44:00UTC:
DB3711048727bytes,volume free265053171712bytes,notestDB/bothmarkersfalse.
223 refresh marker при API снимке был active и снялся штатным владельцем;
чужой marker не удалялся. Реальный memory peak не измерялся; 2GiB — configured cap.

### Итоговые proofs

В `/var/lib/eis-browser/research/rejected/`:

| Файл | SHA-256 |
| --- | --- |
| `s184-deployed-diagnostics.json` | `969bf5c12d2c8499c9a21ef21feb263694555c656e2fbcbd0954e7a14843389f` |
| `s184-live-report.json` | `30816f678041240c275d2727e5e4a813d1a9e44fa6a5baa24b392164e17d71d9` |
| `s184-live-proof.json` | `ebd01123b4425ab98723f617d689734bbd36f9b6f87037deae44e31a5ce685ea` |
| `s184-final-census.json` | `bc40d52a62136c378ea10f704156133f82a79633f8bc4f33273c850f32f3fbcb` |
| `s184-api-proof.json` | `ba860732947fdb6b3b7fb8a0cd99802c02047f80853d0ce49af03519c0ff24e3` |
| `s184-operations-proof.json` | `c4512afcbfad054062f7b3468606455fa1856a867ba0a7e0b090bc4243065b72` |

## Следующий срез

Применить подтверждённый slash metadata fix к прежним region42 gaps ограниченными
проходами, с exact latest recheck и genuine canonical receipts. Остальные
references классифицировать по повторным UID и их metadata, не объявлять
одинаковыми по одному ID. Крупные XML требуют отдельно спроектированного streaming
parser; повышать cap без resource proof нельзя. Безопасное processing filename
с сохранением исходного display label — отдельный этап для document extraction.
Затем fresh backlog/parity и search latency; полный ЕИС пока не подтверждён.

## S185 — восстановление подтверждённой группы metadata gaps

04.10.2026. Operational slice; deployed S184 runtime, schema и cron не меняются.
Baseline16:00:14UTC:44 `ATTACHMENT_REFERENCE_INVALID`,5 `MEMBER_UNSUPPORTED`;
39 первых относятся к region42. Это фиксированная группа прежних attempt IDs,
а не утверждение о причине всех остальных отказов или об охвате региона.

Owner root: docs15/28/68 и ignored operator/proof helpers на VPS. Исходные
данные не копируются на ноутбук. Порции максимум3 окна,600s gate перед следующим
source call; shared priority→import leases с освобождением между порциями;
resource gates DB100GiB/free40GiB. Existing CPU2/memory2GiB не повышаются.
Каждый source call использует прежний `sync_eis_window`, immutable journal,
exact latest/planned/tenant/attempt ID/time/SHA и canonical-absence recheck.
Reports typed; coverage всегда UNKNOWN.

Первый проход:3canonical/162newversions/29.764s. Второй прерван после4-го
canonical окна (+74versions) и source duplicate в42/2026-09-09/EZK:37occurrences,
36pairs,35PROJECTED,1HOLD. Latest journal этого окна FAILED, PARTIAL не закрывает
source gap; genuine canonical checkpoint отсутствует. Новое evidence не
переписывает50прежних попыток. Stopped report сохраняется неизменным.

Независимый review уточнил operational contract: разрешено продолжать только
неопробованные distinct keys исходной39cohort после доказанного
`DUPLICATE_NOTICE_VERSION + PARTIAL + stage COMPLETE`. Конфликт не повторяется.
Валидированный receipt reader проверяет полный SHA receipt, prerequisite
retention/diagnosis/ledger audit payloads и exact audited occurrences/facts/origins.
Projection audit дополнительно сверяется по event/object identity, payload digest,
полному batch, ordered decision rows и receipt SHA. Actual held pairs проверяются
как HOLD/UNKNOWN; no LEGACY checkpoint. Всё это до следующего source call,
включая previous receipts каждого прохода. Иной отказ или неполный proof
останавливает цепочку. `FINISHED_WITH_GAPS` явно отличается от canonical.

Read-only `--verify-only` на VPS перед продолжением:5previous/34remaining,
source0/write0/PASS. Resume максимум12дополнительныхпроходов (overall14 с
прерванным вторым); каждый original key вызывается максимумодинраз. Runtime
admission и supplier participation policy этим не расширяются.

Baseline proof `s185-baseline.json`, SHA
`7acad5cda51c451cc9ca62dd3f6080538685c9837c5f1801d1d972b67bc98d2d`.
Stopped proof `s185-aggregate-proof.json`, SHA
`8a0bb51e4723fe45b169acd9c38894dcca0e071f0df8bfdf81cb65ffff96508d`.
Все proofs находятся в `/var/lib/eis-browser/research/rejected/`.

### S185 итог и proofs

Обработаны все39 exact frozen keys:38LEGACY_CANONICAL/2046newversions,
35partialprojectedversions/1HOLDpair отдельно; конфликт42Sep9EZK не закрыт.
14проходов/463.021s внутри проходов,source requests максимум по одномуокну
каждому ключу. Осталось0region42referencefailures,но5globalreferencefailures и
5members,а также отдельныеvariant/source/resourcegaps. Final39receipts/sourceSHA/
journal/audit/canonical-counts и fullpartialinventory/audits проверены повторно;
50исходныхrecords неизменны. Final census148213planned/5210canonical/143003pending,
136385unattempted/6594NO_DATA/2transport-only;99candidatecodes≠подтверждённые регионы,
coverage/freshnessUNKNOWN. Прирост общей базы включает самостоятельную работу cron.

CachedAPI44current138253,paper8.323s/2671matches,servers15.693s/5580;
223current2901,paper280ms/59,servers510ms/185;health200/anon401/no-store.
Operations16:25:03UTC:DB3807796247bytes/free264945225728bytes,notestDB/markersfalse.
Runtime/schema/cron не менялись, rebuild не нужен; S184tests не повторялись.
Operatorhelpers прошли Ruff/compile/bashsyntax и независимый review; их source0
verification и реальные SQL/API receipts — evidence этого operationalslice.

| Файл в `/var/lib/eis-browser/research/rejected/` | SHA-256 |
| --- | --- |
| `s185-final-verified.json` | `d532f000d4fdb9bb30bb8d326575f98043600a3682790ebe82ff984f65526237` |
| `s185-final-aggregate-proof.json` | `50f708f8dd6b24c6863682b2c4af11ff1b669020347feade74866b8bab40e6c3` |
| `s185-final-census.json` | `b1f67c6e7bc95ded6ed42bb82b4c27fa49dd9e427bfda9eb21302db0b368792a` |
| `s185-api-proof.json` | `62504c7a5d6b45cde9c2e56ea14c3228eee86c77468c2663489e0cf756bf9e35` |
| `s185-operations-proof.json` | `fbfec9ab430baf3f13fd6cd303cff44c580f222a7d16d61fee2ff9474bd52a8f` |
| `s185-search-scope-proof.json` | `5c995ff7750bd7a4d8e5d8bc25413a82b013d90b202bf57eeb063f4925c7681e` |

Searchscopeproof16:20:49UTC:paper2668candidates/1852expired/816future,
server5806/4052expired/1754future,unknown0/fallback0;source0/write0,4.927s.
Это selectivity около70%, не latency benchmark. Следующий S186: deadline scope
в SQL до snapshot hydration + historical mode API/UI; latest version first,
NULLUNKNOWN/holds/provenance и exact result parity; пятьsame-data warmruns и
измерение памяти. FullЕИС/полное сравнение и полноценные document/economic
решения по всем закупкам остаются неподтверждёнными.
