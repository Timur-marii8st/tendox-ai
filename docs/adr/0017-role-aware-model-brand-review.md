# ADR-0017: Role-aware append-only model→brand review

Дата: 2026-09-16  
Статус: частично заменено ADR-0019 (публичный direct-import path удалён)

## Контекст

Artifact ingestion и reviewed catalog persistence замкнули доказательную цепочку,
но любой действующий bearer principal считался одинаковым. Нельзя строить review
UI, пока backend не отличает автора draft от лица, имеющего право принять
терминальное решение.

## Решение

API key получает persisted `access_role`: `OPERATOR` или
`MODEL_BRAND_REVIEWER`. Роль возвращает security-definer authentication function;
клиент не передаёт и не меняет её в payload. Старые и явно не размеченные ключи
мигрируют как `OPERATOR`. Bootstrap принимает `--access-role`.

`model_brand_review_proposals` и `model_brand_review_decisions` — две append-only
tenant-scoped таблицы с RLS/FORCE RLS. Отсутствие decision означает `DRAFT`;
единственная decision имеет `APPROVED` или `REJECTED`. Автор proposal не может
решить собственный draft, а decision endpoint требует
`MODEL_BRAND_REVIEWER`.

При submit repository повторно проверяет все source artifacts. При `APPROVED` он
ещё раз сверяет exact bytes/evidence и одной транзакцией создаёт catalog, decision,
audit events и idempotency receipt. `REJECTED` создаёт decision/audit/receipt, но
не catalog. Терминальное решение нельзя заменить; exact replay стабилен.

Прежний `POST /v1/model-brand-catalogs` временно сохранён как reviewer-only
compatibility/import path. Обычный управляемый путь — proposal/decision API.

## Последствия

- визуальное скрытие кнопки не заменяет backend authorization;
- operator может подготовить draft, но не опубликовать его;
- reviewer не может утвердить собственный draft;
- `REJECTED` никогда не становится searchable catalog;
- роли пока coarse-grained и принадлежат API key, а не production IAM group;
- reviewer UI и отдельная миграция legacy direct-import path остаются следующими
  срезами.

## Альтернативы

- Передавать role в теле запроса — отклонено как подмена authority.
- Хранить изменяемый status в proposal — отклонено: теряется исходный draft и
  терминальное решение.
- Разрешить self-approval reviewer — отклонено: не создаёт независимого review.
