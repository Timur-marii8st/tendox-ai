# S199 — квота и lifecycle исходных ответов ЕИС

Статус: завершён и установлен на VPS; real read-only report проверен. Owner root;
самостоятельные implementation/review, зависимости S198/ADR0079. Это операторский
отчёт о сохранённых NO_DATA, не метрика полного охвата ЕИС.

## Запуск на VPS

```bash
cd /home/syurai/vibe-seller
bash scripts/server-eis-no-data-store-report.sh --since 2026-10-05T12:43:08.752311Z
```

`--since` обязателен, timezone-aware, не старше7дней. Для оценки S198 используем
cutover12:43:08UTC; более ранний период содержит попытки до включения retention.
Tenant фиксирован local-eis-supplier. Отчёт запускает оператор; он не является
автоматическим уведомлением или новым экраном поиска.

## Что измеряется

SQLite: global row/payload/DB used/limit/remaining, tenant rows/payload,
oldest/newest captured_at и число ответов нашего tenant возрастом >=30дней.
Глобальные счётчики нужны для квоты общего store; чужие tenant identities,
времена, manifests и содержимое не выводятся. Сравниваются usage и реальные
COUNT/SUM payload с length(raw)+length(manifest); raw XML не читается в Python.
Снимок проверяет только согласованность метаданных. Для bytes/hash/parser
используется отдельный [отчёт S198](../eis/ingestion/81-eis-no-data-raw-evidence.md).

PostgreSQL: RETAINED/FAILED audit events периода, причины отказов, <=10 latest
failure samples; NO_DATA attempts без capture audit с теми же tenant/window/
actor/SHA и occurred_at<=attempted_at. Такой пробел — UNKNOWN; он может означать
отключённое retention, отказ audit или начало попытки до границы периода.
Нулевое число попыток также даёт UNKNOWN audit_completeness. PASS означает только
наличие соответствующих audit в выбранном периоде, включая FAILED сохранения;
состояние сохранения и число FAILED выводятся отдельно.

## Lifecycle и действия

- OBSERVE — метаданные согласованы, нет отказов/пробелов и thresholds не достигнуты.
- PLAN_ARCHIVE — любое из row/payload/DB достигло80%, либо есть ответы >=30дней.
- INVESTIGATE_FAILURES — есть FAILED audit или попытки без capture audit.
- RESTORE_VISIBILITY — store отсутствует, отключён, недоступен или некорректен.

Приоритет: visibility > failures > archive > observe. Возраст30дней — повод
пересмотреть хранение, не TTL и не доказательство безопасного удаления.
Lifecycle HOLD_IMMUTABLE_EVIDENCE: ответы не удаляются и не вытесняются.
До возможной очистки нужен отдельный контракт проверенного immutable архива и
разрешения ссылок старых audit; текущий slice такого действия не выполняет.
80% — операционная policy S199, effective2026-10-05, источник ADR0080.
Время заполнения не прогнозируется из неполного снимка и текущего темпа.

## Границы выполнения

SQLite mode=ro/query_only, cache1MiB, timeout1s, scan<=65536rows и2s budget
(progress handler и проверка в Python), store<=128MiB; ограничения S198 сохраняются.
Permission/symlink/schema/counter/tenant-date mismatch — FAIL; busy/missing/disabled/
IO/timeout — UNKNOWN. Неизвестные счётчики не подменяются нулями.
SQLite и PostgreSQL — два последовательных независимых снимка с отдельным временем,
не атомарный общий срез. PG REPEATABLE READ / READ ONLY, SQL30s, <=7дней.
Source requests0 / DB writes0; приватный UUID JSON <=1MiB0600 в research/rejected.
Stdout содержит безопасные агрегаты и proof SHA; нет XML или токена.

## Acceptance

48Linux/isolatedPG tests PASS; Ruff/mypy PASS. Проверены exact headroom,80%boundary,
tenant age/cutoff, readonly digest, corruption/schema/type/date, lock/timeout,
period/snapshot guard и live PostgreSQL audit/failure/attempt parity/RLS.
Предварительные ошибки gate: отсутствующая миграция isolatedDB и неполный fixture
plan; исправлены в gate/fixtures, production source runtime не менялся.
Stage тестирует frozen исходники S198; owned changes только два scripts, один
тест и документация. Установка atomic/backup/hash, API/worker/web images, cron,
permissions source, schema и source budgets сохраняются. Реальный report pending.

Следующий S200: независимое подтверждение спорных NO_DATA по официальным данным
ЕИС с проверяемым scope; полная национальная свежесть/coverage/sourceabsenceUNKNOWN.

## Live acceptance — завершено 2026-10-05

Gates48PASS13:28:41UTC (30S198 retention/offline +18S199 quota/PG checks),
Ruff/mypyPASS; isolated testDB removed, source credentials/browser paths unset.
Host-only rollout13:31:47UTC:atomic9, host38/API5/worker5 hashesPASS; runtime,
web images, cronSHA and HEAD20261004_03 unchanged. No restart/manual source pass.
BackupSHA `e2f960853f6dfc44b8781d846b3d694cd211878809fbe6d7e8dff7423a01fedd`.

Real PGsnapshot13:31:46.367122UTC / SQLite13:31:46.393039UTC:
112records, payload144674bytes/96MiB, DB278528bytes/128MiB;
rows remaining65424/65536, payload remaining100518622bytes,
DB remaining133939200bytes. Tenant112records, oldest12:45:20UTC/newest13:31:45UTC,
review-age30days rows0. RETAINED112/FAILED0; NO_DATA without matching capture audit0.
Action OBSERVE. Counts belong to these independent snapshots, not all corpus windows.

Proof `/var/lib/eis-browser/research/rejected/s199-store-health-78ca5522-c628-4696-a937-2e3a598b619a.json`;
SHA256 `fcc0cf5257592c10f399d97639c4033c01d6dc357418c38aec302d90f46ec563`.
Diagnostic source requests0 / DB writes0; ordinary cron continued in background.
Ops13:31:47UTC:health200/HEAD03/testDBnone/DB4445445143/free258312675328bytes,
markersfalse; proofSHA `8c8c1e67804efd75add3434679964facea8a1290a3cd510f84e42910f97b78d4`.
These observations do not prove independent source absence, national freshness or
fullEIS coverage; all remain UNKNOWN. S199 is complete as operator visibility /
HOLD_IMMUTABLE_EVIDENCE slice; archive export/rotation/deletion not implemented.
Next S200: independent NO_DATA corroboration contract against official source,
with exact cohort/scope/evidence and bounded source budget before completeness claims.
