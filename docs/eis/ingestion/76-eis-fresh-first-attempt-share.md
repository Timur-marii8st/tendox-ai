# S193 — первая обработка свежих окон

Статус: DEPLOYED / VERIFIED BOUNDED SELECTION. Owner root, 2026-10-05.
Контракт — [ADR0074](../../adr/0074-eis-fresh-first-attempt-share.md).

Изменение затрагивает только daily selection: квота первых попыток свежих
завершённых дат повышена с40% до60% полного прохода. При limit60 и достаточных
очередях это36new/12recentrepair/3historicalretry/9ordinaryold.
Сначала old anchor и firstnew; затем3new/2other, preserving within-lane order.
При отсутствии retry prefix существующий последовательный fresh block сохраняется;
shadow выявил first6 regression у безусловного чередования, исправлено до rollout.
При early-yield это даёт больше свежих окон в prefix, не обещая полный проход.
Source/lease/cooldown/tenant/canonical/resource/scheduling policy unchanged.
NO_DATA verification остаётся отдельным следующим срезом.

27 unit tests, Ruff/mypy PASS locally. PostgreSQL fairness/RLS/latest/cooldown
gates41PASS07:22:26UTC в отдельной testDB; production schema не менялась.
TestDB удалена trap после проверки, source credentials удалены из pytest environment.
До уточнения conditional prefix первоначальный gate40PASS; релиз использует41PASS.

## Shadow на одном снимке

Tenant RR/read-only snapshot07:21:38UTC: old24fresh/new36fresh из60, first6fresh
5->5, первый old anchor одинаков. При достаточных retry очередях PG fixture
подтвердил36new/12recentrepair/3historicalretry/9ordinaryold, а в first6 —
4new вместо1 при старом retry prefix. Последовательность repair и transient
внутри other сохраняется. Передавать всю свежую очередь вместо истории нельзя.
Реальный shadow: old21Oct4+3Oct1 противnew21Oct4+15Oct1; общий historical
pool36->24. Candidate не выполняет source transport и не меняет БД.
Private `s193-shadow-v2.json` SHA256
`ddb38d9df6b6f95c05dd8eeec1fb11f602a6f676d4b7d79a32205f0a3aa8892a`.
Исходный shadow без conditional prefix сохранён как отвергнутая candidate evidence,
не как доказательство production ускорения.

## Rollout

07:24:16UTC: atomic9files, host25/API2/worker2 hashes PASS. Одна изменённая
runtime module наложена на pinned прежние API/worker images; buildnetworknone,
нет dependency updates. API health200 после restart; web не пересобирался.
Новые image IDs:

- API `sha256:de3b27df071f79f27265b3f537d1068ac488c1a40076abe8b6abb5c8e17466cb`.
- Worker `sha256:37d919e24bef11cdafdbcbc56faf6b8e4828c5cd3e7109c5cb93109120aae02e`.

Pinned rollback tags `vibe-seller-api:s193-base` и `vibe-seller-worker:s193-base`
сохранены. Code backup `/home/syurai/vibe-seller-state/backups/s193-before-20261005T072410Z-code.tar.gz`,
SHA256 `7f7cdf0fc2be88139bbbe5b53040ac459455bc70546cddb5ccd0ff3efca2d753`.
Cron SHA `012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f`
сохранён. Dispatch6/7/8 + import9 guards использованы для test/deploy;
waiter reaped, удалялся только owned marker. Не отменяли чужие workers.

Before snapshot07:24:11UTC Oct2–4:1485planned/375canonical/1089NO_DATA/
21unattempted,6488versions/6488lexicalrows/177events. Proof
`s192-ingestion-f66acc8b-1d74-4cf7-bd76-dd64393389f7.json` SHA256
`9af0be2574e41f73fc9be5d6637848b9cf293d34c62cf234d9f310d45b00ab22`.
Live comparison после очередного штатного cron выполнен ниже.
Source capacity/national hourly freshness/fullEIS UNKNOWN.

## Обычный проход после выпуска

Same exact Oct2–4 scope,07:24:11–07:40:18UTC,967.216606s:

| Показатель | Before | After |
| --- | ---: | ---: |
| Canonical | 375 | 375 |
| NO_DATA без canonical | 1089 | 1097 |
| Unattempted | 21 | 13 |
| Версии / lexical rows | 6488 / 6488 | 6488 / 6488 |
| События | 177 | 177 |

8 first attempts/8latestchanges, all `UNATTEMPTED->NO_DATA`, canonical regressions0.
Пересекающийся cohortOct1–3 снят отдельно07:26:19–07:40:19UTC840s:
0firstattempts/0canonical/indexchange. Счётчики двух пересекающихся диапазонов
не складываются. В этом sample дополнительная квота не дошла до Oct1.
Journal interval фиксирует9records actor `server-corpus-worker`:
1старый Sep4NO_DATA и8Oct4NO_DATA. Это journal records, не число HTTP calls.

Lease horizon:21complete/0censored/0inconsistent runs, corpus1/priority3/documents16/
223one. Observedheldlowerboundunion202.36181s, workknown2sum202.116557742s,
waitknown2max4.17081713s. Capacity UNKNOWN. Corpus operationalERROR1;
latest stdout BLOCKED/REGIONAL_REFRESH_REQUESTED/selected60/attempted9,
не source/parser fault. Exact stdout↔metric run binding UNKNOWN; журнал отдельно
подтверждает9attempts указанного actor за interval. Все диагностические операции
source0/DBwrites0; background cron выполнял обычные source/journal writes.

Вывод: проверено увеличение selection quota, но измеренного throughput gain
или ускорения в1.5 раза нет. В данном pass ранняя уступка региональной задаче
оставила51из60выбранных мест невыполненными. Изменение очереди сохраняется,
но следующий приоритет — ограниченное продолжение после cooperative yield
внутри исходного max60 budget, с учётом времени, lease/marker ownership и source guards.
NO_DATA retry остаётся отдельным verification срезом, без превращения gap в completion.

## Private evidence на VPS

Root `/var/lib/eis-browser/research/rejected/`:

| File | SHA256 |
| --- | --- |
| `s192-progress-39678be5-62c5-444d-bd52-359317e8f25c.json` | `28059ff3121b365f1d7cb4921e545a5bb2c907adb90d5c2f7603b0157c7482ec` |
| `s192-progress-bebe27f9-8b8c-46cb-ba52-e8629e27d03a.json` | `569e1b9dfce516248f20bc6eace6c49802ba3498c6dd28a247cc9d6a948782b0` |
| `s193-lease-observation.json` | `a882b2aa3bc1ab052ecc2f192985daeff633c0ce1fb6c27f33dabc2cdf99b170` |
| `s193-journal-observation.json` | `29d3e82526648c8d762c26eaaec659990b4ac0e303f6bcd66b252dfc90a418b3` |

FinalOct2–4proof SHA256 `7092556214fcd5cd86ab665061fdbd3f21a3125455f15e39f50fdeec43b4c9e3`;
typed progress binds both raw report hashes. Oct1–3afterSHA
`aaf1724fc8753171cb8655bc908aa70a5ebe92264f4afeef57437cbd28ce7103`;
beforeSHA `9e4e91e2598f27652abf6a6f7ed083d90f3ef66e5b09312e843ef727189c24e2`.

## Итоговая проверка VPS

07:42:19UTC: host25/API2/worker2 hashes PASS, API/worker release image IDs
совпадают с записанными при rollout, web image неизменён. HEAD03/health200/OOMfalse,
API1GiB/web768MiB; DB3 970 808 855bytes/free258 912 776 192bytes,
testDBnone. Regional marker true отражает обычный cron; чужие markers не удалены.
Cron/source/CPU/memory/disk budgets unchanged. Ops snapshot отличается по времени
от final cohort, поэтому не используется для attribution source progress.

Private `s193-operations-proof.json` SHA256
`6b67bcfecaa254d03866071afabeeb0b71b9807f7cfd18e3d132e2cde680f407`.
Docs backup `/home/syurai/vibe-seller-state/backups/s193-before-20261005T074217Z-docs.tar.gz`,
SHA256 `3bee1f6af22dcc72005aef2fa5dbfb1c42ef3c7c277979efaaece2549f0ed6a0`.
Receipt additions включены в заключительную docs-only hash сверку;
runtime bytes frozen after41PASS.
