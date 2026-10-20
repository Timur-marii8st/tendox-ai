# ADR-0016: Immutable model→brand official-source artifacts

Дата: 2026-09-16  
Статус: принято

## Контекст

Reviewed catalog из ADR-0015 сохранял SHA-256 официального документа, но сервер
не владел exact bytes и поэтому не мог повторно доказать digest при утверждении
model→brand entries. Одного заявленного URL и hash недостаточно для замыкания
доказательной цепочки.

## Решение

Вводится отдельный immutable tenant-scoped `model_brand_source_artifacts` для
PDF до 20 МиБ. Upload принимает PDF bytes, HTTPS source URL и title; tenant,
artifact ID, `retrieved_at` и `created_at` задаются сервером. Хранилище фиксирует
filename/media type/size/SHA-256/exact bytes. RLS/FORCE RLS, runtime
`SELECT/INSERT` и append-only trigger защищают версию.

`POST /v1/model-brand-source-artifacts` атомарно сохраняет artifact, audit
`model_brand.source_artifact_stored` и idempotency receipt. Exact replay
возвращает прежнюю метаинформацию, изменённый payload конфликтует. `GET
/v1/model-brand-source-artifacts/{artifact_id}` возвращает только tenant-visible
metadata, никогда не bytes.

Каждый catalog entry, сохраняемый через API, обязан иметь `source_artifact_id`.
В той же транзакции repository повторно вычисляет SHA-256 сохранённых bytes и
сверяет artifact ID, title, URL, digest и server retrieval time с evidence.
Отсутствующий, чужой или несовпадающий artifact одинаково отклоняет весь catalog.
Локальный CLI по-прежнему может читать legacy reviewed manifest без persisted ID,
но такой manifest нельзя сохранить через API до ingestion источника.

## Последствия

- persisted model→brand relation замкнута на exact tenant-owned bytes;
- подмена digest/title/URL/retrieval time не даёт сохранить catalog;
- исходный PDF не входит в публичные ответы и поисковую выдачу;
- upload доказывает неизменность принятых bytes, но не доказывает, что сервер сам
  получил их по заявленному URL; это остаётся ответственностью reviewer;
- полноценный review UI, роли/очередь согласования и автоматический разрешённый
  fetch официального URL остаются отдельными срезами.

## Альтернативы

- Хранить только hash в catalog JSON — отклонено: серверу нечего повторно
  хешировать.
- Использовать tender `documents` — отклонено: официальный справочник имеет иной
  жизненный цикл, metadata и audit purpose.
- Автоматически скачивать любой URL из payload — отклонено: SSRF, redirect,
  retention и allowlist policy ещё не определены.
