# ADR-0042: одноразовый admission без подачи на площадку

Дата: 2026-09-21  
Статус: Accepted for the local pilot

## Контекст

S95 сохраняет exact команду и краткосрочное подтверждение, но чистая проверка
`Approval` не гарантирует одноразовость и не доказывает, что оригинальные файлы
по-прежнему соответствуют согласованным SHA-256. Адаптер конкретной ЭТП,
доверенный реестр адресов, персональная MFA и юридическая проверка способа
подачи ещё отсутствуют. Поэтому запись «заявка подана» недопустима.

## Решение

Выделить роль `APPLICATION_SUBMISSION_EXECUTOR` и immutable
`application-submission-admission-v1`. Исполнитель передаёт exact action ID,
payload SHA-256 и approval decision SHA-256. В одной tenant-scoped транзакции
сервер перечитывает S93–S95 evidence, заново проверяет действующий approval,
deadline, `PARTICIPATE` и floor, загружает каждый оригинал
`APPLICATION_ATTACHMENT`, пересчитывает SHA-256 его байтов и сверяет роль,
имя, MIME type и состав. Admission фиксирует размер и хеш каждого файла,
actor/time, digest решения и статус `ADMITTED_NO_DISPATCH`.

Один action ID может иметь только один admission. Уникальность, append-only
trigger, RLS/FORCE RLS, audit `application.submission_admitted` и idempotency
receipt делают claim атомарным и не допускают повторного использования при
другом idempotency key. GET повторно реконструирует admission из точного
approval и оригинальных байтов. Отдельный server-only executor token используется
только на маршруте admission; AUDITOR может читать, но не создавать claim.

## Последствия

Admission резервирует единственную попытку, но не подписывает и не отправляет
документы. `external_action_performed=false` обязателен. Истечение approval
после claim не даёт права начать сетевую передачу: будущий worker обязан снова
проверить время, deadline, цену и байты перед dispatch и зафиксировать
отдельный receipt результата. Если срок истёк до dispatch, claim остаётся
неизменяемым, а для новой попытки потребуется новый одобренный пакет/команда.
Тело запроса ЭТП может отличаться от внутренней команды; до отправки оно должно
получить собственное exact-payload approval. Реальная подача также требует
правовой проверки адаптера, allowlist площадки и персональной MFA. Локальный
BFF пока различает actor ID ключей, а не удостоверяет пользователя страницы.
