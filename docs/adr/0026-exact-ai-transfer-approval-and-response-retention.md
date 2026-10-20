# ADR-0026: Exact approval внешней AI-передачи и retention ответа

- Статус: принято
- Дата: 2026-09-17

## Контекст

Preparation-only `ai-requirements-transfer-manifest-v1` фиксирует точные
OpenRouter request bytes, но намеренно не даёт права на отправку. Свободная строка
`authorization_reference` не доказывает human approval, а общий `ActionRequest`
требует `tender_id` и поэтому не подходит document-scoped передаче без
фиктивного идентификатора.

Существующие import-only AI reports содержат полный `response_content` внутри
immutable digest. Их нельзя использовать для server-managed запуска с удалением
raw через заданный срок: удаление нарушило бы evidence digest. Повтор сетевого
запроса после crash или timeout также может повторно передать ТЗ провайдеру.

Владелец продукта утвердил одноразовый exact-payload approval сроком 15 минут и
хранение полного ответа в защищённом зашифрованном blob не более 30 дней.

## Решение

Вводится отдельный document-scoped `persisted-ai-transfer-request-v1`. Сервер
строит его только из tenant-scoped persisted source bytes и extraction, повторно
проверяя SHA-256, роль `TENDER_REQUIREMENTS`, полный native extraction и
provenance. Request фиксирует:

- tenant, transfer и source identity/digests;
- reviewed model profile, endpoint, method и non-secret headers;
- `zdr=true`, `data_collection=deny`, `require_parameters=true`;
- запрет redirects/environment proxy;
- prompt/schema/chunking versions и digests;
- ordered chunks, exact canonical UTF-8 body и digest каждого body;
- bounded response capture;
- `RAW_RESPONSE_30_DAYS_V1` и
  `ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1`.

Digest request охватывает все эти поля и порядок, но никогда не содержит API key.
Preparation-only manifest не мутирует и не превращается в sendable artifact.

Отдельная роль `AI_TRANSFER_APPROVER` может создать единственный
`persisted-ai-transfer-approval-v1`. Approval связывает exact request digest,
tenant и transfer ID; approver не может быть preparer. `approved_at` назначает
сервер, `expires_at` равен ровно `approved_at + 15 минут`. Сравниваются UTC
instants, включая DST fold. Approval сам не отправляет данные и не является
execution receipt.

Исполнение допускается только как один ordered batch. Durable consumption и
dispatch claim записываются до сети. Перед каждым новым chunk повторно
проверяются exact bytes/digest и срок approval. Один chunk имеет не более одной
попытки: любой crash или timeout после claim означает `DELIVERY_UNKNOWN`,
останавливает batch и никогда не вызывает скрытый retry. Истечение approval между
chunks запрещает новые dispatches, но не мешает сохранить уже полученный ответ.

Server-managed result использует отдельную immutable схему без inline raw body.
Долгоживущие metadata содержат response/body/content digests, provider IDs,
safe outcome, candidates и blob reference. Полный bounded HTTP response
шифруется и хранится отдельно; доступ имеют только
`AI_REQUIREMENTS_REVIEWER` и `AUDITOR`, каждый доступ аудируется. Operator и
approver raw не читают.

Raw недоступен сразу при `expires_at`, равном `received_at + 30 дней`, даже если
cleanup задержался. Cleanup удаляет raw/key material атомарно и идемпотентно,
сохраняя metadata, digests, candidates, review и deletion receipt. Политика
backup/WAL/object versions обязана исключать восстановление доступного raw после
30 дней; до подтверждения этой инфраструктурной настройки production raw capture
не считается соответствующим retention policy.

## Реализация S48: local pilot boundary

S48 добавляет server-managed worker только для первого chunk: server revalidation
выполняется непосредственно перед сетью, после durable claim разрешён ровно один
call без retry/redirect. CLI dispatch по умолчанию выключен и требует
`AI_TRANSFER_LOCAL_PILOT_ENABLED=1`. Для local pilot может использоваться
`AI_TRANSFER_RAW_ROOT_KEK_B64` + `AI_TRANSFER_RAW_KEK_ID` через HKDF-derived
tenant KEK adapter; это не production KMS и не подтверждает key rotation.

Complete response хранится ровно 720 UTC-часов; execution detail раскрывает
reviewer/auditor только безопасные metadata/digests, а purge удаляет ciphertext
и wrapped DEK после immutable deletion receipt. Production capture остаётся
заблокирован до managed KMS/rotation и проверяемых backup/WAL/restore retention
evidence.

## Последствия

Положительное следствие: сервер сможет доказать, какие именно bytes были
одобрены и отправлены, не смешивая разрешение, сетевую попытку и аналитический
результат. Конкурентный replay не создаёт второе право отправки, а неопределённый
transport outcome остаётся `UNKNOWN`.

Approval и provider success не повышают document completeness. Candidates
остаются недоверенными предложениями, требуют независимого review и не создают
`Requirement`, `LineItem`, compliance result, sourcing input или право
`PARTICIPATE`.

Реализация выполняется последовательными срезами: persisted request/approval;
durable admission/claims и exact-byte transport; encrypted response storage и
retention реализованы bounded slice S47; server-managed review snapshot остаётся
следующей границей. Пока production tenant KEK provider и backup/WAL/restore
retention evidence не подтверждены, live external worker и production capture
остаются отключёнными, а их side effects не объявляются доступными.

## Отклонённые варианты

- Tenant-wide blanket permission: не связывает разрешение с конкретным текстом
  ТЗ, model/profile и privacy controls.
- Использовать общий `ActionRequest` с фиктивным `tender_id`: создаёт ложную
  доменную связь и ослабляет аудит.
- Пересобрать prompt/body при execution: отправленные bytes могут отличаться от
  одобренных.
- Автоматически повторить timeout/claim без receipt: может повторно передать ТЗ.
- Хранить raw внутри старого immutable report: делает 30-дневное удаление
  невозможным без разрушения digest.
- Удалять только строку `BYTEA`, игнорируя backup/WAL: не доказывает фактическое
  прекращение доступа к raw.
