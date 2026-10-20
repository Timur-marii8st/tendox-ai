# S195 — повторная проверка недавних пустых ответов ЕИС

Статус: DEPLOYED / VERIFIED BOUNDED SELECTOR AND RECHECK. Owner root, 2026-10-05.
Контракт — [ADR0076](../../adr/0076-eis-recent-no-data-rechecks.md).

Проблема подтверждена read-only snapshot:1148 недавних NO_DATA уже старше24h,
но прежний selector60 выбирает0. Всего1807recentNO_DATA, oldest dueSep29.
Это окна region/date/type, не число пропущенных закупок.

Изменение: внутри прежних12repair slots для L60 до3 старейших пустых ответов,
затем до9FAILED; unused empty slots возвращаются FAILED. Остальные source budgets
и source-safe policies сохраняются. Квота действует на segment; strict60totalbudget
S194 parent включает все повторы. NO_DATA остаётся UNKNOWN и не означает полный ЕИС.

Каждое окно должно иметь latest NO_DATA/sourceSHA, быть запланированным в той же
компании, старше24h, относиться к последним7завершённым MSK датам и не иметь
canonical receipt. Повторный пустой ответ заново включает24h cooldown.
Новый положительный ответ проверяется через intake receipt и searchable projection.

## Проверки

53tests PASS08:54:16UTC:27unit/26PostgreSQL, отдельнаяtestDB удалена,
source credentials removed from pytest environment, production schemaunchanged.
Ruff/mypyPASS. Гейты проверяют latest-first/tieUUID, tenant isolation, отсутствие
канонической загрузки, transport-only не даёт completeness, точную24h границу,
MSK completed dates, malformed dates, read-only выбор, сохранение failure reserve,
daily36new/oldanchor, fallback и малыеL. DB constraints отклоняют NO_DATA без SHA
или с неверным SHA и attempt без planned target.

## Один shadow snapshot

Tenant RR/read-only08:52:32UTC: старая очередь60 —0dueNO_DATA; candidate60 —3.
Dailynew activation отсутствовал: весь latest first-attempt fresh pool уже прошёл
первую проверку. Из исторических непроверенных окон замещены ровно3; общий60limit
не вырос. PG fixture отдельно проверил36new+3NO_DATA+9FAILED+3historicalretry+9old
при активных и достаточных очередях.

SQL elapsed old11.932s/candidate12.046s на этом snapshot. Это background queue
selection, не latency supplier search и не benchmark устойчивой source capacity.
Private `s195-shadow.json` SHA256
`de987ecb5835e80e5b73d8834a0c12d3cc310debbe2b57e5f95fa7fb9a04efa8`.

## Rollout

08:56:53UTC:atomic8files/host28/API2/worker2hashPASS. Pinned one-module overlay
`src/procurement/sources/eis_corpus.py`; dependencies/schema/web/cron unchanged.
API image `sha256:9c3aeb4cec3849dd1ae4cb1e40acab6ecf7835ea1f3445bfb9b1c8a5fe0ba1b9`.
Worker image `sha256:b8e5f797608e29a063a99f0d603674a828aee01d3929a3d709499dbd4ec8baec`.
Rollback tags `vibe-seller-api:s195-base`, `vibe-seller-worker:s195-base` сохраняют
S193 images. Существующий S194 host runner/metrics/leases не менялись.
Code backup `/home/syurai/vibe-seller-state/backups/s195-before-20261005T085646Z-code.tar.gz`
SHA256 `c177db13a4d08e0399b7ddada9aa8c62ff8baee96170c56191167819dec4fd26`.

## Actual ordinary cron evidence

Предварительный snapshot08:56:47UTC сохраняет1148duekeys, exact previous attempt
ID/time/sourceSHA для последующего сравнения. Не сохраняет XML/URL/token в summary.
Private `s195-before-d6a75224-0c01-4762-9511-5b465628086f.json` SHA256
`449f1c4a616aaa5cd0507e34b49c5bb78ca6225aee99e739732f5ed79e976860`.

После09:00ordinarycron:

| Snapshot UTC | Rechecked due windows | Повтор NO_DATA | Новый cooldown | Canonical | Новые версии/index/events |
|---|---:|---:|---:|---:|---|
| 09:01:30 | 3 | 3 | 3 | 0 | 0/0/0 |
| 09:04:16 | 6 | 6 | 6 | 0 | 0/0/0 |

Snapshots cumulative — **не складывать3+6**. Поздний snapshot включает первый.
Два segments одного parent могут выбрать3+3 rechecks; per-segment reservation не
заменяет строгий total60window parent budget. Parent ещё active в этом snapshot;
его окончание/полный throughput этим evidence не утверждаются.

Все6 — actual actorserver-corpus-worker attempts с новымиIDs/sourceSHA,
after.attempted_at>=before.attempted_at+24h, ровно тежеwindowkeys. Typed report
проверяет последний attempt, источник, canonical absence и projection parity;
read-only tenant RR/statementtimeout30s. Повторный ответ не выдаёт canonical status,
новый24h cooldown начинается с newattempt time; coverage/absenceUNKNOWN.

Private files в `/var/lib/eis-browser/research/rejected/`,0600:

- `s195-recheck-observation-91c8c85c-fd6d-4278-b2d1-671d4a1e2681.json`, SHA256
  `a87254cf18dbcc7f467ee68c47656bae29e185bc37a3deae1a81aa842ebcf5c0`.
- `s195-recheck-observation-ce1e9b78-2b26-441f-ab9c-238cae206664.json`, SHA256
  `b34c998ef99a30543faf346a9598d852dc5497797299ace897b0a751714cdbf7`.

Диагностика:source requests0/DBwrites0; backgroundsource workers продолжают обычный
cron. Данные не загружались на ноутбук. API1GiB/web768MiB/worker2CPU2GiB и
DB100GiB/free>=40GiB gates сохраняются.

NextS196: проверка независимого source evidence и возраста pending rechecks,
включая выход окон из7day reserve. Даже повторяющийся пустой ответ не доказывает
отсутствие закупок по всему ЕИС. Полный охват/реестр регионов/hourlyfreshnessUNKNOWN.

## Final operational seal

09:07:38UTC:host28/API2/worker2hashPASS, source runtime unchanged since53test gate.
Pinned S195 images verified, web image/cron unchanged; HEAD20261004_03/health200,
testDBnone/OOMfalse/API1GiB/web768MiB. DB4049787927bytes, free258790928384bytes.
Priority marker present from ordinary cron; foreign marker не удалялся. Snapshot
не требует останавливать ongoing parent или дожидаться всех60 attempts для
проверки фактически observed6rechecks; terminalparent/throughput здесь UNKNOWN.
Private `s195-operations-proof.json` SHA256
`ac66f846226cc567130975b625547ef7021114d4aaeb655a6571da3ca06aa2dc`.
Finaldocs backup SHA256
`254b0e417b3d25f71b6bbe80af7070bffdb80fb9bbe3130bf0b40811f56d6d70`.
Receipt additions включаются в docs-only seal; runtime hashes frozen.
