# ADR-0115: подтверждение владельцем критичных настроек профиля

Статус: локальная реализация проверена; deployment и полный release gate не заявлены.
Дата: 2026-10-23.
Проверки и границы — [отчёт125](../operations/125-spec-remediation.md).

## Контекст

Профиль компании уже хранит immutable tenant-scoped версии, но production пока
сохраняет `OWNER_AUTHORIZATION_UNAVAILABLE`. Критичные финансовые лимиты,
площадки, методы, субподряд и запреты нельзя считать подтверждёнными только по
вводу пользователя или beta invitation. Нужен отдельный владелец компании,
который подтверждает exact normalized command; подтверждение должно сохранять
provenance и оставаться совместимым с legacy snapshot hash.

Локальный срез включает domain snapshot/command, storage/API и profile UI, а
`20261023_02_profile_owner` расширяет допустимую роль `COMPANY_PROFILE_OWNER` и
payload constraint. Его `down_revision` — `20261021_01`; интеграция с B11 head
`20261023_01` остаётся отдельной pending migration и требует explicit integration
перед combined rollout.

## Решение

1. Роль `COMPANY_PROFILE_OWNER` выдаётся только существующим admin bootstrap с
   owner connection. Пользователь и invitation runtime не могут самоназначить
   эту роль или изменить critical settings.
2. Сохранение связывает confirmation с tenant, exact actor, expected version и
   normalized command digest. Snapshot, command, confirmation, audit event и
   idempotency receipt сохраняются атомарно; версия immutable, legacy hashes
   остаются валидными.
3. Storage повторно проверяет command provenance: source hash, actor, tenant,
   changed paths, confirmation digest и соответствующий audit event. Несовпадение
   блокирует чтение/сохранение, а не переводится в PASS.
4. `prohibitions` остаётся unsupported и locked; его знание сохраняется как
   `UNKNOWN`. Подтверждение профиля не выдаёт A3 autonomy, permission на dispatch,
   участие или внешнее действие.

## Последствия

Получается проверяемая граница между обычным ручным вводом и подтверждением
критичной policy: exact actor/tenant/command можно восстановить из snapshot,
source и audit. До owner bootstrap production profile остаётся
`OWNER_AUTHORIZATION_UNAVAILABLE`; локальная проверка не является deployment
receipt. Для rollout требуется отдельное решение по миграционной цепочке и
новый release gate.

## Альтернативы

- Разрешить оператору или приглашению назначать владельца — отклонено: это
  ломает границу tenant/authority.
- Считать `KNOWN` достаточным без owner confirmation — отклонено: provenance и
  critical policy не подтверждены.
- Объединить миграции автоматически — отклонено: сначала нужен explicit review
  совместимости `20261021_01`/B11 `20261023_01` с `20261023_02`.
