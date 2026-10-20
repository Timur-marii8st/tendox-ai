# ADR0075 — bounded continuation после cooperative yield

Дата: 2026-10-05. Owner root. Status: accepted, deployed / bounded slice verified.

## Основание

S193 ordinary cron: corpus выбрал60 окон, обработал9 и завершился после
REGIONAL_REFRESH_REQUESTED. Приоритет исправно работает, но остаток выделенного
бюджета не используется до следующего15-minute tick. Это конкретный механизм
задержки; величина возможного выигрыша пока UNKNOWN.

## Решение

`server-eis-corpus.sh run` делегирует host-only stdlib runner. Остальные операции
сохраняют прежний wrapper. Внутри одного parent dispatch разрешено не более6
worker segments с суммарным исходным бюджетом1..60 attempted windows. Каждая
попытка расходует бюджет, включая NO_DATA и неудачу. Окна не равны HTTP-запросам.

Продолжение разрешено только после exact JSON contract существующего run_corpus:
exit2, BLOCKED, UNKNOWN coverage и один из двух cooperative reasons. Типы счётчиков,
их границы, status/reason/exit, набор полей, duplicate JSON keys проверяются.
При некорректном ответе учёт последнего segment UNKNOWN, новый worker не запускается.
Source/service/database/resource failure не получает автоматического retry.
`run` stdout — отдельный worker JSON на каждый segment; cumulative accounting
только в parent receipt. `plan/extend/status` остаются прежними single responses.

Собственный corpus dispatch lease запрещает дубликаты parent. После yield import
lease освобождается; runner ждёт без него. Для reacquisition кратко проверяет
regional и priority dispatch leases, затем import, освобождая обе dispatch leases
до начала worker. Владелец приоритетного marker успевает завершить работу и cleanup.
Runner не создаёт и не удаляет markers других lanes. При гонке с новым owner
worker снова уступает между atomic windows; segment count остаётся ограничен.

Horizon840s ограничивает ожидание и старт продолжений. **Это не wall-clock kill**:
начатый atomic window/segment может завершиться позже. TERM/INT прекращает ожидание
или запрещает продолжение после завершения активного worker. Нельзя обрывать
импорт архива ради соблюдения времени. Дубликат следующего tick вернёт75 пока
parent ещё работает; source concurrency, spacing, resource gates не меняются.

Каждый segment имеет собственный UUID и один существующий metrics cycle. Новый
tenant-scoped receipt связывает parent/segment UUID, aware UTC, output SHA256,
budget, attempted и причину остановки. Только whitelist metadata, без argv,
source payload, URL, credentials. JSONL0600, current2MiB+previous2MiB; no DB writes.
Ошибка сохранения обязательного receipt останавливает продолжение. Метрики optional.

## Проверка и границы

Linux real-flock process tests, fake Docker, network none: остаток бюджета,
priority ordering, duplicate dispatch, TERM, malformed/oversized output,
counter/exit spoofing, zero-progress segment bound, horizon и atomic completion.
Существующие metrics/other-lane lease regressions проверяются вместе.
Deployment script-only, rollback backup, неизменные images/cron/schema/resources.
Live receipt и cohort snapshot нужны для фактического эффекта. Полный ЕИС,
source completeness, national hourly freshness и throughput/SLA остаются UNKNOWN.

## Evidence результата

95Linux tests PASS08:13:43UTC/networknone, Ruff/mypy/bashsyntaxPASS;
atomic script-only rollout08:14:14UTC/host28hashPASS, images/cron/HEADunchanged.
Обычный cron08:15–08:27: parent60budget,13+26+21attempts после двухyields,
29SYNCED/31NO_DATA,563versions. Read-only gate563lexicalrows для563versions.
Parent/metrics/actualstdoutSHA/journal согласованы; полноценный917s observer
22complete/0censored/0inconsistent. MainOct2–4snapshot не изменился: pass обрабатывал
Oct1/Sep4. Подробные receipts/hashes/границы — [S194](../eis/ingestion/77-eis-corpus-bounded-continuation.md).
