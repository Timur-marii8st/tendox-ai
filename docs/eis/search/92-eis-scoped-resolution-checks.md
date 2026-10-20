# S209 — точная область live resolution checks

Статус: DEPLOYED AND VERIFIED2026-10-05; owner root, Astra independent read-only review closed.
Контракт [аналогов](88-eis-historical-analog-selection.md), baseline [S208](91-eis-analog-lexical-prefilter.md).

Optional SQL resolution scope применяется только к аналогам. Сначала выбираются
все eligible refs по lexical/latest/family/date/history/self, без LIMIT. Затем
берутся все same/newer retained variant/origin pairs этих номеров, независимо от
дат и receipt. Resolution decisions и audit batches ограничены этими pairs.
Полная длина audit array, exact JSON decision equality, canonical bytes,
transport, exact origin и все conflicting origin/variant checks сохраняются.

Область ограничивает только доказательства разрешения: сами hold existence
checks и tenant-wide incomplete receipt predicate остаются общими. Если scope
пропустил pair, разрешение не подтверждено и hold сохраняется. Default unscoped
consumers прежние. Нет новых source calls/writes/cache/schema/index/dependency.

Immutable gate baseline BOTH modules:

- S208 analog SHA256 `3b43638c735e443423d923a0fbb48a6f4cad56906c7448edb3fb46e7bd64b619`.
- S208 hold SHA256 `b044241cc52de3cc742d13f597060cb76d0268072e78879b0680d6d80e6cf570`.

Baseline analog связывается с замороженными функциями hold, чтобы новая общая
реализация не скрыла регрессию. Проверяются same-time/snapshot full report
identity, shared audit batch/full array, malformed arrays, новые/conflicting
origins из другого receipt и вне периода кандидатов, global incomplete receipt,
RLS, отсутствие writes, limits/default consumer equivalence. Затем measured
CTE rows/temp blocks/HTTP+direct first/repeat перед controlled deploy.

## Evidence

228 isolated PostgreSQL tests PASS30.43s/zero skips;27 focused unit/API tests,
Ruff/mypy PASS. Oracle uses both frozen modules; synthetic malformed audit data
is created through the writer, without UPDATE/DELETE/trigger bypass. Astra
review closed after correcting fault-hook idempotence and unrelated batch member.

Initial same-snapshot3full reports identical. Selector EXPLAIN1495.983→570.830ms;
audit CTE2285→98rows, resolved187→2rows, scope2pairs for885eligible refs.
Temp read6194→3460/write13071→3460blocks. Spill remains; CTE nested times are
inclusive and must not be added. No new index/GIN claim, no resource cap increase.

Deploy20:43:42UTC: atomic11/host95/API19/worker19hashes PASS, schema20261005_01.
Six installed comparisons20:44:34UTC use balanced old/new order and exact fixed
clock/snapshot: every full report and HTTP response identical. Direct baseline
1653/1618,1619/1644,1618/1546ms; optimized731/709,752/730,708/717ms.
Median1618→723.5ms (~55% lower in this warmed saved sample). HTTP712–871ms.
Each20notices/82positions/truncated, review0/1/1 and all UNKNOWN unchanged;
12per-reader SQL in shared transaction/13standalone remain unchanged.

Installed Next Action+production SSR20:44:39UTC:6reads648–821ms;
changed position2/lookback30 225ms,8negative cases PASS. This is not a browser
visual check, full-EIS benchmark or nationwide SLA.

Ops20:44:40UTC DB5051169815/free257312370688bytes/testDB0/health200/head01,
markersfalse. API1GiB/web768MiB/worker2CPU2GiB and source/cron budgets unchanged.
Foreground source_requests0/jobs0/database_writes0. Full source coverage,
freshness, specification/delivery equivalence, profit and participation UNKNOWN.

## Pins and retained proofs

- API `sha256:ca07d077619045298720508a84f6dd7cdb6b16dfbd3b0c1bdf994e90e5773547`.
- Worker `sha256:75533660901bff66663dead7f09018a20a483e7b6023c0f230c9360f3d0f08b7`.
- Web S207 `sha256:fe9b6a171709f6c72f9142cf63c00bf6e16aa20c77c61f65a1ddc01b6d6be806`.
- PG log SHA256 `1c3758c25566f4fce2100be51a5ddc8782ab9efb987a27335c8eba0957d0702e`.
- VPS-only0600 proofdir `/var/lib/eis-browser/research/rejected`:
  `s209-initial-selector-proof.json` SHA256 `e73bc8c64ec466c3821c44f445639dce46971ad30ba2e40fe0d0d93c05d4740c`;
  `s209-final-paper-live-proof.json` SHA256 `5ab66ca4d02b74f6f20b21abce9986ec0be15e7c0a9173172fa4656e3879f20f`;
  `s209-final-operations-proof.json` SHA256 `75340233d97ceb32d99f7090efc77fd2e8706dfbbaeaa065d50ce9965ef5b71f`.
- Six individual `s209-final-paper-report-{1..3}-{first,repeat}.json` SHA values
  are in the live manifest. Raw reports/source archives remain on VPS.
- `/home/syurai/vibe-seller-state/s209-web-regression-proof.json`, SHA256
  `d4903c788a29041b15acfa1e330cd5bc04e9aa158e64b9d71bf3e7840e0910ba`.
- Rollback `/home/syurai/vibe-seller-state/backups/s209-before-20261005T204337Z-code.tar.gz`,
  SHA256 `7532499e641511c7c2745f223fea2c8dc40cd489842e93512e0e29fc1e092f57`.

Next S210: exact selected position-pair observations of retained characteristics,
including source values/differences/UNKNOWN. Do not equate recorded similarity
with complete technical compliance or infer delivery from customer/window region.
