# ADR-0058 — evidence quarantine конфликтующих versions44

Статус: **ACCEPTED / DEPLOYED**, S175,2026-10-04,06:07UTC.
Owner ADR:Astra; runtime/capture:root. Schema HEAD `20261003_05` не менялся.
Гипотеза byte-identical duplicates опровергнута; permissive fix отменён.

## Проверенное evidence

Полный READY set5ZIP для getDocsIP/PRIZ/77/2026-09-29+03:00:
2POST/5GET,7,697,126compressed ZIP bytes;7,701,141retained ZIP+SOAP bytes,
production mutations0. Container path:
`/var/lib/eis-browser/research/rejected/local-eis-supplier/s175-20261004T053757Z`.
Classification:499physicalmembers/498uniqueversions,85,606,319expanded bytes,
1DIVERGENTgroup,0identical,issues0. ClassificationSHA:
`e9ff8a90696bda181a5a4ed1b2957eaea57feda66ea85491a94d8dc191b4801d`.
CaptureSHA:`81935ef6339a18e4738f68dc2410ee3fa9b74ac80c180b6d38c8a395960edff9`.

Read-only review проверил оба XML SHA и224leaf fields каждого. Для
0373100047426001450/version1/epNotificationEF2020 различаются два leaf values:

| Path под epNotificationEF2020 | XML A | XML B |
|---|---|---|
| commonInfo/publishDTInEIS |2026-09-29T09:49:51.462+03:00|2026-09-29T09:51:18.297+03:00|
| notificationInfo/procedureInfo/collectingInfo/startDT |2026-09-29T09:49:51+03:00|2026-09-29T09:51:18+03:00|

XMLSHA A:`4a8b2c8bc6ad07232296e8c15b4d05a47478fc8d663a5430ca8fbfbf80492820`;
B:`52eb332959470cf6e258134bae6b6a2d55df7249342510a81e8ab391433f08e4`.
Оба в archiveSHA
`c393956c5d0703912adf9283d99c5c549880798db7a92b9301e5a805c2e15d4b`.
Возможная republication/technical variant — гипотеза, не source contract.
Поздняя публикация не выбирается как current автоматически.

## Решение: guards сохранить

Ни внутриZIP, ни междуZIP нельзя разрешить divergent same(number,version).
DUPLICATE_NOTICE_VERSION/_IN_WINDOW/NOTICE_VERSION_CONFLICT и all-or-nothing
admission сохраняются. Все499members остаются в evidence; ни498unique subset,
ни выбранный последний XML не объявляются SYNCED. Исторические FAILED attempts
не переписываются. Нужен отдельный официальный identity/variant contract.

## Предлагаемый bounded rejected-evidence slice

Opt-in retention, defaultoff, фиксированный EIS_REJECTED_EVIDENCE_DIR на VPS.
Hook в sync orchestration вокруг ingest/preflight failure после rollback;
storage validator не получает скрытого filesystem side effect. Первый allowlist
— три conflict codes выше. Token reflection/unsafe outgoing SOAP не попадают
в автоматический quarantine или reports.

Exact full ZIP set и immutable manifest содержат tenant/window, validated
incoming response/prepared fingerprints, archiveSHA/source binding,
typed reject reason и aware capture time. Member names/XMLSHA/type/business
keys находятся в отдельном classification proof и восстанавливаются из ZIP;
автоматический manifest не заявляется встроенным member-level inventory.
Duplicate filename остаётся ambiguity/rejection; никакого discard/subset.

Bounds прежние:64MiB compressed/window,50MiB/archive, expanded/member caps;
store quota5GiB под import lease до записи. Validated tenant/SHA-only relative
paths, atomic-temp+rename blobs, verify existing hash, final manifest последним.
Immutable permissions/проверкаSHA обязательны: immutable audit не защищает
mutable filesystem от изменения.

После durable manifest — tenant audit в отдельной transaction, без нового
admission/index store. FS+DB не атомарны: orphan manifest при audit failure
видим и повторно связывается deterministic audit identity. Replay того же
capture не пишет blobs/audit; иной source response остаётся иной observation.

Исходная typed source error сохраняется. Optional typed evidence ref содержит
manifestSHA/responseSHA/complete-set flag/retentionstatus, не raw XML/URLs в
exception text. Quota/IO/audit failure не заменяет исходный reject generic
SYNC_FAILED. FAILED attempt может получить verified responseSHA; успешный
checkpoint/SYNCED от этого не возникают.

## Acceptance и незавершённое

Tests: fullset retention/replay; divergent guard unchanged; duplicate filename;
tenant/path traversal/size/quota; corrupted blob; atomic manifest; auditfailure
recovery; safe errors/no tokens; replay no source calls; no notice/index/checkpoint
mutation. Actual evidence — операторская capture, не deployed quarantine service.
Retention lifecycle после5GiB и official revision semantics — отдельные решения.

## Промежуточное integration review

Прочитаны deterministic tenant audit/ref replay и opt-in sync hook. Hook ловит
только3conflict reasons после ingest rollback; originalstr сохраняется при
sink/audit failure. FAILED journal получает verified responseSHA без checkpoint
promotion. Parser/index duplicate guards не изменены. Audit UUID зависит от
tenant/manifestSHA; replay сравнивает exact basis и не добавляет audit повторно.

Замечания финального review:

- Ошибка retention/audit должна быть видима в consumer report/attempt basis:
  исправлено safe_metadata в corpus и typed freshness fields; перечитано.
- Reference redaction нужна на каждом FAILED/DISABLED path: binding/size reject
  до reflection check не должен передать token-bearing URL в audit. Исправлено:
  safe_base используется для failure paths; required-field reflection отклоняется.
- Actual manifest-byteSHA и bounded replay reads перечитаны. Осталась durability
  edge исправлена для первой записи: Linux directory-open/fsync errors
  распространяются, mkdir последовательно fsyncs parents. Перечитано.
  Recovery ещё должен повторить fsync после предыдущего failed fsync:
  manifest chain/leaf resync добавлен для new/replay и проверен чтением.
  Осталась sibling blobs-directory: она не входит в manifest path; после failed
  fsync(blobs) existing-blob replay должен повторять её fsync до RETAINED.
  Итоговые Linux/PG gates и deploy ещё pending.

Полный durability review: success для new/replay требует проверки SHA/size/mode
каждогоZIP и manifest, fsync каждого inode после final0440mode (предпочтительно
mode до finalfilefsync/hardlink), затем fsync всех необходимых directory links,
включая sibling blobs и newly created root chain. Existing/replay повторяет
синхронизацию после failed предыдущей попытки. Linux ошибки распространяются
до RETAINED/audit; orphan/temp после failure допустимы внутри quota, но не
являются successful receipt. Других замечаний в полном пути mkdir→write→mode→
filefsync→link→dirfsync→manifest→replay→audit не выявлено. Это гарантии OS fsync,
не абсолютная гарантия при hardware failure. Полный список передан Sol/root
одним contract; финальный review проверит этот набор целиком.

Финальный consolidated review PASS: Linux fchmod0440 выполняется до filefsync
и hardlink; existing files/replay повторно fsync manifest и каждыйZIP inode;
blobs sibling chain и rejected/identity/root chain синхронизируются до RETAINED.
Linux ошибки остаются failclosed. Все перечисленные review blockers закрыты.
Sol сообщил17/17isolated Linux tests, включая blob-directory failure→retry и
mode/fsync ordering; Ruff/mypyPASS. Root до последнего delta сообщил74unit/20PG;
итоговые final gates77Linux+20isolatedPGPASS. Parser/index conflict guards неизменны.

## Deployment и retained proof

Root подтвердил deployment06:07UTC: backups, API/worker build, host18/API6
hashmatch, schema20261003_05unchanged. Health200, anonymous401, no-store,
markersfalse. Полный actual retained5ZIP прогнан offline через hook:
RETAINED/auditRECORDED,1audit event; replay0filewrites,0index/checkpoint/attempt
delta,0sourcecalls. Исторические8FAILED не изменены; source guard остаётся FAILED.

ManifestSHA:
`62532f02f3021f6078de78bc7cd86cc7a323fac4af9426c6f77fffba872c8a2e`.
Proof `/var/lib/eis-browser/research/rejected/s175-retained-proof.json`, SHA:
`3a7de5da9c6a495e358a1effd47e7c13abf0703d493415a00fae3d27e7998c13`.
Это сохранение evidence, не admission конфликтующих notices и не разрешение
выбрать поздний XML. Official variant semantics и retention lifecycle остаются
отдельными незавершёнными решениями; whole coverage/freshness UNKNOWN.
