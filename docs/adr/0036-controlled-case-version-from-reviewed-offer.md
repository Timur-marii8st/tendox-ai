# ADR-0036: controlled case version из reviewed offer economics

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

После S88 существует immutable economics package с exact PASS offer, полным КП
и тремя сценариями, но исходный `ProcurementCase` не изменён. Импорт целого case
JSON позволил бы браузеру подменить quote, scenarios, assessment или итоговую
рекомендацию и разорвал бы цепочку evidence.

## Решение

Материализовать только следующую immutable версию существующего кейса серверной
командой. Запрос содержит `offer_id`, `economics_id` и `package_sha256`; tenant,
actor, source case version и idempotency задаются authenticated API boundary.
Repository повторно читает exact package и строит snapshot сам:

- selected quote переносится из reviewed commercial terms;
- `base`, `realistic`, `conservative` переносятся из economics package;
- technical `PASS` переносится из terminal PASS row-level offer review с его
  evidence и decision digest;
- остальные пять hard gates отсутствуют и остаются нерешёнными.

Новая версия, audit event и idempotency receipt записываются атомарно. Попытка
создать уже существующую следующую версию конфликтует; update существующей
версии не выполняется. Отдельная schema migration не нужна: используется
существующая append-only таблица `case_versions`.

## Последствия

Материализованная версия имеет полное КП и complete scenarios, но её partial
assessment содержит только technical gate. Существующий recommendation engine
возвращает `NEEDS_ANALYSIS` из-за отсутствующих legal, participant,
company-policy, logistics и document checks. Команда не запускает evaluation и
не может выдать `PARTICIPATE`. Следующий срез должен ввести exact workflow
актуализации оставшихся hard gates для нового input digest.
