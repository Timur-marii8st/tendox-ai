# S180 M2 — автоматическая обработка конфликтных окон44

Дата: 04.10.2026. M2 deployed and verified: tests, retained, live и API gates PASS.
Контракт: [ADR0064](../../adr/0064-eis-44-automatic-partial-intake.md).
Зависимость: [полная операторская проекция M1](64-eis-44-retained-projection.md).

## Автоматическая загрузка

`sync_eis_window` продолжает обычный atomic legacy import. Четыре точных причины
отказа notice44 (`DUPLICATE_NOTICE_VERSION`, `DUPLICATE_NOTICE_VERSION_IN_WINDOW`,
`NOTICE_VERSION_CONFLICT`, `TRANSPORT_WINDOW_NOT_CANONICAL`) запускают отдельный
bounded pipeline. После полного retention и обоих audits записывается immutable
ledger, затем выполняется M1 writer на тех же исходных ZIP. Дополнительных
запросов ЕИС этот pipeline не делает. Procedure events и223 adapters прежние.

Обрабатываются все members и пары полного набора. Singleton требует known-id,
одного type/XMLSHA во всей истории и полного parsed snapshot. Divergence,
existing canonical mismatch и неизвестные факты сохраняют HOLD/UNKNOWN.
Прерванный этап после ledger оставляет consumer hold; projection transaction
атомарна. Новая конфликтная история снова удерживает ранее принятую карточку.

Исходный `EisRejectedWindowError` и FAILED attempt сохраняются даже при успешной
проекции. `VARIANT_TRANSPORT` не становится ordinary checkpoint. Все восемь
completion readers M1 продолжают исключать transport-only; coverage/freshness
всей ЕИС UNKNOWN, supplier eligibility и экономика проходят отдельные gates.

## Typed результат и наблюдаемость

`EisVariantIntakeReport`: `NOT_ATTEMPTED | PARTIAL | FAILED`, stage, allowlisted
reason, exact ledger receipt/audit ids, nested projection report и UNKNOWN
coverage. Нет exception text, raw XML, credentials или токенов в отчёте.
NOT_ATTEMPTED означает отсутствующие prerequisites; попытка не маскируется этим
статусом. Любой FAILED stage останавливает текущий worker pass. Исходная причина
конфликта остаётся в FAILED journal, operational reason — в typed intake report.
Если БД не позволяет записать journal, persisted observation не обещается.

Freshness сохраняет report внутри `EisWindowObservation` в audit текущего attempt;
corpus — отдельным `variant_intake` в том же attempt audit basis. Новый optional
journal argument допустим только для FAILED с source response SHA. Historical
observations без нового поля остаются читаемыми. PARTIAL требует полного
retention/audits и согласованных new_versions; невозможен в SYNCED observation.

`partial_windows` считает успешные automatic intake attempts в текущем run;
`new_versions` увеличивается только на реальные новые canonical rows. При replay
batch историческое `projected_count` не увеличивает new_versions. `held_pairs`
суммирует held_count рассмотренных batches текущего run, не является глобальным
числом всех удержанных закупок или fresh re-evaluation старого batch;
`replayed_projection_batches` показывает число повторов сохранённых решений.
Live shared guard независимо повторно проверяет всю историю.

## Повтор exact transport

После partial intake обычный importer может вернуть
TRANSPORT_WINDOW_NOT_CANONICAL. Новый reason-specific retention менял бы дату
наблюдения и manifest при тех же байтах, нарушая immutable timestamp binding.
Поэтому этот путь read-only получает исходную audited receipt/diagnosis по exact
tenant/window/initial response и одному batch установленного parser version.
Сверяются prepared response SHA, все source URLs, ordered archive SHAs, counts
и parent timestamp; writer повторяет full inventory/audit/transport/snapshot
проверку. Отсутствие или несколько receipts, mismatch и нарушение audit приводят
к FAILED без fallback retention. Timestamp comparison M1 не ослаблен, выбор
latest отсутствует. Outer FAILED reason отражает текущую попытку отдельно.

Ledger-only interruption не имеет transport и повторяет прежний deterministic
retention/ledger identity, затем завершает projection. При held_count=0 окно
тоже остаётся pending/FAILED. Cooldown конфликтов остаётся24h, включая новый
transport-only reason. Resource gate, cron, источник/spacing и scope не расширены.

## Проверки

286 Linux tests /72 PostgreSQL tests PASS (358). Scoped Ruff8runtime/7tests и
mypy8modules PASS. PostgreSQL gates выполнялись на отдельной allowlisted DB
`procurement_eis_test_20261004_s180_m2`; frozen M1 migration и downgrade guards
проверяются до внесения history в test DB. Новых migrations нет; HEAD20261004_03.

Новые end-to-end PG cases на synthetic source: sync→retention→ledger→projection→refresh
attempt audit; PARTIAL singleton+divergent и replay0delta; late projection failure
оставляет ledger hold и повтор восстанавливает его; exact transport retry без
внутреннего duplicate; byte-identical all-singleton corpus всё равно FAILED,
typed audit durable. Прежние late variant, cached consumer, RLS/immutability,
atomic rollback и full inventory gates M1 сохранены.

Real retained automatic rejection-hook proof12:35:56UTC PASS:5ZIP/499XML/498pairs,
497PROJECTED/1HOLD, полные ledger499origins/transport5/decisions498, audit4.
Повтор всех13table deltas0, new_versions0; sourcecalls0/retainedfilewrites0,
checkpointfalse. Полный прогон двух intake вызовов101.737s, peak552,386,560B/2GiB
с Chromium. Это стоимость сохранения/полного audited replay этого batch при
работающей БД; не query latency и не throughput/SLA всей ЕИС.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-isolated-proof.json`
SHA256 `89bc2bc5caff1f57af61d9396697ff57ca4b690822c2979dbd42407e1f8762f8`.

Production deployed12:37:53UTC: API+worker rebuilt, HEAD20261004_03 прежний,
host21/runtime8 hashesPASS. Backup
`/home/syurai/vibe-seller-state/backups/s180-m2-before-20261004T123753Z-code.tar.gz`
SHA256 `937745e635926762fb5d5db69c144c29ef4f5a46118af9692c93611fd61ae72d`.
Production rejection-hook proof12:38:55UTC PASS: first и повторPARTIAL/replayed,
new_versions0, все13table deltas0/sourcecalls0/filewrites0, старый conflictHOLD,
checkpointfalse. Два intake вызова35.251s, peak510,578,688B/2GiB сChromium.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-retained-proof.json`
SHA256 `6c685db32414507646a328f2b39bc294afff3702685dad4d0ae924ada2f60c71`.
Контролируемый live source probe12:40:18UTC PASS: exact date77/2026-09-29,
реальные getDocsIP/polls/downloads принесли5ZIP/499XML/498pairs. Automatic intake
создал новый audited receipt/batch и498decisions:0PROJECTED/497REPLAYED/1HOLD;
new_versions0, все прежние8FAILED сохранены, новый typed attemptFAILED persisted,
checkpointfalse. Время37.43s, peak525,844,480B/2GiB; extra intake sourcecalls0.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-live-proof.json`
SHA256 `9002caa7ba1a56a8fb0b01fd6ab6ac3b0003f9f6793b0507fefa3d0dde909b47`.
Исследование live успешно, source guard не ослаблен. Test DB
`procurement_eis_test_20261004_s180_m2` удалена после проверок.

Final API smoke12:41:03UTC PASS:44current130458, бумага2517matches/7636.59ms,
серверное оборудование5269matches/14218.4ms;223current2882, бумага59/310.34ms,
сервер184/539.79ms. Все поиски no-store; health200/anonymous401,
coverage/freshnessUNKNOWN/sourcecalls0. При снимке priority markerfalse;
223refresh markertrue — выполнялся штатный concurrent cron; его marker затем
штатно снят, без удаления marker другим процессом.
Heldcurrent0 не снимает ledgerHOLD: конфликтующий pair не имеет canonical row.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-api-proof.json`
SHA256 `7cb86d0a8d2ccf5c0cad8d6c2f06c4d30254edfde9e9e314e891c3a045daa030`.
Размер индекса включает обычный cron intake; все новые130458 не приписываются M2.
Это saved-index query timing при текущем размере/нагрузке, не fullЕИС SLA.

Final operations proof12:44:23UTC: оба markersfalse, isolated DB отсутствует;
HEAD20261004_03 отдельно подтверждён owner read. Ошибка первого diagnostic
helper при чтении alembic_version от app role была ожидаемым permission denied;
права приложения не расширялись, production code не менялся.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-operations-proof.json`
SHA256 `137aed5086b0c9db214022d52991a522cfadf494fa96c1ac725e04267d3b0ccb`.

## Оставшаяся работа

Milestone M2 не означает полного охвата ЕИС. После завершённого production proof следующий
этап — измерить результаты automatic intake/cadence, возраст пропусков и lag;
затем расширять активные ранние даты и bounded backfill с parity проверкой.
Скорость comparison большого сохранённого индекса требует отдельного среза.
