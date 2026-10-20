# S188 — фактические пропуски загрузки и свежесть 44-ФЗ

Дата: 04.10.2026. Статус: VERIFIED, independent review PASS.
Это завершённая диагностика. Runtime, source admission и расписание не изменены.

## Что проверено

Tenant `local-eis-supplier`; PostgreSQL READ ONLY REPEATABLE READ, фиксированное
timezone-aware время. Census v2: `2026-10-04T18:29:25.209132Z`, snapshot
`54575:54575:`, 10.708 секунды. Все counts и выбор parser cohort относятся к
запланированным tenant targets; latest определяется до фильтра причины ошибки.
Typed envelope проверяет согласованность сумм, tenant, время и UNKNOWN.

V1 первоначально выбирал parser candidates среди всех latest tenant attempts.
Review потребовал пересечь их с planned targets. V2 исправил predicate и
проверил суммы с `EisGapStatus`. Исходный proof сохранён. Все десять parser
keys/attempt IDs/reasons/response SHA совпали; поздний lag probe перепроверил
эти exact attempts, наличие в плане и отсутствие LEGACY checkpoint.

Ни один probe не обращался к ЕИС и не писал в БД. Обычный cron продолжал работать:
общие серверные source calls и counters могут меняться между proofs.
223-ФЗ, документы и экономика поставщика не входят в этот census.

## Очередь — не процент охвата ЕИС

| Состояние planned targets | Количество |
| --- | ---: |
| Всего запланировано | 148243 |
| Имеют LEGACY_CANONICAL checkpoint | 5221 |
| Pending | 143022 |
| ↳ Ещё не было попытки | 136230 |
| ↳ Latest NO_DATA | 6768 |
| ↳ Latest FAILED | 24 |

Суммы проверены: 148243 = 5221 + 143022; 143022 = 136230 + 6768 + 24.
NO_DATA означает наблюдение источника без архива; оно не превращено в canonical
checkpoint или доказательство полного отсутствия закупок в ЕИС.

24 FAILED: 10 parser (5 `ATTACHMENT_REFERENCE_INVALID`, 5 `MEMBER_UNSUPPORTED`),
10 variant (8 `DUPLICATE_NOTICE_VERSION`, по одному
`DUPLICATE_NOTICE_VERSION_IN_WINDOW` и `NOTICE_VERSION_CONFLICT`),
2 `ARCHIVE_WINDOW_EXPANSION_LIMIT`, по одному `PREPARED_REQUEST_MISMATCH`
и `SOURCE_RESPONSE_REJECTED`. Эти причины требуют разных исправлений.

Всего в feed 5223 canonical window keys: два находятся вне planned denominator.
Transport — 3 records / 2 keys. Исторические projection batches: 1032 pairs,
532 projected, 497 replayed, 3 held decisions. Они пересекаются с pending и
canonical, их нельзя прибавлять к таблице как дополнительные окна.
Текущий live HOLD count этим probe не установлен (UNKNOWN).

## Национальные завершённые даты

Для 01–03.10.2026 daily plan содержит все 1188 ожидаемых candidate windows:
99 кодов × 4 families × 3 даты. Все получили попытку: 509 canonical,
678 latest NO_DATA, один `NOTICE_VERSION_CONFLICT`; UNATTEMPTED = 0.
Отсутствие попыток в старом backlog не объясняет задержку этих последних дат.

Это candidate codes `01..99`, а не подтверждённый реестр действующих регионов.
Families daily script: EF2020, EZK2020, Cancel, CancelFailure.
**EOK2020 не входит в этот национальный daily script.** Проверка предыдущих
завершённых дат также не доказывает national current-day coverage.

## Почему «13 часов» не означали остановку worker

Отдельный lag probe: `2026-10-04T18:31:59.812169+00:00`, snapshot
`54601:54601:`. Actual priority scope: 50/77/78 × 5 families. Проверены все
300 доступных current-day hour keys, отдельно последние два часа (30 keys).
Exact latest attempts, response SHA, canonical manifests и сохранённые publication
timestamps связываются по tenant/window. Последние два часа: 29 NO_DATA и
1 SYNCED, due = 0; максимальный возраст их попыток — 1188 секунд.

| Region / family | Расстояние до последнего canonical часа | Позднейшие latest observations |
| --- | ---: | --- |
| 50 / EZK2020 | 2 часа | 2 NO_DATA |
| 77 / EF2020 | 7 часов | 7 NO_DATA |
| 77 / EZK2020 | 1 час | 1 NO_DATA |
| 78 / EZK2020 | 13 часов | 13 NO_DATA |

У остальных 11 пар нет canonical часа за сегодня (distance NULL), но все
20 доступных часов имеют latest NO_DATA. Distance измеряет интервал от
последнего непустого загруженного часа, а не возраст последней проверки или
задержку публикаций в источнике. NO_DATA с SHA подтверждает только тот ответ
на тот запрос; source freshness остаётся UNKNOWN.

**Current-day hour targets и attempts найдены только для 50, 77 и 78.**
Национальный почасовой поток ещё не настроен. Daily sweep за предыдущие даты
не закрывает этот пробел.

## Скорость загрузки и границы модели

За 24 часа до census v2: 3317 attempts, 1037 первых canonical completions
уникальных window keys. Attempts, distinct windows, повторные SYNCED и новые
canonical completions — разные величины. Actors/outcomes/horizons сохранены
отдельно в proof: corpus 2169 attempts, freshness 1096, S185 manual 39,
attachment recovery 9, остальные proof operations 4. Исторический S185 repair
не выдаётся за скорость автоматического потока.

Freshness capacity: 1096 completed metric samples, 57 audit rows без metrics;
лимит 2000 не достигнут. p95 = 7001.344ms. Модель существующего scope оценивает
288 slots/hour и budget fit PASS; overall feasibility UNKNOWN. Это subset
наблюдений трёх регионов, не SLA для страны и не прогноз окончания backlog.

National five-family hourly intake создаёт 99 × 5 = 495 новых windows/hour
до повторных проверок. Потолок **существующего priority worker**:
24 × 12 = 288 windows/hour даже при нулевой задержке. Нельзя просто поставить
99 регионов в его scope и объявить покрытие. Corpus lane имеет отдельный cap
60 × 4 = 240/hour; оба lane делят import lease, их caps не означают независимую
суммарную производительность. Следующий дизайн должен учитывать совместное
время выполнения и обязательные source cooldowns, 223 и document work.

## Retained parser samples

Все 10 current parser attempts имеют NULL source response SHA. Поэтому поздний
S184 capture не доказывает точный historical response старого FAILED.
Существующие bytes двух samples перепроверены по capture/manifest/archive SHA,
полной SOAP binding, safe paths и прежним compressed/expanded/XML/node limits:

- Region30 / 09.09: 16 XML, 96 attachment entries; один DUPLICATE_UID.
  Entries14/20 имеют одинаковые четыре parsed metadata fields (UID, filename,
  URL, size), но разные serialized subtree hashes. Equivalence всей записи
  не доказана; автоматическое удаление или admission не включены.
- Region23 / 30.09: один XML превышает прежний 32MiB bound, два других достигли
  diagnostic node guard. Inspection UNKNOWN. Diagnostic node guard не назван
  новой причиной canonical parser rejection.
- Остальные восемь keys не имеют matching sample в проверенном S184 capture;
  их форма UNKNOWN. Это не утверждение об отсутствии bytes во всех хранилищах.

Findings histogram ограничен max100. Полный census/inspection и truncation
отражены в typed diagnostic reports; неполный разбор не выдаётся за полный.
Все source bytes остались на VPS. Guards не ослаблены, source retry не запускался.

## Проверки и receipts

Ruff/compile для трёх новых operator helpers PASS; bash syntax PASS.
Проверка empty current-day hours добавлена в lag helper после review; существующий
proof относится к указанному дневному clock с 20 eligible hours на пару.
Новых runtime tests/rebuild/migrations не требуется для read-only operation.
Runtime query и web/worker hashes S187 PASS, HEAD `20261004_03` прежний.

Operations `18:34:30.581190UTC`: DB3809287191bytes, free263259516928bytes,
test DBs отсутствуют, priority/223 markersfalse, API/web OOMfalse.
Caps API1GiB/web768MiB/worker2GiB CPU2, cron и source budgets прежние.

| Proof в `/var/lib/eis-browser/research/rejected/` | SHA256 |
| --- | --- |
| `s188-census.json` (исходный v1) | `a06207190bbf2e299a9c7e363394397b20065c2ae59ca5364e878e158be3c88c` |
| `s188-census-v2.json` | `353a24afca47dfa98386d7bfa21795ad39764c18c62e304f3ed6c0f668b8c42c` |
| `s188-retained-proof.json` | `b01288cd7c6f3fed532ca939a51bd7cd45dd82fb9690f59513b9b4a837e557b1` |
| `s188-lag-proof.json` | `5a7c7ecf73ee643480a7790d8e6a88ed5a46801fafcc016a9d3ee87325d2b562` |
| `s188-operations-proof.json` | `10ea979c814c4545ec75b82a04c0e231baae125c2854ee143008ab2cd82e7fe1` |

Deployed script SHAs: priority
`efa7643252bd4f3b04b1a90a4be48a58a16706687028233cd4aa433cdd629711`,
daily `633b82fe9da71adfa2768e1c18bcde0d2eddc5d57b2f887e816f73203c45bfe3`,
corpus `636e3024ef59902b07904a7ff786fa8b945f89f61376a35432c2440a20f35639`.
Independent review PASS после исправления planned predicate и проверки lag.

## Следующий S189

Сначала выбрать реализуемый национальный cadence: сравнить daily completeness
пяти families (включая EOK) с persistent rolling current-day wave. Dry-run
ordered targets, exact attempt ages и совместная capacity обоих 44 lanes,
223 leases и document work; минимум один backlog slot, отсутствие потери старых
pending при смене даты. Показать sweep age и growth, не выдавать observed
NO_DATA за полноту. Затем внедрить один выбранный bounded scheduler slice.
Исторические parser fixes и full document/profit comparison остаются отдельными
задачами; полный охват и свежесть ЕИС пока UNKNOWN.
