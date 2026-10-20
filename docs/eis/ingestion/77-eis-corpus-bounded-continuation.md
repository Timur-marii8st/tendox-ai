# S194 — продолжение corpus после приоритетного обновления

Статус: DEPLOYED / VERIFIED BOUNDED CONTINUATION. Owner root, 2026-10-05.
Контракт — [ADR0075](../../adr/0075-eis-corpus-bounded-continuation.md).

Теперь один15-minute corpus dispatch может продолжиться после cooperative yield.
Суммарно максимум60 attempted windows, максимум6 segments;840s на ожидание/старт
продолжений. Активный atomic импорт не прерывается по horizon. Другие загрузчики
сохраняют priority, общий import lease, resource limits и свои markers.
Source failures и неизвестные/невалидные ответы завершают parent без продолжения.

Операторская диагностика на VPS:

- `scripts/server-eis-corpus.sh run --max-windows 60 ...` — прежний cron entrypoint.
- `run` stdout теперь содержит отдельный JSON каждого segment (JSONL), exit code
  отражает terminal segment или dispatcher stop. Общие counters берутся из parent
  receipt, не из последней строки. `plan/extend/status` сохраняют прежний stdout.
- `state/eis-corpus-runs/local-eis-supplier/runs.jsonl` и previous: parent receipts
  с metadata; actual absolute state root `/home/syurai/vibe-seller-state`.
- `state/eis-worker-metrics/local-eis-supplier.jsonl`: segment metrics, связываются
  с parent через segment.run_id. Не складывать перекрывающиеся cohort reports.
- Invalid-worker-output receipt: attempted последнего segment и parent null,
  `known_attempted_lower_bound` содержит только проверенные предыдущие segments;
  продолжения нет.

NO_DATA не становится canonical. Следующий отдельный срез должен проверить его
повторную обработку по действующей24h policy. Полный национальный hourly охват,
полнота карточек/документов и выгодность закупок этим изменением не подтверждаются.

Архивы остаются на VPS. Дополнительный stdout buffer parent ограничен1MiB,
receipt logs — current2MiB+previous2MiB; source worker сохраняет2CPU/2GiB лимит.
На ноутбук не переносится база или корпус документов.

## Проверки и rollout

95 Linux unit/process tests PASS08:13:43UTC; network none,2CPU/2GiB.
Ruff/mypy Linux platform/bashsyntax PASS. Runtime frozen after gates.
Atomic10 rollout08:14:14UTC,28 host hashes PASS; API/worker/web images и cron
unchanged. HEAD20261004_03/health200/testDBnone; без migrations и source diagnostic
dispatch. Code backup `/home/syurai/vibe-seller-state/backups/`:
`s194-before-20261005T081413Z-code.tar.gz`, SHA256
`d393d9df41412f4b658271ec0943bed77629f10863acb6db1f726f280a495e85`.

First ordinary parent `5b90565f-a7b8-4ec2-a859-485627aa13aa` started08:15:01UTC.
Segment1:13attempts then priorityyield08:17:07; segment2 started08:18:22 with47
remaining,26attempts then regionalyield08:21:09. Interim known39, remaining21.
Both metric cycle bindings PASS. Interim private proof
`s194-parent-observation-f53b146d-eb26-4c54-aa9f-1bacba3e5585.json` SHA256
`e506d48c637448b21e04c75e9463cc65ce3505ff03ca5ba423f0658937079499`.
Это historical interim receipt; final observation ниже.

Completed Oct2–4 baseline08:14:05UTC,exact1485keys:375canonical/1110NO_DATA,
0unattempted,6488versions/6488lexicalrows/events177. Window cohort не включает
Oct1/older history, поэтому изменение только этого cohort не измеряет весь pass.
Private baseline `s192-ingestion-b474f72f-4062-4fca-9552-d5c5cfd577de.json` SHA256
`98264c0a535681bf750fe270cdec264b3d6b052d65b15b675e63d1db9407d8b7`.

## Завершённый ordinary cron pass

Parent завершён08:27:08UTC; elapsed726.332s (~12min6s), в пределах840s start horizon.
Последний worker statusPARTIAL/reasonnull; parent PASS_FINISHED означает окончание
ограниченного прохода, **coverage остаётся UNKNOWN**.

| Segment | Начало UTC | Конец UTC | Budget | Attempted | Synced | Новых версий | Остановка |
|---|---|---|---:|---:|---:|---:|---|
| 1 | 08:15:01 | 08:17:07 | 60 | 13 | 9 | 20 | priority yield |
| 2 | 08:18:22 | 08:21:09 | 47 | 26 | 4 | 97 | regional yield |
| 3 | 08:23:56 | 08:27:08 | 21 | 21 | 16 | 446 | bounded pass finished |

Итого60 attempts,29SYNCED/31NO_DATA,563 новых **версий карточек**,14 событий.
Продолжения после первой паузы дали47attempts и543версии внутри исходного60budget.
Это факт одного pass, не коэффициент ускорения/устойчивый throughput/SLA.
Source-call count UNKNOWN: window attempt не равен HTTP request.

Exact parent↔stdout SHA binding (`/home/syurai/vibe-seller-state/s194-output-binding.json`)
SHA256 `265c4899b4dff80fcb523f3c701a615d68ad87cd546c4bac88cf1a0b4bc17639`.
Journal на tenant read-only snapshot:60records actorserver-corpus-worker,
Oct1=36(11SYNCED/25NO_DATA), Sep4=24(18SYNCED/6NO_DATA). Это также подтверждает
daily share36/24 на этом проходе. Нет диагностических source requests/DB writes.

Exact60windowkeys и parent UTC interval:563 добавленные версии=563lexical rows,
SQL statementtimeout30s/tenantRLS/RRreadonly. Это проверка попадания новых данных
в поиск, не полнота всех документов и не допуск/выгодность закупок.

## Final private evidence

Все перечисленные ниже files в `/var/lib/eis-browser/research/rejected/`,0600.

| Proof | SHA256 |
|---|---|
| `s194-parent-observation-c1af23f8-f859-4327-b03e-23f60954b320.json` | `fea4f9a949c19c5a50180c4657e008d0211bf5bf7d92460177594c75eb01b208` |
| `s194-journal-observation.json` | `74b6661fa8ee62f9ce5c049453d0606b1195d53ac96c92588b5c23ea2327b1ff` |
| `s194-index-parity.json` | `d3bc457d915e1b4bdd8b02c7fcfa69bfcd817eb3d6e1f490b46cbc0d6c9d0ccc` |
| `s194-lease-observation.json` | `9da22241e909ef4b26feaf507550b2622e4c8821ca534a29b2629f07bf0087df` |
| `s192-ingestion-5ad975a0-f900-4a51-b470-ddec8ae96119.json` | `3e3fea156a6e58d749930f0b34e6be64c404d6564e03ab81ab494d41fecc6f30` |
| `s192-progress-bfe03f3c-9d50-4e03-8d61-9df1e83c20cc.json` | `e2d6cc7f183407e02a0b7401ef207790e1a816bee9531a374cbf4390344828ab` |

Main Oct2–4 cohort before08:14:05/after08:29:22UTC917s:0changes/0regressions,
375canonical/1110NO_DATA,6488versions/index,177events unchanged. Это не противоречит
новым563vers: работа pass была на Oct1 и Sep4. Overlapping samples не суммируются.
Lease observer22complete/0censored/0inconsistent, held union lowerbound724.641081s
across all lanes; corpus3segments/priority3/documents15/223one.
Все3parent metric cycle bindings PASS. Два metric ERROR — raw CLIexit2 cooperative
yield, не source failure. Capacity/national hourly freshness/fullEIS UNKNOWN.

NextS195: bounded проверка NO_DATA retries и evidence по существующей24h policy;
empty response не даёт canonical completeness. Ресурсный бюджет не повышается.

## Final operational seal

08:32:59UTC:host28/API2/worker2hashPASS, frozen runtime matches95-test candidate;
API/worker/web image IDs и cronSHA неизменны. HEAD20261004_03/health200/testDBnone,
API1GiB/web768MiB/OOMfalse; DB3997506583bytes, volume free258867539968bytes.
Priority/regional markers отсутствовали в момент snapshot; foreign cleanup не было.
Private `s194-operations-proof.json` SHA256
`90f127620d9c92f6d1214b2e5d679bfdd56967ddcd4902f2873ce28e653cfdd4`.
Finaldocs backup SHA256
`7257a43e26320305c3b334cfd35aa15ac348e4df43b0fef8d650781b8cf9313d`.
Добавления с receipt hashes включаются в отдельный docs-only seal.
