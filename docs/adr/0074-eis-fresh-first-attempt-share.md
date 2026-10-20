# ADR0074 — доля и порядок первых попыток свежих окон

Статус: DEPLOYED / VERIFIED BOUNDED SELECTION. Effective date: 2026-10-05. Owner root.

## Контекст

S192 проверил 1485 точных окон завершённых дат: за954s24 первых попытки,
23NO_DATA/1canonical; lexical rows не отстают от сохранённых версий.
Read-only selector limit60 выделял24new/36historical. Source workers могут
уступить lease до конца списка; прежний prefix после anchor/new включал
сначала все recent repairs и historical retries.

## Решение

При существующей активации daily lane (есть свежая завершённая дата без
попыток и обычный old anchor) увеличить new cap с ceil(2L/5) до ceil(3L/5).
Сначала old anchor, затем first new; остальные выбранные окна чередуются
пакетами3new/2other, сохраняя относительный порядок внутри этих двух списков.
Чередование применяется только если третье выбранное окно не fresh: при
отсутствии retry prefix сохраняется уже быстрый последовательный new block.
Other содержит прежние recent repair/historical retry/ordinary lanes в их порядке.
ДляL60 при достаточных очередях:36new, до12recentrepair, до3historicalretry,
9ordinaryold (включая anchor). Лимиты при маломL могут сократить new cap.
При исчерпании обычной очереди действует прежний work-conserving overflow.

Не меняются eligibility, latest-first, cooldown24h, canonical/tenant predicates,
worker max windows, source transport, lock/marker/resource policy, расписание
или NO_DATA semantics. Нет активации — прежний fallback. Limit1/2 unchanged.
Новый порядок не отменяет early-yield: гарантируется выбор и порядок, а не
выполнение всех окон, source capacity или полнота ЕИС.

## Последствия

При полном проходе появляется до50% больше мест для первых попыток; это
математическое изменение квоты, не обещание измеренного ускорения сервиса.
При ранней остановке свежие окна раньше представлены в prefix. История
получает anchor первым; исторический backlog имеет меньшую долю полного прохода.
Необходимы PG regression проверки всех предыдущих guards и live cohort report.
Возраст истории и свежей очереди остаётся предметом следующих измерений.

## Альтернативы

Дополнительные источниковые проходы/браузеры меняют нагрузку и общий lease contract.
Свежая очередь без old anchor может лишить историю продвижения при постоянном
early-yield. Изменение retriesNO_DATA является отдельной задачей с source evidence.

## Проверки и выпуск

27 unit +14 isolatedPG tests =41PASS07:22:26UTC; Ruff/mypy PASS.
Проверены доли/caps/overflow, old anchor, отсутствие cross-tenant interference,
latest tie identity, cooldown/canonical exclusions, unchanged row counts и early prefix.
Первый shadow обнаружил regression5->4fresh в first6 при пустых retry lanes;
conditional prefix устранил его. Final same-snapshot shadow24->36fresh/first6=5->5,
source0/DBwrites0, digest в docs76. Это selection evidence, не throughput SLA.
07:24:16UTC atomic9files, host25/API2/worker2 hashes PASS; pinned one-module
overlay без dependency changes, HEAD03/sourcecron/sourcecaps сохранены.
Live bounded observation и ограничения — [docs76](../eis/ingestion/76-eis-fresh-first-attempt-share.md).

967s ordinarycron:8newfirstattempts allNO_DATA,21->13unattempted, canonical/index
unchanged. Journal9attempts=1old/8new; regionalyield stdout9of60.
No measured throughput gain/1.5x speed claim. Nextbounded continuation must
retain original60-window budget; capacity/currentday/fullEIS remain UNKNOWN.
