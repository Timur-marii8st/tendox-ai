# ADR-0063 — explicit retained variant projection

Статус: **ACCEPTED / OPERATOR M1 DEPLOYED AND VERIFIED**.
Дата: 2026-10-04, S180 M1. Owner ADR: Astra; models/migration/hold/checkpoint
readers/PG: root; projection writer: Sol; bounded offline parser: source agent.

## Решение и scope

Выполнить один explicit operator slice над exact retained evidence, без live
source hook. Сохранить complete transport и отдельно принять immutable decision
для каждой purchase number/version. Не выбирать winner divergent pair и не
объявлять subset обычным SYNCED window. Старые 8 FAILED и pending source gap
остаются; application/eligibility PASS автоматически не возникает.

## Alternate provenance

Добавить immutable `eis_feed_windows.intake_kind`:
`LEGACY_CANONICAL` по умолчанию для прежних путей, `VARIANT_TRANSPORT` для нового.
Transport parent содержит все 5 ZIP и все 499 XML members, archive/source
bindings и полные counts. Raw ZIP копируются в DB целиком с bounded window
compressed cap 64 MiB; notebook не получает bulk corpus.

Existing canonical notice → archive FK сохраняется. Это обеспечивает exact
XML/member provenance для проектируемых строк без искусственного subset parent.
Transport record_count отражает все members; projected/replayed/held counts
находятся отдельно в projection batch. Complete transport не равен complete
canonical admission.

**Все** читатели completion/checkpoint/coverage/freshness/claim/skip/retry из
`eis_feed_windows` исключают VARIANT_TRANSPORT. Это обязательный exhaustive
audit gate, включая `has_ingested_window`, journals и index coverage. Наличие
transport parent не завершает прежний canonical target.

## Batch и decisions

Две новые immutable tenant tables: batch с exact audited ledger receipt и
full transport window FK; decisions для всех 498 semantic pairs. Batch связывает
retention manifest, diagnosis, ledger receipt, ordered archive SHAs, parser
identity, counts и audit. Каждый decision содержит input variant-set digest,
typed parsed snapshot или HOLD с reason/provenance. Deterministic identities
и exact immutable payload comparison обеспечивают replay без новых writes.

Проекция допустима только при known source identity, полном успешном parser
и ровно одном distinct `(document_type, XML SHA)` для pair во всей tenant
ledger history. Кандидатов максимум 497 по retained inventory; реальный census
может удержать больше. Existing canonical different SHA означает HOLD без
overwrite. Same SHA допускает явный replay decision; существующий canonical
origin другого window/archive не переписывается.

Весь bounded batch — одна transaction под tenant → ledger lock: full archive
set, decisions всех pairs, новые canonical rows/search keys и audit. Ошибка
binding/resource/parser/inventory не допускает тихого пропуска member.
Доменный HOLD учитывается как явный decision, не как скрытый parse success.

## Discharge shared hold

S179 hold снимается только exact explicit projection decision, когда selected
canonical SHA совпадает и текущая global pair history по-прежнему singleton.
Для каждого same-or-newer ledger pair требуется собственное подтверждённое
разрешение; unresolved newer version продолжает удерживать выбранную older.
Новый другой SHA/type, orphan origin или receipt integrity error автоматически
возвращает hold. Numeric version, filename, timestamps и latest decision сами
по себе не разрешают конфликт. Старые S178 NOT_ENABLED receipts неизменны.

Решение разрешает source projection, но не supplier eligibility, complete КП,
действительный deadline или участие. Все прочие hard gates сохраняются.

## Migration и gates

Frozen migration сохраняет RLS/FORCE, tenant composite FKs и immutability.
Global downgrade guard с row_security off отклоняет rollback при любом
VARIANT_TRANSPORT, batch или decision history до удаления schema objects;
невозможность видеть все tenants означает отказ.

Required proofs: all499/full5ZIP и decisions всех498 pairs; exact divergent
pair HOLD; singleton eligibility census; conflict existing canonical SHA;
replay0writes; later variant reholds search/document/cache/estimate paths;
tenant/RLS/immutable/global downgrade; atomic late failure rollback;
полный fetch-free retained parse→projection memory gate; source calls0.
Отдельно доказать отсутствие обычных checkpoint/SYNCED/completion deltas и
неизменность 8 FAILED. Production rollout и полнота ЕИС пока не заявлены.

## Bounded review

Все восемь completion/replay reader sites проверены: has-ingested, legacy
ingest replay, journal, два corpus selectors, freshness и два index coverage
queries. Transport исключён из checkpoints; legacy replay явно отклоняет его.
Writer повторно валидирует полный audited inventory под tenant → ledger lock,
фиксирует transport/decisions/canonical/search keys/audit атомарно и сохраняет
canonical conflicts как HOLD. Frozen downgrade guard покрывает transport,
batch и decision history всех tenants.

Исправлены три review gaps: discharge проверяет membership объекта из всех
decision columns в exact batch audit JSONB; migration проверяет definition и
validated status существующего intake-kind CHECK; receipt metadata cap не
создаёт ложный INTEGRITY_ERROR для уже resolved SQL NO_HOLD.
Повторный code review пройден. Full retained performance gate обязателен:
JSONB membership включает snapshots и может повторно просматривать большой
audit на каждую pair; прежнее metadata-only timing сюда не переносится.

## Измеренное уточнение snapshot caps

Принято до deployment migration03: aggregate snapshots считаются по compact
UTF-8 JSON, cap остаётся **16 MiB**. Прежний ASCII-escaped serialization давал
ложный resource refusal относительно выбранной UTF-8 метрики. Cap одной
snapshot явно увеличен **1 → 2 MiB**; frozen SQL CHECK до rollout изменён на
2,097,152 bytes. Это отдельное обоснованное изменение, не снятие resource gate.

Fetch-free census exact 499 members: 497 parsed snapshots + 1 conflict pair.
Compact UTF-8 total 13,002,894 bytes против ASCII 17,192,234; maximum UTF-8
snapshot 1,152,449 bytes против ASCII 1,393,220; одна snapshot больше 1 MiB.
Измерение root: 8.658 s, peak 228,069,376 bytes при прежних 2 GiB. Это census,
а не завершённый full transaction/performance gate.

Writer batch audit cap **24 MiB** и ZIP caps **64 MiB compressed / 128 MiB
expanded** неизменны. Serialize metric должна быть явной в parser/writer;
PostgreSQL `snapshot::text` может добавлять пробелы относительно compact JSON,
поэтому реальная запись и DB CHECK остаются обязательным gate. Полный
498-pair projection/replay/hold-query performance подтверждён ниже; source fetch0.

## Retained performance gate и оптимизация

Первый full retained projection прошёл: 497 singleton projections и одна held
pair; replay без writes, peak 582,463,488 bytes / 2 GiB. Но повторный audit
JSONB membership на каждой pair дал paper/server около 56.5/59 s даже на
492 current records. Rollout был отложен. Baseline proof
`/var/lib/eis-browser/research/rejected/s180-isolated-proof.json`, SHA-256
`16aa9f15883c855a0e1271428ac6856b8bb0cbb4687d3301f302d05ddd68f100`.

Приняты два statement-local MATERIALIZED CTE: сначала tenant-filtered exact
audited decision array раскрывается один раз, затем все canonical/origin/global
variant checks и exact full-decision JSON equality формируют DISTINCT resolved
pairs один раз. Обе hold branches используют одну relation. Malformed audit
array не раскрывается и не снимает hold. Это не persisted cache: новый variant
пересчитывает разрешение при следующем snapshot. Политика выбора не меняется.

Optimized proof 10:35:46 UTC на **492 current records**: paper 812.41 ms /
11 matches, server 875.22 ms / 26 matches; selector 351.093 ms, planning
46.955 ms. EXPLAIN: `jsonb_array_elements` loops 1 / 498 rows.
Source calls 0, replay deltas всех 13 таблиц 0, прежние 8 FAILED сохранены,
checkpoint false. Peak 536,924,160 bytes / 2 GiB с resident Chromium.
Proof `/var/lib/eis-browser/research/rejected/s180-isolated-optimized-proof.json`,
SHA-256 `b76e2a74606b8184ebc425f6e4bd469ac804202ad5ca4dfd06e0eca19f3543e8`.

Code review обеих оптимизаций пройден. Эти измерения подтверждают bounded
retained sample, а не nationwide query SLA или scalability произвольной
будущей истории batches.

## Финальный release verdict

Root подтвердил 176 Linux PASS / 68 isolated PG PASS (244 tests), Ruff для
11 runtime / 4 tests и mypy для 9 modules. Финальный exact isolated proof
10:38:24 UTC: 497 PROJECTED / 1 HOLD, все 5 ZIP / 499 XML / 498 decisions;
source calls 0. Ожидаемые новые transport/projection rows отделены от нулевых
ledger/attempt/target deltas; 8 FAILED неизменны, checkpoint false. Replay
всех 13 таблиц — delta 0. Writer 12.879 s / total 29.193 s, peak
583,127,040 bytes / 2 GiB с Chromium. Search на 492 current: 936.03/882.14 ms;
selector 349.207 ms / planning 45.675 ms, array expansion loops1 / 498 rows.

Финальный proof обновил тот же `s180-isolated-optimized-proof.json`, SHA-256
`58e7fb1f215f31076faff93471545f0f1ebbce5156e327e8d7f1271d5fe97786`.
Предыдущий SHA выше относится к предыдущему измерению этого пути.
Release review **PASS** для operator M1; live hook остаётся вне этого slice.

## Production observation

Root подтвердил deployed HEAD `20261004_03`, API/worker hashes 11 PASS,
code/schema backup перед rollout (10:41 UTC). Retained production proof
10:46:19 UTC: 497 PROJECTED / 1 HOLD, all 5 ZIP / 499 XML / 498 decisions.
Replay 13 table deltas 0, source calls 0, прежние 8 FAILED сохранены,
checkpoint false. Exact target проверен SQL: он planned и pending.
Отсутствие target в capped первых 1000 gaps не трактуется как завершение.

Proof `/var/lib/eis-browser/research/rejected/s180-retained-proof.json`, SHA-256
`ba6ff88a151bcfa1e719dbd82126e6396298b155bb261749553137e6b6e17c1b`.
Production current index 128,803; paper 2477 matches / 5814 ms,
server 5232 matches / 12313 ms. Held-current count 0: divergent pair пока не
имеет canonical row, поэтому этот показатель не означает отсутствие конфликтов.
Indexed legacy windows 4929 / pending targets 143196. Peak 539,467,776 bytes /
2 GiB; selector 330.618 ms / planning 50.449 ms; array loops1 / 498 rows.

Эти наблюдения не означают full coverage или query SLA. Production source hook
остаётся выключенным; operator projection не завершил исходный source gap.
Финальный HTTP smoke PASS, 10:46:57 UTC: 44 current 128803, paper 2477 /
5811 ms, server 5232 / 12216 ms; 223 current 2882, paper 59 / 218.47 ms,
server 184 / 573.25 ms. No-store, health 200, anonymous 401, markers false,
source calls 0; coverage/freshness UNKNOWN.
Proof `/var/lib/eis-browser/research/rejected/s180-api-proof.json`, SHA-256
`f22c830afcd3eb0d7b09d7c70c655996560acf246fc5fc9fcc5b9b2e5c88d76c`.
Operator M1 завершён и проверен; live automation остаётся отдельным milestone.
