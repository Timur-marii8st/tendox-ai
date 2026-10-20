# S206 — ускорение SQL отбора исторических кандидатов

Owner root; Astra independent read-only review. Завершено и установлено2026-10-05.

## Контракт и изменение

Контракт [S205](88-eis-historical-analog-selection.md)/[ADR0085](../../adr/0085-bounded-historical-analog-selection.md)
сохраняется. Первое изменение runtime: удалён цикл повторной проверки
каждого из20кандидатов после SQL selection. Полный `notice_variant_hold_clause`
уже применён к тем же exact refs в одной read-only REPEATABLE READ транзакции.
Его receipt integrity, unresolved same/newer origins и audited projection checks
не используют меняющееся время или внешние файлы. Повторные чтения не меняли gate.

Target assertion сохранён. Candidate hold predicate остаётся до LIMIT21;
budget перед bulk hydration сохранён. Не изменяются query/сортировка/кандидаты,
payload/output/time limits, provenance, PASS/FAIL/UNKNOWN, schema или source calls.
20holdqueries +20SET LOCAL удаляются; первоначально52→12SQL при20кандидатах.
Измеренная скорость относится только к приведённым сохранённым запросам;
нагрузочная ёмкость не подтверждена.

## Acceptance и проверка

Полный отчёт при fixed checked_at должен совпадать с immutable S205 reader,
SHA256 `b94a0c850223006787457bad239f7bb77fa0ae2dd06e584f179839f4810be84b`.
Это исторический release artifact, не альтернативная production реализация.
В тестах baseline поступает через явный gate-only path с проверкой SHA.

Отдельно проверить same/newer/older evidence, incomplete tenant receipt,
valid projection, append-only changed origin и invalid audit decision at insert,
RLS и one read-only REPEATABLE READ snapshot. Synthetic fault inserts разрешены
только в disposable `procurement_eis_test_20261005_s206`; owner UPDATE/trigger
disable не используются. Existing S205 gates сохраняются.

Реальные прогоны: те же3paper exact refs/позиция1/queryбумага/lookback365,
первые и повторные HTTP/direct reads, SQL counts/durations, identical baseline
reports при одном checked_at. Отдельные прогоны не доказывают nationwide SLA,
freshness/full coverage, technical/delivery comparability или profit.

После проверки — pinned single-module API/worker overlay под dispatch leases,
host/API/worker/web hashes, health/schema/DBfree/memory/cron/source budgets.
UI этой итерацией не добавляется. Следующий S207 — выбор позиции и объяснения
исторических кандидатов в карточке.

## Gate evidence

Isolated Linux/PostgreSQL gate2026-10-05T18:56:46Z:208PASS in21.96s,
zero skipped; disposable DB removed. Includes193S205 gates,8new analog hold/
identity/isolation/count cases and7existing source hold regressions.
Standalone20candidate reports exactly identical to baseline, initially52→12SQL.
Scoped Ruff/mypy PASS; independent Astra review closed, no remaining findings.
Test fixtures guarded both DB URLs before migrations; no owner updates or
trigger changes.

Initial rollout18:59:04UTC: atomic7/host84/API18/worker18hashPASS.
Six installed reads19:00:36UTC had exact baseline/new same-snapshot equality and
HTTP/direct equality, but HTTP remained3121–3427ms. Redundant SQL removal alone
gave only a small measured improvement. Initial proof `s206-paper-live-proof.json`,
SHA256 `bd64246fe1715e9a281ed87d371e376ae15c4248e4920713d0a7da354fb88b20`.

## Refinement from query plan

Bounded read-only EXPLAIN19:02:31UTC of the actual captured selector:
JITon3036.571ms/JIToff1888.330ms; planning51.5ms each. JIT160functions cost
1150.298ms. Same plan53nodes; scan182596notice rows, with47633surviving that node
and859reaching sort. No SQL parameters/source contents retained in proof.
VPS `s206-selector-explain.json`, SHA256
`9cbcbcffff7bad4f19e0b90eb1cf699665b93f1872ffb5e7770f44d0a6e93f7c`.

Add `SET LOCAL jit='off'` only in this existing read-only transaction. No global
DB setting, schema/index, policy, query/filter or persisted-object change.
Net52→13SQL (40removed,1setup added). Snapshot regression verifies old default,
new transaction off, subsequent transaction default restored, reports identical.
Remaining wide scan/index/prefilter strategy needs a separate measured slice.
First/repeat are chronological calls in a warmed system, not cold-cache trials.
Final gate19:05:15UTC:208PASS in22.18s; independent Astra review closed.
Final installed measurements below.

## Final installed evidence

Final deploy2026-10-05T19:15:01Z: atomic7files/host84/API18/worker18hashes PASS;
health200, schema20261005_01 unchanged. Single-module overlay from pinned initial
S206 image; gate19:05:15UTC208PASS in22.18s, scoped Ruff/mypy/Astra review PASS.
No new dependencies, tables/indexes, source/cron budgets or global DB setting.

Installed source0 proof19:16:57UTC, three same paper refs/position1/queryбумага:

| Target | HTTP first / repeat ms | S205 baseline direct first / repeat ms | Optimized direct first / repeat ms |
| --- | ---: | ---: | ---: |
| 0373100108126000488 | 2167 / 2015 | 3976 / 3254 | 1942 / 1927 |
| 0373100015026000007 | 1994 / 1998 | 3375 / 3307 | 1947 / 1942 |
| 0348200080326000021 | 1977 / 2016 | 3299 / 3299 | 1930 / 1956 |

All six complete baseline/optimized reports identical at the same checked_at,
within one read-only REPEATABLE READ snapshot. All HTTP reports match that
snapshot too. Median paired body latency3303→1942ms (about41% lower), within
this warmed six-call sample. Direct metrics exclude the shared outer transaction
setup and two diagnostic SHOW calls: baseline51/optimized12body SQL; standalone
gate includes tenant set_config,52→13SQL. No SQL text/parameters retained.
HTTP200/no-store, every criterion identifies both XML sources, any FAIL excludes.
Each response20notices/82positions, all truncated=true; excluded/review82/0,
81/1,81/1 unchanged. Coverage/technical/delivery/profit/participation UNKNOWN.
No competitor count, confirmed analogy or nationwide latency claim.

VPS-only proof directory `/var/lib/eis-browser/research/rejected`, files0600:

- `s206-final-paper-live-proof.json`, SHA256
  `7b9f0bf4869ba02ed09884ea8097017112df6149aedb0bb016cb8c176aee0f71`.
- Six raw reports `s206-final-paper-report-{1,2,3}-{first,repeat}.json`;
  exact SHA256 recorded in the proof manifest. No archives downloaded to laptop.
- `s206-final-operations-proof.json`, SHA256
  `addb646e7e2ded0754591b0c1e98cf2c9d1f47c9f77e711005ba7f451aa4d51b`.

Ops19:16:58UTC: DB4971232279/free257516175360bytes, testDB0/head01/health200,
priority/223markersfalse. Read-only/source_requests0/DBwrites0. API1GiB/web768MiB/
worker2CPU2GiB, cron SHA
`012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f` unchanged.

Image pins:

- API `sha256:b4dc7954e64648ba58e551a22a2cd63fd9623bf3008bcb9daa6466bbbe329691`.
- Worker `sha256:a9fccb839a20f8ae54c7ecdae7967539355e9dcc4f8b8bb2e92c299980bb74ba`.
- Web unchanged S204 `sha256:861e3e8f348d1d74f0d20d1f07cc3cda83798465dd13af8a8efe67e458ddf359`.

Final rollback backup
`/home/syurai/vibe-seller-state/backups/s206-before-20261005T191455Z-code.tar.gz`,
SHA256 `2588e5b0355bf08beded519415fb6f0745cb29b8123537c9d186b82ce7f4f728`.
Initial rollout backup SHA256
`76510b6cf4ef660a1e49c0c13849e879bb867b654223c233cbdf3bf15f6661b9`.
No schema downgrade required. Documentation seal19:18:24UTC:
atomic5docs/host84/API18/worker18/web9hashes PASS; image/cron pins/resources PASS,
API/web running/OOMfalse. Seal backup SHA256
`56ce4b2d74f10b2a0d3caabf4f771f2e6a49a38de603e6335f47179ebd0efa7d`.

## Следующие срезы

S207 remains UI: select source position, request historical candidates on demand,
explain every exclusion with provenance and show truncation/UNKNOWN fields.
S208 performance hypothesis (Astra read-only advisory): separate lexical identity
prefilter into disjoint overlap and missing-derivation branches with UNION ALL,
then apply unchanged family/date/latest/complete holds/order/LIMIT21. Neither
branch gets an early LIMIT. Missing/empty derivation semantics must be preserved.
Potential GIN use and lower subplan loops are hypotheses; verify fixed-time full
reports/RLS/holds/ties, actual plans/buffers/first-repeat timing before adoption.
