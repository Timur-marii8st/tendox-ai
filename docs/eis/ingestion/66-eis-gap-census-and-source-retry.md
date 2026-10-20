# S181 — сверка очереди ЕИС и повторы старых сбоев связи

Дата: 04.10.2026. Статус: DEPLOYED; isolated/live/API gates PASS.
Контракт: [ADR-0065](../../adr/0065-eis-gap-census-and-historical-source-retry.md).

## Что измерено до изменения

Сверка production tenant `local-eis-supplier`, 15:52 МСК, без обращений к ЕИС
и записей в базу:

| Состояние запланированного окна | Количество |
|---|---:|
| Ещё не обработано | 136630 |
| Последний ответ NO_DATA | 6427 |
| Последняя попытка FAILED | 72 |
| Последняя попытка SERVICE_ERROR | 1 |
| Всего незавершённых | 143130 |

Даты источника: 28.09.2025–04.10.2026, 99 candidate codes. Это кодовые кандидаты
в запланированной очереди, а не доказательство полного регионального охвата.
В базе 131201 уникальное извещение44, размер базы 3638656023 bytes. Сверка2.293s.

У FAILED:43 `ATTACHMENT_REFERENCE_INVALID`,9 `ATTACHMENT_COUNT_LIMIT`,
7 `DUPLICATE_NOTICE_VERSION`,5 `MEMBER_UNSUPPORTED`,2 `SOURCE_TRANSPORT_FAILED`,
2 `ARCHIVE_WINDOW_EXPANSION_LIMIT`; ещё по одному `NOTICE_VERSION_CONFLICT`,
`PREPARED_REQUEST_MISMATCH`, `DUPLICATE_NOTICE_VERSION_IN_WINDOW`,
`SOURCE_RESPONSE_REJECTED`. Старые сбои связи ранее уступали весь приоритет
большому хвосту окон без попыток.

Baseline proof: `/var/lib/eis-browser/research/rejected/s181-baseline-census.json`,
SHA-256 `8679ec7d7c06bac6dced018170950c90f71baae5c7aa5d7e066c932887147d11`.

## Реализация

CLI `python -m procurement.eis_corpus_cli gap-status --company-id COMPANY
--actor-id OBSERVER --sample-limit 20` не требует source token. Полные totals,
группы причин, даты и ограниченная выборка immutable attempt IDs читаются
в одном tenant repeatable-read snapshot. Сумма groups равна числу pending;
выборка явно помечается `samples_truncated`. Provenance: три именованные таблицы,
company, checked_at, source response SHA и attempt ID для выбранных окон.

Только `LEGACY_CANONICAL` завершает target. `VARIANT_TRANSPORT`, NO_DATA,
ошибки и отсутствие данных остаются gap. Некорректные source coordinates
дают status UNKNOWN; безопасный DATE guard исключает ошибку SQL cast.
Даже OBSERVED означает корректную сверку очереди, coverage/freshness UNKNOWN.

Общий latest helper выбирает последнюю попытку по `(attempted_at DESC,
attempt_id DESC)` внутри tenant/window **до** проверки eligibility. Новое
NO_DATA или ошибка разбора перекрывает старый сбой связи.

Новая historical source retry полоса резервирует до3slots/60run:

- latest FAILED с точным кодом `SOURCE_TRANSPORT_FAILED` или
  `SOURCE_WSDL_UNAVAILABLE`, либо latest PREPARING/SERVICE_ERROR;
- latest попытке не меньше24h, timestamp из будущего не due;
- source day строго раньше MSKtoday−7, вне прежней недавней7day полосы;
- нет canonical checkpoint; ключ соответствует поддерживаемому date window.

Порядок: прежние recent failure slots → historical transient slots → обычный
backlog. Общий limit не растёт; свободные slots заполняются backlog. Как минимум
один обычный slot сохраняется при наличии eligible backlog. Для limit2 пустой
recent lane позволяет historical1+ordinary1; занятый recent — recent1+ordinary1.
Limit1 отдаётся обычному backlog. Выбор детерминирован, повторов ключей нет.

Parser/resource/variant errors и NO_DATA не входят в **новую reserved полосу**.
Прежний общий backlog может повторять такие окна после cooldown; это не новая
политика допуска. Source failures/DB failures прекращают проход по прежним
правилам. Новый результат добавляется в immutable journal; старые attempts
сохраняются. Частичный intake не закрывает checkpoint.

## Проверки

Linux worker:148 unit PASS. Isolated PostgreSQL:30 PASS, включая RLS, immutable
history, partial intake, full census, bounded samples, latest ties, malformed
coordinates, cooling/future timestamps и limits1/2/60. Ruff8files PASS,
mypy4runtimefiles PASS. Production schema без изменений, HEAD20261004_03.

Production staged census на148168targets: первая версия36.697s. После перехода
к одному SQL с общим MATERIALIZED pending набором —8.475s; selector8.369s,
EXPLAIN8.572s. Снимки разные, фоновые workers продолжали работу между ними:
это измерения на живой базе, не same-snapshot benchmark и не SLA. Главный
прежний selector cost — regex scan по146kdate targets; этот slice не меняет
его общий backlog контракт. Полный охват ЕИС пока UNKNOWN.

Первая staged proof: `s181-staged-status-proof.json`, SHA-256
`225342a7342e8f6ae4aa740db48310e750d6bd5f9e9431f4ba3f2c926a5f500e`.
Optimized staged proof: `s181-fast-status-proof.json`, SHA-256
`6ccf4dc75ee6482d3e61b4a26f5d723d353bfd4c4ab356aeddd12541cc9937d7`.
Обе в `/var/lib/eis-browser/research/rejected/`, source0/writes0.

### Production, 16:20–16:23 МСК

Backup `/home/syurai/vibe-seller-state/backups/s181-before-20261004T132027Z-code.tar.gz`,
SHA-256 `5aa74ce97acf72857c08cde51be51c196566ed66452267ece65635ffe2ea4d01`.
Host14/runtime4 hashes PASS, API и worker rebuilt; HEAD20261004_03 прежний.

Deployed census:148168 planned,5040 canonical completed,143128 pending;
136602 unattempted,6451 NO_DATA,2 historical due. Census8.357s,
selector8.264s, EXPLAIN8.372s. Partial transport1 остаётся pending.
Нет некорректных coordinates;99candidate codes по-прежнему не certified scope.

Контролируемый live retry, всего2старых source windows:

| Окно отмены epNotificationCancelFailure | Ответ | Время | Canonical checkpoint |
|---|---|---:|---|
| 50 / 24.09.2026 | NO_DATA | 3.324s | false |
| 90 / 17.09.2026 | NO_DATA | 2.501s | false |

Каждая прежняя FAILED запись сохранена без изменений, новый attempt и audit
проверены. Новых notices/events0. Peak280690688B при memory limit2GiB —
измерение этих двух пустых ответов, не большого XML импорта. Повторная сверка
подтвердила exact latest IDs, NO_DATA6453 и historical due0; оба окна остаются
gap. Сетевой сбой больше не является последним состоянием этих окон.

Cached API:44 current131573, бумага2527/7.733s, сервер5303/14.602s;
223current2884, бумага59/295ms, сервер184/520ms. Health200, anonymous401,
no-store и UNKNOWN coverage/freshness сохранены. Эти timings не fast SLA.
Isolated testDB удалена. Наш priority marker снят; при API snapshot marker
следующего штатного freshness cron был active. Final operations16:25:07МСК:
оба markers false после естественного завершения cron; testDB отсутствует.
Чужие markers не удалялись.

| Proof в `/var/lib/eis-browser/research/rejected/` | SHA-256 |
|---|---|
| `s181-deployed-status-proof.json` | `bc1880e85a37867150ec7379b2bee4142d9203abc1892e9cc42eeaefd09ea3e5` |
| `s181-live-proof.json` | `46c233e57a976f5f912b737e20ea2530f538f7bb0b730cf75532791073a2c69f` |
| `s181-outcome-proof.json` | `b623a291b32cd34c72be512332916450f4dc83689dde30026b39d98edf1c5694` |
| `s181-api-proof.json` | `7eee64ac26c2df2e2fa8d8db9dda1cf99784215db0d54fd1aff0decb1d826dbf` |
| `s181-operations-proof.json` | `4cd89173a4cfd7146d94b9e169dce512b3e31e469fa60d12e093e070bfa2eb1a` |

## Следующий срез

Отдельно восстановить9окон с obsolete `ATTACHMENT_COUNT_LIMIT`: текущий parser
уже поддерживает больший metadata catalogue, но старые FAILED не получают
быстрый повтор. Сначала проверить exact latest reason и не завершённые окна,
затем bounded retry2–3 с обычным full atomic checkpoint. Не включать эту причину
в transient allowlist и не расслаблять43ошибки attachment reference без evidence.
