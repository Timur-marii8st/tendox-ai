# S208 — измеренный лексический prefilter исторических кандидатов

Статус: завершён и установлен2026-10-05, owner root; Astra независимый read-only
review. Контракт [S205](88-eis-historical-analog-selection.md), baseline
[S206](89-eis-analog-query-performance.md), установленный [UI S207](90-eis-analog-candidates-ui.md).

## Изменение и acceptance

Две непересекающиеся ветви identities: строки lexical keys с пересечением
запроса и карточки без строки derivation. UNION ALL без раннего LIMIT.
Пустые и непересекающиеся сохранённые keys не считаются отсутствующими.
Complete family/date/deadline/latest/source-hold predicates, сортировка и LIMIT21,
payload/time/output budgets и read-only REPEATABLE READ сохраняются.
Никаких новых индексов/схемы, глобальных DB settings, source calls/jobs/writes.

Immutable S206 reader SHA256
`12e41b09bf4c415549aaef265543d615b4f614d8a901f7bd707c36ebc52fc0b5`.
Только release artifact для gate, не дополнительный production путь.
Требуются полная идентичность отчётов при одном времени/snapshot, негативные
missing/empty/foreign keys, latest/ties/history-before-limit/holds/RLS/bounds
и реальные EXPLAIN buffers/loops + same-ref first/repeat HTTP/direct timings.
Индекс GIN и предполагаемое ускорение должны подтверждаться замерами до deploy.

## Evidence

216 isolated Linux/PG tests PASS24.81s/zero skips; 27 local unit/API tests,
scoped Ruff/mypy PASS. Astra review закрыт. Новые8cases: missing/empty/custom
keys, tenant/RLS, latest cross-branches, history-before-limit для обеих ветвей,
ties/truncation, period boundaries/missingtarget и missing-derivation same/newer
holds. Derivations append-only: fixtures создают версии без ключей через scoped
ingestion hook и при необходимости вставляют empty/custom keys один раз под
обычной tenant runtime role. Owner UPDATE/DELETE или trigger bypass не применяются.
Gate log SHA256 `67cffd2cfe86d5a30811bac6711be4e85957eea2cd74c9f562cefafed7fed4ab`.

Initial source0/read-only proof20:19:18UTC:3full reports identical; baseline
2260/2047/2068ms vs candidate1683/1597/1597ms in one snapshot/time.
EXPLAIN selector1950.147→1533.970ms, planning52.594/53.021ms.
Original notice scan186898physical rows and main hold-subplan49031loops;
candidate PK probes3583 and hold938loops. Root shared hit blocks467227→122449,
read blocks39540→20056. Temporary read/write blocks5692/12065 unchanged.
GIN use **не наблюдался**; measured improvement is narrower notice/hold work,
а не доказанный эффект lexical GIN. SQL LIMIT не ограничивает полный DB scan.
Proof0600 `/var/lib/eis-browser/research/rejected/s208-initial-selector-proof.json`,
SHA256 `9311a1f672157cbfbafe344e6402b96a757c848af8f3d9cd68d459cc36f88cf4`.

Controlled deploy20:25:42UTC: atomic8/host92/API18/worker18hashes PASS,
health200/head20261005_01. Single storage module overlay, no schema change.

Image pins:

- API `sha256:0436f940aecda731ac1167d2a2a4934e3b81397bb4d40edd206b909bbd3adee9`.
- Worker `sha256:40cc367b477ec6591bc949f3960b37ba7a972398d7ca1f5bf32764922be0233e`.
- Web unchanged S207 `sha256:fe9b6a171709f6c72f9142cf63c00bf6e16aa20c77c61f65a1ddc01b6d6be806`.

Rollback backup
`/home/syurai/vibe-seller-state/backups/s208-before-20261005T202536Z-code.tar.gz`,
SHA256 `23f32df1a56a38e7ad5e4fe502f6bf8eed07025593fc0ae184d5a6dbe73d7213`.

Installed20:27:02UTC same3paper exact refs/position1/queryбумага/lookback365:

| Target | HTTP first/repeat ms | S206 direct first/repeat ms | S208 direct first/repeat ms |
| --- | ---: | ---: | ---: |
| 0373100108126000488 | 1744/1662 | 2184/2119 | 1626/1622 |
| 0373100015026000007 | 1619/1612 | 2187/2107 | 1708/1616 |
| 0348200080326000021 | 1614/1644 | 2124/2085 | 1628/1618 |

Balanced measurement order: baseline first in first runs, optimized first in repeat.
All six complete reports identical at one checked_at/snapshot and HTTP/direct
equality. Paired median2122→1624ms (~23.5% lower), standalone13SQL unchanged.
20notices/82positions/truncated each; excluded/review82/0,81/1,81/1 unchanged.
Coverage/technical/delivery/profit/participation UNKNOWN; warmed samples, not
cold-cache trials, nationwide response time or load-capacity guarantee.

Installed Next Action+production SSR regression20:27:14UTC:6same-paper reads
1545–2011ms, changed position2/period30 227ms,8negative requests PASS.
No browser visual check; source0/DBwrites0.

Private proof0600 (only VPS, archives/reports not copied to laptop):

- `/var/lib/eis-browser/research/rejected/s208-final-paper-live-proof.json`, SHA256
  `cde1ebaa81f4ddc4909699839c50d7417a221bd7bf4060a06626626db634835c`.
- Six `s208-final-paper-report-{1,2,3}-{first,repeat}.json`, SHA recorded in proof.
- `/home/syurai/vibe-seller-state/s208-web-regression-proof.json`, SHA256
  `41641d5bbe8ba68e672174d0a1f5ada2b074094086018de42337a20b56093928`.
- `/var/lib/eis-browser/research/rejected/s208-final-operations-proof.json`, SHA256
  `0843978a3a680a1219918539e8d1f3733ab854326fa9f27cbc0301e6d27877f3`.

Ops20:27:15UTC: DB5050481687/free257335136256bytes/testDB0/head01/health200,
API/web running/OOMfalse, API1GiB/web768MiB/worker2CPU2GiB.
Priority marker=true — ordinary lane activity; 223marker=false. Cron SHA256
`012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f` unchanged.

Next S209: optional exact scope for resolution decisions and their audit batches,
initially only analog reads. Scope includes all pre-limit eligible notices and
every relevant same/newer variant/origin pair, independent of those origins'
publication dates. Keep full array-length/JSON equality/canonical/transport/all
origin and variant checks; receipt integrity stays tenant-wide. Existing unscoped
consumers unchanged. Spill reduction must be measured against immutable S208.

Docs seal20:28:53UTC: atomic5/host92/API18/worker18/web14hashes PASS;
image/cron pins/resources PASS, API/web running/OOMfalse. Seal backup SHA256
`12556dfc1bc767eb6bed5c1abb3426e41de64c73a91cf81d8983b8ad450c0d68`.
