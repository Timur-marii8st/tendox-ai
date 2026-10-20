# ADR-0034: независимая построчная проверка server offer

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

`server-offer-proposal-v1` связывает exact sourcing lead, BOM и КП, но остаётся
операторской транскрипцией со статусом `UNKNOWN`. Общий checkbox соответствия не
показывает, какое требование подтверждает конкретная BOM-строка, и позволяет
пропустить manual rows либо коммерческие ограничения.

## Решение

Reviewer открывает один явный `offer_id` и получает в одном immutable evidence
bundle exact proposal и independently approved requirement set. Для каждой
исходной строки `1..N` обязательны `PASS | FAIL | UNKNOWN`, основание и ссылки на
`BOM_LINE` либо `COMMERCIAL_TERMS`; известный verdict без evidence запрещён.
Отдельно reviewer подтверждает полноту BOM и коммерческих условий.

Итог вычисляет сервер. Любой построчный `FAIL`, подтверждённо неполный BOM,
отклонённые terms, истёкшее КП или `covers_full_scope=false` дают `FAIL`. `PASS`
возможен только при PASS всех строк, полном BOM, подтверждённых terms и полном
действующем КП; остальные состояния дают `UNKNOWN`. Reviewer должен отличаться
от автора proposal.

Решение привязано к proposal SHA-256 и обоим digest requirement set. Оно
сохраняется один раз в tenant-scoped append-only таблице вместе с audit event и
idempotency receipt. Reviewer API использует роль `COMPLETENESS_REVIEWER`; BFF
имеет отдельный server-only token и не выбирает latest proposal.

## Последствия

Technical verdict теперь имеет воспроизводимую матрицу evidence и не может быть
назначен browser-клиентом. Даже `PASS` review ещё не создаёт экономические
сценарии и не переводит кейс в `PARTICIPATE`; это отдельный последующий срез.
