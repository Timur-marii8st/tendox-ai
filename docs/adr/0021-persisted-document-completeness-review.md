# ADR-0021: Persisted review полноты одного native-документа

Дата: 2026-09-16  
Статус: принято

## Контекст

ADR-0018 ввёл типизированную оценку полноты, а ADR-0020 запретил положительный
document compliance без `completeness=PASS`. До этого решения mapping и review
существовали только в памяти процесса. Reviewer не мог доказуемо подтвердить,
какие именно bytes, extraction, правила mapping и непокрытые блоки он видел.

Принимать `FactMappingResult`, provenance или reviewer identity из браузера
нельзя: внешнее содержимое недоверенно, а решение должно быть tenant-scoped,
воспроизводимым и связано с точным evidence. Один server-side bearer в текущем
Next.js BFF также не является пользовательской сессией и не позволяет безопасно
смешивать operator и reviewer полномочия в одном публичном интерфейсе.

## Решение

Первый persisted-срез ограничен одним уже сохранённым native-документом с ролью
`TENDER_REQUIREMENTS`. OCR derivatives, ZIP, embedded media и объединение файлов
не повышаются до полноты этим workflow.

Оператор создаёт immutable review snapshot. Сервер загружает tenant-scoped
документ, повторно сверяет SHA-256 сохранённых bytes, использует сохранённый
`ExtractionResult` и сам выполняет текущий детерминированный mapping. Клиент не
передаёт extraction, requirements, текст блока или provenance.

Snapshot сохраняет:

- source document ID, SHA-256 и роль;
- полный extraction и server-derived mapping с `completeness=UNKNOWN`;
- версию mapper и порог confidence;
- canonical `evidence_sha256`, связывающий весь снимок;
- operator identity и timezone-aware время из bearer principal и сервера.

Отдельная роль `COMPLETENESS_REVIEWER` принимает единственное append-only
решение `PASS | FAIL | UNKNOWN`. Payload ссылается на точный `evidence_sha256` и
на позиции `unmapped`-блоков; сервер восстанавливает полные
`UnmappedBlockReview` из snapshot и повторно валидирует доменный контракт.
Reviewer identity, время и review reference задаются сервером. Self-review
запрещён. Исправление требует нового snapshot, старое решение не изменяется.
Для reviewed `UNKNOWN` reviewer metadata хранится в immutable decision, а
`FactMappingResult.completeness` остаётся исходным bare `UNKNOWN`: ему не
приписывается evidence положительного или отрицательного terminal gate.

`PASS` дополнительно требует успешного native extraction без unresolved reasons,
хотя бы одного `Requirement`, решения по каждому `unmapped` и отсутствия
`MATERIAL_REQUIREMENT`. `FAIL` требует точного material-блока. Недостаточное
evidence записывается как явный reviewed `UNKNOWN`, а не как допуск или
технический `FAIL`.

Snapshot, decision, audit event и idempotency receipt записываются в tenant
transaction. Таблицы имеют RLS/FORCE RLS, composite tenant foreign keys и
immutable UPDATE/DELETE triggers. Exact replay возвращает исходный результат;
изменённый replay, stale digest и конкурентное второе решение дают конфликт.
Чужой и отсутствующий ресурс неразличимы.

API среза:

- `POST /v1/documents/{document_id}/completeness-reviews` — operator создаёт
  snapshot;
- `GET /v1/completeness-reviews` и `GET /v1/completeness-reviews/{review_id}` —
  tenant-scoped чтение evidence и решения;
- `POST /v1/completeness-reviews/{review_id}/decision` — reviewer записывает
  терминальное решение по exact digest.

Server-rendered `/completeness-review` использует один server-only reviewer
token, `cache: no-store` и server actions. Token не попадает в HTML, RSC payload,
формы, URL или browser bundle. До появления session auth/RBAC/MFA этот экран
разворачивается отдельно как внутренний reviewer pilot; скрытый второй token в
общем operator BFF запрещён.

## Последствия

- Положительная полнота становится долговечным evidence, а не transient-флагом.
- Повторный review читает сохранённый snapshot и не пересчитывает исторический
  mapping новой версией кода.
- Discovery, completeness и compliance остаются разными утверждениями.
- Persisted `PASS` одного файла не доказывает полноту всего комплекта закупки и
  сам по себе не разрешает `PARTICIPATE`.
- Подключение review к case ingestion требует отдельного явного среза: нельзя
  автоматически выбирать «последний PASS» и игнорировать более поздний
  отрицательный или неизвестный review.
- Production multi-user authentication, OCR/ZIP evidence manifests и
  multi-document completeness остаются отдельными задачами.

## Отклонённые альтернативы

- Принимать готовый mapping из UI — отклонено: клиент мог бы удалить mandatory
  requirement или подменить provenance.
- Связывать решение только с SHA-256 source bytes — отклонено: mapping зависит
  также от роли, extraction, mapper version и threshold.
- Переиспользовать `MODEL_BRAND_REVIEWER` — отклонено: это иное полномочие.
- Хранить только последнее решение — отклонено: это разрушает audit и допускает
  незаметную замену ранее показанного evidence.
- Добавить reviewer credential в browser или выбирать server token параметром
  формы — отклонено как privilege escalation.
