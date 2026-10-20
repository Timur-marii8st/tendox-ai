# ADR-0108: Ограниченные фрагменты больших audit rows в capture ЕИС

- **Статус:** ACCEPTED для архитектуры v2; реализация и actual capture не подтверждены.
- **Дата:** 2026-10-07.
- **Владелец решения:** root; контракт и независимый review — Astra.
- **Контракт:** [M2b capture](../eis/search/117-eis-frozen-benchmark-capture.md).

## Контекст

Первый production READ ONLY capture v1 завершился `INCOMPLETE` на
`RAW_ROW_EXCEEDS_SHARD_LIMIT:audit_events`, до экспорта relation rows.
Отдельный более поздний app-role READ ONLY REPEATABLE READ probe увидел 96
exact linked audit rows, из них три больше 8 MiB: максимум raw row —
14 839 504 bytes, `basis::text` — 14 839 307 bytes. Все три относятся к
`EIS_NOTICE_PROJECTION_RECORDED` / `eis_notice_projection_batch`.
Probe получал только scalars, без basis payload; их семантическая валидность
и размер canonical typed encoding этим не доказаны.

Основания в `tmp/improvement-program/m2/`: `linked-audit-width-probe-v1.json`
(SHA `f5056766500fcc1993231df1d67c220bac04905de1646562b20586b94552deec`),
`capture-large-row-design-v1.json`
(`eeb1124c9a05652b9f3494881e8ad74809a535f3f7f217f1485a1de1e1cd4d1e`),
`trusted-capture-run1-final-evidence-review-v1.json`
(`9017eac76744485eec9c6db7644262f39fc03b29a9d67983e3d3c7f022fc243b`).
Run1 и его очистка проверены как неуспешный запуск; origin остаётся UNKNOWN.
`clock` его incomplete marker — host `attempted_at`, не DB T. Snapshot/T
неуспешной транзакции не сохранены; поздний width probe их не восстанавливает.

Полный audit basis участвует в проверке projection/receipt hashes, batch,
decisions и связей. Исключить большие rows или части basis нельзя. Наблюдение
обосновывает явное изменение формата, а не изменение production данных/прав.

## Решение

Ввести отдельный format/plan v2 с исключением **только для `audit_events`**:
большая логическая строка может занимать несколько физических payload files.
V1 сохраняет прежнее поведение, включая отказ строки больше одного shard.
Новый verifier выбирает строгий version-specific путь; v1 не принимает v2
descriptors. Старые планы, source archives и results неизменны.

Для v2 audit row новые явные пределы: raw scalar sum <=32 MiB, полная canonical
typed строка с newline <=64 MiB, максимум восемь fragments. Для остальных
relations предел одной строки не меняется. Это отдельное согласованное
исключение logical-row bound, а не автоматическое повышение лимита shard.

Сохраняются 8 MiB на physical payload file, 16 MiB на metadata artifact,
512 physical payload files и 4 GiB total payload **включая fragments**,
1M logical rows/relation, batch <=8 и <=64 MiB raw prefetch, 900 s capture,
30 s statement, 1 s lock, >=5 GiB свободного места и 2 GiB container memory.
Превышение любого предела — `INCOMPLETE`, без fallback к subset или compression.

### Wire format и логическая целостность

Малая строка сохраняет прежние canonical typed JSONL bytes. Для большой audit
строки её место в PK-порядке занимает явно типизированный v2 descriptor.
Её **точные прежние canonical typed bytes с newline** делятся на consecutive
binary fragments <=8 MiB: без compression/base64 и без изменения JSON/Decimal
семантики. Каждый nonfinal fragment имеет ровно 8 MiB, последний непустой.

Descriptor связывает tenant/relation/typed PK, logical ordinal, полный размер
и SHA256 строки, число fragments и ordered descriptors. Каждый fragment имеет
fixed relative path, ordinal, offset, bytes и SHA256. Один path принадлежит
ровно одной логической строке; manifest содержит полную точную file closure.
Fragment — payload, не metadata и не дополнительная relation row.

Verifier проверяет declared counts/lengths до allocations/reads, ограниченно
собирает одну строку, проверяет bytes/hash, затем применяет прежние typed decode,
tenant/PK/FK и **полные** projection/receipt/audit semantic checks. PK descriptor
равен decoded PK. Counts, first/last PK, duplicates и ordered-row digest считают
логические строки; digest получает исходную canonical строку ровно один раз.
Transport hashes не заменяют семантическую проверку basis.

Отсутствующий, лишний, повторный, переставленный, пересекающийся fragment,
gap, чужой parent/tenant/relation, неверный offset/hash/size/PK, неоднозначная
версия, path escape и nonregular file блокируют пакет. Неоконченная fragmented
row не увеличивает `actual_relation_rows`; частичные counts явно incomplete
или UNKNOWN. Terminal complete manifest при такой ошибке запрещён.

### Чтение, память и время

Предикат exact linked audit IDs, все девять колонок и единая tenant-bound
READ ONLY REPEATABLE READ транзакция остаются прежними. До stream cursor в той
же транзакции измеряются count и maximum raw row bytes. Размер fetch заранее:
`min(8, floor(64 MiB / max(1, maximum_raw_row_bytes)))`; и driver prefetch,
и partitions ограничены им. Проверка после уже большого fetch недостаточна.
Raw row/batch bytes дополнительно проверяются при чтении.

Canonical encoding/hash/write выполняются bounded fragments с проверкой
64 MiB logical budget во время генерации, без предварительной неограниченной
полной сериализации. Reassembly обрабатывает одну ограниченную строку.
64 MiB raw prefetch не означает 64 MiB Python heap: обязательна измеренная
проверка collector и verifier на нескольких больших rows в прежних 2 GiB.
Parsing, typed objects и semantic checks также входят в этот process budget.
Если доказательства нет или предел превышен, slice не принимается.

Deadline/disk/total-byte checks действуют в fragment loops. Versioned incomplete
record разделяет aware host `attempted_at` и nullable фактически полученные
DB T/snapshot/runtime; отсутствующие данные — UNKNOWN, без подстановки host
clock. Credentials и basis bodies не попадают в диагностические logs.

## Acceptance и последствия

Один bounded slice Sol: два capture модуля, CLI, два **новых** v2 плана
(synthetic и production08), unit и integration PG tests; точные пути в 117.
Search/API/migrations, v1 benchmark, production данные и grants не меняются.
Root после independent review фиксирует новый source archive/controller plan
и новые run/capture/output IDs. Никакого продолжения run1 в новой транзакции.

Обязательны прежние v1 controls; byte-identical small/fragmented roundtrip и
logical digest; Unicode/Decimal/null/nested JSON и границы 8/32/64 MiB; все
перечисленные corruptions; source/batch/payload/file/time caps; failure посреди
fragment без complete manifest. Hash-consistent semantic basis corruption
должна по-прежнему отвергаться. Fresh disposable real PG fixture содержит
семантически корректный linked audit basis >8 MiB, несколько больших rows,
app-role RLS и concurrent commit вне capture snapshot. Измеряются prefetch и
peak memory collector/verifier; production credentials в тестах запрещены.

Instrument acceptance не обещает, что реальные typed rows уложатся в 64 MiB,
весь corpus — в 4 GiB/512 files, а capture — в 900 s. Actual capture и его
external origin anchor проверяются отдельно. M2b2 labels/replay/metrics остаются
следующим срезом; это решение не подтверждает baseline или полный M2.

## Альтернативы

- Оставить v1 и `INCOMPLETE` — допустимый результат, если v2 не проходит review.
- Обрезать basis/выбрать subset — нарушает read-closure и audit semantics.
- Увеличить shard — меняет физический предел, не разделяя row и shard.
- Compression alone — не даёт заранее известного размера и требует нового
  expansion budget; для этого slice не выбрана.
- Менять grants или production audit rows — не устраняет форматное ограничение
  корректным способом и не входит в решение.

## Уточнение v2 от 2026-10-08: authority raw width и reservation

Root принял ограниченные исправления F2-A/F2-B из independent review
`capture-format-v2-independent-review-v1.json`, SHA
`efc43df15786142f74758b4841ec7e3c71183cb2553b010bd0a8ee5a9d728251`.
Отклонённые source и прежние редакции ADR/117 сохранены в
`tmp/improvement-program/m2/capture-format-v2-source-rejected-v1/`;
archive7/actual PG для них не выполнялись. Это уточнение контракта, не
подтверждение исправленной реализации или нового capture.

**F2-A.** Авторитетное raw width — сумма PostgreSQL
`COALESCE(octet_length(column::text), 1)` по выбранным колонкам в той же
capture transaction. Collector сохраняет обязательный exact preflight <=32 MiB
для audit row. Offline verifier не реконструирует это наблюдение из Python:
JSONB numeric scale и формат date/time могут отличаться после typed roundtrip.

Вместо ложного exact raw claim verifier bounded-обходом вычисляет **нижнюю
границу**: сумму UTF-8 bytes decoded string values выбранных колонок, включая
каждое вхождение JSON object key/string leaf и strings внутри arrays. Каждое
сериализованное вхождение считается отдельно; column names, typed wrappers и
дублированный PK descriptor не входят. Для numeric/date и других значений с
неустановленным соответствием PG text вклад равен нулю. Обход/UTF-8 encoding
ограничены по chunk и прекращаются при превышении 32 MiB. Такую строку verifier
отвергает; значение ниже cap **не доказывает**, что exact PG raw width ниже cap.
Полный decoded basis и прежние semantic checks сохраняются.

V2 verification report во всех исходах явно содержит
`raw_width_validation=DECODED_LOWER_BOUND_ONLY` и
`source_raw_width_attestation=UNKNOWN`. Даже совпадение external manifest digest
не повышает эти поля. Фактическое соблюдение source raw bound относится к
trusted collector execution и последующему внешнему root origin audit.
Package self-assertion/per-row claimed raw bytes не заменяет это наблюдение.
V1 report/plan semantics не меняются.

**F2-B.** Общие file-count и payload-byte budgets проверяются/резервируются
**до** открытия нового physical payload file и **до** каждой записи bytes,
включая inline shard, переход inline→fragment и каждый binary fragment.
Затем проверяются оставшийся deadline и disk capacity; после этого разрешена
запись. При исчерпанном budget новый payload file/bytes не создаётся.
Partial write учитывается консервативно; reservation нельзя освобождать так,
чтобы оставшийся на диске payload стал невидимым для cap. Незавершённая logical
row не увеличивает completed count и не создаёт complete manifest. Bounded
temporary spool сохраняет свои logical/time/disk ограничения.

Acceptance дополнена regressions: семантически согласованный package с одной
string >32 MiB отвергается offline; неустановленные PG formatting bytes не
выдаются за измеренные; оба v2 report поля остаются указанными при любом
external digest. При уже исчерпанных 512 files/4 GiB writer не создаёт лишний
fragment/inline payload; boundary/partial failure accounting проверяется до
emission. Пределы, семь owned implementation paths и требование fresh real PG
плюс memory evidence остаются прежними.
