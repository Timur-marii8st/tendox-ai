# ADR-0038: независимое решение об участии по exact evaluation

Дата: 2026-09-21  
Статус: Accepted for the local pilot

## Контекст

После S90 детерминированный engine может сохранить `PARTICIPATE` для полной
immutable case version. Рекомендация движка не должна автоматически становиться
решением человека, а внутреннее решение об участии не должно разрешать подачу
заявки. Между вычислением и review также могут истечь срок подачи или КП.

## Решение

Ввести отдельную роль `PARTICIPATION_APPROVER` и terminal decision по одной
persisted evaluation. Reviewer получает evidence envelope с tenant, case
version/input digest, engine version, полной рекомендацией, evaluator identity,
временем и content digest. Одобрять собственную evaluation запрещено.

Перед `APPROVED` repository в той же транзакционной операции перечитывает exact
case version и повторно запускает engine на текущее timezone-aware серверное
время. Текущий результат обязан оставаться `PARTICIPATE`. `REJECTED` можно
зафиксировать и при ухудшившемся результате, сохранив этот пересчёт как evidence.

Одна evaluation получает не более одного immutable решения. Decision, audit
event и idempotency receipt записываются атомарно в tenant-scoped таблицы под
RLS/FORCE RLS. Payload всегда содержит `external_action_authorized=false`.
Внешняя подача заявки требует отдельного exact-payload approval и в этот срез не
входит.

## Последствия

Положительный расчёт больше не выглядит как автоматически принятое решение.
Reviewer видит точные экономические показатели, причины и digest, а stale
evaluation не может получить `APPROVED`. Audit различает evaluator и approver.
Отдельный BFF использует только server-side participation token и повторно
читает evidence перед POST. Само решение не создаёт, не подписывает и не
отправляет заявку.
