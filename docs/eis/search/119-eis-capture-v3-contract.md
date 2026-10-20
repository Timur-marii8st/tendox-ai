# M2b1: отдельный capture V3 и ограниченное временное состояние

Дата2026-10-08. Статус **ACCEPTED CONTRACT; реализация и actual fit UNKNOWN**.
Владелец root; архитектурный review Astra. Зависимости: [PRD §3.1](../../product/11-product-requirements.md#31-поиск),
[M2](../../product/16-improvement-program.md), [capture V1/V2](117-eis-frozen-benchmark-capture.md),
[ADR0109](../../adr/0109-bounded-eis-capture-v3-state.md).
Результаты инструмента и actual runs — в [evidence](118-eis-benchmark-instrument-evidence.md).

## Ресурсный профиль production6 — 2026-10-08

По прямому разрешению пользователя после подтверждённого production5
`CAPTURE_TIMEOUT` полный исходный scope25relations сохраняется. Для одного
следующего exact запуска production V3 plan использует capture3600s,
payload17179869184B (16GiB),4096physicalfiles и RAM4294967296B (4GiB).
V3 limits принимают только два целостных профиля: исторический
`(900s,4GiB,512files)` либо этот `(3600s,16GiB,4096files)`; mixed profile
отвергается. V1/V2 планы и модели не расширяются; synthetic V3 сохраняет старый
профиль. Разрешение нового ceiling не доказывает достаточность для corpus.

Строки, fragments, metadata, batches и PG statement/lock limits прежние:
raw8MiB/32MiB audit, logical64MiB, fragment/shard8MiB,max8fragments,
metadata16MiB,batch8rows/64MiB,1Mrows/relation,statement30s/lock1s.
Membership1GiB/verifierSQLite8GiB,tmp64MiB,CPU1,pids128,swap0 не меняются.
Collector membership deadline наследует начало capture и3600s; offline verifier
имеет собственный3600s deadline. Controller phase3660s,overall8000s,
cleanup reserve300s; durable launcher8060s плюс fallback cleanup300s.
Collector полностью удаляется до создания offline verifier (networknone).

Перед каждой фазой сервер повторно проверяет `MemAvailable`: worker4GiB плюс
минимум1.5GiB свободного резерва для роста PostgreSQL/приложения/ОС. Их уже
занятая память не входит в MemAvailable. Missing/invalid/low facts блокируют
фазу. Это admission, не резервирование против будущего роста соседних сервисов.
Collector disk admission требует16GiB payload+1GiB membership+64MiB pending+
16MiB metadata+5GiB free reserve (23706206208B); verifier после существующего
пакета требует прежние8GiB SQLite+16MiB report+5GiB reserve (13975420928B)
на общем filesystem. Sequential execution исключает одновременные4GiB workers.
Scope/tenant/RLS/read-onlyRR/DB clock/provenance и полный integrity/semantic
verifier сохраняются. Исторические описания ceilings ниже относятся к старому
профилю; этот раздел задаёт единственное разрешённое расширение production6.

## Версия, данные и пределы

Новые exact discriminators: `eis-search-capture-plan-v3`,
`m2b1-full-tenant-search-projection-v3` plan ID,
`eis-search-capture-manifest-v3`, `eis-search-capture-incomplete-v3`,
`eis-search-capture-verification-v3`, fragment kind `ROW_FRAGMENTS_V3`.
Модели frozen/extra-forbid; dispatch только по exact version. Cross-version
plan/manifest/incomplete/descriptor отвергается. Не выводить версию из наличия полей.

Новый строгий `FragmentationPolicyV3`: ordinary raw8388608B, audit raw33554432B,
encoded logical row67108864B, fragment8388608B, максимум8parts и точный sorted
allowlist ниже. Missing/extra/duplicate/reordered names и несовместимые
role/selection/columns отвергаются:

```text
audit_events
eis_223_event_schema_checks
eis_223_events
eis_223_lot_event_schema_checks
eis_223_lot_events
eis_223_notice_versions
eis_223_schema_checks
eis_notice_projection_batches
eis_notice_projection_decisions
eis_notice_variant_receipts
eis_notice_variants
eis_notice_versions
```

Audit selection остаётся LINKED_AUDIT; остальные11 — FULL_TENANT, non-FK,
с JSON column. Те же25relations/колонки/PK/FK/indexes/current/future selection,
tenant/RLS/schema, полный linked audit basis. Другие relations остаются inline.
Оба V1 и оба V2 plans неизменны; их frozen source pins не разрешают новый
capture изменённым source. Historical verification сохраняет прежние исходы,
descriptor kinds/paths/report fields и audit-only V2 policy.

Не меняются physical8MiB, payload4GiB/512files, metadata16MiB, 1Mrows/relation,
batch<=8/64MiB raw, capture900s, PG statement30s/lock1s и RAM2GiB.
V3 verifier также имеет внутренний900s budget и bounded SQLite interruption;
прежний controller process bound930s/overall2100s с cleanup reserve сохраняется.
Дополнительные transient ceilings ниже не входят в payload counters.

## Exact encoding и целостность

Source6 implementation candidate (2026-10-08): только V3
`eis_notice_versions` сначала сортирует PK в узком SQL subquery, затем читает
тот же полный projection через correlated LATERAL по всему PK. Оба subquery
сохраняют исходный tenant/selection; внешний `ORDER BY` сохраняет точный C-PK
порядок. OFFSET0 препятствует flattening, но не гарантирует будущий план.
Наблюдавшийся `EXPLAIN DECLARE` показал narrow Sort → indexed payload lookup
без wide outer Sort; это не измерение времени и не доказательство причины
неуспешного production4. Требуются independent source review и actual isolated
PG equivalence до нового capture. Все25 relations, bytes, prefetch formula,
ceilings и V1/V2 query paths остаются прежними; client-side PK buffer не добавлен.
V3 SQL failures могут иметь фиксированный relation/operation/SQLSTATE reason
с заранее наблюдавшимся backend ID. Missing state остаётся UNKNOWN; SQL,
parameters и exception text не сохраняются, diagnostic SQL после fault нет.
Первичная ошибка сохраняется при дополнительном отказе cursor close/abort.
Подробный контекст решения — в [ADR0109](../../adr/0109-bounded-eis-capture-v3-state.md).

До stream cursor измерить SQL count/max text width в той же READ ONLY RR TX;
audit<=32MiB, ordinary<=8MiB. Prefetch заранее
`min(8,floor(64MiB/max(1,max_raw_width)))`; повторить actual row/batch checks.

Малая строка имеет прежние canonical typed JSONL bytes. Большая строка сохраняет
те же bytes с newline, без compression. Descriptor связывает version, tenant,
relation, typed PK, logical ordinal, whole length/SHA, ordered fragments
path/ordinal/offset/length/SHA. V3 paths:
`fragments/{relation}-{logical_ordinal:07d}-{fragment_ordinal:02d}.bin`.
Nonfinal piece ровно8MiB, final непустой; количество равно ceil(length/8MiB).
Строка<=8MiB не может быть fragmented. Один path — один owner; manifest имеет
exact physical closure. Logical count/digest учитывают восстановленную строку
один раз; descriptor PK равен decoded PK.

До reads/allocations проверить declarations/limits; reassemble одну bounded
строку и применить прежние tenant/order/PK/FK/current/future/projection/receipt/
audit semantics. Hash-consistent повреждение basis по-прежнему FAIL. Missing,
extra, duplicate, cross-owner, gap/overlap, unsafe/nonregular path, неверные
offset/size/hash/PK/version и mixed descriptor kinds отвергаются.

Exact raw authority — PG observation в capture TX. Offline проверять bounded
decoded-string UTF-8 lower bound с relation-specific8/32MiB; меньшая граница
не доказывает exact source width. V3 report во всех исходах сохраняет
`raw_width_validation=DECODED_LOWER_BOUND_ONLY`,
`source_raw_width_attestation=UNKNOWN`, `capture_origin_trust=UNKNOWN`.
Top4 probe не устанавливает глобальный encoded максимум.

## Три отдельных временных объекта

| Объект | Main ceiling и условия |
|---|---|
| Collector membership | Fixed `.current-membership.sqlite3`, exclusive zero-byte regular0600 file; page4096/max262144=1GiB, journalOFF/tempMEMORY до schema/inserts |
| Collector pending row | Единственный `.fragment-row.pending`, <=64MiB exact encoded bytes; incremental checks, одна строка за раз |
| Verifier semantic SQLite | Один precreated zero-byte regular0600/nlink1 UID1000 file; page4096/max2097152=8GiB, journalOFF/tempMEMORY до schema/data |

Membership и verifier используют по одному соединению, mode=rw URI, fixed
parameterized SQL; нет ATTACH/WAL/VACUUM/extensions/backup или второго
неconfigured connection. `TEMP_STORE=0`/unknown configuration запрещены.
Прочитать effective PRAGMAs до data. External operator identity pin проверяет
SQLite version/source_id/canonical compile-options SHA **для обоих** процессов.
Package/plan/manifest не задают trusted path/URI/PRAGMA/runtime authority.

V3 API/CLI требуют явный operator SQLite context; verifier дополнительно
scratch database. Production verifier path только `/capture/scratch/keys.sqlite3`,
URI `file:/capture/scratch/keys.sqlite3?mode=rw`. Operator runtime identity —
отдельный bounded regular staged file вне package. V1/V2 не принимают новые
аргументы и сохраняют прежний TemporaryDirectory lifecycle.

Verifier file имеет единственный RW bind, RO parent/root, без RW ancestor;
source/corpus RO, report RW с frozen16MiB writer, networknone/capdropALL/nnp.
`SQLITE_TMPDIR=/tmp`, `TMPDIR=/tmp`, RO cwd; `/tmp64MiB` сохраняется. Проверять
полный mount set, image volumes, bounded system mounts, actual inode и swap
policy. Нельзя объявлять file bind/page limit общей arbitrary-code quota или
RAM limit доказательством swap0. Temp spill допустим только внутри проверенных
конечных memory/tmp bounds, без report/другого host-disk fallback.

## Disk, время и отказ

Перед fresh collector allocation на общем filesystem free>=remaining4GiB
payload+1GiBmembership+64MiBpending+16MiBmetadata+5GiBreserve, то есть минимум
10GiB+80MiB без дополнительных allocators. Перед verifier free>=remaining8GiB
scratch+remaining bounded report+5GiBreserve. Уже существующий package отражён
в free space и не списывается дважды. Разные filesystems учитываются отдельно.
Admission не резервирует место против concurrent host writers; mid-runENOSPC
завершает операцию. Existing free5GiB floor/per-emission checks сохраняются.

Резервировать file/byte counters **до** открытия/записи каждого physical payload;
проверять monotonic deadline/disk в row/fragment loops и вокруг SQLite work.
SQLite progress/deadline interruption обязателен для длинных statements.
Pending row никогда не увеличивает completed count; при неизвестном partial
fragmented relation actual count UNKNOWN, не число только inline rows.

Любой FULL/I/O/constraint/memory/deadline fault — terminal без rollback-dependent
recovery/continuation/reuse. Не публиковать COMPLETE manifest при residual
membership/pending или неоконченной строке. Cleanup failure не стирает исходный
typed failure. Basis/DSN/env/произвольный exception text не попадают в logs.
Incomplete разделяет host attempted_at и nullable DB T/snapshot/runtime.

Verifier закрывает scratch, но не удаляет. Controller сначала удаляет exact
owned container и подтверждает отсутствие; затем проверяет owner/private
parent/run nonce/device/inode и удаляет только исходный host file. Replacement
или неуверенная container absence остаются UNKNOWN; replacement не удаляется.

## Один implementation slice и проверка

После root acceptance контракта/sandbox Sol владеет только двумя capture модулями,
`scripts/eis-search-capture.py`, новыми synthetic/production08 V3 plans,
`tests/test_eis_search_capture.py` и `tests/integration/test_eis_search_capture_pg.py`.
Root владеет docs/future archive/controller plan; Astra — independent review.
Search/API/migrations/permissions/ingestion и старые plans не меняются.

Обязательны golden V1/V2 bytes/outcomes, strict policy/version refusals,
multi-relation exact roundtrip, 8/32/64MiB boundaries, Unicode/Decimal/null/
arrays/nested/escaped-wrapper amplification, tamper/semantic/FK/tenant controls,
global reservation/partial failures. Actual sandbox проверяет single-file
initialization/inode, sibling/journal/WAL/unlink/rename denial, tiny-page FULL,
tmp-full, timeout и container-first cleanup; enforcement не доказывает fit.

Fresh isolated real PG содержит несколько valid ordinary rows raw<=8MiB,
encoded>8MiB, несколько large audit bases и concurrent post-snapshot commit.
Collector/verifier работают в intended2GiB/CPU/pids/tmp/file-bind layout.
Измерить оба main DB page counts/lengths, pending max, tmp и whole-cgroup RAM/
swap отдельно. 64MiB encoded не является heap bound; full semantic-state stress
и worst valid objects обязательны. Synthetic PASS не подтверждает full corpus.

Затем source freeze/independent review, отдельный archive/controller adaptation
и fresh actual capture. Origin/replay/independent labels/quality metrics имеют
свои acceptance. До них M2 и охват всей ЕИС остаются незавершёнными.

## Уточнение B1–B6 перед реализацией

Это закрывает finite author questions из
`capture-format-v3-author-contract-readiness-v1.json`; уточнения приняты после
final independent review/root acceptance. Все новые модели frozen/extra-forbid.

| Модель | Точные поля и типы относительно неизменного предыдущего контракта |
|---|---|
| CapturePlanV3 | CapturePlan V1 поля с V3 version/plan_id; limits: CaptureLimits; дополнительно fragmentation: FragmentationPolicyV3 |
| FragmentationPolicyV3 | ordinary_raw_row_bytes=8388608, audit_raw_row_bytes=33554432, encoded_row_bytes=67108864, fragment_bytes=8388608, max_fragments=8, relations: tuple[str,...] exact sorted12allowlist |
| RowFragmentDescriptorV3 | AuditFragmentDescriptor поля/границы: path, ordinal, offset, bytes, sha256; V3 path rule |
| FragmentedRowDescriptorV3 | FragmentedAuditRowDescriptor поля/границы: kind=ROW_FRAGMENTS_V3, relation из12allowlist, tenant, typed_primary_key, logical_ordinal, whole_bytes, whole_sha256, fragment_count, fragments: tuple[RowFragmentDescriptorV3,...] |
| RelationDescriptorV3 | RelationDescriptor поля: name, rows, shards, ordered_rows_sha256, source_count; дополнительно fragmented_rows: tuple[FragmentedRowDescriptorV3,...]=() |
| CaptureManifestV3 | CaptureManifestV2 поля с V3 version, relations: tuple[RelationDescriptorV3,...]; дополнительно collector_state: CollectorStateV3 |
| IncompleteCaptureV3 | IncompleteCaptureV2 поля с V3 version; дополнительно collector_state: CollectorStateV3 |
| VerificationReportV3 | VerificationReportV2 поля с V3 version; дополнительно verifier_state: SqliteStateObservationV3 или null до SQLite open |

Relation rows/source_count — logical, ShardDescriptor.rows — inline. Observation
wire ниже имеет все перечисленные поля обязательными, null явно означает UNKNOWN:

```text
SqliteRuntimeIdentity:
  version: Literal[eis-capture-sqlite-runtime-v1]
  sqlite_version: str[1..80]
  source_id: str[1..300]
  compile_options_sha256: Sha256
SqliteStateObservationV3:
  purpose: Literal[COLLECTOR_MEMBERSHIP,VERIFIER_SEMANTICS]
  runtime: SqliteRuntimeIdentity | null
  configuration: Literal[PASS,FAIL,UNKNOWN]
  page_size: int[1..65536] | null
  max_page_count: int[1..2097152] | null
  journal_mode: Literal[off] | null
  temp_store: Literal[2] | null
  page_count_last_observed: int[0..2097152] | null
  main_file_bytes_last_observed: int[0..8589934592] | null
  file_identity_unchanged: bool | null
  connection_closed: bool | null
  failure_code: str[1..100] | null
TransientCleanupV3:
  status: Literal[PASS,FAIL,UNKNOWN]
  membership_removed: bool | null
  pending_removed: bool | null
  failure_codes: tuple[str[1..100],...] max8
CollectorStateV3:
  membership: SqliteStateObservationV3 | null
  pending_peak_bytes: int[0..67108864] | null
  cleanup: TransientCleanupV3
```

Failure codes — fixed safe source literals, не exception text. Last_observed
не называется peak. COMPLETE требует configured PASS/runtime/identity,
закрытого membership и cleanup PASS; CAPTURE_CONTENT_VERIFIED — configured
PASS/runtime/identity и закрытого verifier. После ошибки не выполнять SQL
ради observations: сохранить последние известные значения, остальные null.
Проверять purpose и observed configured limits относительно роли: membership
max262144pages/1GiB, verifier max2097152pages/8GiB, page4096/journaloff/temp2.
Согласованные package observations всё равно не аттестуют external origin.

Operator runtime file<=16384B, bounded regular no-follow read. Compile options:
<=256 уникальных строк по<=1024chars из PRAGMA compile_options, duplicate/invalid
отвергнуть; SHA256 от `canonical_bytes(sorted(options))` без newline. Точно
сравнить version/source_id/digest в каждом процессе. Production pin root выводит
из принятого isolated pinned-image observation; package не задаёт authority.

Capture API keyword-only `expected_sqlite_runtime`; verify — этот аргумент и
`scratch_database`. CLI обеих команд: `--sqlite-runtime-identity`; verify также
`--scratch-database`. V3 требует контекст, V1/V2 отвергают новые аргументы.

Collector сам создаёт fixed output_root/.current-membership.sqlite3 после
проверок нового output root: O_EXCL|O_NOFOLLOW,0600 на созданном FD,
regular/UID1000/nlink1/zero/device/inode до/после fixed mode=rw open.
Произвольного membership path нет. После закрытия удалить только тот же inode
на success/failure; replacement/unclosed connection не удалять, cleanup
UNKNOWN/FAIL. Pending имеет такой же identity-bound lifecycle. Остатки —
transient facts, не COMPLETE payload closure.

Public V3 capture/verify POSIX-only, UID1000; Windows даёт typed platform
failure до filesystem/SQLite mutation. Windows units используют pure normalized
file/runtime validators, serializers и private connection/core. Никаких public
flag/env/plan bypass guards. Positive public end-to-end lifecycle/ownership
обязателен в actual Linux PG/sandbox.

Output/membership/pending находятся на одном filesystem; проверить st_dev/path
bindings до allocation, требовать10821304320B free. Verifier scratch/report
на одном filesystem требуют13975420928B; на разных scratch8GiB+5GiBreserve,
report16MiB+5GiBreserve на каждом отдельно. Report path — controller context,
не package input; source проверяет scratch FS, controller — report admission.
Уже существующий package не добавлять к free requirement повторно.

Cooperative900s monotonic deadline проверяется до/после SQLite operations и
iterator steps; busy_timeout=0, set_progress_handler каждые1000opcodes
interrupt при истечении. SQLITE_INTERRUPT/deadline — fixed typed terminal
failure. Progress handler не ограничивает OS I/O stall: hard930s process kill
принадлежит reviewed controller. Fake clock/long recursive SQL проверяют
cooperative interruption; Linux controller — hard kill/cleanup. Source не
заявляет hard900s.
