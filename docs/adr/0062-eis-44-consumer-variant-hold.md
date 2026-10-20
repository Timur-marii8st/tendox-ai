# ADR-0062 — shared consumer hold для unresolved notice44 evidence

Статус: **ACCEPTED / DEPLOYED**, 2026-10-04, 09:32 UTC.
Дата: 2026-10-04, S179. Owner ADR: Astra; index/bridge/projection/comparison,
integration gates: root; shared guard/document store: Sol.

## Решение

До любого canonical intake switch защитить текущие 44-FZ consumers от
unresolved evidence ledger [ADR-0061](0061-eis-44-notice-variant-ledger.md).
Typed operational reason: `NOTICE_VARIANT_REVIEW_REQUIRED`. Это UNKNOWN и
operation hold, не supplier FAIL и не доказанная отмена закупки.

Hold существует, если для tenant/purchase number есть variant **или origin**
с numeric version >= выбранной canonical version. Даже singleton остаётся
NOT_ENABLED: совпадение SHA, отсутствие второго варианта, успешный receipt
или bounded full-state read не разрешают его автоматически. Origin без
нормального receipt/variant linkage также не может снять hold.

Ledger более старой version не блокирует более новую выбранную canonical
version этим конкретным guard. Это не утверждение актуальности/допуска:
остальные source/version/deadline/procedure gates сохраняются.
Receipt-only запись не содержит per-number identity; integrity check может
консервативно удержать tenant при receipt без origins. Нельзя угадывать номер
или включать отдельный неполный receipt interpreter.

## Общий guard и consumer coverage

Guard использует bounded metadata SQL EXISTS; search не загружает ledger
JSON или все variants для каждой строки. Search исключает held candidates
до ranking/selection и отдельно сообщает held count.

Strict product reads вызывают ValueError с указанным reason **до** загрузки
и выдачи usable cached evidence. Guard покрывает:

- document plan/top selection, worker dispatch/capacity и pre-download read;
- status/analysis, cached received-document reanalysis и final receipt;
- evidence bridge, competition criteria и cached position projection;
- comparison (44/mixed), source estimate и legacy preliminary estimate;
- position projection reads/writes и их replay/cached returns.

Worker возвращает typed audited skip через существующий document-read audit.
Остальные read-only guards не создают audit, jobs или source calls.
Historical artifacts не удаляются; их наличие не обходит hold.
Pure comparison/estimate helpers дополнительно проверяют `collection.read_gate`
на blocker, чтобы held/stale in-memory DTO не породил usable economics.
Существующие mandatory FAIL не понижаются до UNKNOWN ради этого guard.

## Snapshot и race

Read paths используют один tenant-consistent snapshot. Ledger writer берёт
сначала общий tenant advisory lock, затем прежний ledger lock; document
final receipt использует тот же tenant lock. Final check выполняется **до**
cached/replay return и до blob/analysis/observation mutations. Это сериализует
commit нового hold с документным receipt; pre-download check сам по себе
не гарантирует состояние к моменту записи результата.

## Acceptance

Проверить same-version, newer-ledger, older-ledger cutoff; singleton и
divergent pair; tenant isolation; orphan origin/receipt integrity hold;
search exclusion до ranking и held count; queued и cached jobs; status,
analysis, bridge, projection, оба estimates и mixed comparison.
Сценарий race: download начался, ledger committed, final receipt отвергнут
без новых blob/analysis/observation writes. Повторить с cached receipt и
reanalysis. Pure held DTO не должен обходить blocker.

Новый intake, source calls, migration и автоматическое разрешение variants в
этом slice отсутствуют. Старый canonical gap остаётся FAILED. Implementation,
isolated gates и production deployment подтверждены ниже.

## Bounded review реализации

Проверены shared SQL guard, document store/worker, ledger lock order,
search, bridge, comparison и projection. Tenant lock теперь предшествует
ledger lock; document receipt/reanalysis и final projection recheck используют
тот же tenant lock. Strict notice load защищает cached status/analysis paths,
а search исключает held rows и в indexed, и в fallback candidates.

Исправлен найденный release blocker: worker отдельно проверял hold, затем вызывал
`get_document_status` вне hold-catching try. Commit ledger между этими двумя
snapshot приводил к uncaught exception вместо audited skip. Теперь оба шага
в одном hold-catching try; worker аудирует skip и продолжает к следующему job.
Детерминированный test покрывает hold именно на status read после успешного
assert. Повторный review исправления пройден; других blockers не найдено.
Root подтвердил финальные 172 Linux PASS и 52 isolated PG PASS (224 tests),
Ruff для 10 runtime / 10 test files и mypy для 9 storage/source modules.

Global receipt integrity predicate считает origins по indexed receipt key;
при literal tenant это общий для query subplan, без JSON loading. Рост стоимости
с историей receipts остаётся измеряемым свойством, не constant-time обещанием.
By-number sync защищает возвращаемую latest reference после существующего
intake; этот consumer guard не меняет canonical intake contract.

Финальный held-count query использует UNION ALL metadata variants/origins,
join current canonical и count DISTINCT; при receipt integrity error CASE
возвращает весь current count. Candidate exclusion и cutoff не изменены.
Comparison строится в одном consistent tenant snapshot. Известный hold на HTTP
paths возвращается как 422 с `Cache-Control: no-store`, включая mixed/source
estimate и live-number result. Финальный independent review пройден.

## Production evidence

Final rollout 09:32 UTC: host 26 / runtime 10 hashes совпали, оба code backups
сохранены, schema HEAD `20261004_02` неизменён. Read-only retained proof:
12 table deltas 0, source calls 0; pair 2 variants / 2 origins HOLD,
singleton HOLD, другой tenant и выбранная более новая version NO_HOLD.
Metadata SQL selector 500 rows — 2.884 ms.
Proof `/var/lib/eis-browser/research/rejected/s179-retained-proof.json`, SHA-256
`b76c18be42a06a633825631edec6b5df714c9cfcefd752830bb8302c97bfe115`.

API sample: 127,150 known current 44 numbers, 46 held current; cached paper
3,443.95 ms / 2,436 matches, server 9,398.68 ms / 5,138 matches. Эти единичные
измерения не SLA и не полнота ЕИС; широкий search остаётся заметно медленнее
metadata hold lookup. Proof `rejected/s179-after-api-proof.json`, SHA-256
`b59fe434a4e3511b5d8412fb8a28e27b84095a94c4578a8431f56df9818c75c5`.

Real HTTP held response: 422 / exact reason / no-store PASS.
Proof `rejected/s179-http-hold-proof.json`, SHA-256
`2f7514b6f82a1c35ad0c3293459a1f1f8d05ee8a39b8cd8318ffc20854915e85`.
Health 200 / anonymous 401 / no-store, markers отсутствуют, test DB удалена.
223 sample: 2,882 current, paper 243.89 ms / server 610.14 ms. Consumer hold
не снимает исторический FAILED и не включает canonical variant intake.
