# S171: отдельные лоты — план реализации и high-risk review

Статус: **DEPLOYED**, S171, HEAD `20261003_03`,2026-10-03.
Code review и test gates PASS; root подтвердил backups/build/health.
Реальное lot event не получено: два bounded окна region50 дали NO_DATA.
Развёрнут UNKNOWN-only evidence contract, не подтверждённый lot availability gate.
Owner документации:Astra; owned только docs/53 и ADR0054. Runtime owners и
owned files root фиксирует в docs/15 до code mutation. Зависимости:S170,
docs/50, research docs/52 и [draft ADR0054](../../adr/0054-eis-223-lot-cancellation-evidence.md).

## M1 — закрыть identity contract

Research подтверждает qualified paths и смысл eventGUID/lotGUID/ordinal,
COMMON/VARIOUS, date vs datetime, версии лотов и доступные real samples.
До источника, доказывающего соответствие, не включать confirmed lot cancellation.
GUID annotation из docs50 недостаточна; scalar equality сама по себе не legal
mapping. Отдельно проверить legacy AES/ZK notices без сохранённого lot.guid.

Acceptance: документирован exact mapping либо явный UNKNOWN-only mapping scope;
определены случаи MATCH/DISJOINT/UNKNOWN и scope hold. Решение фиксируется ADR
перед runtime admission, без inventing отсутствующего источника.

Решение M1: текущий S171 — UNKNOWN-only association. Любой связанный lot event
создаёт selected-lot review hold, никогда application FAIL; отсутствие события
UNKNOWN без event hold. Apparent GUID+ordinal mapping сохраняется как evidence,
но не освобождает apparent unrelated lot от hold. Даже совпадение обоих полей,
purchase GUID, dual XSD PASS и aware chronology не исключает неполученную
промежуточную notice revision. DISJOINT/no-hold требует отдельного official
stable identity/revision contract. Это ограниченный срез видимости событий и
защиты операций, не завершённый gate доступности отдельного лота.

## M2 — bounded reader и immutable source variants

Новый explicit parser/event model, strict source identity и все cancelled lot
references, никакого note version/status inference. Отдельные event windows/
archive sources/variants/quality/attempts, reuse tenant SHA blob store допустим.
Полный returned set атомарен. Не расширять whole-event parser literal и не
создавать fake notice версии ради shared schema-check key.

Tests: roots/namespaces/direct number, packet/event/targetGUID различаются,
missing/duplicate identity, jointLot, COMMON/VARIOUS branches, optional fields,
date-only/raw timezone, archive/target limits и duplicate members. Все новые
fixtures synthetic; real bytes на VPS. Exact XSD quality отдельно от typed
source projection и lot identity confidence.

PG: tenant sameGUID/crossnumber variants, sameSHA replay/no audit, immutable
history, source/quality FK, event-before-notice, unsafe whole-window rollback,
guarded downgrade. No last-write-wins или automatically restored current state.

## M3 — per-lot resolver и consumers одним vertical slice

Читать exact notice + all relevant bounded variants/quality одним snapshot.
Per-number GUID one-hop и per-lot limits; overflow UNKNOWN+hold. Вывод содержит
реальный source ordinal/GUID и selected index отдельно, reason/evidence refs.
Проверить ordinal7/index1, reorder, missing GUID, duplicate ordinal, conflicting
GUID/ordinal, sameGUIDcrossnumber, proven unrelated lot, ambiguous scope.

Purchase-wide blockers и selected-lot blockers раздельны. Source estimate
проверяет выбранный лот; comparison/search не объявляют whole FAIL из одного
cancelled lot. Shared row today используется estimate целиком, поэтому document
hold нельзя добавить туда без отделения поля и проверки всех consumers.

Notice-wide document collection может получить отдельный scope hold, если
принадлежность manifest лотам неизвестна. Pending selector и queue capacity
должны пропускать held jobs, worker повторяет gate под company lock. Known
unrelated selected lot не наследует этот document-only hold в preliminary
economics. Whole rejection всегда сохраняет прежний higher-priority hold.

Tests S171: apparent target lotA + apparent other lotB → оба UNKNOWN review hold,
ни один не получает false cancellation FAIL; no-event → UNKNOWN/no event hold;
ambiguous target → UNKNOWN hold; existing queued job receives event →
no downloader/retry waste; source estimate BLOCKED/no scenarios только в
применимом scope; cached reads/audit counts unchanged, no snapshot races.

Future mapping acceptance (не S171): доказанно disjoint lotB не наследует
document-only hold. До такого evidence нельзя включать этот runtime shortcut.

## M4 — source proof и rollout

Только после gates root выбирает одно bounded region50/day/event-family окно,
общие lock/quota/memory/disk bounds прежние. READY → все returned members;
NO_DATA остаётся observation, не proof parser или отсутствия отмен лотов.
Если получен event с известным notice, сопоставить source GUID/ordinal/live
reference и получить решение research об identity policy; иначе связь UNKNOWN.

Перед deploy: focused/PG/security/type/web gates и независимый review; code/
schema backups, guarded migration, равенство server/image source, health.
После deploy: raw/schema/source-state proof, replay/no mutation, API/UI scope
labels. Статус DEPLOYED не означает доказанный current lot eligibility,
полнотуЕИС или восстановление процедуры. Глубокие файлы/парсинг остаются на VPS.

## Риски, уже выявленные чтением S170 consumers

- `get_source_estimate` копирует row223.blocking_reasons для любого lot_index:
  необходимо разделение scope, иначе notice document hold загрязняет все лоты.
- Старый search `matched_lot_ordinal` — только hint morphology, не unique key:
  нельзя привязывать cancellation по этому hint без exact snapshot lot selection.
- `_PENDING` текущих jobs имеет только purchase-level fields: per-lot document
  permission из этого SQL не следует; conservative document-only hold должен
  быть явным продуктовым состоянием.
- Устаревшие AES/ZK snapshots не имеют GUID extension; immutable raw-derived
  projection — отдельный срез, нельзя подставить GUID из номера/ordinal.

На этапе M1 архитектурный review опирался на текущий код/исследование docs50.
Source requests, runtime edits, migrations и production writes выполнял root;
эта архитектурная задача ограничена read-only review и owned documentation.

## M2 — независимое чтение реализации, 2026-10-03

Проверены policy/resolver, storage variants, пять таблиц и migration20261003_03,
shared document/comparison/estimate/search, queue, refresh и offline quality.
UNKNOWN-only соблюдён: source schema PASS отдельно, apparent mapping не снимает
hold; source estimate добавляет selected reasons и сохраняет прочие blockers.
Immutable PK/FK tenant-scoped, FORCE RLS/insert-select permissions, downgrade
guard, one-hop GUID lookup и replay согласованы с ADR. Document receipt повторно
проверяет gate под company lock; event importer берёт eis223:company → company.
Queue исключает связанное lot event и при dispatch, и в pending capacity.

Выявленные границы:

1. Overflow resolver первоначально не возвращал IDENTITY_UNRESOLVED; selected
   projection validator выдавал ошибку вместо UNKNOWN hold. Owner исправил
   overflow reasons; исправление прочитано. Regression gate подтверждает root.
2. `storage/eis_223_lot_events.py` первоначально выбирал full snapshots до
   per-number overflow и без byte budget. Cap2000 при XML до4MiB не является
   приемлемым memory budget. До широкого intake нужен server-side bounded
   metadata/byte preflight, превышение даёт UNKNOWN hold до передачи snapshots.
   Owner добавил bounded metadata query с octet_length(snapshot::text), cap2000,
   cap100 variants/number и8MiB JSON budget до SELECT(snapshot). Превышение
   возвращает whole-batch UNKNOWN hold. Исправление прочитано; production
   callers используют consistent read либо company lock, поэтому между
   preflight и загрузкой нельзя добавить lot variant в их snapshot. Добавлены
   policy overflow projections и PG byte-budget regression; запуск PG gate
   подтверждает root отдельно.

Повторное code review после этих двух исправлений: открытых блокирующих
замечаний не осталось. Exact quality SQL ограничен tenant/GUID/SHA/current
validator; DB constraints фиксируют обе разрешённые schema trees/package/root.
Schema PASS не меняет UNKNOWN-only application policy. По сообщению root
10policytests PASS; итоговые isolated PG и live proof приведены ниже.

Новые live events, полнота источника и стабильная связь с версиями лотов остаются
UNKNOWN. Code review само по себе не является deployment proof.

## Итоговые gates и deployment evidence

По результатам root: isolated PG84PASS (prior75+new9), focused Linux454PASS,
local438PASS/16skip, mypy10/RuffPASS, webbuild/ESLintPASS. Deployment:
HEAD20261003_03, backups, container build и health подтверждены; финальную
сверку server/image hashes ведёт root в operational docs.

Все нижеприведённые артефакты переданы root; в этой архитектурной задаче
повторные source calls/DB writes не выполнялись.

| Proof | Результат | SHA256 |
|---|---|---|
| `s171-synthetic-schema-proof-20261003T120402Z.json` | pinned full16.2+16.3 PASS; UNKNOWN hold;0writes/source calls | `9e226dc2d0b9c145205ac1a4544bff94298a2d1cf181a821f6c5593d535d77fc` |
| `s171-live-proof-20261003T120404Z.json` | region50 purchaseLotCancellation2026-10-02 NO_DATA,3.552s | `b3539abcf0a6c80d3c2716a4c17d599ce6199e4984ee2eb0da2a124ee35017b6` |
| `s171-live-proof-20261003T120510Z.json` | region50 purchaseLotCancellation2026-10-01 NO_DATA,3.614s | `364550e03e433f17f696324b3f007f92db826e09a81c5f4f2711990c0c47e075` |
| `s171-api-proof-20261003T120515Z.json` | comparison/document/search/source estimate typed cached UNKNOWN; read-only, no source calls | `192e6c58929ee3f5c033cfb599f3f2e8d83a59c15eef0705033f69f792f8fa23` |

Search sample41ms — один замер, не SLA. Browser проверен на существующей
карточке32615966906: новый блок no-event UNKNOWN, screenshot
`data/research/eis-documents-2026-10-02/s171-lot-cancellation-ui.jpg`.
Это UI proof отсутствия локального evidence у карточки, не proof реальной
отмены/неотмены. Ни NO_DATA, ни synthetic XSD PASS не подтверждают stable lot
GUID semantics, real event admission или полноту по регионам/датам/семействам.
