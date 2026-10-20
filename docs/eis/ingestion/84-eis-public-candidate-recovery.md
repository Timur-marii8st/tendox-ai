# S201 — адресная загрузка кандидатов публичной выдачи

Owner: root. Статус: bounded operator slice завершён; full EIS coverage UNKNOWN.

## Контракт

Вход — неизменённый S200 report и его явно заданный SHA256. До обращения к
источнику проверяются модель, возраст отчёта <=7 дней, SHA/размер DOM, повторный
разбор карточек и сохранённый SOAP NO_DATA receipt. Исходная публикация может
быть исторической: возраст отчёта не означает свежесть закупки.

Кандидаты берутся только из `not_indexed_candidates`. Перед каждым номером
проверяется tenant index. Маршруты `ea20`, `zk20`, `ok20` служат подсказками
порядка загрузки; сначала берётся первый кандидат каждого поддержанного маршрута.
Поддержка XML определяется прежним `sync_eis_number` и `preflight_ready_window`.
Все документы полного архива должны пройти проверки, каждый номер в XML должен
совпасть с запрошенным. Неподдержанный документ не удаляется из набора ради допуска.

Один ручной pass: максимум3 номера, 18 попыток SOAP, 20 попыток download,
180с общего сетевого бюджета /60с на номер. Транспорт последовательный, один
браузер через существующий proxy; wrapper держит общий import lease и worker
получает прежние2CPU/2GiB. DB statement timeout20с/lock timeout2с;
DB<100GiB/free>=40GiB проверяются перед источником.
Wrapper ожидает priority lease до300с, затем создаёт exclusive UUID marker и
ожидает import lease до300с. Эти ожидания не входят в180с сетевого allowance.
Existing marker не перезаписывается; cleanup удаляет только свой UUID marker.
Busy/unavailable proxy возвращают UNKNOWN с0 SOAP attempts.

64MiB — лимит принимаемых ответов архивов и запрет следующего download после
исчерпания. Browser transport возвращает целый ответ, поэтому это **не лимит
трафика на проводе**. Отчёт отдельно считает полученные байты, включая отвергнутый
ответ, и принятые байты. Синхронные DB/retention операции и закрытие браузера
также могут увеличить wall time сверх сетевого бюджета.

## Результат и evidence

`SYNCED` сохраняет полный набор через существующий атомарный intake вместе с
lexical projection. Только usable exact latest `(number, version, XML SHA)`
ставится в документную очередь. Ошибка очереди не отменяет факт записи XML.
После ошибки source hold повторный read показывает реальные записанные версии;
такая закупка не получает допуск к сравнению.

Полный связанный отвергнутый набор сохраняется через прежний immutable rejected
store (5GiB total, 64MiB compressed/128MiB expanded per set). Manifest связывает
номер, SOAP/prepared SHA, URL и архивные SHA. Фактическая причина отказа идёт в
typed outcome; общий retention reason `TRANSPORT_WINDOW_NOT_CANONICAL` означает
отказ текущего intake, а не доказательство некорректности публикации ЕИС.
Неполный/непривязанный набор не получает complete-set receipt.

Попытки пишут tenant-scoped `EIS_PUBLIC_CANDIDATE_RECOVERY` audit с входным SHA,
before/after index evidence и result. Пропущенные кандидаты остаются в отчёте.
`ROUTE_UNSUPPORTED` означает отсутствие загрузки по подсказке URL, не вывод о XML.
Proof — приватный JSON<=1MiB, не более128 файлов в отдельном tenant directory.
Нет удаления, ротации, изменения checkpoints или автоматического расширения cron.
Full EIS coverage, свежесть всех версий и participation остаются `UNKNOWN`.

## Запуск на VPS

```bash
bash scripts/server-eis-public-candidate-recovery.sh \
  --input /var/lib/eis-browser/research/rejected/s200-public-check-60c82246-c776-421f-b885-216d6d5c41a0.json \
  --input-sha256 e747bf27ea301f86a4087270a992533020ffb318396293a73400274f342c6b27
```

Секреты берутся из worker environment; запрос с токеном не сохраняется и не
печатается. Host script mount read-only, runtime images/schema/cron не меняются.

## Проверки

Проверяются corruption/age/offline binding, budget attempts/overshoot,
unsupported route scheduling, post-ingest hold/queue failure. Изолированный PG:
чужой tenant не подавляет запрос, точный XML пишет notice+lexical+version-bound
document job; другой номер и неподдержанный XML отклоняются без canonical writes,
при этом сохраняется bound rejected evidence и audit. Bounded live proof и ограничение mixed archives приведены ниже.

## S201 live acceptance — завершено 2026-10-05

65Linux/isolatedPGtestsPASS14:41:24UTC; Ruff/mypyPASS, bash syntaxPASS.
Gate includes preservation of existing/replaced foreign markers and source0 cleanup
after import-busy. Synthetic exact notice+lexical+exact document job PASS;
foreign number/unsupported XML rejected atomically with retained evidence/audit.
Host-only initial rollout14:35:29UTC atomic9/host52/API11/worker11hashPASS;
code backupSHA `8a74bc35dfff465b7d3dbb197d9149db638430c672cf006952b5495b262490ce`.
Initial plain import wait expired after30s (source0/no report); wrapper adjusted
to existing priority lane, exclusive owned UUID marker and300s lease waits.
No runtime restart/image/schema/cron/source quota change.
Final seal14:46:20UTC: host52/API11/worker11hashPASS, pinned images/cron unchanged;
API/web running, no OOM. Seal backupSHA
`81172ad31ea6f5e5e2033adffbc168f74a5d981ed0b5b12c89966258aa8c4d93`.

Real report14:38:21.742553UTC:3 attempted numbers/6 SOAP attempts/3 downloads,
158156received+accepted archivebytes, 23.07465s worker pass (lease waits excluded).
Of S20023 missing candidates,12 already present at fresh tenant recheck,
8 unsupported route hints,3 attempted/rejected. The12 existing numbers are not new
writes attributable to this batch; indexed does not mean usable/fresh.
Attempted `0373100075926000096`, `0373100075926000095`, `0573500000526000095`:
all DOCUMENT_TYPE_UNSUPPORTED; before/after versions0/lexical0, no document queue.
All3 complete bound archives retained, all3 tenant audits RECORDED; new canonical
versions from this pass0. These historical/allstage candidates are not recommendations.

Recovery proof `/var/lib/eis-browser/research/rejected/addressed-recovery/local-eis-supplier/s201-600fa7d0-9b22-41ce-9c02-1a0fb250eed2.json`;
SHA `6ed2d640b90c005e9d30d6ef8b008ece90c8ffe30b9d8636aa98b6246f0026e0`.
Offline proof/model/input DOM+SOAP receipt/3audit payloads/3manifest+ZIP hashes PASS;
16XML members inventoried source0/DBwrites0. Types: epNotificationEOK2020,
epClarificationDoc, epProtocolEOK2020FirstSections/SecondSections/Final,
fcsPlacementResult, fcsProposalsResult. Supported notification occurs in every set;
other families block whole-set canonical intake. Nested purchaseNumber leaves are
not registry identity evidence. Need family-specific paths and official schema.
Offline proof `/var/lib/eis-browser/research/rejected/s201-offline-verification.json`;
SHA `107175bb8ee94aca306118acc444b8f63fbfe1071b5ac828cb24a69ba43ad735`.
Ops14:42:59UTC health200/HEAD03/no testDB/markersfalse;
DB4524792855/free258191085568bytes. OpsSHA
`538ed62fb21593e4e172698b95f6217a6355477ed2cb2dd9e8922597786d4891`.
FullEIS coverage/independent source absence/participation remain UNKNOWN.

NextS202: typed mixed by-number archive intake, beginning with these retained EOK
sets. Preserve every member and XML provenance; separate notification,
clarification and lifecycle/result families under explicit ADR. Unmapped members
remain UNKNOWN and cannot produce full-set/active/participation claims.
Replay stored bytes source0 first; demonstrate notice/search recovery with correct
lifecycle/hold semantics before new source requests or automatic recovery schedule.
