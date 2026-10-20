# ADR-0023: Persisted review AI-кандидатов требований

Дата: 2026-09-17  
Статус: принят для import-only технического среза

## Контекст

`ai-requirement-analysis-v1` и `v2` являются типизированными отчётами внешней
модели, но до этого решения существовали только как локальные файлы. Внутренний
digest доказывает целостность самого файла, но не доказывает, что его evidence
по-прежнему совпадает с tenant-scoped документом и сохранённым extraction.
Подключать такой файл напрямую к `Requirement`, `LineItem`, compliance или
sourcing нельзя.

HTTP-запуск внешней модели также нельзя смешивать с обычным POST: повтор после
сбоя между external transfer и записью receipt может отправить ТЗ второй раз.
Свободная строка `authorization_reference` не является доказательством
exact-payload approval. Полный `response_content` может повторять текст ТЗ, а
production retention и круг доступа к нему пока не утверждены.

## Решение

Первый persisted-срез является **import-only**. Он принимает уже полученный
v1/v2 report как недоверенное предложение, повторно валидирует его схему и
digest и связывает с точными сохранёнными source bytes/extraction:

- tenant, document ID, роль, source SHA-256 и extraction SHA-256 совпадают;
- `b000001...` восстанавливаются сервером из полного extraction;
- текст и полный provenance каждого cited evidence block совпадают;
- chunk source/unresolved IDs принадлежат источнику, а union chunks покрывает
  полный extraction;
- v1 и v2 сохраняются без silent upgrade;
- импортированный отчёт помечается `IMPORTED_REPORT` и не представляется как
  вызов, выполненный сервером.

Snapshot immutable и tenant-scoped. Один независимый reviewer принимает
append-only решение по exact evidence digest. Каждый requirement/item candidate
получает ровно одну диспозицию `ACCEPTED`, `REJECTED` или
`NEEDS_CLARIFICATION` с основанием. Reviewer не может быть submitter. Значения и
evidence кандидата inline не редактируются; исправление требует нового
source-bound артефакта.

Review разрешён только для технически `COMPLETE` run. Complete run без
кандидатов может быть закрыт пустым решением, но это не доказывает отсутствие
требований. При любом количестве принятых кандидатов completeness остаётся
`UNKNOWN`; executable requirements, case recommendation и sourcing input не
создаются.

Persistence повторяет проверенный completeness-review pattern: actor-bound
idempotency, точный evidence digest в composite FK, append-only таблицы,
tenant RLS, атомарные receipt/audit/insert и одинаковое отсутствие чужого и
несуществующего ресурса. Автоматический выбор «последнего принятого» запрещён.

## Preparation-only дополнение

До решения отложенных продуктовых вопросов разрешён только чистый in-memory
`ai-requirements-transfer-manifest-v1`. Он не вызывает сеть и не создаёт право
на отправку. Manifest фиксирует точные canonical UTF-8 request bytes каждого
chunk, digests source/extraction/schema/prompt/request, reviewed model profile,
privacy controls, fixed endpoint/headers и no-proxy transport. Он всегда имеет
`APPROVAL_REQUIRED`, `send_allowed=false`, а approval/retention остаются
`UNRESOLVED`.

Manifest digest является идентификатором содержимого, но не approval,
idempotency key или execution receipt. Полные request bodies содержат текст ТЗ,
поэтому этот срез не сохраняет, не логирует и не отдаёт manifest через API.
Будущий executor обязан отправлять именно одобренные bytes, а не пересобирать их
из текущей версии prompt/schema/chunking. Для batch потребуются durable
per-chunk claims/receipts: timeout после dispatch означает `UNKNOWN`, а не
автоматический retry всего batch.

## Отложенные решения

До server-managed external run владелец продукта должен отдельно определить:

1. exact-payload approval или ограниченную tenant policy для передачи ТЗ,
   полномочия выдающего, срок действия и поля, связанные digest;
2. допустимость, срок хранения и роли доступа к полному provider
   `response_content`, либо отдельный защищённый immutable blob-контракт.

До этих решений API не отправляет документ внешнему провайдеру. Import-only
workflow не выдаёт новое разрешение на external transfer.

## Последствия

- Локальный пилот получает воспроизводимую границу между AI proposal и
  человеческим решением.
- Подмена source text/provenance обнаруживается даже при пересчитанном digest
  импортируемого report.
- Принятый candidate остаётся только reviewed claim и не обходит hard gates.
- Следующий отдельный срез может связать явно выбранные run/review IDs с case
  ingestion, но не имеет права выбирать их автоматически.
